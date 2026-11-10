---
name: local-document-ocr
description: Use when a downstream agent needs to submit a PDF or document image to a New API Local Document OCR task channel, choose MinerU or PaddleOCR-VL, poll an asynchronous OCR task, and download Markdown, JSON or ZIP artifacts.
---

# Local Document OCR

Submit **one PDF, PNG, JPEG or WebP** through a configured New API Local Document OCR channel. Use this for document-to-Markdown, formula extraction to LaTeX, structured JSON, and downloadable result packages. This is OCR routing, not general-purpose chat or mathematical reasoning.

## Configure before calling

Copy `assets/config.example.json` to `config.json` in the Skill root and set:

- `api_key`: the caller's ordinary New API user token;
- `base_url`: the caller's New API gateway, including any required path prefix;
- `model`: `mineru-pipeline-cpu` or `paddleocr-vl-1.6-cpu`.

Optional timing fields are `timeout`, `poll_interval`, and `max_wait`. Do not put real credentials in the example file, source, ZIP, logs or replies. Do not invent a channel ID or endpoint. The configured New API must already have the OCR task plugin and channel enabled.

## Run

From the Skill directory:

```bash
# Submit a document and download Markdown.
python scripts/parse.py paper.pdf -o result.md

# Select PaddleOCR-VL explicitly.
python scripts/parse.py scan.png --model paddleocr-vl-1.6-cpu -o result.md

# Select structured JSON or a complete ZIP package.
python scripts/parse.py paper.pdf --artifact json -o result.json
python scripts/parse.py paper.pdf --artifact package -o result.zip

# Override configuration or print a machine-readable delivery summary.
python scripts/parse.py paper.pdf --config /private/ocr.json --base-url https://gateway.example -o result.md
python scripts/parse.py paper.pdf --json -o result.md
```

Use the script's absolute path from another working directory if needed. On Windows use `python` or `py` as appropriate. Runtime requires Python 3.9+ and only the standard library.

### Important options

| Option | Meaning |
|---|---|
| `-o`, `--output` | Local result path; default `ocr-result.md` |
| `--artifact` | Artifact key such as `markdown`, `json`, `package`, or an engine-specific key listed by the gateway |
| `--model` | Select exactly one supported OCR model; no automatic model fallback |
| `--config` | Read a caller-owned configuration JSON instead of the Skill-root `config.json` |
| `--base-url` | Override only the configured New API base URL |
| `--timeout` | Positive per-request seconds |
| `--poll-interval` | Nonnegative seconds between status checks |
| `--max-wait` | Positive maximum client polling seconds; does not cancel the upstream task |
| `--overwrite` | Replace an existing output only after a complete, validated download |
| `--json` | Emit a success summary with model, task ID, artifact, local path, bytes and elapsed time |

## Model selection for this deployment

**在当前这台无 NVIDIA GPU、Intel Xeon E5-2690 v2 的 CPU 机器上，长文档默认推荐 MinerU；PaddleOCR-VL 建议用于少量页面或对照路线。** The default configuration therefore uses `mineru-pipeline-cpu`. On a different GPU or CPU, reassess the choice with a small real document rather than treating this as a universal accuracy or performance ranking.

Measured with the same real 15-page public paper *Attention Is All You Need* through this Skill:

- MinerU: **105.364 seconds total**, about **7.02 seconds/page**, with richer heading structure and structured artifacts. Prefer it for long documents on this host.
- PaddleOCR-VL: **2261.908 seconds total**, about **150.79 seconds/page** (about 2 minutes 31 seconds/page). Use it for a small number of pages or as a comparison route, not unattended long-document batches on this host.

These are timing observations, not claims that every formula is recognized perfectly. Inspect the actual document's formulas, superscripts, matrices and LaTeX output.

## Safety and failure behavior

1. Validate configuration, input file, output path and parameters before submission.
2. Submit with `POST /local-ocr/v1/parse` using multipart `model` and `file`.
3. Once New API returns a public task ID, **never submit the same request again**. Poll only `GET /v1/tasks/{task_id}`.
4. Continue for known queued/running states. Stop on SUCCESS/completed or an explicit failed/cancelled state. Unknown statuses are errors, not success.
5. Read `GET /v1/tasks/{task_id}/artifacts` and download the selected artifact from the standard same-origin content path. Do not follow arbitrary artifact URLs or forward keys cross-origin.
6. A poll, artifact-listing or download failure is not an empty successful result. Preserve the task ID in the error, including application errors and downloaded-format validation failures; do not claim the task was cancelled or create a second task.
7. Download to a temporary sibling file, validate nonempty Markdown/JSON or a safe CRC-checked ZIP, then atomically rename. Failure preserves an existing output unless the caller explicitly chose `--overwrite` and a valid replacement is ready.
8. Redact credentials and signed URL query values from errors. Do not print document bytes or Base64.

A downloaded result proves delivery, not OCR accuracy. Review formulas, superscripts, matrices, table structure and LaTeX rendering. Long PDFs can take substantial time on CPU; set a realistic `--max-wait` rather than retrying submission.

## Validate and package

Run offline tests from the Skill root:

```bash
python -m unittest discover -s evals -p 'test_*.py' -v
```

The tests use local fake HTTP services and no real credentials. Package only `SKILL.md`, `scripts/`, `assets/config.example.json`, `assets/minimal.png`, and `evals/`; never include `config.json`, generated outputs, caches or logs. Test the exact clean ZIP before uploading it.
