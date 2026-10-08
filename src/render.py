"""Declarative video spec renderer.

Usage:
    python3 render.py spec.json [-o output.mp4] [--workdir /tmp/renders]

Scene durations are audio-driven when `narration` is present (duration = audio
length + padding), unless an explicit `duration` overrides them.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from moviepy import (ColorClip, CompositeVideoClip, ImageClip, TextClip,
                     AudioFileClip, CompositeAudioClip, concatenate_videoclips,
                     concatenate_audioclips, vfx)

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "themes"))
import tts
import presets

ANIM_IN = 0.6
SLIDE_DIST = 120


def rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def load_spec(path: str) -> dict:
    spec = json.loads(Path(path).read_text())
    theme = dict(presets.__dict__[spec.get("theme", {}).get("preset", "dark")])
    theme.update({k: v for k, v in spec.get("theme", {}).items() if k != "preset"})
    spec["theme"] = theme
    spec.setdefault("meta", {})
    spec["meta"].setdefault("resolution", {"width": 1920, "height": 1080})
    spec["meta"].setdefault("fps", 30)
    return spec


def synth_narration(scene: dict, workdir: Path, voice_cfg: dict) -> tuple[str | None, float]:
    """Synthesize narration if present; return (audio_path, duration)."""
    texts = []
    per_bullet = scene.get("narration_per_bullet")
    if per_bullet:
        texts = per_bullet
    elif scene.get("narration"):
        texts = [scene["narration"]]
    if not texts:
        return None, 0.0
    paths = []
    for i, text in enumerate(texts):
        h = hashlib.sha1(text.encode()).hexdigest()[:10]
        out = workdir / f"narr_{h}_{i}.{voice_cfg.get('format', 'mp3')}"
        if not out.exists():
            tts.synth_to_file(
                text, str(out),
                voice_slug=voice_cfg.get("slug"), voice_id=voice_cfg.get("voice_id"),
                model=voice_cfg.get("model", "voxtral-mini-tts-2603"),
                fmt=voice_cfg.get("format", "mp3"),
            )
        paths.append(str(out))
    if len(paths) == 1:
        return paths[0], tts.audio_duration(paths[0])
    combined = workdir / f"narr_combined_{hashlib.sha1(json.dumps(paths).encode()).hexdigest()[:10]}.{voice_cfg.get('format', 'mp3')}"
    if not combined.exists():
        merged = concatenate_audioclips([AudioFileClip(p) for p in paths])
        merged.write_audiofile(str(combined), logger=None)
    return str(combined), tts.audio_duration(str(combined))


def scene_duration(scene: dict, audio_dur: float, default: float = 4.0) -> float:
    if scene.get("duration"):
        return scene["duration"]
    if audio_dur > 0:
        return audio_dur + scene.get("padding", 0.5)
    if scene.get("type") == "bullets":
        return 1.2 + scene.get("stagger", 0.4) * len(scene.get("items", [])) + 2.0
    return default


def text_clip(text: str, theme: dict, size: int, color: str | None = None,
              center=(0.5, 0.5), bold=False) -> TextClip:
    clip = TextClip(
        text=text, font_size=size,
        color=color or theme["fg"],
        method="caption",
        text_align="center",
        size=(int(1920 * 0.85), None),
    )
    return clip.with_position((center[0], center[1]), relative=True)


def build_title(scene, theme):
    bg = ColorClip(size=(1920, 1080), color=rgb(theme["bg"]))
    title = text_clip(scene["text"], theme, theme["title_font_size"], bold=True,
                      center=(0.5, 0.42))
    clips = [bg, title]
    if scene.get("subtitle"):
        sub = text_clip(scene["subtitle"], theme, int(theme["font_size"] * 0.55),
                        color=theme["accent"], center=(0.5, 0.58))
        clips.append(sub)
    return CompositeVideoClip(clips, size=(1920, 1080))


def build_bullets(scene, theme):
    bg = ColorClip(size=(1920, 1080), color=rgb(theme["bg"]))
    clips = [bg]
    y = 0.25
    if scene.get("heading"):
        clips.append(text_clip(scene["heading"], theme, int(theme["font_size"] * 0.8),
                               color=theme["accent"], center=(0.5, 0.16), bold=True))
    step = min(0.55 / max(len(scene["items"]), 1), 0.18)
    for item in scene["items"]:
        bullet = TextClip(
            text="• " + item, font_size=int(theme["font_size"] * 0.55),
            color=theme["fg"], method="caption", text_align="left",
            size=(int(1920 * 0.75), None),
        )
        bullet = bullet.with_position(("center", y * 1080))
        clips.append(bullet)
        y += step
    return CompositeVideoClip(clips, size=(1920, 1080))


def build_image(scene, theme, workdir):
    src = scene["src"]
    img_clip = ImageClip(src)
    scale = max(1920 / img_clip.w, 1080 / img_clip.h)
    img_clip = img_clip.resized(scale)
    if img_clip.w > 1920 or img_clip.h > 1080:
        img_clip = img_clip.cropped(x_center=img_clip.w / 2, y_center=img_clip.h / 2,
                                     width=1920, height=1080)
    img_clip = img_clip.with_position("center")
    clips = [img_clip]
    if scene.get("caption"):
        cap = text_clip(scene["caption"], theme, int(theme["font_size"] * 0.5))
        cap = cap.with_position(("center", 0.86), relative=True)
        cap_bg = ColorClip(size=(1920, int(1080 * 0.14)), color=(0, 0, 0)).with_opacity(0.6)
        cap_bg = cap_bg.with_position(("center", 0.86), relative=True)
        clips.extend([cap_bg, cap])
    return CompositeVideoClip(clips, size=(1920, 1080))


def build_chart(scene, theme, workdir):
    fig, ax = plt.subplots(figsize=(19.2, 10.8), dpi=100)
    fig.patch.set_facecolor(theme["bg"])
    ax.set_facecolor(theme["bg"])
    ax.tick_params(colors=theme["fg"], labelsize=18)
    for spine in ax.spines.values():
        spine.set_color(theme["fg"])
    if scene.get("chart_type", "bar") == "bar":
        bars = ax.bar(scene["labels"], scene["values"],
                      color=theme["accent"], width=0.55)
    elif scene["chart_type"] == "line":
        ax.plot(scene["labels"], scene["values"], color=theme["accent"],
                linewidth=4, marker="o", markersize=10)
    else:
        ax.pie(scene["values"], labels=scene["labels"], colors=[theme["accent"], theme["fg"], "#888"],
               textprops={"color": theme["fg"], "fontsize": 18}, autopct="%1.0f%%")
    if scene["chart_type"] != "pie":
        if scene.get("y_label"):
            ax.set_ylabel(scene["y_label"], color=theme["fg"], fontsize=20)
        ax.set_title(scene.get("heading", ""), color=theme["fg"],
                     fontsize=28, pad=20)
        ax.grid(axis="y", alpha=0.25, color=theme["fg"])
    out = workdir / f"chart_{hashlib.sha1(json.dumps(scene).encode()).hexdigest()[:10]}.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=theme["bg"])
    plt.close(fig)
    img = ImageClip(str(out)).resized(height=1080)
    if img.w > 1920:
        img = img.resized(width=1920)
    img = img.with_position("center")
    return CompositeVideoClip([img], size=(1920, 1080))


def build_outro(scene, theme):
    bg = ColorClip(size=(1920, 1080), color=rgb(theme["bg"]))
    txt = text_clip(scene["text"], theme, theme["title_font_size"],
                    color=theme["accent"], bold=True)
    return CompositeVideoClip([bg, txt], size=(1920, 1080))


BUILDERS = {
    "title": build_title,
    "bullets": build_bullets,
    "image": build_image,
    "chart": build_chart,
    "outro": build_outro,
}


def apply_anim(clip, anim: str, duration: float):
    if anim in ("fade", "kenburns"):
        return clip.with_effects([vfx.FadeIn(ANIM_IN), vfx.FadeOut(ANIM_IN)])
    if anim == "slide-up":
        def pos(t):
            return ("center", 1080 / 2 + min(t / ANIM_IN, 1) * SLIDE_DIST)
        return clip.with_position(pos).with_effects([vfx.FadeIn(ANIM_IN)])
    if anim == "zoom-in":
        def zoom(t):
            return 1.0 + min(t / duration, 1) * 0.06
        return clip.resized(lambda t: 1.0 + min(t / (duration * 0.8), 1) * 0.05) \
                   .with_effects([vfx.FadeIn(ANIM_IN)])
    return clip


def render(spec_path: str, output: str, workdir: str | None = None):
    spec = load_spec(spec_path)
    theme = spec["theme"]
    voice_cfg = spec.get("voice", {})
    workdir = Path(workdir or Path(spec_path).parent / ".render_cache")
    workdir.mkdir(parents=True, exist_ok=True)

    video_clips, audio_clips = [], []
    t_cursor = 0.0
    for i, scene in enumerate(spec["timeline"]):
        stype = scene["type"]
        builder = BUILDERS[stype]
        if stype == "image":
            clip = builder(scene, theme, workdir)
        elif stype == "chart":
            clip = builder(scene, theme, workdir)
        else:
            clip = builder(scene, theme)

        try:
            audio_path, audio_dur = synth_narration(scene, workdir, voice_cfg)
        except RuntimeError as e:
            if "MISTRAL_API_KEY" in str(e):
                print(f"[warn] {e} — rendering scene {i} without narration")
                audio_path, audio_dur = None, 0.0
            else:
                raise

        dur = scene_duration(scene, audio_dur)
        clip = clip.with_duration(dur)
        clip = apply_anim(clip, scene.get("anim", "fade"), dur)

        if audio_path:
            a = AudioFileClip(audio_path).with_start(0)
            clip = clip.with_audio(a)

        video_clips.append(clip)
        t_cursor += dur
        print(f"[scene {i}] {stype}: {dur:.2f}s"
              + (f" (narration {audio_dur:.2f}s)" if audio_path else ""))

    final = concatenate_videoclips(video_clips, method="compose")

    audios = [c.audio for c in video_clips if c.audio]
    if spec.get("music", {}).get("src"):
        m = spec["music"]
        music = AudioFileClip(m["src"]).with_volume_scaled(m.get("volume", 0.2))
        music = music.subclipped(0, min(music.duration, final.duration))
        music = music.with_effects([vfx.audioFadeIn(m.get("fade_in", 1)),
                                    vfx.audioFadeOut(m.get("fade_out", 2))])
        audios.append(music)
    if audios:
        final = final.with_audio(CompositeAudioClip(audios))

    fps = spec["meta"]["fps"]
    final.write_videofile(output, fps=fps, codec="libx264",
                          audio_codec="aac", logger=None)
    print(f"[done] {output} ({t_cursor:.1f}s at {fps}fps)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("spec")
    p.add_argument("-o", "--output", default="output/video.mp4")
    p.add_argument("--workdir", default=None)
    args = p.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    render(args.spec, args.output, args.workdir)
