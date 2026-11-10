"""Boundary-frame and render-routing evidence for authored scene transitions."""

import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from moviepy import ColorClip, VideoClip, VideoFileClip

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
composition = importlib.import_module("src.composition")
render = importlib.import_module("src.render")


class SceneTransitionTests(unittest.TestCase):
    def timeline(self, effect):
        # Outgoing endpoint and incoming local time are observable separately.
        first = VideoClip(lambda t: np.full((4, 8, 3), round(t * 100), dtype=np.uint8), duration=1)
        second = VideoClip(lambda t: np.full((4, 8, 3), round(200 + t * 20), dtype=np.uint8), duration=2)
        third = ColorClip((8, 4), color=(10, 20, 30), duration=1)
        scenes = [{"transition": {"effect": effect, "duration": 0.5}}, {}, {}]
        return composition.build_timeline([first, second, third], scenes, 8, 4)

    def test_crossfade_uses_frozen_outgoing_and_live_incoming_without_overlap(self):
        with self.timeline("crossfade") as clip:
            self.assertEqual(clip.duration, 4)
            for time, value in ((0.5, 50), (0.99, 99), (1, 100),
                                (1.25, 152), (1.5, 210), (2, 220)):
                with self.subTest(time=time):
                    np.testing.assert_array_equal(clip.get_frame(time), np.full((4, 8, 3), value))
            np.testing.assert_array_equal(clip.get_frame(3), np.full((4, 8, 3), (10, 20, 30)))
            np.testing.assert_array_equal(clip.get_frame(1.25), clip.get_frame(1.25))

    def test_slide_left_fills_frame_and_changes_to_incoming_at_end(self):
        with self.timeline("slide-left") as clip:
            np.testing.assert_array_equal(clip.get_frame(1), np.full((4, 8, 3), 100))
            middle = clip.get_frame(1.25)
            np.testing.assert_array_equal(middle[:, :4], np.full((4, 4, 3), 100))
            np.testing.assert_array_equal(middle[:, 4:], np.full((4, 4, 3), 205))
            np.testing.assert_array_equal(clip.get_frame(1.5), np.full((4, 8, 3), 210))
            self.assertEqual(middle.dtype, np.uint8)
            self.assertEqual(middle.shape, (4, 8, 3))

    def test_slide_translates_spatial_content_instead_of_wiping(self):
        outgoing = np.tile(np.arange(8, dtype=np.uint8)[None, :, None], (4, 1, 3))
        incoming = outgoing + 100
        clips = [VideoClip(lambda t: outgoing, duration=1), VideoClip(lambda t: incoming, duration=1)]
        with composition.build_timeline(clips, [{"transition": {"effect": "slide-left", "duration": 1}}, {}], 8, 4) as clip:
            np.testing.assert_array_equal(clip.get_frame(1.5)[0, :, 0], [4, 5, 6, 7, 100, 101, 102, 103])

    def test_legacy_transition_strings_are_cuts(self):
        clips = [ColorClip((8, 4), (255, 0, 0), duration=1), ColorClip((8, 4), (0, 0, 255), duration=1)]
        with composition.build_timeline(clips, [{"transition": "fade"}, {}], 8, 4) as clip:
            self.assertEqual(clip.duration, 2)
            self.assertEqual(tuple(clip.get_frame(1)[0, 0]), (0, 0, 255))

    def test_real_encoded_clip_retains_duration_and_boundary_blend(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "transition.mp4")
            with self.timeline("crossfade") as clip:
                clip.write_videofile(path, fps=20, codec="libx264", audio=False, logger=None)
            with VideoFileClip(path) as decoded:
                self.assertAlmostEqual(decoded.duration, 4, places=2)
                self.assertEqual(decoded.size, [8, 4])
                self.assertLess(abs(int(decoded.get_frame(1)[0, 0, 0]) - 100), 6)
                self.assertLess(abs(int(decoded.get_frame(1.25)[0, 0, 0]) - 152), 6)
                self.assertLess(abs(int(decoded.get_frame(1.5)[0, 0, 0]) - 210), 6)

    def test_render_rejects_streamed_objects_before_building_scenes(self):
        spec = {"meta": {"resolution": {"width": 1280, "height": 720}, "fps": 24},
                "theme": {}, "timeline": [{"type": "composition", "transition": {"effect": "crossfade", "duration": 0.5}}] * 13}
        with patch.object(render, "load_spec", return_value=spec), patch.object(render.composition, "build_clip") as builder:
            with self.assertRaisesRegex(ValueError, "at most 12 scenes"):
                render.render("unused.json", "unused.mp4")
            builder.assert_not_called()

    def test_video_only_skips_deck_artifacts_in_short_and_streamed_renders(self):
        for count in (1, 13):
            with self.subTest(count=count):
                scenes = [{"type": "composition", "motion_version": 1, "duration": 1}] * count
                spec = {"meta": {"resolution": {"width": 1280, "height": 720}, "fps": 24},
                        "theme": {}, "timeline": scenes}
                with tempfile.TemporaryDirectory() as temp, \
                        patch.object(render, "load_spec", return_value=spec), \
                        patch.object(render.composition, "build_clip", side_effect=lambda *args: ColorClip((8, 4), (0, 0, 0))), \
                        patch.object(render, "scene_narration", return_value=(None, 0)), \
                        patch.object(render, "collect_artifacts") as collect, \
                        patch.object(render, "_export_pptx") as export, \
                        patch.object(render, "_ffmpeg_exe", return_value="ffmpeg"), \
                        patch.object(render.subprocess, "run") as encode, \
                        patch.object(render, "concatenate_videoclips") as concatenate, \
                        patch.object(ColorClip, "write_videofile") as segment:
                    render.render("unused.json", "unused.mp4", workdir=temp, export_pptx=False)
                    collect.assert_not_called()
                    export.assert_not_called()
                    if count == 1:
                        concatenate.return_value.write_videofile.assert_called_once()
                        encode.assert_not_called()
                    else:
                        self.assertEqual(segment.call_count, 13)
                        encode.assert_called_once()

    def test_video_only_cli_encodes_mp4_and_rejects_conflicting_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = Path(temp) / "spec.json"
            output = Path(temp) / "video.mp4"
            spec.write_text(json.dumps({
                "meta": {"resolution": {"width": 1280, "height": 720}, "fps": 10},
                "timeline": [{"type": "composition", "motion_version": 1,
                              "duration": 0.2, "elements": []}],
            }))
            command = [sys.executable, str(Path(render.__file__)), str(spec),
                       "-o", str(output), "--workdir", str(Path(temp) / "cache"), "--video-only"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.is_file())
            self.assertFalse(output.with_suffix(".pptx").exists())
            with VideoFileClip(str(output)) as clip:
                self.assertEqual(clip.size, [1280, 720])
                self.assertAlmostEqual(clip.duration, 0.2, places=2)
            result = subprocess.run(command + ["--pptx-only"], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn("not allowed with argument", result.stderr)

    def test_short_render_routes_only_object_transitions_to_timeline(self):
        for transition, authored in (({"effect": "crossfade", "duration": 0.5}, True), ("fade", False), (None, False)):
            scenes = [{"type": "composition", "motion_version": 1, "duration": 1},
                      {"type": "composition", "motion_version": 1, "duration": 1}]
            if transition is not None:
                scenes[0]["transition"] = transition
            spec = {"meta": {"resolution": {"width": 1280, "height": 720}, "fps": 24}, "theme": {}, "timeline": scenes}
            with tempfile.TemporaryDirectory() as temp, patch.object(render, "load_spec", return_value=spec), \
                    patch.object(render.composition, "build_clip", side_effect=lambda *args: ColorClip((8, 4), (0, 0, 0))), \
                    patch.object(render, "scene_narration", return_value=(None, 0)), \
                    patch.object(render, "collect_artifacts", return_value={}), patch.object(render, "_export_pptx"), \
                    patch.object(render.composition, "build_timeline") as timeline, \
                    patch.object(render, "concatenate_videoclips") as concatenate:
                render.render("unused.json", "unused.mp4", workdir=temp)
                self.assertEqual(timeline.called, authored)
                self.assertEqual(concatenate.called, not authored)
                selected = timeline if authored else concatenate
                selected.return_value.write_videofile.assert_called_once()


if __name__ == "__main__":
    unittest.main()
