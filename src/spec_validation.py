"""Validate a video spec against src/schema.json before rendering.

Errors are collected (not fail-fast), phrased for people writing their first
spec, and numbered by scene from 1, e.g.

    scene 2: unknown type 'bullet', did you mean 'bullets'?
    scene 3: missing required field 'text'

Scenes are checked against the definition named by their own "type" rather
than the schema's oneOf, which would collapse every mistake in a scene into
a single "is not valid under any of the given schemas" message.

Kept free of MoviePy/Matplotlib imports so `--validate` stays fast.
"""

from __future__ import annotations

import difflib
import json
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).with_name("schema.json")

_TYPE_WORDS = {
    "string": "text (a string)",
    "number": "a number",
    "integer": "a whole number",
    "boolean": "true or false",
    "array": "a list",
    "object": "an object",
    "null": "null",
}


class SpecValidationError(ValueError):
    """A spec could not be read or does not match the schema."""

    def __init__(self, source: str, errors: list[str]):
        self.source = source
        self.errors = list(errors)
        super().__init__(format_errors(source, self.errors))


def format_errors(source: str, errors: list[str]) -> str:
    noun = "problem" if len(errors) == 1 else "problems"
    lines = [f"{source}: found {len(errors)} {noun}:"]
    lines += [f"  - {e}" for e in errors]
    return "\n".join(lines)


@cache
def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def scene_types() -> list[str]:
    """Scene types, in schema order (title, bullets, image, ...)."""
    refs = load_schema()["definitions"]["scene"]["oneOf"]
    return [r["$ref"].rsplit("/", 1)[-1] for r in refs]


def read_spec(path: str) -> dict:
    """Read and parse a spec file, turning I/O and JSON errors into
    SpecValidationError with a line/column instead of a traceback."""
    try:
        raw = Path(path).read_text()
    except FileNotFoundError:
        raise SpecValidationError(path, ["file not found"]) from None
    except OSError as e:
        raise SpecValidationError(path, [f"could not read file ({e.strerror})"]) from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        hint = ""
        if e.msg.startswith("Expecting property name") or e.msg.startswith(
            "Expecting value"
        ):
            hint = " (a trailing comma before } or ] is a common cause)"
        raise SpecValidationError(
            path, [f"invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}{hint}"]
        ) from None


def validate_spec(spec: Any, source: str = "spec") -> None:
    """Raise SpecValidationError listing every problem, or return None."""
    errors = collect_errors(spec)
    if errors:
        raise SpecValidationError(source, errors)


def collect_errors(spec: Any) -> list[str]:
    if not isinstance(spec, dict):
        return [f"the spec must be a JSON object ({{...}}), got {_json_type(spec)}"]
    schema = load_schema()
    errors = _top_level_errors(spec, schema)
    timeline = spec.get("timeline")
    if isinstance(timeline, list):
        if not timeline:
            errors.append("timeline is empty: add at least one scene")
        for i, scene in enumerate(timeline):
            errors += [f"scene {i + 1}: {m}" for m in _scene_errors(scene, schema)]
    return errors


def _top_level_errors(spec: dict, schema: dict) -> list[str]:
    # Everything except the scenes themselves (and emptiness, reported above
    # with friendlier wording); scenes get per-type validation below.
    top = dict(schema)
    top["properties"] = dict(schema["properties"], timeline={"type": "array"})
    found = Draft7Validator(top).iter_errors(spec)
    return [_describe(e) for e in sorted(found, key=_sort_key)]


