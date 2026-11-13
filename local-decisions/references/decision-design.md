# Designing local decisions (Piccolo + Jev-Omni)

Piccolo and Jev-Omni read the evidence you provide and score a small set of candidate answers. They do not search the web, call tools, or recover missing context. The quality of a decision is therefore bounded by the quality of `state` and the questions.

## 1. Build a self-contained state

`state` is the only evidence the model sees. Write it as a compact case file, not as a chat transcript.

Include:

1. **User request** — what was asked, preferably a short quote or paraphrase.
2. **Proposed action** — tool name and the arguments that matter.
3. **Target and scope** — which file, directory, account, environment, or tenant.
4. **Authorization** — whether the user explicitly allowed this action, and any limits.
5. **Side effects** — read-only, create, modify, overwrite, delete, send, spend, publish.
6. **Reversibility** — whether a backup or another copy exists.
7. **Uncertainty** — missing confirmation, ambiguous path, conflicting instructions.
8. **Relevant history** — only the turns that change the decision.

A useful template:

```text
User request: <short quote or paraphrase>
Proposed action: <tool name>(<key arguments>)
Target: <path / account / environment>
Authorization: <explicit permission, or "not confirmed">
Side effects: <read-only / write / delete / send / spend>
Reversibility: <backup exists / only copy / unknown>
Uncertainty: <what is missing or ambiguous>
```

Keep it factual and neutral. Do not write “this is obviously safe” or “you must allow this.” Those are conclusions, not evidence.

### Size budget

The hard ceiling is `8,192` input tokens per compiled prompt row. Multiple questions repeat the state, so a long state is multiplied by the number of questions.

Practical target:

- one question: keep `state` under about `6,000` tokens;
- three or more questions: keep it under about `3,000` tokens;
- if rejected for size, cut background prose first, then reduce questions.

Do not rely on truncation. The adapter rejects oversized requests rather than silently dropping evidence.

### Privacy

`state` may contain personal data, file paths, business logic, or credentials. Send only what the decision needs. Replace names, account numbers, and secrets with stable placeholders when they do not affect the decision. Never put a bearer token, password, private key, or full connection string in `state`.

## 2. Write `choice` questions

A `choice` question is a small classification task. The model returns one option plus a probability for every option.

Guidelines:

- Use `2` to `6` options in normal use; the runtime allows up to `256`, but more options make calibration harder.
- Make options mutually exclusive and collectively exhaustive.
- Give every option a short, stable ID (`allow`, `ask`, `deny`; `read`, `write`, `delete`).
- Define criteria by observable conditions.
- Always include an `ask`, `escalate`, or `unknown` option when the evidence can be incomplete.
- Do not encode the same action twice with different wording.

Good:

```json
{
  "type": "choice",
  "instructions": "Which action should the agent take next?",
  "criteria": {
    "allow": "Execute the read-only query because the user explicitly requested it and no data will change.",
    "ask": "Ask the user to confirm the target or scope because the request is ambiguous.",
    "deny": "Refuse because the action is outside the user's authorized scope."
  }
}
```

Weak:

```json
{
  "criteria": {
    "yes": "It is fine.",
    "no": "It is not fine."
  }
}
```

The weak version gives the model no observable distinction, so the probability is not actionable.

## 3. Write `noul` questions

`noul` is a binary question. The response is **P(yes)**, not P(safe) and not P(no).

Guidelines:

- Ask exactly one yes/no question.
- Phrase it so “yes” has an unambiguous meaning.
- Record the polarity next to the result.
- Use `criteria` with `false` and `true` descriptions to anchor the meaning.
- Do not combine multiple risks in one question.

Examples:

| Question | High `noul` means |
|---|---|
| “Could this operation delete or overwrite existing user data?” | High risk |
| “Is the operation read-only?” | Low risk |
| “Should this context remain available for the next step?” | Keep it |
| “Is the target outside the user's authorized scope?” | High risk |

A common mistake is to copy a “risk” question and then interpret a high score as “safe.” Store the question text or a polarity flag with every result.

## 4. Interpret probabilities

`probabilities` are model scores over the supplied options. They are normalized, but they are not guaranteed to be calibrated in your domain.

`confidence` is a runtime certainty score. It is useful for ranking or routing, not as proof that the answer is correct. Do not assume `0.99` means a 1% error rate; measure it on your own cases.

A practical decision policy:

