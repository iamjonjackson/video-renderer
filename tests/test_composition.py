"""Canvas geometry, glyphs and actual render/export invariants."""

import copy
import importlib
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
composition = importlib.import_module("src.composition")
validate = importlib.import_module("src.studio").validate_spec

BASE: dict[str, Any] = {
    "timeline": [
        {
            "type": "composition",
            "duration": 1,
            "background": {
                "style": "grid",
                "color": "#191925",
                "accent": "#6750a4",
                "motion": "drift",
            },
            "elements": [
                {
                    "id": "text",
                    "type": "text",
                    "text": "Café • canvas",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.3,
                    "font_size": 0.07,
                    "color": "#ffffff",
                },
                {
                    "id": "shape",
                    "type": "shape",
                    "shape": "ellipse",
                    "x": 0.1,
                    "y": 0.6,
                    "w": 0.15,
                    "h": 0.2,
                    "color": "#6750a4",
                },
                {
                    "id": "chart",
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["A", "B"],
                    "values": [2, 4],
                    "x": 0.3,
                    "y": 0.5,
                    "w": 0.6,
                    "h": 0.4,
                    "color": "#bba5ff",
                },
            ],
        }
    ]
}


def validate_motion_scene(scene):
    # Test the composition boundary directly: Studio's outer field allowlist is
    # integrated separately and is deliberately outside this change's scope.
    def fields(value, allowed, where):
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise ValueError(where)

    def number(value, where, low, high):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not low <= value <= high):
            raise ValueError(where)

    def text(value, where, maximum):
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError(where)

    return composition.validate_composition(scene, text, number, fields)


def entrance_scene(effect="fade", easing="linear"):
    return {
        "type": "composition", "duration": 2, "motion_version": 1,
        "background": {"style": "solid", "color": "#000000", "motion": "none"},
        "elements": [{
            "id": "box", "type": "shape", "shape": "rect", "color": "#ffffff",
            "x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4,
            "animation": {"effect": effect, "start": 0.5, "duration": 1, "easing": easing},
        }],
    }


