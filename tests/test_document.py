"""Document migration, shared semantics and legacy CLI policy boundaries."""

import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
document = importlib.import_module("src.document")
render = importlib.import_module("src.render")
studio = importlib.import_module("src.studio")
SpecError, validate_spec = document.SpecError, document.validate_spec


def canvas():
    return {
        "type": "composition",
        "motion_version": 1,
        "duration": 4,
        "elements": [
            {
                "id": "heading",
                "type": "text",
                "text": "Hello",
                "x": 0.13,
                "y": 0.21,
                "w": 0.52,
                "h": 0.2,
                "color": "#ffffff",
            }
        ],
    }


class DocumentTests(unittest.TestCase):
    def test_branding_logo_respects_all_frame_edges(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            logo = Path(directory) / "logo.png"
            Image.new("RGBA", (120, 120), "white").save(logo)
            for corner in ("top-left", "top-right", "bottom-left", "bottom-right"):
                branding = render.load_branding({"branding": {"logo": str(logo), "max_height": 1, "margin": 40, "position": corner}}, str(Path(directory) / "spec.json"), 320, 180)
                clip = branding["clip"]
                x, y = clip.pos(0)
                self.assertGreaterEqual(x, 40)
                self.assertGreaterEqual(y, 40)
                self.assertLessEqual(x + clip.w, 280)
                self.assertLessEqual(y + clip.h, 140)
                clip.close()
            with self.assertRaisesRegex(ValueError, "no usable"):
                render.load_branding({"branding": {"logo": str(logo), "margin": 100}}, str(logo), 320, 180)

    def test_fork_branding_stays_cli_only(self):
        spec = {"branding": {"logo": "logo.png", "scenes": ["title"]}, "timeline": [{"type": "title", "text": "Hello"}]}
        self.assertEqual(validate_spec(spec, studio=False)["branding"], spec["branding"])
        with self.assertRaises(SpecError):
            validate_spec(spec)
        for invalid in ({"logo": "logo.png", "opacity": True}, {"logo": "logo.png", "position": "middle"}):
            with self.assertRaises(SpecError):
                validate_spec({**spec, "branding": invalid}, studio=False)

    def test_studio_reexports_shared_contract(self):
        self.assertIs(studio.validate_spec, validate_spec)
        self.assertIs(studio.SpecError, SpecError)

    def test_unversioned_migration_preserves_geometry_and_authored_input(self):
        spec = {"timeline": [canvas()]}
        original = copy.deepcopy(spec)
        migrated = validate_spec(spec)
        self.assertEqual(migrated["version"], 1)
        self.assertEqual(spec, original)
        item = migrated["timeline"][0]["elements"][0]
        self.assertEqual(
            {key: item[key] for key in ("x", "y", "w", "h")},
            {"x": 0.13, "y": 0.21, "w": 0.52, "h": 0.2},
        )
        self.assertEqual(validate_spec(migrated), migrated)

    def test_unknown_noninteger_and_boolean_versions_are_rejected(self):
        for version in (0, 2, "1", 1.0, True, False, None):
            for studio_policy in (True, False):
                with (
                    self.subTest(version=version, studio=studio_policy),
                    self.assertRaises(SpecError),
                ):
                    validate_spec(
                        {"version": version, "timeline": [canvas()]},
                        studio=studio_policy,
                    )

    def test_cli_keeps_long_timelines_and_scene_durations(self):
        spec = {
            "timeline": [{"type": "title", "text": "Long film", "duration": 20}] * 13
        }
        result = validate_spec(spec, studio=False)
        self.assertEqual(len(result["timeline"]), 13)
        self.assertEqual(sum(scene["duration"] for scene in result["timeline"]), 260)
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_studio_envelope_enforces_each_independent_limit(self):
        for scenes in (
            [{"type": "title", "text": "Hi", "duration": 1}] * 13,
            [{"type": "title", "text": "Hi", "duration": 13}] * 5,
            [{"type": "title", "text": "Hi", "duration": 16}],
            [{"type": "title", "text": "Hi", "duration": 0.5}],
        ):
            with self.subTest(scenes=scenes), self.assertRaises(SpecError):
                validate_spec({"timeline": scenes})

    def test_cli_retains_short_composition_and_custom_frame_rate(self):
        scene = canvas()
        scene["duration"] = 0.2
        spec = {"meta": {"fps": 10}, "timeline": [scene]}
        self.assertEqual(
            validate_spec(spec, studio=False)["timeline"][0]["duration"], 0.2
        )
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_cli_does_not_materialize_legacy_audio_or_bullet_timing(self):
        spec = {"timeline": [{"type": "bullets", "items": ["A", "B"]}]}
        result = validate_spec(spec, studio=False)
        self.assertNotIn("duration", result["timeline"][0])
        self.assertEqual(render.scene_duration(result["timeline"][0], 0), 4.0)
        self.assertEqual(render.scene_duration(result["timeline"][0], 9), 10)

    def test_cli_preserves_legacy_image_paths_and_provider_settings_only(self):
        for scene in (
            {
                "type": "image",
                "src": "/not/opened/example.png",
                "anim": "kenburns",
                "caption": "Photo",
            },
            {
                "type": "title",
                "text": "Hello",
                "image": {
                    "prompt": "Concept",
                    "model": "legacy",
                    "placement": "right",
                    "opacity": 0.3,
                },
            },
        ):
            with self.subTest(scene=scene):
                result = validate_spec({"timeline": [scene]}, studio=False)
                self.assertEqual(result["timeline"][0], scene)
                with self.assertRaises(SpecError):
                    validate_spec({"timeline": [scene]})

    def test_composition_images_reject_paths_and_urls_in_both_policies(self):
        for src in ("/etc/passwd", "https://example.invalid/image.png"):
            scene = canvas()
            scene["elements"][0].update(type="image", src=src)
            scene["elements"][0].pop("text")
            for policy in (True, False):
                with self.subTest(src=src, studio=policy), self.assertRaises(SpecError):
                    validate_spec({"timeline": [scene]}, studio=policy)

    def test_composition_effect_glyph_and_keyframe_semantics_are_shared(self):
        illegal_effect = canvas()
        illegal_effect["elements"][0]["animation"] = {
            "effect": "explode",
            "start": 0,
            "duration": 1,
            "easing": "linear",
        }
        illegal_glyph = canvas()
        illegal_glyph["elements"][0]["text"] = "\U0001f9d1"
        illegal_track = canvas()
        illegal_track["elements"][0]["keyframes"] = [
            {"time": 0, "x": 0, "y": 0, "scale": 1, "opacity": 1},
            {"time": 5, "x": 0, "y": 0, "scale": 1, "opacity": 1},
        ]
        for scene in (illegal_effect, illegal_glyph, illegal_track):
            messages = []
            for policy in (True, False):
                with (
                    self.subTest(scene=scene, studio=policy),
                    self.assertRaises(SpecError) as failure,
                ):
                    validate_spec({"timeline": [scene]}, studio=policy)
                messages.append(str(failure.exception))
            self.assertEqual(messages[0], messages[1])

    def test_source_references_and_ordered_beats_survive_validation(self):
        scene = canvas()
        scene.update(
            source_ids=["source-1", "source-2"],
            beats=[
                {"label": "Reveal", "time": 0},
                {"label": "Read", "time": 4},
            ],
        )
        result = validate_spec({"timeline": [scene]})["timeline"][0]
        self.assertEqual(result["source_ids"], ["source-1", "source-2"])
        self.assertEqual(result["beats"], scene["beats"])

    def test_source_reference_bounds(self):
        for refs in ([], ["x"] * 21, [True], ["x" * 61], [""], "source-1"):
            scene = canvas()
            scene["source_ids"] = refs
            with self.subTest(refs=refs), self.assertRaises(SpecError):
                validate_spec({"timeline": [scene]})

    def test_beat_bounds_types_and_order(self):
        for beats in (
            [{"label": "Beat", "time": 0}] * 9,
            [{"label": "x" * 81, "time": 0}],
            [{"label": "Beat", "time": True}],
            [{"label": "Beat", "time": 4.1}],
            [{"label": "Later", "time": 2}, {"label": "Earlier", "time": 1}],
            [{"label": "A", "time": 1}, {"label": "B", "time": 1}],
            [{"label": "Beat", "time": 0, "script": "no"}],
        ):
            scene = canvas()
            scene["beats"] = beats
            with self.subTest(beats=beats), self.assertRaises(SpecError):
                validate_spec({"timeline": [scene]})

    def test_cli_load_expands_actual_presets_without_studio_size_limits(self):
        for preset, background in (("dark", "#0d1117"), ("light", "#ffffff")):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "spec.json"
                path.write_text(
                    json.dumps(
                        {
                            "theme": {
                                "preset": preset,
                                "font_size": 16,
                                "title_font_size": 180,
                            },
                            "timeline": [{"type": "title", "text": "Hello"}],
                        }
                    )
                )
                spec = render.load_spec(str(path))
            self.assertEqual(spec["version"], 1)
            self.assertEqual(spec["theme"]["bg"], background)
            self.assertEqual(spec["theme"]["font_size"], 16)
            self.assertEqual(spec["theme"]["title_font_size"], 180)
            self.assertEqual(spec["meta"]["fps"], 30)
            self.assertEqual(
                spec["meta"]["resolution"], {"width": 1920, "height": 1080}
            )

    def test_invalid_composition_fails_before_renderer_or_provider_io(self):
        scene = canvas()
        scene["elements"][0]["text"] = "\U0001f9d1"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "spec.json"
            path.write_text(json.dumps({"timeline": [scene]}))
            cache = Path(temp) / "cache"
            with (
                patch.object(render, "scene_narration") as narration,
                patch.object(render.composition, "build_clip") as builder,
            ):
                with self.assertRaises(SpecError):
                    render.render(
                        str(path), str(Path(temp) / "out.mp4"), workdir=str(cache)
                    )
                narration.assert_not_called()
                builder.assert_not_called()
                self.assertFalse(cache.exists())

    def test_all_checked_in_legacy_render_samples_validate(self):
        for path in (Path(__file__).resolve().parents[1] / "samples").glob(
            "*-spec.json"
        ):
            with self.subTest(sample=path.name):
                self.assertEqual(render.load_spec(str(path))["version"], 1)


if __name__ == "__main__":
    unittest.main()
