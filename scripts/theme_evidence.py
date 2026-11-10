"""Render every whole-video colour scheme and capture review evidence."""
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
from moviepy import VideoFileClip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render
from themes.presets import COLOR_SCHEMES


def main():
    out = ROOT / "output" / "theme-evidence"
    out.mkdir(parents=True, exist_ok=True)
    evidence = ROOT / "docs" / "evidence" / "branding"
    evidence.mkdir(parents=True, exist_ok=True)
    gallery = Image.new("RGB", (1920, 1080))
    videos = []
    for i, name in enumerate(COLOR_SCHEMES):
        spec = {
            "meta": {"fps": 6}, "theme": {"color_scheme": name},
            "branding": {"generated": {"name": "Video Render", "style": "spark"},
                         "opacity": 1},
            "timeline": [
                {"type": "title", "text": name.capitalize(),
                 "subtitle": "One choice for every slide", "duration": 1.5},
                {"type": "bullets", "heading": f"{name.capitalize()} / Ideas in motion",
                 "items": ["Coordinated backgrounds and panels", "Readable text and accents", "Matching charts and branding"], "duration": 1.5},
                {"type": "chart", "chart_type": "bar", "heading": "Progress together",
                 "labels": ["Explore", "Create", "Share"], "values": [42, 65, 84], "duration": 1.5},
                {"type": "chart", "chart_type": "pie", "labels": ["Explore", "Create", "Share"],
                 "values": [25, 35, 40], "duration": 1.5},
            ],
        }
        path = out / f"{name}.json"
        path.write_text(json.dumps(spec, indent=2) + "\n")
        video = out / f"{name}.mp4"
        render.render(str(path), str(video), str(out / name))
        videos.append(video)
        sheet = Image.new("RGB", (1920, 1080))
        with VideoFileClip(str(video)) as clip:
            for j, t in enumerate((.75, 2.25, 3.75, 5.25)):
                frame = Image.fromarray(clip.get_frame(t))
                sheet.paste(frame.resize((960, 540)), ((j % 2)*960, (j // 2)*540))
                if j == 1:
                    gallery.paste(frame.resize((640, 360)), ((i % 3)*640, (i // 3)*360))
        sheet.save(evidence / f"scheme-{name}.png")
    gallery.save(evidence / "color-schemes.png")
    concat = out / "concat.txt"
    concat.write_text("".join(f"file '{path}'\n" for path in videos))
    subprocess.run([render._ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-c", "copy", str(evidence / "color-schemes.mp4")], check=True)


if __name__ == "__main__":
    main()
