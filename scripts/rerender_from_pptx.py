"""import chart and wording edits into a separate spec, narrated video and native deck"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pptx_import


def rerender(spec_path, edited_pptx, output, workdir=None, slides_dir=None, spec_only=False):
    """reuse the existing renderer and publish outputs only after the rerender succeeds"""
    output = Path(output).resolve()
    if output.suffix.lower() != ".mp4":
        raise ValueError("Choose an MP4 output name; the JSON and PPTX will use the same stem")
    destinations = [output.with_suffix(".json")] if spec_only else [output, output.with_suffix(".pptx"), output.with_suffix(".json")]
    for destination in destinations:
        if destination.exists():
            raise FileExistsError(f"Output already exists; choose a new name: {destination}")
    output.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(workdir) if workdir else Path(spec_path).resolve().parent / ".render_cache"
    # staging protects the originals and avoids publishing a half-finished set of files
    with tempfile.TemporaryDirectory(prefix=".pptx-rerender-", dir=output.parent) as tmp:
        staging = Path(tmp)
        source = staging / "edited.pptx"
        shutil.copy2(edited_pptx, source)
        spec, indices, changed = pptx_import.import_chart_edits(spec_path, source)
        spec_file = staging / "updated.json"
        spec_file.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("[import] updated content on slides: " + (", ".join(str(i + 1) for i in changed) or "none; retaining narration"))
        if spec_only:
            spec_file.replace(output.with_suffix(".json"))
            print(f"[done] {output.with_suffix('.json')} (spec preview only)")
            return
        # importing the video stack is unnecessary for a data-only preview
        import render
        images = pptx_import.chart_slide_images(source, indices, staging / "slides", render.W, render.H, slides_dir)
        rendered_spec = staging / "video.json"
        rendered_spec.write_text(json.dumps(pptx_import.video_spec(spec, images)), encoding="utf-8")
        staged_video = staging / "result.mp4"
        render.render(str(rendered_spec), str(staged_video), str(cache), source_pptx=str(source))
        for path in (staged_video, staged_video.with_suffix(".pptx"), spec_file):
            if not path.is_file():
                raise RuntimeError(f"The rerender did not produce {path.suffix}")
        for path, destination in zip((staged_video, staged_video.with_suffix(".pptx"), spec_file), destinations):
            path.replace(destination)
            print(f"[done] {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", help="the original JSON spec used to build the deck")
    parser.add_argument("pptx", help="the edited and saved PowerPoint deck")
    parser.add_argument("-o", "--output", required=True, help="a new MP4 filename")
    parser.add_argument("--workdir", help="reuse a narration/image cache directory")
    parser.add_argument("--slides-dir", help="use Slide1.png etc exported from PowerPoint instead of LibreOffice")
    parser.add_argument("--spec-only", action="store_true", help="preview imported data and narration without rendering or API calls")
    args = parser.parse_args()
    try:
        rerender(args.spec, args.pptx, args.output, args.workdir, args.slides_dir, args.spec_only)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"[error] {error}\n")


if __name__ == "__main__":
    main()
