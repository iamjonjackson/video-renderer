"""Normalised canvas elements shared by MoviePy and editable PowerPoint export."""

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from io import BytesIO
from typing import cast

import numpy as np
from fontTools.ttLib import TTFont
from moviepy import VideoClip
from PIL import Image, ImageDraw, ImageFont

if __package__:
    from .canvas_assets import decode_image, raster_image
else:
    from canvas_assets import decode_image, raster_image

RESOLUTIONS = (
    (1280, 720),
    (1920, 1080),
    (1080, 1920),
    (1080, 1080),
    (720, 1280),
    (2560, 1440),
    (3840, 2160),
    (2160, 3840),
    (2160, 2160),
)
BACKGROUNDS = ("solid", "gradient", "grid", "orbits", "waves")
ICONS = (
    "check", "arrow", "star", "info", "target", "heart",
    "book", "code", "shield", "users", "cloud", "lightbulb",
    "calendar", "chart", "mail", "globe", "layers", "play",
)
VECTOR_LIBRARY_PATH = Path(__file__).resolve().parents[1] / "studio/vector-library.json"


FONT_FAMILIES = {"sans": "DejaVu Sans", "serif": "DejaVu Serif", "mono": "DejaVu Sans Mono"}
FONT_FILES = {"sans": "DejaVuSans", "serif": "DejaVuSerif", "mono": "DejaVuSansMono"}


@lru_cache(maxsize=6)
def font_path(bold=False, family="sans"):
    if not isinstance(family, str) or family not in FONT_FILES:
        raise ValueError("Choose a supported font family: sans, serif or mono.")
    import matplotlib

    path = (
        Path(matplotlib.__file__ or "").parent
        / "mpl-data/fonts/ttf"
        / (FONT_FILES[family] + ("-Bold.ttf" if bold else ".ttf"))
    )
    return str(path)


@lru_cache(maxsize=6)
def supported_codepoints(bold=False, family="sans"):
    with TTFont(font_path(bold, family)) as font:
        return frozenset(font.getBestCmap() or {})


def check_glyphs(text, where, bold=False, family="sans"):
    unsupported = sorted(
        {
            ord(char)
            for char in text
            if char not in "\n\r\t" and ord(char) not in supported_codepoints(bold, family)
        }
    )
    if unsupported:
        values = ", ".join(f"U+{code:04X}" for code in unsupported[:6])
        raise ValueError(
            f"{where}: the export font cannot display {values}. Replace those symbols with supported text; colour emoji are not supported."
        )


