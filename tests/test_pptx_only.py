"""check deck-only exports, cache reuse and the unchanged video path"""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

from PIL import Image
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render
import pptx_export


def write_audio(path):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 8000)


def no_video(stack):
    # any attempt to build or encode video should fail this test
    for name in ("TextClip", "ColorClip", "ImageClip", "CompositeVideoClip",
                 "VideoFileClip", "concatenate_videoclips", "apply_anim", "_ffmpeg_exe"):
        stack.enter_context(patch.object(render, name, side_effect=AssertionError(name)))
    stack.enter_context(patch.object(render.subprocess, "run", side_effect=AssertionError("video subprocess")))


class PptxOnlyTests(unittest.TestCase):
    def test_complete_deck_and_warm_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "local.png"
            Image.new("RGB", (64, 64), "navy").save(image)
            scenes = [
                {"type": "title", "text": "Title", "narration": "Opening",
                 "image": {"prompt": "background", "placement": "background"}},
                {"type": "bullets", "items": ["First", "Second"],
                 "narration_per_bullet": ["First", "Second"],
                 "image": {"prompt": "panel", "placement": "right"}},
                {"type": "chart", "chart_type": "bar", "labels": ["A", "B"], "values": [1, 2]},
                {"type": "image", "src": str(image), "caption": "Local image"},
                {"type": "outro", "text": "End"},
            ]
            spec = root / "spec.json"
            spec.write_text(json.dumps({"theme": {"accent": "#abcdef"}, "timeline": scenes}))
            output = root / "deck.pptx"
            cache = root / "cache"

            def synth(text, path, **kwargs):
                write_audio(path)

            def generate(prompt, path, **kwargs):
                Image.new("RGB", (64, 64), "blue").save(path)

            with contextlib.ExitStack() as stack:
                no_video(stack)
                tts = stack.enter_context(patch.object(render.tts, "synth_to_file", side_effect=synth))
                images = stack.enter_context(patch.object(render.imggen, "generate_image", side_effect=generate))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                render.render(str(spec), str(output), str(cache), render_video=False)
                self.assertEqual(tts.call_count, 3)
                self.assertEqual(images.call_count, 2)

                # a second run must use cached audio, images and chart pngs
                tts.side_effect = AssertionError("uncached narration")
                images.side_effect = AssertionError("uncached image")
                stack.enter_context(patch.object(render.plt, "subplots", side_effect=AssertionError("uncached chart")))
                render.render(str(spec), str(output), str(cache), render_video=False)

            prs = Presentation(output)
            self.assertEqual(len(prs.slides), 5)
            for index in (0, 1):
                media = [rel.target_part.blob for rel in prs.slides[index].part.rels.values()
                         if rel.target_part.content_type == "audio/wav"]
                self.assertTrue(media, f"missing audio on slide {index}")
                self.assertTrue(all(blob.startswith(b"RIFF") for blob in media))
            for index in (0, 1, 2, 3):
                self.assertTrue(any(shape.shape_type == 13 for shape in prs.slides[index].shapes))
            self.assertIn("ABCDEF", prs.slides[4]._element.xml.upper())
            self.assertFalse(list(root.rglob("*.mp4")))
            self.assertFalse((cache / "segments").exists())
            self.assertEqual(render.plt.get_fignums(), [])

    def test_dostoyevsky_31_scenes_without_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = ROOT / "samples" / "dostoyevsky-spec.json"
            loaded = render.load_spec(str(spec))
            cache = root / "cache"
            cache.mkdir()
            # stand-in cached assets exercise the full spec without paid api calls
            for scene in loaded["timeline"]:
                text = scene.get("narration")
                if text:
                    digest = hashlib.sha1(text.encode()).hexdigest()[:10]
                    write_audio(cache / f"narr_{digest}_0.wav")
                if scene.get("image"):
                    digest = hashlib.sha1(json.dumps(scene["image"], sort_keys=True).encode()).hexdigest()[:12]
                    Image.new("RGB", (64, 64), "navy").save(cache / f"sceneimg_{digest}.png")
            output = root / "novel.pptx"
            log = io.StringIO()
            with contextlib.ExitStack() as stack:
                no_video(stack)
                stack.enter_context(patch.object(render.tts, "synth_to_file", side_effect=AssertionError("tts api")))
                stack.enter_context(patch.object(render.imggen, "generate_image", side_effect=AssertionError("image api")))
                stack.enter_context(contextlib.redirect_stdout(log))
                render.render(str(spec), str(output), str(cache), render_video=False)
            prs = Presentation(output)
            self.assertEqual(len(prs.slides), 31)
            self.assertEqual(log.getvalue().count("[scene "), 31)
            self.assertFalse((cache / "segments").exists())
            self.assertFalse(list(root.rglob("*.mp4")))
            for slide in prs.slides:
                self.assertTrue(any(rel.target_part.content_type == "audio/wav"
                                    for rel in slide.part.rels.values()))

    def test_deck_only_export_errors_propagate(self):
        with patch.object(pptx_export, "build_pptx", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                render._export_pptx({}, [], "deck.pptx", required=True)
            with contextlib.redirect_stdout(io.StringIO()) as log:
                render._export_pptx({}, [], "video.mp4")
            self.assertIn("[warn] pptx export failed", log.getvalue())

    def test_cli_normalizes_output_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = root / "spec.json"
            spec.write_text(json.dumps({"timeline": [{"type": "outro", "text": "End"}]}))
            output = root / "deck.mp4"
            result = subprocess.run([sys.executable, str(ROOT / "src" / "render.py"),
                                     str(spec), "-o", str(output), "--pptx-only"],
                                    check=True, capture_output=True, text=True)
            self.assertTrue(output.with_suffix(".pptx").exists())
            self.assertFalse(output.exists())
            self.assertIn("[scene 0]", result.stdout)

    def test_full_render_keeps_video_and_slide_artifacts(self):
        for count in (2, 13):
            with self.subTest(scenes=count), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cache = root / "cache"
                cache.mkdir()
                chart = {"type": "chart", "chart_type": "bar", "labels": ["A", "B"],
                         "values": [1, 2], "narration": "Opening", "padding": 0.5, "anim": "none"}
                digest = hashlib.sha1(b"Opening").hexdigest()[:10]
                audio = cache / f"narr_{digest}_0.wav"
                write_audio(audio)
                scenes = [chart] + [{"type": "outro", "text": "End", "duration": 0.5,
                                     "anim": "none"} for _ in range(count - 1)]
                spec = root / "spec.json"
                spec.write_text(json.dumps({"meta": {"fps": 2}, "timeline": scenes}))
                output = root / "video.mp4"
                with patch.object(render, "W", 320), patch.object(render, "H", 180), \
                        patch.object(render, "_export_pptx", wraps=render._export_pptx) as export, \
                        contextlib.redirect_stdout(io.StringIO()):
                    render.render(str(spec), str(output), str(cache))
                self.assertGreater(output.stat().st_size, 0)
                self.assertEqual(len(Presentation(output.with_suffix(".pptx")).slides), count)
                artifacts = export.call_args.args[1]
                self.assertEqual(artifacts[0], {"narration_path": str(audio),
                                                "chart_png": str(render.chart_path(chart, cache))})
                self.assertEqual(artifacts[1:], [{} for _ in range(count - 1)])
                self.assertEqual((cache / "segments").exists(), count > 12)
                theme = render.load_spec(str(spec))["theme"]
                cached = render.render_chart_png(chart, theme, cache, use_cache=True)
                self.assertEqual(render.chart_path(chart, cache).read_bytes(), cached.read_bytes())

    def test_cached_chart_updates_with_theme(self):
        scene = {"type": "chart", "chart_type": "bar", "labels": ["A"], "values": [1]}
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            theme = dict(render.presets.dark)
            first = render.render_chart_png(scene, theme, cache, use_cache=True)
            theme["accent"] = "#ff0000"
            second = render.render_chart_png(scene, theme, cache, use_cache=True)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
