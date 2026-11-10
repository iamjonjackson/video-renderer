"""Studio safety and real loopback API checks; no paid provider calls."""

import copy
import http.client
import importlib
import json
import os
import signal
import subprocess
import sys
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
studio = importlib.import_module("src.studio")
RenderJobs, SpecError = studio.RenderJobs, studio.SpecError
StudioServer = studio.StudioServer
silent_spec, validate_spec = studio.silent_spec, studio.validate_spec

BASE = {
    "meta": {"title": "Test"},
    "timeline": [{"type": "title", "text": "Hello", "duration": 1}],
}


class ValidationTests(unittest.TestCase):
    def test_silent_copy_preserves_authored_narration(self):
        spec = copy.deepcopy(BASE)
        spec["timeline"][0]["narration"] = "Do not send this to a provider"
        spec["voice"] = {"slug": "gb_jane_neutral"}
        result = silent_spec(validate_spec(spec))
        self.assertNotIn("voice", result)
        self.assertNotIn("narration", result["timeline"][0])
        self.assertIn("narration", spec["timeline"][0])

    def test_silent_copy_drops_tts_provider_settings(self):
        spec = copy.deepcopy(BASE)
        spec["meta"]["tts"] = {"provider": "google", "voice": "Kore"}
        result = silent_spec(validate_spec(spec))
        self.assertNotIn("tts", result["meta"])
        self.assertEqual(spec["meta"]["tts"]["provider"], "google")

    def test_rejects_unknown_tts_fields(self):
        spec = copy.deepcopy(BASE)
        spec["meta"]["tts"] = {"provider": "google", "api_key": "never"}
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_converted_bullet_notes_keep_all_narration(self):
        spec = {
            "meta": {"title": "Notes"},
            "timeline": [
                {
                    "type": "composition",
                    "duration": 4,
                    "elements": [],
                    "narration": "a" * 700 + "\n" + "b" * 700,
                }
            ],
        }
        self.assertEqual(
            validate_spec(spec)["timeline"][0]["narration"],
            spec["timeline"][0]["narration"],
        )
        spec["timeline"][0]["narration"] = "x" * 7206
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_bad_specs_rejected(self):
        invalid = [
            {"timeline": []},
            {"timeline": [{"type": [], "text": "x"}]},
            {"timeline": [{"type": "title", "text": "x", "duration": 10**400}]},
            {"timeline": [{"type": "image", "src": "/etc/passwd"}]},
            {"timeline": [{"type": "title", "text": "x", "image": {"prompt": "paid"}}]},
            {"timeline": [{"type": "title", "text": "x", "duration": float("nan")}]},
            {"timeline": [{"type": "title", "text": "x", "duration": True}]},
            {"theme": {"preset": "__dict__"}, **BASE},
            {"timeline": [{"type": "chart", "labels": ["x"], "values": []}]},
            {
                "timeline": [
                    {
                        "type": "chart",
                        "chart_type": "pie",
                        "labels": ["x"],
                        "values": [-1],
                    }
                ]
            },
            {"timeline": [{"type": "title", "text": "x", "duration": 15}] * 5},
        ]
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(SpecError):
                validate_spec(spec)

    def test_chart_default_is_materialized_without_mutation(self):
        spec = {"timeline": [{"type": "chart", "labels": ["x"], "values": [1]}]}
        self.assertEqual(validate_spec(spec)["timeline"][0]["chart_type"], "bar")
        self.assertNotIn("chart_type", spec["timeline"][0])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.jobs = RenderJobs()
        self.server = StudioServer(("127.0.0.1", 0), self.jobs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.jobs.close()
        self.thread.join()

    def request(self, path, method="GET", data=None, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        connection.request(
            method, path, json.dumps(data) if data is not None else None, headers or {}
        )
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_host_origin_and_token_gates(self):
        self.assertEqual(self.request("/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(
            self.request("/api/bootstrap", headers={"Origin": "https://evil.example"})[
                0
            ],
            403,
        )
        self.assertEqual(self.request("/api/job")[0], 403)
        self.assertEqual(
            self.request("/api/job", headers={"X-Studio-Token": self.server.token})[0],
            200,
        )
        self.assertEqual(
            self.request(
                "/api/render", "POST", BASE, {"Content-Type": "application/json"}
            )[0],
            403,
        )

    def test_localhost_alias_and_head(self):
        host = f"localhost:{self.server.server_port}"
        headers = {"Host": host, "Origin": f"http://{host}"}
        status, body = self.request("/", headers=headers)
        self.assertEqual(status, 200)
        self.assertIn(b"Video Studio", body)
        status, body = self.request("/", method="HEAD", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")
        headers["X-Studio-Token"] = self.server.token
        self.assertEqual(self.request("/api/job", headers=headers)[0], 200)
        headers["Origin"] = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("/api/job", headers=headers)[0], 403)

    def test_invalid_spec_does_not_launch(self):
        with patch.object(self.jobs, "start") as start:
            invalid = [
                {"timeline": []},
                {"timeline": [{"type": []}]},
                {"timeline": [{"type": "title", "text": "x", "duration": 10**400}]},
            ]
            for spec in invalid:
                status, _ = self.request(
                    "/api/render",
                    "POST",
                    {"spec": spec, "format": "video"},
                    {
                        "Content-Type": "application/json",
                        "X-Studio-Token": self.server.token,
                    },
                )
                self.assertEqual(status, 400)
            start.assert_not_called()

    def test_validation_and_export_format_wiring(self):
        headers = {
            "Content-Type": "application/json",
            "X-Studio-Token": self.server.token,
        }
        status, body = self.request("/api/validate", "POST", BASE, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["spec"]["timeline"][0]["text"], "Hello")
        with patch.object(
            self.jobs, "start", return_value={"state": "rendering"}
        ) as start:
            status, _ = self.request(
                "/api/render", "POST", {"spec": BASE, "format": "pptx"}, headers
            )
            self.assertEqual(status, 202)
            self.assertEqual(start.call_args.args[1], "pptx")
        with self.assertRaises(SpecError):
            self.jobs.start(BASE, "shell")

    def test_hosted_generation_removed_and_browser_assets_confined(self):
        headers = {
            "X-Studio-Token": self.server.token,
            "Content-Type": "application/json",
        }
        self.assertEqual(
            self.request(
                "/api/generate",
                "POST",
                {"brief": "Private brief", "consent": True},
                headers,
            )[0],
            404,
        )
        for path in (
            "/ai-assets/../app.js",
            "/ai-assets/smollm2.gguf/../../app.js",
            "/ai-assets/unlisted.js",
        ):
            self.assertEqual(self.request(path)[0], 404)
        status, body = self.request("/ai-worker.js")
        self.assertEqual(status, 200)
        self.assertIn(b"loadModelFromUrl", body)
        self.assertNotIn(
            "generation_enabled", json.loads(self.request("/api/bootstrap")[1])
        )

    def test_pptx_only_does_not_require_or_offer_video(self):
        directory = Path(self.jobs.storage.name) / "deck"
        directory.mkdir()
        with zipfile.ZipFile(directory / "video.pptx", "w") as archive:
            archive.writestr("ppt/presentation.xml", "<presentation/>")

        class Process:
            def wait(self, timeout=None):
                return 0

        with patch("src.studio.subprocess.Popen", return_value=Process()) as launch:
            self.jobs._render("a" * 32, directory, "pptx")
            self.assertIn("--pptx-only", launch.call_args.args[0])
        self.assertEqual(self.jobs.snapshot()["artifacts"], ["pptx"])
        self.assertFalse((directory / "video.mp4").exists())

    def test_traversal_cannot_read_files(self):
        for path in ("/../README.md", "/api/artifact/../../README.md", "/.env"):
            self.assertEqual(
                self.request(path, headers={"X-Studio-Token": self.server.token})[0],
                404,
            )

    def test_duplicate_render_rejected(self):
        self.jobs.job = {"id": "a" * 32, "state": "rendering", "artifacts": []}
        with self.assertRaises(RuntimeError):
            self.jobs.start(BASE)

    def test_session_limit(self):
        for index in range(10):
            (Path(self.jobs.storage.name) / str(index)).mkdir()
        with self.assertRaisesRegex(RuntimeError, "Session limit"):
            self.jobs.start(BASE)

    def test_timeout_kills_process_group(self):
        class Process:
            pid = 12345

            def wait(self, timeout=None):
                if timeout is not None:
                    raise subprocess.TimeoutExpired("render", timeout)
                return -9

            def poll(self):
                return None

        directory = Path(self.jobs.storage.name) / "timeout"
        directory.mkdir()
        with (
            patch("src.studio.subprocess.Popen", return_value=Process()),
            patch("src.studio.os.killpg") as kill,
        ):
            self.jobs._render("a" * 32, directory)
            kill.assert_called_once_with(12345, signal.SIGKILL)
            self.assertIn("exceeded", self.jobs.snapshot()["message"])

    def test_artifact_success_and_partial_export(self):
        for pptx_available in (False, True):
            directory = Path(self.jobs.storage.name) / str(pptx_available)
            directory.mkdir()
            (directory / "video.mp4").write_bytes(b"video-fixture")
            if pptx_available:
                with zipfile.ZipFile(directory / "video.pptx", "w") as archive:
                    archive.writestr("ppt/presentation.xml", "<presentation/>")

            class Process:
                def wait(self, timeout=None):
                    return 0

            with patch("src.studio.subprocess.Popen", return_value=Process()):
                self.jobs._render("a" * 32, directory)
            snapshot = self.jobs.snapshot()
            self.assertEqual(snapshot["state"], "complete")
            self.assertEqual(
                snapshot["artifacts"], ["mp4", "pptx"] if pptx_available else ["mp4"]
            )
            if not pptx_available:
                self.assertIn("PowerPoint export failed", snapshot["message"])

    def test_render_environment_excludes_credentials(self):
        class Process:
            def wait(self, timeout=None):
                return 1

        with (
            patch.dict(
                os.environ,
                {
                    "MISTRAL_API_KEY": "never-send",
                    "AWS_SECRET_ACCESS_KEY": "never-send",
                },
            ),
            patch("src.studio.subprocess.Popen", return_value=Process()) as launch,
        ):
            directory = Path(self.jobs.storage.name) / "a"
            directory.mkdir()
            self.jobs._render("a" * 32, directory)
            environment = launch.call_args.kwargs["env"]
            self.assertNotIn("MISTRAL_API_KEY", environment)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)
            self.assertTrue(launch.call_args.kwargs["start_new_session"])
            snapshot = self.jobs.snapshot()
            assert snapshot is not None
            self.assertEqual(snapshot["state"], "failed")


if __name__ == "__main__":
    unittest.main()
