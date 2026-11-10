"""check decoded narration offsets and visible bullets in actual video frames"""
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image
from moviepy import ColorClip, VideoFileClip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render


class BulletSyncTests(unittest.TestCase):
    def setUp(self):
        """use unequal clip lengths so a fixed stagger cannot accidentally pass"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = {"type": "bullets", "items": ["First point", "Second point", "Third point"],
                      "narration_per_bullet": ["First speech", "Second speech", "Third speech"],
                      "stagger": 0.1, "anim": "none"}
        self.theme = {**render.presets.dark, "font_size": 48}
        self.durations = [0.8, 1.4, 1.0]
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(render, "W", 640))
        self.stack.enter_context(patch.object(render, "H", 360))
        self.stack.enter_context(patch.object(render.tts, "synth_to_file", side_effect=AssertionError("tts api")))

    def cache_audio(self, fmt="wav"):
        """prepare decodable cached audio locally without a narration provider"""
        paths = []
        for i, (text, duration) in enumerate(zip(self.scene["narration_per_bullet"], self.durations)):
            pcm = b"".join(struct.pack("<h", int(10000 * math.sin(2 * math.pi * (330 + i * 110) * j / 8000)))
                           for j in range(round(duration * 8000)))
            digest = hashlib.sha1(text.encode()).hexdigest()[:10]
            output = self.root / f"narr_{digest}_{i}.{fmt}"
            if fmt == "wav":
                with wave.open(str(output), "wb") as audio:
                    audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                    audio.writeframes(pcm)
            else:
                subprocess.run([render._ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "s16le",
                                "-ar", "8000", "-ac", "1", "-i", "pipe:0", str(output)],
                               input=pcm, check=True, capture_output=True)
            paths.append(output)
        return paths

    def visible_bullets(self, frame, x_range=(0, 448)):
        """count text pixels in the three row bands, away from the heading"""
        visible, left_edges = [], []
        bg = np.array(render.rgb(self.theme["bg"]))
        for i in range(3):
            y = int(360 * (0.30 + i * (0.85 - 0.30) / 3))
            band = frame[y:y + 50, x_range[0]:x_range[1]]
            mask = np.max(np.abs(band.astype(int) - bg), axis=2) > 45
            visible.append(np.count_nonzero(mask) > 12)
            xs = np.where(mask)[1]
            if len(xs):
                left_edges.append(int(xs.min()) + x_range[0])
        return visible, left_edges

    def test_decoded_offsets_and_warm_cache(self):
        for fmt in ("wav", "mp3"):
            with self.subTest(fmt=fmt):
                paths = self.cache_audio(fmt)
                measured = [render.tts.audio_duration(str(path)) for path in paths]
                starts = []
                path, duration = render.synth_narration(self.scene, self.root, {"format": fmt}, starts)
                self.assertEqual(starts, [0.0, measured[0], measured[0] + measured[1]])
                self.assertGreaterEqual(duration, sum(measured))
                self.assertGreaterEqual(render.scene_duration(self.scene, duration), sum(measured) + 1)
                cached_starts = []
                with patch.object(render, "concatenate_audioclips", side_effect=AssertionError("rebuilt cached audio")):
                    self.assertEqual(render.synth_narration(self.scene, self.root, {"format": fmt}, cached_starts),
                                     (path, duration))
                self.assertEqual(cached_starts, starts)

    def test_bullets_reveal_with_a_short_fade_and_stay_left_aligned(self):
        self.cache_audio()
        starts = []
        _, audio_duration = render.synth_narration(self.scene, self.root, {}, starts)
        duration = render.scene_duration(self.scene, audio_duration)
        clip = render.build_bullets(self.scene, self.theme, bullet_starts=starts, duration=duration).with_duration(duration)
        try:
            for i, start in enumerate(starts):
                if i:
                    visible, _ = self.visible_bullets(clip.get_frame(start - 0.2))
                    self.assertEqual(visible, [j < i for j in range(3)])
                visible, _ = self.visible_bullets(clip.get_frame(start + 0.2))
                self.assertEqual(visible, [j <= i for j in range(3)])
            _, left_edges = self.visible_bullets(clip.get_frame(starts[-1] + 0.2))
            self.assertEqual(len(left_edges), 3)
            self.assertLessEqual(max(left_edges) - min(left_edges), 1)
            self.assertAlmostEqual(left_edges[0], 640 * 0.15, delta=5)
            bullet = clip.clips[-1]
            self.assertEqual(float(bullet.mask.get_frame(0)[0, 0]), 0)
            self.assertGreater(float(bullet.mask.get_frame(0.075).max()), 0)
            self.assertLess(float(bullet.mask.get_frame(0.075).max()), 1)
        finally:
            clip.close()

    def test_plain_narration_and_silent_scenes_use_stagger(self):
        for narration in ({}, {"narration": "One clip for the whole scene"}):
            scene = {key: value for key, value in self.scene.items() if key != "narration_per_bullet"}
            scene.update(narration)
            scene["stagger"] = 0.4
            clip = render.build_bullets(scene, self.theme, duration=4).with_duration(4)
            try:
                for t, count in ((0.2, 1), (0.6, 2), (1.0, 3), (3.9, 3)):
                    self.assertEqual(self.visible_bullets(clip.get_frame(t))[0], [i < count for i in range(3)])
            finally:
                clip.close()

    def test_single_bullet_and_explicit_duration(self):
        self.cache_audio()
        scene = {**self.scene, "items": self.scene["items"][:1],
                 "narration_per_bullet": self.scene["narration_per_bullet"][:1], "duration": 6}
        starts = []
        _, duration = render.synth_narration(scene, self.root, {}, starts)
        self.assertEqual(starts, [0])
        self.assertEqual(render.scene_duration(scene, duration), 6)

    def test_audio_sync_takes_priority_over_stagger_in_the_standard_sample(self):
        spec = json.loads((ROOT / "samples" / "sample-spec.json").read_text())
        for scene in spec["timeline"]:
            if scene["type"] == "bullets":
                self.assertEqual(len(scene["narration_per_bullet"]), len(scene["items"]))
        self.cache_audio()
        starts = []
        _, audio_duration = render.synth_narration(self.scene, self.root, {}, starts)
        duration = render.scene_duration(self.scene, audio_duration)
        for stagger in (0, 0.4, 10):
            scene = {**self.scene, "stagger": stagger}
            with render.build_bullets(scene, self.theme, bullet_starts=starts, duration=duration).with_duration(duration) as clip:
                self.assertEqual([bullet.start for bullet in clip.clips[1:]], starts)
                self.assertEqual(self.visible_bullets(clip.get_frame(0.6))[0], [True, False, False])

    def test_default_custom_and_zero_stagger(self):
        scene = {"type": "bullets", "items": self.scene["items"], "anim": "none"}
        for stagger in (None, 0, 0.7):
            with self.subTest(stagger=stagger):
                config = scene if stagger is None else {**scene, "stagger": stagger}
                interval = 0.4 if stagger is None else stagger
                with render.build_bullets(config, self.theme, duration=4).with_duration(4) as clip:
                    self.assertEqual([b.start for b in clip.clips[1:]], [i * interval for i in range(3)])
                    self.assertEqual(self.visible_bullets(clip.get_frame(0.2))[0],
                                     [True, True, True] if stagger == 0 else [True, False, False])
        for invalid in (-0.1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "stagger"):
                render.build_bullets({**scene, "stagger": invalid}, self.theme)

    def test_stagger_preserves_alignment_in_full_width_and_both_spotlight_layouts(self):
        image = self.root / "panel.png"
        Image.new("RGB", (640, 360), "orange").save(image)
        for side in (None, "left", "right"):
            with self.subTest(side=side):
                scene = {"type": "bullets", "heading": "Heading", "items": self.scene["items"], "stagger": 0.4}
                if side:
                    scene["image"] = {"src": str(image), "placement": side}
                with patch.object(render, "scene_image_clip", return_value=str(image) if side else None):
                    clip = render.build_bullets(scene, self.theme, self.root, duration=3).with_duration(3)
                try:
                    heading, *bullets = clip.clips[-4:]
                    self.assertTrue(all(b.pos(0)[0] == heading.pos(0)[0] for b in bullets))
                    roi = (300, 640) if side == "left" else (0, 330) if side == "right" else (0, 448)
                    for t, count in ((0.2, 1), (0.6, 2), (1.0, 3), (2.9, 3)):
                        visible, edges = self.visible_bullets(clip.get_frame(t), roi)
                        self.assertEqual(visible, [i < count for i in range(3)])
                        self.assertLessEqual(max(edges) - min(edges), 1)
                finally:
                    clip.close()

    def test_encoded_stagger_keeps_existing_scene_duration_rules(self):
        self.cache_audio()
        text = self.scene["narration_per_bullet"][0]
        for narration, explicit, expected in ((None, None, 4.4), (None, 2.5, 2.5),
                                               (text, None, 1.8), (text, 4.5, 4.5)):
            with self.subTest(narration=narration, explicit=explicit):
                scene = {"type": "bullets", "items": self.scene["items"], "stagger": 0.4, "anim": "none"}
                if narration:
                    scene["narration"] = narration
                if explicit:
                    scene["duration"] = explicit
                spec = self.root / "stagger.json"
                spec.write_text(json.dumps({"meta": {"fps": 20}, "theme": self.theme, "timeline": [scene]}))
                output = self.root / "stagger.mp4"
                with patch.object(render, "_export_pptx"), contextlib.redirect_stdout(io.StringIO()):
                    render.render(str(spec), str(output), str(self.root))
                with VideoFileClip(str(output)) as video:
                    self.assertAlmostEqual(video.duration, expected, delta=0.06)
                    self.assertEqual(video.audio is not None, bool(narration))
                    for t, count in ((0.2, 1), (0.6, 2), (1.0, 3), (expected - 0.1, 3)):
                        self.assertEqual(self.visible_bullets(video.get_frame(t))[0], [i < count for i in range(3)])

    def test_short_explicit_scene_does_not_extend_or_create_negative_clip_durations(self):
        scene = {"type": "bullets", "items": self.scene["items"], "duration": 0.3, "stagger": 0.4}
        duration = render.scene_duration(scene, 0)
        self.assertEqual(duration, 0.3)
        with render.build_bullets(scene, self.theme, duration=duration).with_duration(duration) as clip:
            self.assertEqual(self.visible_bullets(clip.get_frame(0.2))[0], [True, False, False])
            self.assertTrue(all(b.duration > 0 for b in clip.clips[1:]))

    def test_mismatched_entries_fail_before_api_calls(self):
        with self.assertRaisesRegex(ValueError, "one narration entry per bullet"):
            render.synth_narration({**self.scene, "narration_per_bullet": ["Only one"]}, self.root, {})

    def test_missing_key_falls_back_to_stagger(self):
        spec = self.root / "missing.json"
        scene = {**self.scene, "stagger": 0.4}
        spec.write_text(json.dumps({"meta": {"fps": 10}, "theme": self.theme, "timeline": [scene]}))
        with patch.object(render.tts, "synth_to_file", side_effect=RuntimeError("MISTRAL_API_KEY not set")), \
                patch.object(render, "_export_pptx"), contextlib.redirect_stdout(io.StringIO()) as log:
            render.render(str(spec), str(self.root / "silent.mp4"), str(self.root))
        self.assertIn("without narration", log.getvalue())
        with VideoFileClip(str(self.root / "silent.mp4")) as video:
            self.assertIsNone(video.audio)
            self.assertEqual(self.visible_bullets(video.get_frame(0.2))[0], [True, False, False])
            self.assertEqual(self.visible_bullets(video.get_frame(1.0))[0], [True, True, True])

    def test_encoded_frames_audio_and_tail_in_normal_and_streamed_videos(self):
        for count, fmt, lead, trailing in ((2, "wav", 0.2, False), (2, "mp3", 0.2, False),
                                           (13, "wav", 0.2, False), (13, "wav", 0.23, True)):
            with self.subTest(scenes=count, fmt=fmt, lead=lead, trailing=trailing):
                paths = self.cache_audio(fmt)
                measured = [render.tts.audio_duration(str(path)) for path in paths]
                starts = [0, measured[0], measured[0] + measured[1]]
                lead_duration = lead * (count - 1)
                scenes = [{"type": "outro", "text": "", "duration": lead, "anim": "none"}
                          for _ in range(count - 1)] + [self.scene]
                if trailing:
                    scenes.append({"type": "outro", "text": "", "duration": 0.2, "anim": "none"})
                spec = self.root / "spec.json"
                spec.write_text(json.dumps({"meta": {"fps": 20}, "voice": {"format": fmt},
                                            "theme": self.theme, "timeline": scenes}))
                output = self.root / f"sync-{count}-{fmt}-{lead}-{trailing}.mp4"
                # a blank opening scene makes the first reveal measurable too
                with patch.dict(render.BUILDERS, outro=lambda *a: ColorClip((640, 360), render.rgb(self.theme["bg"]))), \
                        patch.object(render, "_export_pptx"), contextlib.redirect_stdout(io.StringIO()) as log:
                    render.render(str(spec), str(output), str(self.root))
                self.assertIn("bullet narration starts:", log.getvalue())
                with VideoFileClip(str(output)) as video:
                    for i, start in enumerate(starts):
                        before = video.get_frame(lead_duration + start - 0.2)
                        after = video.get_frame(lead_duration + start + 0.2)
                        self.assertEqual(self.visible_bullets(before)[0], [j < i for j in range(3)])
                        self.assertEqual(self.visible_bullets(after)[0], [j <= i for j in range(3)])
                    video_duration = video.duration
                # decode the physical audio stream so container padding cannot hide truncation
                decoded = subprocess.run([render._ffmpeg_exe(), "-loglevel", "error", "-i", str(output),
                                          "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"],
                                         check=True, capture_output=True).stdout
                samples = np.frombuffer(decoded, dtype="<i2")
                audible = np.where(np.abs(samples.astype(int)) > 500)[0]
                last_sample = audible[-1] / 8000
                self.assertGreaterEqual(last_sample, lead_duration + sum(measured) - 0.15)
                self.assertGreaterEqual(video_duration - last_sample, 0.9)


if __name__ == "__main__":
    unittest.main()