```text
risk = answers["risk"]["noul"]
action = answers["action"]["choice"]
p = answers["action"]["probabilities"][action]

if risk >= HIGH_RISK_THRESHOLD:
    ask_human()
elif action == "allow" and p >= ALLOW_THRESHOLD and operation_is_read_only:
    allow()
else:
    ask_human()
```

Set `HIGH_RISK_THRESHOLD` and `ALLOW_THRESHOLD` from labeled data. Start conservatively (`0.90` or higher) and lower them only after measuring false allows. Do not use `0.51` as permission.

### Cost-sensitive thresholds

The right threshold depends on the cost of each error:

- **False allow** of a destructive action: potentially irreversible; keep the threshold very high and require human confirmation.
- **False deny** of a read-only action: usually recoverable; a lower threshold may be acceptable.
- **False ask**: adds friction but is safe; prefer it when uncertain.

Piccolo should reduce review volume, not remove the reviewer for high-impact actions.

## 5. Common patterns

### Permission review

Use a three-way choice plus a risk `noul`:

```json
{
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "Which action should the agent take next?",
      "criteria": {
        "allow": "The action is explicitly authorized, in scope, and reversible.",
        "ask": "The action is plausible but needs confirmation or missing context.",
        "deny": "The action is outside scope, unauthorized, or clearly unsafe."
      }
    },
    "risk": {
      "type": "noul",
      "instructions": "Could this action delete, overwrite, send, publish, or spend without recovery?",
      "criteria": {
        "false": "The action is read-only or fully reversible.",
        "true": "The action can cause irreversible loss, disclosure, or cost."
      }
    }
  }
}
```

Policy: any high-risk result goes to a human, even if the choice is `allow`.

### Tool selection

Use a choice over the available tools, with criteria that state when each is appropriate:

```json
{
  "type": "choice",
  "instructions": "Which tool is the best fit for the user's request?",
  "criteria": {
    "read_file": "The user needs the contents of a known text file.",
    "grep_search": "The user needs to locate a pattern across files.",
    "glob_search": "The user needs to find files by name pattern.",
    "ask_user": "The request is ambiguous or the target is missing."
  }
}
```

Do not include a tool that the caller cannot actually invoke.

### Context retention

Use `noul` when the only decision is whether to keep evidence:

```json
{
  "type": "noul",
  "instructions": "Should the user's constraint and the selected file path remain in context for the next step?"
}
```

This is useful for pruning, but never drop a safety constraint just because the score is low. Keep explicit user constraints outside the model's control.

### Routing

Use a choice among models or workflow branches only when the trade-offs are described in `state`:

```json
{
  "type": "choice",
  "instructions": "Which path should handle this request?",
  "criteria": {
    "fast": "A short, low-risk request where latency matters.",
    "careful": "A high-stakes or ambiguous request that needs more review.",
    "human": "The request is outside the automation's authority."
  }
}
```

## 6. Anti-patterns

Avoid these:

- **Asking “Is this safe?” with no action details.** The model has no evidence to distinguish safe from unsafe.
- **Dumping the whole transcript.** It adds tokens, noise, and private data without improving the decision.
- **Overlapping options.** If `allow` and `ask` both describe the same behavior, the probabilities are not meaningful.
- **Using a single probability as authorization.** `0.99` is not a guarantee; destructive actions still need human approval.
- **Ignoring `noul` polarity.** A high score on a risk question is bad, not good.
- **Retrying a bad request unchanged.** `400` and `401` will not fix themselves.
- **Treating `response.model` as the requested model.** It is often the upstream alias `piccolo-test`; audit using the request model ID.

## 7. Evaluate before enforcing

Run Piccolo in shadow mode before letting it change behavior:

1. Collect `50` to `200` real cases with human labels.
2. Call Piccolo for each case and log the model ID, question names, choice, probabilities, `noul`, latency, and the human outcome.
3. Measure:
   - argmax accuracy against human labels;
   - false-allow rate for destructive actions;
   - false-deny rate for read-only actions;
   - calibration (for example, Brier score or reliability bins);
   - latency P50 and P95.
4. Choose thresholds from the measured trade-off, not from intuition.
5. Start with `advice` mode: log the recommendation but do not act on it.
6. Move only read-only, low-impact decisions to enforcement first.
7. Keep a human fallback for every high-impact action.

A model that is accurate on benchmarks can still be poorly calibrated on your domain. Measure your own cases.