class KeyframeMotionTests(unittest.TestCase):
    @staticmethod
    def scene():
        scene = entrance_scene()
        scene["duration"] = 3
        item = scene["elements"][0]
        del item["animation"]
        item["keyframes"] = [
            {"time": 0.5, "x": -0.2, "y": 0.2, "scale": 0.5, "opacity": 0.2},
            {"time": 1.5, "x": 0.2, "y": -0.2, "scale": 1.5, "opacity": 0.8},
            {"time": 2.5, "x": -0.4, "y": 0.4, "scale": 1, "opacity": 0.4},
        ]
        return scene

    def test_exact_knots_clamped_endpoints_and_reverse_segment(self):
        scene = validate_motion_scene(self.scene())
        item = scene["elements"][0]
        before = copy.deepcopy(item)
        for time, expected in (
            (-10, {"dx": -0.2, "dy": 0.2, "scale": 0.5, "opacity": 0.2}),
            (0.5, {"dx": -0.2, "dy": 0.2, "scale": 0.5, "opacity": 0.2}),
            (1.5, {"dx": 0.2, "dy": -0.2, "scale": 1.5, "opacity": 0.8}),
            (2.5, {"dx": -0.4, "dy": 0.4, "scale": 1, "opacity": 0.4}),
            (10, {"dx": -0.4, "dy": 0.4, "scale": 1, "opacity": 0.4}),
        ):
            with self.subTest(time=time):
                self.assertEqual(composition.motion_state(item, time), expected)
        for time, expected in (
            (0.75, {"dx": -0.1414213562373095, "dy": 0.1414213562373095,
                    "scale": 0.6464466094067262, "opacity": 0.2878679656440358}),
            (1, {"dx": 0, "dy": 0, "scale": 1, "opacity": 0.5}),
            (2, {"dx": -0.1, "dy": 0.1, "scale": 1.25, "opacity": 0.6}),
        ):
            with self.subTest(time=time):
                actual = composition.motion_state(item, time)
                for key, value in expected.items():
                    self.assertAlmostEqual(actual[key], value)
        self.assertEqual(item, before)

    def test_keyframes_combine_with_entrance_and_exit(self):
        scene = self.scene()
        item = scene["elements"][0]
        item["animation"] = {"effect": "slide", "direction": "right",
                             "start": 0, "duration": 0.5, "easing": "linear"}
        item["exit_animation"] = {"effect": "scale", "start": 2,
                                  "duration": 1, "easing": "linear"}
        validate_motion_scene(scene)
        for time, expected in (
            (0.25, {"dx": -0.17, "dy": 0.2, "scale": 0.5, "opacity": 0.1}),
            (2.5, {"dx": -0.4, "dy": 0.4, "scale": 0.925, "opacity": 0.2}),
        ):
            with self.subTest(time=time):
                actual = composition.motion_state(item, time)
                for key, value in expected.items():
                    self.assertAlmostEqual(actual[key], value)

    def test_validation_accepts_bounds_and_two_to_eight_frames(self):
        for count in (2, 8):
            scene = self.scene()
            scene["elements"][0]["keyframes"] = [
                {"time": 3 * i / (count - 1), "x": -1 if i % 2 else 1,
                 "y": 1 if i % 2 else -1, "scale": 0.5 if i % 2 else 1.5,
                 "opacity": i % 2}
                for i in range(count)
            ]
            original = copy.deepcopy(scene["elements"][0])
            validate_motion_scene(scene)
            self.assertEqual(scene["elements"][0], original)

    def test_validation_rejects_malformed_lists_and_duplicate_or_reverse_times(self):
        for invalid in (None, {}, (), "keyframes", [], [{}], [{}] * 9):
            scene = self.scene()
            scene["elements"][0]["keyframes"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for invalid in (None, [], "frame", 1):
            scene = self.scene()
            scene["elements"][0]["keyframes"][1] = invalid
            with self.subTest(frame=invalid), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for time in (0.5, 0.4):
            scene = self.scene()
            scene["elements"][0]["keyframes"][1]["time"] = time
            with self.subTest(time=time), self.assertRaises(ValueError):
                validate_motion_scene(scene)

    def test_validation_requires_exact_fields_and_finite_bounded_numbers(self):
        invalid_bounds = {"time": (-0.01, 3.01), "x": (-1.01, 1.01),
                          "y": (-1.01, 1.01), "scale": (0.49, 1.51),
                          "opacity": (-0.01, 1.01)}
        for key, bounds in invalid_bounds.items():
            for value in (*bounds, True, False, None, "1", float("nan"),
                          float("inf"), -float("inf")):
                scene = self.scene()
                scene["elements"][0]["keyframes"][1][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_motion_scene(scene)
            scene = self.scene()
            del scene["elements"][0]["keyframes"][1][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = self.scene()
        scene["elements"][0]["keyframes"][1]["easing"] = "linear"
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        for duration in (None, True, "3", -1, float("nan"), float("inf")):
            scene = self.scene()
            scene["duration"] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validate_motion_scene(scene)

    def test_keyframes_alone_require_motion_version_one(self):
        for version in (None, 0, 2, True, 1.0, "1"):
            scene = self.scene()
            if version is None:
                del scene["motion_version"]
            else:
                scene["motion_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_motion_scene(scene)

    def test_build_clip_midpoint_raster_uses_offsets_scale_and_opacity(self):
        import numpy as np

        scene = self.scene()
        scene["elements"][0]["keyframes"] = [
            {"time": 0, "x": 0, "y": 0, "scale": 1, "opacity": 1},
            {"time": 2, "x": 0.2, "y": 0.2, "scale": 0.5, "opacity": 0.5},
        ]
        validate_motion_scene(scene)
        static = copy.deepcopy(scene)
        del static["elements"][0]["keyframes"]
        clip = composition.build_clip(scene, 200, 100)
        resting = composition.build_clip(static, 200, 100)
        try:
            middle = clip.get_frame(1)
            self.assertFalse(np.array_equal(middle, resting.get_frame(0)))
            self.assertTrue(np.array_equal(clip.get_frame(0), resting.get_frame(0)))
            ys, xs = np.where(middle[:, :, 0] > 0)
            self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (90, 149, 45, 74))
            self.assertEqual(tuple(middle[50, 100]), (191, 191, 191))
        finally:
            clip.close()
            resting.close()

    def test_static_raster_and_editable_export_keep_resting_geometry(self):
        from pptx import Presentation
        from pptx.util import Inches

        scene = validate_motion_scene(self.scene())
        static = copy.deepcopy(scene)
        del static["elements"][0]["keyframes"]
        animated_image, x, y = composition.element_images(scene, 200, 100)[0]
        static_image, static_x, static_y = composition.element_images(static, 200, 100)[0]
        self.assertEqual((x, y, animated_image.tobytes()),
                         (static_x, static_y, static_image.tobytes()))
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, scene, Inches(10), Inches(5))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "keyframes.pptx"
            prs.save(str(path))
            exported = Presentation(str(path)).slides[0]
            shape = exported.shapes[0]
            self.assertEqual((shape.left, shape.top, shape.width, shape.height),
                             (Inches(3), Inches(1.5), Inches(4), Inches(2)))
            self.assertFalse(exported._element.xpath(".//p:timing"))


class ElementMotionTests(unittest.TestCase):
    def test_shared_easing_curves_at_quarter_midpoint_and_boundaries(self):
        expected = {
            "linear": (0.25, 0.5),
            "ease-out": (0.578125, 0.875),
            "ease-in-out": (0.1464466094067262, 0.5),
            "ease-out-quart": (0.68359375, 0.9375),
        }
        for easing, (quarter, midpoint) in expected.items():
            scene = validate_motion_scene(entrance_scene("fade", easing))
            animation = scene["elements"][0]["animation"]
            for time, value in ((0, 0), (0.5, 0), (0.75, quarter),
                                (1, midpoint), (1.5, 1), (4, 1)):
                with self.subTest(easing=easing, time=time):
                    self.assertAlmostEqual(composition.animation_progress(animation, time), value)

    def test_intensity_scales_only_transforms_without_rewriting_geometry(self):
        for effect in ("slide", "scale", "fade", "wipe", "words", "characters", "chart-draw"):
            for intensity in (0, 0.5, 1, 2):
                scene = entrance_scene(effect)
                item = scene["elements"][0]
                if effect in ("words", "characters"):
                    item.pop("shape")
                    item.update(type="text", text="One two")
                elif effect == "chart-draw":
                    item.pop("shape")
                    item.update(type="chart", labels=["A"], values=[1])
                item["animation"]["intensity"] = intensity
                geometry = {key: item[key] for key in ("x", "y", "w", "h")}
                validate_motion_scene(scene)
                before = copy.deepcopy(item)
                for time, remaining in ((0.5, 1), (1, 0.5), (1.5, 0)):
                    with self.subTest(effect=effect, intensity=intensity, time=time):
                        state = composition.motion_state(item, time)
                        self.assertEqual(set(state), {"opacity", "dx", "dy", "scale"})
                        self.assertAlmostEqual(state["dx"], -0.06 * intensity * remaining if effect == "slide" else 0)
                        self.assertEqual(state["dy"], 0)
                        self.assertAlmostEqual(state["scale"], 1 - 0.15 * intensity * remaining if effect == "scale" else 1)
                        self.assertAlmostEqual(state["opacity"], 1 - remaining if effect in ("slide", "scale", "fade") else 1)
                        self.assertAlmostEqual(composition.reveal_progress(item, time), 1 - remaining if effect not in ("slide", "scale", "fade") else 1)
                self.assertEqual(item, before)
                self.assertEqual({key: item[key] for key in geometry}, geometry)
        for effect, expected in (("slide", -0.06), ("scale", 0.85)):
            item = entrance_scene(effect)["elements"][0]
            self.assertAlmostEqual(composition.motion_state(item, 0.5)["dx" if effect == "slide" else "scale"], expected)

    def test_exit_intensity_and_easing_use_the_same_transform_contract(self):
        for effect, field, value in (("slide", "dx", 0.1125), ("scale", "scale", 0.71875)):
            scene = entrance_scene(effect)
            item = scene["elements"][0]
            item["exit_animation"] = item.pop("animation")
            item["exit_animation"].update(intensity=2, easing="ease-out-quart")
            if effect == "slide":
                item["exit_animation"]["direction"] = "right"
            validate_motion_scene(scene)
            state = composition.motion_state(item, 1)
            self.assertAlmostEqual(state[field], value)
            self.assertEqual(state["opacity"], 0.0625)

    def test_intensity_rejects_invalid_numbers_for_entrance_and_exit(self):
        for key in ("animation", "exit_animation"):
            for value in (-0.01, 2.01, True, False, "1", None, float("nan"), float("inf")):
                scene = entrance_scene()
                animation = scene["elements"][0].pop("animation")
                animation["intensity"] = value
                scene["elements"][0][key] = animation
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_motion_scene(scene)

    def test_each_effect_has_independent_start_mid_end_states(self):
        expected = {
            "fade": [
                {"opacity": 0, "dx": 0, "dy": 0, "scale": 1},
                {"opacity": 0.5, "dx": 0, "dy": 0, "scale": 1},
            ],
            "slide": [
                {"opacity": 0, "dx": -0.06, "dy": 0, "scale": 1},
                {"opacity": 0.5, "dx": -0.03, "dy": 0, "scale": 1},
            ],
            "scale": [
                {"opacity": 0, "dx": 0, "dy": 0, "scale": 0.85},
                {"opacity": 0.5, "dx": 0, "dy": 0, "scale": 0.925},
            ],
        }
        resting = {"opacity": 1, "dx": 0, "dy": 0, "scale": 1}
        for effect, states in expected.items():
            item = entrance_scene(effect)["elements"][0]
            for time, state in [(-1, states[0]), (0.5, states[0]), (1, states[1]),
                                (1.5, resting), (20, resting)]:
                with self.subTest(effect=effect, time=time):
                    actual = composition.motion_state(item, time)
                    self.assertEqual(set(actual), set(state))
                    for key, value in state.items():
                        self.assertAlmostEqual(actual[key], value)

    def test_ease_out_and_direction_use_scene_normalised_offsets(self):
        for direction, dx, dy in [("left", -0.0075, 0), ("right", 0.0075, 0),
                                   ("up", 0, -0.0075), ("down", 0, 0.0075)]:
            item = entrance_scene("slide", "ease-out")["elements"][0]
            item["animation"]["direction"] = direction
            with self.subTest(direction=direction):
                state = composition.motion_state(item, 1)
                self.assertEqual(state["opacity"], 0.875)
                self.assertAlmostEqual(state["dx"], dx)
                self.assertAlmostEqual(state["dy"], dy)
        item = entrance_scene("scale", "ease-out")["elements"][0]
        self.assertAlmostEqual(composition.motion_state(item, 1)["scale"], 0.98125)
        item = entrance_scene("fade", "ease-out")["elements"][0]
        self.assertEqual(composition.motion_state(item, 1)["opacity"], 0.875)

    def test_validation_rejects_nonfinite_timings_unknown_fields_and_modes(self):
        changes = [
            ("start", -0.1), ("start", float("nan")), ("start", float("inf")),
            ("start", True), ("start", "0"), ("start", 2),
            ("duration", 0), ("duration", 0.099), ("duration", 3.001),
            ("duration", float("inf")), ("duration", float("nan")),
            ("duration", True), ("duration", "1"), ("duration", 1.6),
            ("effect", "spin"), ("easing", "bounce"), ("direction", "left"),
            ("target", "missing-element"), ("repeat", 2), ("exit", "fade"),
        ]
        for key, value in changes:
            scene = entrance_scene()
            scene["elements"][0]["animation"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for missing in ("effect", "start", "duration", "easing"):
            scene = entrance_scene()
            del scene["elements"][0]["animation"][missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for invalid in (None, [], "fade"):
            scene = entrance_scene()
            scene["elements"][0]["animation"] = invalid
            with self.subTest(animation=invalid), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = entrance_scene("slide")
        scene["elements"][0]["animation"]["direction"] = "diagonal"
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        scene = entrance_scene("scale")
        scene["elements"][0]["animation"]["direction"] = "up"
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)

    def test_version_required_only_for_motion_and_geometry_is_preserved(self):
        scene = entrance_scene()
        original = copy.deepcopy(scene["elements"][0])
        validate_motion_scene(scene)
        self.assertEqual(scene["elements"][0], original)
        for version in (None, 0, 2, True, 1.0, "1"):
            scene = entrance_scene()
            if version is None:
                del scene["motion_version"]
            else:
                scene["motion_version"] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = entrance_scene()
        del scene["elements"][0]["animation"]
        del scene["motion_version"]
        validate_motion_scene(scene)
        for time in (0, 1, 20):
            self.assertEqual(composition.motion_state(scene["elements"][0], time),
                             {"opacity": 1, "dx": 0, "dy": 0, "scale": 1})
        scene["motion_version"] = 1
        validate_motion_scene(scene)
        scene["motion_version"] = 2
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)

    def test_timing_boundaries_and_unknown_scene_or_element_fields(self):
        for start, duration in ((0, 0.1), (0, 3), (2.9, 0.1)):
            scene = entrance_scene()
            scene["duration"] = 3
            scene["elements"][0]["animation"].update(start=start, duration=duration)
            validate_motion_scene(scene)
        scene = entrance_scene()
        scene["duration"] = 1.2
        scene["elements"][0]["animation"].update(start=0.8, duration=0.4)
        validate_motion_scene(scene)
        scene["elements"][0]["animation"]["duration"] = 0.400001
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        for duration in (None, -1, float("inf"), float("nan"), True):
            scene = entrance_scene()
            scene["duration"] = duration
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for target in ("scene", "element"):
            scene = entrance_scene()
            (scene if target == "scene" else scene["elements"][0])["motions"] = []
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = entrance_scene()
        scene["elements"].append(copy.deepcopy(scene["elements"][0]))
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)

    def test_rendered_frames_fade_slide_and_centred_scale(self):
        import numpy as np

        for effect in ("fade", "slide", "scale"):
            scene = validate_motion_scene(entrance_scene(effect))
            static = copy.deepcopy(scene)
            del static["elements"][0]["animation"]
            clip = composition.build_clip(scene, 200, 100)
            resting = composition.build_clip(static, 200, 100)
            try:
                with self.subTest(effect=effect):
                    self.assertFalse(clip.get_frame(0.5).any())
                    self.assertTrue(np.array_equal(clip.get_frame(1.5), resting.get_frame(0)))
                    self.assertTrue(np.array_equal(clip.get_frame(5), resting.get_frame(0)))
                    middle = clip.get_frame(1)
                    self.assertEqual(tuple(middle[50, 100]), (128, 128, 128))
                    ys, xs = np.where(middle[:, :, 0] > 64)
                    expected = {"fade": (60, 139, 30, 69),
                                "slide": (54, 133, 30, 69),
                                "scale": (63, 136, 32, 68)}[effect]
                    self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), expected)
            finally:
                clip.close()
                resting.close()

    def test_transparent_text_keeps_its_alpha_and_slide_directions_render(self):
        import numpy as np

        scene = entrance_scene()
        scene["elements"][0].update(type="text", text="Hi", font_size=0.08)
        del scene["elements"][0]["shape"]
        clip = composition.build_clip(scene, 200, 100)
        try:
            self.assertEqual(tuple(clip.get_frame(1)[65, 135]), (0, 0, 0))
            self.assertGreater(clip.get_frame(1).max(), 0)
            self.assertLessEqual(clip.get_frame(1).max(), 128)
        finally:
            clip.close()
        for direction, bounds in [("right", (66, 145, 30, 69)),
                                   ("up", (60, 139, 27, 66)),
                                   ("down", (60, 139, 33, 72))]:
            scene = entrance_scene("slide")
            scene["elements"][0]["animation"]["direction"] = direction
            clip = composition.build_clip(scene, 200, 100)
            try:
                ys, xs = np.where(clip.get_frame(1)[:, :, 0] > 64)
                self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), bounds)
            finally:
                clip.close()

    def test_actual_video_decodes_entrance_and_resting_pose(self):
        from moviepy import VideoFileClip

        scene = validate_motion_scene(entrance_scene("slide"))
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "entrance.mp4")
            clip = composition.build_clip(scene, 200, 100).with_duration(2)
            try:
                clip.write_videofile(path, fps=24, codec="libx264", audio=False, logger=None)
            finally:
                clip.close()
            with VideoFileClip(path) as decoded:
                self.assertEqual(decoded.size, [200, 100])
                self.assertLess(decoded.get_frame(0.25).max(), 5)
                self.assertTrue(115 <= decoded.get_frame(1)[50, 100, 0] <= 140)
                self.assertGreater(decoded.get_frame(1.75)[50, 100, 0], 245)
                self.assertLess(decoded.get_frame(1.75)[50, 50, 0], 5)

    def test_animated_pptx_retains_editable_resting_geometry_without_timing(self):
        from pptx import Presentation
        from pptx.util import Inches

        scene = copy.deepcopy(BASE["timeline"][0])
        scene["motion_version"] = 1
        for item, effect in zip(scene["elements"], ("fade", "slide", "scale")):
            item["animation"] = {"effect": effect, "start": 0, "duration": 1, "easing": "linear"}
        validate_motion_scene(scene)
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, scene, Inches(10), Inches(5.625))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "resting.pptx"
            prs.save(str(path))
            exported = Presentation(str(path)).slides[0]
            self.assertEqual(exported.shapes[0].text, "Café • canvas")
            self.assertTrue(exported.shapes[2].has_chart)
            for item, shape in zip(scene["elements"], exported.shapes):
                self.assertEqual(shape.left, round(item["x"] * Inches(10)))
                self.assertEqual(shape.top, round(item["y"] * Inches(5.625)))
                self.assertEqual(shape.width, round(item["w"] * Inches(10)))
                self.assertEqual(shape.height, round(item["h"] * Inches(5.625)))
            self.assertFalse(exported._element.xpath(".//p:timing"))


