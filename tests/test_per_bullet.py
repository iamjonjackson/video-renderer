"""Run: python3 -m unittest discover tests  (needs moviepy + matplotlib)"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import render  # noqa: E402

ITEMS = ["Revenue up 24%", "Churn down 3 points", "Two new enterprise clients"]
PER = ["Revenue is up.", "Churn is down.", "Two new clients."]
SEGS = [{"text": PER[0], "start": 0.0, "duration": 3.01},
        {"text": PER[1], "start": 3.01, "duration": 1.72},
        {"text": PER[2], "start": 4.73, "duration": 3.84}]


class RevealTimesTests(unittest.TestCase):
    def test_per_bullet_uses_cumulative_audio_offsets(self):
        scene = {"type": "bullets", "items": ITEMS, "narration_per_bullet": PER}
        self.assertEqual(render.bullet_reveal_times(scene, SEGS), [0.0, 3.01, 4.73])

    def test_single_narration_falls_back_to_stagger(self):
        scene = {"type": "bullets", "items": ITEMS, "narration": "One clip."}
        self.assertIsNone(render.bullet_reveal_times(scene, SEGS[:1]))

    def test_silent_falls_back_to_stagger(self):
        scene = {"type": "bullets", "items": ITEMS}
        self.assertIsNone(render.bullet_reveal_times(scene, []))

    def test_clip_count_mismatch_falls_back_to_stagger(self):
        scene = {"type": "bullets", "items": ITEMS, "narration_per_bullet": PER[:2]}
        self.assertIsNone(render.bullet_reveal_times(scene, SEGS[:2]))


class BuildBulletsRevealTests(unittest.TestCase):
    def setUp(self):
        self.theme = dict(vars(render.presets)["dark"])

    def test_bullets_start_at_reveal_times(self):
        scene = {"type": "bullets", "heading": "H", "items": ITEMS, "narration_per_bullet": PER}
        clip = render.build_bullets(scene, self.theme, reveal_times=[0.0, 3.01, 4.73])
        self.assertEqual([c.start for c in clip.clips[-3:]], [0.0, 3.01, 4.73])

    def test_without_reveal_times_uses_stagger(self):
        scene = {"type": "bullets", "heading": "H", "items": ITEMS, "stagger": 0.4}
        clip = render.build_bullets(scene, self.theme)
        self.assertEqual([c.start for c in clip.clips[-3:]], [0.0, 0.4, 0.8])

    def test_per_bullet_duration_fits_all_narration(self):
        scene = {"type": "bullets", "items": ITEMS, "narration_per_bullet": PER}
        total = SEGS[-1]["start"] + SEGS[-1]["duration"]
        self.assertAlmostEqual(render.scene_duration(scene, total), total + 1.0)


if __name__ == "__main__":
    unittest.main()
