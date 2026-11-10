"""Actual MoviePy import/ffmpeg regression without reading repository credentials."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path


class MediaIsolationTests(unittest.TestCase):
    def test_dotenv_cannot_reintroduce_credentials_into_ffmpeg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sentinel = root / ".env"
            sentinel.write_text("FRAME_TEST_SECRET=sentinel-not-a-real-key\n")
            audio = root / "audio.wav"
            with wave.open(str(audio), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(24000)
                writer.writeframes(b"\0\0" * 12000)
            script = """
import json, os, subprocess, sys
import dotenv
# Route MoviePy's automatic lookup only to a disposable sentinel.
dotenv.find_dotenv = lambda *args, **kwargs: sys.argv[1]
from moviepy import AudioFileClip
original = subprocess.Popen
observed = []
def launch(*args, **kwargs):
    environment = kwargs.get('env') or os.environ
    assert 'FRAME_TEST_SECRET' not in environment
    assert environment.get('PYTHON_DOTENV_DISABLED') == '1'
    observed.append(args[0])
    return original(*args, **kwargs)
subprocess.Popen = launch
with AudioFileClip(sys.argv[2]) as clip:
    assert .45 < clip.duration < .55
assert observed
print(json.dumps({'launched': len(observed)}))
"""
            env = {
                key: os.environ[key]
                for key in ("PATH", "TMPDIR", "SYSTEMROOT")
                if key in os.environ
            }
            env["PYTHON_DOTENV_DISABLED"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", script, str(sentinel), str(audio)],
                env=env,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            self.assertGreater(json.loads(result.stdout)["launched"], 0)
