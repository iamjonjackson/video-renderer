"""Strict server preparation and renderer wiring; local HTTP, never paid APIs."""

import base64
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import narration
import pptx_export
import render


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 12000)
    return buffer.getvalue()


def provider_body(provider, audio):
    encoded = base64.b64encode(audio).decode()
    if provider == "mistral":
        return json.dumps({"audio_data": encoded}).encode()
    if provider == "google":
        return json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/wav",
                                        "data": encoded,
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode()
    return audio


@contextmanager
def local_http(body, status=200):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append((self.path, dict(self.headers), payload))
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    urls, timeouts = [], []

    def transport(req, timeout):
        urls.append(req.full_url)
        timeouts.append(timeout)
        suffix = req.full_url.split("/", 3)[3]
        local = request.Request(
            f"http://127.0.0.1:{server.server_port}/{suffix}",
            data=req.data,
            headers=dict(req.header_items()),
            method=req.method,
        )
        return request.urlopen(local, timeout=timeout)

    try:
        yield transport, calls, urls, timeouts
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class NarrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "PATH": os.environ.get("PATH", ""),
                "MISTRAL_API_KEY": "fixture-mistral",
                "GOOGLE_API_KEY": "fixture-google",
                "ELEVENLABS_API_KEY": "fixture-eleven",
                "TTS_PROVIDER": "wrong-provider",
                "GOOGLE_TTS_MODEL": "wrong-model",
                "GOOGLE_TTS_VOICE": "wrong-voice",
            },
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.spec = {
            "timeline": [
                {
                    "type": "title",
                    "text": "Hello",
                    "duration": 2,
                    "narration": "Hello there. This is the whole transcript.",
                }
            ]
        }

    def prepare(self, provider="mistral", body=None):
        body = body if body is not None else provider_body(provider, wav_bytes())
        with local_http(body) as (transport, calls, urls, timeouts):
            path = narration.prepare_narration(
                self.spec,
                self.root,
                provider,
                "gemini-3.1-flash-tts-preview"
                if provider == "google"
                else "selected_model",
                "selected_voice",
                True,
                transport,
            )
        return path, calls, urls, timeouts

    def test_exact_selection_real_http_and_real_decoding_all_providers(self):
        import imageio_ffmpeg

        wav = self.root / "fixture.wav"
        mp3 = self.root / "fixture.mp3"
        wav.write_bytes(wav_bytes())
        # Fixtures carry no credentials into the real encoder either.
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav),
                str(mp3),
            ],
            check=True,
            env={"PATH": os.environ["PATH"]},
        )
        for provider in ("mistral", "google", "elevenlabs"):
            with self.subTest(provider=provider):
                body = provider_body(
                    provider,
                    mp3.read_bytes() if provider == "elevenlabs" else wav_bytes(),
                )
                path, calls, urls, timeouts = self.prepare(provider, body)
                self.assertEqual(len(calls), 1)
                self.assertTrue(0 < timeouts[0] <= 180)
                payload = calls[0][2]
                if provider == "google":
                    self.assertIn(
                        "/models/gemini-3.1-flash-tts-preview:generateContent", urls[0]
                    )
                    self.assertEqual(
                        payload["generationConfig"]["speechConfig"]["voiceConfig"][
                            "prebuiltVoiceConfig"
                        ]["voiceName"],
                        "selected_voice",
                    )
                    self.assertEqual(
                        payload["contents"][0]["parts"][0]["text"],
                        self.spec["timeline"][0]["narration"],
                    )
                elif provider == "mistral":
                    self.assertEqual(payload["model"], "selected_model")
                    self.assertEqual(payload["voice"], "selected_voice")
                else:
                    self.assertIn(
                        "/text-to-speech/selected_voice?output_format=mp3_44100_128",
                        urls[0],
                    )
                    self.assertEqual(payload["model_id"], "selected_model")
                manifest = json.loads(path.read_text())
                entry = manifest["scenes"][0]
                self.assertAlmostEqual(entry["duration"], 0.5, delta=0.1)
                self.assertEqual(
                    entry["path"],
                    "scene00.mp3" if provider == "elevenlabs" else "scene00.wav",
                )
                self.assertEqual(
                    entry["captions"],
                    [
                        {
                            "start": 0,
                            "end": entry["duration"],
                            "text": self.spec["timeline"][0]["narration"],
                        }
                    ],
                )
                self.assertNotIn("fixture-", path.read_text())
                self.assertEqual(
                    narration.load_media_manifest(path, self.spec)[0]["path"],
                    str(path.parent / entry["path"]),
                )

    def test_google_raw_pcm_is_wrapped_using_existing_adapter(self):
        body = json.dumps(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/L16;rate=24000",
                                        "data": base64.b64encode(
                                            b"\0\0" * 12000
                                        ).decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        ).encode()
        path, *_ = self.prepare("google", body)
        with wave.open(str(path.parent / "scene00.wav")) as audio:
            self.assertEqual(audio.getnframes(), 12000)

    def test_consent_and_identifiers_fail_before_transport_or_output(self):
        transport = MagicMock()
        self.assertIsNone(
            narration.prepare_narration(
                self.spec, self.root, "google", "m", "v", False, transport
            )
        )
        for provider, model, voice, consent in [
            (None, "m", "v", True),
            ("google", "https://evil/model", "v", True),
            ("google", "m", "../voice", True),
            ("google", "m", "v", None),
        ]:
            with self.assertRaises(narration.NarrationError):
                narration.prepare_narration(
                    self.spec, self.root, provider, model, voice, consent, transport
                )
        transport.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_unknown_voice_and_quota_never_try_alternatives(self):
        for provider in ("mistral", "google", "elevenlabs"):
            for status, detail in (
                (400, b'"invalid_voice secret fixture"'),
                (429, b'"quota exceeded"'),
            ):
                with self.subTest(provider=provider, status=status):
                    with local_http(detail, status) as (transport, calls, *_):
                        with self.assertRaises(narration.NarrationError) as error:
                            narration.prepare_narration(
                                self.spec,
                                self.root,
                                provider,
                                "selected_model",
                                "unknown_voice",
                                True,
                                transport,
                            )
                    self.assertEqual(len(calls), 1)
                    self.assertNotIn("secret", str(error.exception))
                    self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_key_does_not_use_other_provider_key(self):
        with patch.dict(os.environ, {"MISTRAL_API_KEY": ""}):
            transport = MagicMock()
            with self.assertRaises(narration.NarrationError):
                narration.prepare_narration(
                    self.spec, self.root, "mistral", "m", "v", True, transport
                )
            transport.assert_not_called()

    def test_decode_subprocess_receives_no_server_secrets_and_is_bounded(self):
        original = subprocess.run
        observed = []

        def run(*args, **kwargs):
            observed.append(kwargs)
            return original(*args, **kwargs)

        with patch.object(narration.subprocess, "run", side_effect=run):
            self.prepare()
        self.assertEqual(len(observed), 1)
        self.assertFalse(
            any("KEY" in key or "TTS" in key for key in observed[0]["env"])
        )
        self.assertTrue(0 < observed[0]["timeout"] <= 180)

    def test_limits_decode_failure_and_short_explicit_scene_publish_nothing(self):
        with patch.object(narration, "MAX_BYTES", 100):
            with self.assertRaisesRegex(narration.NarrationError, "20 MB"):
                self.prepare()
        with self.assertRaises(narration.NarrationError):
            self.prepare("elevenlabs", b"not audio")
        self.spec["timeline"][0]["duration"] = 0.1
        with self.assertRaisesRegex(narration.NarrationError, "explicit"):
            self.prepare()
        self.assertEqual(list(self.root.iterdir()), [])
        transport = MagicMock()
        self.spec["timeline"] *= 13
        with self.assertRaises(narration.NarrationError):
            narration.prepare_narration(
                self.spec, self.root, "mistral", "m", "v", True, transport
            )
        transport.assert_not_called()

    def test_request_count_at_most_twelve_and_deadline_stops_requests(self):
        self.spec["timeline"] *= 12
        with patch.object(narration, "_decoded_duration", return_value=0.5):
            _, calls, *_ = self.prepare()
        self.assertEqual(len(calls), 12)
        transport = MagicMock()
        with patch.object(narration, "DEADLINE_SECONDS", 0):
            with self.assertRaises(narration.NarrationError):
                narration.prepare_narration(
                    self.spec, self.root, "mistral", "m", "v", True, transport
                )
        transport.assert_not_called()

    def test_pre_cancelled_preparation_never_calls_transport_or_creates_output(self):
        cancelled = threading.Event()
        cancelled.set()
        transport = MagicMock()
        with self.assertRaisesRegex(narration.NarrationError, "cancelled"):
            narration.prepare_narration(
                self.spec,
                self.root,
                "mistral",
                "m",
                "v",
                True,
                transport,
                cancelled=cancelled,
            )
        transport.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancellation_while_request_is_blocked_discards_response_and_stops_scenes(
        self,
    ):
        self.spec["timeline"].append({"narration": "Second scene.", "duration": 2})
        cancelled = threading.Event()
        entered = threading.Event()
        release = threading.Event()
        body = provider_body("mistral", wav_bytes())

        def blocked_transport(req, timeout):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test did not release the blocked request")
            return io.BytesIO(body)

        transport = MagicMock(side_effect=blocked_transport)
        with (
            patch.object(
                narration, "_audio_bytes", wraps=narration._audio_bytes
            ) as decode,
            patch.object(narration, "_decoded_duration") as duration,
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(
                narration.prepare_narration,
                self.spec,
                self.root,
                "mistral",
                "m",
                "v",
                True,
                transport,
                cancelled=cancelled,
            )
            try:
                self.assertTrue(entered.wait(timeout=5), "First request never started")
                cancelled.set()
            finally:
                release.set()
            with self.assertRaisesRegex(narration.NarrationError, "cancelled"):
                future.result(timeout=5)
            decode.assert_not_called()
            duration.assert_not_called()
        transport.assert_called_once()
        self.assertEqual(
            json.loads(transport.call_args.args[0].data)["input"],
            self.spec["timeline"][0]["narration"],
        )
        self.assertEqual(list(self.root.rglob("media-manifest.json")), [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_cancellation_between_scenes_is_checked_before_next_request(self):
        self.spec["timeline"].append({"narration": "Second scene.", "duration": 2})
        cancelled = threading.Event()
        transport = MagicMock(
            return_value=io.BytesIO(provider_body("mistral", wav_bytes()))
        )

        def cancel_after_decode(path, deadline):
            cancelled.set()
            return 0.5

        with patch.object(
            narration, "_decoded_duration", side_effect=cancel_after_decode
        ) as duration:
            with self.assertRaisesRegex(narration.NarrationError, "cancelled"):
                narration.prepare_narration(
                    self.spec,
                    self.root,
                    "mistral",
                    "m",
                    "v",
                    True,
                    transport,
                    cancelled=cancelled,
                )
        duration.assert_called_once()
        transport.assert_called_once()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_request_cap_one_rejects_two_narrated_scenes_before_transport(self):
        self.spec["timeline"].append({"narration": "Second scene.", "duration": 2})
        transport = MagicMock()
        with self.assertRaisesRegex(narration.NarrationError, "request budget"):
            narration.prepare_narration(
                self.spec,
                self.root,
                "mistral",
                "m",
                "v",
                True,
                transport,
                max_requests=1,
            )
        transport.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_google_helpers_work_as_package_without_src_on_import_path(self):
        repository = Path(__file__).resolve().parents[1]
        script = textwrap.dedent("""
            import base64
            import io
            import json
            import sys
            import wave
            from pathlib import Path
            from unittest.mock import patch

            root = Path(sys.argv[1]).resolve()
            sys.path = [entry for entry in sys.path
                        if Path(entry).resolve() != root / "src"]
            sys.path.insert(0, str(root))
            with patch("socket.socket", side_effect=AssertionError("Network forbidden")):
                from src import narration

                assert narration.__package__ == "src"
                assert "tts_google" not in sys.modules
                assert "tts" not in sys.modules
                if sys.argv[2] == "request":
                    req = narration._speech_request(
                        "google", "gemini-3.1-flash-tts-preview", "Kore",
                        "Package narration.", "fixture-key",
                    )
                    assert req.full_url == (
                        "https://generativelanguage.googleapis.com/v1beta/models/"
                        "gemini-3.1-flash-tts-preview:generateContent"
                    )
                    assert req.method == "POST"
                    assert req.get_header("X-goog-api-key") == "fixture-key"
                    assert json.loads(req.data) == {
                        "contents": [{"role": "user", "parts": [{"text": "Package narration."}]}],
                        "generationConfig": {
                            "responseModalities": ["AUDIO"],
                            "speechConfig": {"voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": "Kore"}
                            }},
                        },
                    }
                else:
                    pcm = b"\\x01\\x00" * 12000
                    raw = json.dumps({"candidates": [{"content": {"parts": [{
                        "inlineData": {
                            "mimeType": "audio/L16;rate=24000",
                            "data": base64.b64encode(pcm).decode(),
                        }
                    }]}}]}).encode()
                    audio = narration._audio_bytes("google", raw)
                    with wave.open(io.BytesIO(audio), "rb") as wav:
                        assert wav.getnchannels() == 1
                        assert wav.getsampwidth() == 2
                        assert wav.getframerate() == 24000
                        assert wav.getnframes() == 12000
                        assert wav.readframes(12000) == pcm
                assert "src.tts_google" in sys.modules
                assert "tts_google" not in sys.modules
                assert "tts" not in sys.modules
        """)
        for operation in ("request", "audio"):
            with self.subTest(operation=operation):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-B",
                        "-c",
                        script,
                        str(repository),
                        operation,
                    ],
                    cwd=repository,
                    env={"PATH": os.environ["PATH"]},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_manifest_rejects_escape_absolute_url_and_symlink(self):
        path, *_ = self.prepare()
        manifest = json.loads(path.read_text())
        for malicious in (
            "../fixture.wav",
            str(self.root / "fixture.wav"),
            "https://evil/audio.wav",
        ):
            bad = copy.deepcopy(manifest)
            bad["scenes"][0]["path"] = malicious
            path.write_text(json.dumps(bad))
            with self.assertRaises(narration.NarrationError):
                narration.load_media_manifest(path, self.spec)
        path.write_text(json.dumps(manifest))
        outside = self.root / "outside.wav"
        outside.write_bytes(wav_bytes())
        (path.parent / "scene00.wav").unlink()
        (path.parent / "scene00.wav").symlink_to(outside)
        with self.assertRaises(narration.NarrationError):
            narration.load_media_manifest(path, self.spec)

    def test_manifest_rejects_missing_duplicate_bad_duration_and_transcript(self):
        path, *_ = self.prepare()
        original = json.loads(path.read_text())
        variants = []
        for key, value in (
            ("duration", float("nan")),
            ("index", True),
            ("captions", []),
        ):
            bad = copy.deepcopy(original)
            bad["scenes"][0][key] = value
            variants.append(bad)
        variants.extend(({"scenes": []}, {"scenes": original["scenes"] * 2}))
        for bad in variants:
            path.write_text(json.dumps(bad))
            with self.assertRaises(narration.NarrationError):
                narration.load_media_manifest(path, self.spec)

    def test_video_manifest_bypasses_keys_attaches_audio_and_emits_srt(self):
        path, *_ = self.prepare()
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(self.spec))
        video = MagicMock()
        video.with_duration.return_value = video
        final = MagicMock()
        final.with_audio.return_value = final
        audio = MagicMock()
        audio.with_start.return_value = audio
        with (
            patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True),
            patch.object(
                render,
                "narration_config",
                side_effect=AssertionError("must not read keys"),
            ),
            patch.object(
                render,
                "synth_narration",
                side_effect=AssertionError("must not synthesize"),
            ),
            patch.dict(render.BUILDERS, {"title": MagicMock(return_value=video)}),
            patch.object(render, "apply_anim", return_value=video),
            patch.object(render, "AudioFileClip", return_value=audio) as audio_cls,
            patch.object(render, "CompositeAudioClip") as mix,
            patch.object(render, "concatenate_videoclips", return_value=final),
        ):
            output = self.root / "video.mp4"
            render.render(
                str(spec_path),
                str(output),
                str(self.root / "work"),
                export_pptx=False,
                media_manifest=str(path),
            )
        video.with_duration.assert_called_with(2)
        audio_cls.assert_called_once_with(str(path.parent / "scene00.wav"))
        mix.assert_called_once_with([audio])
        final.write_videofile.assert_called_once()
        audio.close.assert_called_once()
        srt = output.with_suffix(".srt").read_text()
        self.assertIn("00:00:00,000 --> 00:00:00,500", srt)
        self.assertIn(self.spec["timeline"][0]["narration"], srt)

    def test_pptx_only_contains_transcript_disclosure_and_existing_audio(self):
        from pptx import Presentation

        path, *_ = self.prepare()
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(self.spec))
        with (
            patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True),
            patch.object(
                render,
                "narration_config",
                side_effect=AssertionError("must not read keys"),
            ),
            patch.object(
                render,
                "synth_narration",
                side_effect=AssertionError("must not synthesize"),
            ),
        ):
            render.render(
                str(spec_path),
                str(self.root / "deck.mp4"),
                str(self.root / "work"),
                render_video=False,
                media_manifest=str(path),
            )
        deck = Presentation(self.root / "deck.pptx")
        notes = deck.slides[0].notes_slide.notes_text_frame.text
        self.assertIn(self.spec["timeline"][0]["narration"], notes)
        self.assertIn("not word-level", notes)
        self.assertTrue(any(shape.shape_type == 16 for shape in deck.slides[0].shapes))

    def test_srt_offsets_preserve_full_scene_lengths(self):
        entries = {
            1: {"captions": [{"start": 0, "end": 0.5, "text": "Second sentence."}]}
        }
        output = self.root / "video.mp4"
        narration.write_srt(output, entries, [2, 4])
        self.assertEqual(
            output.with_suffix(".srt").read_text(),
            "1\n00:00:02,000 --> 00:00:02,500\nSecond sentence.\n",
        )

    def test_render_isolates_secret_environment_before_any_decoding(self):
        path, *_ = self.prepare()
        with (
            patch.object(render.subprocess, "run") as run,
            patch.object(
                render, "_render_impl", side_effect=AssertionError("must isolate")
            ),
        ):
            render.render(
                "spec.json", "video.mp4", render_video=False, media_manifest=str(path)
            )
        args, kwargs = run.call_args
        self.assertIn("--media-manifest", args[0])
        self.assertIn("--pptx-only", args[0])
        self.assertFalse(any("KEY" in name or "TTS" in name for name in kwargs["env"]))

    def test_encoding_failure_still_closes_audio(self):
        path, *_ = self.prepare()
        spec_path = self.root / "spec.json"
        spec_path.write_text(json.dumps(self.spec))
        video, final, audio = MagicMock(), MagicMock(), MagicMock()
        video.with_duration.return_value = video
        final.with_audio.return_value = final
        audio.with_start.return_value = audio
        final.write_videofile.side_effect = RuntimeError("encode failed")
        with (
            patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True),
            patch.dict(render.BUILDERS, {"title": MagicMock(return_value=video)}),
            patch.object(render, "apply_anim", return_value=video),
            patch.object(render, "AudioFileClip", return_value=audio),
            patch.object(render, "CompositeAudioClip"),
            patch.object(render, "concatenate_videoclips", return_value=final),
        ):
            with self.assertRaisesRegex(RuntimeError, "encode failed"):
                render.render(
                    str(spec_path),
                    str(self.root / "video.mp4"),
                    export_pptx=False,
                    media_manifest=str(path),
                )
        audio.close.assert_called_once()
        video.close.assert_called_once()
        final.close.assert_called_once()

    def test_static_composition_notes_use_prepared_transcript(self):
        scene = {"narration": "Original.", "elements": []}
        self.assertIn(
            "Prepared.",
            pptx_export._notes_text(
                scene,
                {
                    "transcript": "Prepared.",
                    "caption_disclosure": narration.CAPTION_DISCLOSURE,
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
