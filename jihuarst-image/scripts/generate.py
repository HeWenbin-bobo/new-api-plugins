#!/usr/bin/env python3
"""Generate or edit images through every configured jihuarst URL/model combination.

Supports two server modes:

* ``/v1/images/generations`` -- text-to-image (JSON body).
* ``/v1/images/edits``       -- image-to-image / reference guided editing
  (multipart body, one or more ``image`` parts, optional ``mask``).

Every URL is tried in turn; within a URL every model is tried; the first
combination that returns a usable image wins.  Only the Python standard
library is required at runtime and for the offline tests.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import http.client
import ipaddress
import json
import logging
import mimetypes
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

BASE_URLS = [
    "http://222.211.75.198:3000",
    "https://gz-api.jihuarst.top:8443",
    "https://api.jihuarst.top",
    "https://sg-api.jihuarst.top",
]
GPT_MODELS = ["gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2"]
MODELS = [*GPT_MODELS, "hunyuan-image-alpha"]
EDIT_MODELS = [*GPT_MODELS, "hunyuan-image-alpha-edit"]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
LOGGER = logging.getLogger("jihuarst-image")
SECRET_PATTERN = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]+\b")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{4,}={0,2}")
# Upstream errors can echo credentials embedded in URLs or request payloads.
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|authorization|credential)"
    r"(\s*[=:]\s*|\s*\"\s*:\s*\")([^\s&,\"'}]{4,})"
)

# The upstream silently raises any request below this pixel budget to a
# 1254x1254 default.  Verified against the live gateway: 1024x1024 and
# 512x512 both came back as 1254x1254, while 1024x1536 / 1536x1024 were kept.
MIN_HONOURED_PIXELS = 1254 * 1254
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_COUNT = 10
MAX_TOTAL_IMAGE_BYTES = 256 * 1024 * 1024
# The decoded ceiling is 64 MB, so the base64 text can never exceed ~86 MB.
MAX_ENCODED_IMAGE_CHARS = 4 * (MAX_IMAGE_BYTES // 3 + 2)
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
MAX_ERROR_BODY_BYTES = 64 * 1024
MAX_REFERENCE_BYTES = 64 * 1024 * 1024

ENDPOINT_GENERATIONS = "/v1/images/generations"
ENDPOINT_EDITS = "/v1/images/edits"


class _ImageDownloadError(RuntimeError):
    """Image retrieval failed for one entry of an already-paid response."""


class _PaidDeliveryError(RuntimeError):
    """The generation was paid for, but its artifacts could not be delivered.

    Terminal: falling through to another URL/model would pay for a new generation.
    """


class _HTTPOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def _validate_redirect(self, req: urllib.request.Request, newurl: str) -> None:
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme.lower() not in {"http", "https"}:
            raise _ImageDownloadError("图片重定向仅支持 HTTP(S)")
        if old.scheme.lower() == "https" and new.scheme.lower() == "http":
            raise _ImageDownloadError("图片重定向不允许从 HTTPS 降级到 HTTP")

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str,
        headers: Any, newurl: str,
    ) -> urllib.request.Request | None:
        try:
            self._validate_redirect(req, newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
        finally:
            # Do not let urllib drain an untrusted, potentially endless redirect body.
            fp.close()


class _SameOriginRedirectHandler(_HTTPOnlyRedirectHandler):
    def _validate_redirect(self, req: urllib.request.Request, newurl: str) -> None:
        super()._validate_redirect(req, newurl)
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        old_origin = (
            old.scheme.lower(), old.hostname,
            old.port or (443 if old.scheme.lower() == "https" else 80),
        )
        new_origin = (
            new.scheme.lower(), new.hostname,
            new.port or (443 if new.scheme.lower() == "https" else 80),
        )
        if old_origin != new_origin:
            raise _ImageDownloadError("生成接口重定向仅允许同源 HTTP(S)")


def _resolved_addresses(hostname: str, port: int,
                        allow_private: bool = False) -> list[str]:
    """Resolve once, rejecting non-public results unless explicitly testing locally."""
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if address not in addresses:
            addresses.append(address)
    if not allow_private and any(
        not address.is_global or address.is_multicast or address.is_reserved
        for address in addresses
    ):
        raise _ImageDownloadError("图片地址仅允许公网 HTTP(S)")
    return [str(address) for address in addresses]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to a validated numeric address, not a second DNS resolution."""

    allow_private_addresses = False

    def connect(self) -> None:
        addresses = _resolved_addresses(
            self.host, self.port, self.allow_private_addresses,
        )
        last_error: OSError | None = None
        for address in addresses:
            try:
                self.sock = socket.create_connection(
                    (address, self.port), self.timeout, self.source_address,
                )
                if self._tunnel_host:
                    self._tunnel()
                return
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError("图片地址没有可用 IP")


