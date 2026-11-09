"""Mocked TTS provider tests (no network or API keys needed)."""
import base64
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import tts  # noqa: E402

ENV_KEYS = ("MISTRAL_API_KEY", "GOOGLE_API_KEY", "ELEVENLABS_API_KEY",
            "MISTRAL_VOICE", "GOOGLE_VOICE", "ELEVENLABS_VOICE_ID", "FAL_VOICE",
            "FAL_KEY", "TTS_PROVIDER", "FAL_ENDPOINT")


def pcm(rate=24000, seconds=0.2):
    n = int(rate * seconds)
    return b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * i / rate)))
                    for i in range(n))


def wav_bytes(rate=24000, seconds=0.2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm(rate, seconds))
    return buf.getvalue()


def google_body(audio, mime="audio/l16;rate=24000"):
    return {"steps": [{"type": "model_output", "content": [
        {"type": "audio", "mime_type": mime,
         "data": base64.b64encode(audio).decode()}]}]}


class FakeResp:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.calls = []
        self._orig_urlopen = tts._rq.urlopen
        self._env = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self):
        tts._rq.urlopen = self._orig_urlopen
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.tmp.cleanup()

    def fake(self, handler):
        def fake_urlopen(req, timeout=None, context=None):
            self.calls.append({
                "url": req.full_url,
                "headers": {k.lower(): v for k, v in (req.headers or {}).items()},
                "data": req.data.decode() if req.data else None,
            })
            return FakeResp(handler(req))
        tts._rq.urlopen = fake_urlopen

    def payload(self, index=-1):
        return json.loads(self.calls[index]["data"])

    def out(self, name):
        return str(self.dir / name)


class ResolutionTests(Base):
    def test_provider_formats_and_voice_env(self):
        os.environ["TTS_PROVIDER"] = "elevenlabs"
        self.assertEqual(tts.resolve_provider(), "elevenlabs")
        self.assertEqual(tts.resolve_provider({"provider": "google"}), "google")
        with self.assertRaises(tts.TTSError):
            tts.resolve_provider({"provider": "nope"})

        for provider, fmt, model, expected in [
            ("mistral", None, None, "wav"), ("mistral", "mp3", None, "mp3"),
            ("google", "mp3", None, "wav"),
            ("elevenlabs", None, None, "mp3"), ("elevenlabs", "wav", None, "wav"),
            ("fal", None, None, "mp3"),
            ("fal", "wav", "fal-ai/gemini-3.1-flash-tts", "wav"),
        ]:
            self.assertEqual(tts.resolve_format(provider, fmt, model), expected)
        self.assertEqual(tts.DEFAULT_GOOGLE_MODEL, "gemini-3.8-flash-tts")

        os.environ.update(MISTRAL_VOICE="gb_jane_neutral", GOOGLE_VOICE="Kore",
                          ELEVENLABS_VOICE_ID="envvoice", FAL_VOICE="Rachel")
        self.assertEqual(tts.resolve_voice("mistral"), ("gb_jane_neutral", None))
        self.assertEqual(tts.resolve_voice("google"), ("Kore", None))
        self.assertEqual(tts.resolve_voice("elevenlabs"), (None, "envvoice"))
        self.assertEqual(tts.resolve_voice("fal"), ("Rachel", None))
        self.assertEqual(tts.resolve_voice("google", "Charon"), ("Charon", None))


class GoogleTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["GOOGLE_API_KEY"] = "test-google"

    def test_interactions_payload_and_wav(self):
        self.fake(lambda req: json.dumps(google_body(pcm(24000))).encode())
        out = self.out("g.wav")
        tts.synth_to_file("hello", out, provider="google",
                          voice_slug="Kore", style="calm")
        call, payload = self.calls[-1], self.payload()
        self.assertEqual(call["url"],
                         "https://generativelanguage.googleapis.com/v1beta/interactions")
        self.assertEqual(call["headers"].get("x-goog-api-key"), "test-google")
        self.assertEqual(payload["model"], "gemini-3.8-flash-tts")
        part = payload["input"][0]["content"][0]
        self.assertEqual(part["annotations"],
                         [{"type": "speech_metadata", "style": "calm"}])
        self.assertEqual(payload["generation_config"],
                         {"speech_config": [{"voice": "Kore"}]})
        with wave.open(out) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()),
                             (24000, 1, 2))

    def test_env_voice(self):
        os.environ["GOOGLE_VOICE"] = "Kore"
        self.fake(lambda req: json.dumps(google_body(pcm(24000))).encode())
        tts.synth_to_file("hello", self.out("g.wav"), provider="google")
        self.assertEqual(self.payload()["generation_config"]["speech_config"],
                         [{"voice": "Kore"}])

    def test_strict_requires_voice(self):
        for provider in ("mistral", "google", "elevenlabs", "fal"):
            with self.subTest(provider=provider):
                with self.assertRaises(tts.StrictVoiceError):
                    tts.synth_to_file("x", self.out("x"),
                                      provider=provider, strict=True)
        self.assertEqual(self.calls, [])


class ElevenLabsTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["ELEVENLABS_API_KEY"] = "test-elevenlabs"

    def test_default_mp3_and_explicit_wav(self):
        mp3 = b"ID3fake"
        self.fake(lambda req: mp3)
        out = self.out("e.mp3")
        tts.synth_to_file("hello", out, provider="elevenlabs")
        self.assertEqual(out and Path(out).read_bytes(), mp3)
        self.assertIn(f"/v1/text-to-speech/{tts.DEFAULT_ELEVENLABS_VOICE_ID}",
                      self.calls[0]["url"])
        self.assertIn("output_format=mp3_44100_128", self.calls[0]["url"])

        self.calls.clear()
        self.fake(lambda req: pcm(44100))
        out = self.out("e.wav")
        tts.synth_to_file("hello", out, provider="elevenlabs",
                          voice_id="voice1", fmt="wav")
        self.assertIn("output_format=pcm_44100", self.calls[0]["url"])
        with wave.open(out) as w:
            self.assertEqual(w.getframerate(), 44100)



class FalTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["FAL_KEY"] = "test-fal"

    def test_eleven_and_gemini_payloads(self):
        mp3 = b"ID3fake"
        def handler(req):
            if req.full_url.startswith("https://fal.run/"):
                return json.dumps({"audio": {"url": "https://storage.example/a.mp3"}}).encode()
            return mp3
        self.fake(handler)
        out = self.out("f.mp3")
        tts.synth_to_file("hello", out, provider="fal", voice_slug="Rachel")
        request, download = self.calls[0], self.calls[1]
        self.assertEqual(request["url"],
                         "https://fal.run/fal-ai/elevenlabs/tts/eleven-v3")
        self.assertTrue(request["headers"]["authorization"].startswith("Key "))
        self.assertEqual(json.loads(request["data"]), {"text": "hello", "voice": "Rachel"})
        self.assertNotIn("authorization", download["headers"])
        self.assertEqual(Path(out).read_bytes(), mp3)

        audio = wav_bytes(24000)
        def gemini(req):
            if req.full_url.startswith("https://fal.run/"):
                return json.dumps({"audio": {"url": "https://storage.example/g.wav"}}).encode()
            return audio
        self.calls.clear()
        self.fake(gemini)
        tts.synth_to_file("hello", self.out("g.wav"), provider="fal", fmt="wav",
                          model="fal-ai/gemini-3.1-flash-tts",
                          voice_slug="Kore", style="calm")
        payload = json.loads(self.calls[0]["data"])
        self.assertEqual((payload["prompt"], payload["output_format"],
                          payload["style_instructions"]), ("hello", "wav", "calm"))



class MistralTests(Base):
    def setUp(self):
        super().setUp()
        os.environ["MISTRAL_API_KEY"] = "test-mistral"

    def test_strict_vs_fallback(self):
        def reject(req):
            raise HTTPError(req.full_url, 422, "Unprocessable", {},
                            io.BytesIO(b'{"detail":"invalid_voice"}'))
        self.fake(reject)
        with self.assertRaises(tts.StrictVoiceError):
            tts.synth_to_file("hi", self.out("m.wav"), provider="mistral",
                              voice_slug="bad", strict=True)
        self.assertEqual(len(self.calls), 1)

        voices = []
        def fallback(req):
            voices.append(json.loads(req.data).get("voice"))
            if len(voices) == 1:
                raise HTTPError(req.full_url, 422, "Unprocessable", {},
                                io.BytesIO(b'{"detail":"invalid_voice"}'))
            return json.dumps({"audio_data": base64.b64encode(b"fake").decode()}).encode()
        self.calls.clear()
        self.fake(fallback)
        tts.synth_to_file("hi", self.out("m.wav"), provider="mistral",
                          voice_slug="bad")
        self.assertEqual(len(voices), 2)
        self.assertNotEqual(voices[0], voices[1])



class ErrorAndCacheTests(Base):
    def test_missing_key(self):
        with self.assertRaises(tts.MissingAPIKey) as caught:
            tts.synth_to_file("hello", self.out("x.wav"), provider="google")
        self.assertIn("GOOGLE_API_KEY", str(caught.exception))

    def test_cache_key_uses_provider_voice_and_strict(self):
        import render
        calls = []
        def fake_synth(text, out_path, **kwargs):
            calls.append(kwargs)
            Path(out_path).write_bytes(wav_bytes(24000, 0.1))
            return out_path
        orig_synth, orig_duration = tts.synth_to_file, tts.audio_duration
        tts.synth_to_file = fake_synth
        tts.audio_duration = lambda path: 0.1
        try:
            workdir = self.dir / "work"
            workdir.mkdir()
            scene = {"narration": "cache"}
            google = {"provider": "google", "slug": "Kore"}
            first, _ = render.synth_narration(scene, workdir, google)
            second, _ = render.synth_narration(scene, workdir, google)
            eleven, _ = render.synth_narration(
                scene, workdir, {"provider": "elevenlabs", "slug": "Kore"})
            strict, _ = render.synth_narration(
                scene, workdir, {**google, "strict": True})
            self.assertEqual(first, second)
            self.assertNotEqual(first, eleven)
            self.assertNotEqual(first, strict)
            self.assertEqual(len(calls), 3)
        finally:
            tts.synth_to_file = orig_synth
            tts.audio_duration = orig_duration


if __name__ == "__main__":
    unittest.main()
