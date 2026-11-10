"""Run with:  python -m unittest discover -s tests -v"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import subtitles as sub  # noqa: E402

LONG = ("Revenue grew twenty four percent this quarter, churn fell by three "
        "points, and we closed two new enterprise accounts. Looking ahead, we "
        "launch the new product in October, enter two new markets, and keep "
        "hiring in engineering across every region we operate in today.")


class Timestamp(unittest.TestCase):
    def test_format(self):
        self.assertEqual(sub.format_timestamp(0), "00:00:00,000")
        self.assertEqual(sub.format_timestamp(7.3), "00:00:07,300")
        self.assertEqual(sub.format_timestamp(3661.5), "01:01:01,500")
        self.assertEqual(sub.format_timestamp(59.9996), "00:01:00,000")

    def test_parse_roundtrip(self):
        for t in (0, 0.001, 12.345, 3599.999, 7384.2):
            self.assertAlmostEqual(sub.parse_timestamp(sub.format_timestamp(t)), t, places=3)

    def test_parse_rejects_dot_milliseconds(self):
        with self.assertRaises(ValueError):
            sub.parse_timestamp("00:00:01.000")


class Splitting(unittest.TestCase):
    def test_short_text_is_one_cue_covering_the_clip(self):
        cues = sub.split_cues("Welcome to the review.", 10.0, 3.0)
        self.assertEqual(len(cues), 1)
        self.assertEqual((cues[0]["start"], cues[0]["end"]), (10.0, 13.0))

    def test_long_text_splits_into_readable_cues(self):
        cues = sub.split_cues(LONG, 0.0, 20.0)
        self.assertGreater(len(cues), 1)
        for c in cues:
            lines = c["text"].split("\n")
            self.assertLessEqual(len(lines), 2)
            for line in lines:
                self.assertLessEqual(len(line), 42, line)
            self.assertLessEqual(c["end"] - c["start"], 6.5 + 1e-6)

    def test_slow_narration_is_split_by_duration(self):
        # short text, but spoken over 20 s -> no cue may linger > 6.5 s
        cues = sub.split_cues("One two three four five six seven eight nine ten", 0, 20)
        self.assertGreater(len(cues), 1)
        for c in cues:
            self.assertLessEqual(c["end"] - c["start"], 6.5 + 1e-6)

    def test_contiguous_no_overlap_and_exact_bounds(self):
        cues = sub.split_cues(LONG, 5.0, 20.0)
        self.assertEqual(cues[0]["start"], 5.0)
        self.assertAlmostEqual(cues[-1]["end"], 25.0)
        for a, b in zip(cues, cues[1:]):
            self.assertAlmostEqual(a["end"], b["start"])

    def test_no_words_lost_or_reordered(self):
        cues = sub.split_cues(LONG, 0, 20)
        joined = " ".join(c["text"].replace("\n", " ") for c in cues)
        self.assertEqual(joined.split(), LONG.split())

    def test_empty_or_zero_duration(self):
        self.assertEqual(sub.split_cues("", 0, 5), [])
        self.assertEqual(sub.split_cues("hi", 0, 0), [])


class RoundTrip(unittest.TestCase):
    def test_build_then_parse(self):
        cues = sub.split_cues(LONG, 1.0, 20.0) + sub.split_cues("Thanks.", 21.0, 2.0)
        parsed = sub.parse_srt(sub.build_srt(cues))
        self.assertEqual(len(parsed), len(cues))
        for a, b in zip(cues, parsed):
            self.assertAlmostEqual(a["start"], b["start"], places=3)
            self.assertAlmostEqual(a["end"], b["end"], places=3)
            self.assertEqual(a["text"], b["text"])

    def test_format_is_standard(self):
        out = sub.build_srt([{"start": 0, "end": 1.5, "text": "Hi"}])
        self.assertEqual(out, "1\n00:00:00,000 --> 00:00:01,500\nHi\n")

    def test_parser_rejects_bad_numbering(self):
        with self.assertRaises(ValueError):
            sub.parse_srt("2\n00:00:00,000 --> 00:00:01,000\nHi\n")


if __name__ == "__main__":
    unittest.main()