class _PinnedHTTPSConnection(_PinnedHTTPConnection, http.client.HTTPSConnection):
    def connect(self) -> None:
        super().connect()
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host,
        )


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    connection_class = _PinnedHTTPConnection

    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(self.connection_class, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    connection_class = _PinnedHTTPSConnection

    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(self.connection_class, req, context=self._context)


def _build_image_opener(allow_private: bool = False) -> urllib.request.OpenerDirector:
    class HTTPConnection(_PinnedHTTPConnection):
        allow_private_addresses = allow_private

    class HTTPSConnection(_PinnedHTTPSConnection):
        allow_private_addresses = allow_private

    http_handler = _PinnedHTTPHandler()
    http_handler.connection_class = HTTPConnection
    https_handler = _PinnedHTTPSHandler()
    https_handler.connection_class = HTTPSConnection
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _HTTPOnlyRedirectHandler,
        http_handler, https_handler,
    )


_IMAGE_OPENER = _build_image_opener()
_GENERATION_OPENER = urllib.request.build_opener(_SameOriginRedirectHandler)


@dataclass(frozen=True)
class GenerationResult:
    """Outcome of a successful generation attempt."""

    base_url: str
    model: str
    endpoint: str
    paths: tuple[Path, ...]
    revised_prompt: str | None = None


def redact_secrets(text: str, api_key: str) -> str:
    """Remove the configured key and common token-shaped strings from errors."""
    redacted = SECRET_PATTERN.sub("[REDACTED]", text)
    redacted = BEARER_PATTERN.sub("Bearer [REDACTED]", redacted)
    redacted = ASSIGNMENT_PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", redacted)
    if api_key:
        redacted = redacted.replace(api_key, "[REDACTED]")
    return redacted


