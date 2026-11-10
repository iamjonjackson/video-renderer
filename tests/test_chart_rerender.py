"""check importing chart edits and publishing a new narrated set of outputs"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.oxml.ns import qn
from moviepy import VideoFileClip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import pptx_import
import pptx_export
import render
import rerender_from_pptx


def write_audio(path, duration=0.5):
    """make a valid audio file without contacting a speech provider"""
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * round(8000 * duration))


class ChartRerenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = {"type": "chart", "chart_type": "bar", "heading": "Revenue",
                      "labels": ["Jul", "Aug"], "values": [10, 20], "y_label": "Dollars",
                      "narration": "Old revenue was ten and twenty.", "duration": 1.5}
        self.spec = {"meta": {"fps": 10}, "theme": dict(render.presets.dark), "timeline": [self.scene]}
        self.spec_path = self.root / "original.json"
        self.spec_path.write_text(json.dumps(self.spec))
        self.source = self.root / "edited.pptx"
        pptx_export.build_pptx(self.spec, [{}], str(self.source))
        self.edit_chart()
        self.output = self.root / "new.mp4"

    def edit_chart(self):
        """simulate a saved powerpoint edit to both data and formatting"""
        prs = Presentation(self.source)
        chart = next(shape.chart for shape in prs.slides[0].shapes if shape.has_chart)
        data = CategoryChartData()
        data.categories = ["Jul", "Sep"]
        data.add_series("Dollars", [12.5, 333])
        chart.replace_data(data)
        chart.chart_title.text_frame.text = "Updated revenue"
        chart.series[0].format.fill.fore_color.rgb = RGBColor.from_string("FF8800")
        prs.save(self.source)

    def test_imported_values_titles_and_readout_match_the_saved_chart(self):
        original = self.spec_path.read_bytes()
        updated, indices, changed = pptx_import.import_chart_edits(self.spec_path, self.source)
        self.assertEqual(indices, [0])
        self.assertEqual(changed, [0])
        scene = updated["timeline"][0]
        self.assertEqual(scene["labels"], ["Jul", "Sep"])
        self.assertEqual(scene["values"], [12.5, 333])
        self.assertEqual(scene["heading"], "Updated revenue")
        self.assertEqual(scene["narration"], "Updated revenue. Dollars. Jul: 12.5. Sep: 333.")
        self.assertEqual(self.spec_path.read_bytes(), original)

    def test_unchanged_chart_retains_the_original_narration(self):
        pptx_export.build_pptx(self.spec, [{}], str(self.source))
        updated, _, changed = pptx_import.import_chart_edits(self.spec_path, self.source)
        self.assertEqual(changed, [])
        self.assertEqual(updated, self.spec)

    def test_wording_edits_update_text_and_narration_without_changing_other_slides(self):
        scenes = [
            {"type": "title", "text": "Original title", "subtitle": "Original subtitle", "narration": "Old introduction"},
            {"type": "bullets", "heading": "Original heading", "items": ["First", "Second"],
             "narration_per_bullet": ["Old first", "Old second"]},
            {"type": "outro", "text": "End", "duration": 2},
        ]
        self.spec["timeline"] = scenes
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{}, {}, {}], str(self.source))
        prs = Presentation(self.source)
        boxes = [s for s in prs.slides[0].shapes if s.has_text_frame and s.text.strip()]
        boxes[0].text = "Revised title\nRevised subtitle"
        boxes = [s for s in prs.slides[1].shapes if s.has_text_frame and s.text.strip()]
        boxes[0].text = "Revised heading"
        boxes[1].text = "\u2022 Updated first\n\u2022 Second\n\u2022 Added third"
        prs.save(self.source)
        updated, images, changed = pptx_import.import_chart_edits(self.spec_path, self.source)
        self.assertEqual(images, [0, 1])
        self.assertEqual(changed, [0, 1])
        title, bullets, outro = updated["timeline"]
        self.assertEqual(title["text"], "Revised title")
        self.assertEqual(title["subtitle"], "Revised subtitle")
        self.assertEqual(title["narration"], "Revised title. Revised subtitle.")
        self.assertEqual(bullets["items"], ["Updated first", "Second", "Added third"])
        self.assertEqual(bullets["narration"], "Revised heading. Updated first. Second. Added third.")
        self.assertNotIn("narration_per_bullet", bullets)
        self.assertEqual(outro, scenes[2])

    def test_unchanged_wording_preserves_custom_narration_and_silence(self):
        self.spec["timeline"] = [
            {"type": "title", "text": "Title", "subtitle": "Subtitle", "narration": "A custom introduction"},
            {"type": "bullets", "heading": "Heading", "items": ["First", "Second"],
             "narration_per_bullet": ["Explain first", "Explain second"]},
            {"type": "outro", "text": "End"},
        ]
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{}, {}, {}], str(self.source))
        updated, images, changed = pptx_import.import_chart_edits(self.spec_path, self.source)
        self.assertEqual(updated, self.spec)
        self.assertEqual(images, [])
        self.assertEqual(changed, [])

    def test_unmatched_text_boxes_fail_instead_of_guessing(self):
        self.spec["timeline"] = [{"type": "title", "text": "Title"}]
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{}], str(self.source))
        prs = Presentation(self.source)
        prs.slides[0].shapes.add_textbox(0, 0, 100, 100).text = "Unmapped text"
        prs.save(self.source)
        with self.assertRaisesRegex(ValueError, "text boxes"):
            pptx_import.import_chart_edits(self.spec_path, self.source)

    def test_changed_wording_renders_and_reuses_new_narration_from_cache(self):
        self.spec["timeline"] = [{"type": "title", "text": "Title", "narration": "Old introduction"}]
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{}], str(self.source))
        prs = Presentation(self.source)
        next(s for s in prs.slides[0].shapes if s.has_text_frame and s.text.strip()).text = "Updated introduction"
        prs.save(self.source)
        folder = self.root / "pngs"
        folder.mkdir()
        Image.new("RGB", (640, 360), "orange").save(folder / "Slide1.png")
        def synth(text, path, **kwargs):
            self.assertEqual(text, "Updated introduction.")
            write_audio(path)
        with patch.object(render, "W", 640), patch.object(render, "H", 360), \
                patch.object(render.tts, "synth_to_file", side_effect=synth) as speech, contextlib.redirect_stdout(io.StringIO()):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, slides_dir=folder)
            self.assertEqual(speech.call_count, 1)
            rerender_from_pptx.rerender(self.spec_path, self.source, self.root / "again.mp4", slides_dir=folder)
            self.assertEqual(speech.call_count, 1)
        deck = Presentation(self.output.with_suffix(".pptx"))
        self.assertTrue(any(s.has_text_frame and s.text == "Updated introduction" for s in deck.slides[0].shapes))
        self.assertEqual(len(pptx_export.narration_shapes(deck.slides[0])), 1)
        with VideoFileClip(str(self.output)) as video:
            self.assertIsNotNone(video.audio)
            self.assertGreater(video.get_frame(0.8)[100, 100, 0], 245)

    def test_image_caption_edits_are_imported_and_narrated(self):
        image = self.root / "image.png"
        Image.new("RGB", (640, 360), "blue").save(image)
        self.spec["timeline"] = [{"type": "image", "src": str(image), "caption": "Old caption"}]
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{"image_png": str(image)}], str(self.source))
        prs = Presentation(self.source)
        next(s for s in prs.slides[0].shapes if s.has_text_frame and s.text.strip()).text = "New caption"
        prs.save(self.source)
        updated, images, changed = pptx_import.import_chart_edits(self.spec_path, self.source)
        self.assertEqual(images, [0])
        self.assertEqual(changed, [0])
        self.assertEqual(updated["timeline"][0]["caption"], "New caption")
        self.assertEqual(updated["timeline"][0]["narration"], "New caption.")

    def test_line_and_pie_data_can_be_imported(self):
        for kind in ("line", "pie"):
            spec = {**self.spec, "timeline": [{**self.scene, "chart_type": kind}]}
            self.spec_path.write_text(json.dumps(spec))
            pptx_export.build_pptx(spec, [{}], str(self.source))
            self.edit_chart()
            updated, _, _ = pptx_import.import_chart_edits(self.spec_path, self.source)
            self.assertEqual(updated["timeline"][0]["chart_type"], kind)
            self.assertEqual(updated["timeline"][0]["values"], [12.5, 333])

    def test_missing_or_unsupported_chart_and_reordered_slides_are_rejected(self):
        prs = Presentation(self.source)
        chart_shape = next(shape for shape in prs.slides[0].shapes if shape.has_chart)
        chart_shape.name = "renderer-chart-9"
        prs.save(self.source)
        with self.assertRaisesRegex(ValueError, "reordered"):
            pptx_import.import_chart_edits(self.spec_path, self.source)
        chart_shape.name = "renderer-chart-0"
        chart_shape.chart.element.xpath(".//c:barDir")[0].set("val", "bar")
        prs.save(self.source)
        with self.assertRaisesRegex(ValueError, "single-series"):
            pptx_import.import_chart_edits(self.spec_path, self.source)
        self.spec["timeline"].append({"type": "outro", "text": "Extra"})
        self.spec_path.write_text(json.dumps(self.spec))
        with self.assertRaisesRegex(ValueError, "slide count"):
            pptx_import.import_chart_edits(self.spec_path, self.source)

    def test_slide_images_preserve_supplied_pixels_without_becoming_spec_data(self):
        images = self.root / "powerpoint-pngs"
        images.mkdir()
        Image.new("RGB", (640, 360), "orange").save(images / "Slide1.PNG")
        paths = pptx_import.chart_slide_images(self.source, [0], self.root / "frames", 640, 360, images)
        with Image.open(paths[0]) as frame:
            self.assertEqual(frame.getpixel((0, 0)), (255, 165, 0))
        updated, _, _ = pptx_import.import_chart_edits(self.spec_path, self.source)
        video = pptx_import.video_spec(updated, paths)
        self.assertEqual(video["timeline"][0]["type"], "image")
        self.assertEqual(updated["timeline"][0]["type"], "chart")
        self.assertNotIn("src", updated["timeline"][0])
        self.assertEqual(video["timeline"][0]["narration"], updated["timeline"][0]["narration"])

    def test_missing_or_wrong_size_exported_images_fail_clearly(self):
        folder = self.root / "pngs"
        folder.mkdir()
        with self.assertRaisesRegex(ValueError, "Missing Slide1"):
            pptx_import.chart_slide_images(self.source, [0], self.root / "frames", slides_dir=folder)
        Image.new("RGB", (100, 100), "red").save(folder / "Slide1.png")
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            pptx_import.chart_slide_images(self.source, [0], self.root / "frames", slides_dir=folder)

    def test_refresh_keeps_chart_parts_and_replaces_audio_without_orphan_playback(self):
        old = self.root / "old.wav"
        new = self.root / "new.wav"
        write_audio(old, 0.3)
        write_audio(new, 0.7)
        prs = Presentation(self.source)
        slide = prs.slides[0]
        pptx_export._add_narration(slide, old)
        # powerpoint can save narration as an audio node rather than python-pptx's video node
        slide._element.xpath(".//p:video")[0].tag = qn("p:audio")
        # an extra shape makes the replacement audio use a different shape id
        slide.shapes.add_textbox(0, 0, 100, 100)
        prs.save(self.source)
        result = self.root / "refreshed.pptx"
        pptx_export.refresh_narration(self.source, [{"narration_path": str(new)}], result)
        with ZipFile(self.source) as before, ZipFile(result) as after:
            self.assertEqual(before.read("ppt/charts/chart1.xml"), after.read("ppt/charts/chart1.xml"))
            for name in after.namelist():
                if name.startswith("ppt/media/"):
                    self.assertNotEqual(after.read(name), old.read_bytes())
        slide = Presentation(result).slides[0]
        audios = pptx_export.narration_shapes(slide)
        self.assertEqual(len(audios), 1)
        targets = slide._element.xpath(".//p:video//p:spTgt")
        self.assertEqual([target.get("spid") for target in targets], [str(audios[0].shape_id)])

    def test_preview_writes_only_a_new_spec_and_never_calls_tts(self):
        with patch.object(render, "render", side_effect=AssertionError("render called")), contextlib.redirect_stdout(io.StringIO()):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, spec_only=True)
        self.assertTrue(self.output.with_suffix(".json").exists())
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".pptx").exists())
        with self.assertRaises(FileExistsError):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, spec_only=True)

    def test_refresh_replaces_multiple_loaded_audio_parts(self):
        audio_paths = [self.root / f"track-{i}.wav" for i in range(4)]
        for i, path in enumerate(audio_paths):
            write_audio(path, 0.2 + i * 0.1)
        spec = {**self.spec, "timeline": [self.scene, {"type": "outro", "text": "End"}]}
        pptx_export.build_pptx(spec, [{"narration_path": str(path)} for path in audio_paths[:2]], str(self.source))
        result = self.root / "refreshed.pptx"
        pptx_export.refresh_narration(self.source, [{"narration_path": str(path)} for path in audio_paths[2:]], result)
        slides = Presentation(result).slides
        for slide, expected in zip(slides, audio_paths[2:]):
            self.assertEqual(len(pptx_export.narration_shapes(slide)), 1)
            self.assertTrue(any(rel.target_part.blob == expected.read_bytes() for rel in slide.part.rels.values()))

    def test_end_to_end_reuses_the_renderer_and_keeps_native_chart_styling(self):
        folder = self.root / "pngs"
        folder.mkdir()
        Image.new("RGB", (640, 360), "orange").save(folder / "Slide1.png")
        original_spec = self.spec_path.read_bytes()
        original_deck = self.source.read_bytes()
        requested = []
        def synth(text, path, **kwargs):
            requested.append(text)
            write_audio(path)
        with patch.object(render, "W", 640), patch.object(render, "H", 360), \
                patch.object(render.tts, "synth_to_file", side_effect=synth), contextlib.redirect_stdout(io.StringIO()):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, slides_dir=folder)
        updated = json.loads(self.output.with_suffix(".json").read_text())
        self.assertEqual(requested, [updated["timeline"][0]["narration"]])
        self.assertIn("333", requested[0])
        self.assertEqual(self.spec_path.read_bytes(), original_spec)
        self.assertEqual(self.source.read_bytes(), original_deck)
        chart = next(shape.chart for shape in Presentation(self.output.with_suffix(".pptx")).slides[0].shapes if shape.has_chart)
        self.assertEqual(str(chart.series[0].format.fill.fore_color.rgb), "FF8800")
        self.assertEqual(list(chart.series[0].values), [12.5, 333])
        with VideoFileClip(str(self.output)) as video:
            self.assertIsNotNone(video.audio)
            pixel = video.get_frame(0.8)[100, 100]
            self.assertLess(abs(int(pixel[0]) - 255), 6)
            self.assertLess(abs(int(pixel[1]) - 165), 6)
        with self.assertRaises(FileExistsError):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, slides_dir=folder)

    def test_failed_narration_does_not_publish_outputs(self):
        folder = self.root / "pngs"
        folder.mkdir()
        Image.new("RGB", (640, 360), "orange").save(folder / "Slide1.png")
        with patch.object(render.tts, "synth_to_file", side_effect=RuntimeError("MISTRAL_API_KEY not set")), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "needs narration"):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, slides_dir=folder)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".pptx").exists())
        self.assertFalse(self.output.with_suffix(".json").exists())

    def test_streamed_rerender_keeps_all_slides_and_the_silent_outro(self):
        self.spec["timeline"] += [{"type": "outro", "text": "End", "duration": 0.2, "anim": "none"}
                                  for _ in range(12)]
        self.spec["timeline"][0]["anim"] = "none"
        self.spec_path.write_text(json.dumps(self.spec))
        pptx_export.build_pptx(self.spec, [{} for _ in range(13)], str(self.source))
        self.edit_chart()
        folder = self.root / "pngs"
        folder.mkdir()
        Image.new("RGB", (320, 180), "orange").save(folder / "Slide1.png")
        def synth(text, path, **kwargs):
            write_audio(path)
        with patch.object(render, "W", 320), patch.object(render, "H", 180), \
                patch.object(render.tts, "synth_to_file", side_effect=synth), contextlib.redirect_stdout(io.StringIO()):
            rerender_from_pptx.rerender(self.spec_path, self.source, self.output, slides_dir=folder)
        self.assertEqual(len(Presentation(self.output.with_suffix(".pptx")).slides), 13)
        with VideoFileClip(str(self.output)) as video:
            self.assertAlmostEqual(video.duration, 3.9, delta=0.11)


if __name__ == "__main__":
    unittest.main()
