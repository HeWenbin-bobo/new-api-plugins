---
name: local-document-ocr
description: Use when a downstream agent needs to submit a PDF or document image to a New API Local Document OCR task channel, choose among seven self-hosted OCR models, optionally score pages with Jev for every model (and blocks for MinerU), poll an asynchronous OCR task, and download Markdown, JSON or ZIP artifacts.
---

# Local Document OCR

Submit **one PDF, PNG, JPEG or WebP** through a configured New API Local Document OCR channel. Use this for document-to-Markdown, formula extraction to LaTeX, structured JSON, and downloadable result packages. This is OCR routing, not general-purpose chat or mathematical reasoning.

## Configure before calling

Copy `assets/config.example.json` to `config.json` in the Skill root and set:

- `api_key`: the caller's ordinary New API user token;
- `base_url`: the caller's New API gateway, including any required path prefix;
- `model`: one of the seven supported models:
  `mineru-pipeline-cpu`, `paddleocr-vl-1.6-cpu`, `hunyuanocr-1.5-cpu`,
  `glm-ocr-cpu`, `xiaomi-ocr-0-cpu`, `minicpm-ocr-1.0-cpu`, `ovisocr3-cpu`.

Optional timing fields are `timeout`, `poll_interval`, and `max_wait`. Do not put real credentials in the example file, source, ZIP, logs or replies. Do not invent a channel ID or endpoint. The configured New API must already have the OCR task plugin and channel enabled.

## Run

From the Skill directory:

```bash
# Submit a document and download Markdown.
python scripts/parse.py paper.pdf -o result.md

# Select PaddleOCR-VL explicitly.
python scripts/parse.py scan.png --model paddleocr-vl-1.6-cpu -o result.md

# MiniCPM-OCR 1.0: strong on Chinese text and display formulas, tables as plain text.
python scripts/parse.py scan.pdf --model minicpm-ocr-1.0-cpu -o result.md

# Page-level Jev quality for any model (opt-in; dense pages can take 2-3 min each).
python scripts/parse.py scan.png --model minicpm-ocr-1.0-cpu --quality --artifact quality -o quality.json

# MinerU adds block-level localization on top of page-level quality.
python scripts/parse.py paper.pdf --quality -o result.md
python scripts/parse.py paper.pdf --quality --artifact quality -o quality.json

# Quality scoring is slow on CPU; raise the client polling limit for long runs.
python scripts/parse.py paper.pdf --quality --max-wait 7200 --artifact quality -o quality.json

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
| `--quality` | Score pages with Jev for any model; MinerU also scores blocks; adds `quality` and `quality_report` artifacts |
| `--config` | Read a caller-owned configuration JSON instead of the Skill-root `config.json` |
| `--base-url` | Override only the configured New API base URL |
| `--timeout` | Positive per-request seconds |
| `--poll-interval` | Nonnegative seconds between status checks |
| `--max-wait` | Positive maximum client polling seconds; does not cancel the upstream task |
| `--overwrite` | Replace an existing output only after a complete, validated download |
| `--json` | Emit a success summary with model, task ID, artifact, local path, bytes and elapsed time |

## Model selection for this deployment

**在当前这台无 NVIDIA GPU、Intel Xeon E5-2690 v2 的 CPU 机器上，长文档默认推荐 MinerU。** The default configuration therefore uses `mineru-pipeline-cpu`. All OCR inference is serialized by the gateway and capped at 10 threads per active model on this host.

Measured on this host:

- MinerU: **105.364 seconds total** for a real 15-page paper, about **7.02 seconds/page**; produces structured artifacts and is the long-document default.
- PaddleOCR-VL: **2261.908 seconds total**, about **150.79 seconds/page**; use for a small number of pages or comparison.
- MiniCPM-OCR 1.0: about **132 seconds/page** for one 1240×1754 page at 10 threads; good Chinese text and display formulas, but tables degrade to space-aligned plain text in page mode.

The other models (`hunyuanocr-1.5-cpu`, `glm-ocr-cpu`, `xiaomi-ocr-0-cpu`, `ovisocr3-cpu`) are quality/format comparison routes; check their output on a few real pages before using them for a batch.

These are timing observations, not claims that every formula is recognized perfectly. Inspect the actual document's formulas, superscripts, matrices and LaTeX output.

## Quality scoring with Jev

`--quality` works with all seven OCR models. The gateway sends the original page image and the rendered OCR page text to MiniCPM-OCR Jev, then records a consistency probability. The two scopes coexist:

- **Every model, page-level:** `quality.json.page_quality.pages[]` has one entry per scored page (`prob`, `chars`, `chars_scored`, `truncated`, `seconds`, optional `error`); `page_quality.summary` has `pages_total`, `pages_scored`, `pages_skipped`, `failed`, `low_confidence`, `mean_prob`, `truncated` and timing.
- **MinerU extra, block-level:** when `middle_json.json` is present, `quality.json.pages[].blocks[]` adds per-block `prob`, `bbox`, `type`, `category` and `chars`, and the top-level `summary` aggregates blocks. This is the only route that localizes a low-confidence region.
- `quality.json.scope` is `page` for VLM routes and `page+block` for MinerU.
- `quality_report` is a Markdown view: a page table for every model, plus a block table when MinerU block scoring is present.

For VLM routes the `package` ZIP also contains `quality.json` and `quality_report.md`. For MinerU they are separate artifacts alongside the raw upstream package.

Page scoring is capped at `JEV_PAGE_QUALITY_MAX_PAGES` pages (default 10) and `JEV_PAGE_MAX_CHARS` characters per page (default 12000). MinerU block scoring is capped at `JEV_MAX_BLOCKS` blocks (default 80). When a cap is hit, `truncated` is true and `pages_skipped` or page `truncated` shows where. Dense pages can take roughly 2-3 minutes each on this CPU host; margin cropping helps sparse pages but does not make dense pages cheap. Block scoring adds roughly 8-30 s/block. Use a generous `--max-wait` (for example 7200 seconds) for quality runs.

A high page score means the rendered page text is broadly consistent with the page image. It is not proof of correctness and cannot identify a wrong line. Use MinerU block scores for localization. Tables and LaTeX are rendered as literal text, so their scores are conservative. A per-page Jev error is recorded in `error` and does not turn a successful OCR task into a failure.

## Safety and failure behavior

1. Validate configuration, input file, output path and parameters before submission.
2. Submit with `POST /local-ocr/v1/parse` using multipart `model`, `file` and the optional `quality` flag; `quality=true` is valid for every supported model.
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