def load_api_key() -> str:
    """Read the key from the skill-local config without exposing it in logs."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 {CONFIG_PATH}: {exc}") from exc
    api_key = config.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError(f"{CONFIG_PATH} 中缺少有效的 api_key")
    return api_key.strip()


def _detect_mime(path: Path) -> str:
    """Best-effort MIME type for a reference image."""
    guess, _ = mimetypes.guess_type(path.name)
    if guess and guess.startswith("image/"):
        return guess
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "application/octet-stream")


def _read_reference(path: Path) -> tuple[str, bytes, str]:
    """Return (field_name_source, bytes, mime) for one reference image."""
    if not path.is_file():
        raise ValueError(f"参考图不存在: {path}")
    if path.stat().st_size > MAX_REFERENCE_BYTES:
        raise ValueError(f"参考图超过大小上限: {path}")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取参考图 {path}: {type(exc).__name__}") from exc
    if not data:
        raise ValueError(f"参考图为空文件: {path}")
    if len(data) > MAX_REFERENCE_BYTES:
        raise ValueError(f"参考图超过大小上限: {path}")
    return path.name, data, _detect_mime(path)


def _multipart_body(
    fields: dict[str, str],
    files: Sequence[tuple[str, str, bytes, str]],
) -> tuple[bytes, str]:
    """Build a multipart/form-data body from text fields and file parts."""
    boundary = "----jihuarst" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode("utf-8")
        )
    for field, filename, payload, mime in files:
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
            f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8")
        )
        chunks.append(payload)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _build_request(
    base_url: str,
    model: str,
    prompt: str,
    api_key: str,
    count: int,
    references: Sequence[Path],
    mask: Path | None,
    size: str | None,
    quality: str | None,
    input_fidelity: str | None,
) -> tuple[urllib.request.Request, str]:
    """Construct the HTTP request for either the edits or generations mode."""
    # multipart parts are strings, but the JSON body must keep native types:
    # the Go gateway rejects a string "n" with `cannot unmarshal string into uint`.
    common: dict[str, str] = {"model": model, "prompt": prompt, "n": str(count),
                              "response_format": "b64_json"}
    if size:
        common["size"] = size
    if quality:
        common["quality"] = quality

    if references:
        if input_fidelity:
            common["input_fidelity"] = input_fidelity
        files: list[tuple[str, str, bytes, str]] = []
        if len(references) == 1:
            filename, payload, mime = _read_reference(references[0])
            files.append(("image", filename, payload, mime))
        else:
            for reference in references:
                filename, payload, mime = _read_reference(reference)
                files.append(("image[]", filename, payload, mime))
        if mask is not None:
            if len(references) != 1:
                raise ValueError("mask 只能与单张参考图一起使用")
            filename, payload, mime = _read_reference(mask)
            files.append(("mask", filename, payload, mime))
        body, content_type = _multipart_body(common, files)
        request = urllib.request.Request(
            base_url.rstrip("/") + ENDPOINT_EDITS,
            data=body,
            headers={"Content-Type": content_type, "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        return request, "edits"

    payload: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "n": count,
        "response_format": "b64_json",
    }
    if size:
        payload["size"] = size
    if quality:
        payload["quality"] = quality
    request = urllib.request.Request(
        base_url.rstrip("/") + ENDPOINT_GENERATIONS,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    return request, "generations"


def _validate_image_bytes(raw: bytes) -> None:
    if len(raw) > MAX_IMAGE_BYTES:
        raise _ImageDownloadError("图片响应过大")
    has_signature = raw.startswith((
        b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a",
    )) or (len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
    if not has_signature:
        raise _ImageDownloadError("图片响应不是支持的图片")


def _decode_base64_image(encoded: str) -> bytes:
    """Decode one base64 entry, bounding its size before allocating."""
    if encoded.startswith("data:"):
        if "," not in encoded:
            raise _ImageDownloadError("图片 data URL 缺少分隔符")
        encoded = encoded.split(",", 1)[1]
    compact = "".join(encoded.split())
    if len(compact) > MAX_ENCODED_IMAGE_CHARS:
        # Checked before decoding so an oversized payload cannot expand in memory.
        raise _ImageDownloadError("图片响应过大")
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _ImageDownloadError("图片 base64 内容无效") from exc


def _decode_images(
    result: dict,
    timeout: float,
    max_images: int,
    max_total_bytes: int = MAX_TOTAL_IMAGE_BYTES,
) -> tuple[list[bytes], list[str]]:
    """Return ``(images, failures)`` for at most ``max_images`` response entries.

    Failures are collected rather than raised: the caller decides whether the
    paid response is still usable.  Unusable entries are never silently dropped
    -- an entry with no image payload is reported too.
    """
    if not isinstance(result, dict):
        raise ValueError("API 响应必须是 JSON 对象")
    entries = result.get("data") or []
    if not isinstance(entries, list):
        raise ValueError("API 响应的 data 必须是数组")
    images: list[bytes] = []
    failures: list[str] = []
    total_bytes = 0
    for index, item in enumerate(entries[:max_images]):
        try:
            if not isinstance(item, dict):
                raise _ImageDownloadError("图片条目格式无效")
            url = item.get("url", "")
            encoded = item.get("b64_json") or (url if isinstance(url, str) and url.startswith("data:") else "")
            if encoded:
                if not isinstance(encoded, str):
                    raise _ImageDownloadError("图片 base64 字段必须是字符串")
                raw = _decode_base64_image(encoded)
            elif isinstance(url, str) and urllib.parse.urlsplit(url).scheme.lower() in {"http", "https"}:
                # Signed image URLs need no gateway credentials; never forward the API key.
                try:
                    with _IMAGE_OPENER.open(url, timeout=timeout) as response:
                        raw = response.read(MAX_IMAGE_BYTES + 1)
                except _ImageDownloadError:
                    raise
                except urllib.error.HTTPError as exc:
                    exc.close()
                    raise _ImageDownloadError("图片下载失败") from None
                except Exception as exc:
                    raise _ImageDownloadError("图片下载失败") from exc
            else:
                raise _ImageDownloadError("图片条目缺少可用的 url 或 b64_json")
            _validate_image_bytes(raw)
            if not raw:
                raise _ImageDownloadError("图片内容为空")
            if total_bytes + len(raw) > max_total_bytes:
                raise _ImageDownloadError("图片总大小超过上限")
            total_bytes += len(raw)
            images.append(raw)
        except _ImageDownloadError as exc:
            failures.append(f"第 {index + 1} 张图片: {exc}")
    return images, failures


def _output_targets(output_path: Path, count: int) -> list[Path]:
    """Return one path per requested image, adding a numeric suffix when needed."""
    if count <= 1:
        return [output_path]
    stem, suffix = output_path.stem, output_path.suffix
    return [output_path.parent / f"{stem}-{index}{suffix}" for index in range(1, count + 1)]


def _write_images_atomically(targets: Sequence[Path], images: Sequence[bytes]) -> list[Path]:
    """Write each image to a sibling temporary file, then replace its target.

    A failed write never truncates or removes a previously saved image.  When
    several images are requested, a target is replaced only once its complete
    content has been flushed to disk.
    """
    saved: list[Path] = []
    for image_bytes, target in zip(images, targets):
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=target.name + ".", suffix=".tmp", delete=False,
            ) as temporary:
                temp_name = temporary.name
                temporary.write(image_bytes)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_name, target)
            temp_name = None
            saved.append(target)
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name)
                except FileNotFoundError:
                    pass
    return saved


def generate_image(
    prompt: str,
    output_path: Path,
    api_key: str,
    base_urls: Sequence[str] = BASE_URLS,
    models: Sequence[str] | None = None,
    timeout: float = 180.0,
    count: int = 1,
    references: Sequence[Path] = (),
    mask: Path | None = None,
    size: str | None = None,
    quality: str | None = None,
    input_fidelity: str | None = None,
) -> GenerationResult:
    """Try models within each URL, returning after the first saved image."""
    if not prompt.strip():
        raise ValueError("提示词不能为空")
    if not api_key.strip():
        raise ValueError("API key 不能为空")
    if not 1 <= count <= MAX_IMAGE_COUNT:
        raise ValueError(f"生成数量必须在 1..{MAX_IMAGE_COUNT} 之间")
    # Local input problems must fail fast, before any paid request: retrying
    # them across every URL/model would only repeat the same error and cost money.
    for reference in references:
        _read_reference(reference)
    if mask is not None:
        if len(references) != 1:
            raise ValueError("mask 只能与单张参考图一起使用")
        _read_reference(mask)

    errors: list[str] = []
    selected_models = models if models is not None else (EDIT_MODELS if references else MODELS)
    total = len(base_urls) * len(selected_models)
    attempt = 0
    for base_url in base_urls:
        for model in selected_models:
            attempt += 1
            LOGGER.info("尝试 %d/%d: %s | %s", attempt, total, base_url, model)
            try:
                request, endpoint = _build_request(
                    base_url, model, prompt, api_key, count,
                    list(references), mask, size, quality, input_fidelity,
                )
                with _GENERATION_OPENER.open(request, timeout=timeout) as response:
                    response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise ValueError("生成接口响应过大")
                result = json.loads(response_body.decode("utf-8"))
                entries = result.get("data") or [] if isinstance(result, dict) else []
                if not isinstance(entries, list):
                    raise _PaidDeliveryError(
                        "本次生图已计费，但图片响应的 data 不是数组；未提交新的生图请求。"
                    )
                images, failures = _decode_images(result, timeout, count)
                if not entries:
                    # No artifact was produced: nothing was billed for a result,
                    # so another URL/model combination is still worth trying.
                    raise ValueError("API 未返回任何图片")
                if len(images) != count:
                    if not failures:
                        failures.append(
                            f"仅返回 {len(entries)} 个图片条目，少于请求的 {count} 张"
                        )
                    raise _PaidDeliveryError(
                        f"本次生图已计费，但图片获取不完整（请求 {count} 张，"
                        f"成功 {len(images)} 张）；未提交新的生图请求。\n"
                        + "\n".join(redact_secrets(item, api_key) for item in failures)
                    )
                revised = result.get("data", [{}])[0].get("revised_prompt")
            except urllib.error.HTTPError as exc:
                try:
                    try:
                        error_body = exc.read(MAX_ERROR_BODY_BYTES + 1)
                        detail = (
                            "错误响应过大" if len(error_body) > MAX_ERROR_BODY_BYTES
                            else error_body.decode("utf-8", errors="replace")[:300]
                        )
                    except Exception:
                        detail = "错误响应读取失败"
                finally:
                    exc.close()
                errors.append(
                    f"{base_url} | {model} | {endpoint}: HTTP {exc.code} "
                    f"{redact_secrets(detail, api_key)}"
                )
                LOGGER.warning("失败: %s", errors[-1])
                continue
            except _PaidDeliveryError:
                raise
            except Exception as exc:  # network / malformed response / bad local file
                errors.append(
                    f"{base_url} | {model}: {type(exc).__name__}: "
                    f"{redact_secrets(str(exc), api_key)}"
                )
                LOGGER.warning("失败: %s", errors[-1])
                continue

            targets = _output_targets(output_path, count)
            try:
                saved = _write_images_atomically(targets, images)
            except OSError as exc:
                raise _PaidDeliveryError(
                    f"本次生图已计费，但写入输出文件失败；未提交新的生图请求。"
                    f"输出路径: {output_path.parent}\n{type(exc).__name__}"
                ) from exc
            return GenerationResult(
                base_url=base_url,
                model=model,
                endpoint=endpoint,
                paths=tuple(saved),
                revised_prompt=revised,
            )

    details = "\n".join(errors)
    raise RuntimeError(
        f"{total} 次 URL/模型组合尝试均失败；jihuarst 生图 skill 当前无法使用。\n{details}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 jihuarst 生成或编辑图片（支持参考图 / mask / 多图参考）"
    )
    parser.add_argument("prompt", help="图片描述或编辑指令")
    parser.add_argument("-o", "--output", type=Path, default=Path("jihuarst-image.png"),
                        help="输出文件路径")
    parser.add_argument("-r", "--ref", type=Path, action="append", default=[],
                        metavar="IMAGE",
                        help="参考图路径，可重复传入以进行多图参考（触发 edits 模式）")
    parser.add_argument("-m", "--mask", type=Path, default=None,
                        help="局部重绘遮罩（透明区域为待编辑区域，仅限单张参考图）")
    parser.add_argument("--size", default=None,
                        help="请求尺寸，如 1536x1024 或 auto")
    parser.add_argument("--quality", default=None,
                        choices=["low", "medium", "high", "auto"], help="生成质量")
    parser.add_argument("--input-fidelity", default=None, choices=["low", "high"],
                        help="参考图保真度（仅 edits 模式）")
    parser.add_argument("-n", "--count", type=int, default=1, help="生成数量")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次请求超时秒数")
    parser.add_argument("--model", default=None, help="仅使用指定模型，跳过其余模型")
    parser.add_argument("--base-url", default=None, help="仅使用指定 Base URL，跳过其余地址")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果摘要")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.size and "x" in args.size and args.size != "auto":
        try:
            width, height = (int(part) for part in args.size.lower().split("x"))
        except ValueError:
            LOGGER.warning("无法解析 --size=%s，将原样透传", args.size)
        else:
            if width * height < MIN_HONOURED_PIXELS:
                LOGGER.warning(
                    "尺寸 %s 总像素低于阈值，上游可能抬升为 1254x1254", args.size
                )

    models = [args.model] if args.model else None
    base_urls = [args.base_url] if args.base_url else BASE_URLS

    try:
        result = generate_image(
            args.prompt,
            args.output,
            load_api_key(),
            base_urls=base_urls,
            models=models,
            timeout=args.timeout,
            count=args.count,
            references=args.ref,
            mask=args.mask,
            size=args.size,
            quality=args.quality,
            input_fidelity=args.input_fidelity,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 1

    if args.json:
        print(json.dumps({
            "base_url": result.base_url,
            "model": result.model,
            "endpoint": result.endpoint,
            "paths": [str(path) for path in result.paths],
            "revised_prompt": result.revised_prompt,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"图片已保存到 {', '.join(str(p) for p in result.paths)}"
              f"（{result.base_url} | {result.model} | {result.endpoint}）")
        if result.revised_prompt:
            print(f"重写后的提示词: {result.revised_prompt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