def validate_composition(scene, text, number, object_fields):
    object_fields(
        scene,
        (
            "type",
            "name",
            "elements",
            "background",
            "duration",
            "narration",
            "padding",
            "motion_version",
            "transition",
        ),
        "Canvas scene",
    )
    if "motion_version" in scene and (
        type(scene["motion_version"]) is not int or scene["motion_version"] != 1
    ):
        raise ValueError("Canvas: only motion_version 1 is supported.")
    text(scene.get("name", "Canvas"), "Scene name", 100)
    background = scene.setdefault("background", {})
    for key, value in {
        "style": "solid",
        "color": "#191925",
        "accent": "#6750a4",
        "motion": "none",
    }.items():
        background.setdefault(key, value)
    object_fields(background, ("style", "color", "accent", "motion"), "Background")
    if background.get("style", "solid") not in BACKGROUNDS or background.get(
        "motion", "none"
    ) not in ("none", "drift", "pulse"):
        raise ValueError("Choose a supported background and motion.")
    for key in ("color", "accent"):
        if key in background:
            colour(background[key])
    elements = scene.get("elements")
    if not isinstance(elements, list) or len(elements) > 16:
        raise ValueError("Canvas: use at most 16 elements.")
    ids = set()
    for index, item in enumerate(elements, 1):
        where = f"Element {index}"
        if not isinstance(item, dict) or item.get("type") not in (
            "text",
            "chart",
            "shape",
            "icon",
            "image",
        ):
            raise ValueError(f"{where}: choose text, chart, shape, icon or image.")
        common = (
            "id",
            "type",
            "x",
            "y",
            "w",
            "h",
            "color",
            "animation",
            "exit_animation",
            "keyframes",
        )
        fields = {
            "text": ("text", "font_size", "bold", "align", "font_family"),
            "chart": ("chart_type", "labels", "values"),
            "shape": ("shape",),
            "icon": ("icon",),
            "image": ("src", "alt", "fit"),
        }
        object_fields(item, common + fields[item["type"]], where)
        if "keyframes" in item:
            if scene.get("motion_version") != 1:
                raise ValueError("Keyframed elements require motion_version 1.")
            validate_keyframes(
                item["keyframes"], scene.get("duration"), where, number, object_fields
            )
        for key in ("animation", "exit_animation"):
            if key in item:
                if scene.get("motion_version") != 1:
                    raise ValueError("Animated elements require motion_version 1.")
                validate_animation(
                    item[key],
                    scene.get("duration"),
                    f"{where} {key}",
                    number,
                    object_fields,
                )
                effect = item[key]["effect"]
                if key == "exit_animation" and effect in (
                    "words",
                    "wipe",
                    "characters",
                    "chart-draw",
                ):
                    raise ValueError(f"{where}: {effect} is an entrance-only effect.")
                if effect in ("words", "characters") and item["type"] != "text":
                    raise ValueError(f"{where}: {effect} requires a text element.")
                if effect == "chart-draw" and item["type"] != "chart":
                    raise ValueError(f"{where}: chart-draw requires a chart element.")
        if "animation" in item and "exit_animation" in item:
            entrance_end = item["animation"]["start"] + item["animation"]["duration"]
            exit_start = item["exit_animation"]["start"]
            if entrance_end > exit_start and not math.isclose(
                entrance_end, exit_start, rel_tol=0, abs_tol=1e-9
            ):
                raise ValueError(f"{where}: entrance must end before the exit starts.")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 60
            or identifier in ids
        ):
            raise ValueError("Each canvas element needs a unique text id.")
        ids.add(identifier)
        for key in ("x", "y"):
            number(item.get(key), f"{where} {key}", 0, 1)
        for key in ("w", "h"):
            number(item.get(key), f"{where} {key}", 0.02, 1)
        if item["x"] + item["w"] > 1.000001 or item["y"] + item["h"] > 1.000001:
            raise ValueError(f"{where}: keep the element inside the canvas.")
        colour(item.get("color"))
        if item["type"] == "text":
            item.setdefault("font_size", 0.06)
            item.setdefault("bold", False)
            item.setdefault("align", "left")
            item.setdefault("font_family", "sans")
            family = item["font_family"]
            if not isinstance(family, str) or family not in FONT_FAMILIES:
                raise ValueError(f"{where}: choose sans, serif or mono font family.")
            text(item.get("text"), where, 600)
            number(item.get("font_size", 0.06), f"{where} font size", 0.02, 0.15)
            if not isinstance(item.get("bold", False), bool) or item.get(
                "align", "left"
            ) not in ("left", "center", "right"):
                raise ValueError(f"{where}: invalid text formatting.")
            check_glyphs(item["text"], where, item.get("bold", False), family)
        elif item["type"] == "image":
            item.setdefault("fit", "cover")
            item.setdefault("alt", "")
            text(item["alt"], f"{where} alt", 600)
            if item["fit"] not in ("cover", "contain"):
                raise ValueError(f"{where}: choose cover or contain image fit.")
            decode_image(item.get("src"))
        elif item["type"] == "icon":
            if item.get("icon") not in ICONS:
                raise ValueError(f"{where}: choose a supported icon.")
        elif item["type"] == "shape":
            item.setdefault("shape", "rect")
            if item.get("shape", "rect") not in (
                "rect",
                "ellipse",
                "rounded",
                "triangle",
                "arrow",
            ):
                raise ValueError(f"{where}: choose a supported shape.")
        else:
            labels, values = item.get("labels"), item.get("values")
            if (
                not isinstance(labels, list)
                or not isinstance(values, list)
                or not 1 <= len(labels) <= 8
                or len(labels) != len(values)
            ):
                raise ValueError(
                    f"{where}: supply 1–8 matching chart labels and values."
                )
            for label in labels:
                text(label, where, 40)
                check_glyphs(label, where)
            for value in values:
                number(value, where, -1000000, 1000000)
            kind = item.setdefault("chart_type", "bar")
            if kind not in ("bar", "horizontal", "line", "area", "pie", "doughnut") or (
                kind in ("pie", "doughnut") and (min(values) < 0 or sum(values) <= 0)
            ):
                raise ValueError(f"{where}: invalid chart style or pie values.")
    return scene


def validate_keyframes(keyframes, scene_duration, where, number, object_fields):
    """Validate scene-time transforms; x/y are offsets from resting geometry."""
    if not isinstance(keyframes, list) or not 2 <= len(keyframes) <= 8:
        raise ValueError(f"{where}: supply 2–8 keyframes.")
    number(scene_duration, "Keyframed scene duration", 0, float("inf"))
    previous_time = -1
    for index, keyframe in enumerate(keyframes, 1):
        label = f"{where} keyframe {index}"
        object_fields(keyframe, ("time", "x", "y", "scale", "opacity"), label)
        number(keyframe.get("time"), f"{label} time", 0, scene_duration)
        for axis in ("x", "y"):
            number(keyframe.get(axis), f"{label} {axis} offset", -1, 1)
        number(keyframe.get("scale"), f"{label} scale", 0.5, 1.5)
        number(keyframe.get("opacity"), f"{label} opacity", 0, 1)
        if keyframe["time"] <= previous_time:
            raise ValueError(f"{where}: keyframe times must strictly increase.")
        previous_time = keyframe["time"]


