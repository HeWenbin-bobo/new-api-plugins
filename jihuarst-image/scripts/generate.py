#!/usr/bin/env python3
"""Generate or edit images through every configured jihuarst URL/model combination.

Supports two server modes:

* ``/v1/images/generations`` -- text-to-image (JSON body).
* ``/v1/images/edits``       -- image-to-image / reference guided editing
  (multipart body, one or more ``image`` parts, optional ``mask``).

Every URL is tried in turn; within a URL every model is tried; the first
combination that returns a usable image wins.  Only the Python standard
library is required at runtime (Pillow is used by ``--inspect`` and the tests,
never for the request path itself).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

BASE_URLS = [
    "https://gz-api.jihuarst.top:8443",
    "https://api.jihuarst.top",
    "https://sg-api.jihuarst.top",
]
MODELS = ["gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2"]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.json"
LOGGER = logging.getLogger("jihuarst-image")
SECRET_PATTERN = re.compile(r"(?i)\bsk-[A-Za-z0-9_-]+\b")

# The upstream silently raises any request below this pixel budget to a
# 1254x1254 default.  Verified against the live gateway: 1024x1024 and
# 512x512 both came back as 1254x1254, while 1024x1536 / 1536x1024 were kept.
MIN_HONOURED_PIXELS = 1254 * 1254

ENDPOINT_GENERATIONS = "/v1/images/generations"
ENDPOINT_EDITS = "/v1/images/edits"


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
    return SECRET_PATTERN.sub("[REDACTED]", text).replace(api_key, "[REDACTED]")


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
    data = path.read_bytes()
    if not data:
        raise ValueError(f"参考图为空文件: {path}")
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


def _decode_images(result: dict) -> list[bytes]:
    """Pull every image out of a generations/edits response."""
    images: list[bytes] = []
    for item in result.get("data", []):
        encoded = item.get("b64_json") or ""
        if not encoded and item.get("url", "").startswith("data:"):
            encoded = item["url"]
        if not encoded:
            continue
        if encoded.startswith("data:"):
            encoded = encoded.split(",", 1)[1]
        raw = base64.b64decode(encoded)
        if raw:
            images.append(raw)
    return images


def _output_targets(output_path: Path, count: int) -> list[Path]:
    """Return one path per returned image, adding a numeric suffix when needed."""
    if count <= 1:
        return [output_path]
    stem, suffix = output_path.stem, output_path.suffix
    return [output_path.parent / f"{stem}-{index}{suffix}" for index in range(1, count + 1)]


def generate_image(
    prompt: str,
    output_path: Path,
    api_key: str,
    base_urls: Sequence[str] = BASE_URLS,
    models: Sequence[str] = MODELS,
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
    if count < 1:
        raise ValueError("生成数量至少为 1")
    # Local input problems must fail fast: retrying them across every URL/model
    # combination would only repeat the same error and waste time.
    for reference in references:
        if not reference.is_file():
            raise ValueError(f"参考图不存在: {reference}")
    if mask is not None:
        if len(references) != 1:
            raise ValueError("mask 只能与单张参考图一起使用")
        if not mask.is_file():
            raise ValueError(f"遮罩图不存在: {mask}")

    errors: list[str] = []
    total = len(base_urls) * len(models)
    attempt = 0
    for base_url in base_urls:
        for model in models:
            attempt += 1
            LOGGER.info("尝试 %d/%d: %s | %s", attempt, total, base_url, model)
            try:
                request, endpoint = _build_request(
                    base_url, model, prompt, api_key, count,
                    list(references), mask, size, quality, input_fidelity,
                )
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    result = json.loads(response.read().decode("utf-8"))
                images = _decode_images(result)
                if not images:
                    raise ValueError("API 未返回任何图片")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                errors.append(
                    f"{base_url} | {model} | {endpoint}: HTTP {exc.code} "
                    f"{redact_secrets(detail, api_key)}"
                )
                LOGGER.warning("失败: %s", errors[-1])
                continue
            except Exception as exc:  # network / malformed response / bad local file
                errors.append(
                    f"{base_url} | {model}: {type(exc).__name__}: "
                    f"{redact_secrets(str(exc), api_key)}"
                )
                LOGGER.warning("失败: %s", errors[-1])
                continue

            targets = _output_targets(output_path, len(images))
            saved: list[Path] = []
            for image_bytes, target in zip(images, targets):
                target.write_bytes(image_bytes)
                saved.append(target)
            revised = result.get("data", [{}])[0].get("revised_prompt")
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

    models = [args.model] if args.model else MODELS
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
