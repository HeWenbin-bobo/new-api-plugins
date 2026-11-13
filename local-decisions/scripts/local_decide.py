#!/usr/bin/env python3
"""Call a Piccolo or Jev-Omni decision model through a New API Task Plugin channel.

The client uses only the Python standard library. It validates the request
before sending it and validates the response before printing it, so a caller
never mistakes a malformed or unauthorized response for a usable decision.

Environment:
    NEW_API_BASE_URL   Gateway root, e.g. http://127.0.0.1:3000
    NEW_API_KEY        New API user token (sent as a Bearer token)

Exit codes:
    0  success
    2  input or configuration error
    3  HTTP or network error
    4  invalid upstream response
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MODELS = ("Piccolo-4B-Q4_K_M", "Piccolo-9B-Q8_0", "Jev-Omni-12B-Q4_K_M")
MAX_INPUT_TOKENS = 8192
DEFAULT_TIMEOUT = 60.0

EXIT_INPUT = 2
EXIT_HTTP = 3
EXIT_RESPONSE = 4


class ClientError(Exception):
    """A user-facing error with a process exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _fail(message: str, exit_code: int = EXIT_INPUT) -> None:
    raise ClientError(message, exit_code)


def _is_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def normalize_base_url(raw: str) -> str:
    """Return a gateway root without a trailing slash or /v1 suffix."""
    if not isinstance(raw, str) or not raw.strip():
        _fail("NEW_API_BASE_URL is required")
    value = raw.strip().rstrip("/")
    for suffix in ("/v1/systemone", "/v1"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
            break
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        _fail("base URL must be an absolute http(s) URL")
    if parsed.query or parsed.fragment:
        _fail("base URL must not contain a query or fragment")
    return value


def load_request(path: str) -> dict:
    """Load a request object from a file, or from stdin when path is '-'."""
    try:
        if path == "-":
            text = sys.stdin.read()
        else:
            text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"cannot read request: {exc}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"request is not valid JSON: {exc}")
    if not isinstance(data, dict):
        _fail("request must be a JSON object")
    return data


def validate_request(payload: dict) -> None:
    """Validate the fields required by the local decision Task Plugin adapter."""
    model = payload.get("model")
    if model not in MODELS:
        _fail("model must be one of: " + ", ".join(MODELS))

    state = payload.get("state")
    if isinstance(state, str):
        if not state.strip():
            _fail("state must not be empty")
    elif isinstance(state, list):
        if not state:
            _fail("state must not be an empty array")
    else:
        _fail("state must be a non-empty string or array")

    questions = payload.get("questions")
    if not isinstance(questions, dict) or not questions:
        _fail("questions must be a non-empty object")

    for name, question in questions.items():
        if not isinstance(name, str) or not name.strip():
            _fail("question names must be non-empty strings")
        if not isinstance(question, dict):
            _fail(f"question {name!r} must be an object")

        question_type = question.get("type")
        if question_type not in ("choice", "noul"):
            _fail(f"question {name!r} type must be 'choice' or 'noul'")

        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            _fail(f"question {name!r} needs non-empty instructions")

        criteria = question.get("criteria")
        if question_type == "choice":
            if not isinstance(criteria, dict):
                _fail(f"choice question {name!r} needs a criteria object")
            if not 2 <= len(criteria) <= 256:
                _fail(f"choice question {name!r} needs 2 to 256 criteria")
            for option, description in criteria.items():
                if not isinstance(option, str) or not option.strip():
                    _fail(f"choice question {name!r} has an empty option ID")
                if not isinstance(description, str) or not description.strip():
                    _fail(f"choice option {option!r} needs a description")
        elif criteria is not None:
            if not isinstance(criteria, dict):
                _fail(f"noul question {name!r} criteria must be an object")
            if set(criteria) - {"false", "true"}:
                _fail(f"noul question {name!r} criteria must use 'false' and 'true'")
            for option, description in criteria.items():
                if not isinstance(description, str) or not description.strip():
                    _fail(f"noul option {option!r} needs a description")


def _error_detail(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "empty error response"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return " ".join(text.split())[:300]
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return " ".join(error["message"].split())[:300]
        if isinstance(data.get("message"), str):
            return " ".join(data["message"].split())[:300]
    return " ".join(text.split())[:300]


def post_json(url: str, payload: dict, api_key: str, timeout: float) -> dict:
    """POST a JSON object and return the decoded JSON response."""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        detail = _error_detail(exc.read())
        raise ClientError(f"HTTP {exc.code}: {detail}", EXIT_HTTP) from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ClientError(f"network error: {reason}", EXIT_HTTP) from exc
    except (TimeoutError, OSError) as exc:
        raise ClientError(f"network error: {exc}", EXIT_HTTP) from exc

    if status != 200:
        raise ClientError(f"unexpected HTTP status {status}", EXIT_HTTP)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError(f"invalid JSON response: {exc}", EXIT_RESPONSE) from exc
    if not isinstance(data, dict):
        _fail("response must be a JSON object", EXIT_RESPONSE)
    return data


def validate_response(payload: dict, request: dict) -> None:
    """Validate the decision envelope before a caller can act on it."""
    if not isinstance(payload.get("model"), str) or not payload["model"].strip():
        _fail("response.model must be a non-empty string", EXIT_RESPONSE)

    answers = payload.get("answers")
    if not isinstance(answers, dict):
        _fail("response.answers must be an object", EXIT_RESPONSE)

    for name, question in request["questions"].items():
        answer = answers.get(name)
        if not isinstance(answer, dict):
            _fail(f"response is missing answer {name!r}", EXIT_RESPONSE)
        if answer.get("type") != question["type"]:
            _fail(f"answer {name!r} has the wrong type", EXIT_RESPONSE)

        if question["type"] == "choice":
            probabilities = answer.get("probabilities")
            if not isinstance(probabilities, dict):
                _fail(f"answer {name!r} is missing probabilities", EXIT_RESPONSE)
            expected = set(question["criteria"])
            if set(probabilities) != expected:
                _fail(f"answer {name!r} probability keys do not match criteria", EXIT_RESPONSE)
            for option, value in probabilities.items():
                if not _is_number(value) or not 0.0 <= float(value) <= 1.0:
                    _fail(f"answer {name!r} has an invalid probability for {option!r}", EXIT_RESPONSE)
            total = sum(float(value) for value in probabilities.values())
            if abs(total - 1.0) > 0.001:
                _fail(f"answer {name!r} probabilities sum to {total:.6f}, not 1", EXIT_RESPONSE)
            choice = answer.get("choice")
            if choice not in probabilities:
                _fail(f"answer {name!r} chose an unknown option", EXIT_RESPONSE)
            best = max(probabilities, key=lambda key: float(probabilities[key]))
            if float(probabilities[choice]) + 1e-9 < float(probabilities[best]):
                _fail(f"answer {name!r} chose a non-maximal option", EXIT_RESPONSE)
            confidence = answer.get("confidence")
            if confidence is not None:
                if not _is_number(confidence) or not 0.0 <= float(confidence) <= 1.0:
                    _fail(f"answer {name!r} has an invalid confidence", EXIT_RESPONSE)
        else:
            noul = answer.get("noul")
            if not _is_number(noul) or not 0.0 <= float(noul) <= 1.0:
                _fail(f"answer {name!r} has an invalid noul value", EXIT_RESPONSE)

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        _fail("response.usage must be an object", EXIT_RESPONSE)
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if (
        not isinstance(input_tokens, int)
        or isinstance(input_tokens, bool)
        or not 0 <= input_tokens <= MAX_INPUT_TOKENS
    ):
        _fail("response.usage.input_tokens must be an integer in 0..8192", EXIT_RESPONSE)
    if (
        not isinstance(output_tokens, int)
        or isinstance(output_tokens, bool)
        or output_tokens != 0
    ):
        _fail("response.usage.output_tokens must be 0", EXIT_RESPONSE)


def decide(
    request: dict,
    *,
    base_url: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT,
    model: str | None = None,
) -> dict:
    """Send one decision request and return the validated response."""
    if not isinstance(request, dict):
        _fail("request must be a JSON object")
    if not isinstance(api_key, str) or not api_key.strip():
        _fail("NEW_API_KEY is required")
    if not _is_number(timeout) or float(timeout) <= 0:
        _fail("timeout must be a positive number")

    payload = copy.deepcopy(request)
    if model is not None:
        if model not in MODELS:
            _fail("model must be one of: " + ", ".join(MODELS))
        payload["model"] = model
    validate_request(payload)

    root = normalize_base_url(base_url)
    response = post_json(
        root + "/v1/systemone",
        payload,
        api_key.strip(),
        float(timeout),
    )
    validate_response(response, payload)
    return response


def _default_timeout() -> float:
    raw = os.environ.get("PICCOLO_TIMEOUT", str(int(DEFAULT_TIMEOUT)))
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Call a Piccolo or Jev-Omni decision model through New API /v1/systemone."
    )
    parser.add_argument(
        "--request",
        "-r",
        required=True,
        help="Path to a JSON request, or '-' to read from stdin.",
    )
    parser.add_argument(
        "--model",
        choices=MODELS,
        help="Override the request model.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NEW_API_BASE_URL", ""),
        help="New API gateway root; defaults to NEW_API_BASE_URL.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_default_timeout(),
        help="HTTP timeout in seconds; defaults to PICCOLO_TIMEOUT or 60.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print the upstream response without request_model and elapsed_ms.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print one-line JSON instead of indented JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        request = load_request(args.request)
        started = time.monotonic()
        response = decide(
            request,
            base_url=args.base_url,
            api_key=os.environ.get("NEW_API_KEY", ""),
            timeout=args.timeout,
            model=args.model,
        )
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        output = response
        if not args.raw:
            output = {
                "request_model": args.model or request.get("model"),
                "elapsed_ms": elapsed_ms,
                **response,
            }
        print(json.dumps(output, ensure_ascii=False, indent=None if args.compact else 2))
        return 0
    except ClientError as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"message": str(exc)}},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
