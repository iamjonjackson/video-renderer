"""Run: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import subtitles as st

LONG = ("Monthly recurring revenue climbed from four hundred ten thousand in "
        "July to five hundred twelve thousand in September, driven by two new "
        "enterprise clients and lower churn. Looking ahead, we launch the new "
        "product in October and continue hiring in engineering.")


class TimestampTests(unittest.TestCase):
    def test_format(self):
        self.assertEqual(st.format_timestamp(0), "00:00:00,000")
        self.assertEqual(st.format_timestamp(3.5), "00:00:03,500")
        self.assertEqual(st.format_timestamp(3725.042), "01:02:05,042")

    def test_roundtrip(self):
        for t in (0, 0.001, 59.999, 61.25, 3600.5):
            self.assertAlmostEqual(st.parse_timestamp(st.format_timestamp(t)), t, places=3)


class ChunkTests(unittest.TestCase):
    def test_short_single_cue(self):
        cues = st.chunk_narration("Hello world.", 2.0, 1.5)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0]["start"], cues[0]["end"]), (2.0, 3.5))

    def test_long_is_split_and_readable(self):
        cues = st.chunk_narration(LONG, 10.0, 16.0)
        self.assertGreater(len(cues), 1)
        for c in cues:
            lines = c["text"].split("\n")
            self.assertLessEqual(len(lines), st.MAX_LINES)
            for line in lines:
                self.assertLessEqual(len(line), st.MAX_LINE_CHARS)
            self.assertLessEqual(c["end"] - c["start"], st.MAX_CUE_SECONDS + 1e-6)
        # contiguous, covering exactly the narration span
        self.assertAlmostEqual(cues[0]["start"], 10.0)
        self.assertAlmostEqual(cues[-1]["end"], 26.0)
        for a, b in zip(cues, cues[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        # no words lost
        self.assertEqual(" ".join(c["text"].replace("\n", " ") for c in cues), LONG)

    def test_slow_narration_respects_max_cue_seconds(self):
        cues = st.chunk_narration("A short but very slowly spoken line here.", 0, 20.0)
        for c in cues:
            self.assertLessEqual(c["end"] - c["start"], st.MAX_CUE_SECONDS + 1e-6)


class SrtTests(unittest.TestCase):
    def test_serialize_parse_roundtrip(self):
        segs = [{"text": "Welcome to the review.", "start": 0.0, "duration": 2.4},
                {"text": LONG, "start": 3.4, "duration": 16.0}]
        cues = st.build_cues(segs)
        srt = st.to_srt(cues)
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> 00:00:02,400\nWelcome"))
        parsed = st.parse_srt(srt)
        self.assertEqual(len(parsed), len(cues))
        for a, b in zip(parsed, cues):
            self.assertAlmostEqual(a["start"], b["start"], places=3)
            self.assertAlmostEqual(a["end"], b["end"], places=3)
            self.assertEqual(a["text"], b["text"])


if __name__ == "__main__":
    unittest.main()
