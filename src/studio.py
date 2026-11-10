"""Loopback-only scene editor and bounded, credential-free renderer."""

import argparse
import copy
import importlib
import json
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
MAX_BODY = 3 * 1024 * 1024
MAX_ARTIFACT = 100 * 1024 * 1024


if __package__:
    from .document import SpecError, validate_spec
else:
    from document import SpecError, validate_spec


def silent_spec(spec):
    result = copy.deepcopy(spec)
    result.pop("voice", None)
    result.get("meta", {}).pop("tts", None)
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
        self.cancelled = threading.Event()
        self.worker = None
        self.storage = tempfile.TemporaryDirectory(prefix="video-studio-")

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.job)

    def start(self, spec, output_format="video", narration=None):
        if output_format not in ("video", "video-only", "pptx"):
            raise SpecError("Export format: choose video, video-only or pptx.")
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
            if narration:
                (directory / "narration-source.json").write_text(json.dumps(spec))
            self.job = {
                "id": job_id,
                "state": "rendering",
                "message": "Rendering on your computer…",
                "artifacts": [],
            }
            self.worker = threading.Thread(
                target=self._render,
                args=(job_id, directory, output_format, narration)
                if narration
                else (job_id, directory, output_format),
                daemon=True,
            )
            self.worker.start()
            return copy.deepcopy(self.job)

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()

    def _render(self, job_id, directory, output_format="video", narration=None):
        # Explicit allowlist: no inherited API keys, Python injection or cloud credentials.
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT")
            if key in os.environ
        }
        environment["PYTHON_DOTENV_DISABLED"] = "1"
        environment["MPLCONFIGDIR"] = str(directory / "matplotlib")
        message, artifacts, state = (
            "Render failed. Check that the renderer dependencies are installed.",
            [],
            "failed",
        )
        try:
            manifest = None
            if narration:
                module = importlib.import_module(
                    "src.narration" if __package__ else "narration"
                )
                source = json.loads((directory / "narration-source.json").read_text())
                for scene in source["timeline"]:
                    if not scene.get("narration"):
                        scene["narration"] = (
                            " ".join(
                                item.get("text", "")
                                for item in scene.get("elements", [])
                                if item.get("type") == "text"
                            )
                            or " ".join(scene.get("items", []))
                            or scene.get("text", "")
                            or scene.get("heading", "")
                        )
                    if not scene["narration"].strip():
                        raise ValueError(
                            "Narrated exports require a transcript for every scene."
                        )
                manifest = module.prepare_narration(
                    source,
                    directory,
                    os.environ.get("FRAME_TTS_PROVIDER", ""),
                    os.environ.get("FRAME_TTS_MODEL", ""),
                    os.environ.get("FRAME_TTS_VOICE", ""),
                    narration["consent"],
                    cancelled=self.cancelled,
                    max_requests=narration.get("max_requests", 12),
                )
                (directory / "spec.json").write_text(json.dumps(source))
            with self.lock:
                if self.closed:
                    return
                command = [
                    sys.executable,
                    str(ROOT / "src/render.py"),
                    str(directory / "spec.json"),
                    "-o",
                    str(directory / "video.mp4"),
                    "--workdir",
                    str(directory / "cache"),
                ]
                if manifest:
                    command.extend(["--media-manifest", str(manifest)])
                if output_format == "pptx":
                    command.append("--pptx-only")
                elif output_format == "video-only":
                    command.append("--video-only")
                process = subprocess.Popen(
                    command,
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
            if output_format in ("video", "video-only"):
                if (directory / "video.srt").is_file():
                    artifacts.append("srt")
                if not mp4.is_file() or not 0 < mp4.stat().st_size <= MAX_ARTIFACT:
                    raise RuntimeError("The renderer did not produce a usable video.")
                artifacts.append("mp4")
            pptx = directory / "video.pptx"
            if (
                output_format != "video-only"
                and pptx.is_file()
                and 0 < pptx.stat().st_size <= MAX_ARTIFACT
                and zipfile.is_zipfile(pptx)
            ):
                with zipfile.ZipFile(pptx) as archive:
                    if "ppt/presentation.xml" in archive.namelist():
                        artifacts.append("pptx")
            if output_format == "pptx" and "pptx" not in artifacts:
                raise RuntimeError(
                    "PowerPoint export failed. No usable deck was produced."
                )
            state = "complete"
            if output_format == "pptx":
                message = "PowerPoint is ready. No video was rendered."
            elif output_format == "video-only":
                message = "Video is ready. No PowerPoint was requested."
            else:
                message = (
                    "Video and PowerPoint are ready."
                    if "pptx" in artifacts
                    else "Video ready. PowerPoint export failed; only the video is available."
                )
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as error:
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
            "srt",
        ):
            return None
        path = Path(self.storage.name) / job_id / f"video.{extension}"
        with self.lock:
            if (
                self.job
                and self.job["id"] == job_id
                and (
                    self.job["state"] == "rendering"
                    or extension not in self.job["artifacts"]
                )
            ):
                return None
        return (
            path if path.is_file() and 0 < path.stat().st_size <= MAX_ARTIFACT else None
        )

    def close(self):
        with self.lock:
            self.closed = True
            self.cancelled.set()
            process = self.process
        if process:
            self.terminate(process)
        if self.worker is not None:
            self.worker.join(timeout=65)
        if self.worker is None or not self.worker.is_alive():
            self.storage.cleanup()


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, jobs):
        super().__init__(address, StudioHandler)
        self.jobs = jobs
        module = importlib.import_module("src.ai_setup" if __package__ else "ai_setup")
        self.ai_setup = module.AISetup(WEB / "ai-assets")
        generation = importlib.import_module(
            "src.generation" if __package__ else "generation"
        )
        self.generation = generation.GenerationJobs()
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def server_close(self):
        self.ai_setup.close()
        self.generation.close()
        super().server_close()


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
            "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
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
                200,
                {
                    "token": self.studio.token,
                    "job": self.studio.jobs.snapshot(),
                },
            )
        elif self.path.startswith("/fonts/"):
            if __package__:
                from . import composition
            else:
                import composition
            names = {
                f"/fonts/{family}-{weight}.ttf": (weight == "bold", family)
                for family in ("sans", "serif", "mono")
                for weight in ("regular", "bold")
            }
            font = names.get(self.path)
            if font is None:
                self.reply(404, {"error": "Font unavailable."})
            else:
                self.reply(
                    200, Path(composition.font_path(*font)).read_bytes(), "font/ttf"
                )
        elif self.path == "/api/generation/capabilities":
            self.reply(200, self.studio.generation.capabilities())
        elif self.path == "/api/generation":
            self.reply(200, {"job": self.studio.generation.snapshot()})
        elif self.path == "/api/ai-setup":
            self.reply(200, self.studio.ai_setup.snapshot())
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
                    else "text/plain; charset=utf-8"
                    if parts[4] == "srt"
                    else "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            else:
                self.reply(404, {"error": "Artifact unavailable."})
        else:
            files = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/selection-motion.js": (
                    "selection-motion.js",
                    "text/javascript; charset=utf-8",
                ),
                "/ai-worker.js": ("ai-worker.js", "text/javascript; charset=utf-8"),
                "/ai-protocol.mjs": (
                    "ai-protocol.mjs",
                    "text/javascript; charset=utf-8",
                ),
                "/canvas-icons.js": (
                    "canvas-icons.js",
                    "text/javascript; charset=utf-8",
                ),
                "/design-presets.mjs": (
                    "design-presets.mjs",
                    "text/javascript; charset=utf-8",
                ),
                "/ai-visuals.mjs": ("ai-visuals.mjs", "text/javascript; charset=utf-8"),
                "/authoring.js": ("authoring.js", "text/javascript; charset=utf-8"),
                "/scene-menus.js": ("scene-menus.js", "text/javascript; charset=utf-8"),
                "/shot-regeneration.js": (
                    "shot-regeneration.js",
                    "text/javascript; charset=utf-8",
                ),
                "/timeline-editor.js": (
                    "timeline-editor.js",
                    "text/javascript; charset=utf-8",
                ),
                "/rich-elements.js": (
                    "rich-elements.js",
                    "text/javascript; charset=utf-8",
                ),
                "/hosted-generation.js": (
                    "hosted-generation.js",
                    "text/javascript; charset=utf-8",
                ),
                "/history.js": ("history.js", "text/javascript; charset=utf-8"),
                "/sequence-director.mjs": (
                    "sequence-director.mjs",
                    "text/javascript; charset=utf-8",
                ),
                "/vector-library.json": (
                    "vector-library.json",
                    "application/json; charset=utf-8",
                ),
                "/DEJAVU-LICENSE": ("DEJAVU-LICENSE", "text/plain; charset=utf-8"),
                "/composition-design.mjs": (
                    "composition-design.mjs",
                    "text/javascript; charset=utf-8",
                ),
                "/canvas-assets.js": (
                    "canvas-assets.js",
                    "text/javascript; charset=utf-8",
                ),
                "/project-playback.js": (
                    "project-playback.js",
                    "text/javascript; charset=utf-8",
                ),
                "/canvas-motion.js": (
                    "canvas-motion.js",
                    "text/javascript; charset=utf-8",
                ),
                "/canvas.js": ("canvas.js", "text/javascript; charset=utf-8"),
                "/thumbnails.js": ("thumbnails.js", "text/javascript; charset=utf-8"),
                "/interactions.js": (
                    "interactions.js",
                    "text/javascript; charset=utf-8",
                ),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
            }
            assets = {
                "/ai-assets/wllama.js": "text/javascript",
                "/ai-assets/wllama.wasm": "application/wasm",
                "/ai-assets/qwen3.5-0.8b-q4_k_m.gguf": "application/octet-stream",
            }
            if self.path in assets:
                path = WEB / self.path.lstrip("/")
                # WEB already denotes studio; strip only the leading slash.
                if (
                    self.studio.ai_setup.snapshot()["status"] != "ready"
                    or not path.is_file()
                ):
                    self.reply(
                        404, {"error": "Enable local AI from the Create setup panel."}
                    )
                    return
                self.send_response(200)
                self.send_header("Content-Type", assets[self.path])
                self.send_header("Content-Length", str(path.stat().st_size))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                if self.command != "HEAD":
                    try:
                        with path.open("rb") as source:
                            while chunk := source.read(1024 * 1024):
                                self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass  # Worker termination cancels asset loading.
                return
            if self.path in files:
                name, mime = files[self.path]
                self.reply(200, (WEB / name).read_bytes(), mime)
            else:
                self.reply(404, {"error": "Not found."})

    def do_POST(self):
        if not self.allowed(True):
            self.reply(403, {"error": "This request is not from the local Studio."})
            return
        if self.path not in (
            "/api/render",
            "/api/generation/start",
            "/api/generation/cancel",
            "/api/quality",
            "/api/validate",
            "/api/ai-setup/start",
            "/api/ai-setup/cancel",
        ):
            self.reply(404, {"error": "Not found."})
            return
        try:
            if self.headers.get("Content-Type") != "application/json":
                raise SpecError("Send a JSON project.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise SpecError("Project must be smaller than 3 MiB.")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/generation/start":
                self.reply(202, {"job": self.studio.generation.start(payload)})
            elif self.path == "/api/generation/cancel":
                if (
                    not isinstance(payload, dict)
                    or set(payload) != {"id"}
                    or not isinstance(payload["id"], str)
                ):
                    raise SpecError("Provide the generation job ID.")
                self.studio.generation.cancel(payload["id"])
                self.reply(200, {"job": self.studio.generation.snapshot()})
            elif self.path == "/api/quality":
                quality = importlib.import_module(
                    "src.quality" if __package__ else "quality"
                )
                self.reply(200, quality.inspect_document(validate_spec(payload)))
            elif self.path == "/api/ai-setup/start":
                if (
                    not isinstance(payload, dict)
                    or payload != {"consent": True}
                    or type(payload.get("consent")) is not bool
                ):
                    raise SpecError("Confirm the local model download.")
                self.studio.ai_setup.start(consent=True)
                self.reply(202, self.studio.ai_setup.snapshot())
            elif self.path == "/api/ai-setup/cancel":
                if payload != {}:
                    raise SpecError("Do not supply setup targets.")
                self.studio.ai_setup.cancel()
                self.reply(200, self.studio.ai_setup.snapshot())
            elif self.path == "/api/validate":
                self.reply(200, {"spec": validate_spec(payload)})
            else:
                if (
                    not isinstance(payload, dict)
                    or not {"spec", "format"} <= set(payload)
                    or set(payload) - {"spec", "format", "narration"}
                ):
                    raise SpecError("Provide a project and export format.")
                spec = validate_spec(payload["spec"])
                narration = payload.get("narration")
                if narration is not None and narration != {"consent": True}:
                    raise SpecError("Confirm narration charges.")
                self.reply(
                    202, self.studio.jobs.start(spec, payload["format"], narration)
                )
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
        server.ai_setup.close()
        server.server_close()
        jobs.close()


if __name__ == "__main__":
    main()
