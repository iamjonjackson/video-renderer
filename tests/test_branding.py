"""Pixel-level overlay checks and shared render-path regression coverage."""
import json
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import wave
from unittest.mock import patch

import numpy as np
from PIL import Image
from moviepy import ColorClip

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import render
import branding


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Opaque, half-alpha, and fully transparent stripes.
        pixels = np.zeros((40, 120, 4), dtype=np.uint8)
        pixels[:, :, :3] = (240, 120, 60)
        pixels[:, :40, 3] = 255
        pixels[:, 40:80, 3] = 128
        self.logo = self.root / "logo.png"
        Image.fromarray(pixels).save(self.logo)
        self.base = ColorClip((render.W, render.H), color=(20, 40, 80)).with_duration(2)
        self.addCleanup(self.base.close)

    def config(self, **options):
        return {"logo": str(self.logo), **options}

    def test_four_corners_alpha_opacity_and_unchanged_pixels(self):
        original = self.base.get_frame(1)
        for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
            with self.subTest(corner=corner):
                clip = render.apply_branding(self.base, self.config(
                    position=corner, margin=0.05, opacity=0.5), "title")
                self.addCleanup(clip.close)
                frame = clip.get_frame(1)
                mx, my = round(render.W * .05), round(render.H * .05)
                x = mx if corner.endswith("left") else render.W - mx - 120
                y = my if corner.startswith("top") else render.H - my - 40
                expected = original.copy()
                expected[y:y+40, x:x+40] = (130, 80, 70)
                alpha = .5 * 128 / 255
                expected[y:y+40, x+40:x+80] = (
                    np.rint(np.array((20, 40, 80)) * (1-alpha)
                    + np.array((240, 120, 60)) * alpha)).astype(np.uint8)
                # Includes transparent pixels, the inset border, and all
                # pixels outside the logo; those must be byte-identical.
                np.testing.assert_array_equal(frame, expected)
                self.assertEqual(clip.duration, self.base.duration)

    def test_scale_and_wide_logo_fit(self):
        clip = render.apply_branding(self.base, self.config(max_height=20/render.H), "title")
        self.addCleanup(clip.close)
        self.assertEqual(clip.clips[-1].size, (60, 20))
        wide = self.root / "wide.png"
        Image.new("RGBA", (4000, 40), (255, 0, 0, 255)).save(wide)
        clip = render.apply_branding(self.base, self.config(logo=str(wide), margin=.06), "chart")
        self.addCleanup(clip.close)
        logo = clip.clips[-1]
        self.assertLessEqual(logo.w, render.W - 2*round(render.W*.06))
        self.assertGreater(logo.h, 0)

    def test_defaults_no_upscaling_and_zero_opacity(self):
        clip = render.apply_branding(self.base, self.config(), "title")
        self.addCleanup(clip.close)
        self.assertEqual(clip.clips[-1].size, (120, 40))
        self.assertEqual(clip.clips[-1].pos(0), (render.W-58-120, render.H-32-40))
        hidden = render.apply_branding(self.base, self.config(opacity=0), "title")
        self.addCleanup(hidden.close)
        np.testing.assert_array_equal(hidden.get_frame(1), self.base.get_frame(1))

    def test_absent_branding_and_scene_filters_are_exact_noops(self):
        self.assertIs(render.apply_branding(self.base, None, "title"), self.base)
        for scene_type in render.BUILDERS:
            clip = render.apply_branding(self.base, self.config(scenes=["title", "outro"]), scene_type)
            if scene_type in ("title", "outro"):
                self.assertIsNot(clip, self.base)
                clip.close()
            else:
                self.assertIs(clip, self.base)
        self.assertIs(render.apply_branding(self.base, self.config(scenes=[]), "title"), self.base)

    def test_validation_and_spec_relative_path(self):
        path = self.root / "spec.json"
        path.write_text(json.dumps({"branding": {"logo": "logo.png"}, "timeline": []}))
        self.assertEqual(render.load_spec(str(path))["branding"]["logo"], str(self.logo.resolve()))
        for invalid in (None, {}, {"logo": ""}, self.config(position="center"),
                        self.config(margin=0), self.config(margin=.5),
                        self.config(max_height=-1), self.config(max_height=True),
                        self.config(opacity=1.1), self.config(opacity=float("nan")),
                        self.config(scenes="title"), self.config(scenes=["unknown"])):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                render.validate_branding(invalid)

    def test_generated_styles_palettes_and_transparency(self):
        for style in branding.STYLES:
            results = []
            for palette in branding.PALETTES:
                config = {"name": "Video Render", "tagline": "LEARNING LAB",
                          "style": style, "palette": palette}
                options = {"generated": config, "opacity": 1}
                render.validate_branding(options)
                clip = render.apply_branding(self.base, options, "title")
                self.addCleanup(clip.close)
                frame = clip.get_frame(1)
                self.assertTrue(np.any(frame != self.base.get_frame(1)))
                pixels = branding.generated_logo(json.dumps(config, sort_keys=True), render._resolve_font(True))
                self.assertEqual(pixels.shape[2], 4)
                self.assertEqual(pixels[0, 0, 3], 0)
                self.assertTrue(np.any(pixels[:, :, 3] == 255))
                self.assertTrue(np.any((pixels[:, :, 3] > 0) & (pixels[:, :, 3] < 255)))
                results.append(pixels)
                np.testing.assert_array_equal(pixels, branding.generated_logo(
                    json.dumps(config, sort_keys=True), render._resolve_font(True)))
            for pixels in results[1:]:
                self.assertFalse(np.array_equal(results[0], pixels))

    def test_generated_custom_colours_and_validation(self):
        custom = {"name": "Video Render", "colors": {
            "primary": "#FF0000", "secondary": "#00FF00", "text": "#0000FF"}}
        pixels = branding.generated_logo(json.dumps(custom), render._resolve_font(True))
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255)):
            self.assertTrue(np.any(np.all(pixels[:, :, :3] == color, axis=2)
                                   & (pixels[:, :, 3] == 255)))
        path = self.root / "generated.json"
        path.write_text(json.dumps({"branding": {"generated": custom}, "timeline": []}))
        self.assertEqual(render.load_spec(str(path))["branding"]["generated"], custom)
        for invalid in ({}, {"name": " "}, {"name": "a\nb"}, {"name": "N"*33},
                        {"name": "N", "style": "unknown"}, {"name": "N", "palette": {}},
                        {"name": "N", "palette": "unknown"},
                        {"name": "N", "colors": {"primary": "red"}},
                        {"name": "N", "colors": {"typo": "#FFFFFF"}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                render.validate_branding({"generated": invalid})
        with self.assertRaises(ValueError):
            render.validate_branding({"logo": str(self.logo), "generated": custom})

    def test_branding_example_keeps_the_original_presentation_content(self):
        root = Path(__file__).resolve().parents[1]
        original = json.loads((root / "samples" / "sample-spec.json").read_text())
        branded = json.loads((root / "samples" / "branding-spec.json").read_text())
        # branding options must not introduce a different script or timeline
        self.assertEqual({k: v for k, v in branded.items() if k not in ("branding", "theme")},
                         {k: v for k, v in original.items() if k not in ("branding", "theme")})
        self.assertEqual(len(branded["timeline"]), 5)
        self.assertIn("branding", branded)
        self.assertEqual(branded["theme"]["color_scheme"], "purple")

    def test_colour_and_logo_changes_preserve_narration_and_reuse_cached_audio(self):
        root = Path(__file__).resolve().parents[1]
        spec = json.loads((root / "samples" / "sample-spec.json").read_text())
        original = copy.deepcopy(spec)
        path = self.root / "content.json"
        def speech(text, output, **kwargs):
            with wave.open(str(output), "wb") as audio:
                audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 800)
        with patch.object(render.tts, "synth_to_file", side_effect=speech) as synth:
            path.write_text(json.dumps(spec))
            baseline = render.load_spec(str(path))
            tracks = [render.synth_narration(scene, self.root, baseline["voice"])
                      for scene in baseline["timeline"]]
            requests = synth.call_count
            self.assertEqual(requests, 4)
            for scheme in branding.PALETTES:
                for corner in ("top-left", "bottom-right"):
                    spec["theme"] = {"color_scheme": scheme}
                    spec["branding"] = self.config(position=corner)
                    path.write_text(json.dumps(spec))
                    branded = render.load_spec(str(path))
                    self.assertEqual(branded["timeline"], original["timeline"])
                    self.assertEqual(branded["voice"], original["voice"])
                    self.assertEqual(branded["meta"], original["meta"])
                    for scene, original_scene, expected in zip(branded["timeline"], baseline["timeline"], tracks):
                        track = render.synth_narration(scene, self.root, branded["voice"])
                        self.assertEqual(track, expected)
                        self.assertEqual(render.scene_duration(scene, track[1]),
                                         render.scene_duration(original_scene, expected[1]))
                    self.assertEqual(synth.call_count, requests)

    def test_render_integration_short_and_streamed_after_animation(self):
        # Capture frames at the encoder boundary, exercising the real scene
        # loop and both export branches without lossy MP4 pixel comparisons.
        for count in (3, 13):
            with self.subTest(count=count):
                types = (["title", "bullets", "outro"] * 5)[:count]
                timeline = [{"type": t, "text": "Branding", "items": ["Example"],
                             "duration": 2, "anim": "zoom-in"} for t in types]
                spec = self.root / "integration.json"
                frames = []
                def capture(clip, *args, **kwargs):
                    for i in range(count if count <= 12 else 1):
                        frames.append(clip.get_frame(i*2+1 if count <= 12 else 1).copy())
                with patch.object(render, "_export_pptx"), \
                     patch.object(render.subprocess, "run"), \
                     patch("moviepy.video.VideoClip.VideoClip.write_videofile", capture):
                    spec.write_text(json.dumps({"timeline": timeline}))
                    render.render(str(spec), str(self.root / "base.mp4"), str(self.root))
                    baseline = frames[:]
                    frames.clear()
                    spec.write_text(json.dumps({"timeline": timeline, "branding": self.config(
                        scenes=["title", "outro"], opacity=1)}))
                    render.render(str(spec), str(self.root / "branded.mp4"), str(self.root))
                for t, before, after in zip(types, baseline, frames):
                    if t == "bullets":
                        np.testing.assert_array_equal(before, after)
                    else:
                        changed = np.any(before != after, axis=2)
                        self.assertTrue(changed.any())
                        expected_region = np.zeros_like(changed)
                        expected_region[render.H-32-40:render.H-32,
                                        render.W-58-120:render.W-58] = True
                        self.assertFalse(changed[~expected_region].any())


if __name__ == "__main__":
    unittest.main()
