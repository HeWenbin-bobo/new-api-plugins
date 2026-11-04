# jihuarst-video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create an independent `jihuarst-video` Agent Skill that submits text/image-to-video tasks to the four jihuarst gateways, polls them, downloads an MP4, and falls back across two approved models.

**Architecture:** One Python standard-library CLI owns validation, request construction, asynchronous polling, safe download, and URL-first fallback. A loopback HTTP server tests the complete flow without real credentials or paid generation. Documentation and an allowlisted ZIP make the Skill distributable without local secrets.

**Tech Stack:** Python 3.9+, `argparse`, `urllib`, `unittest`, `http.server`, `zipfile`; no runtime dependencies.

## Global Constraints

- Default model order is exactly `minimax-video-h3`, then `kling-video-v3`; no other CLI model is accepted.
- URL order is exactly `http://222.211.75.198:3000`, `https://gz-api.jihuarst.top:8443`, `https://api.jihuarst.top`, `https://sg-api.jihuarst.top`; exhaust both models at one URL before switching.
- Use `POST /v1/videos` and `GET /v1/videos/{id}`; never treat failed, pending, unknown, or empty responses as success.
- `-r` accepts one existing non-empty local image and sends it as an `input_reference` data URL.
- Never print credentials or image bytes. Do not forward the gateway key to a different origin, including across redirects.
- Save via a same-directory temporary file and atomic replacement; failed attempts leave no new target.
- Tests must be offline and use temporary fake keys and loopback servers.
- Do not add the Skill to `index.json`; do not commit or push without an explicit user request.
- Preserve all unrelated existing working-tree edits.

---

### Task 1: Submission, polling, and fallback

**Files:**
- Create: `jihuarst-video/scripts/generate.py`
- Create: `jihuarst-video/tests/test_generate.py`

**Interfaces:**
- Produces: `BASE_URLS: list[str]`, `MODELS: list[str]`, `load_api_key() -> str`, `redact_secrets(text: str, api_key: str) -> str`.
- Produces: `_build_submit_request(base_url: str, model: str, prompt: str, api_key: str, seconds: float, size: str | None, reference: str | None) -> urllib.request.Request`.
- Produces: `_poll_task(base_url: str, task_id: str, api_key: str, timeout: float, poll_interval: float, max_wait: float) -> dict`.
- Produces: `generate_video(...) -> GenerationResult`; download is isolated behind `_download_video(...)` so Task 2 can implement it without changing submission logic.

- [x] **Step 1: Write failing loopback tests for request and model order**

Create tests whose handler records JSON POSTs and returns either HTTP 500 or `{"id":"task-1","status":"queued"}`. Add these concrete cases:

```python
def test_declared_priorities(self) -> None:
    self.assertEqual(EXPECTED_URLS, self.module.BASE_URLS)
    self.assertEqual(["minimax-video-h3", "kling-video-v3"], self.module.MODELS)

def test_text_request_uses_openai_video_contract(self) -> None:
    request = self.module._build_submit_request(
        "http://127.0.0.1:9", "minimax-video-h3", "cat", "test-key", 5, "1280x720", None
    )
    self.assertEqual("http://127.0.0.1:9/v1/videos", request.full_url)
    self.assertEqual({"model": "minimax-video-h3", "prompt": "cat", "seconds": "5",
                      "size": "1280x720"}, json.loads(request.data))

def test_reference_is_sent_as_input_reference_data_url(self) -> None:
    reference = self.module._reference_data_url(self.ref)
    self.assertTrue(reference.startswith("data:image/png;base64,"))
    request = self.module._build_submit_request(
        "http://127.0.0.1:9", "minimax-video-h3", "move", "test-key", 5, None, reference
    )
    self.assertEqual(reference, json.loads(request.data)["input_reference"])
```

These request-builder tests inspect the serialized request directly and perform no network I/O.

- [x] **Step 2: Add failing state and fallback tests**

```python
def test_exhausts_models_before_switching_url(self) -> None:
    with fake_api([500]) as (first, first_url), fake_api([200]) as (second, second_url):
        with self.assertRaises(RuntimeError):
            self.module.generate_video("cat", self.output, "test-key", [first_url, second_url],
                                       timeout=2, poll_interval=0, max_wait=2)
    self.assertEqual(EXPECTED_MODELS, [r["payload"]["model"] for r in first.requests])

def test_poll_does_not_resubmit(self) -> None:
    with fake_api([200], task_statuses=["queued", "processing", "failed"]) as (server, url):
        with self.assertRaises(RuntimeError):
            self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                       timeout=2, poll_interval=0, max_wait=2)
    self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))
    self.assertEqual(2, len([r for r in server.requests if r["method"] == "GET"]))
```

