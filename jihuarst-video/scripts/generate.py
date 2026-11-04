#!/usr/bin/env python3
"""Submit and poll jihuarst video tasks with URL/model fallback."""

from __future__ import annotations

import base64
import argparse
import http.client
import ipaddress
import json
import logging
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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

BASE_URLS = [
    "http://222.211.75.198:3000",
    "https://gz-api.jihuarst.top:8443",
    "https://api.jihuarst.top",
    "https://sg-api.jihuarst.top",
]
MODELS = ["minimax-video-h3", "kling-video-v3"]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
LOGGER = logging.getLogger("jihuarst-video")
SECRET_PATTERN = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]+\b")
MAX_ERROR_SUMMARY_CHARS = 300
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_VIDEO_BYTES = 1024 * 1024 * 1024

PENDING = {"queued", "pending", "submitted", "processing", "in_progress", "running"}
SUCCESS = {"completed", "succeeded"}
FAILURE = {"failed", "rejected", "cancelled", "lost"}


@dataclass(frozen=True)
class GenerationResult:
    base_url: str
    model: str
    task_id: str
    path: Path


class VideoDownloadError(RuntimeError):
    """Retryable remote MP4 failure; never wrap local output or programming errors."""


class TaskTerminalError(RuntimeError):
    """The upstream explicitly rejected or ended the task; fallback is allowed."""


class PaidDeliveryError(RuntimeError):
    """A task ID exists, so automatic fallback could create another paid task."""


def redact_secrets(text: str, api_key: str) -> str:
    """Remove the configured key and common token-shaped strings from errors."""
    redacted = SECRET_PATTERN.sub("[REDACTED]", text)
    return redacted.replace(api_key, "[REDACTED]") if api_key else redacted


def load_api_key() -> str:
    """Read the key from the skill-local config without exposing it in logs."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 {CONFIG_PATH}: {exc}") from exc
    if not isinstance(config, dict):
        raise ValueError(f"{CONFIG_PATH} 必须包含 JSON 对象")
    api_key = config.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError(f"{CONFIG_PATH} 中缺少有效的 api_key")
    return api_key.strip()


def _reference_data_url(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"参考图不存在: {path}")
    data = path.read_bytes()
    if not data:
        raise ValueError(f"参考图为空文件: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _build_submit_request(
    base_url: str,
    model: str,
    prompt: str,
    api_key: str,
    seconds: float,
    size: str | None,
    reference: str | None,
) -> urllib.request.Request:
    payload: dict[str, object] = {"model": model, "prompt": prompt, "seconds": str(seconds)}
    if size is not None:
        payload["size"] = size
    if reference is not None:
        payload["input_reference"] = reference
    return urllib.request.Request(
        base_url.rstrip("/") + "/v1/videos",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )


def _validate_timing(timeout: float, poll_interval: float, max_wait: float) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout 必须是有限正数")
    if not math.isfinite(poll_interval) or poll_interval < 0:
        raise ValueError("poll_interval 必须是有限非负数")
    if not math.isfinite(max_wait) or max_wait <= 0:
        raise ValueError("max_wait 必须是有限正数")


def _normalized_origin(url: str) -> tuple[str, str, int | None]:
    parts = urllib.parse.urlsplit(url)
    scheme = parts.scheme.lower()
    default_port = {"http": 80, "https": 443}.get(scheme)
    port = parts.port if parts.port is not None else default_port
    return scheme, (parts.hostname or "").lower(), port


class _CredentialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow HTTP(S) redirects without forwarding credentials across origins."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: http.client.HTTPResponse,
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        try:
            target = urllib.parse.urljoin(req.full_url, newurl)
            if urllib.parse.urlsplit(target).scheme.lower() not in {"http", "https"}:
                raise ValueError("重定向仅允许 HTTP(S) 目标")
            # An HTTPS source must never be downgraded to plaintext HTTP.
            if _normalized_origin(req.full_url)[0] == "https" and _normalized_origin(target)[0] == "http":
                raise ValueError("重定向不允许从 HTTPS 降级到 HTTP")
            if req.data is not None and code in {307, 308}:
                redirected = urllib.request.Request(
                    target, data=req.data, headers=dict(req.header_items()),
                    origin_req_host=req.origin_req_host,
                    unverifiable=True, method=req.get_method(),
                )
            else:
                redirected = super().redirect_request(req, fp, code, msg, headers, target)
            if redirected is not None and _normalized_origin(req.full_url) != _normalized_origin(target):
                redirected.remove_header("Authorization")
            return redirected
        finally:
            fp.close()


def _resolved_addresses(hostname: str, port: int, allow_private: bool = False) -> list[str]:
    """Resolve once and reject non-public results unless explicitly testing locally."""
    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(info[4][0].split("%", 1)[0])
        if address not in addresses:
            addresses.append(address)
    if not allow_private and any(
        not address.is_global or address.is_multicast or address.is_reserved
        for address in addresses
    ):
        raise ValueError("视频地址仅允许公网 HTTP(S)")
    return [str(address) for address in addresses]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connect to a validated numeric IP without a second DNS resolution."""

    allow_private_addresses = False

    def connect(self) -> None:
        addresses = _resolved_addresses(self.host, self.port, self.allow_private_addresses)
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
        raise OSError("视频地址没有可用 IP")


