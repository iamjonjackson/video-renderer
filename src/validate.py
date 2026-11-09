"""Validate video specs against src/schema.json with friendly, scene-numbered errors.

Scenes are numbered from 0, matching the renderer's "[scene N]" log lines.

    python3 src/validate.py samples/sample-spec.json   # or: render.py --validate
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.json"

_TYPE_NAMES = {
    "string": "a string", "number": "a number", "integer": "a whole number",
    "array": "a list", "object": "an object", "boolean": "true/false", "null": "null",
}


class SpecError(Exception):
    """Raised when a spec can't be loaded or doesn't match the schema."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _suggest(word, options) -> str:
    if not isinstance(word, str):
        return ""
    match = difflib.get_close_matches(word, [str(o) for o in options], n=1, cutoff=0.6)
    return f" — did you mean '{match[0]}'?" if match else ""


def _fmt_path(path) -> str:
    out = ""
    for part in path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _json_type(value) -> str:
    if isinstance(value, bool):
        return "true/false"
    if value is None:
        return "null"
    for py, name in ((str, "string"), (int, "integer"), (float, "number"),
                     (list, "array"), (dict, "object")):
        if isinstance(value, py):
            return _TYPE_NAMES[name]
    return type(value).__name__


def _describe(err) -> str:
    """Turn one jsonschema ValidationError into a readable sentence."""
    where = _fmt_path(err.absolute_path)
    field = f"'{where}'" if where else "spec"
    v = err.validator
    if v == "required":
        missing = err.message.split("'")[1]
        return f"missing required field '{where + '.' if where else ''}{missing}'"
    if v == "additionalProperties":
        allowed = list(err.schema.get("properties", {}))
        extras = [k for k in err.instance if k not in allowed]
        loc = f" in '{where}'" if where else ""
        return "; ".join(f"unknown field '{k}'{loc}{_suggest(k, allowed)}" for k in extras)
    if v in ("enum", "const"):
        options = err.validator_value if v == "enum" else [err.validator_value]
        choices = ", ".join(repr(o) for o in options)
        return (f"{field} must be one of {choices} (got {err.instance!r})"
                f"{_suggest(err.instance, options)}")
    if v == "type":
        expected = err.validator_value
        expected = expected if isinstance(expected, list) else [expected]
        want = " or ".join(_TYPE_NAMES.get(t, t) for t in expected)
        return f"{field} should be {want}, got {_json_type(err.instance)} {json.dumps(err.instance)}"
    if v == "minItems":
        n = err.validator_value
        return f"{field} needs at least {n} item{'s' if n != 1 else ''}"
    if v in ("minimum", "maximum"):
        word = "at least" if v == "minimum" else "at most"
        return f"{field} must be {word} {err.validator_value} (got {err.instance})"
    return f"{field}: {err.message}"


def validate_spec(spec, schema: dict | None = None) -> list[str]:
    """Return a list of human-readable problems; empty list means valid."""
    from jsonschema import Draft7Validator

    schema = schema or _load_schema()
    if not isinstance(spec, dict):
        return [f"spec must be a JSON object, got {_json_type(spec)}"]

    errors: list[str] = []

    # Top level (meta/theme/voice/timeline shape). Scenes are checked one by
    # one below: the schema's oneOf over scene types produces unreadable errors.
    top = dict(schema)
    top["properties"] = dict(schema["properties"])
    top["properties"]["timeline"] = {k: v for k, v in schema["properties"]["timeline"].items()
                                     if k != "items"}
    for err in sorted(Draft7Validator(top).iter_errors(spec), key=lambda e: list(e.absolute_path)):
        if list(err.absolute_path) == ["timeline"] and err.validator == "minItems":
            errors.append("timeline is empty — add at least one scene")
        else:
            errors.append(_describe(err))

    timeline = spec.get("timeline")
    if not isinstance(timeline, list):
        return errors

    defs = schema["definitions"]
    scene_types = [ref["$ref"].rsplit("/", 1)[-1] for ref in defs["scene"]["oneOf"]]
    for i, scene in enumerate(timeline):
        prefix = f"scene {i}"
        if not isinstance(scene, dict):
            errors.append(f"{prefix}: should be an object, got {_json_type(scene)}")
            continue
        stype = scene.get("type")
        if stype is None:
            errors.append(f"{prefix}: missing required field 'type' "
                          f"(one of {', '.join(scene_types)})")
            continue
        if stype not in scene_types:
            errors.append(f"{prefix}: unknown type {stype!r}{_suggest(stype, scene_types)} "
                          f"(valid types: {', '.join(scene_types)})")
            continue
        prefix += f" ({stype})"
        scene_schema = {"$ref": f"#/definitions/{stype}", "definitions": defs}
        validator = Draft7Validator(scene_schema)
        for err in sorted(validator.iter_errors(scene), key=lambda e: list(e.absolute_path)):
            errors.append(f"{prefix}: {_describe(err)}")
    return errors


def load_and_validate(path: str | Path) -> dict:
    """Read a spec file and validate it. Raises SpecError listing every problem."""
    path = Path(path)
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise SpecError([f"spec file not found: {path}"]) from None
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        raise SpecError([f"{path}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"]) from None
    try:
        errors = validate_spec(spec)
    except ImportError:
        print("[warn] jsonschema not installed; skipping spec validation "
              "(pip install jsonschema)", file=sys.stderr)
        return spec
    if errors:
        raise SpecError(errors)
    return spec


def report(path: str | Path, err: SpecError) -> str:
    n = len(err.errors)
    lines = [f"[spec] {path}: {n} problem{'s' if n != 1 else ''} found"]
    lines += [f"  - {e}" for e in err.errors]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python3 src/validate.py SPEC.json", file=sys.stderr)
        return 2
    try:
        spec = load_and_validate(argv[0])
    except SpecError as e:
        print(report(argv[0], e), file=sys.stderr)
        return 1
    print(f"[spec] {argv[0]}: OK ({len(spec.get('timeline', []))} scenes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
