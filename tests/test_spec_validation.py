"""Spec validation against src/schema.json (issue: validate specs before render).

Broken-spec fixtures live in tests/fixtures/invalid_specs/. Each test asserts
the exact, scene-numbered messages a spec author would see. No rendering, TTS
or network: the CLI tests stop at validation, before any clip is built.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "themes"))
import presets  # noqa: E402
import spec_validation as sv  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "invalid_specs"
SAMPLES = sorted((ROOT / "samples").glob("*.json"))


def errors_for(name: str) -> list[str]:
    path = str(FIXTURES / name)
    try:
        sv.validate_spec(sv.read_spec(path), path)
    except sv.SpecValidationError as e:
        return e.errors
    raise AssertionError(f"{name} unexpectedly passed validation")


class BrokenSpecFixtures(unittest.TestCase):
    def test_wrong_scene_type_suggests_closest(self):
        self.assertEqual(
            errors_for("wrong_scene_type.json"),
            ["scene 2: unknown type 'bullet', did you mean 'bullets'?"],
        )

    def test_missing_required_field(self):
        self.assertEqual(
            errors_for("missing_required_field.json"),
            [
                "scene 1: missing required field 'text'",
                "scene 2: missing required field 'values'",
            ],
        )

    def test_bad_enum_value(self):
        self.assertEqual(
            errors_for("bad_enum_value.json"),
            [
                "'theme.preset' is \"drak\", which is not allowed, did you mean "
                "'dark'? (use one of: dark, light)",
                "scene 1: 'anim' is \"zoom\", which is not allowed, did you mean "
                "'zoom-in'? (use one of: fade, slide-up, zoom-in)",
            ],
        )

    def test_wrong_value_type(self):
        self.assertEqual(
            errors_for("wrong_value_type.json"),
            [
                "'meta.fps' should be a whole number, got text (\"30\")",
                "scene 1: 'duration' should be a number, got text (\"5\")",
                "scene 1: 'items' should be a list, got text (\"Just one string\")",
            ],
        )

    def test_empty_timeline(self):
        self.assertEqual(
            errors_for("empty_timeline.json"),
            ["timeline is empty: add at least one scene"],
        )

    def test_multiple_errors_all_reported_in_scene_order(self):
        self.assertEqual(
            errors_for("multiple_errors.json"),
            [
                "scene 2: unknown type 'bullet', did you mean 'bullets'?",
                "scene 3: unknown field 'hedaing', did you mean 'heading'?",
                "scene 3: 'values[1]' should be a number, got text (\"455\")",
                "scene 4: missing required field 'text'",
            ],
        )

    def test_invalid_json_reports_line_and_column(self):
        (msg,) = errors_for("invalid_json.json")
        self.assertTrue(msg.startswith("invalid JSON at line 4, column 3:"), msg)
        self.assertIn("trailing comma", msg)


class OtherShapes(unittest.TestCase):
    def check(self, spec):
        return sv.collect_errors(spec)

    def test_missing_timeline(self):
        self.assertEqual(self.check({"meta": {}}), ["missing required field 'timeline'"])

    def test_top_level_not_an_object(self):
        self.assertEqual(
            self.check([1, 2]), ["the spec must be a JSON object ({...}), got a list"]
        )

    def test_scene_not_an_object_and_missing_type(self):
        self.assertEqual(
            self.check({"timeline": ["title", {"text": "x"}]}),
            [
                'scene 1: must be an object like {"type": "title", ...}, got text',
                "scene 2: missing required field 'type' (one of: title, bullets, "
                "image, chart, outro, composition)",
            ],
        )

    def test_unrelated_type_lists_choices(self):
        (msg,) = self.check({"timeline": [{"type": "video"}]})
        self.assertEqual(
            msg,
            "scene 1: unknown type 'video' (choose one of: title, bullets, image, "
            "chart, outro, composition)",
        )

    def test_nested_paths_are_named(self):
        spec = {
            "timeline": [
                {"type": "bullets", "items": ["a"],
                 "image": {"prompt": "p", "placement": "top"}},
                {"type": "composition", "elements": [
                    {"id": "a", "type": "text", "x": 0, "y": 0, "w": 0.5,
                     "h": 0.5, "color": "red"}]},
            ]
        }
        self.assertEqual(
            self.check(spec),
            [
                "scene 1: 'image.placement' is \"top\", which is not allowed "
                "(use one of: background, left, right)",
                "scene 2: 'elements[0].color' should be a six-digit hex colour "
                "like #58a6ff, got \"red\"",
            ],
        )

    def test_missing_file(self):
        with self.assertRaises(sv.SpecValidationError) as ctx:
            sv.read_spec(str(FIXTURES / "does-not-exist.json"))
        self.assertEqual(ctx.exception.errors, ["file not found"])


class ValidSpecsUnchanged(unittest.TestCase):
    def test_every_sample_is_valid(self):
        self.assertTrue(SAMPLES)
        for path in SAMPLES:
            with self.subTest(sample=path.name):
                self.assertEqual(sv.collect_errors(json.loads(path.read_text())), [])

    def test_load_spec_output_matches_pre_validation_behaviour(self):
        # load_spec lives in render.py (MoviePy import); compare its result
        # with the original read + theme-merge logic, inlined here.
        import render

        for path in SAMPLES:
            with self.subTest(sample=path.name):
                spec = json.loads(path.read_text())
                theme = dict(presets.__dict__[spec.get("theme", {}).get("preset", "dark")])
                theme.update({k: v for k, v in spec.get("theme", {}).items() if k != "preset"})
                spec["theme"] = theme
                spec.setdefault("meta", {})
                spec["meta"].setdefault("resolution", {"width": 1920, "height": 1080})
                spec["meta"].setdefault("fps", 30)
                self.assertEqual(render.load_spec(str(path)), spec)

    def test_studio_shaped_scenes_with_anim_are_valid(self):
        # The renderer applies "anim" to every scene and Studio allows it on
        # bullets/chart/outro, so the schema must not reject it there.
        spec = {"timeline": [
            {"type": "bullets", "items": ["a"], "anim": "slide-up"},
            {"type": "chart", "labels": ["a"], "values": [1], "anim": "zoom-in"},
            {"type": "outro", "text": "Bye", "anim": "fade"},
            {"type": "title", "text": "Hi", "transition": "fade"},
        ]}
        self.assertEqual(sv.collect_errors(spec), [])


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "src" / "render.py"), *args],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )

    def test_validate_ok_exits_zero(self):
        r = self.run_cli("samples/sample-spec.json", "--validate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "samples/sample-spec.json: OK (5 scenes)")

    def test_validate_broken_exits_one_with_all_errors(self):
        r = self.run_cli(str(FIXTURES / "multiple_errors.json"), "--validate")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("found 4 problems:", r.stderr)
        for scene in (2, 3, 4):
            self.assertIn(f"  - scene {scene}: ", r.stderr)

    def test_render_of_broken_spec_stops_before_rendering(self):
        out = ROOT / "output" / "_validation_test.mp4"
        r = self.run_cli(str(FIXTURES / "multiple_errors.json"), "-o", str(out))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("found 4 problems:", r.stderr)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