Also test empty prompt, non-positive/non-finite seconds, missing/empty reference, invalid timeout/wait values, unknown status, terminal failure, max-wait expiry, and redaction of `sk-test-secret` and the exact configured key.

- [x] **Step 3: Run tests and confirm RED**

Run from `jihuarst-video/`:

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: collection or execution fails because `scripts/generate.py` and its functions do not yet exist. No external network calls are allowed.

- [x] **Step 4: Implement minimal submission and polling**

Implement constants and a frozen result DTO:

```python
BASE_URLS = ["http://222.211.75.198:3000", "https://gz-api.jihuarst.top:8443",
             "https://api.jihuarst.top", "https://sg-api.jihuarst.top"]
MODELS = ["minimax-video-h3", "kling-video-v3"]

@dataclass(frozen=True)
class GenerationResult:
    base_url: str
    model: str
    task_id: str
    path: Path
```

Build JSON with `seconds` serialized as a string; add `size` only when supplied and `input_reference` only for image mode. Encode a reference with `base64.b64encode` and a MIME type inferred from the filename. Submit with bearer authentication, require a non-empty string `id`, and URL-encode that ID in the poll path.

Map statuses as follows:

```python
PENDING = {"queued", "pending", "submitted", "processing", "in_progress", "running"}
SUCCESS = {"completed", "succeeded"}
FAILURE = {"failed", "rejected", "cancelled", "lost"}
```

Poll the same task while pending, sleeping `poll_interval` between requests and stopping when `time.monotonic() - started >= max_wait`. Raise explicit errors for failure and unknown statuses. Return the completed response dictionary. Outer fallback catches sanitized HTTP/network/JSON/task errors, records one bounded summary per combination, and only raises unavailable after all selected combinations fail.

- [x] **Step 5: Run Task 1 tests**

Run the same unittest command. Expected: submission, validation, polling, redaction, and fallback tests pass; tests requiring actual MP4 download remain red until Task 2. Do not claim the full suite passes at this checkpoint.

---

### Task 2: Safe MP4 download and CLI

**Files:**
- Modify: `jihuarst-video/scripts/generate.py`
- Modify: `jihuarst-video/tests/test_generate.py`
- Create: `jihuarst-video/config.example.json`

**Interfaces:**
- Consumes: completed task dictionaries from `_poll_task(...)`.
- Produces: `_download_video(url: str, output_path: Path, api_key: str, base_url: str, timeout: float) -> Path`.
- Produces: `main(argv: Iterable[str] | None = None) -> int` and `_build_parser() -> argparse.ArgumentParser`.

- [x] **Step 1: Write failing download and CLI tests**

Use an 8+ byte fake MP4 payload whose bytes 4–7 are `ftyp`, for example:

```python
MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00jihuarst-test"
```

Add loopback cases for:

```python
def test_remote_video_download_does_not_receive_api_key(self) -> None:
    with fake_api([200], remote_video=True) as (server, url):
        result = self.module.generate_video("cat", self.output, "test-key", [url],
                                            ["minimax-video-h3"], timeout=2,
                                            poll_interval=0, max_wait=2)
    self.assertEqual(MP4_BYTES, self.output.read_bytes())
    self.assertIsNone(server.download_authorization)
    self.assertEqual("task-1", result.task_id)

def test_non_mp4_is_not_saved(self) -> None:
    with fake_api([200], remote_video=True, download_body=b"<html>error</html>") as (server, url):
        with self.assertRaises(RuntimeError):
            self.module.generate_video("cat", self.output, "test-key", [url],
                                       ["minimax-video-h3"], timeout=2,
                                       poll_interval=0, max_wait=2)
    self.assertFalse(self.output.exists())
```

Also cover HTTP(S) redirect success, non-HTTP redirect rejection, cross-origin redirect authorization stripping, same-origin `/content` fallback, failed download fallback to the next model, preservation of a pre-existing output on failure, CLI `--model`/`--base-url`, invalid CLI model rejection, `--json` success fields, and non-zero CLI failure status.

- [x] **Step 2: Run focused tests and confirm RED**

```bash
PYTHONIOENCODING=utf-8 python -m unittest tests.test_generate.GenerateTests.test_remote_video_download_does_not_receive_api_key -v
```

Expected: FAIL because download/result handling is not implemented.

- [x] **Step 3: Implement streaming download and atomic save**

Choose the completed response's non-empty `url`; resolve relative URLs against the gateway. If absent, use `/v1/videos/{quoted-id}/content`. Build a request without credentials for a cross-origin URL. Use a redirect handler that permits only HTTP(S) and removes `Authorization` whenever the redirect target origin differs.