class _PinnedHTTPSConnection(_PinnedHTTPConnection, http.client.HTTPSConnection):
    def connect(self) -> None:
        super().connect()
        self.sock = self._context.wrap_socket(
            self.sock, server_hostname=self._tunnel_host or self.host,
        )


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self.connection_class, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self.connection_class, req, context=self._context)


def _build_opener(allow_private: bool = False) -> urllib.request.OpenerDirector:
    """Build an opener with validated-IP downloads and no global installation."""
    class HTTPConnection(_PinnedHTTPConnection):
        allow_private_addresses = allow_private

    class HTTPSConnection(_PinnedHTTPSConnection):
        allow_private_addresses = allow_private

    http_handler = _PinnedHTTPHandler()
    http_handler.connection_class = HTTPConnection
    https_handler = _PinnedHTTPSHandler()
    https_handler.connection_class = HTTPSConnection
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _CredentialRedirectHandler(),
        http_handler, https_handler,
    )


_JSON_OPENER = _build_opener()
_DOWNLOAD_OPENER = _build_opener()


def _read_json(request: urllib.request.Request, timeout: float) -> dict:
    with _JSON_OPENER.open(request, timeout=timeout) as response:
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("API 响应过大")
    result = json.loads(body.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("API 响应必须是 JSON 对象")
    return result


def _poll_task(
    base_url: str,
    task_id: str,
    api_key: str,
    timeout: float,
    poll_interval: float,
    max_wait: float,
) -> dict:
    _validate_timing(timeout, poll_interval, max_wait)
    url = base_url.rstrip("/") + "/v1/videos/" + urllib.parse.quote(task_id, safe="")
    started = time.monotonic()
    while True:
        if time.monotonic() - started >= max_wait:
            raise RuntimeError(f"视频任务等待超过 max_wait={max_wait} 秒")
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        result = _read_json(request, timeout)
        status = result.get("status")
        if status in SUCCESS:
            return result
        if status in FAILURE:
            raise TaskTerminalError(f"视频任务终止，状态: {redact_secrets(str(status), api_key)}")
        if status not in PENDING:
            raise RuntimeError(f"视频任务返回未知状态: {redact_secrets(str(status), api_key)}")
        time.sleep(poll_interval)


def _download_video(
    url: str,
    output_path: Path,
    api_key: str,
    base_url: str,
    timeout: float,
) -> Path:
    """Stream a validated MP4 to a sibling temporary file, then replace atomically."""
    try:
        video_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", url)
        if urllib.parse.urlsplit(video_url).scheme.lower() not in {"http", "https"}:
            raise VideoDownloadError("视频下载仅允许 HTTP(S) 地址")
        headers = {}
        if _normalized_origin(video_url) == _normalized_origin(base_url):
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(video_url, headers=headers, method="GET")
    except VideoDownloadError:
        raise
    except ValueError as exc:
        raise VideoDownloadError(
            f"远程视频地址无效: {type(exc).__name__}: {exc}"
        ) from exc
    temp_name: str | None = None
    try:
        try:
            response = _DOWNLOAD_OPENER.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            try:
                raise VideoDownloadError(f"远程视频请求失败: HTTP {exc.code}") from exc
            finally:
                exc.close()
        except (OSError, http.client.HTTPException, ValueError) as exc:
            raise VideoDownloadError(f"远程视频请求失败: {type(exc).__name__}: {exc}") from exc
        download_error: BaseException | None = None
        try:
            try:
                first_chunk = response.read(65536)
            except (OSError, http.client.HTTPException, ValueError) as exc:
                raise VideoDownloadError(
                    f"远程视频读取失败: {type(exc).__name__}: {exc}"
                ) from exc
            if first_chunk[4:8] != b"ftyp":
                raise VideoDownloadError("远程响应不是有效的 MP4 文件")
            with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as temporary:
                temp_name = temporary.name
                written = 0
                temporary.write(first_chunk)
                written += len(first_chunk)
                if written > MAX_VIDEO_BYTES:
                    raise VideoDownloadError("远程视频超过大小上限")
                while True:
                    try:
                        chunk = response.read(65536)
                    except (OSError, http.client.HTTPException, ValueError) as exc:
                        raise VideoDownloadError(
                            f"远程视频读取失败: {type(exc).__name__}: {exc}"
                        ) from exc
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_VIDEO_BYTES:
                        raise VideoDownloadError("远程视频超过大小上限")
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
        except BaseException as exc:
            download_error = exc
            raise
        finally:
            try:
                response.close()
            except (OSError, http.client.HTTPException, ValueError) as exc:
                if download_error is None:
                    raise VideoDownloadError(
                        f"远程视频关闭失败: {type(exc).__name__}: {exc}"
                    ) from exc
        os.replace(temp_name, output_path)
        return output_path
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成并下载 jihuarst 视频")
    parser.add_argument("prompt")
    parser.add_argument("-o", "--output", type=Path, default=Path("jihuarst-video.mp4"))
    parser.add_argument("-r", "--ref", type=Path)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--size")
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--max-wait", type=float, default=1800)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--base-url")
    parser.add_argument("--json", action="store_true", dest="json_output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    args = _build_parser().parse_args(argv)
    api_key = ""
    try:
        api_key = load_api_key()
        result = generate_video(
            args.prompt, args.output, api_key,
            [args.base_url] if args.base_url else BASE_URLS,
            [args.model] if args.model else None,
            timeout=args.timeout, poll_interval=args.poll_interval,
            max_wait=args.max_wait, seconds=args.seconds, size=args.size,
            reference=args.ref,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(redact_secrets(str(exc), api_key), file=sys.stderr)
        return 1
    if args.json_output:
        json.dump({
            "base_url": result.base_url, "model": result.model,
            "task_id": redact_secrets(result.task_id, api_key), "path": str(result.path),
        }, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        LOGGER.info("视频已保存: %s", result.path)
    return 0


def generate_video(
    prompt: str,
    output_path: Path,
    api_key: str,
    base_urls: Sequence[str] = BASE_URLS,
    models: Sequence[str] | None = None,
    timeout: float = 30.0,
    poll_interval: float = 5.0,
    max_wait: float = 1800.0,
    seconds: float = 5,
    size: str | None = None,
    reference: Path | None = None,
) -> GenerationResult:
    """Try every model within each URL and return the first completed download."""
    if not prompt.strip():
        raise ValueError("提示词不能为空")
    if not api_key.strip():
        raise ValueError("API key 不能为空")
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("seconds 必须是有限正数")
    _validate_timing(timeout, poll_interval, max_wait)
    reference_url = _reference_data_url(reference) if reference is not None else None

    errors: list[str] = []
    selected_models = models if models is not None else MODELS
    total = len(base_urls) * len(selected_models)
    attempt = 0
    for base_url in base_urls:
        for model in selected_models:
            attempt += 1
            attempt_target = redact_secrets(f"{base_url} | {model}", api_key)
            LOGGER.info("尝试 %d/%d: %s", attempt, total, attempt_target)
            try:
                request = _build_submit_request(
                    base_url, model, prompt, api_key, seconds, size, reference_url,
                )
                submitted = _read_json(request, timeout)
                task_id = submitted.get("id")
                if not isinstance(task_id, str) or not task_id.strip():
                    raise ValueError("API 未返回有效的任务 id")
                task_id = task_id.strip()
                LOGGER.info(
                    "任务已提交: %s | %s", attempt_target,
                    redact_secrets(task_id, api_key),
                )
                try:
                    completed = _poll_task(
                        base_url, task_id, api_key, timeout, poll_interval, max_wait,
                    )
                except TaskTerminalError:
                    raise
                except urllib.error.HTTPError as exc:
                    exc.close()
                    raise PaidDeliveryError(
                        f"视频任务可能已计费，但轮询失败；未提交新的请求或任务。"
                        f"任务 ID: {redact_secrets(task_id, api_key)}"
                        f"（{attempt_target}），HTTP {exc.code}"
                    ) from None
                except (OSError, http.client.HTTPException, ValueError, RuntimeError) as exc:
                    raise PaidDeliveryError(
                        f"视频任务可能已计费，但轮询失败；未提交新的请求或任务。"
                        f"任务 ID: {redact_secrets(task_id, api_key)}"
                        f"（{attempt_target}）\n{type(exc).__name__}: "
                        f"{redact_secrets(str(exc), api_key)}"
                        f"\n请使用同一任务 ID 只读查询或恢复，不要直接重新生成。"
                    ) from exc
            except urllib.error.HTTPError as exc:
                try:
                    summary = f"{base_url} | {model} | HTTP {exc.code}"
                finally:
                    exc.close()
            except PaidDeliveryError:
                raise
            except (OSError, http.client.HTTPException, ValueError, RuntimeError) as exc:
                summary = (
                    f"{base_url} | {model} | {type(exc).__name__}: {exc}"
                )
            else:
                content_url = (
                    base_url.rstrip("/") + "/v1/videos/"
                    + urllib.parse.quote(task_id, safe="") + "/content"
                )
                video_urls = [content_url]
                if isinstance(completed.get("url"), str) and completed["url"].strip():
                    video_urls.insert(0, completed["url"].strip())
                delivery_errors: list[str] = []
                for index, video_url in enumerate(video_urls):
                    try:
                        path = _download_video(
                            video_url, output_path, api_key, base_url, timeout,
                        )
                    except VideoDownloadError as exc:
                        delivery_errors.append(
                            f"{type(exc).__name__}: {redact_secrets(str(exc), api_key)}"
                        )
                        if index == 0 and len(video_urls) > 1:
                            LOGGER.warning(
                                "返回地址下载失败，尝试同任务 content: %s | %s | %s",
                                attempt_target, redact_secrets(task_id, api_key),
                                type(exc).__name__,
                            )
                            continue
                    else:
                        return GenerationResult(base_url, model, task_id, path)
                # The paid task exists and finished; only its delivery failed.
                # Falling through to the next combination would submit a new task.
                raise PaidDeliveryError(
                    f"视频任务已计费，但视频下载失败，未提交新的请求或任务。"
                    f"任务 ID: {redact_secrets(task_id, api_key)}"
                    f"（{attempt_target}）\n"
                    + "\n".join(delivery_errors)
                    + "\n请使用同一任务 ID 重试下载，或检查网关的 content/artifact 代理。"
                )
            summary = redact_secrets(summary, api_key)[:MAX_ERROR_SUMMARY_CHARS]
            errors.append(summary)
            LOGGER.warning("失败: %s", summary)

    details = "\n".join(errors)
    raise RuntimeError(
        f"{total} 次 URL/模型组合尝试均失败；jihuarst 视频 skill 当前无法使用。\n{details}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
