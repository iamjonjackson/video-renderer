"""Mocked tests for the one-shot TTS CLI (no network or API keys)."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import tts_cli  # noqa: E402


class CliTests(unittest.TestCase):
    def test_forwards_arguments_and_adds_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip"
            with mock.patch.object(tts_cli, "resolve_provider",
                                   return_value="google"), \
                 mock.patch.object(tts_cli, "resolve_format",
                                   return_value="wav"), \
                 mock.patch.object(tts_cli, "synth_to_file",
                                   return_value="wrote") as synth:
                rc = tts_cli.main([
                    "--provider", "google", "--text", "hello",
                    "--output", str(out), "--voice", "Kore",
                    "--voice-id", "voice1", "--model", "gemini-x",
                    "--style", "calm", "--strict",
                ])
        self.assertEqual(rc, 0)
        synth.assert_called_once_with(
            "hello", str(out.with_suffix(".wav")),
            voice_slug="Kore", voice_id="voice1", model="gemini-x",
            fmt="wav", provider="google", style="calm", strict=True,
        )

    def test_rejects_extension_mismatch(self):
        with mock.patch.object(tts_cli, "resolve_provider",
                               return_value="google"), \
             mock.patch.object(tts_cli, "resolve_format",
                               return_value="wav"), \
             mock.patch.object(tts_cli, "synth_to_file") as synth:
            rc = tts_cli.main([
                "--provider", "google", "--text", "hello",
                "--output", "clip.mp3",
            ])
        self.assertEqual(rc, 2)
        synth.assert_not_called()

    def test_list_providers(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = tts_cli.main(["--list-providers"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().split(), list(tts_cli.PROVIDERS))

    def test_text_required(self):
        with self.assertRaises(SystemExit) as caught:
            tts_cli.main(["--provider", "google", "--output", "clip.wav"])
        self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
