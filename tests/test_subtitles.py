"""check the srt format and both render paths without making api calls"""
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import subtitles


def parse_srt(text):
    """read file separately mistakes are caught in how its written"""
    result = []
    for index, block in enumerate(text.strip().split("\n\n"), 1):
        number, timing, *lines = block.splitlines()
        assert int(number) == index
        match = re.fullmatch(
            r"(\d{2,}):(\d{2}):(\d{2}),(\d{3}) --> "
            r"(\d{2,}):(\d{2}):(\d{2}),(\d{3})", timing)
        assert match and lines
        values = list(map(int, match.groups()))
        times = [((h * 60 + m) * 60 + s) * 1000 + ms
                 for h, m, s, ms in (values[:4], values[4:])]
        result.append(subtitles.Cue(*times, "\n".join(lines)))
    return result


class SubtitleTests(unittest.TestCase):
    def test_handwritten_srt_round_trip(self):
        sample = "1\n00:00:59,999 --> 01:00:00,001\nHello, café!\n\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.srt"
            subtitles.write_srt(path, parse_srt(sample))
            self.assertEqual(path.read_text(encoding="utf-8"), sample)

    def test_rounding_carries_into_next_minute_and_hour(self):
        for start, expected in [(59.9996, "00:01:00,000"),
                                (3599.9996, "01:00:00,000")]:
            cue = subtitles.narration_cues("Hello", start, 1)[0]
            self.assertEqual(subtitles.timestamp(cue.start_ms), expected)

    def test_long_narration_is_readable_and_covers_audio(self):
        text = "Café narration with enough words to need several readable cues. " * 12
        cues = subtitles.narration_cues(text, 3.25, 47.125)
        self.assertGreater(len(cues), 1)
        self.assertEqual(cues[0].start_ms, 3250)
        self.assertEqual(cues[-1].end_ms, 50375)
        self.assertEqual(" ".join(c.text.replace("\n", " ") for c in cues), text.strip())
        for i, cue in enumerate(cues):
            self.assertTrue(0 < cue.end_ms - cue.start_ms <= 6500)
            self.assertLessEqual(len(cue.text.splitlines()), 2)
            self.assertTrue(all(len(line) <= 42 for line in cue.text.splitlines()))
            if i:
                self.assertEqual(cues[i - 1].end_ms, cue.start_ms)

    def test_slow_text_and_long_unbroken_words(self):
        for text in ["Slow narration", "x" * 150]:
            for cue in subtitles.narration_cues(text, 0, 30):
                self.assertTrue(0 < cue.end_ms - cue.start_ms <= 6500)
                self.assertTrue(all(len(line) <= 42 for line in cue.text.splitlines()))

    def test_empty_or_zero_duration_narration(self):
        self.assertEqual(subtitles.narration_cues(" \n ", 0, 2), [])
        self.assertEqual(subtitles.narration_cues("Hello", 0, 0), [])

    def test_actual_render_normal_and_streamed(self):
        import render
        from moviepy import ColorClip

        # more than 12 scenes uses the long-video path, so check both here
        for count in (4, 13):
            with self.subTest(scenes=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                wav = root / "voice.wav"
                # a one-second audio file gives known timings without using tts
                with wave.open(str(wav), "wb") as audio:
                    audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                    audio.writeframes(b"\0\0" * 8000)
                scenes = [{"type": "title", "text": "Test", "duration": 0.5,
                           "anim": "none"} for _ in range(count)]
                scenes[1].update(narration="Hello, café!", padding=0.5)
                scenes[2].update(narration="Ignored fallback",
                                 narration_per_bullet=["First bullet.", "Second bullet."],
                                 padding=0.5)
                spec = root / "spec.json"
                spec.write_text(json.dumps({"meta": {"fps": 2}, "timeline": scenes}))
                output = root / "custom.name.mp4"

                def synth(scene, *args):
                    return (str(wav), 1.0) if scene.get("narration") else (None, 0.0)

                log = io.StringIO()
                # keep the video small so this is quick, but still encode a real mp4
                with patch.object(render, "W", 320), patch.object(render, "H", 180), \
                        patch.dict(render.BUILDERS, title=lambda *a: ColorClip((320, 180), (0, 0, 0))), \
                        patch.object(render, "synth_narration", side_effect=synth), \
                        patch.object(render, "_export_pptx"), contextlib.redirect_stdout(log):
                    render.render(str(spec), str(output), str(root / "cache"))
                self.assertGreater(output.stat().st_size, 0)
                cues = parse_srt(output.with_suffix(".srt").read_text(encoding="utf-8"))
                self.assertEqual(cues, [subtitles.Cue(500, 1500, "Hello, café!"),
                                        subtitles.Cue(2000, 3000, "First bullet. Second bullet.")])
                self.assertIn("starting at 0.50s (narration 1.00s)", log.getvalue())
                self.assertIn("starting at 2.00s (narration 1.00s)", log.getvalue())
                render._export_srt([], str(output))
                self.assertFalse(output.with_suffix(".srt").exists())


if __name__ == "__main__":
    unittest.main()