class RevealTests(unittest.TestCase):
    def text_scene(self, effect="words", align="left"):
        scene = entrance_scene(effect)
        item = scene["elements"][0]
        item.pop("shape")
        item.update(type="text", text="alpha beta\ngamma delta", font_size=0.08,
                    align=align, x=0.1, y=0.1, w=0.8, h=0.8)
        return scene

    def test_reveal_validation_type_phase_and_direction(self):
        for kind in ("text", "chart", "shape", "icon"):
            scene = entrance_scene("wipe")
            item = scene["elements"][0]
            item.pop("shape")
            item.update(type=kind)
            item.update({"text": {"text": "hello"},
                         "chart": {"labels": ["A"], "values": [1]},
                         "shape": {"shape": "rect"},
                         "icon": {"icon": "check"}}[kind])
            validate_motion_scene(scene)
            item["animation"]["effect"] = "words"
            if kind == "text":
                validate_motion_scene(scene)
            else:
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    validate_motion_scene(scene)
        for effect in ("words", "wipe"):
            scene = self.text_scene(effect)
            item = scene["elements"][0]
            item["exit_animation"] = item.pop("animation")
            with self.subTest(effect=effect), self.assertRaises(ValueError):
                validate_motion_scene(scene)
            scene = self.text_scene(effect)
            scene["elements"][0]["animation"]["direction"] = "left"
            with self.assertRaises(ValueError):
                validate_motion_scene(scene)

    def test_progress_endpoints_easing_and_legacy_state_keys(self):
        resting = {"opacity": 1, "dx": 0, "dy": 0, "scale": 1}
        for effect in ("words", "wipe"):
            item = self.text_scene(effect)["elements"][0]
            for time, expected in ((-1, 0), (0.5, 0), (1, 0.5), (1.5, 1), (20, 1)):
                with self.subTest(effect=effect, time=time):
                    self.assertEqual(composition.reveal_progress(item, time), expected)
                    self.assertEqual(composition.motion_state(item, time), resting)
            item["animation"]["easing"] = "ease-out"
            self.assertEqual(composition.reveal_progress(item, 1), 0.875)
        self.assertEqual(composition.reveal_progress({}, -1), 1)
        self.assertEqual(composition.reveal_progress(entrance_scene()["elements"][0], 1), 1)

    def test_words_are_stationary_with_wrapping_and_all_alignments(self):
        import numpy as np

        for align in ("left", "center", "right"):
            scene = self.text_scene(align=align)
            item = scene["elements"][0]
            # Narrow enough to wrap within a paragraph as well as at the newline.
            item.update(w=0.35, text="alpha beta\ngamma delta")
            full = np.asarray(composition.text_image(item, 140, 160))
            for count in (0, 1, 2, 3, 4):
                revealed = np.asarray(composition.text_image(item, 140, 160, count))
                mask = revealed[:, :, 3] > 0
                with self.subTest(align=align, count=count):
                    self.assertTrue(np.array_equal(revealed[mask], full[mask]))
                    self.assertEqual(bool(mask.any()), count > 0)
                    if count == 4:
                        self.assertTrue(np.array_equal(revealed, full))
            first = np.asarray(composition.text_image(item, 140, 160, 1))
            second = np.asarray(composition.text_image(item, 140, 160, 2))
            ys, xs = np.where(first[:, :, 3] > 0)
            self.assertGreater(len(xs), 0)
            self.assertTrue(np.array_equal(first[ys, xs], second[ys, xs]))
            self.assertGreater((second[:, :, 3] > 0).sum(), len(xs))

    def test_render_endpoints_backward_seek_and_word_frame_cache(self):
        import numpy as np
        from unittest.mock import patch

        for effect in ("words", "wipe"):
            scene = validate_motion_scene(self.text_scene(effect, "center"))
            static = copy.deepcopy(scene)
            del static["elements"][0]["animation"]
            with patch.object(composition, "text_image", wraps=composition.text_image) as render_text:
                clip = composition.build_clip(scene, 400, 200)
                resting = composition.build_clip(static, 400, 200)
                try:
                    self.assertFalse(clip.get_frame(0.5).any())
                    middle = clip.get_frame(1).copy()
                    self.assertGreater(middle.max(), 0)
                    calls = render_text.call_count
                    clip.get_frame(1.01)
                    self.assertEqual(render_text.call_count, calls)
                    self.assertTrue(np.array_equal(clip.get_frame(1.5), resting.get_frame(0)))
                    self.assertTrue(np.array_equal(clip.get_frame(20), resting.get_frame(0)))
                    self.assertTrue(np.array_equal(clip.get_frame(1), middle))
                    self.assertFalse(clip.get_frame(0).any())
                finally:
                    clip.close()
                    resting.close()

    def test_overflowing_tab_separated_word_reveal_is_clipped_to_box(self):
        import numpy as np

        scene = self.text_scene()
        item = scene["elements"][0]
        item.update(text="A" * 80 + "\tB", w=0.2)
        validate_motion_scene(scene)
        clip = composition.build_clip(scene, 400, 200)
        try:
            middle = clip.get_frame(1)
            self.assertGreater(middle.max(), 0)
            self.assertFalse(middle[:, 120:].any())
            self.assertTrue(np.array_equal(middle, clip.get_frame(1.5)))
        finally:
            clip.close()

    def test_wipe_masks_original_alpha_without_fade_or_motion(self):
        import numpy as np

        scene = entrance_scene("wipe")
        scene["elements"][0].update(shape="ellipse", color="#12ab34")
        clip = composition.build_clip(validate_motion_scene(scene), 200, 100)
        try:
            middle = clip.get_frame(1)
            self.assertEqual(tuple(middle[50, 90]), (18, 171, 52))
            self.assertFalse(middle[:, 100:].any())
            self.assertEqual(tuple(middle[30, 60]), (0, 0, 0))
            final = clip.get_frame(1.5)
            self.assertTrue(np.array_equal(middle[:, :100], final[:, :100]))
        finally:
            clip.close()