def _scene_errors(scene: Any, schema: dict) -> list[str]:
    types = scene_types()
    if not isinstance(scene, dict):
        return [f"must be an object like {{\"type\": \"title\", ...}}, got {_json_type(scene)}"]
    if "type" not in scene:
        return [f"missing required field 'type' (one of: {', '.join(types)})"]
    stype = scene["type"]
    if not isinstance(stype, str):
        return [f"'type' must be text, one of: {', '.join(types)}"]
    if stype not in types:
        return [f"unknown type {stype!r}{_did_you_mean(stype, types, ', '.join(types))}"]
    definitions = schema["definitions"]
    sub = {
        "definitions": definitions,
        "allOf": [
            # Shared scene-level rules (e.g. the transition enum) plus the
            # rules for this scene's own type.
            {"properties": definitions["scene"].get("properties", {})},
            {"$ref": f"#/definitions/{stype}"},
        ],
    }
    found = Draft7Validator(sub).iter_errors(scene)
    out = []
    for e in sorted(found, key=_sort_key):
        if e.validator == "additionalProperties":
            out += _unknown_fields(e)
        else:
            out.append(_describe(e))
    return list(dict.fromkeys(out))  # de-dupe, keep order


def _unknown_fields(e) -> list[str]:
    allowed = sorted(e.schema.get("properties", {}))
    where = _where(e)
    prefix = f"{where}: " if where else ""
    return [
        f"{prefix}unknown field {name!r}{_did_you_mean(name, allowed)}"
        for name in e.instance
        if name not in allowed
    ]


def _describe(e) -> str:
    where = _where(e)
    field = f"'{where}'" if where else "the spec"
    v = e.validator
    if v == "additionalProperties":
        return "; ".join(_unknown_fields(e))
    if v == "required":
        missing = e.message.split("'")[1] if "'" in e.message else e.message
        loc = f"{where}: " if where else ""
        return f"{loc}missing required field {missing!r}"
    if v == "type":
        want = e.validator_value
        wants = want if isinstance(want, list) else [want]
        words = " or ".join(_TYPE_WORDS.get(w, w) for w in wants)
        return f"{field} should be {words}, got {_json_type(e.instance)} ({_short(e.instance)})"
    if v == "enum":
        options = ", ".join(str(o) for o in e.validator_value)
        hint = (
            _did_you_mean(e.instance, [str(o) for o in e.validator_value])
            if isinstance(e.instance, str)
            else ""
        )
        return f"{field} is {_short(e.instance)}, which is not allowed{hint} (use one of: {options})"
    if v == "const":
        return f"{field} must be {e.validator_value!r}, got {_short(e.instance)}"
    if v == "minItems":
        n = e.validator_value
        return f"{field} needs at least {n} item{'s' if n != 1 else ''}"
    if v == "maxItems":
        return f"{field} allows at most {e.validator_value} items, got {len(e.instance)}"
    if v in ("minimum", "exclusiveMinimum"):
        op = ">=" if v == "minimum" else ">"
        return f"{field} must be {op} {e.validator_value}, got {_short(e.instance)}"
    if v in ("maximum", "exclusiveMaximum"):
        op = "<=" if v == "maximum" else "<"
        return f"{field} must be {op} {e.validator_value}, got {_short(e.instance)}"
    if v == "pattern":
        if e.validator_value == "^#[0-9a-fA-F]{6}$":
            return f"{field} should be a six-digit hex colour like #58a6ff, got {_short(e.instance)}"
        return f"{field} does not match the pattern {e.validator_value}, got {_short(e.instance)}"
    return f"{field}: {e.message}"


def _did_you_mean(word: str, options: list[str], fallback: str = "") -> str:
    match = difflib.get_close_matches(word.lower(), options, n=1, cutoff=0.6)
    if match:
        return f", did you mean {match[0]!r}?"
    return f" (choose one of: {fallback})" if fallback else ""


def _where(e) -> str:
    """Dotted path to the failing value, e.g. image.placement or elements[2].color."""
    out = ""
    for part in e.absolute_path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _sort_key(e):
    return [str(p).zfill(6) if isinstance(p, int) else str(p) for p in e.absolute_path]


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, int):
        return "a whole number"
    if isinstance(value, float):
        return "a number"
    if isinstance(value, str):
        return "text"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return type(value).__name__


def _short(value: Any, limit: int = 40) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 3] + "..."
