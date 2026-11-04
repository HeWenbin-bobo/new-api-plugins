"""Offline tests for video submission, polling, and fallback."""

from __future__ import annotations

import http.client
import importlib.util
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "generate.py"
EXPECTED_URLS = [
    "http://222.211.75.198:3000",
    "https://gz-api.jihuarst.top:8443",
    "https://api.jihuarst.top",
    "https://sg-api.jihuarst.top",
]
EXPECTED_MODELS = ["minimax-video-h3", "kling-video-v3"]
PNG_BYTES = b"\x89PNG\r\n\x1a\njihuarst-test"
MP4_BYTES = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00jihuarst-test"


class Handler(BaseHTTPRequestHandler):
    """Record requests and replay scripted submission and polling responses."""

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        self.server.requests.append({
            "method": "POST",
            "path": self.path,
            "payload": payload,
            "authorization": self.headers.get("Authorization"),
        })
        if self.path == self.server.redirect_path:
            self._send_redirect()
            return
        index = min(self.server.post_count, len(self.server.statuses) - 1)
        self.server.post_count += 1
        status = self.server.statuses[index]
        if status == 200:
            if self.server.invalid_json:
                body = b"{not-json"
            else:
                body = json.dumps({"id": self.server.task_id, "status": "queued"}).encode()
        else:
            body = json.dumps({"error": {"message": self.server.error_detail}}).encode()
        self._send_json(status, body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        self.server.requests.append({
            "method": "GET",
            "path": self.path,
            "payload": None,
            "authorization": self.headers.get("Authorization"),
        })
        if self.path.startswith("/video/") or self.path.endswith("/content"):
            self.server.download_authorization = self.headers.get("Authorization")
        if self.path == self.server.redirect_path:
            self._send_redirect()
            return
        if self.path.startswith("/video/") or self.path.endswith("/content"):
            status = 404 if self.path in self.server.failed_download_paths else self.server.download_status
            body = b'{"error":{"message":"not found"}}' if status == 404 else self.server.download_body
            self.send_response(status)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        # The first scripted state represents the submission response. Polls
        # consume subsequent states, matching the two-GET failure scenario.
        index = min(self.server.poll_count + 1, len(self.server.task_statuses) - 1)
        self.server.poll_count += 1
        status = self.server.task_statuses[index]
        result = {"id": self.server.task_id, "status": status}
        if status in {"completed", "succeeded"} and self.server.video_url:
            result["url"] = self.server.video_url
        self._send_json(200, json.dumps(result).encode())

    def _send_redirect(self) -> None:
        self.send_response(307)
        self.send_header("Location", self.server.redirect_target)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


@contextmanager
def fake_api(statuses, *, task_statuses=None, task_id="task-1", invalid_json=False,
             video_url="https://cdn.example.invalid/video.mp4", redirect_target=None,
             redirect_path="/redirect", remote_video=False, download_body=MP4_BYTES,
             download_status=200):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.statuses = statuses
    server.task_statuses = task_statuses or ["queued", "failed"]
    server.task_id = task_id
    server.invalid_json = invalid_json
    server.video_url = video_url
    server.redirect_target = redirect_target
    server.redirect_path = redirect_path
    if remote_video:
        server.task_statuses = ["queued", "completed"]
        server.video_url = "/video/task-1.mp4"
    server.download_body = download_body
    server.download_status = download_status
    server.download_authorization = None
    server.failed_download_paths = set()
    server.error_detail = "injected failure; sk-test-secret and test-key; " + "x" * 1000
    server.requests = []
    server.post_count = 0
    server.poll_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def load_module():
    import sys

    spec = importlib.util.spec_from_file_location("jihuarst_video_generate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GenerateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "jihuarst video generate.py 尚未实现")
        self.module = load_module()
        self.public_json_opener = self.module._JSON_OPENER
        self.original_download_opener = self.module._DOWNLOAD_OPENER
        self.module._JSON_OPENER = self.module._build_opener(allow_private=True)
        self.module._DOWNLOAD_OPENER = self.module._build_opener(allow_private=True)
        self.tempdir = tempfile.TemporaryDirectory()
        self.output = Path(self.tempdir.name) / "out.mp4"
        self.ref = Path(self.tempdir.name) / "ref.png"
        self.ref.write_bytes(PNG_BYTES)

    def tearDown(self) -> None:
        self.module._JSON_OPENER = self.public_json_opener
        self.module._DOWNLOAD_OPENER = self.original_download_opener
        self.tempdir.cleanup()

    def test_declared_priorities(self) -> None:
        self.assertEqual(EXPECTED_URLS, self.module.BASE_URLS)
        self.assertEqual(["minimax-video-h3", "kling-video-v3"], self.module.MODELS)

    def test_text_request_uses_openai_video_contract(self) -> None:
        request = self.module._build_submit_request(
            "http://127.0.0.1:9", "minimax-video-h3", "cat", "test-key", 5, "1280x720", None
        )
        self.assertEqual("http://127.0.0.1:9/v1/videos", request.full_url)
        self.assertEqual({"model": "minimax-video-h3", "prompt": "cat", "seconds": "5",
                          "size": "1280x720"}, json.loads(request.data))
        self.assertEqual("Bearer test-key", request.get_header("Authorization"))
        self.assertEqual("application/json", request.get_header("Content-type"))

    def test_reference_is_sent_as_input_reference_data_url(self) -> None:
        reference = self.module._reference_data_url(self.ref)
        self.assertTrue(reference.startswith("data:image/png;base64,"))
        request = self.module._build_submit_request(
            "http://127.0.0.1:9", "minimax-video-h3", "move", "test-key", 5, None, reference
        )
        self.assertEqual(reference, json.loads(request.data)["input_reference"])
        self.assertNotIn("size", json.loads(request.data))

    def test_exhausts_models_before_switching_url(self) -> None:
        with fake_api([500]) as (first, first_url), fake_api([200]) as (second, second_url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video("cat", self.output, "test-key", [first_url, second_url],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual(EXPECTED_MODELS, [r["payload"]["model"] for r in first.requests])

    def test_poll_does_not_resubmit(self) -> None:
        with fake_api([200], task_statuses=["queued", "processing", "failed"]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))
        self.assertEqual(2, len([r for r in server.requests if r["method"] == "GET"]))

    def test_poll_returns_completed_response(self) -> None:
        with fake_api([200], task_statuses=["queued", "completed"]) as (server, url):
            result = self.module._poll_task(url, "task-1", "test-key", 2, 0, 2)
        self.assertEqual("completed", result["status"])
        self.assertEqual("task-1", result["id"])
        self.assertEqual(1, len(server.requests))

    def test_status_sets_match_contract(self) -> None:
        self.assertEqual({"queued", "pending", "submitted", "processing", "in_progress", "running"},
                         self.module.PENDING)
        self.assertEqual({"completed", "succeeded"}, self.module.SUCCESS)
        self.assertEqual({"failed", "rejected", "cancelled", "lost"}, self.module.FAILURE)

    def test_unknown_status_is_an_explicit_failure(self) -> None:
        with fake_api([200], task_statuses=["queued", "mystery"]) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertIn("mystery", str(raised.exception))
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "GET"]))

    def test_terminal_failure_is_an_explicit_failure(self) -> None:
        with fake_api([200], task_statuses=["queued", "cancelled"]) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertIn("cancelled", str(raised.exception))

    def test_max_wait_expiry_stops_polling(self) -> None:
        with fake_api([200], task_statuses=["queued", "processing", "completed"]) as (server, url):
            with mock.patch.object(self.module.time, "monotonic", side_effect=[0, 0, 2]):
                with self.assertRaises(RuntimeError) as raised:
                    self.module._poll_task(url, "task-1", "test-key", 2, 0, 1)
        self.assertIn("wait", str(raised.exception).lower())
        self.assertEqual(1, len(server.requests))

    def test_submission_requires_nonempty_id(self) -> None:
        with fake_api([200], task_id=" ") as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual(1, len(server.requests))

    def test_poll_path_url_encodes_task_id(self) -> None:
        with fake_api([200], task_id="task /?#%") as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual("/v1/videos/task%20%2F%3F%23%25", server.requests[-1]["path"])

    def test_empty_prompt_fails_without_requests(self) -> None:
        with fake_api([200]) as (server, url):
            for prompt in ("", "   "):
                with self.subTest(prompt=prompt), self.assertRaises(ValueError):
                    self.module.generate_video(prompt, self.output, "test-key", [url],
                                               timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual([], server.requests)

    def test_invalid_seconds_fail_without_requests(self) -> None:
        with fake_api([200]) as (server, url):
            for seconds in (0, -1, math.inf, math.nan):
                with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                    self.module.generate_video("cat", self.output, "test-key", [url],
                                               seconds=seconds, timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual([], server.requests)

    def test_missing_or_empty_reference_fails_without_requests(self) -> None:
        missing = Path(self.tempdir.name) / "missing.png"
        empty = Path(self.tempdir.name) / "empty.png"
        empty.write_bytes(b"")
        with fake_api([200]) as (server, url):
            for reference in (missing, empty):
                with self.subTest(reference=reference.name), self.assertRaises(ValueError):
                    self.module.generate_video("cat", self.output, "test-key", [url],
                                               reference=reference, timeout=2,
                                               poll_interval=0, max_wait=2)
        self.assertEqual([], server.requests)

    def test_invalid_timing_values_fail_without_requests(self) -> None:
        cases = [
            {"timeout": value} for value in (0, -1, math.inf, math.nan)
        ] + [
            {"max_wait": value} for value in (0, -1, math.inf, math.nan)
        ] + [
            {"poll_interval": value} for value in (-1, math.inf, math.nan)
        ]
        with fake_api([200]) as (server, url):
            for overrides in cases:
                kwargs = {"timeout": 2, "poll_interval": 0, "max_wait": 2, **overrides}
                with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                    self.module.generate_video("cat", self.output, "test-key", [url], **kwargs)
        self.assertEqual([], server.requests)

    def test_empty_api_key_fails_without_requests(self) -> None:
        with fake_api([200]) as (server, url):
            with self.assertRaises(ValueError):
                self.module.generate_video("cat", self.output, " ", [url],
                                           timeout=2, poll_interval=0, max_wait=2)
        self.assertEqual([], server.requests)

    def test_http_error_summaries_omit_upstream_bodies(self) -> None:
        with fake_api([500]) as (server, url):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_video("cat", self.output, "test-key", [url], ["minimax-video-h3"],
                                           timeout=2, poll_interval=0, max_wait=2)
        message = str(raised.exception)
        self.assertIn("HTTP 500", message)
        self.assertNotIn("injected failure", message)
        self.assertNotIn("sk-test-secret", message)
        self.assertNotIn("test-key", message)
        self.assertLess(len(message), 600)

    def test_http_error_does_not_echo_input_reference(self) -> None:
        reference = self.module._reference_data_url(self.ref)
        encoded = reference.split(",", 1)[1]
        with fake_api([500]) as (server, url):
            server.error_detail = f"upstream echoed {reference}"
            with self.assertLogs("jihuarst-video", level="WARNING") as logs:
                with self.assertRaises(RuntimeError) as raised:
                    self.module.generate_video(
                        "move", self.output, "test-key", [url], ["minimax-video-h3"],
                        reference=self.ref, timeout=2, poll_interval=0, max_wait=2,
                    )
        exposed = "\n".join(logs.output) + str(raised.exception)
        self.assertNotIn(reference, exposed)
        self.assertNotIn(encoded, exposed)

    def test_http_error_body_read_cannot_interrupt_model_fallback(self) -> None:
        with fake_api([200], task_statuses=["queued", "failed"]) as (server, url):
            error = urllib.error.HTTPError(url + "/v1/videos", 500, "injected", {}, None)
            error.read = mock.Mock(side_effect=AssertionError("body read must not happen"))
            error.close = mock.Mock()
            real_open = self.module._JSON_OPENER.open
            attempted_models = []

            def fail_first_model(request, timeout):
                if request.get_method() == "POST":
                    model = json.loads(request.data)["model"]
                    attempted_models.append(model)
                    if model == EXPECTED_MODELS[0]:
                        raise error
                return real_open(request, timeout=timeout)

            with mock.patch.object(self.module._JSON_OPENER, "open", side_effect=fail_first_model):
                try:
                    self.module.generate_video(
                        "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                        timeout=2, poll_interval=0, max_wait=2,
                    )
                except RuntimeError:
                    pass
                except Exception as exc:
                    self.fail(f"HTTP error handling stopped fallback: {type(exc).__name__}")
                else:
                    self.fail("terminal task failure should raise RuntimeError")
        self.assertEqual(EXPECTED_MODELS, attempted_models)
        error.read.assert_not_called()
        error.close.assert_called_once_with()

    def test_http_protocol_error_uses_next_model(self) -> None:
        with fake_api([200], task_statuses=["queued", "failed"]) as (server, url):
            real_open = self.module._JSON_OPENER.open
            attempted_models = []

            def fail_first_model(request, timeout):
                if request.get_method() == "POST":
                    model = json.loads(request.data)["model"]
                    attempted_models.append(model)
                    if model == EXPECTED_MODELS[0]:
                        raise http.client.BadStatusLine("injected protocol failure")
                return real_open(request, timeout=timeout)

            with mock.patch.object(self.module._JSON_OPENER, "open", side_effect=fail_first_model):
                try:
                    self.module.generate_video(
                        "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                        timeout=2, poll_interval=0, max_wait=2,
                    )
                except RuntimeError:
                    pass
                except Exception as exc:
                    self.fail(f"protocol error stopped fallback: {type(exc).__name__}")
                else:
                    self.fail("terminal task failure should raise RuntimeError")
        self.assertEqual(EXPECTED_MODELS, attempted_models)

    def test_submit_redirect_drops_cross_origin_authorization(self) -> None:
        with fake_api([200], redirect_path="/v1/videos") as (source, source_url), \
                fake_api([200], task_statuses=["queued", "completed"]) as (target, target_url):
            source.redirect_target = target_url + "/v1/videos"
            submitted = self.module._read_json(
                self.module._build_submit_request(
                    source_url, "minimax-video-h3", "cat", "test-key", 5, None, None,
                ), 2,
            )
        self.assertEqual("task-1", submitted["id"])
        self.assertEqual("Bearer test-key", source.requests[0]["authorization"])
        self.assertEqual("POST", target.requests[0]["method"])
        self.assertEqual("/v1/videos", target.requests[0]["path"])
        self.assertIsNone(target.requests[0]["authorization"])

    def test_submit_rejects_non_public_redirect_without_connecting(self) -> None:
        request = self.module._build_submit_request(
            "http://public.example.invalid", "minimax-video-h3", "cat", "test-key", 5, None, None,
        )
        response = mock.Mock()
        with fake_api([200]) as (target, target_url):
            redirected = self.module._CredentialRedirectHandler().redirect_request(
                request, response, 307, "Temporary Redirect", {}, target_url + "/v1/videos",
            )
            with mock.patch.object(
                self.module.socket, "create_connection", wraps=self.module.socket.create_connection,
            ) as connect:
                with self.assertRaises(ValueError):
                    with self.public_json_opener.open(redirected, timeout=2) as opened:
                        opened.read()
            self.assertEqual([], target.requests)
        connect.assert_not_called()
        response.close.assert_called_once_with()

    def test_poll_redirect_drops_cross_origin_authorization(self) -> None:
        with fake_api([200], task_statuses=["queued", "completed"]) as (source, source_url), \
                fake_api([200], task_statuses=["queued", "completed"],
                         redirect_path="/v1/videos/task-1") as (target, target_url):
            target.redirect_target = source_url + "/v1/videos/task-1"
            result = self.module._poll_task(target_url, "task-1", "test-key", 2, 0, 2)
        self.assertEqual("completed", result["status"])
        self.assertEqual("Bearer test-key", target.requests[0]["authorization"])
        self.assertEqual("GET", source.requests[0]["method"])
        self.assertEqual("/v1/videos/task-1", source.requests[0]["path"])
        self.assertIsNone(source.requests[0]["authorization"])

    def test_cross_origin_redirect_drops_authorization(self) -> None:
        with fake_api([200]) as (source, source_url), fake_api([200]) as (target, target_url):
            source.redirect_target = target_url + "/final"
            request = self.module.urllib.request.Request(
                source_url + "/redirect", headers={"Authorization": "Bearer test-key"},
            )
            result = self.module._read_json(request, 2)
        self.assertEqual("failed", result["status"])
        self.assertEqual("Bearer test-key", source.requests[0]["authorization"])
        self.assertIsNone(target.requests[0]["authorization"])

    def test_same_origin_redirect_retains_authorization(self) -> None:
        with fake_api([200]) as (server, url):
            server.redirect_target = url + "/final"
            request = self.module.urllib.request.Request(
                url + "/redirect", headers={"Authorization": "Bearer test-key"},
            )
            result = self.module._read_json(request, 2)
        self.assertEqual("failed", result["status"])
        self.assertEqual(
            ["Bearer test-key", "Bearer test-key"],
            [request["authorization"] for request in server.requests],
        )

    def test_non_http_redirect_is_an_explicit_failure(self) -> None:
        with fake_api([200], redirect_target="ftp://127.0.0.1:1/video") as (server, url):
            request = self.module.urllib.request.Request(
                url + "/redirect", headers={"Authorization": "Bearer test-key"},
            )
            with self.assertRaises(Exception) as raised:
                self.module._read_json(request, 2)
        self.assertIsInstance(raised.exception, ValueError)
        self.assertIn("HTTP(S)", str(raised.exception))
        self.assertEqual(1, len(server.requests))

    def test_malformed_json_uses_next_combination(self) -> None:
        with fake_api([200], invalid_json=True) as (first, first_url), \
                fake_api([500]) as (second, second_url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video("cat", self.output, "test-key", [first_url, second_url],
                                           ["minimax-video-h3"], timeout=2,
                                           poll_interval=0, max_wait=2)
        self.assertEqual(1, len(first.requests))
        self.assertEqual(1, len(second.requests))

    def test_network_errors_are_sanitized(self) -> None:
        error = urllib.error.URLError("offline test-key sk-test-secret")
        with mock.patch.object(self.module._JSON_OPENER, "open", side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_video("cat", self.output, "test-key", ["http://127.0.0.1:9"],
                                           ["minimax-video-h3"], timeout=2,
                                           poll_interval=0, max_wait=2)
        self.assertNotIn("test-key", str(raised.exception))
        self.assertNotIn("sk-test-secret", str(raised.exception))

    def test_nonterminal_poll_failure_does_not_submit_another_task(self) -> None:
        with fake_api([200], task_statuses=["queued", "failed"]) as (server, url):
            real_read = self.module._read_json

            def fail_poll(request, timeout):
                if request.get_method() == "GET":
                    raise TimeoutError("poll connection lost")
                return real_read(request, timeout)

            with mock.patch.object(self.module, "_read_json", side_effect=fail_poll):
                with self.assertRaises(self.module.PaidDeliveryError) as raised:
                    self.module.generate_video(
                        "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                        timeout=2, poll_interval=0, max_wait=2,
                    )
        self.assertIn("task-1", str(raised.exception))
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))
        self.assertEqual(0, len([r for r in server.requests if r["method"] == "GET"]))
        self.assertFalse(self.output.exists())

    def test_complete_error_summary_is_capped_and_redacted(self) -> None:
        self.assertTrue(hasattr(self.module, "MAX_ERROR_SUMMARY_CHARS"),
                        "summary limit constant is missing")
        long_url = "http://test-key@" + "x" * 1000 + ".invalid"
        long_model = "model-test-key-" + "y" * 1000
        with self.assertLogs("jihuarst-video", level="INFO") as logs:
            with mock.patch.object(
                self.module._JSON_OPENER, "open",
                side_effect=urllib.error.URLError("offline"),
            ):
                with self.assertRaises(RuntimeError) as raised:
                    self.module.generate_video(
                        "cat", self.output, "test-key", [long_url], [long_model],
                        timeout=2, poll_interval=0, max_wait=2,
                    )
        message = str(raised.exception)
        summary = message.splitlines()[-1]
        self.assertLessEqual(len(summary), self.module.MAX_ERROR_SUMMARY_CHARS)
        self.assertNotIn("test-key", message)
        self.assertNotIn(long_url, message)
        log_output = "\n".join(logs.output)
        self.assertNotIn("test-key", log_output)
        self.assertNotIn(long_url, log_output)

    def test_generate_returns_result_through_download_hook(self) -> None:
        with fake_api([200], task_statuses=["queued", "completed"]) as (server, url):
            with mock.patch.object(self.module, "_download_video", return_value=self.output) as download:
                result = self.module.generate_video(
                    "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual((url, "minimax-video-h3", "task-1", self.output),
                         (result.base_url, result.model, result.task_id, result.path))
        download.assert_called_once_with(
            "https://cdn.example.invalid/video.mp4", self.output, "test-key", url, 2,
        )

    def test_local_download_errors_do_not_resubmit(self) -> None:
        for error in (PermissionError("read-only output"), NotImplementedError("deferred"),
                      TypeError("programming error")):
            with self.subTest(error=type(error).__name__):
                with fake_api([200, 200], task_statuses=["queued", "completed"]) as (server, url):
                    with mock.patch.object(self.module, "_download_video", side_effect=error):
                        with self.assertRaises(type(error)):
                            self.module.generate_video(
                                "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                                timeout=2, poll_interval=0, max_wait=2,
                            )
                    self.assertEqual(1, len([
                        r for r in server.requests if r["method"] == "POST"
                    ]))

    def test_retryable_remote_download_error_does_not_resubmit(self) -> None:
        self.assertTrue(hasattr(self.module, "VideoDownloadError"),
                        "retryable remote download contract is missing")
        with fake_api([200, 200], task_statuses=["queued", "completed"]) as (server, url):
            with mock.patch.object(
                self.module, "_download_video",
                side_effect=[
                    self.module.VideoDownloadError("returned URL unavailable"),
                    self.module.VideoDownloadError("content unavailable"),
                    self.output,
                ],
            ) as download:
                with self.assertRaises(RuntimeError):
                    self.module.generate_video(
                        "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                        timeout=2, poll_interval=0, max_wait=2,
                    )
        self.assertEqual(2, download.call_count)
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))

    def test_load_api_key_uses_temporary_config(self) -> None:
        original_path = self.module.CONFIG_PATH
        self.module.CONFIG_PATH = Path(self.tempdir.name) / "config.json"
        self.addCleanup(setattr, self.module, "CONFIG_PATH", original_path)
        self.module.CONFIG_PATH.write_text('{"api_key": " test-fixture-key "}', encoding="utf-8")
        self.assertEqual("test-fixture-key", self.module.load_api_key())
        self.module.CONFIG_PATH.write_text('{"api_key": ""}', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.module.load_api_key()
        for content in ("[]", "null"):
            with self.subTest(content=content):
                self.module.CONFIG_PATH.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.module.load_api_key()

    def test_redacts_token_shaped_and_exact_configured_secrets(self) -> None:
        redacted = self.module.redact_secrets(
            "sk-test-secret exact-configured-key sk-other_secret", "exact-configured-key"
        )
        self.assertEqual("[REDACTED] [REDACTED] [REDACTED]", redacted)

    def test_remote_video_download_does_not_receive_api_key(self) -> None:
        with fake_api([200], remote_video=True) as (api, api_url), \
                fake_api([200], remote_video=True) as (remote, remote_url):
            api.video_url = remote_url + "/video/task-1.mp4"
            result = self.module.generate_video(
                "cat", self.output, "test-key", [api_url], ["minimax-video-h3"],
                timeout=2, poll_interval=0, max_wait=2,
            )
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertIsNone(remote.download_authorization)
        self.assertEqual("task-1", result.task_id)

    def test_non_mp4_is_not_saved(self) -> None:
        with fake_api([200], remote_video=True, download_body=b"<html>error</html>") as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertFalse(self.output.exists())

    def test_download_rejects_non_public_initial_url_without_connecting(self) -> None:
        self.module._DOWNLOAD_OPENER = self.module._build_opener()
        with mock.patch.object(self.module.socket, "create_connection") as connect:
            with self.assertRaises(self.module.VideoDownloadError):
                self.module._download_video(
                    "http://127.0.0.1:9/video.mp4", self.output, "test-key",
                    "https://api.example.invalid", 2,
                )
        connect.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_https_redirect_downgrade_is_rejected_and_closed(self) -> None:
        request = self.module.urllib.request.Request("https://public.example.invalid/start")
        response = mock.Mock()
        with self.assertRaisesRegex(ValueError, "HTTPS.*HTTP"):
            self.module._CredentialRedirectHandler().redirect_request(
                request, response, 307, "Temporary Redirect", {},
                "http://public.example.invalid/video.mp4",
            )
        response.close.assert_called_once_with()

    def test_download_rejects_non_public_redirect_without_connecting(self) -> None:
        request = self.module.urllib.request.Request("http://public.example.invalid/start")
        response = mock.Mock()
        handler = self.module._CredentialRedirectHandler()
        redirected = handler.redirect_request(
            request, response, 307, "Temporary Redirect", {},
            "http://127.0.0.1:9/video.mp4",
        )
        target = self.module.urllib.parse.urlsplit(redirected.full_url)
        with mock.patch.object(self.module.socket, "create_connection") as connect:
            connection = self.module._PinnedHTTPConnection(target.hostname, target.port)
            with self.assertRaises(ValueError):
                connection.connect()
        connect.assert_not_called()
        response.close.assert_called_once_with()
        self.assertFalse(self.output.exists())

    def test_json_response_limit_rejects_excess_before_decoding(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"{}"
        with mock.patch.object(self.module, "MAX_RESPONSE_BYTES", 1), \
                mock.patch.object(self.module._JSON_OPENER, "open", return_value=response):
            with self.assertRaisesRegex(ValueError, "响应过大"):
                self.module._read_json(mock.Mock(), 2)
        response.read.assert_called_once_with(2)
        response.__exit__.assert_called_once_with(None, None, None)
    def test_oversized_video_preserves_existing_output_and_removes_temporary_file(self) -> None:
        self.output.write_bytes(b"existing-output")
        with fake_api([200], remote_video=True) as (server, url), \
                mock.patch.object(self.module, "MAX_VIDEO_BYTES", len(MP4_BYTES) - 1):
            with self.assertRaisesRegex(self.module.VideoDownloadError, "大小上限"):
                self.module._download_video(
                    url + "/video/task-1.mp4", self.output, "test-key", url, 2,
                )
        self.assertEqual(b"existing-output", self.output.read_bytes())
        self.assertEqual([], list(Path(self.tempdir.name).glob("tmp*")))

    def test_direct_script_empty_key_exits_without_traceback(self) -> None:
        skill_copy = Path(self.tempdir.name) / "skill"
        (skill_copy / "scripts").mkdir(parents=True)
        shutil.copy2(SCRIPT, skill_copy / "scripts" / "generate.py")
        (skill_copy / "config.json").write_text('{"api_key": ""}', encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(skill_copy / "scripts" / "generate.py"), "cat"],
            capture_output=True, text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(1, completed.returncode)
        self.assertNotIn("Traceback", completed.stderr)
        self.assertNotIn("NameError", completed.stderr)

    def test_download_redirect_success_and_cross_origin_key_stripping(self) -> None:
        with fake_api([200], remote_video=True, redirect_path="/video/task-1.mp4") as (source, source_url), \
                fake_api([200], remote_video=True) as (target, target_url):
            source.redirect_target = target_url + "/video/task-1.mp4"
            self.module._download_video(source_url + "/video/task-1.mp4", self.output,
                                        "test-key", source_url, 2)
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertEqual("Bearer test-key", source.download_authorization)
        self.assertIsNone(target.download_authorization)

    def test_response_close_failure_does_not_resubmit_and_preserves_output(self) -> None:
        self.output.write_bytes(b"existing-output")
        original_open = self.module._DOWNLOAD_OPENER.open

        class CloseFailureResponse:
            def __init__(self, response):
                self.response = response

            def close(self):
                self.response.close()
                raise http.client.IncompleteRead(b"")

            def read(self, size):
                return self.response.read(size)

        close_failures = 0

        def open_with_close_failure(request, timeout):
            nonlocal close_failures
            response = original_open(request, timeout=timeout)
            if (request.full_url.endswith("/video/task-1.mp4") or
                    request.full_url.endswith("/content")) and close_failures < 2:
                close_failures += 1
                return CloseFailureResponse(response)
            return response

        with fake_api([200, 200], remote_video=True) as (server, url), \
                mock.patch.object(self.module._DOWNLOAD_OPENER, "open",
                                  side_effect=open_with_close_failure):
            with self.assertRaises(self.module.PaidDeliveryError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(b"existing-output", self.output.read_bytes())
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))
        self.assertEqual(2, close_failures)
        self.assertEqual([], list(Path(self.tempdir.name).glob("tmp*")))

    def test_initial_read_failure_does_not_resubmit_and_preserves_output(self) -> None:
        self.output.write_bytes(b"existing-output")
        original_open = self.module._DOWNLOAD_OPENER.open

        class InitialReadFailureResponse:
            def __init__(self, response):
                self.response = response
                self.closed = False

            def close(self):
                self.closed = True
                self.response.close()

            def read(self, size):
                raise http.client.IncompleteRead(b"")

        responses = []

        def open_with_read_failure(request, timeout):
            response = original_open(request, timeout=timeout)
            if len(responses) < 2:
                wrapper = InitialReadFailureResponse(response)
                responses.append(wrapper)
                return wrapper
            return response

        with fake_api([200, 200], remote_video=True) as (server, url), \
                mock.patch.object(self.module._DOWNLOAD_OPENER, "open",
                                  side_effect=open_with_read_failure):
            with self.assertRaises(self.module.PaidDeliveryError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(b"existing-output", self.output.read_bytes())
        self.assertTrue(all(response.closed for response in responses))
        self.assertEqual(1, len([r for r in server.requests if r["method"] == "POST"]))
        self.assertEqual([], list(Path(self.tempdir.name).glob("tmp*")))

    def test_download_rejects_non_http_redirect_without_replacing_output(self) -> None:
        self.output.write_bytes(b"existing-output")
        with fake_api([200], remote_video=True, redirect_path="/video/task-1.mp4",
                      redirect_target="ftp://127.0.0.1:1/video") as (server, url):
            with self.assertRaises(self.module.VideoDownloadError):
                self.module._download_video(url + "/video/task-1.mp4", self.output,
                                            "test-key", url, 2)
        self.assertEqual(b"existing-output", self.output.read_bytes())

    def test_same_origin_content_fallback_uses_key_and_relative_url(self) -> None:
        with fake_api([200], task_statuses=["queued", "completed"], video_url=None) as (server, url):
            result = self.module.generate_video(
                "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                timeout=2, poll_interval=0, max_wait=2,
            )
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertEqual("Bearer test-key", server.download_authorization)
        self.assertEqual("/v1/videos/task-1/content", result.path.name and server.requests[-1]["path"])

    def test_failed_returned_url_retries_same_task_content_without_resubmitting(self) -> None:
        with fake_api([200], remote_video=True) as (server, url):
            server.failed_download_paths = {"/video/task-1.mp4"}
            with self.assertLogs("jihuarst-video", level="INFO") as logs:
                result = self.module.generate_video(
                    "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertEqual("task-1", result.task_id)
        self.assertEqual(1, server.post_count)
        self.assertEqual("Bearer test-key", server.download_authorization)
        paths = [request["path"] for request in server.requests]
        self.assertEqual(1, paths.count("/v1/videos/task-1/content"))
        self.assertTrue(any("task-1" in line for line in logs.output))

    def test_malformed_returned_url_retries_same_task_content(self) -> None:
        with fake_api([200], task_statuses=["queued", "completed"],
                      video_url="http://[invalid") as (server, url):
            result = self.module.generate_video(
                "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                timeout=2, poll_interval=0, max_wait=2,
            )
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertEqual("task-1", result.task_id)
        self.assertEqual(1, server.post_count)
        self.assertEqual("/v1/videos/task-1/content", server.requests[-1]["path"])

    def test_task_id_is_redacted_in_logs_and_json(self) -> None:
        secret = "nonstandard-private-key"
        with fake_api([200], task_statuses=["queued", "completed"],
                      task_id=secret) as (server, url):
            with self.assertLogs("jihuarst-video", level="INFO") as logs:
                result = self.module.generate_video(
                    "cat", self.output, secret, [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(secret, result.task_id)
        self.assertNotIn(secret, "\n".join(logs.output))
        self.assertIn("[REDACTED]", "\n".join(logs.output))
        stdout = io.StringIO()
        with mock.patch.object(self.module, "load_api_key", return_value=secret), \
                mock.patch.object(self.module, "generate_video", return_value=result), \
                mock.patch.object(self.module.sys, "stdout", new=stdout):
            self.assertEqual(0, self.module.main(["cat", "--json"]))
        self.assertNotIn(secret, stdout.getvalue())
        self.assertEqual("[REDACTED]", json.loads(stdout.getvalue())["task_id"])

    def test_completed_task_download_failure_does_not_submit_another_task(self) -> None:
        with fake_api([200, 200], remote_video=True) as (server, url):
            server.failed_download_paths = {"/video/task-1.mp4", "/v1/videos/task-1/content"}
            with self.assertRaises(RuntimeError) as raised:
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(1, server.post_count)
        message = str(raised.exception)
        self.assertIn("计费", message)
        self.assertIn("下载失败", message)
        self.assertIn("未提交新的请求或任务", message)
        self.assertIn("task-1", message)

    def test_same_task_content_fallback_downloads_after_failed_returned_url(self) -> None:
        with fake_api([200], remote_video=True) as (server, url):
            server.failed_download_paths = {"/video/task-1.mp4"}
            result = self.module.generate_video(
                "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                timeout=2, poll_interval=0, max_wait=2,
            )
        self.assertEqual(MP4_BYTES, self.output.read_bytes())
        self.assertEqual("task-1", result.task_id)
        self.assertEqual(1, server.post_count)
        paths = [request["path"] for request in server.requests]
        self.assertEqual(1, paths.count("/video/task-1.mp4"))
        self.assertEqual(1, paths.count("/v1/videos/task-1/content"))

    def test_submission_failure_falls_through_to_next_combination(self) -> None:
        with fake_api([500]) as (first, first_url), \
                fake_api([200], task_statuses=["queued", "completed"], video_url=None) as (second, second_url):
            result = self.module.generate_video(
                "cat", self.output, "test-key", [first_url, second_url], ["minimax-video-h3"],
                timeout=2, poll_interval=0, max_wait=2,
            )
        self.assertEqual(1, first.post_count)
        self.assertEqual(1, second.post_count)
        self.assertEqual(second_url, result.base_url)
        self.assertEqual(MP4_BYTES, self.output.read_bytes())

    def test_terminal_task_state_falls_through_to_next_combination(self) -> None:
        with fake_api([200, 200], task_statuses=["queued", "failed"]) as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(2, server.post_count)

    def test_content_download_failure_includes_task_id(self) -> None:
        with fake_api([200], remote_video=True) as (server, url):
            server.failed_download_paths = {"/video/task-1.mp4", "/v1/videos/task-1/content"}
            with self.assertRaisesRegex(RuntimeError, "task-1"):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(1, server.post_count)
        self.assertFalse(self.output.exists())

    def test_failed_download_does_not_fall_back_to_next_model(self) -> None:
        with fake_api([200, 200], remote_video=True) as (server, url):
            server.download_body = b"not-an-mp4"
            with self.assertRaises(RuntimeError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(1, server.post_count)
        self.assertFalse(self.output.exists())

    def test_failed_download_preserves_preexisting_output(self) -> None:
        self.output.write_bytes(b"existing-output")
        with fake_api([200], remote_video=True, download_body=b"<html>error</html>") as (server, url):
            with self.assertRaises(RuntimeError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], ["minimax-video-h3"],
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(b"existing-output", self.output.read_bytes())
        self.assertEqual([], list(Path(self.tempdir.name).glob("tmp*")))

    def test_actual_download_local_output_error_does_not_resubmit(self) -> None:
        with fake_api([200, 200], remote_video=True) as (server, url), \
                mock.patch.object(self.module.os, "replace", side_effect=PermissionError("read-only")):
            with self.assertRaises(PermissionError):
                self.module.generate_video(
                    "cat", self.output, "test-key", [url], EXPECTED_MODELS,
                    timeout=2, poll_interval=0, max_wait=2,
                )
        self.assertEqual(1, len([request for request in server.requests if request["method"] == "POST"]))
        self.assertFalse(self.output.exists())
        self.assertEqual([], list(Path(self.tempdir.name).glob("tmp*")))

    def test_cli_model_and_base_url(self) -> None:
        result = self.module.GenerationResult("http://127.0.0.1:1", "kling-video-v3", "task-1", self.output)
        with mock.patch.object(self.module, "load_api_key", return_value="test-key"), \
                mock.patch.object(self.module, "generate_video", return_value=result) as generate:
            status = self.module.main([
                "cat", "-o", str(self.output), "--model", "kling-video-v3",
                "--base-url", "http://127.0.0.1:1", "--seconds", "7", "--size", "1280x720",
                "--timeout", "2", "--poll-interval", "0", "--max-wait", "3", "-r", str(self.ref),
            ])
        self.assertEqual(0, status)
        generate.assert_called_once_with(
            "cat", self.output, "test-key", ["http://127.0.0.1:1"], ["kling-video-v3"],
            timeout=2, poll_interval=0, max_wait=3, seconds=7, size="1280x720", reference=self.ref,
        )

    def test_cli_invalid_model_is_rejected(self) -> None:
        with mock.patch.object(self.module, "load_api_key") as load_key, \
                mock.patch.object(self.module.sys, "stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                self.module.main(["cat", "--model", "unknown"])
        self.assertNotEqual(0, raised.exception.code)
        load_key.assert_not_called()

    def test_cli_json_success_fields(self) -> None:
        result = self.module.GenerationResult("http://127.0.0.1:1", "minimax-video-h3", "task-1", self.output)
        stdout = io.StringIO()
        with mock.patch.object(self.module, "load_api_key", return_value="test-key"), \
                mock.patch.object(self.module, "generate_video", return_value=result), \
                mock.patch.object(self.module.sys, "stdout", new=stdout):
            status = self.module.main(["cat", "-o", str(self.output), "--json"])
        self.assertEqual(0, status)
        self.assertEqual({"base_url": result.base_url, "model": result.model,
                          "task_id": result.task_id, "path": str(self.output)}, json.loads(stdout.getvalue()))

    def test_cli_generation_failure_returns_nonzero(self) -> None:
        stderr = io.StringIO()
        with mock.patch.object(self.module, "load_api_key", return_value="test-key"), \
                mock.patch.object(self.module, "generate_video", side_effect=RuntimeError("offline test-key")), \
                mock.patch.object(self.module.sys, "stderr", new=stderr):
            status = self.module.main(["cat"])
        self.assertEqual(1, status)
        self.assertIn("[REDACTED]", stderr.getvalue())
        self.assertNotIn("test-key", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
