"""TTS provider dispatch, adapters, cache keys and graceful degradation.

All HTTP is mocked: no provider quota is used. Produced files are decoded
with MoviePy's AudioFileClip (via tts.audio_duration) to prove they play.
"""

import base64
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tts  # noqa: E402
import tts_elevenlabs  # noqa: E402
import tts_google  # noqa: E402

TTS_ENV = (
    "TTS_PROVIDER", "MISTRAL_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
    "ELEVENLABS_API_KEY", "GOOGLE_TTS_VOICE", "GOOGLE_TTS_MODEL",
    "GOOGLE_TTS_STYLE", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL",
)


def clean_env(**values):
    """os.environ without any TTS vars, plus `values`."""
    env = {k: v for k, v in os.environ.items() if k not in TTS_ENV}
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


def pcm_tone(seconds=0.5, rate=24000) -> bytes:
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                    for i in range(n))


def wav_bytes(seconds=0.5, rate=24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm_tone(seconds, rate))
    return buf.getvalue()


def mp3_bytes(seconds=0.5) -> bytes:
    import imageio_ffmpeg
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.wav", Path(d) / "out.mp3"
        src.write_bytes(wav_bytes(seconds, 44100))
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                        "-i", str(src), "-codec:a", "libmp3lame", str(dst)], check=True)
        return dst.read_bytes()


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(url, code, body=b"{}"):
    return HTTPError(url, code, "error", {}, io.BytesIO(body))


class Recorder:
    """urlopen stand-in: records requests, replies from a handler."""

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        return self.handler(req)


def gemini_body(audio: bytes, mime: str) -> bytes:
    return json.dumps({"candidates": [{"content": {"parts": [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio).decode()}}
    ]}}]}).encode()


class ProviderSelectionTests(unittest.TestCase):
    SPEC = {"voice": {"slug": "gb_jane_neutral"}, "timeline": []}

    def test_default_is_mistral_with_unchanged_settings(self):
        with clean_env():
            cfg = tts.resolve_config(self.SPEC)
        self.assertEqual(cfg["provider"], "mistral")
        self.assertEqual(cfg["slug"], "gb_jane_neutral")
        self.assertEqual(cfg["model"], "voxtral-mini-tts-2603")
        self.assertEqual(cfg["format"], "wav")

    def test_env_selects_provider(self):
        for name, fmt in (("google", "wav"), ("elevenlabs", "mp3"), ("MISTRAL", "wav")):
            with clean_env(TTS_PROVIDER=name):
                cfg = tts.resolve_config(self.SPEC)
            self.assertEqual(cfg["provider"], name.lower())
            self.assertEqual(cfg["format"], fmt)

    def test_spec_meta_selects_provider_and_voice(self):
        spec = {"meta": {"tts": {"provider": "google", "voice": "Charon",
                                 "style": "calm"}}, "timeline": []}
        with clean_env():
            cfg = tts.resolve_config(spec)
        self.assertEqual((cfg["provider"], cfg["slug"], cfg["style"]),
                         ("google", "Charon", "calm"))

    def test_env_override_ignores_other_providers_voice(self):
        spec = {"meta": {"tts": {"provider": "elevenlabs", "voice": "el-voice"}},
                "voice": {"slug": "gb_jane_neutral"}, "timeline": []}
        with clean_env(TTS_PROVIDER="google"):
            cfg = tts.resolve_config(spec)
        self.assertEqual(cfg["provider"], "google")
        self.assertIsNone(cfg["slug"])  # neither the EL id nor the Mistral slug

    def test_provider_env_voice_overrides(self):
        with clean_env(TTS_PROVIDER="elevenlabs", ELEVENLABS_VOICE_ID="abc"):
            self.assertEqual(tts.resolve_config({})["voice_id"], "abc")
        with clean_env(TTS_PROVIDER="google", GOOGLE_TTS_VOICE="Puck"):
            self.assertEqual(tts.resolve_config({})["slug"], "Puck")

    def test_unknown_provider_is_a_tts_error(self):
        with clean_env(TTS_PROVIDER="polly"):
            with self.assertRaises(tts.TTSError):
                tts.resolve_config({})


