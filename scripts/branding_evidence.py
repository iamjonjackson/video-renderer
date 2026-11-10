"""Generate reproducible review evidence without API keys.

Run: .venv/bin/python scripts/branding_evidence.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import render
import branding


def main():
    out = ROOT / "output" / "branding-evidence"
    out.mkdir(parents=True, exist_ok=True)
    evidence = ROOT / "docs" / "evidence" / "branding"
    evidence.mkdir(parents=True, exist_ok=True)
    # Show every palette/style combination, using the same generator as render.
    gallery = Image.new("RGB", (2000, 2700), "#0d1117")
    draw = ImageDraw.Draw(gallery)
    font_path = render._resolve_font(True)
    font = ImageFont.truetype(font_path, 20)
    for row, style in enumerate(branding.STYLES):
        for col, palette in enumerate(branding.PALETTES):
            cfg = {"name": "Video Render", "style": style, "palette": palette}
            pixels = branding.generated_logo(json.dumps(cfg, sort_keys=True), font_path)
            logo = Image.fromarray(pixels)
            logo.thumbnail((430, 160), Image.Resampling.LANCZOS)
            x, y = (col % 3)*660, (col // 3)*900 + row*300
            draw.rectangle((x, y, x+660, y+300), fill=branding.COLOR_SCHEMES[palette]["bg"])
            draw.text((x+30, y+30), f"{palette.upper()} / {style}", font=font, fill=branding.COLOR_SCHEMES[palette]["fg"])
            gallery.paste(logo, (x+30, y+105), logo)
    gallery.save(evidence / "brand-options.png")
    screenshots = []
    videos = []
    for corner, palette in zip(("top-left", "top-right", "bottom-left", "bottom-right"), branding.PALETTES):
        spec = {
            "meta": {"fps": 8},
            "theme": {"color_scheme": palette},
            "branding": {"generated": {"name": "Video Render"},
                         "position": corner, "margin": .05,
                         "max_height": .1, "opacity": .85},
            "timeline": [{"type": "title", "text": corner,
                          "subtitle": f"{palette} · 5% inset · 10% max height · 85% opacity", "duration": 2}],
        }
        spec_path = out / f"{corner}.json"
        spec_path.write_text(json.dumps(spec, indent=2) + "\n")
        video = out / f"{corner}.mp4"
        render.render(str(spec_path), str(video), str(out / "cache"))
        with VideoFileClip(str(video)) as clip:
            screenshots.append(Image.fromarray(clip.get_frame(1)).resize((960, 540)))
        videos.append(video)
    sheet = Image.new("RGB", (1920, 1080))
    for i, frame in enumerate(screenshots):
        sheet.paste(frame, ((i % 2)*960, (i // 2)*540))
    sheet.save(evidence / "four-corners.png")
    concat = out / "concat.txt"
    concat.write_text("".join(f"file '{path}'\n" for path in videos))
    subprocess.run([render._ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", str(concat), "-c", "copy",
                    str(evidence / "four-corners.mp4")], check=True)
    spec["branding"].update(scenes=["title", "outro"])
    spec["timeline"] = [
        {"type": "title", "text": "Title: branded", "duration": 2},
        {"type": "bullets", "heading": "Bullets: unbranded", "items": ["Scene filter excludes this scene"], "duration": 2},
        {"type": "outro", "text": "Outro: branded", "duration": 2},
    ]
    spec_path = out / "filtered.json"
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")
    filtered = out / "title-outro-only.mp4"
    render.render(str(spec_path), str(filtered), str(out / "cache"))
    shutil.copyfile(filtered, evidence / filtered.name)
    strip = Image.new("RGB", (1920, 360))
    with VideoFileClip(str(filtered)) as clip:
        for i, time in enumerate((1, 3, 5)):
            frame = Image.fromarray(clip.get_frame(time)).resize((640, 360))
            strip.paste(frame, (i*640, 0))
    strip.save(evidence / "title-outro-only.png")


if __name__ == "__main__":
    main()
