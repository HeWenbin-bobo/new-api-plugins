# Repository Maintenance and Organization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Save the current project handoff, clarify repository organization, and preserve lessons from the moejs Task Plugin release without moving or republishing product artifacts.

**Architecture:** Use focused documentation edits in the existing four ownership surfaces plus this design/plan pair. Product source, tests, package versions, index entries, and allowlisted archives remain untouched.

**Tech Stack:** Markdown, Git ignore metadata, offline Python/Node/Git validation.

## Global Constraints

- Keep all six product trees and all six exact client ZIP paths unchanged.
- `CLAUDE.md` must remain exactly `@AGENTS.md`.
- Do not commit, tag, push, move local inputs, or make paid API calls.
- New documents must not contain placeholders or claim unperformed verification.

---

### Task 1: Correct and extend repository documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `docs/PROJECT_STATUS.md`
- Create: `docs/superpowers/specs/2026-11-06-repository-maintenance-organization-design.md`
- Create: `docs/superpowers/plans/2026-11-06-repository-maintenance-organization.md`

**Interfaces:**
- Consumes: existing publication, verification, and document-ownership rules.
- Produces: an accurate handoff and durable moejs/release maintenance guidance; no executable API changes.

- [x] Add moejs no-`URL` coverage and restricted URL validation requirements to `AGENTS.md` without duplicating Panel's existing COS policy.
- [x] Add version-scoped handling for user-tested ZIPs and live reports, exact Git-blob packaging on Windows, and correct GitHub tree/blob comparison.
- [x] Keep the README block rooted at the repository and transition directly between sibling product directories with `cd ../<project>`; use the documented UTF-8 Python test invocations.
- [x] Change the `.gitignore` allowlist comment to six reviewed client distributions.
- [x] Add a dated documentation-organization handoff to `PROJECT_STATUS.md`, with actual verification added only after it runs.

### Task 2: Verify the focused documentation change

**Files:**
- Inspect: the six files above and `git status --short --branch`.

**Interfaces:**
- Consumes: the completed documentation edits.
- Produces: evidence of valid links, commands, index hashes, archive invariants, and local-input isolation.

- [x] Run `git diff --check` and inspect the complete diff for placeholders, contradictions, and unrelated changes.
- [x] Parse `index.json`, compare both source hashes, and verify that no plugin, ZIP, package version, or `CLAUDE.md` content changed.
- [x] Resolve local Markdown links in changed documentation and check README test directory transitions from a simulated repository-root shell.
- [x] Verify that the six allowlisted ZIPs remain tracked and the root DOCX plus `video_wb2api_hub_newapi/workbuddy-video-hub-current-20261106.zip` and `video_wb2api_panel_newapi/workbuddy-panel-video-current-20261106.zip` remain untracked/ignored without printing local configuration values.
- [x] Run an independent documentation review, disposition all findings, and record any unverified scope in the final report. Independent review passes requested corrections to the publication date, current test snapshot, design/plan scope, README fail-fast behavior, and status wording. All reported findings were corrected and rechecked locally. A fresh final verifier then approved the documentation-only scope with zero blockers; the unresolved image/video test failures remain explicitly recorded as separate maintenance work.
- [x] Leave the changes uncommitted and unpushed.

## Verification result

- Documentation checks and push-guard tests (38/38) passed; the corrected README directory transitions reached all five product test suites.
- Hub (20/20), Panel (18/18), and MCP (85/85) passed. The full Jihuarst Image suite did not pass: its first run reported 1 failure/4 errors and its second 1 failure/1 error, with local `WinError 10048` port conflicts; five initial failures passed individually but do not establish a green full suite.
- Jihuarst Video reported 2 failures. The unknown-status case passed individually. The terminal-task fallback case observed zero submissions in the full run and one in a targeted run, rather than the expected two. Independent diagnosis confirmed that this mock hardcodes the submission status to `queued`, its first poll selects `failed`, and `TaskTerminalError` permits fallback; that path does not explain why the second submission was not observed. Current evidence does not establish whether the source or fixture violates the intended contract. No product or test source was changed in this documentation-only task.
- Independent socket tracing located the image `WinError 10048` failures in outbound `socket.create_connection()` before HTTP bytes were sent; no confirmed cross-process conflicting four-tuple was captured. The evidence does not generalize that socket diagnosis to the video terminal-task assertion. The later test-only in-memory transport repair and its verification are recorded separately in `docs/PROJECT_STATUS.md`, not in this documentation-only plan.
- New API marketplace installation and final live moejs behavior remain outside this maintenance pass.