class ChunkAndSeriesTests(unittest.TestCase):
    @staticmethod
    def scene():
        scene = entrance_scene("chunks")
        scene["duration"] = 4
        item = scene["elements"][0]
        item.pop("shape")
        item.update(type="text", text="AB  ÉF\nZ", font_size=0.08, chunks=[
            {"text": "AB  ", "start": 0.5, "duration": 1},
            {"text": "ÉF\nZ", "start": 2, "duration": 1},
        ])
        return scene

    def test_chunk_source_prefix_timing_ignores_enclosing_progress(self):
        scene = validate_motion_scene(self.scene())
        item = scene["elements"][0]
        item["animation"].update(start=0, duration=0.1, easing="linear")
        for time, count in ((-1, 0), (0.5, 0), (1, 3), (1.5, 4),
                            (2, 4), (2.5, 7), (3, 8), (20, 8), (1, 3)):
            self.assertEqual(composition.chunk_visible_characters(item, time), count)
            self.assertEqual(composition.motion_state(item, time),
                             {"opacity": 1, "dx": 0, "dy": 0, "scale": 1})
            self.assertEqual(composition.reveal_progress(item, time), 1)

    def test_chunk_contract_rejects_loss_overlap_invalid_timing_and_exit(self):
        mutations = [
            lambda s: s.pop("motion_version"),
            lambda s: s["elements"][0].pop("chunks"),
            lambda s: s["elements"][0].update(chunks=[]),
            lambda s: s["elements"][0].update(chunks=s["elements"][0]["chunks"] * 9),
            lambda s: s["elements"][0]["chunks"][0].update(text="AB"),
            lambda s: s["elements"][0]["chunks"][0].update(text=""),
            lambda s: s["elements"][0]["chunks"][0].update(extra=1),
            lambda s: s["elements"][0]["chunks"][1].update(start=1.4),
            lambda s: s["elements"][0]["chunks"][1].update(start=3.1),
            lambda s: s["elements"][0]["animation"].update(effect="characters"),
            lambda s: s["elements"][0].update(exit_animation={
                "effect": "chunks", "start": 3, "duration": 1, "easing": "linear"}),
            lambda s: s["elements"][0].update(exit_animation={
                "effect": "fade", "start": 2.9, "duration": 1, "easing": "linear"}),
        ]
        for mutation in mutations:
            scene = self.scene()
            mutation(scene)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for key, values in (("start", [-1, True, float("nan"), float("inf")]),
                            ("duration", [0.09, 3.01, True, float("nan")])):
            for value in values:
                scene = self.scene()
                scene["elements"][0]["chunks"][0][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_motion_scene(scene)
        scene = self.scene()
        scene["elements"][0]["chunks"][1]["start"] = 1.5
        validate_motion_scene(scene)  # Touching endpoints are nonoverlapping.

    def test_chunk_frames_keep_full_layout_and_are_stateless(self):
        import numpy as np

        for align in ("left", "center", "right"):
            scene = self.scene()
            item = scene["elements"][0]
            item.update(align=align, w=0.2)
            validate_motion_scene(scene)
            clip = composition.build_clip(scene, 400, 240)
            full_item = copy.deepcopy(item)
            full_item.pop("animation")
            full_item.pop("chunks")
            static = copy.deepcopy(scene)
            static["elements"] = [full_item]
            resting = composition.build_clip(static, 400, 240)
            try:
                final = resting.get_frame(0)
                self.assertFalse(clip.get_frame(0).any())
                middle = clip.get_frame(2.5).copy()
                self.assertTrue(middle.any())
                mask = middle.any(axis=2)
                self.assertTrue(np.array_equal(middle[mask], final[mask]))
                self.assertTrue(np.array_equal(clip.get_frame(3), final))
                self.assertTrue(np.array_equal(clip.get_frame(20), final))
                self.assertTrue(np.array_equal(clip.get_frame(2.5), middle))
            finally:
                clip.close()
                resting.close()

    def test_series_stagger_contract_and_independent_signed_bar_geometry(self):
        for kind in ("bar", "horizontal"):
            scene = ContentEffectTests().scene(kind=kind)
            item = scene["elements"][0]
            item["series_stagger"] = 0.5
            validate_motion_scene(scene)
            for p, expected in ((0, [0, 0, 0]), (0.125, [0.25, 0, 0]),
                                (0.375, [0.75, 0.25, 0]),
                                (0.625, [1, 0.75, 0.25]), (1, [1, 1, 1])):
                self.assertEqual([composition.chart_series_progress(item, i, p)
                                  for i in range(3)], expected)
            image = composition.chart_animation_image(item, 400, 240, 0.375)
            if kind == "bar":  # Baseline y=110; negative grows down, positive up.
                self.assertEqual(image.getpixel((50, 165))[3], 255)
                self.assertEqual(image.getpixel((50, 180))[3], 0)
                self.assertEqual(image.getpixel((160, 95))[3], 255)
                self.assertEqual(image.getpixel((160, 80))[3], 0)
            else:  # Baseline x=240; negative grows left, positive right.
                self.assertEqual(image.getpixel((145, 40))[3], 255)
                self.assertEqual(image.getpixel((120, 40))[3], 0)
                self.assertEqual(image.getpixel((265, 100))[3], 255)
                self.assertEqual(image.getpixel((290, 100))[3], 0)
            original = copy.deepcopy(item)
            item.pop("series_stagger")
            self.assertEqual(composition.chart_image(original, 400, 240).tobytes(),
                             composition.chart_image(item, 400, 240).tobytes())
        for value in (-0.1, 0.5001, True, float("nan"), float("inf"), "0.1"):
            scene = ContentEffectTests().scene(kind="bar")
            scene["elements"][0]["series_stagger"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for kind in ("line", "area", "pie", "doughnut"):
            scene = ContentEffectTests().scene(kind=kind, values=[1, 3])
            scene["elements"][0]["series_stagger"] = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = ContentEffectTests().scene(kind="bar")
        scene.pop("motion_version")
        scene["elements"][0].pop("animation")
        scene["elements"][0]["series_stagger"] = 0.1
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)


class ContentEffectTests(unittest.TestCase):
    def scene(self, effect="chart-draw", kind="line", values=None):
        scene = entrance_scene(effect)
        item = scene["elements"][0]
        item.pop("shape")
        if effect == "characters":
            item.update(type="text", text="AB CD\nEF", font_size=0.08)
        else:
            item.update(type="chart", chart_type=kind, values=values or [-2, 2, 0],
                        labels=["A", "B", "C"] if values is None else ["A", "B"])
        return scene

    def test_content_effect_type_phase_and_direction_validation(self):
        for effect in ("characters", "chart-draw"):
            validate_motion_scene(self.scene(effect))
            for kind in ("text", "chart", "shape", "icon"):
                if kind == ("text" if effect == "characters" else "chart"):
                    continue
                scene = self.scene(effect)
                scene["elements"][0]["type"] = kind
                with self.subTest(effect=effect, kind=kind), self.assertRaises(ValueError):
                    validate_motion_scene(scene)
            scene = self.scene(effect)
            item = scene["elements"][0]
            item["exit_animation"] = item.pop("animation")
            with self.assertRaises(ValueError):
                validate_motion_scene(scene)
            scene = self.scene(effect)
            scene["elements"][0]["animation"]["direction"] = "left"
            with self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for values in ([0, 0], [-1, 2]):
            with self.assertRaises(ValueError):
                validate_motion_scene(self.scene(kind="pie", values=values))

    def test_characters_keep_wrapping_alignment_and_count_whitespace_codepoints(self):
        import numpy as np

        for align in ("left", "center", "right"):
            item = self.scene("characters")["elements"][0]
            item.update(align=align, text="AB CD\nÉF", w=0.2)
            full = np.asarray(composition.text_image(item, 80, 140))
            previous = np.zeros_like(full)
            for count in range(len(item["text"]) + 1):
                frame = np.asarray(composition.text_image(item, 80, 140,
                                                          visible_characters=count))
                mask = frame[:, :, 3] > 0
                with self.subTest(align=align, count=count):
                    self.assertTrue(np.array_equal(frame[mask], full[mask]))
                    self.assertTrue((frame[:, :, 3] >= previous[:, :, 3]).all())
                    if count in (3, 6):  # Wrapping space and explicit newline.
                        self.assertTrue(np.array_equal(frame, previous))
                previous = frame
            self.assertTrue(np.array_equal(previous, full))

    def test_characters_repeated_whitespace_consumes_original_source_steps(self):
        import numpy as np

        item = self.scene("characters")["elements"][0]
        item.update(text="  AB  CD\n\nEF  ", w=0.8)
        images = [np.asarray(composition.text_image(item, 320, 140,
                                                   visible_characters=count))
                  for count in range(len(item["text"]) + 1)]
        self.assertFalse(images[0].any())
        self.assertFalse(images[2].any())
        self.assertTrue(images[3].any())
        for before, after in ((4, 5), (5, 6), (8, 9), (9, 10), (12, 13), (13, 14)):
            self.assertTrue(np.array_equal(images[before], images[after]))
        self.assertGreater(images[7][:, :, 3].sum(), images[6][:, :, 3].sum())
        self.assertTrue(np.array_equal(images[-1],
                                      np.asarray(composition.text_image(item, 320, 140))))

    def test_chart_signed_bar_growth_and_line_segment_front(self):
        item = self.scene(kind="bar")["elements"][0]
        middle = composition.chart_animation_image(item, 400, 240, 0.5)
        self.assertEqual(middle.getpixel((50, 140))[:3], (255, 255, 255))
        self.assertEqual(middle.getpixel((50, 170))[3], 0)
        self.assertEqual(middle.getpixel((160, 80))[:3], (255, 255, 255))
        self.assertEqual(middle.getpixel((160, 40))[3], 0)
        item["chart_type"] = "horizontal"
        middle = composition.chart_animation_image(item, 400, 240, 0.5)
        self.assertGreater(middle.getpixel((180, 40))[3], 0)
        self.assertEqual(middle.getpixel((120, 40))[3], 0)
        self.assertGreater(middle.getpixel((280, 100))[3], 0)
        self.assertEqual(middle.getpixel((350, 100))[3], 0)
        item["chart_type"] = "line"
        middle = composition.chart_animation_image(item, 400, 240, 0.25)
        self.assertGreater(middle.getpixel((105, 110))[3], 0)
        self.assertEqual(middle.getpixel((132, 70))[3], 0)
        self.assertEqual(middle.getpixel((160, 30))[3], 0)
        self.assertGreater(middle.getpixel((50, 190))[3], 0)

    def test_pie_clockwise_truncation_opacity_percentages_and_transparent_hole(self):
        from unittest.mock import patch

        item = self.scene(kind="pie", values=[1, 3])["elements"][0]
        with patch.object(composition.ImageDraw.ImageDraw, "text",
                          autospec=True) as labels:
            early = composition.chart_animation_image(item, 400, 240, 0.2)
            self.assertNotIn("25%", [call.args[2] for call in labels.call_args_list])
            labels.reset_mock()
            middle = composition.chart_animation_image(item, 400, 240, 0.5)
            strings = [call.args[2] for call in labels.call_args_list]
            self.assertIn("25%", strings)
            self.assertNotIn("75%", strings)
        self.assertGreater(early.getpixel((250, 130))[3], 0)
        self.assertEqual(early.getpixel((170, 130))[3], 0)
        self.assertEqual(middle.getpixel((170, 130))[3], 235)
        self.assertEqual(middle.getpixel((200, 40))[3], 0)
        item["chart_type"] = "doughnut"
        final = composition.chart_image(item, 400, 240)
        self.assertEqual(final.getpixel((200, 100))[3], 0)
        self.assertGreater(final.getpixel((200, 170))[3], 0)

    def test_content_frames_start_mid_final_backward_seek_and_scaled_dimensions(self):
        import numpy as np

        for effect, kind in (("characters", "line"), ("chart-draw", "line"),
                             ("chart-draw", "area"), ("chart-draw", "bar"),
                             ("chart-draw", "horizontal"), ("chart-draw", "pie"),
                             ("chart-draw", "doughnut")):
            scene = self.scene(effect, kind, [1, 3])
            validate_motion_scene(scene)
            static = copy.deepcopy(scene)
            del static["elements"][0]["animation"]
            clip = composition.build_clip(scene, 400, 240)
            resting = composition.build_clip(static, 400, 240)
            try:
                with self.subTest(effect=effect, kind=kind):
                    self.assertFalse(clip.get_frame(-1).any())
                    self.assertFalse(clip.get_frame(0.5).any())
                    middle = clip.get_frame(1).copy()
                    self.assertTrue(middle.any())
                    final = resting.get_frame(0)
                    self.assertTrue(np.array_equal(clip.get_frame(1.5), final))
                    self.assertTrue(np.array_equal(clip.get_frame(20), final))
                    self.assertTrue(np.array_equal(clip.get_frame(1), middle))
                    self.assertFalse(clip.get_frame(0).any())
            finally:
                clip.close()
                resting.close()
        item = self.scene()["elements"][0]
        self.assertEqual(composition.chart_animation_image(item, 83, 57, 0.5).size, (83, 57))

    def test_content_effect_actual_video(self):
        from moviepy import VideoFileClip

        scene = validate_motion_scene(self.scene(kind="bar", values=[1, 3]))
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / "chart-draw.mp4")
            clip = composition.build_clip(scene, 400, 240).with_duration(2)
            try:
                clip.write_videofile(path, fps=24, codec="libx264", audio=False, logger=None)
            finally:
                clip.close()
            with VideoFileClip(path) as decoded:
                self.assertLess(decoded.get_frame(0.25).max(), 5)
                self.assertGreater(decoded.get_frame(1).max(), 240)
                self.assertGreater(decoded.get_frame(1.75).max(), 240)
                # The second bar's upper region is reached only at full progress.
                self.assertLess(decoded.get_frame(1)[96, 212, 0], 10)
                self.assertGreater(decoded.get_frame(1.75)[96, 212, 0], 240)