def keyframe_state(keyframes, t):
    """Cosine ease-in-out per segment, with exact knots and clamped endpoints."""
    if t <= keyframes[0]["time"]:
        return keyframes[0]
    for left, right in zip(keyframes, keyframes[1:]):
        if t == right["time"]:
            return right
        if t < right["time"]:
            progress = (t - left["time"]) / (right["time"] - left["time"])
            eased = 0.5 - 0.5 * math.cos(math.pi * progress)
            return {
                key: left[key] + (right[key] - left[key]) * eased
                for key in ("x", "y", "scale", "opacity")
            }
    return keyframes[-1]


def validate_animation(animation, scene_duration, where, number, object_fields):
    """Validate a finite v1 entrance or exit without changing resting geometry."""
    object_fields(
        animation,
        ("effect", "start", "duration", "easing", "direction", "intensity"),
        f"{where} animation",
    )
    if animation.get("effect") not in (
        "fade",
        "slide",
        "scale",
        "words",
        "wipe",
        "characters",
        "chart-draw",
    ):
        raise ValueError(f"{where}: choose a supported entrance or exit effect.")
    if animation.get("easing") not in (
        "linear", "ease-out", "ease-in-out", "ease-out-quart"
    ):
        raise ValueError(f"{where}: choose a supported easing curve.")
    number(animation.get("intensity", 1), f"{where} animation intensity", 0, 2)
    number(scene_duration, "Animated scene duration", 0, float("inf"))
    number(animation.get("start"), f"{where} animation start", 0, scene_duration)
    number(animation.get("duration"), f"{where} animation duration", 0.1, 3)
    end = animation["start"] + animation["duration"]
    # Decimal second endpoints can accumulate one binary rounding error.
    if end > scene_duration and not math.isclose(
        end, scene_duration, rel_tol=0, abs_tol=1e-9
    ):
        raise ValueError(f"{where}: animation must end within the scene duration.")
    if "direction" in animation and (
        animation["effect"] != "slide"
        or animation["direction"] not in ("left", "right", "up", "down")
    ):
        raise ValueError(f"{where}: direction is supported only for slide animations.")


def animation_progress(animation, t):
    """Clamped scene-time progress using the browser's shared easing curves."""
    progress = min(1.0, max(0.0, (t - animation["start"]) / animation["duration"]))
    easing = animation["easing"]
    if easing == "ease-out":
        return 1 - (1 - progress) ** 3
    if easing == "ease-in-out":
        return 0.5 - 0.5 * math.cos(math.pi * progress)
    if easing == "ease-out-quart":
        return 1 - (1 - progress) ** 4
    return progress


def reveal_progress(item, t):
    """Entrance reveal fraction, separate from the legacy motion-state keys.

    Browser/export contract: words uses floor(progress * whitespace word count);
    characters counts Unicode codepoints (JS Array.from), including whitespace,
    not grapheme clusters. Chart-draw reveals geometry; wipe exposes the left
    progress fraction of the original element box.
    Neither reveal changes resting geometry or fades the revealed content.
    """
    animation = item.get("animation")
    if animation and animation["effect"] in (
        "words",
        "wipe",
        "characters",
        "chart-draw",
    ):
        return animation_progress(animation, t)
    return 1.0


def motion_state(item, t):
    """Return opacity, canvas-normalised dx/dy and centred scale at scene time t.

    Inputs must satisfy validate_composition. Slide direction names the starting
    side for entrances and the destination side for exits, defaulting to left.
    Intensity defaults to 1 and scales only slide distance and scale displacement;
    all effects accept it, but opacity and reveal progress are unaffected.
    Keyframes add offsets and multiply opacity/scale after entrance/exit motion.
    """
    state = {"opacity": 1.0, "dx": 0.0, "dy": 0.0, "scale": 1.0}
    for key in ("animation", "exit_animation"):
        if key not in item:
            continue
        animation = item[key]
        if animation["effect"] in ("words", "wipe", "characters", "chart-draw"):
            continue
        progress = animation_progress(animation, t)
        disappearing = progress if key == "exit_animation" else 1 - progress
        state["opacity"] *= 1 - disappearing
        if animation["effect"] == "slide":
            axis, sign = {
                "left": ("dx", -1),
                "right": ("dx", 1),
                "up": ("dy", -1),
                "down": ("dy", 1),
            }[animation.get("direction", "left")]
            state[axis] += sign * 0.06 * animation.get("intensity", 1) * disappearing
        elif animation["effect"] == "scale":
            state["scale"] *= 1 - 0.15 * animation.get("intensity", 1) * disappearing
    if "keyframes" in item:
        authored = keyframe_state(item["keyframes"], t)
        state["dx"] += authored["x"]
        state["dy"] += authored["y"]
        state["scale"] *= authored["scale"]
        state["opacity"] *= authored["opacity"]
    return state