class CacheKeyTests(unittest.TestCase):
    def test_key_varies_by_provider_voice_and_model(self):
        base = {"provider": "mistral", "slug": "gb_jane_neutral", "model": "m"}
        keys = {
            tts.cache_key("hi", base),
            tts.cache_key("hi", {**base, "provider": "google"}),
            tts.cache_key("hi", {**base, "slug": "en_paul_neutral"}),
            tts.cache_key("hi", {**base, "model": "other"}),
            tts.cache_key("bye", base),
        }
        self.assertEqual(len(keys), 5)
        self.assertEqual(tts.cache_key("hi", base), tts.cache_key("hi", dict(base)))


class MistralDispatchTests(unittest.TestCase):
    def test_unset_provider_uses_mistral_payload(self):
        audio = wav_bytes()
        rec = Recorder(lambda req: FakeResponse(json.dumps(
            {"audio_data": base64.b64encode(audio).decode()}).encode()))
        with tempfile.TemporaryDirectory() as d, clean_env(MISTRAL_API_KEY="k"), \
                patch.object(tts._rq, "urlopen", rec), redirect_stdout(io.StringIO()):
            out = tts.synth_to_file("Hello", f"{d}/a.wav", voice_slug="gb_jane_neutral")
            self.assertAlmostEqual(tts.audio_duration(out), 0.5, places=1)
        req = rec.requests[0]
        self.assertEqual(req.full_url, tts.API_URL)
        self.assertEqual(json.loads(req.data), {
            "model": "voxtral-mini-tts-2603", "input": "Hello",
            "response_format": "wav", "voice": "gb_jane_neutral"})

    def test_missing_key_is_key_missing(self):
        with clean_env(), tempfile.TemporaryDirectory() as d:
            with self.assertRaises(tts.TTSKeyMissing) as ctx:
                tts.synth_to_file("Hello", f"{d}/a.wav", voice_slug="x")
        self.assertIn("MISTRAL_API_KEY", str(ctx.exception))


class GoogleAdapterTests(unittest.TestCase):
    def synth(self, handler, **kwargs):
        rec = Recorder(handler)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with clean_env(GOOGLE_API_KEY="g-key"), patch.object(tts_google._rq, "urlopen", rec), \
                redirect_stdout(io.StringIO()):
            out = tts.synth_to_file("Hello there", f"{d}/n.wav", provider="google", **kwargs)
        return out, rec

    def test_legacy_pcm_is_wrapped_into_decodable_wav(self):
        out, rec = self.synth(
            lambda req: FakeResponse(gemini_body(pcm_tone(0.5), "audio/L16;codec=pcm;rate=24000")),
            model="gemini-2.5-flash-preview-tts")
        self.assertEqual(Path(out).read_bytes()[:4], b"RIFF")
        self.assertAlmostEqual(tts.audio_duration(out), 0.5, places=1)
        body = json.loads(rec.requests[0].data)
        part = body["contents"][0]["parts"][0]
        self.assertTrue(part["text"].startswith(tts_google.DEFAULT_STYLE))
        self.assertNotIn("speechMetadata", part)

    def test_current_model_wav_passes_through_with_style_metadata(self):
        wav = wav_bytes(0.4)
        out, rec = self.synth(lambda req: FakeResponse(gemini_body(wav, "audio/wav")),
                              voice_slug="Charon", style="calm")
        self.assertEqual(Path(out).read_bytes(), wav)
        self.assertAlmostEqual(tts.audio_duration(out), 0.4, places=1)
        req = rec.requests[0]
        self.assertIn(f"/models/{tts_google.DEFAULT_MODELS[0]}:generateContent", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "g-key")
        body = json.loads(req.data)
        part = body["contents"][0]["parts"][0]
        self.assertEqual(part, {"text": "Hello there", "speechMetadata": {"style": "calm"}})
        voice = body["generationConfig"]["speechConfig"]["voiceConfig"]
        self.assertEqual(voice["prebuiltVoiceConfig"]["voiceName"], "Charon")
        self.assertEqual(body["generationConfig"]["responseModalities"], ["AUDIO"])

    def test_falls_back_to_next_model_when_unavailable(self):
        def handler(req):
            if tts_google.DEFAULT_MODELS[0] in req.full_url:
                raise http_error(req.full_url, 404, b'{"error":{"status":"NOT_FOUND"}}')
            return FakeResponse(gemini_body(wav_bytes(), "audio/wav"))
        out, rec = self.synth(handler)
        self.assertEqual(len(rec.requests), 2)
        self.assertIn(tts_google.DEFAULT_MODELS[1], rec.requests[1].full_url)
        self.assertTrue(Path(out).exists())

    def test_per_model_quota_falls_back_to_next_model(self):
        def handler(req):
            if tts_google.DEFAULT_MODELS[0] in req.full_url:
                raise http_error(req.full_url, 429, b'{"error":{"status":"RESOURCE_EXHAUSTED"}}')
            return FakeResponse(gemini_body(wav_bytes(), "audio/wav"))
        out, rec = self.synth(handler)
        self.assertIn(tts_google.DEFAULT_MODELS[1], rec.requests[1].full_url)
        self.assertTrue(Path(out).exists())

    def test_pinned_model_rate_limit_is_not_retried(self):
        def handler(req):
            raise http_error(req.full_url, 429, b'{"error":{"status":"RESOURCE_EXHAUSTED"}}')
        rec = Recorder(handler)
        with clean_env(GOOGLE_API_KEY="k"), patch.object(tts_google._rq, "urlopen", rec), \
                tempfile.TemporaryDirectory() as d, redirect_stdout(io.StringIO()):
            with self.assertRaises(tts.TTSError):
                tts.synth_to_file("Hi", f"{d}/a.wav", provider="google",
                                  model="gemini-3.8-flash-tts")
        self.assertEqual(len(rec.requests), 1)

    def test_gemini_api_key_alias(self):
        with clean_env(GEMINI_API_KEY="alias"):
            self.assertEqual(tts_google.get_api_key(), "alias")

    def test_missing_key_is_key_missing(self):
        with clean_env(), tempfile.TemporaryDirectory() as d:
            with self.assertRaises(tts.TTSKeyMissing) as ctx:
                tts.synth_to_file("Hi", f"{d}/a.wav", provider="google")
        self.assertIn("GOOGLE_API_KEY", str(ctx.exception))

    def test_blocked_response_is_tts_error(self):
        with self.assertRaises(tts.TTSError):
            self.synth(lambda req: FakeResponse(json.dumps(
                {"promptFeedback": {"blockReason": "SAFETY"}}).encode()))


