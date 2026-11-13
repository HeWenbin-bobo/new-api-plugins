#!/usr/bin/env python3
"""Submit one document to a configured New API OCR task plugin.

Uses only the Python standard library. A successful submission pins the public
New API task ID: polling and downloads never create another task.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping

MODELS = (
    "mineru-pipeline-cpu",
    "paddleocr-vl-1.6-cpu",
    "hunyuanocr-1.5-cpu",
    "glm-ocr-cpu",
    "xiaomi-ocr-0-cpu",
    "minicpm-ocr-1.0-cpu",
    "ovisocr3-cpu",
)
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
PENDING = {"NOT_START", "SUBMITTED", "QUEUED", "IN_PROGRESS", "PENDING", "PROCESSING", "RUNNING"}
TERMINAL_FAILURES = {"FAILURE", "FAILED", "CANCELED", "CANCELLED", "REJECTED", "ERROR"}
SUCCESS = {"SUCCESS", "COMPLETED", "SUCCEEDED"}
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
ARTIFACT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
MAX_INPUT_BYTES = 50 * 1024 * 1024


class OCRError(RuntimeError):
    """An error safe to show without exposing a credential or document body."""


class TaskTimeout(OCRError):
    """The client stopped polling; it did not cancel the upstream task."""


def redact(text: object, secrets: tuple[str, ...] = ()) -> str:
    """Bound diagnostics and remove known credentials without showing them."""
    result = str(text)
    for secret in secrets:
        if secret:
            result = result.replace(secret, "<redacted>")
    result = re.sub(r"(?i)(bearer\s+|sk-)[A-Za-z0-9_\-.]{12,}", r"\1<redacted>", result)
    result = re.sub(r"(?i)([?&](?:access|token|key|signature|sig|x-amz-signature)=)[^&\s]+", r"\1<redacted>", result)
    return result[:400]


def finite_number(value: object, name: str, minimum: float, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OCRError(f"{name} must be a number") from exc
    if not math.isfinite(number) or number < minimum or (not allow_zero and number == minimum):
        qualifier = "nonnegative" if allow_zero else "positive"
        raise OCRError(f"{name} must be a finite {qualifier} number")
    return number


def normalize_base_url(value: object) -> str:
    """Validate a caller-owned gateway while preserving any path prefix."""
    if not isinstance(value, str) or not value.strip():
        raise OCRError("base_url is required; set it in config.json")
    candidate = value.strip()
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OCRError("base_url must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise OCRError("base_url must not contain credentials, a query or a fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise OCRError("base_url contains an invalid port") from exc
    return candidate.rstrip("/")


def endpoint(base_url: str, path: str) -> str:
    return f"{base_url}{urllib.parse.quote(path, safe='/:')}"


def load_configuration(path: Path | None = None) -> dict[str, Any]:
    config_path = path or Path(__file__).resolve().parents[1] / "config.json"
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise OCRError(f"Missing {config_path.name}; copy assets/config.example.json to config.json and fill api_key/base_url") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise OCRError(f"Cannot read configuration: {redact(exc)}") from exc
    if not isinstance(data, dict):
        raise OCRError("Configuration must be a JSON object")
    key = data.get("api_key", "")
    if not isinstance(key, str) or not key.strip():
        raise OCRError("api_key is required in the configuration file")
    return data


def validate_document(path_value: str | os.PathLike[str]) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise OCRError("Input document does not exist or is not a regular file")
    if path.suffix.lower() not in SUFFIXES:
        raise OCRError("Only PDF, PNG, JPEG and WebP documents are supported")
    size = path.stat().st_size
    if size == 0 or size > MAX_INPUT_BYTES:
        raise OCRError("Input document must be nonempty and no larger than 50 MiB")
    return path


def validate_task_id(value: object) -> str:
    if not isinstance(value, str) or not TASK_ID_RE.fullmatch(value):
        raise OCRError("New API did not return a valid public task ID")
    return value


def status_value(response: Mapping[str, Any]) -> str:
    status = response.get("status")
    if not isinstance(status, str):
        data = response.get("data")
        if isinstance(data, dict):
            status = data.get("status")
    if not isinstance(status, str) or not status.strip():
        raise OCRError("OCR task response has no status")
    return status.strip().upper()


def response_task_id(response: Mapping[str, Any]) -> str:
    for container in (response, response.get("data")):
        if isinstance(container, dict):
            for field in ("task_id", "id", "taskId"):
                if field in container:
                    return validate_task_id(container[field])
    raise OCRError("OCR submit response did not include a public task ID")


class NewAPIOCRClient:
    """A bounded same-origin client for the native Local Document OCR route."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30):
        self.base_url = normalize_base_url(base_url)
        self.api_key = api_key.strip()
        self.timeout = finite_number(timeout, "timeout", 0)
        if not self.api_key:
            raise OCRError("api_key is required")
        # Do not inherit system proxy settings for a configured local gateway.
        self.opener = urllib.request.build_opener(_SameOriginRedirectHandler(self.base_url), urllib.request.ProxyHandler({}))

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _json(self, path: str, method: str = "GET", data: bytes | None = None, content_type: str | None = None) -> dict[str, Any]:
        request = urllib.request.Request(endpoint(self.base_url, path), data=data, method=method, headers=self._headers(content_type))
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(MAX_JSON_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # Error bodies can contain request data. Never echo them wholesale.
            try:
                exc.read(4096)
            except OSError:
                pass
            raise OCRError(f"New API returned HTTP {exc.code} for {path}: {redact(exc.reason, (self.api_key,))}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise OCRError(f"New API request failed for {path}: {redact(exc, (self.api_key,))}") from exc
        if len(body) > MAX_JSON_BYTES:
            raise OCRError("New API JSON response exceeds 8 MiB")
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OCRError("New API returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise OCRError("New API JSON response must be an object")
        error = value.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("code") or "New API returned an error"
            raise OCRError(redact(message, (self.api_key,)))
        return value

    def submit(self, document: Path, model: str, quality: bool = False) -> str:
        if model not in MODELS:
            raise OCRError(f"model must be one of: {', '.join(MODELS)}")
        # Every OCR model gets page-level Jev scoring. MinerU additionally
        # emits block-level scores when its middle_json is available.
        document = validate_document(document)
        boundary = f"----local-document-ocr-{uuid.uuid4().hex}"
        mime_type = mimetypes.guess_type(document.name)[0] or "application/octet-stream"
        chunks: list[bytes] = []
        for name, value in (("model", model), ("quality", "true" if quality else "false")):
            chunks.extend([
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode(),
                value.encode("utf-8"), b"\r\n",
            ])
        # Avoid unquoted filenames containing quotes, backslashes or CRLF.
        if any(ord(char) < 32 for char in document.name) or any(char in '"\\' for char in document.name):
            raise OCRError("Input filename contains unsupported characters")
        chunks.extend([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{document.name}\"\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8"),
            document.read_bytes(), b"\r\n", f"--{boundary}--\r\n".encode(),
        ])
        response = self._json("/local-ocr/v1/parse", "POST", b"".join(chunks), f"multipart/form-data; boundary={boundary}")
        return response_task_id(response)

    def poll(self, task_id: str, poll_interval: float = 3, max_wait: float = 1800) -> dict[str, Any]:
        task_id = validate_task_id(task_id)
        poll_interval = finite_number(poll_interval, "poll_interval", 0, allow_zero=True)
        max_wait = finite_number(max_wait, "max_wait", 0)
        deadline = time.monotonic() + max_wait
        while True:
            try:
                response = self._json(f"/v1/tasks/{task_id}")
            except OCRError as exc:
                raise OCRError(f"Polling task {task_id} failed: {redact(exc, (self.api_key,))}") from exc
            try:
                status = status_value(response)
            except OCRError as exc:
                raise OCRError(f"Polling task {task_id} failed: {exc}") from exc
            if status in SUCCESS:
                return response
            if status in TERMINAL_FAILURES:
                reason = response.get("fail_reason") or response.get("error") or "OCR task failed"
                raise OCRError(f"OCR task {task_id} failed: {redact(reason, (self.api_key,))}")
            if status not in PENDING:
                raise OCRError(f"OCR task {task_id} returned unknown status {redact(status)}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TaskTimeout(f"Polling timed out for task {task_id}; the task was not canceled and may still be running")
            time.sleep(min(poll_interval, max(0, remaining)))

    def artifacts(self, task_id: str) -> list[dict[str, Any]]:
        task_id = validate_task_id(task_id)
        try:
            response = self._json(f"/v1/tasks/{task_id}/artifacts")
        except OCRError as exc:
            raise OCRError(f"Listing artifacts for task {task_id} failed: {redact(exc, (self.api_key,))}") from exc
        try:
            artifacts = response.get("artifacts")
            if not isinstance(artifacts, list):
                raise OCRError("New API artifact response has no artifacts array")
            valid = []
            for item in artifacts:
                if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not ARTIFACT_RE.fullmatch(item["key"]):
                    raise OCRError("New API returned an invalid artifact key")
                valid.append(item)
            return valid
        except OCRError as exc:
            raise OCRError(f"Listing artifacts for task {task_id} failed: {redact(exc, (self.api_key,))}") from exc

    def download(self, task_id: str, artifact: str, output: Path, overwrite: bool = False) -> Path:
        task_id = validate_task_id(task_id)
        if not ARTIFACT_RE.fullmatch(artifact):
            raise OCRError("artifact must be a simple New API artifact key")
        # Build the standard URL rather than trusting arbitrary content_url data.
        path = f"/v1/tasks/{task_id}/artifacts/{artifact}/content"
        request = urllib.request.Request(endpoint(self.base_url, path), headers={"Authorization": f"Bearer {self.api_key}"}, method="GET")
        output = output.expanduser()
        if output.exists() and not overwrite:
            raise OCRError(f"Output already exists: {output}; use --overwrite to replace it")
        output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".part", dir=output.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > MAX_DOWNLOAD_BYTES:
                            raise OCRError("Artifact exceeds the 256 MiB download limit")
                    except ValueError as exc:
                        raise OCRError("Artifact returned an invalid Content-Length") from exc
                with temporary.open("wb") as target:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        if target.tell() + len(chunk) > MAX_DOWNLOAD_BYTES:
                            raise OCRError("Artifact exceeds the 256 MiB download limit")
                        target.write(chunk)
                    target.flush()
                    os.fsync(target.fileno())
            try:
                if temporary.stat().st_size == 0:
                    raise OCRError("Downloaded artifact is empty")
                validate_download(temporary, artifact)
                if output.exists() and not overwrite:
                    raise OCRError(f"Output already exists: {output}; use --overwrite to replace it")
                os.replace(temporary, output)
            except (OCRError, UnicodeError) as exc:
                raise OCRError(f"Validating artifact for task {task_id} failed: {redact(exc, (self.api_key,))}") from exc
            return output
        except urllib.error.HTTPError as exc:
            raise OCRError(f"Artifact download for task {task_id} returned HTTP {exc.code}: {redact(exc.reason, (self.api_key,))}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise OCRError(f"Artifact download for task {task_id} failed: {redact(exc, (self.api_key,))}") from exc
        finally:
            temporary.unlink(missing_ok=True)


def validate_download(path: Path, artifact: str) -> None:
    """Validate downloaded bytes without extracting untrusted archive members."""
    if artifact == "package" or path.suffix.lower() == ".zip":
        if not zipfile.is_zipfile(path):
            raise OCRError("Downloaded package is not a valid ZIP")
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise OCRError("Downloaded ZIP has a corrupt member")
            for name in archive.namelist():
                candidate = Path(name)
                if candidate.is_absolute() or ".." in candidate.parts:
                    raise OCRError("ZIP contains an unsafe path")
    elif artifact == "json" or path.suffix.lower() == ".json":
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OCRError("Downloaded artifact is not valid JSON") from exc
        if not isinstance(value, (dict, list)):
            raise OCRError("JSON artifact must contain an object or array")
    else:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise OCRError("Downloaded Markdown is empty")


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never carry the New API key to another scheme/host/port."""

    def __init__(self, base_url: str):
        self.origin = urllib.parse.urlsplit(base_url)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        origin = (parsed.scheme, parsed.hostname, parsed.port)
        allowed = (self.origin.scheme, self.origin.hostname, self.origin.port)
        if origin != allowed:
            raise OCRError("Cross-origin artifact redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a PDF/image to a configured New API Local Document OCR channel")
    parser.add_argument("document", help="PDF, PNG, JPEG or WebP input")
    parser.add_argument("-o", "--output", default="ocr-result.md", help="Local output path (default: ocr-result.md)")
    parser.add_argument("--config", help="Configuration JSON path; default: skill-root/config.json")
    parser.add_argument("--base-url", help="Override configured New API base URL")
    parser.add_argument("--model", choices=MODELS, help="OCR model; default from configuration")
    parser.add_argument("--quality", action="store_true", help="Score pages with Jev for any model; MinerU also scores blocks; writes quality/quality_report artifacts")
    parser.add_argument("--artifact", default="markdown", help="Artifact key to download (default: markdown)")
    parser.add_argument("--timeout", type=float, help="Per-request timeout in seconds")
    parser.add_argument("--poll-interval", type=float, help="Polling interval in seconds")
    parser.add_argument("--max-wait", type=float, help="Maximum polling wait in seconds; does not cancel the upstream task")
    parser.add_argument("--overwrite", action="store_true", help="Atomically replace an existing output only after a valid download")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable success summary")
    return parser


def parse_document(args: argparse.Namespace) -> dict[str, Any]:
    config = load_configuration(Path(args.config).expanduser() if args.config else None)
    base_url = normalize_base_url(args.base_url or config.get("base_url", ""))
    model = args.model or config.get("model", MODELS[0])
    if model not in MODELS:
        raise OCRError(f"model must be one of: {', '.join(MODELS)}")
    if not ARTIFACT_RE.fullmatch(args.artifact):
        raise OCRError("artifact must be a simple New API artifact key")
    document = validate_document(args.document)
    output = Path(args.output).expanduser()
    if output.exists() and not args.overwrite:
        raise OCRError(f"Output already exists: {output}; use --overwrite to replace it")
    client = NewAPIOCRClient(base_url, config["api_key"], args.timeout if args.timeout is not None else config.get("timeout", 30))
    started = time.monotonic()
    task_id = client.submit(document, model, args.quality)
    # Once the ID exists, all subsequent failures are scoped to this task and
    # intentionally never trigger another submission.
    client.poll(task_id, args.poll_interval if args.poll_interval is not None else config.get("poll_interval", 3), args.max_wait if args.max_wait is not None else config.get("max_wait", 1800))
    available = client.artifacts(task_id)
    if args.artifact not in [item["key"] for item in available]:
        raise OCRError(f"Task {task_id} completed but artifact {args.artifact} is unavailable; available keys: {', '.join(item['key'] for item in available)}")
    path = client.download(task_id, args.artifact, output, args.overwrite)
    return {"base_url": base_url, "model": model, "quality": bool(args.quality), "task_id": task_id, "artifact": args.artifact, "path": str(path), "bytes": path.stat().st_size, "elapsed_seconds": round(time.monotonic() - started, 3)}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = parse_document(args)
    except OCRError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"Saved {result['artifact']} to {result['path']} ({result['bytes']} bytes)", file=sys.stderr)
        print(f"Task: {result['task_id']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
