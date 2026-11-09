"""Run: python3 -m unittest discover tests  (needs moviepy + matplotlib)"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import render  # noqa: E402

SCENE = {"type": "bullets", "heading": "Key Wins", "stagger": 0.4,
         "items": ["Revenue up 24%", "Churn down 3 points", "Two new enterprise clients"]}


class StaggerTests(unittest.TestCase):
    def setUp(self):
        theme = dict(vars(render.presets)["dark"])
        self.theme = theme
        self.clip = render.build_bullets(SCENE, theme).with_duration(4.4)
        self.bullets = self.clip.clips[-3:]

    def test_bullet_start_times_follow_stagger(self):
        self.assertEqual([c.start for c in self.bullets], [0.0, 0.4, 0.8])

    def test_heading_and_background_visible_from_start(self):
        self.assertTrue(all(c.start == 0 for c in self.clip.clips[:-3]))

    def test_late_bullets_do_not_vanish_before_scene_end(self):
        for c in self.bullets:
            self.assertIsNone(c.end)

    def test_bullet_fades_in_via_mask(self):
        late = self.bullets[2]
        self.assertAlmostEqual(late.mask.get_frame(0).max(), 0.0)
        self.assertAlmostEqual(late.mask.get_frame(1.0).max(), 1.0, places=3)

    def test_custom_stagger(self):
        clip = render.build_bullets({**SCENE, "stagger": 1.0}, self.theme)
        self.assertEqual([c.start for c in clip.clips[-3:]], [0.0, 1.0, 2.0])

    def test_no_narration_duration_unchanged(self):
        self.assertAlmostEqual(render.scene_duration(SCENE, 0.0), 1.2 + 0.4 * 3 + 2.0)


if __name__ == "__main__":
    unittest.main()