def colour(value):
    import re

    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Use a six-digit hex colour.")
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def background_frame(config, width, height, t=0):
    base = np.array(colour(config.get("color", "#191925")), dtype=float)
    accent = np.array(colour(config.get("accent", "#6750a4")), dtype=float)
    style = config.get("style", "solid")
    motion = config.get("motion", "none")
    phase = t * 0.35 if motion == "drift" else 0
    pulse = 0.7 + 0.3 * math.sin(t * 0.7) if motion == "pulse" else 1
    strength = 0.25 * pulse
    if style == "gradient":
        ramp = (
            np.clip(np.linspace(0, 1, width) + math.sin(phase) * 0.15, 0, 1)[
                None, :, None
            ]
            * strength
        )
        data = (
            np.broadcast_to(base * (1 - ramp) + accent * ramp, (height, width, 3))
            .astype("uint8")
            .copy()
        )
        image = Image.fromarray(data)
    else:
        image = Image.new("RGB", (width, height), tuple(base.astype(int)))
    draw = ImageDraw.Draw(image)
    line = tuple((base * (1 - 0.3 * pulse) + accent * 0.3 * pulse).astype(int))
    if style == "grid":
        step = max(20, round(height * 0.09))
        offset = round(phase * step) % step
        for x in range(-step + offset, width + step, step):
            draw.line((x, 0, x, height), fill=line, width=1)
        for y in range(-step + offset, height + step, step):
            draw.line((0, y, width, y), fill=line, width=1)
    elif style == "orbits":
        cx, cy = width * 0.82 + math.sin(phase) * width * 0.03, height * 0.25
        for i in range(1, 6):
            radius = height * (0.13 * i + 0.02 * math.sin(phase))
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=line,
                width=max(1, round(height * 0.002)),
            )
    elif style == "waves":
        for band in range(5):
            points = [
                (
                    x,
                    height * (0.65 + band * 0.06)
                    + math.sin(x / width * math.pi * 2 + phase + band * 0.4)
                    * height
                    * 0.06,
                )
                for x in range(0, width + 1, max(1, width // 150))
            ]
            draw.line(points, fill=line, width=max(1, round(height * 0.002)))
    return image


def text_image(item, width, height, visible_words=None, visible_characters=None):
    """Render the full resting layout, masking unrevealed words without reflow.

    visible_words counts whitespace-delimited words, matching the browser reveal.
    visible_characters counts original Unicode codepoints, including whitespace.
    None (or all characters/words) retains the full raster, alignment and wrapping.
    """
    box = Image.new("RGBA", (width, height))
    font = ImageFont.truetype(
        font_path(item.get("bold", False), item.get("font_family", "sans")),
        max(8, round(item.get("font_size", 0.06) * height / item["h"])),
    )
    draw = ImageDraw.Draw(box)
    lines = []
    for paragraph in item["text"].split("\n"):
        current = ""
        for word in paragraph.split(" "):
            candidate = (current + " " + word).strip()
            if current and draw.textlength(candidate, font=font) > width - 8:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    y = 0
    source_offset = 0
    for line in lines:
        length = draw.textlength(line, font=font)
        align = item.get("align", "left")
        x = (
            max(0, (width - length) / 2)
            if align == "center"
            else max(0, width - length - 4)
            if align == "right"
            else 4
        )
        if visible_characters is not None:
            # Resting layout can collapse repeated spaces. Map its retained
            # codepoints in order rather than searching for a normalised line;
            # discarded spaces/newlines must still consume reveal steps.
            source_indices = []
            for char in line:
                source_index = item["text"].find(char, source_offset)
                source_indices.append(source_index)
                source_offset = source_index + 1
            count = sum(index < visible_characters for index in source_indices)
            if count:
                layer = Image.new("RGBA", box.size)
                ImageDraw.Draw(layer).text(
                    (x, y), line, font=font, fill=item["color"], anchor="lt"
                )
                if count < len(line):
                    cutoff = round(x + draw.textlength(line[:count], font=font))
                    alpha = layer.getchannel("A")
                    alpha.paste(0, (min(width, max(0, cutoff)), 0, width, height))
                    layer.putalpha(alpha)
                box.alpha_composite(layer)
        elif visible_words is None:
            draw.text((x, y), line, font=font, fill=item["color"], anchor="lt")
        else:
            words = list(re.finditer(r"\S+", line))
            count = min(len(words), max(0, visible_words))
            if count:
                # Draw the original line to preserve kerning and anchor height;
                # mask in the separating whitespace, never reposition glyphs.
                layer = Image.new("RGBA", box.size)
                ImageDraw.Draw(layer).text(
                    (x, y), line, font=font, fill=item["color"], anchor="lt"
                )
                if count < len(words):
                    end = words[count - 1].end()
                    next_start = words[count].start()
                    cutoff = round(
                        x
                        + (
                            draw.textlength(line[:end], font=font)
                            + draw.textlength(line[:next_start], font=font)
                        )
                        / 2
                    )
                    alpha = layer.getchannel("A")
                    alpha.paste(0, (min(width, max(0, cutoff)), 0, width, height))
                    layer.putalpha(alpha)
                box.alpha_composite(layer)
            visible_words -= len(words)
        y += round(font.size * 1.25)
    return box


def chart_image(item, width, height):
    """Resting chart uses the same SVG-coordinate renderer as its entrance."""
    return chart_animation_image(item, width, height, 1)


@lru_cache(maxsize=1)
def chart_font():
    return ImageFont.truetype(font_path(), 13)


def chart_animation_image(item, width, height, progress):
    """Draw actual data in the browser's 400×240 viewport, never tween values.

    Progress is absolute and clamped, making out-of-order video seeks stateless.
    Pillow's clockwise pie angles start at the right, matching SVG arc geometry.
    """
    progress = min(1.0, max(0.0, progress))
    image = Image.new("RGBA", (400, 240))
    if progress == 0:
        return image.resize((width, height), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(image)
    values, labels = item["values"], item["labels"]
    count = len(values)
    col = colour(item["color"])
    kind = item.get("chart_type", "bar")
    font = chart_font()
    if kind in ("pie", "doughnut"):
        total = sum(values)
        if min(values) < 0 or total <= 0:
            raise ValueError(
                "Pie charts require nonnegative values and a positive total."
            )
        angle = 0.0
        percentages = []
        for index, value in enumerate(values):
            end = angle + value / total * 360
            revealed_end = min(end, progress * 360)
            if revealed_end > angle:
                draw.pieslice(
                    (115, 15, 285, 185),
                    angle,
                    revealed_end,
                    fill=(*col, round(255 * (1 - index * 0.08))),
                )
            if value > 0 and progress >= end / 360:
                middle = math.radians((angle + end) / 2)
                percentages.append(
                    (
                        200 + 60 * math.cos(middle),
                        100 + 60 * math.sin(middle),
                        f"{math.floor(value / total * 100 + 0.5)}%",
                    )
                )
            angle = end
        if kind == "doughnut":
            draw.ellipse((152, 52, 248, 148), fill=(0, 0, 0, 0))
        for x, y, label in percentages:
            draw.text((x, y), label, font=font, fill="#191925", anchor="mm")
    else:
        low, high = min(0, *values), max(0, *values)
        span = high - low or 1
        baseline = 190 - (0 - low) / span * 160
        points = [
            (50 + i * 330 / count, 190 - (v - low) / span * 160)
            for i, v in enumerate(values)
        ]
        if kind in ("line", "area"):
            segment_progress = progress * (count - 1)
            completed = math.floor(segment_progress)
            revealed = points[: completed + 1]
            if completed < count - 1:
                start, end = points[completed], points[completed + 1]
                fraction = segment_progress - completed
                revealed.append(
                    (
                        start[0] + (end[0] - start[0]) * fraction,
                        start[1] + (end[1] - start[1]) * fraction,
                    )
                )
            if len(revealed) > 1:
                if kind == "area":
                    draw.polygon(
                        revealed
                        + [(revealed[-1][0], baseline), (revealed[0][0], baseline)],
                        fill=(*col, 77),
                    )
                draw.line(revealed, fill=col, width=3)
            for index, (x, y) in enumerate(points):
                dot_progress = min(
                    1, max(0, (progress - index / max(count - 1, 1)) / 0.12)
                )
                # The resting endpoint contains all full-size dots, including
                # the last dot whose scheduled growth starts at progress 1.
                radius = 5 * (1 if progress == 1 else dot_progress)
                if radius > 0:
                    draw.ellipse(
                        (x - radius, y - radius, x + radius, y + radius), fill=col
                    )
        else:
            for index, value in enumerate(values):
                if value == 0:
                    continue
                if kind == "horizontal":
                    zero = 100 + (0 - low) / span * 280
                    end = zero + value / span * 280 * progress
                    y = 10 + index * 180 / count
                    draw.rectangle(
                        (min(zero, end), y, max(zero, end), y + 130 / count), fill=col
                    )
                else:
                    end = baseline - value / span * 160 * progress
                    x = 35 + index * 330 / count
                    draw.rectangle(
                        (x, min(baseline, end), x + 220 / count, max(baseline, end)),
                        fill=col,
                    )
    for index, label in enumerate(labels):
        x = 5 if kind == "horizontal" else 35 + index * 330 / count
        y = 30 + index * 180 / count if kind == "horizontal" else 222
        draw.text((x, y), label, font=font, fill=col, anchor="ls")
    return image.resize((width, height), Image.Resampling.LANCZOS)


@lru_cache(maxsize=1)
def vector_library():
    """Load original offline geometry also consumed by the browser editor."""
    return json.loads(VECTOR_LIBRARY_PATH.read_text(encoding="utf-8"))


def icon_primitives(kind):
    """Curated unit-box geometry, shared by raster and editable vector exports.

    New icons use an inset 0.08–0.92 box; the original six retain their geometry.
    Rings are outlines, never background coloured cutouts, so icons remain
    transparent on patterned backgrounds.
    """
    if kind not in ICONS:
        raise ValueError("Choose a supported icon.")
    library = vector_library()
    if kind in library:
        return library[kind]
    if kind == "check":
        return [("path", [(0.15, 0.5), (0.4, 0.75), (0.85, 0.25)], 0.12)]
    if kind == "arrow":
        return [
            (
                "polygon",
                [
                    (0.15, 0.1),
                    (0.45, 0.1),
                    (0.85, 0.5),
                    (0.45, 0.9),
                    (0.15, 0.9),
                    (0.55, 0.5),
                ],
                0,
            )
        ]
    if kind == "star":
        points = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            radius = 0.42 if index % 2 == 0 else 0.19
            points.append(
                (0.5 + radius * math.cos(angle), 0.5 + radius * math.sin(angle))
            )
        return [("polygon", points, 0)]
    if kind == "heart":
        # Sample the classic closed heart curve; export the same editable path.
        points = []
        for index in range(96):
            angle = index * 2 * math.pi / 96
            x = 16 * math.sin(angle) ** 3
            y = (
                13 * math.cos(angle)
                - 5 * math.cos(2 * angle)
                - 2 * math.cos(3 * angle)
                - math.cos(4 * angle)
            )
            points.append((0.5 + x / 40, 0.1 + (12 - y) * 0.8 / 29))
        return [("polygon", points, 0)]
    if kind == "info":
        return [
            ("ring", (0.14, 0.14, 0.86, 0.86), 0.08),
            ("oval", (0.45, 0.29, 0.55, 0.39), 0),
            ("path", [(0.5, 0.49), (0.5, 0.7)], 0.1),
        ]
    if kind == "target":
        return [
            ("ring", (0.14, 0.14, 0.86, 0.86), 0.08),
            ("ring", (0.32, 0.32, 0.68, 0.68), 0.08),
            ("oval", (0.45, 0.45, 0.55, 0.55), 0),
        ]
    raise ValueError("Choose a supported icon.")


def icon_image(item, width, height):
    image = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(image)
    for kind, geometry, stroke in icon_primitives(item["icon"]):
        thickness = max(1, round(stroke * min(width, height)))
        if kind in ("polygon", "path"):
            points = [(x * (width - 1), y * (height - 1)) for x, y in geometry]
            if kind == "polygon":
                draw.polygon(points, fill=item["color"])
            else:
                draw.line(points, fill=item["color"], width=thickness, joint="curve")
                radius = thickness / 2
                for x, y in points:
                    draw.ellipse(
                        (x - radius, y - radius, x + radius, y + radius),
                        fill=item["color"],
                    )
        else:
            x1, y1, x2, y2 = cast(tuple[float, float, float, float], geometry)
            box = (
                x1 * (width - 1),
                y1 * (height - 1),
                x2 * (width - 1),
                y2 * (height - 1),
            )
            if kind == "oval":
                draw.ellipse(box, fill=item["color"])
            else:
                # Pillow outlines are inside the box; PPTX strokes are centred.
                inset = thickness / 2
                draw.ellipse(
                    (box[0] - inset, box[1] - inset, box[2] + inset, box[3] + inset),
                    outline=item["color"],
                    width=thickness,
                )
    return image


def export_icon(slide, item, x, y, width, height, color):
    """Keep compound icons grouped and all geometry native/editable in PPTX."""
    from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
    from pptx.util import Emu

    group = slide.shapes.add_group_shape()
    group.name = item["id"]
    shapes = group.shapes
    bounds = shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, width, height)
    bounds.fill.background()
    bounds.line.fill.background()
    for kind, geometry, stroke in icon_primitives(item["icon"]):
        thickness = round(stroke * min(width, height))
        if kind == "polygon":
            points = [
                (round(x + px * width), round(y + py * height)) for px, py in geometry
            ]
            builder = shapes.build_freeform(*points[0])
            builder.add_line_segments(points[1:], close=True)
            shape = builder.convert_to_shape()
            shape.fill.solid()
            shape.fill.fore_color.rgb = color
            shape.line.fill.background()
        elif kind == "path":
            points = [
                (round(x + px * width), round(y + py * height)) for px, py in geometry
            ]
            for start, end in zip(points, points[1:]):
                shape = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, *start, *end)
                shape.line.color.rgb = color
                shape.line.width = Emu(thickness)
            for px, py in points:
                shape = shapes.add_shape(
                    MSO_SHAPE.OVAL,
                    round(px - thickness / 2),
                    round(py - thickness / 2),
                    thickness,
                    thickness,
                )
                shape.fill.solid()
                shape.fill.fore_color.rgb = color
                shape.line.fill.background()
        else:
            x1, y1, x2, y2 = cast(tuple[float, float, float, float], geometry)
            shape = shapes.add_shape(
                MSO_SHAPE.OVAL,
                round(x + x1 * width),
                round(y + y1 * height),
                round((x2 - x1) * width),
                round((y2 - y1) * height),
            )
            if kind == "ring":
                shape.fill.background()
                shape.line.color.rgb = color
                shape.line.width = Emu(thickness)
            else:
                shape.fill.solid()
                shape.fill.fore_color.rgb = color
                shape.line.fill.background()
    return group


def element_images(scene, width, height):
    result = []
    for item in scene["elements"]:
        w, h = max(1, round(item["w"] * width)), max(1, round(item["h"] * height))
        if item["type"] == "text":
            image = text_image(item, w, h)
        elif item["type"] == "chart":
            image = chart_image(item, w, h)
        elif item["type"] == "image":
            image = raster_image(item, w, h)
        elif item["type"] == "icon":
            image = icon_image(item, w, h)
        else:
            image = Image.new("RGBA", (w, h))
            draw = ImageDraw.Draw(image)
            if item.get("shape", "rect") == "ellipse":
                draw.ellipse((0, 0, w - 1, h - 1), fill=item["color"])
            elif item.get("shape") == "rounded":
                draw.rounded_rectangle(
                    (0, 0, w - 1, h - 1), radius=min(w, h) // 5, fill=item["color"]
                )
            elif item.get("shape") == "triangle":
                draw.polygon(
                    [(w // 2, 0), (w - 1, h - 1), (0, h - 1)], fill=item["color"]
                )
            elif item.get("shape") == "arrow":
                draw.polygon(
                    [
                        (0, h // 3),
                        (w * 2 // 3, h // 3),
                        (w * 2 // 3, 0),
                        (w - 1, h // 2),
                        (w * 2 // 3, h - 1),
                        (w * 2 // 3, h * 2 // 3),
                        (0, h * 2 // 3),
                    ],
                    fill=item["color"],
                )
            else:
                draw.rectangle((0, 0, w, h), fill=item["color"])
        result.append((image, round(item["x"] * width), round(item["y"] * height)))
    return result


def build_clip(scene, width, height):
    overlays = element_images(scene, width, height)
    word_frames = [{} for _ in scene["elements"]]

    def frame(t):
        image = background_frame(scene.get("background", {}), width, height, t)
        for item, (overlay, x, y), cache in zip(
            scene["elements"], overlays, word_frames
        ):
            state = motion_state(item, t)
            progress = reveal_progress(item, t)
            if state["opacity"] == 0 or progress == 0:
                continue
            effect = item.get("animation", {}).get("effect")
            if effect == "words" and progress < 1:
                count = math.floor(progress * len(item["text"].split()))
                if count not in cache:
                    cache[count] = text_image(item, *overlay.size, visible_words=count)
                overlay = cache[count]
            elif effect == "characters" and progress < 1:
                count = math.floor(progress * len(item["text"]))
                if count not in cache:
                    cache[count] = text_image(
                        item, *overlay.size, visible_characters=count
                    )
                overlay = cache[count]
            elif effect == "chart-draw" and progress < 1:
                overlay = chart_animation_image(item, *overlay.size, progress)
            elif effect == "wipe" and progress < 1:
                overlay = overlay.copy()
                alpha = overlay.getchannel("A")
                alpha.paste(
                    0,
                    (
                        math.floor(progress * overlay.width),
                        0,
                        overlay.width,
                        overlay.height,
                    ),
                )
                overlay.putalpha(alpha)
            if state["scale"] != 1:
                original_width, original_height = overlay.size
                overlay = overlay.resize(
                    (
                        max(1, round(original_width * state["scale"])),
                        max(1, round(original_height * state["scale"])),
                    ),
                    Image.Resampling.LANCZOS,
                )
                x += (original_width - overlay.width) / 2
                y += (original_height - overlay.height) / 2
            x += state["dx"] * width
            y += state["dy"] * height
            if state["opacity"] != 1:
                overlay = overlay.copy()
                overlay.putalpha(
                    overlay.getchannel("A").point(
                        lambda alpha: round(alpha * state["opacity"])
                    )
                )
            image.paste(overlay, (round(x), round(y)), overlay)
        return np.asarray(image)

    return VideoClip(frame_function=frame)


def build_timeline(clips, scenes, width, height):
    """Keep scene durations intact; outgoing transitions occupy the next scene.

    Scene transition objects are validated at the project boundary. MoviePy's
    concatenation overlap shortens duration, so sample a frozen outgoing endpoint
    and the incoming scene's actual local time instead. Legacy strings are cuts.
    """
    from bisect import bisect_right

    if not clips or len(clips) != len(scenes):
        raise ValueError("Supply one clip per scene on a nonempty timeline.")
    boundaries = [0.0]
    for clip in clips:
        if (
            clip.duration is None
            or not math.isfinite(clip.duration)
            or clip.duration <= 0
        ):
            raise ValueError("Timeline clips need finite positive durations.")
        boundaries.append(boundaries[-1] + clip.duration)

    def frame(t):
        t = min(max(t, 0.0), np.nextafter(boundaries[-1], 0.0))
        index = min(bisect_right(boundaries, t) - 1, len(clips) - 1)
        local_t = t - boundaries[index]
        incoming = Image.fromarray(
            np.asarray(clips[index].get_frame(local_t), dtype=np.uint8)
        ).convert("RGB")
        transition = scenes[index - 1].get("transition") if index else None
        if not isinstance(transition, dict) or local_t >= transition["duration"]:
            return np.asarray(incoming)
        progress = local_t / transition["duration"]
        previous = clips[index - 1]
        outgoing = Image.fromarray(
            np.asarray(
                previous.get_frame(np.nextafter(previous.duration, 0.0)), dtype=np.uint8
            )
        ).convert("RGB")
        if transition["effect"] == "crossfade":
            image = Image.blend(outgoing, incoming, progress)
        elif transition["effect"] == "slide-left":
            offset = round(width * progress)
            image = Image.new("RGB", (width, height))
            image.paste(outgoing, (-offset, 0))
            image.paste(incoming, (width - offset, 0))
        else:
            raise ValueError("Unsupported scene transition effect.")
        return np.asarray(image)

    return VideoClip(frame_function=frame, duration=boundaries[-1])


def export_slide(slide, scene, width, height):
    """Export editable resting poses; v1 element motion has no native PPTX animation."""
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Pt

    for item in scene["elements"]:
        x, y, w, h = [
            Emu(round(item[k] * dimension))
            for k, dimension in [
                ("x", width),
                ("y", height),
                ("w", width),
                ("h", height),
            ]
        ]
        color = RGBColor(*colour(item["color"]))
        if item["type"] == "text":
            shape = slide.shapes.add_textbox(x, y, w, h)
            tf = shape.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            for i, line in enumerate(item["text"].split("\n")):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = line
                p.alignment = {
                    "left": PP_ALIGN.LEFT,
                    "center": PP_ALIGN.CENTER,
                    "right": PP_ALIGN.RIGHT,
                }[item.get("align", "left")]
                p.font.name = FONT_FAMILIES[item.get("font_family", "sans")]
                p.font.size = Pt(item.get("font_size", 0.06) * height / 12700)
                p.font.bold = item.get("bold", False)
                p.font.color.rgb = color
        elif item["type"] == "image":
            # EMUs -> pixels at 96 dpi; fitting preserves the element's exact box.
            raster = raster_image(item, max(1, round(w / 9525)), max(1, round(h / 9525)))
            stream = BytesIO()
            raster.save(stream, format="PNG")
            stream.seek(0)
            picture = slide.shapes.add_picture(stream, x, y, w, h)
            picture.name = item["id"]
            picture._element.nvPicPr.cNvPr.set("descr", item.get("alt", ""))
        elif item["type"] == "icon":
            export_icon(slide, item, x, y, w, h, color)
        elif item["type"] == "shape":
            shape = slide.shapes.add_shape(
                {
                    "ellipse": MSO_SHAPE.OVAL,
                    "rect": MSO_SHAPE.RECTANGLE,
                    "rounded": MSO_SHAPE.ROUNDED_RECTANGLE,
                    "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
                    "arrow": MSO_SHAPE.RIGHT_ARROW,
                }[item.get("shape", "rect")],
                x,
                y,
                w,
                h,
            )
            shape.fill.solid()
            shape.fill.fore_color.rgb = color
            shape.line.fill.background()
        else:
            data = CategoryChartData()
            data.categories = item["labels"]
            data.add_series("Values", item["values"])
            kind = {
                "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
                "line": XL_CHART_TYPE.LINE,
                "horizontal": XL_CHART_TYPE.BAR_CLUSTERED,
                "area": XL_CHART_TYPE.AREA,
                "doughnut": XL_CHART_TYPE.DOUGHNUT,
                "pie": XL_CHART_TYPE.PIE,
            }[item.get("chart_type", "bar")]
            chart = slide.shapes.add_chart(kind, x, y, w, h, data).chart
            chart.has_legend = False
            chart.chart_style = 10
            chart.series[0].format.fill.solid()
            chart.series[0].format.fill.fore_color.rgb = color
            chart.series[0].format.line.color.rgb = color
