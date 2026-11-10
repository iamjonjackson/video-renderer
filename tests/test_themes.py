"""Contrast, inheritance and rendering checks for whole-video colour schemes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image
from moviepy import ColorClip, CompositeVideoClip

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import render
import branding
import pptx_export
from themes.presets import COLOR_SCHEMES, resolve_theme, dark, light
from images import luminance, contrast_ratio


def contrast(a, b):
    return contrast_ratio(luminance(a), luminance(b))


class ThemeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_all_nine_schemes_have_accessible_solid_colour_pairs(self):
        self.assertEqual(list(COLOR_SCHEMES), [
            "red", "orange", "yellow", "green", "blue", "purple", "pink", "white", "grey"])
        for name in COLOR_SCHEMES:
            t = resolve_theme({"color_scheme": name})
            with self.subTest(scheme=name):
                for background in (t["bg"], t["surface"]):
                    for foreground in (t["fg"], t["accent"], t["secondary"]):
                        self.assertGreaterEqual(contrast(foreground, background), 4.5)
                    for fill in t["chart_colors"]:
                        self.assertGreaterEqual(contrast(fill, background), 3)
                for fill in t["chart_colors"]:
                    self.assertGreaterEqual(contrast(t["chart_text"], fill), 4.5)

    def test_resolution_validation_overrides_and_legacy_defaults(self):
        self.assertEqual(resolve_theme({}), dark)
        self.assertEqual(resolve_theme({"preset": "light"}), light)
        self.assertEqual(resolve_theme({"color_scheme": "white"})["bg"], "#FFFFFF")
        self.assertEqual(resolve_theme({"color_scheme": "red", "accent": "#FFFFFF"})["accent"], "#FFFFFF")
        for bad in ("aurora", "rainbow", [], None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                resolve_theme({"color_scheme": bad})
        theme = resolve_theme({"color_scheme": "red"})
        theme["chart_colors"][0] = "#000000"
        self.assertNotEqual(COLOR_SCHEMES["red"]["chart_colors"][0], "#000000")
        path = self.root / "spec.json"
        path.write_text(json.dumps({"theme": {"color_scheme": "pink"}, "timeline": []}))
        self.assertEqual(render.load_spec(str(path))["theme"]["surface"], COLOR_SCHEMES["pink"]["surface"])

    def test_generated_logo_inherits_all_theme_tokens_and_allows_overrides(self):
        base = ColorClip((render.W, render.H), color=(0, 0, 0)).with_duration(1)
        for name in COLOR_SCHEMES:
            t = resolve_theme({"color_scheme": name})
            cfg = {"name": "Video Render", "tagline": "LAB"}
            inherited = render.apply_branding(base, {"generated": cfg}, "title", t)
            explicit = render.apply_branding(base, {"generated": {**cfg, "palette": name}}, "title")
            np.testing.assert_array_equal(inherited.get_frame(0), explicit.get_frame(0))
            inherited.close()
            explicit.close()
        t = resolve_theme({"color_scheme": "white"})
        custom = {"generated": {"name": "Video Render", "colors": {"primary": "#AABBCC"}}}
        actual = render.apply_branding(base, custom, "title", t)
        expected = render.apply_branding(base, {"generated": {
            "name": "Video Render", "colors": {"primary": "#AABBCC", "secondary": t["secondary"], "text": t["fg"]}}}, "title")
        np.testing.assert_array_equal(actual.get_frame(0), expected.get_frame(0))
        actual.close()
        expected.close()
        base.close()

    def test_scenes_panels_captions_and_all_chart_types_use_scheme(self):
        src = self.root / "image.png"
        Image.new("RGB", (1920, 1080), "#ABCDEF").save(src)
        for name in COLOR_SCHEMES:
            t = resolve_theme({"color_scheme": name})
            with self.subTest(scheme=name):
                for builder in (render.build_title, render.build_outro):
                    clip = builder({"text": "Example"}, t)
                    np.testing.assert_array_equal(clip.get_frame(0)[0, 0], render.rgb(t["bg"]))
                    clip.close()
                clip = render.build_bullets({"items": ["One", "Two"]}, t)
                np.testing.assert_array_equal(clip.get_frame(0)[300, 280], render.rgb(t["surface"]))
                clip.close()
                clip = render.build_image({"src": str(src), "caption": "Caption"}, t, self.root)
                np.testing.assert_array_equal(clip.get_frame(0)[1070, 0], render.rgb(t["surface"]))
                clip.close()
                for chart_type in ("bar", "line", "pie"):
                    clip = render.build_chart({"chart_type": chart_type, "labels": ["A", "B", "C"],
                                               "values": [2, 3, 5]}, t, self.root)
                    np.testing.assert_array_equal(clip.get_frame(0)[0, 0], render.rgb(t["bg"]))
                    self.assertEqual(clip.size, (render.W, render.H))
                    clip.close()

    def test_pptx_uses_same_background_panel_and_text_tokens(self):
        from pptx import Presentation
        theme = resolve_theme({"color_scheme": "white"})
        dest = self.root / "theme.pptx"
        spec = {"theme": theme, "timeline": [
            {"type": "title", "text": "Title", "subtitle": "Subtitle"},
            {"type": "bullets", "heading": "Heading", "items": ["Body"]}]}
        pptx_export.build_pptx(spec, [{}, {}], str(dest))
        prs = Presentation(str(dest))
        for slide in prs.slides:
            colors = {node.get("val") for node in slide._element.xpath(".//a:srgbClr")}
            self.assertIn(theme["bg"][1:], colors)
            self.assertIn(theme["fg"][1:], colors)
            self.assertIn(theme["accent"][1:], colors)
        colors = {node.get("val") for node in prs.slides[1]._element.xpath(".//a:srgbClr")}
        self.assertIn(theme["surface"][1:], colors)

    def test_image_background_text_panel_and_spotlight_border_are_themed(self):
        src = self.root / "bright.png"
        Image.new("RGB", (1920, 1080), "white").save(src)
        theme = resolve_theme({"color_scheme": "purple"})
        scene = {"image": {"opacity": 1}}
        bg = ColorClip((render.W, render.H), color=render.rgb(theme["bg"]))
        clips = render.composite_bg_image([bg], scene, theme, str(src))
        clip = CompositeVideoClip(clips, size=(render.W, render.H))
        frame = clip.get_frame(0)
        np.testing.assert_array_equal(frame[540, 960], render.rgb(theme["surface"]))
        np.testing.assert_array_equal(frame[0, 0], (255, 255, 255))
        clip.close()
        panels, _ = render.build_spotlight_panel({"image": {"placement": "right"}}, theme, str(src))
        np.testing.assert_array_equal(panels[0].get_frame(0)[0, 0], render.rgb(theme["accent"]))
        for panel in panels:
            panel.close()


if __name__ == "__main__":
    unittest.main()
