"""Loopback-only scene editor and bounded, credential-free renderer."""

import argparse
import copy
import json
import math
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import zipfile
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "studio"
MAX_BODY = 128 * 1024
MAX_ARTIFACT = 100 * 1024 * 1024


class SpecError(ValueError):
    pass


def validate_spec(value):
    """Validate the Studio subset independently of the permissive CLI schema."""

    def object_fields(obj, allowed, where):
        if not isinstance(obj, dict) or set(obj) - set(allowed):
            raise SpecError(f"{where}: expected an object with supported fields only.")

    def text(value, where, maximum=600):
        if not isinstance(value, str) or len(value) > maximum:
            raise SpecError(f"{where}: use text of at most {maximum} characters.")

    def number(value, where, low, high):
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not low <= value <= high
            or not math.isfinite(value)
        ):
            raise SpecError(f"{where}: use a number between {low} and {high}.")

    object_fields(value, ("meta", "theme", "timeline", "voice"), "Project")
    spec = copy.deepcopy(value)
    meta = spec.setdefault("meta", {})
    object_fields(meta, ("title", "fps", "resolution"), "Project settings")
    text(meta.get("title", ""), "Project title", 100)
    if meta.get("fps", 30) not in (24, 30):
        raise SpecError("Frame rate: choose 24 or 30 fps.")
    if "resolution" in meta and meta["resolution"] != {"width": 1920, "height": 1080}:
        raise SpecError("Resolution: Studio supports 1920 × 1080 only.")
    theme = spec.setdefault("theme", {})
    object_fields(
        theme, ("preset", "bg", "fg", "accent", "font_size", "title_font_size"), "Theme"
    )
    if theme.get("preset", "dark") not in ("dark", "light"):
        raise SpecError("Theme: choose dark or light.")
    for key in ("bg", "fg", "accent"):
        if key in theme and (
            not isinstance(theme[key], str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", theme[key])
        ):
            raise SpecError(f"Theme {key}: use a six-digit hex colour.")
    for key in ("font_size", "title_font_size"):
        if key in theme:
            number(theme[key], f"Theme {key}", 24, 120)
            if not isinstance(theme[key], int):
                raise SpecError(f"Theme {key}: use a whole number.")
    if "voice" in spec:
        object_fields(spec["voice"], ("slug", "voice_id", "model", "format"), "Voice")
        for key, item in spec["voice"].items():
            text(item, f"Voice {key}", 100)
    scenes = spec.get("timeline")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 12:
        raise SpecError("Timeline: include between 1 and 12 scenes.")
    duration = 0
    common = ("type", "duration", "anim", "narration", "padding")
    fields = {
        "title": ("text", "subtitle"),
        "outro": ("text",),
        "bullets": ("heading", "items", "stagger", "narration_per_bullet"),
        "chart": ("heading", "chart_type", "labels", "values", "y_label"),
    }
    for index, scene in enumerate(scenes, 1):
        where = f"Scene {index}"
        if (
            not isinstance(scene, dict)
            or not isinstance(scene.get("type"), str)
            or scene["type"] not in fields
        ):
            raise SpecError(
                f"{where}: choose title, bullets, chart or outro. Image scenes are CLI-only."
            )
        kind = scene["type"]
        object_fields(scene, common + fields[kind], where)
        for key in ("text", "subtitle", "heading", "y_label", "narration"):
            if key in scene:
                text(scene[key], f"{where} {key}", 1200 if key == "narration" else 300)
        if kind in ("title", "outro") and not scene.get("text", "").strip():
            raise SpecError(f"{where}: add some text.")
        if scene.get("anim", "fade") not in ("fade", "slide-up", "zoom-in"):
            raise SpecError(f"{where}: unsupported animation.")
        if "padding" in scene:
            number(scene["padding"], f"{where} padding", 0, 3)
        if kind == "bullets":
            items = scene.get("items")
            if not isinstance(items, list) or not 1 <= len(items) <= 6:
                raise SpecError(f"{where}: add between 1 and 6 bullets.")
            for item in items:
                text(item, f"{where} bullet", 180)
                if not item.strip():
                    raise SpecError(f"{where}: bullets cannot be empty.")
            number(scene.get("stagger", 0.4), f"{where} stagger", 0, 2)
            if "narration_per_bullet" in scene:
                narrations = scene["narration_per_bullet"]
                if not isinstance(narrations, list) or len(narrations) != len(items):
                    raise SpecError(
                        f"{where}: per-bullet narration must match the bullets."
                    )
                for item in narrations:
                    text(item, f"{where} narration", 1200)
        if kind == "chart":
            labels, values = scene.get("labels"), scene.get("values")
            if (
                not isinstance(labels, list)
                or not isinstance(values, list)
                or not 1 <= len(labels) <= 8
                or len(labels) != len(values)
            ):
                raise SpecError(
                    f"{where}: supply 1–8 matching chart labels and values."
                )
            for label in labels:
                text(label, f"{where} label", 40)
            for item in values:
                number(item, f"{where} chart value", -1000000, 1000000)
            scene.setdefault("chart_type", "bar")
            if scene["chart_type"] not in ("bar", "line", "pie"):
                raise SpecError(f"{where}: choose bar, line or pie.")
            if scene["chart_type"] == "pie" and (
                any(v < 0 for v in values) or sum(values) <= 0
            ):
                raise SpecError(
                    f"{where}: pie values must be non-negative with a positive total."
                )
        scene.setdefault("duration", 4)
        number(scene["duration"], f"{where} duration", 1, 15)
        duration += scene["duration"]
    if duration > 60:
        raise SpecError("Timeline: keep the total duration at 60 seconds or less.")
    return spec


def silent_spec(spec):
    result = copy.deepcopy(spec)
    result.pop("voice", None)
    for scene in result["timeline"]:
        scene.pop("narration", None)
        scene.pop("narration_per_bullet", None)
    return result


class RenderJobs:
    def __init__(self, timeout=180):
        self.lock = threading.Lock()
        self.job = None
        self.process = None
        self.closed = False
        self.timeout = timeout
        self.storage = tempfile.TemporaryDirectory(prefix="video-studio-")

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def start(self, spec):
        with self.lock:
            if self.closed or (self.job and self.job["state"] == "rendering"):
                raise RuntimeError(
                    "A render is already running. Wait for it to finish."
                )
            # Keep downloads stable throughout this session; bounded to ten renders.
            if len(list(Path(self.storage.name).iterdir())) >= 10:
                raise RuntimeError(
                    "Session limit reached. Export your JSON and restart Studio."
                )
            job_id = secrets.token_hex(16)
            directory = Path(self.storage.name) / job_id
            directory.mkdir(mode=0o700)
            (directory / "spec.json").write_text(json.dumps(silent_spec(spec)))
            self.job = {
                "id": job_id,
                "state": "rendering",
                "message": "Rendering on your computer…",
                "artifacts": [],
            }
            threading.Thread(
                target=self._render, args=(job_id, directory), daemon=True
            ).start()
            return copy.deepcopy(self.job)

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    def _render(self, job_id, directory):
        # Explicit allowlist: no inherited API keys, Python injection or cloud credentials.
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT")
            if key in os.environ
        }
        environment["MPLCONFIGDIR"] = str(directory / "matplotlib")
        message, artifacts, state = (
            "Render failed. Check that the renderer dependencies are installed.",
            [],
            "failed",
        )
        try:
            with self.lock:
                if self.closed:
                    return
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(ROOT / "src/render.py"),
                        str(directory / "spec.json"),
                        "-o",
                        str(directory / "video.mp4"),
                        "--workdir",
                        str(directory / "cache"),
                    ],
                    cwd=directory,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                self.process = process
            try:
                returncode = process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired as error:
                self.terminate(process)
                raise RuntimeError(
                    "Render exceeded three minutes. Shorten the timeline and try again."
                ) from error
            if returncode != 0:
                raise RuntimeError(message)
            mp4 = directory / "video.mp4"
            if not mp4.is_file() or not 0 < mp4.stat().st_size <= MAX_ARTIFACT:
                raise RuntimeError("The renderer did not produce a usable video.")
            artifacts.append("mp4")
            pptx = directory / "video.pptx"
            if (
                pptx.is_file()
                and 0 < pptx.stat().st_size <= MAX_ARTIFACT
                and zipfile.is_zipfile(pptx)
            ):
                with zipfile.ZipFile(pptx) as archive:
                    if "ppt/presentation.xml" in archive.namelist():
                        artifacts.append("pptx")
            state = "complete"
            message = (
                "Video and PowerPoint are ready."
                if "pptx" in artifacts
                else "Video ready. PowerPoint export failed; only the video is available."
            )
        except (OSError, RuntimeError, zipfile.BadZipFile) as error:
            message = str(error)
        finally:
            with self.lock:
                self.process = None
                self.job = {
                    "id": job_id,
                    "state": state,
                    "message": message,
                    "artifacts": artifacts,
                }

    def artifact(self, job_id, extension):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id) or extension not in (
            "mp4",
            "pptx",
        ):
            return None
        path = Path(self.storage.name) / job_id / f"video.{extension}"
        with self.lock:
            if (
                self.job
                and self.job["id"] == job_id
                and self.job["state"] == "rendering"
            ):
                return None
        return (
            path if path.is_file() and 0 < path.stat().st_size <= MAX_ARTIFACT else None
        )

    def close(self):
        with self.lock:
            self.closed = True
            process = self.process
        if process:
            self.terminate(process)
        self.storage.cleanup()


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, jobs):
        super().__init__(address, StudioHandler)
        self.jobs = jobs
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class StudioHandler(BaseHTTPRequestHandler):
    @property
    def studio(self) -> StudioServer:
        return cast(StudioServer, self.server)

    def log_message(self, format, *args):
        pass

    def reply(self, status, data, content_type="application/json"):
        body = json.dumps(data).encode() if content_type == "application/json" else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def allowed(self, protected=False):
        host = self.headers.get("Host")
        if host not in (
            f"127.0.0.1:{self.studio.server_port}",
            f"localhost:{self.studio.server_port}",
        ):
            return False
        # Each alias is its own origin; do not allow cross-origin alias requests.
        if self.headers.get("Origin") not in (None, f"http://{host}"):
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return False
        return not protected or secrets.compare_digest(
            self.headers.get("X-Studio-Token", ""), self.studio.token
        )

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.allowed(
            self.path.startswith("/api/") and self.path != "/api/bootstrap"
        ):
            self.reply(403, {"error": "This request is not from the local Studio."})
            return
        if self.path == "/api/bootstrap":
            self.reply(
                200, {"token": self.studio.token, "job": self.studio.jobs.snapshot()}
            )
        elif self.path == "/api/job":
            self.reply(200, {"job": self.studio.jobs.snapshot()})
        elif self.path.startswith("/api/artifact/"):
            parts = self.path.split("/")
            path = (
                self.studio.jobs.artifact(parts[3], parts[4])
                if len(parts) == 5
                else None
            )
            if path:
                self.reply(
                    200,
                    path.read_bytes(),
                    "video/mp4"
                    if parts[4] == "mp4"
                    else "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            else:
                self.reply(404, {"error": "Artifact unavailable."})
        else:
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            if self.path in files:
                name, mime = files[self.path]
                self.reply(200, (WEB / name).read_bytes(), mime)
            else:
                self.reply(404, {"error": "Not found."})

    def do_POST(self):
        if not self.allowed(True):
            self.reply(403, {"error": "This request is not from the local Studio."})
            return
        if self.path != "/api/render":
            self.reply(404, {"error": "Not found."})
            return
        try:
            if self.headers.get("Content-Type") != "application/json":
                raise SpecError("Send a JSON project.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise SpecError("Project must be smaller than 128 KB.")
            spec = validate_spec(json.loads(self.rfile.read(length)))
            self.reply(202, self.studio.jobs.start(spec))
        except (ValueError, UnicodeDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except RuntimeError as error:
            self.reply(409, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    jobs = RenderJobs()
    server = StudioServer(("127.0.0.1", args.port), jobs)
    print(f"Video Studio: {server.origin} (Ctrl+C to stop)", flush=True)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        jobs.close()


if __name__ == "__main__":
    main()