class ElevenLabsAdapterTests(unittest.TestCase):
    VOICES = {"voices": [
        {"voice_id": "cloned1", "category": "cloned", "labels": {}},
        {"voice_id": "us1", "category": "premade", "labels": {"accent": "american"}},
        {"voice_id": "gb1", "category": "premade", "labels": {"accent": "british"}},
    ]}

    def setUp(self):
        tts_elevenlabs._default_voice_cache = None

    def synth(self, handler, **kwargs):
        rec = Recorder(handler)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with clean_env(ELEVENLABS_API_KEY="el-key"), \
                patch.object(tts_elevenlabs._rq, "urlopen", rec), redirect_stdout(io.StringIO()):
            out = tts.synth_to_file("Hello there", f"{d}/n.mp3", provider="elevenlabs", **kwargs)
        return out, rec

    def test_mp3_bytes_written_and_decodable(self):
        mp3 = mp3_bytes(0.5)
        out, rec = self.synth(lambda req: FakeResponse(mp3), voice_id="v123")
        self.assertEqual(Path(out).read_bytes(), mp3)
        self.assertAlmostEqual(tts.audio_duration(out), 0.5, delta=0.1)
        req = rec.requests[0]
        self.assertTrue(req.full_url.startswith(
            "https://api.elevenlabs.io/v1/text-to-speech/v123?output_format=mp3_44100_128"))
        self.assertEqual(req.get_header("Xi-api-key"), "el-key")
        self.assertEqual(json.loads(req.data),
                         {"text": "Hello there", "model_id": "eleven_multilingual_v2"})

    def test_default_voice_prefers_premade_british(self):
        mp3 = mp3_bytes(0.3)

        def handler(req):
            if req.full_url.endswith("/voices"):
                return FakeResponse(json.dumps(self.VOICES).encode())
            return FakeResponse(mp3)
        _, rec = self.synth(handler)
        self.assertIn("/text-to-speech/gb1?", rec.requests[1].full_url)

    def test_key_without_voices_read_gets_actionable_error(self):
        def handler(req):
            raise http_error(req.full_url, 401, b'{"detail":{"message":"The API key you '
                             b'used is missing the permission voices_read"}}')
        with self.assertRaises(tts.TTSError) as ctx:
            self.synth(handler)
        self.assertIn("Voices (read)", str(ctx.exception))
        self.assertIn("ELEVENLABS_VOICE_ID", str(ctx.exception))

    def test_no_usable_voices_is_tts_error(self):
        with self.assertRaises(tts.TTSError) as ctx:
            self.synth(lambda req: FakeResponse(b'{"voices": []}'))
        self.assertIn("ELEVENLABS_VOICE_ID", str(ctx.exception))

    def test_http_error_is_tts_error(self):
        def handler(req):
            raise http_error(req.full_url, 401, b'{"detail":{"status":"quota_exceeded"}}')
        with self.assertRaises(tts.TTSError):
            self.synth(handler, voice_id="v")

    def test_missing_key_is_key_missing(self):
        with clean_env(), tempfile.TemporaryDirectory() as d:
            with self.assertRaises(tts.TTSKeyMissing) as ctx:
                tts.synth_to_file("Hi", f"{d}/a.mp3", provider="elevenlabs", voice_id="v")
        self.assertIn("ELEVENLABS_API_KEY", str(ctx.exception))


