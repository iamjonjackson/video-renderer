#!/usr/bin/env python3
"""Offline fixture evidence, NOT a live generation/model comparison.

Usage: .venv/bin/python scripts/evaluate_generation.py --output /tmp/frame-eval
Optional --spec PATH (repeatable) evaluates already-generated candidates too.
Reads sources only. Writes silent full-film MP4, editable PPTX, PNG samples and
report.json outside the repository. Copies retain scene durations/transitions;
films must be <=60 seconds, <=12 composition scenes. Evidence uses the smallest
supported matching aspect ratio at 6 fps (720p landscape/portrait, 1080 square),
not production export or factual approval. No provider calls or .env reads.
"""
import argparse
import base64
import copy
import json
import importlib
import os
from pathlib import Path
import subprocess
import sys
import types
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]


def isolate():
    """Relaunch before media imports, keeping credentials out of ffmpeg children."""
    env = {key: os.environ[key] for key in
           ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME")
           if key in os.environ}
    env["PYTHON_DOTENV_DISABLED"] = "1"
    return subprocess.run([sys.executable, str(Path(__file__).resolve()),
                           *sys.argv[1:], "--isolated"], env=env, check=False).returncode


def fixture_document(fixture, brief, sources):
    scenes = []
    for index, text in enumerate(fixture["text"]):
        refs = [source["id"] for source in sources
                if source["text"].rstrip(".") == text.rstrip(".")]
        refs = refs or [sources[0]["id"]]
        item = {"id": "claim", "type": "text", "text": text,
                "font_size": .032, "x": .08, "y": .12, "w": .84, "h": .30,
                "color": "#ffffff"}
        if fixture["id"] == "long-token" and index == 0:
            item["w"] = .30
        if fixture.get("supplied_image") and index == 0:
            item["w"] = .40
        elements = [item]
        if fixture.get("chartData"):
            elements.append({"id": "data", "type": "chart", "chart_type": "bar",
                             **fixture["chartData"], "x": .08, "y": .48,
                             "w": .84, "h": .40, "color": "#93c5fd"})
        scene = {"type": "composition", "duration": 4, "motion_version": 1,
                 "source_ids": refs, "elements": elements,
                 "background": {"style": "solid", "color": "#191925"}}
        if brief.get("motion", True) and index < len(fixture["text"]) - 1:
            scene["transition"] = {"effect": "crossfade", "duration": .4}
        scenes.append(scene)
    return {"version": 1, "meta": {"title": brief["title"],
            "resolution": brief["resolution"]}, "timeline": scenes}


def rejection_probe(fixture, candidate, brief, sources, generation, quality):
    bad = copy.deepcopy(candidate)
    kind = fixture["id"]
    if kind == "tutorial":
        bad["timeline"][0]["source_ids"] = ["unknown-source"]
    elif kind == "comparison":
        bad["timeline"][0]["elements"][0]["text"] = "999999% measured improvement"
    elif kind == "data":
        bad["timeline"][0]["elements"][1]["values"][0] = 999999
    elif kind == "image":
        bad["timeline"][0]["elements"].append({"id": "untrusted-image", "type": "image",
            "src": image_data(), "alt": "Untrusted generated image", "fit": "cover",
            "x": .54, "y": .15, "w": .38, "h": .70, "color": "#ffffff"})
    try:
        validated = generation.validate_candidate(bad, brief, sources)
    except ValueError as error:
        return {"expected": fixture["expected_rejection"], "observed": str(error)[:300],
                "rejected": True}
    errors = quality.inspect_document(validated)["errors"]
    return {"expected": fixture["expected_rejection"], "observed": errors,
            "rejected": any("unbreakable text" in error for error in errors) if kind == "long-token" else False}


def image_data():
    from PIL import Image
    output = BytesIO()
    Image.new("RGB", (48, 48), "#537b91").save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()


