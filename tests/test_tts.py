"""check provider requests, real audio decoding, cache isolation and silent fallback"""
import base64
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import tts
import tts_google
import tts_elevenlabs
import render
import pptx_export
from moviepy import AudioFileClip, VideoFileClip
from pptx import Presentation


class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 24000)))
                           for i in range(6000))
        cls.wav = tts.pcm_wav(cls.pcm)
        # make a small mp3 locally so the mock still exercises real decoding
        result = subprocess.run([render._ffmpeg_exe(), "-loglevel", "error", "-f", "s16le",
                                 "-ar", "24000", "-ac", "1", "-i", "pipe:0", "-ar", "44100",
                                 "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1"],
                                input=cls.pcm, capture_output=True, check=True)
        cls.mp3 = result.stdout

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"MISTRAL_API_KEY": "test-mistral-key",
                                          "GOOGLE_API_KEY": "test-google-key",
                                          "ELEVENLABS_API_KEY": "test-elevenlabs-key"}, clear=True)
        tts_elevenlabs._account_voice.cache_clear()
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch.object(tts._rq, "urlopen", side_effect=self.response)
        self.urlopen = self.network.start()
        self.addCleanup(self.network.stop)

    def response(self, req, **kwargs):
        if "googleapis.com" in req.full_url:
            return io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [
                {"inlineData": {"mimeType": "audio/L16;codec=pcm;rate=24000",
                                "data": base64.b64encode(self.pcm).decode()}}
            ]}}]}).encode())
        if "/v2/voices" in req.full_url:
            return io.BytesIO(json.dumps({"voices": [
                {"voice_id": "account-built-in", "name": "Alice", "category": "premade"}
            ]}).encode())
        if "elevenlabs.io" in req.full_url:
            return io.BytesIO(self.pcm if "pcm_24000" in req.full_url else self.mp3)
        audio = self.mp3 if json.loads(req.data).get("response_format") == "mp3" else self.wav
        return io.BytesIO(json.dumps({"audio_data": base64.b64encode(audio).decode()}).encode())

    def assert_audio(self, path):
        with AudioFileClip(str(path)) as audio:
            self.assertGreater(audio.duration, 0.2)
            self.assertLess(audio.duration, 0.5)
            self.assertGreater(abs(audio.get_frame(0.103)).max(), 0.01)

    def test_unset_provider_keeps_mistral_request_and_audio(self):
        output = self.root / "mistral.wav"
        self.assertEqual(tts.get_provider(), "mistral")
        self.assertEqual(tts.synth_to_file("Hello", str(output)), str(output))
        req = self.urlopen.call_args.args[0]
        self.assertEqual(req.full_url, tts.API_URL)
        self.assertEqual(json.loads(req.data), {"model": "voxtral-mini-tts-2603", "input": "Hello",
                                               "response_format": "wav", "voice": "gb_jane_neutral"})
        self.assertEqual(req.get_header("Authorization"), "Bearer test-mistral-key")
        self.assertEqual(output.read_bytes(), self.wav)
        self.assert_audio(output)

    def test_mistral_custom_voice_and_fallback(self):
        output = self.root / "mistral.wav"
        # the old positional arguments and cloned-voice contract still work
        tts.synth_to_file("Hello", str(output), "ignored", "cloned-id", "custom-model", "wav")
        self.assertEqual(json.loads(self.urlopen.call_args.args[0].data), {
            "model": "custom-model", "input": "Hello", "response_format": "wav", "voice_id": "cloned-id"})
        bad_voice = HTTPError(tts.API_URL, 400, "Bad request", {}, io.BytesIO(b"invalid_voice"))
        self.urlopen.side_effect = [bad_voice, self.response(self.urlopen.call_args.args[0])]
        with contextlib.redirect_stdout(io.StringIO()):
            tts.synth_to_file("Hello", str(output), voice_slug="missing-voice")
        reqs = [json.loads(call.args[0].data) for call in self.urlopen.call_args_list[-2:]]
        self.assertEqual([req["voice"] for req in reqs], ["missing-voice", "gb_jane_neutral"])

    def test_google_payload_and_pcm_wav(self):
        os.environ["TTS_PROVIDER"] = "google"
        output = self.root / "google.wav"
        tts.synth_to_file("Hello", str(output), voice_slug="Charon", style="Read calmly")
        req = self.urlopen.call_args.args[0]
        self.assertIn("gemini-2.5-flash-preview-tts:generateContent", req.full_url)
        self.assertNotIn("test-google-key", req.full_url)
        self.assertEqual(dict((k.lower(), v) for k, v in req.header_items())["x-goog-api-key"], "test-google-key")
        body = json.loads(req.data)
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "Read calmly:\nHello")
        self.assertEqual(body["generationConfig"], {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Charon"}}}})
        with wave.open(str(output)) as audio:
            self.assertEqual((audio.getframerate(), audio.getsampwidth(), audio.getnchannels()), (24000, 2, 1))
            self.assertEqual(audio.readframes(audio.getnframes()), self.pcm)
        self.assert_audio(output)

    def test_google_ready_wav_and_model_override(self):
        self.urlopen.side_effect = None
        self.urlopen.return_value = io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [
            {"text": "metadata"}, {"inlineData": {"mimeType": "audio/wav",
                                                  "data": base64.b64encode(self.wav).decode()}}
        ]}}]}).encode())
        output = self.root / "google.wav"
        tts.synth_to_file("Hello", str(output), provider="google", model="gemini-3.1-flash-tts-preview", style="")
        self.assertEqual(output.read_bytes(), self.wav)
        req = self.urlopen.call_args.args[0]
        self.assertIn("gemini-3.1-flash-tts-preview", req.full_url)
        self.assertEqual(json.loads(req.data)["contents"][0]["parts"][0]["text"], "Hello")

    def test_elevenlabs_mp3_bytes_and_auth(self):
        os.environ["TTS_PROVIDER"] = "elevenlabs"
        output = self.root / "elevenlabs.mp3"
        tts.synth_to_file("Hello", str(output))
        req = self.urlopen.call_args.args[0]
        self.assertIn(f"/v1/text-to-speech/account-built-in?output_format=mp3_44100_128", req.full_url)
        self.assertEqual(dict((k.lower(), v) for k, v in req.header_items())["xi-api-key"], "test-elevenlabs-key")
        self.assertEqual(json.loads(req.data), {"text": "Hello", "model_id": "eleven_multilingual_v2"})
        self.assertEqual(output.read_bytes(), self.mp3)
        self.assert_audio(output)

    def test_elevenlabs_free_pcm_wav_and_custom_voice(self):
        output = self.root / "elevenlabs.wav"
        tts.synth_to_file("Hello", str(output), provider="elevenlabs", voice_id="custom/id", fmt="wav")
        self.assertIn("custom%2Fid?output_format=pcm_24000", self.urlopen.call_args.args[0].full_url)
        self.assertEqual(output.read_bytes(), self.wav)
        self.assert_audio(output)

    def test_elevenlabs_default_uses_account_voice_and_reuses_lookup(self):
        options = tts.resolve_options(provider="elevenlabs")
        self.assertEqual(options["voice_id"], "account-built-in")
        req = self.urlopen.call_args.args[0]
        self.assertIn("/v2/voices?category=premade", req.full_url)
        self.assertEqual(tts.resolve_options(provider="elevenlabs"), options)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_elevenlabs_explicit_voice_skips_lookup(self):
        with patch.dict(os.environ, {"ELEVENLABS_VOICE_ID": "environment-voice"}):
            options = tts.resolve_options(provider="elevenlabs")
            self.assertEqual(options["voice_id"], "environment-voice")
            options = tts.resolve_options(provider="elevenlabs", voice_id="spec-voice")
            self.assertEqual(options["voice_id"], "spec-voice")
        self.urlopen.assert_not_called()

    def test_elevenlabs_no_builtin_voice_does_not_select_paid_library_voice(self):
        for body in ({"voices": [{"voice_id": "paid", "category": "professional"}]}, []):
            self.urlopen.side_effect = lambda *a, **k: io.BytesIO(json.dumps(body).encode())
            with self.assertRaises(tts.TTSError):
                tts.resolve_options(provider="elevenlabs")

    def test_elevenlabs_paid_voice_failure_is_not_cached(self):
        self.urlopen.side_effect = HTTPError("https://example.com", 402, "payment required", {},
                                            io.BytesIO(b"Free users cannot use library voices via the API"))
        output = self.root / "paid.mp3"
        with self.assertRaisesRegex(tts.TTSError, "402"):
            tts.synth_to_file("Hello", str(output), provider="elevenlabs", voice_id="paid-library")
        self.assertFalse(output.exists())

    def test_each_provider_requires_its_own_key(self):
        for provider, name in (("mistral", "MISTRAL_API_KEY"), ("google", "GOOGLE_API_KEY"),
                               ("elevenlabs", "ELEVENLABS_API_KEY")):
            with self.subTest(provider=provider), patch.dict(os.environ, {name: ""}):
                self.urlopen.reset_mock()
                with self.assertRaisesRegex(tts.TTSError, name):
                    tts.synth_to_file("Hello", str(self.root / "missing.wav"), provider=provider)
                self.urlopen.assert_not_called()
                self.assertFalse((self.root / "missing.wav").exists())

    def test_http_network_timeout_and_bad_json_are_provider_errors(self):
        for provider in ("mistral", "google", "elevenlabs"):
            failures = [HTTPError("https://example.com", 429, "quota", {}, io.BytesIO(b"quota exceeded")),
                        HTTPError("https://example.com", 401, "auth", {}, io.BytesIO(b"unauthorized")),
                        URLError("offline"), TimeoutError("timeout")]
            for error in failures:
                with self.subTest(provider=provider, error=type(error).__name__):
                    self.urlopen.side_effect = error
                    output = self.root / "failed.wav"
                    with self.assertRaises(tts.TTSError):
                        tts.synth_to_file("Hello", str(output), provider=provider)
                    self.assertFalse(output.exists())
        for provider in ("mistral", "google"):
            self.urlopen.side_effect = lambda *a, **k: io.BytesIO(b"not json")
            with self.assertRaises(tts.TTSError):
                tts.synth_to_file("Hello", str(self.root / "bad.wav"), provider=provider)

    def test_incomplete_or_invalid_audio_never_replaces_cache(self):
        output = self.root / "existing.wav"
        output.write_bytes(self.wav)
        bad_bodies = [b'{}', b'null', b'[]', b'{"candidates":[]}',
                      json.dumps({"candidates": [{"finishReason": "MAX_TOKENS"}]}).encode(),
                      json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {
                          "mimeType": "audio/L16", "data": "invalid base64!"}}]}}]}).encode()]
        for data in bad_bodies:
            self.urlopen.side_effect = lambda *a, data=data, **k: io.BytesIO(data)
            with self.assertRaises(tts.TTSError):
                tts.synth_to_file("Hello", str(output), provider="google")
            self.assertEqual(output.read_bytes(), self.wav)
        for provider in ("mistral", "elevenlabs"):
            self.urlopen.side_effect = lambda *a, **k: io.BytesIO(
                b'{"audio":"YWJj"}' if provider == "mistral" else b"not an mp3")
            with self.assertRaises(tts.TTSError):
                tts.synth_to_file("Hello", str(output), provider=provider)
            self.assertEqual(output.read_bytes(), self.wav)
        self.assertFalse(list(self.root.glob(".tts-*")))

    def test_provider_and_voice_settings_isolate_cached_audio(self):
        scene = {"narration": "Hello"}
        config = {"slug": "gb_jane_neutral", "model": "voxtral-mini-tts-2603"}
        paths = []
        for provider in ("mistral", "google", "elevenlabs"):
            os.environ["TTS_PROVIDER"] = provider
            path, duration = render.synth_narration(scene, self.root, config)
            paths.append(path)
            self.assertGreater(duration, 0)
            self.assertIn(f"narr_{provider}_", Path(path).name)
            calls = self.urlopen.call_count
            self.assertEqual(render.synth_narration(scene, self.root, config)[0], path)
            self.assertEqual(self.urlopen.call_count, calls)
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(self.urlopen.call_count, 4)
        google = json.loads(self.urlopen.call_args_list[1].args[0].data)
        self.assertEqual(google["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"], "Kore")
        self.assertIn("gemini-2.5-flash-preview-tts", self.urlopen.call_args_list[1].args[0].full_url)

        for provider, overrides in (("google", [{"slug": "Charon"}, {"model": "custom-model"}, {"style": "Slowly"}]),
                                    ("elevenlabs", [{"voice_id": "custom-voice"}, {"format": "wav"}]),
                                    ("mistral", [{"slug": "gb_other"}, {"voice_id": "clone"},
                                                 {"model": "custom-model"}, {"format": "mp3"}])):
            os.environ["TTS_PROVIDER"] = provider
            for override in overrides:
                # every setting that changes the sound must also change the cache key
                cfg = override if provider == "mistral" else {provider: override}
                path, _ = render.synth_narration(scene, self.root, cfg)
                self.assertNotIn(path, paths)
                paths.append(path)

    def test_old_text_only_cache_is_not_mistaken_for_another_voice(self):
        digest = hashlib.sha1(b"Hello").hexdigest()[:10]
        old = self.root / f"narr_{digest}_0.wav"
        old.write_bytes(self.wav)
        path, _ = render.synth_narration({"narration": "Hello"}, self.root, {})
        self.assertNotEqual(Path(path), old)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_per_bullet_audio_is_combined_and_cached_for_each_provider(self):
        scene = {"narration": "ignored", "narration_per_bullet": ["First", "Second"]}
        paths = []
        for provider in ("mistral", "google", "elevenlabs"):
            os.environ["TTS_PROVIDER"] = provider
            path, duration = render.synth_narration(scene, self.root, {})
            self.assertGreater(duration, 0.45)
            paths.append(path)
            calls = self.urlopen.call_count
            self.assertEqual(render.synth_narration(scene, self.root, {})[0], path)
            self.assertEqual(self.urlopen.call_count, calls)
        self.assertEqual(len(set(paths)), 3)
        self.assertEqual(self.urlopen.call_count, 7)

    def test_renderer_continues_with_silent_scene_after_provider_failure(self):
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({"meta": {"fps": 2}, "timeline": [
            {"type": "outro", "text": "Test", "narration": "Hello", "duration": 1, "anim": "none"}]}))
        for provider in ("mistral", "google", "elevenlabs"):
            for missing_key in (False, True):
                os.environ["TTS_PROVIDER"] = provider
                self.urlopen.side_effect = HTTPError("https://example.com", 429, "quota", {}, io.BytesIO(b"quota exceeded"))
                cache = self.root / f"cache-{provider}-{missing_key}"
                output = self.root / f"silent-{provider}-{missing_key}.mp4"
                env = {f"{provider.upper()}_API_KEY": ""} if missing_key else {}
                with patch.dict(os.environ, env), patch.object(render, "W", 320), patch.object(render, "H", 180), \
                        contextlib.redirect_stdout(io.StringIO()) as log:
                    render.render(str(spec), str(output), str(cache))
                self.assertIn("rendering scene 0 without narration", log.getvalue())
                self.assertFalse(list(cache.glob("narr_*")))
                with VideoFileClip(str(output)) as video:
                    self.assertIsNone(video.audio)
                    self.assertEqual(video.duration, 1)

    def test_embedded_narration_uses_correct_media_type(self):
        spec = render.load_spec(str(ROOT / "samples" / "sample-spec.json"))
        spec["timeline"] = [{"type": "outro", "text": "End"}]
        for provider, mime in (("mistral", "audio/wav"), ("google", "audio/wav"), ("elevenlabs", "audio/mpeg")):
            options = tts.resolve_options(provider=provider)
            audio = self.root / f"{provider}.{options['fmt']}"
            tts.synth_to_file("Hello", str(audio), **options)
            output = self.root / f"{provider}.pptx"
            pptx_export.build_pptx(spec, [{"narration_path": str(audio)}], str(output))
            slide = Presentation(output).slides[0]
            self.assertTrue(any(rel.target_part.content_type == mime and rel.target_part.blob == audio.read_bytes()
                                for rel in slide.part.rels.values()))

    def test_rendered_narration_starts_at_the_scene_offset(self):
        spec = self.root / "spec.json"
        spec.write_text(json.dumps({"meta": {"fps": 4}, "timeline": [
            {"type": "outro", "text": "Silent", "duration": 0.5, "anim": "none"},
            {"type": "outro", "text": "Narrated", "narration": "Hello", "duration": 2, "anim": "none"}]}))
        for provider in ("mistral", "google", "elevenlabs"):
            os.environ["TTS_PROVIDER"] = provider
            output = self.root / f"narrated-{provider}.mp4"
            with patch.object(render, "W", 320), patch.object(render, "H", 180), \
                    contextlib.redirect_stdout(io.StringIO()) as log:
                render.render(str(spec), str(output), str(self.root / f"cache-{provider}"))
            self.assertIn("starting at 0.50s (narration", log.getvalue())
            # check the encoded audio, including the silence before the narrated scene
            with VideoFileClip(str(output)) as video:
                self.assertEqual(video.duration, 2.5)
                self.assertLess(abs(video.audio.get_frame(0.103)).max(), 0.001)
                self.assertGreater(abs(video.audio.get_frame(0.603)).max(), 0.01)

    def test_invalid_configuration_and_disk_errors(self):
        with self.assertRaises(tts.TTSError):
            tts.synth_to_file("Hello", str(self.root / "bad.wav"), provider="unknown")
        with self.assertRaises(tts.TTSError):
            tts.synth_to_file("Hello", str(self.root / "bad.mp3"), provider="google", fmt="mp3")
        # a local storage failure should not be hidden as an unavailable provider
        with patch.object(tts, "_synth_mistral", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                tts.synth_to_file("Hello", str(self.root / "failed.wav"))

    def test_error_messages_redact_provider_keys(self):
        self.urlopen.side_effect = HTTPError("https://example.com", 401, "auth", {},
                                            io.BytesIO(b"bad test-google-key and test-elevenlabs-key"))
        with self.assertRaises(tts.TTSError) as error:
            tts.synth_to_file("Hello", str(self.root / "bad.wav"), provider="google")
        self.assertNotIn("test-google-key", str(error.exception))
        self.assertNotIn("test-elevenlabs-key", str(error.exception))


if __name__ == "__main__":
    unittest.main()