Stream the response to `tempfile.NamedTemporaryFile(dir=output.parent, delete=False)`. Validate `first_chunk[4:8] == b"ftyp"` before creating the final output, copy the remainder with `shutil.copyfileobj`, close successfully, then `os.replace(temp_name, output_path)`. On every exception, close the response and unlink only the temporary file. Do not put response bodies in logs.

- [x] **Step 4: Implement the CLI and empty example config**

Create exactly:

```json
{"api_key": ""}
```

Add arguments `prompt`, `-o/--output` (default `jihuarst-video.mp4`), `-r/--ref`, `--seconds` (default `5`), `--size`, `--timeout` (default `30`), `--poll-interval` (default `5`), `--max-wait` (default `1800`), `--model` (choices `MODELS`), `--base-url`, and `--json`. Keep informational logging on stderr; success JSON contains `base_url`, `model`, `task_id`, and `path`. Return 1 on expected generation errors and 0 only after a complete MP4 has replaced the output.

- [x] **Step 5: Run the full offline suite**

```bash
PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
```

Expected: `OK`, zero failures/errors/skips, and all HTTP traffic confined to `127.0.0.1`. Record the final test count from the actual summary.

---

### Task 3: Skill documentation, repository integration, and distributable ZIP

**Files:**
- Create: `jihuarst-video/SKILL.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Generate but do not track: `jihuarst-video/config.json`
- Generate and track after archive safety review: `jihuarst-video/jihuarst-video.zip`

**Interfaces:**
- Consumes: the exact Task 2 CLI and test command.
- Produces: an installable Skill directory and a ZIP containing only `SKILL.md`, `config.example.json`, `scripts/generate.py`, and `tests/test_generate.py`.

- [x] **Step 1: Write documentation matching implemented behavior**

Document both calls with exact commands:

```bash
python scripts/generate.py "一只猫在阳光下的窗边伸懒腰，镜头缓慢推进" --seconds 5 -o out.mp4
python scripts/generate.py "人物自然转头，镜头缓慢推进" -r photo.png --seconds 5 -o out.mp4
```

List the four URLs and two models in their actual order, the asynchronous endpoints, polling/deadline options, cost implication of fallback after submission, the plaintext first gateway warning, and the fact that live gateway behavior is not proven by offline tests. Add client installation paths and the offline test command. Do not copy image-only claims or parameters.

Update root README and AGENTS from four projects/two Skills to five projects/three Skills, add the new documentation, test, and ZIP paths, and leave `index.json` untouched. Inspect existing diffs first and make focused edits that preserve unrelated changes.

- [x] **Step 2: Copy local config without exposing it and verify ignore rules**

Copy `jihuarst-image/config.json` to `jihuarst-video/config.json` using a file operation that never prints its contents. Verify:

```bash
git check-ignore -v jihuarst-video/config.json jihuarst-video/jihuarst-video.zip
git ls-files jihuarst-video
```

Expected: the generated private config is ignored; the reviewed ZIP is intentionally visible for tracking after the repository's archive-distribution policy change. `git ls-files` lists only source, tests, example config, documentation, and the reviewed ZIP. Do not print or compare credential values in output.

- [x] **Step 3: Generate and independently inspect the ZIP**

Use Python `zipfile` with the explicit four-file allowlist, fixed portable `/` entry names, and no parent directory entries. Extract into a new temporary directory, run its offline tests with `PYTHONIOENCODING=utf-8`, compare every archived file byte-for-byte with current source, and assert no extra entries. Confirm the archive contains no `config.json`, cache, local state, or nested archive.

- [x] **Step 4: Run final offline verification and audits**

Run from the repository root and new Skill directory as appropriate:

```bash
cd jihuarst-video && PYTHONIOENCODING=utf-8 python -m unittest discover -s tests -v
node --test .githooks/check-push.test.js
git diff --check
git status --short
```

Expected: both test suites exit 0; inspect their actual final summaries. Verify README local links and JSON example parsing. Inspect changed files for `TODO`, `test.skip`, `.only`, stubs, and unimplemented branches. Report exact test counts and any unrun live test separately.

- [x] **Step 5: Request authorization before any paid live generation**

User explicitly requested actual testing of both models after the initial offline delivery. Live scope used HTTPS, one forced model per run, five seconds, and no size. The resulting completed tasks could not be downloaded; record the blocker rather than presenting them as successful MP4 tests.

Before live generation, state the selected URL/model, exact prompt or reference image path, `seconds`, `size`, and that the prompt/key/media leave the machine. Ask for confirmation of the smallest useful paid test. If declined or cost cannot be established, stop after offline verification and report live generation as unverified rather than claiming end-to-end success.
