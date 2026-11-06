# Repository Maintenance and Organization Design

**Date:** 2026-11-06

## Goal

Preserve the published six-product layout while making document ownership, local-input boundaries, and the latest Task Plugin maintenance lessons explicit.

## Approved scope

1. Keep all six top-level product directories, `index.json` paths, historical project documents, and the six allowlisted client ZIPs in place. Do not create parallel source or archive locations.
2. Treat `AGENTS.md` as the durable maintenance guide, root `README.md` as the user/install entry point, and `docs/PROJECT_STATUS.md` as the dated handoff and verification snapshot. Existing `docs/superpowers/specs/` and `plans/` remain the homes for repository-wide design and implementation records.
3. Correct the README's offline-test directory transitions with one continuous sibling-directory sequence from the repository root, so each command runs from its owning project directory. Correct the `.gitignore` comment from five to six allowlisted archives.
4. Record durable lessons from the moejs compatibility release: do not assume host URL constructors; cover submission, polling, and content retrieval with no-`URL` tests; preserve restricted channel parsing and Panel COS isolation; validate compressed IPv6 and ports; treat user-tested archives and reports as version-scoped evidence rather than authoritative source replacements.
5. Clarify exact-source packaging and Windows checkout byte comparison, plus the distinction between a Git commit ID, its root tree ID, and recursive API tree/blob entries.
6. Leave the local DOCX and both `video_wb2api_hub_newapi/workbuddy-video-hub-current-20261106.zip` and `video_wb2api_panel_newapi/workbuddy-panel-video-current-20261106.zip` inputs in place and unpublished. Add an exact root ignore rule for the DOCX, which was untracked but not previously ignored; both ZIPs are already ignored by the archive rule. Do not modify plugin behavior, package versions, index metadata, or distributable ZIPs.
7. Do not commit or push this maintenance pass without separate user authorization.

## Verification

Validate the complete documentation diff, JSON parsing and unchanged plugin hashes, local Markdown links, documented test directory transitions, six ZIP invariants, ignored local inputs, and working-tree safety. The minimum for a documentation-only change is the set of static checks in `AGENTS.md`; the optional full offline suite was also run here and its actual failures are recorded in `PROJECT_STATUS.md`, not converted into a passing claim. No paid or live marketplace validation is implied.
