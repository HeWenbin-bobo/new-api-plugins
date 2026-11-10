"""Offline tests for the New API Local Document OCR CLI."""

from __future__ import annotations

import argparse
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from scripts import parse


PNG = b"\x89PNG\r\n\x1a\noffline-test-image"


class Handler(BaseHTTPRequestHandler):
    """Record requests without logging document bytes or authorization."""

    def _json_response(self, status: int, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        server = self.server
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        server.submissions += 1
        server.auth_headers.append(self.headers.get("Authorization"))
        server.content_types.append(self.headers.get("Content-Type"))
        server.bodies.append(body)
        if server.submit_http_status != 200:
            self._json_response(server.submit_http_status, {"error": {"message": server.failure_reason}})
            return
        if server.application_error:
            self._json_response(200, {"error": {"message": server.failure_reason}})
            return
        self._json_response(200, {"task_id": server.task_id, "status": "queued"})

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        server = self.server
        parsed = urllib.parse.urlsplit(self.path)
        server.download_auth_headers.append(self.headers.get("Authorization"))
        if parsed.path == f"/v1/tasks/{server.task_id}":
            server.polls += 1
            if server.poll_application_error:
                self._json_response(200, {"error": {"message": server.failure_reason}})
                return
            if server.unknown_status:
                status = "UNRECOGNIZED"
            elif server.task_failure:
                status = "FAILURE"
            elif server.stuck:
                status = "IN_PROGRESS"
            else:
                status = "IN_PROGRESS" if server.polls == 1 else "SUCCESS"
            self._json_response(200, {"task_id": server.task_id, "status": status, "progress": "100%" if status == "SUCCESS" else "0%", "fail_reason": server.failure_reason if status == "FAILURE" else ""})
            return
        if parsed.path == f"/v1/tasks/{server.task_id}/artifacts":
            if server.artifacts_application_error:
                self._json_response(200, {"error": {"message": server.failure_reason}})
                return
            self._json_response(200, {"task_id": server.task_id, "artifacts": [{"key": key, "type": "file"} for key in server.artifact_keys]})
            return
        if parsed.path.startswith(f"/v1/tasks/{server.task_id}/artifacts/") and parsed.path.endswith("/content"):
            if server.download_http_status != 200:
                self._json_response(server.download_http_status, {"error": {"message": server.failure_reason}})
                return
            if server.cross_origin_redirect:
                self.send_response(307)
                self.send_header("Location", server.cross_origin_redirect)
                self.end_headers()
                return
            artifact = parsed.path.rsplit("/", 2)[-2]
            body = server.artifact_bodies.get(artifact, b"# offline OCR\n")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json_response(404, {"error": {"message": "unknown fixture path"}})

    def log_message(self, *args) -> None:
        pass


class FakeServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.task_id = "task_offline_1"
        self.submissions = 0
        self.polls = 0
        self.auth_headers = []
        self.download_auth_headers = []
        self.content_types = []
        self.bodies = []
        self.artifact_keys = ["markdown", "json", "package"]
        self.artifact_bodies = {}
        self.submit_http_status = 200
        self.application_error = False
        self.poll_application_error = False
        self.artifacts_application_error = False
        self.download_http_status = 200
        self.failure_reason = "fixture failure"
        self.task_failure = False
        self.unknown_status = False
        self.stuck = False
        self.cross_origin_redirect = None


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.document = self.root / "input.png"
        self.document.write_bytes(PNG)
        self.server = FakeServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.key = "sk-offline-test-key"
        self.client = parse.NewAPIOCRClient(self.base_url, self.key, timeout=2)
        self.zip_bytes = self.make_zip()

    @staticmethod
    def make_zip() -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("markdown.md", "# offline OCR\n")
        return stream.getvalue()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def test_configuration_is_required(self) -> None:
        with self.assertRaises(parse.OCRError):
            parse.load_configuration(self.root / "missing.json")
        with self.assertRaises(parse.OCRError):
            parse.NewAPIOCRClient("", self.key)
        with self.assertRaises(parse.OCRError):
            parse.NewAPIOCRClient(self.base_url, "")

    def test_multipart_submission_poll_and_markdown(self) -> None:
        task_id = self.client.submit(self.document, "mineru-pipeline-cpu")
        self.assertEqual(task_id, self.server.task_id)
        self.assertEqual(self.client.poll(task_id, 0, 2)["status"], "SUCCESS")
        self.assertEqual(len(self.client.artifacts(task_id)), 3)
        output = self.client.download(task_id, "markdown", self.root / "result.md")
        self.assertEqual(output.read_text(), "# offline OCR\n")
        body = self.server.bodies[0]
        self.assertIn(b'name="model"', body)
        self.assertIn(b"mineru-pipeline-cpu", body)
        self.assertIn(PNG, body)
        self.assertTrue(all(value == f"Bearer {self.key}" for value in self.server.auth_headers + self.server.download_auth_headers))
        self.assertEqual(self.server.submissions, 1)

    def test_pdf_is_accepted(self) -> None:
        document = self.root / "paper.pdf"
        document.write_bytes(b"%PDF-1.4\noffline")
        self.assertEqual(self.client.submit(document, "mineru-pipeline-cpu"), self.server.task_id)

    def test_json_and_zip_artifacts(self) -> None:
        self.server.artifact_bodies["json"] = b'{"pages": 1}'
        self.server.artifact_bodies["package"] = self.zip_bytes
        self.assertEqual(json.loads(self.client.download(self.server.task_id, "json", self.root / "result.json").read_text())["pages"], 1)
        self.assertTrue(zipfile.is_zipfile(self.client.download(self.server.task_id, "package", self.root / "result.zip")))

    def test_corrupt_zip_preserves_existing_output(self) -> None:
        self.server.artifact_bodies["package"] = b"not a zip"
        output = self.root / "existing.zip"
        output.write_bytes(self.zip_bytes)
        with self.assertRaises(parse.OCRError):
            self.client.download(self.server.task_id, "package", output, overwrite=True)
        self.assertEqual(output.read_bytes(), self.zip_bytes)

    def test_existing_output_is_not_overwritten(self) -> None:
        output = self.root / "result.md"
        output.write_text("valid previous output")
        with self.assertRaises(parse.OCRError):
            self.client.download(self.server.task_id, "markdown", output)
        self.assertEqual(output.read_text(), "valid previous output")

    def test_task_failure_is_terminal(self) -> None:
        self.server.task_failure = True
        with self.assertRaisesRegex(parse.OCRError, "failed"):
            self.client.poll(self.server.task_id, 0, 2)
        self.assertEqual(self.server.submissions, 0)

    def test_unknown_status_is_not_success(self) -> None:
        self.server.unknown_status = True
        with self.assertRaisesRegex(parse.OCRError, "unknown status"):
            self.client.poll(self.server.task_id, 0, 2)

    def test_timeout_does_not_submit_again_or_cancel(self) -> None:
        self.server.stuck = True
        with self.assertRaises(parse.TaskTimeout) as caught:
            self.client.poll(self.server.task_id, 0, 0.03)
        self.assertIn("not canceled", str(caught.exception))
        self.assertEqual(self.server.submissions, 0)

    def test_download_failure_does_not_submit_again(self) -> None:
        self.server.download_http_status = 502
        with self.assertRaisesRegex(parse.OCRError, "502"):
            self.client.download(self.server.task_id, "markdown", self.root / "result.md")
        self.assertEqual(self.server.submissions, 0)

    def test_cross_origin_redirect_does_not_forward_key(self) -> None:
        self.server.cross_origin_redirect = "http://example.com/stolen"
        with self.assertRaisesRegex(parse.OCRError, "Cross-origin"):
            self.client.download(self.server.task_id, "markdown", self.root / "result.md")
        self.assertTrue(all(value != self.key for value in self.server.download_auth_headers))

    def test_invalid_inputs_and_parameters(self) -> None:
        for name, value in (("input.txt", b"text"), ("empty.pdf", b"")):
            document = self.root / name
            document.write_bytes(value)
            with self.assertRaises(parse.OCRError):
                self.client.submit(document, "mineru-pipeline-cpu")
        for value in ("ftp://example.com", "https://user:password@example.com", "https://example.com?key=value"):
            with self.assertRaises(parse.OCRError):
                parse.normalize_base_url(value)
        with self.assertRaises(parse.OCRError):
            self.client.submit(self.document, "unconfigured-model")
        with self.assertRaises(parse.OCRError):
            self.client.download("bad/task", "markdown", self.root / "x")
        with self.assertRaises(parse.OCRError):
            self.client.download(self.server.task_id, "../outside", self.root / "x")

    def test_application_error_redacts_nonstandard_token(self) -> None:
        key = "offline-nonstandard-token"
        client = parse.NewAPIOCRClient(self.base_url, key, timeout=2)
        self.server.application_error = True
        self.server.failure_reason = f"upstream rejected Bearer {key}"
        with self.assertRaises(parse.OCRError) as caught:
            client.submit(self.document, "mineru-pipeline-cpu")
        self.assertNotIn(key, str(caught.exception))

    def test_redaction(self) -> None:
        sanitized = parse.redact(f"Bearer {self.key} https://example.com?access=secret", (self.key,))
        self.assertNotIn(self.key, sanitized)
        self.assertNotIn("secret", sanitized)


class CLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.server = FakeServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.document = self.root / "input.png"
        self.document.write_bytes(PNG)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({"api_key": "sk-cli-test-key", "base_url": f"http://127.0.0.1:{self.server.server_port}", "poll_interval": 0, "max_wait": 3}))
        self.output = self.root / "result.md"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.tempdir.cleanup()

    def arguments(self, *extra: str) -> list[str]:
        return [str(self.document), "--config", str(self.config), "-o", str(self.output), *extra]

    def test_cli_success_and_machine_summary(self) -> None:
        with mock.patch("sys.stdout", new=io.StringIO()) as stdout:
            result = parse.main(self.arguments("--json"))
        self.assertEqual(result, 0)
        summary = json.loads(stdout.getvalue())
        self.assertEqual(summary["task_id"], self.server.task_id)
        self.assertEqual(summary["model"], "mineru-pipeline-cpu")
        self.assertNotIn("api_key", summary)
        self.assertTrue(self.output.read_text().strip())

    def test_cli_missing_key_fails_before_submission(self) -> None:
        self.config.write_text(json.dumps({"base_url": self.config and f"http://127.0.0.1:{self.server.server_port}"}))
        with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertEqual(self.server.submissions, 0)
        self.assertNotIn("sk-cli-test-key", stderr.getvalue())

    def test_cli_existing_output_fails_before_submission(self) -> None:
        self.output.write_text("keep")
        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertEqual(self.server.submissions, 0)
        self.assertEqual(self.output.read_text(), "keep")

    def test_cli_download_failure_preserves_public_task_id(self) -> None:
        self.server.download_http_status = 502
        with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertIn(self.server.task_id, stderr.getvalue())
        self.assertIn("502", stderr.getvalue())
        self.assertEqual(self.server.submissions, 1)
        self.assertFalse(self.output.exists())

    def test_cli_poll_error_preserves_public_task_id(self) -> None:
        self.server.poll_application_error = True
        self.server.failure_reason = "poll rejected"
        with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertIn(self.server.task_id, stderr.getvalue())
        self.assertIn("poll rejected", stderr.getvalue())
        self.assertEqual(self.server.submissions, 1)

    def test_cli_artifacts_error_preserves_public_task_id(self) -> None:
        self.server.artifacts_application_error = True
        self.server.failure_reason = "artifacts rejected"
        with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertIn(self.server.task_id, stderr.getvalue())
        self.assertIn("artifacts rejected", stderr.getvalue())
        self.assertEqual(self.server.submissions, 1)

    def test_cli_invalid_download_preserves_id_and_existing_output(self) -> None:
        for artifact, body, output in (
            ("markdown", b"\xff", self.root / "result.md"),
            ("package", b"not a zip", self.root / "result.zip"),
        ):
            with self.subTest(artifact=artifact):
                self.server.submissions = 0
                self.server.polls = 0
                self.server.artifact_bodies[artifact] = body
                output.write_bytes(b"keep")
                with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
                    self.assertEqual(parse.main(self.arguments("--artifact", artifact, "--overwrite")), 1)
                self.assertIn(self.server.task_id, stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                self.assertEqual(self.server.submissions, 1)
                self.assertEqual(output.read_bytes(), b"keep")
        self.server.artifact_bodies["markdown"] = b""
        self.output = self.root / "empty.md"
        with mock.patch("sys.stderr", new=io.StringIO()) as stderr:
            self.assertEqual(parse.main(self.arguments()), 1)
        self.assertIn(self.server.task_id, stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_cli_paddle_is_explicit(self) -> None:
        with mock.patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(parse.main(self.arguments("--model", "paddleocr-vl-1.6-cpu", "--json")), 0)
        self.assertIn(b"paddleocr-vl-1.6-cpu", self.server.bodies[0])


if __name__ == "__main__":
    unittest.main()