def render_evidence(spec, directory, render, composition):
    silent = copy.deepcopy(spec)
    scenes = silent["timeline"]
    if not 1 <= len(scenes) <= 12 or any(s["type"] != "composition" for s in scenes):
        raise ValueError("Evidence requires 1–12 composition scenes")
    if sum(s["duration"] for s in scenes) > 60:
        raise ValueError("Evidence timeline exceeds 60 seconds")
    silent.pop("theme", None)
    silent["meta"].pop("tts", None)
    original = silent["meta"]["resolution"]
    # Choose an existing supported size with identical aspect, including square.
    candidates = [(w, h) for w, h in composition.RESOLUTIONS
                  if w * original["height"] == h * original["width"]]
    width, height = min(candidates, key=lambda size: size[0] * size[1])
    silent["meta"]["resolution"] = {"width": width, "height": height}
    silent["meta"]["fps"] = 6
    for scene in scenes:
        for field in ("narration", "narration_per_bullet", "image"):
            scene.pop(field, None)
    directory.mkdir()
    spec_path = directory / "silent-evidence.json"
    spec_path.write_text(json.dumps(silent), encoding="utf-8")
    manifest = directory / "silent-media.json"
    manifest.write_text('{"scenes": []}', encoding="utf-8")
    render.render(str(spec_path), str(directory / "film.mp4"),
                  str(directory / "cache"), media_manifest=str(manifest))
    width, height = silent["meta"]["resolution"].values()
    for index, scene in enumerate(scenes):
        clip = composition.build_clip(scene, width, height)
        try:
            from PIL import Image
            Image.fromarray(clip.get_frame(scene["duration"] * .65)).save(
                directory / f"scene-{index+1:02d}.png")
        finally:
            clip.close()
    return {"duration_seconds": sum(s["duration"] for s in scenes),
            "fps": 6, "resolution": silent["meta"]["resolution"],
            "silent": True, "source_resolution": original}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise ValueError(f"Cannot read JSON input: {path}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--spec", action="append", default=[], type=Path)
    parser.add_argument("--isolated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.isolated:
        return isolate()
    # MoviePy's configuration imports dotenv and calls find_dotenv automatically.
    # Supply a no-I/O module before any media imports, even on older dotenv versions.
    dotenv = types.ModuleType("dotenv")
    setattr(dotenv, "find_dotenv", lambda *args, **kwargs: "")
    setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    sys.modules["dotenv"] = dotenv
    sys.path.insert(0, str(ROOT))
    composition = importlib.import_module("src.composition")
    generation = importlib.import_module("src.generation")
    quality = importlib.import_module("src.quality")
    render = importlib.import_module("src.render")
    validate_spec = importlib.import_module("src.document").validate_spec
    output = args.output.resolve()
    if output.is_relative_to(ROOT) or (output.exists() and any(output.iterdir())):
        raise ValueError("Choose a new/empty output directory outside the repository")
    output.mkdir(parents=True, exist_ok=True)
    briefs = read_json(ROOT / "samples/canvas-ai-briefs.json")
    corpus = read_json(ROOT / "samples/generation-evaluation.json")
    report = {"label": corpus["label"], "requires_human_review": True, "fixtures": [],
              "imported_candidates": [], "provider_calls": 0}
    for fixture in corpus["fixtures"]:
        if "brief" in fixture:
            brief = copy.deepcopy(fixture["brief"])
        else:
            brief = copy.deepcopy(next(b for b in briefs if b["id"] == fixture["brief_id"]))
            brief.pop("id")
        if fixture.get("chartData"):
            brief["chartData"] = fixture["chartData"]
        sources = generation.source_bundle(brief)
        candidate = fixture_document(fixture, brief, sources)
        probe = rejection_probe(fixture, candidate, brief, sources, generation, quality)
        candidate = generation.validate_candidate(candidate, brief, sources)
        if fixture.get("supplied_image"):
            generation.validate_asset_slot(candidate)
            candidate["timeline"][0]["elements"].append({"id": "supplied-asset", "type": "image",
                "src": image_data(), "alt": "Synthetic local fixture, not generated imagery",
                "fit": "cover", "x": .54, "y": .15, "w": .38, "h": .70, "color": "#ffffff"})
        checks = quality.inspect_document(candidate)
        entry = {"id": fixture["id"], "sources": sources, "quality": checks,
                 "rejection_probe": probe}
        # Render intentional clipping too: reviewers need evidence of the failure.
        entry["evidence"] = render_evidence(candidate, output / fixture["id"], render, composition)
        report["fixtures"].append(entry)
    for index, path in enumerate(args.spec):
        candidate = validate_spec(read_json(path))
        entry = {"path": str(path.resolve()), "quality": quality.inspect_document(candidate),
                 "fidelity": "Not checked: imported specs need their original brief/source bundle"}
        entry["evidence"] = render_evidence(candidate, output / f"imported-{index+1}", render, composition)
        report["imported_candidates"].append(entry)
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if all(entry["rejection_probe"]["rejected"] for entry in report["fixtures"]) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        raise SystemExit(2) from None