class RenderIntegrationTests(unittest.TestCase):
    """render.py narration path: cache naming and silent degradation."""

    @classmethod
    def setUpClass(cls):
        import render
        cls.render = render

    def scene(self):
        return {"type": "title", "text": "T", "narration": "Hello world"}

    def test_missing_key_degrades_to_silence_for_every_provider(self):
        for provider in tts.PROVIDERS:
            with self.subTest(provider=provider), clean_env(TTS_PROVIDER=provider), \
                    tempfile.TemporaryDirectory() as d:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cfg = self.render.narration_config({})
                    result = self.render.scene_narration(self.scene(), 0, Path(d), cfg)
                self.assertEqual(result, (None, 0.0))
                self.assertIn("[warn]", buf.getvalue())
                self.assertIn("without narration", buf.getvalue())

    def test_provider_failure_degrades_to_silence(self):
        def handler(req):
            raise http_error(req.full_url, 429, b'{"error":{"status":"RESOURCE_EXHAUSTED"}}')
        with clean_env(TTS_PROVIDER="google", GOOGLE_API_KEY="k"), \
                patch.object(tts_google._rq, "urlopen", Recorder(handler)), \
                tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                cfg = self.render.narration_config({})
                result = self.render.scene_narration(self.scene(), 3, Path(d), cfg)
            self.assertEqual(result, (None, 0.0))
            self.assertIn("google TTS failed", buf.getvalue())
            self.assertEqual(list(Path(d).iterdir()), [])  # no partial cache entry

    def test_bad_provider_setting_renders_silently(self):
        with clean_env(TTS_PROVIDER="nope"), redirect_stdout(io.StringIO()):
            cfg = self.render.narration_config({})
        self.assertIsNone(cfg)
        self.assertEqual(self.render.scene_narration(self.scene(), 0, Path("."), cfg),
                         (None, 0.0))

    def test_switching_provider_regenerates_instead_of_replaying_cache(self):
        calls = []

        def fake_synth(text, out_path, **kwargs):
            calls.append(kwargs["provider"])
            Path(out_path).write_bytes(wav_bytes(0.3))
            return out_path

        with tempfile.TemporaryDirectory() as d, \
                patch.object(self.render.tts, "synth_to_file", fake_synth):
            work = Path(d)
            for provider in ("mistral", "google", "mistral"):
                with clean_env(TTS_PROVIDER=provider), redirect_stdout(io.StringIO()):
                    cfg = self.render.narration_config({})
                    path, dur = self.render.synth_narration(self.scene(), work, cfg)
                self.assertIn(f"narr_{provider}_", Path(path).name)
                self.assertGreater(dur, 0)
            names = sorted(p.name for p in work.iterdir())
        # Second mistral run is a cache hit; google got its own clip.
        self.assertEqual(calls, ["mistral", "google"])
        self.assertEqual(len(names), 2)


if __name__ == "__main__":
    unittest.main()