class ElementExitTests(unittest.TestCase):
    def scene(self, effect="fade", easing="linear"):
        scene = entrance_scene()
        scene["duration"] = 3
        scene["elements"][0]["exit_animation"] = {
            "effect": effect, "start": 2, "duration": 1, "easing": easing,
        }
        return scene

    def test_exit_start_mid_end_and_combined_entrance(self):
        for effect, dx, scale in (("fade", 0, 1), ("slide", -0.03, 1), ("scale", 0, 0.925)):
            scene = validate_motion_scene(self.scene(effect))
            item = scene["elements"][0]
            with self.subTest(effect=effect):
                self.assertEqual(composition.motion_state(item, 0)["opacity"], 0)
                self.assertEqual(composition.motion_state(item, 1)["opacity"], 0.5)
                self.assertEqual(composition.motion_state(item, 2),
                                 {"opacity": 1, "dx": 0, "dy": 0, "scale": 1})
                state = composition.motion_state(item, 2.5)
                self.assertEqual(state["opacity"], 0.5)
                self.assertAlmostEqual(state["dx"], dx)
                self.assertAlmostEqual(state["scale"], scale)
                self.assertEqual(composition.motion_state(item, 3)["opacity"], 0)
                self.assertEqual(composition.motion_state(item, 20)["opacity"], 0)

    def test_exit_only_direction_easing_and_real_frames(self):
        import numpy as np

        for direction, dx, dy in (("left", -0.0525, 0), ("right", 0.0525, 0),
                                   ("up", 0, -0.0525), ("down", 0, 0.0525)):
            scene = self.scene("slide", "ease-out")
            item = scene["elements"][0]
            del item["animation"]
            item["exit_animation"]["direction"] = direction
            validate_motion_scene(scene)
            state = composition.motion_state(item, 2.5)
            self.assertEqual(state["opacity"], 0.125)
            self.assertAlmostEqual(state["dx"], dx)
            self.assertAlmostEqual(state["dy"], dy)
        for effect, bounds in (("fade", (60, 139, 30, 69)),
                               ("slide", (54, 133, 30, 69)),
                               ("scale", (63, 136, 32, 68))):
            scene = validate_motion_scene(self.scene(effect))
            clip = composition.build_clip(scene, 200, 100)
            try:
                self.assertEqual(tuple(clip.get_frame(2)[50, 100]), (255, 255, 255))
                middle = clip.get_frame(2.5)
                self.assertEqual(tuple(middle[50, 100]), (128, 128, 128))
                ys, xs = np.where(middle[:, :, 0] > 64)
                self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), bounds)
                self.assertFalse(clip.get_frame(3).any())
            finally:
                clip.close()

    def test_exit_validation_and_touching_endpoints(self):
        for key, value in (("start", -1), ("start", 2.001), ("start", True),
                           ("start", float("nan")), ("duration", 0.099),
                           ("duration", float("inf")), ("effect", "spin"),
                           ("easing", "bounce"), ("direction", "up"), ("repeat", 1)):
            scene = self.scene()
            scene["elements"][0]["exit_animation"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for invalid in (None, [], "fade"):
            scene = self.scene()
            scene["elements"][0]["exit_animation"] = invalid
            with self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for missing in ("effect", "start", "duration", "easing"):
            scene = self.scene()
            del scene["elements"][0]["exit_animation"][missing]
            with self.assertRaises(ValueError):
                validate_motion_scene(scene)
        scene = self.scene()
        del scene["motion_version"]
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        scene = self.scene()
        scene["elements"][0]["exit_animation"]["start"] = 1.49
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        scene["elements"][0]["exit_animation"]["start"] = 1.5
        validate_motion_scene(scene)
        scene["duration"] = 1.5
        scene["elements"][0]["animation"].update(start=0.4, duration=0.8)
        scene["elements"][0]["exit_animation"].update(start=1.2, duration=0.3)
        validate_motion_scene(scene)
        scene["elements"][0]["exit_animation"]["start"] = 1.19999
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)


