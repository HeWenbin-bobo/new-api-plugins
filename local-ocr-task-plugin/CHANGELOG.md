# Changelog

## 0.1.7

- Reserve the 100-page maximum before every task-expression submission, without trusting caller-supplied page counts, filenames or MIME metadata; completion still uses the task service's actual pages.

## 0.1.0

- Initial private asynchronous OCR task service for MinerU 4.1.7 Basic and PaddleOCR-VL-1.6 GGUF.
- New API Task Plugin API v1 driver with JSON/multipart submission, polling, page usage and document artifacts.
- CPU-only Docker images, including an Intel Ivy Bridge-compatible llama.cpp build.
- Fixed upstream allowlist, internal authentication, validation and retention defaults.

## 0.1.1

- Add initial and completion page usage for per-page task pricing.

## 0.1.2

- Stream multipart documents without Base64 expansion; correct completion usage context handling.

## 0.1.3

- Accept the generic task driver's requestBody/files context; forward opaque file references as Base64 JSON without inline placeholder objects.

## 0.1.4

- Return progress as a percentage string, artifact type file, and native task model name.

## 0.1.5

- Support public task_id view and persisted upstream_task_id for artifact downloads.

## 0.1.6

- Prefer the persisted upstream task id for artifact content lookup.
