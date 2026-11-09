"""Spec validation tests: run with `python3 -m pytest tests`."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "src"))

from validate import SpecError, load_and_validate, validate_spec  # noqa: E402


def errors_for(name: str) -> list[str]:
    with pytest.raises(SpecError) as exc:
        load_and_validate(FIXTURES / name)
    return exc.value.errors


@pytest.mark.parametrize("spec", sorted((ROOT / "samples").glob("*.json")), ids=lambda p: p.name)
def test_sample_specs_are_valid(spec):
    assert validate_spec(json.loads(spec.read_text())) == []


def test_wrong_scene_type_suggests_closest():
    assert errors_for("wrong_scene_type.json") == [
        "scene 1: unknown type 'bullet' — did you mean 'bullets'? "
        "(valid types: title, bullets, image, chart, outro)"
    ]


def test_missing_required_field():
    assert errors_for("missing_required_field.json") == [
        "scene 0 (bullets): missing required field 'items'"
    ]


def test_bad_enum_values_at_top_level_and_in_scene():
    assert errors_for("bad_enum_value.json") == [
        "'theme.preset' must be one of 'dark', 'light' (got 'drak') — did you mean 'dark'?",
        "scene 0 (title): 'anim' must be one of 'fade', 'slide-up', 'zoom-in' (got 'zoom')"
        " — did you mean 'zoom-in'?",
    ]


def test_wrong_value_types():
    assert errors_for("wrong_value_type.json") == [
        "'meta.fps' should be a whole number, got a string \"30\"",
        "scene 0 (bullets): 'stagger' should be a number, got a string \"0.5\"",
        "scene 1 (chart): 'values[0]' should be a number, got a string \"410\"",
    ]


def test_empty_timeline():
    assert errors_for("empty_timeline.json") == ["timeline is empty — add at least one scene"]


def test_unknown_field_suggests_closest():
    assert errors_for("unknown_field.json") == [
        "scene 0 (bullets): unknown field 'haeding' — did you mean 'heading'?"
    ]


def test_scene_image_block():
    assert errors_for("bad_scene_image.json") == [
        "scene 0 (bullets): missing required field 'image.prompt'",
        "scene 0 (bullets): 'image.opacity' must be at most 1 (got 2)",
        "scene 0 (bullets): 'image.placement' must be one of 'background', 'left', 'right'"
        " (got 'middle')",
    ]


def test_all_errors_reported_in_one_run():
    errors = errors_for("multiple_errors.json")
    assert len(errors) == 3
    assert errors[0].startswith("scene 0: unknown type 'titel' — did you mean 'title'?")
    assert errors[1] == "scene 1 (bullets): missing required field 'items'"
    assert errors[2].startswith("scene 2 (chart): 'chart_type' must be one of")


def test_invalid_json_and_missing_file():
    [err] = errors_for("invalid_json.json")
    assert "invalid JSON at line 5" in err
    [err] = errors_for("does_not_exist.json")
    assert err.startswith("spec file not found")


def test_non_object_scene_and_missing_type():
    assert validate_spec({"timeline": ["oops", {"text": "hi"}]}) == [
        "scene 0: should be an object, got a string",
        "scene 1: missing required field 'type' (one of title, bullets, image, chart, outro)",
    ]


@pytest.mark.parametrize("script", ["validate.py", "render.py"])
def test_cli_exit_codes_and_no_traceback(script, tmp_path):
    if script == "render.py":
        pytest.importorskip("moviepy")
    cmd = [sys.executable, str(ROOT / "src" / script)]
    flags = ["--validate"] if script == "render.py" else []

    bad = subprocess.run(cmd + [str(FIXTURES / "multiple_errors.json")] + flags,
                         capture_output=True, text=True)
    assert bad.returncode == 1
    assert "3 problems found" in bad.stderr
    assert "Traceback" not in bad.stderr

    ok = subprocess.run(cmd + [str(ROOT / "samples" / "sample-spec.json")] + flags,
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "OK (5 scenes)" in ok.stdout


def test_render_without_validate_flag_stops_before_rendering(tmp_path):
    pytest.importorskip("moviepy")
    out = tmp_path / "out.mp4"
    res = subprocess.run([sys.executable, str(ROOT / "src" / "render.py"),
                          str(FIXTURES / "wrong_scene_type.json"), "-o", str(out)],
                         capture_output=True, text=True)
    assert res.returncode == 1
    assert "did you mean 'bullets'?" in res.stderr
    assert "Traceback" not in res.stderr
    assert not out.exists()