class IconTests(unittest.TestCase):
    def test_shared_library_has_twelve_original_inset_icons(self):
        library = json.loads(composition.VECTOR_LIBRARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(set(library), {
            "book", "code", "shield", "users", "cloud", "lightbulb",
            "calendar", "chart", "mail", "globe", "layers", "play",
        })
        self.assertEqual(set(composition.ICONS), set(library) | {
            "check", "arrow", "star", "info", "target", "heart",
        })
        kinds = set()
        for name, primitives in library.items():
            self.assertEqual(composition.icon_primitives(name), primitives)
            self.assertIs(composition.vector_library(), composition.vector_library())
            self.assertTrue(primitives)
            for kind, geometry, stroke in primitives:
                kinds.add(kind)
                self.assertIn(kind, ("path", "polygon", "ring", "oval"))
                self.assertGreaterEqual(stroke, 0)
                self.assertLessEqual(stroke, 0.12)
                if kind in ("path", "polygon"):
                    self.assertGreaterEqual(len(geometry), 3 if kind == "polygon" else 2)
                    self.assertTrue(all(len(point) == 2 for point in geometry))
                    coordinates = [value for point in geometry for value in point]
                else:
                    self.assertEqual(len(geometry), 4)
                    self.assertLess(geometry[0], geometry[2])
                    self.assertLess(geometry[1], geometry[3])
                    coordinates = geometry
                self.assertTrue(all(0.08 <= value <= 0.92 for value in coordinates))
                self.assertEqual(stroke == 0, kind in ("polygon", "oval"))
        self.assertEqual(kinds, {"path", "polygon", "ring", "oval"})
        with self.assertRaises(ValueError):
            composition.icon_primitives("unknown")

    def test_new_icons_render_distinct_transparent_rasters_and_saved_native_groups(self):
        from io import BytesIO
        import numpy as np
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from pptx.util import Inches

        masks = []
        for name in ("book", "code", "shield", "users", "cloud", "lightbulb",
                     "calendar", "chart", "mail", "globe", "layers", "play"):
            with self.subTest(icon=name):
                scene = validate_motion_scene(self.scene(name))
                item = scene["elements"][0]
                item["color"] = "#12ab34"
                pixels = np.asarray(composition.icon_image(item, 100, 100))
                mask = pixels[:, :, 3] > 0
                self.assertGreater(mask.sum(), 300)
                self.assertLess(mask.sum(), 7000)
                self.assertFalse(mask[0].any())
                self.assertFalse(mask[-1].any())
                self.assertTrue(np.all(pixels[mask] == (18, 171, 52, 255)))
                self.assertFalse(any(np.array_equal(mask, other) for other in masks))
                masks.append(mask)
                prs = Presentation()
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                composition.export_slide(slide, scene, Inches(10), Inches(5))
                stream = BytesIO()
                prs.save(stream)
                stream.seek(0)
                exported = Presentation(stream).slides[0]
                self.assertEqual(len(exported.shapes), 1)
                group = exported.shapes[0]
                self.assertEqual(group.shape_type, MSO_SHAPE_TYPE.GROUP)
                self.assertEqual(group.name, item["id"])
                self.assertEqual((group.left, group.top, group.width, group.height),
                                 (Inches(3), Inches(1.5), Inches(4), Inches(2)))
                self.assertGreaterEqual(len(group.shapes), 2)
                self.assertTrue(all(shape.shape_type in (
                    MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.FREEFORM,
                    MSO_SHAPE_TYPE.LINE) for shape in group.shapes))
                self.assertFalse(group._element.xpath(".//p:pic | .//a:blip | .//p:timing"))
                self.assertTrue(group._element.xpath(".//a:srgbClr[@val='12AB34']"))

    def scene(self, kind="check"):
        scene = entrance_scene()
        scene["elements"][0].pop("shape")
        scene["elements"][0].update(type="icon", icon=kind)
        return scene

    def test_curated_names_geometry_and_animation_validate_through_studio(self):
        for kind in ("check", "arrow", "star", "info", "target", "heart"):
            scene = self.scene(kind)
            original = copy.deepcopy(scene["elements"])
            normalized = validate({"timeline": [scene]})["timeline"][0]
            self.assertEqual(normalized["elements"], original)
        for kind in (None, "", "logo", "https://example.com/icon.svg", "<svg/>", [], {}):
            scene = self.scene(kind)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate({"timeline": [scene]})
        for key, value in (("svg", "<svg/>"), ("src", "https://example.com/icon.svg"),
                           ("shape", "rect"), ("text", "x"), ("w", 0), ("x", 0.9),
                           ("color", "red")):
            scene = self.scene()
            scene["elements"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate({"timeline": [scene]})
        scene = self.scene()
        del scene["elements"][0]["icon"]
        with self.assertRaises(ValueError):
            validate({"timeline": [scene]})
        del scene["elements"][0]["animation"]
        scene["elements"][0]["icon"] = "check"
        del scene["motion_version"]
        validate({"timeline": [scene]})

    def test_raster_geometry_transparency_colour_and_motion(self):
        import numpy as np

        samples = {
            "check": ((25, 85), (20, 20)),
            "arrow": ((50, 70), (50, 25)),
            "star": ((50, 50), (10, 10)),
            "info": ((60, 50), (50, 30)),
            "target": ((50, 50), (50, 40)),
            "heart": ((50, 50), (15, 50)),
        }
        masks = []
        for kind, (filled, empty) in samples.items():
            scene = self.scene(kind)
            scene["elements"][0]["color"] = "#12ab34"
            scene = validate({"timeline": [scene]})["timeline"][0]
            image, x, y = composition.element_images(scene, 250, 250)[0]
            self.assertEqual((image.size, x, y), ((100, 100), 75, 75))
            pixels = np.asarray(image)
            with self.subTest(kind=kind):
                self.assertEqual(tuple(pixels[filled]), (18, 171, 52, 255))
                self.assertEqual(pixels[empty][3], 0)
                self.assertEqual(pixels[0, 0, 3], 0)
                mask = pixels[:, :, 3] > 0
                self.assertGreater(mask.sum(), 300)
                self.assertLess(mask.sum(), 7000)
                self.assertFalse(any(np.array_equal(mask, other) for other in masks))
                masks.append(mask)
                clip = composition.build_clip(scene, 250, 250)
                try:
                    self.assertFalse(clip.get_frame(0).any())
                    resting = clip.get_frame(1.5)
                    middle = clip.get_frame(1)
                    py, px = filled
                    self.assertEqual(tuple(resting[75+py, 75+px]), (18, 171, 52))
                    self.assertEqual(tuple(middle[75+py, 75+px]), (9, 86, 26))
                finally:
                    clip.close()

    def test_saved_pptx_icons_are_grouped_native_editable_resting_geometry(self):
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from pptx.util import Inches

        prs = Presentation()
        scene = self.scene()
        scene["elements"] = []
        for index, kind in enumerate(("check", "arrow", "star", "info", "target", "heart")):
            item = self.scene(kind)["elements"][0]
            item.update(id=kind, x=0.05 + index * 0.15, y=0.2, w=0.1, h=0.3)
            scene["elements"].append(item)
        scene = validate({"timeline": [scene]})["timeline"][0]
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, scene, Inches(10), Inches(5))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "icons.pptx"
            prs.save(str(path))
            slide = Presentation(str(path)).slides[0]
            self.assertEqual(len(slide.shapes), 6)
            for item, group in zip(scene["elements"], slide.shapes):
                with self.subTest(kind=item["icon"]):
                    self.assertEqual(group.shape_type, MSO_SHAPE_TYPE.GROUP)
                    self.assertEqual(group.name, item["id"])
                    self.assertEqual(group.left, round(item["x"] * Inches(10)))
                    self.assertEqual(group.top, round(item["y"] * Inches(5)))
                    self.assertEqual(group.width, round(item["w"] * Inches(10)))
                    self.assertEqual(group.height, round(item["h"] * Inches(5)))
                    self.assertGreaterEqual(len(group.shapes), 2)
                    self.assertTrue(all(shape.shape_type in (
                        MSO_SHAPE_TYPE.AUTO_SHAPE, MSO_SHAPE_TYPE.FREEFORM,
                        MSO_SHAPE_TYPE.LINE) for shape in group.shapes))
                    self.assertFalse(group._element.xpath(".//p:pic | .//a:blip | .//p:timing"))
                    self.assertTrue(group._element.xpath(".//a:srgbClr[@val='FFFFFF']"))
            check = slide.shapes[0]
            self.assertEqual(sum(shape.shape_type == MSO_SHAPE_TYPE.LINE for shape in check.shapes), 2)
            target = slide.shapes[4]
            self.assertEqual(len(target.shapes), 4)
            self.assertTrue(target.shapes[1]._element.xpath(".//a:noFill"))

    def test_schema_curated_icon_contract(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "src/schema.json").read_text())
        element = schema["definitions"]["composition"]["properties"]["elements"]["items"]
        self.assertIn("icon", element["properties"]["type"]["enum"])
        # Schema expansion is owned by the frontend integration; retain the
        # legacy names and ensure every advertised icon is supported here.
        advertised = set(element["properties"]["icon"]["enum"])
        self.assertTrue({"check", "arrow", "star", "info", "target", "heart"} <= advertised)
        self.assertTrue(advertised <= set(composition.ICONS))
        self.assertFalse(element["additionalProperties"])
        self.assertEqual(element["allOf"][0]["then"]["required"], ["icon"])


class CanvasTests(unittest.TestCase):
    def test_validation_bounds_and_glyphs(self):
        validate(BASE)
        for key, value in [
            ("x", 0.5),
            ("w", -1),
            ("font_size", float("nan")),
            ("text", "Unsupported 🧑‍🚀"),
            ("id", "chart"),
        ]:
            spec = copy.deepcopy(BASE)
            spec["timeline"][0]["elements"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(spec)
        spec = copy.deepcopy(BASE)
        spec["timeline"][0]["elements"][2]["values"] = [1]
        with self.assertRaises(ValueError):
            validate(spec)

    def test_defaults_and_integer_resolution(self):
        spec = copy.deepcopy(BASE)
        spec["timeline"][0].pop("background")
        spec["timeline"][0]["elements"][0].pop("font_size")
        result = validate(spec)
        self.assertEqual(result["timeline"][0]["background"]["motion"], "none")
        self.assertEqual(result["timeline"][0]["elements"][0]["font_size"], 0.06)
        self.assertNotIn("background", spec["timeline"][0])
        spec["meta"] = {"resolution": {"width": 1280.0, "height": 720.0}}
        with self.assertRaises(ValueError):
            validate(spec)

    def test_background_motion_and_static_time_zero(self):
        import numpy as np

        for style in composition.BACKGROUNDS:
            config = {
                "style": style,
                "color": "#191925",
                "accent": "#6750a4",
                "motion": "drift",
            }
            first = np.asarray(composition.background_frame(config, 320, 180, 0))
            last = np.asarray(composition.background_frame(config, 320, 180, 3))
            self.assertEqual(first.shape, (180, 320, 3))
            if style in ("gradient", "grid", "orbits", "waves"):
                self.assertFalse(np.array_equal(first, last))

    def test_gradient_pulse_changes_and_still_remains_static(self):
        import numpy as np

        config = {
            "style": "gradient",
            "color": "#191925",
            "accent": "#6750a4",
            "motion": "pulse",
        }
        first = np.asarray(composition.background_frame(config, 320, 180, 0))
        last = np.asarray(composition.background_frame(config, 320, 180, 2))
        self.assertFalse(np.array_equal(first, last))
        config["motion"] = "none"
        self.assertTrue(
            np.array_equal(
                np.asarray(composition.background_frame(config, 320, 180, 0)),
                np.asarray(composition.background_frame(config, 320, 180, 2)),
            )
        )

    def test_pptx_elements_remain_editable_and_positioned(self):
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, BASE["timeline"][0], Inches(10), Inches(5.625))
        self.assertEqual(len(slide.shapes), 3)
        self.assertEqual(slide.shapes[0].text, "Café • canvas")
        self.assertAlmostEqual(slide.shapes[0].left / Inches(10), 0.1)
        self.assertTrue(slide.shapes[2].has_chart)
        self.assertEqual(list(slide.shapes[2].chart.series[0].values), [2, 4])

    def test_chart_types_and_shapes_render_and_export_natively(self):
        from pptx import Presentation
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches
        for kind, expected in [('bar',XL_CHART_TYPE.COLUMN_CLUSTERED),('horizontal',XL_CHART_TYPE.BAR_CLUSTERED),('line',XL_CHART_TYPE.LINE),('area',XL_CHART_TYPE.AREA),('pie',XL_CHART_TYPE.PIE),('doughnut',XL_CHART_TYPE.DOUGHNUT)]:
            with self.subTest(chart=kind):
                spec=copy.deepcopy(BASE)
                spec['timeline'][0]['elements'][2]['chart_type']=kind
                scene=validate(spec)['timeline'][0]
                self.assertEqual(composition.element_images(scene,320,180)[2][0].size,(192,72))
                prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
                composition.export_slide(slide,scene,Inches(10),Inches(5.625))
                self.assertEqual(slide.shapes[2].chart.chart_type,expected)
        for kind,expected in [('rounded',MSO_SHAPE.ROUNDED_RECTANGLE),('triangle',MSO_SHAPE.ISOSCELES_TRIANGLE),('arrow',MSO_SHAPE.RIGHT_ARROW)]:
            spec=copy.deepcopy(BASE);spec['timeline'][0]['elements'][1]['shape']=kind
            scene=validate(spec)['timeline'][0]
            composition.element_images(scene,320,180)
            prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
            composition.export_slide(slide,scene,Inches(10),Inches(5.625))
            self.assertEqual(slide.shapes[1].auto_shape_type,expected)
        for kind in ('pie','doughnut'):
            spec=copy.deepcopy(BASE);spec['timeline'][0]['elements'][2].update(chart_type=kind,values=[-1,2])
            with self.assertRaises(ValueError):validate(spec)

    def test_real_mp4_and_pptx_dimensions_for_all_presets(self):
        from pptx import Presentation

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            for width, height in composition.RESOLUTIONS:
                directory = Path(temp) / f"{width}x{height}"
                directory.mkdir()
                spec = copy.deepcopy(BASE)
                spec["meta"] = {
                    "resolution": {"width": width, "height": height},
                    "fps": 24,
                }
                path = directory / "spec.json"
                path.write_text(json.dumps(validate(spec)))
                subprocess.run(
                    [
                        sys.executable,
                        str(root / "src/render.py"),
                        str(path),
                        "-o",
                        str(directory / "video.mp4"),
                        "--workdir",
                        str(directory / "cache"),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=60,
                )
                import imageio_ffmpeg

                probe = subprocess.run(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-i",
                        str(directory / "video.mp4"),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertIn(f"{width}x{height}", probe.stderr)
                prs = Presentation(str(directory / "video.pptx"))
                self.assertAlmostEqual(
                    int(prs.slide_width or 0) / int(prs.slide_height or 1),
                    width / height,
                    places=5,
                )
                self.assertTrue(any(shape.has_chart for shape in prs.slides[0].shapes))


class PortableAssetTests(unittest.TestCase):
    def image_scene(self, fit="cover"):
        import base64
        from io import BytesIO
        from PIL import Image

        image = Image.new("RGB", (120, 40), "green")
        image.paste("red", (0, 0, 40, 40))
        image.paste("blue", (80, 0, 120, 40))
        stream = BytesIO()
        image.save(stream, format="PNG")
        src = "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()
        return {"type": "composition", "duration": 2, "motion_version": 1,
                "background": {"color": "#000000"}, "elements": [{
                    "id": "photo", "type": "image", "src": src, "alt": "Three stripes",
                    "fit": fit, "x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5,
                    "color": "#ffffff"}]}

    def test_image_src_persists_and_real_frames_fit_the_asset(self):
        for fit in ("cover", "contain"):
            scene = self.image_scene(fit)
            original = scene["elements"][0]["src"]
            persisted = json.loads(json.dumps(validate_motion_scene(scene)))
            self.assertEqual(persisted["elements"][0]["src"], original)
            image, x, y = composition.element_images(persisted, 240, 240)[0]
            self.assertEqual((image.size, x, y), ((120, 120), 60, 60))
            clip = composition.build_clip(persisted, 240, 240)
            try:
                frame = clip.get_frame(1)
                self.assertEqual(tuple(frame[120, 120]), (0, 128, 0))
                if fit == "contain":
                    self.assertEqual(tuple(frame[80, 120]), (0, 0, 0))
                    self.assertEqual(tuple(frame[120, 80]), (255, 0, 0))
                else:
                    self.assertEqual(tuple(frame[80, 120]), (0, 128, 0))
            finally:
                clip.close()

    def test_image_defaults_strict_fields_and_incompatible_effects(self):
        scene = self.image_scene()
        del scene["elements"][0]["fit"]
        validate_motion_scene(scene)
        self.assertEqual(scene["elements"][0]["fit"], "cover")
        for key, value in (("fit", "stretch"), ("alt", 12), ("src", "/tmp/photo.png"), ("src", []), ("src", {}),
                           ("text", "no"), ("font_family", "sans")):
            bad = self.image_scene()
            bad["elements"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_motion_scene(bad)
        for effect in ("words", "characters", "chart-draw"):
            bad = self.image_scene()
            bad["elements"][0]["animation"] = {
                "effect": effect, "start": 0, "duration": 1, "easing": "linear"}
            with self.subTest(effect=effect), self.assertRaises(ValueError):
                validate_motion_scene(bad)

    def test_saved_pptx_has_individual_fitted_picture_and_geometry(self):
        from io import BytesIO
        from PIL import Image
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from pptx.util import Inches

        for fit in ("cover", "contain"):
            scene = validate_motion_scene(self.image_scene(fit))
            prs = Presentation()
            prs.slide_width = prs.slide_height = Inches(5)
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            composition.export_slide(slide, scene, prs.slide_width, prs.slide_height)
            stream = BytesIO()
            prs.save(stream)
            stream.seek(0)
            reopened = Presentation(stream)
            picture = reopened.slides[0].shapes[0]
            self.assertEqual(len(reopened.slides[0].shapes), 1)
            self.assertEqual(picture.shape_type, MSO_SHAPE_TYPE.PICTURE)
            self.assertEqual(picture.name, "photo")
            self.assertEqual((picture.left, picture.top, picture.width, picture.height),
                             (Inches(1.25), Inches(1.25), Inches(2.5), Inches(2.5)))
            raster = Image.open(BytesIO(picture.image.blob)).convert("RGBA")
            self.assertEqual(raster.size, (240, 240))
            self.assertEqual(raster.getpixel((120, 120)), (0, 128, 0, 255))
            self.assertEqual(raster.getpixel((120, 20))[3], 0 if fit == "contain" else 255)

    def test_bundled_families_change_rasters_and_pptx_font_names(self):
        from pptx import Presentation
        from pptx.util import Inches

        rasters = []
        for family, name in (("sans", "DejaVu Sans"), ("serif", "DejaVu Serif"),
                             ("mono", "DejaVu Sans Mono")):
            for bold in (False, True):
                self.assertTrue(Path(composition.font_path(bold, family)).is_file())
            scene = copy.deepcopy(BASE["timeline"][0])
            scene["elements"] = scene["elements"][:1]
            item = scene["elements"][0]
            item["font_family"] = family
            validate_motion_scene(scene)
            rasters.append(composition.text_image(item, 320, 120).tobytes())
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            composition.export_slide(slide, scene, Inches(5), Inches(3))
            self.assertEqual(slide.shapes[0].text_frame.paragraphs[0].font.name, name)
        self.assertEqual(len(set(rasters)), 3)
        default = copy.deepcopy(BASE["timeline"][0])
        validate_motion_scene(default)
        self.assertEqual(default["elements"][0]["font_family"], "sans")
        for family in ("unknown", None, [], "DejaVu Sans"):
            bad = copy.deepcopy(BASE["timeline"][0])
            bad["elements"][0]["font_family"] = family
            with self.subTest(family=family), self.assertRaises(ValueError):
                validate_motion_scene(bad)
        # U+2103 is in Sans but not Sans Mono; coverage follows the selected family.
        composition.check_glyphs("℃", "test", family="sans")
        with self.assertRaises(ValueError):
            composition.check_glyphs("℃", "test", family="mono")


class RichElementTests(unittest.TestCase):
    @staticmethod
    def path_scene():
        scene = entrance_scene("path-draw")
        scene["elements"][0].update(type="path", points=[[0.1, 0.2], [0.5, 0.2], [0.5, 0.8]])
        del scene["elements"][0]["shape"]
        return scene

    @staticmethod
    def group_scene():
        scene = entrance_scene()
        item = scene["elements"][0]
        del item["animation"]
        item.update(x=0.1, y=0.2, w=0.2, h=0.2, group="pair")
        scene["elements"].append(dict(item, id="right", x=0.5))
        scene["groups"] = [{"id": "pair", "keyframes": [
            {"time": 0, "x": 0, "y": 0, "scale": 1, "opacity": 1},
            {"time": 2, "x": 0.1, "y": 0.2, "scale": 1.5, "opacity": 0.5},
        ]}]
        return scene

    def test_path_defaults_bounds_and_effect_ownership(self):
        scene = validate_motion_scene(self.path_scene())
        self.assertEqual(scene["elements"][0]["stroke_width"], 0.01)
        invalid_points = ([], [[0, 0]], [[0, 0]] * 33, [[0, 0], [1]],
                          [[0, 0], [True, 1]], [[0, 0], [float("nan"), 1]],
                          [[0, 0], [1.01, 1]], [[0, 0], [-0.01, 1]])
        for points in invalid_points:
            scene = self.path_scene()
            scene["elements"][0]["points"] = points
            with self.subTest(points=points), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for width in (0.001, 0.051, True, float("inf")):
            scene = self.path_scene()
            scene["elements"][0]["stroke_width"] = width
            with self.subTest(width=width), self.assertRaises(ValueError):
                validate_motion_scene(scene)
        for width in (0.002, 0.05):
            scene = self.path_scene()
            scene["elements"][0].update(points=[[0, 0], [1, 1]], stroke_width=width)
            validate_motion_scene(scene)
        scene = self.path_scene()
        scene["elements"][0]["exit_animation"] = scene["elements"][0].pop("animation")
        with self.assertRaises(ValueError):
            validate_motion_scene(scene)
        with self.assertRaises(ValueError):
            validate_motion_scene(entrance_scene("path-draw"))

    def test_path_arc_length_uses_rendered_aspect_and_partial_endpoint(self):
        item = {"points": [[0, 0], [0.5, 0], [0.5, 1]]}
        self.assertEqual(composition.path_points(item, 200, 100, 0.75),
                         [(0, 0), (100, 0), (100, 50)])
        self.assertEqual(composition.path_points(item, 100, 200, 0.5),
                         [(0, 0), (50, 0), (50, 75)])
        self.assertEqual(composition.path_points(item, 200, 100, -1), [])
        item["points"] = [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]]
        self.assertEqual(len(composition.path_points(item, 100, 100, 0.5)), 3)

    def test_one_pixel_boundary_paths_remain_visible(self):
        for points, sample in (([[1, 0], [1, 1]], (199, 50)),
                               ([[0, 1], [1, 1]], (100, 99))):
            item = {"points": points, "stroke_width": 0.002, "color": "#ffffff"}
            image = composition.path_image(item, 200, 100)
            with self.subTest(points=points):
                self.assertEqual(image.getpixel(sample), (255, 255, 255, 255))

    def test_path_clip_actual_reveal_and_out_of_order_seek(self):
        import numpy as np
        scene = validate_motion_scene(self.path_scene())
        clip = composition.build_clip(scene, 200, 100)
        try:
            middle = clip.get_frame(1).copy()
            full = clip.get_frame(2)
            # Local geometry: horizontal 32 px, vertical 24 px; half ends x=84.
            self.assertGreater(middle[38, 80, 0], 0)
            self.assertEqual(middle[55, 100, 0], 0)
            self.assertGreater(full[55, 100, 0], 0)
            self.assertTrue(np.array_equal(middle, clip.get_frame(1)))
            self.assertFalse(np.any(clip.get_frame(0)))
            self.assertEqual(composition.motion_state(scene["elements"][0], 1)["opacity"], 1)
        finally:
            clip.close()

    def test_group_pivot_additive_offsets_opacity_and_seek(self):
        import numpy as np
        scene = validate_motion_scene(self.group_scene())
        original = copy.deepcopy(scene)
        left, right = scene["elements"]
        self.assertAlmostEqual(composition.scene_motion_state(scene, left, 2)["dx"], 0)
        self.assertAlmostEqual(composition.scene_motion_state(scene, right, 2)["dx"], 0.2)
        left["keyframes"] = [
            {"time": 0, "x": 0.04, "y": 0, "scale": 0.8, "opacity": 0.4},
            {"time": 2, "x": 0.04, "y": 0, "scale": 0.8, "opacity": 0.4},
        ]
        state = composition.scene_motion_state(scene, left, 2)
        for key, expected in {"dx": 0.04, "dy": 0.2, "scale": 1.2, "opacity": 0.2}.items():
            self.assertAlmostEqual(state[key], expected)
        scene = original
        clip = composition.build_clip(scene, 200, 100)
        try:
            end = clip.get_frame(2).copy()
            ys, xs = np.where(end[:, :, 0] > 0)
            self.assertEqual((xs.min(), xs.max(), ys.min(), ys.max()), (10, 189, 35, 64))
            self.assertEqual(tuple(end[40, 20]), (128, 128, 128))
            clip.get_frame(0)
            self.assertTrue(np.array_equal(end, clip.get_frame(2)))
            self.assertEqual(scene, original)
        finally:
            clip.close()

    def test_group_validation_reuses_keyframe_rules_and_rejects_unknown_members(self):
        for change in ("unknown", "duplicate", "too_many", "time", "rotation", "version"):
            scene = self.group_scene()
            if change == "unknown":
                scene["elements"][0]["group"] = "missing"
            elif change == "duplicate":
                scene["groups"] *= 2
            elif change == "too_many":
                scene["groups"] = [dict(scene["groups"][0], id=str(i)) for i in range(9)]
            elif change == "time":
                scene["groups"][0]["keyframes"][1]["time"] = 0
            elif change == "rotation":
                scene["groups"][0]["keyframes"][0]["rotation"] = 30
            else:
                del scene["motion_version"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_motion_scene(scene)

    def test_path_pptx_is_static_native_connectors_after_roundtrip(self):
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        from pptx.util import Inches, Emu
        scene = validate_motion_scene(self.path_scene())
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, scene, Inches(10), Inches(5))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "path.pptx"
            prs.save(str(path))
            exported = Presentation(str(path)).slides[0]
            from pptx.shapes.group import GroupShape
            group = exported.shapes[0]
            self.assertIsInstance(group, GroupShape)
            assert isinstance(group, GroupShape)
            self.assertEqual(group.name, "box")
            self.assertEqual(len(group.shapes), 2)
            for connector in group.shapes:
                self.assertEqual(connector.shape_type, MSO_SHAPE_TYPE.LINE)
                self.assertEqual(connector.line.width, Emu(round(Inches(2) * 0.01)))
            first, second = group.shapes
            self.assertEqual((first.left, first.top, first.width, first.height),
                             (Inches(3.4), Inches(1.9), Inches(1.6), 0))
            self.assertEqual((second.left, second.top, second.width, second.height),
                             (Inches(5), Inches(1.9), 0, Inches(1.2)))
            self.assertFalse(exported._element.xpath(".//p:timing"))


if __name__ == "__main__":
    unittest.main()
