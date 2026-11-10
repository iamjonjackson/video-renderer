"""Normalised canvas elements shared by MoviePy and editable PowerPoint export."""

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from moviepy import VideoClip
from PIL import Image, ImageDraw, ImageFont

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


@lru_cache(maxsize=2)
def font_path(bold=False):
    import matplotlib

    path = (
        Path(matplotlib.__file__ or "").parent
        / "mpl-data/fonts/ttf"
        / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    )
    return str(path)


@lru_cache(maxsize=2)
def supported_codepoints(bold=False):
    with TTFont(font_path(bold)) as font:
        return frozenset(font.getBestCmap())


def check_glyphs(text, where, bold=False):
    unsupported = sorted(
        {
            ord(char)
            for char in text
            if char not in "\n\r\t" and ord(char) not in supported_codepoints(bold)
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
        ("type", "name", "elements", "background", "duration", "narration", "padding"),
        "Canvas scene",
    )
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
        ):
            raise ValueError(f"{where}: choose text, chart or shape.")
        common = ("id", "type", "x", "y", "w", "h", "color")
        fields = {
            "text": ("text", "font_size", "bold", "align"),
            "chart": ("chart_type", "labels", "values"),
            "shape": ("shape",),
        }
        object_fields(item, common + fields[item["type"]], where)
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
            text(item.get("text"), where, 600)
            number(item.get("font_size", 0.06), f"{where} font size", 0.02, 0.15)
            if not isinstance(item.get("bold", False), bool) or item.get(
                "align", "left"
            ) not in ("left", "center", "right"):
                raise ValueError(f"{where}: invalid text formatting.")
            check_glyphs(item["text"], where, item.get("bold", False))
        elif item["type"] == "shape":
            item.setdefault("shape", "rect")
            if item.get("shape", "rect") not in ("rect", "ellipse", "rounded", "triangle", "arrow"):
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


def text_image(item, width, height):
    box = Image.new("RGBA", (width, height))
    font = ImageFont.truetype(
        font_path(item.get("bold", False)),
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
        draw.text((x, y), line, font=font, fill=item["color"], anchor="lt")
        y += round(font.size * 1.25)
    return box


def chart_image(item, width, height):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    fig.patch.set_alpha(0)
    ax.set_facecolor("none")
    col = item["color"]
    labels = item["labels"]
    values = item["values"]
    kind = item.get("chart_type", "bar")
    if kind in ("pie", "doughnut"):
        ax.pie(
            values,
            wedgeprops={"width": 0.4} if kind == "doughnut" else {},
            labels=labels,
            textprops={"color": col, "fontsize": max(8, height / 35)},
            colors=[col, "#9990b8", "#746a8d", "#c3b6d9"],
        )
    elif kind in ("line", "area"):
        ax.plot(labels, values, color=col, marker="o")
        if kind == "area":
            ax.fill_between(range(len(values)), values, color=col, alpha=0.3)
    elif kind == "horizontal":
        ax.barh(labels, values, color=col)
    else:
        ax.bar(labels, values, color=col, width=0.6)
    if kind not in ("pie", "doughnut"):
        ax.tick_params(colors=col, labelsize=max(8, height / 35))
        ax.grid(axis="y", alpha=0.15, color=col)
        for spine in ax.spines.values():
            spine.set_color(col)
    fig.tight_layout(pad=1)
    fig.canvas.draw()
    result = Image.fromarray(np.asarray(fig.canvas.buffer_rgba()).copy()).resize((width, height))
    plt.close(fig)
    return result


def element_images(scene, width, height):
    result = []
    for item in scene["elements"]:
        w, h = max(1, round(item["w"] * width)), max(1, round(item["h"] * height))
        if item["type"] == "text":
            image = text_image(item, w, h)
        elif item["type"] == "chart":
            image = chart_image(item, w, h)
        else:
            image = Image.new("RGBA", (w, h))
            draw = ImageDraw.Draw(image)
            if item.get("shape", "rect") == "ellipse":
                draw.ellipse((0, 0, w - 1, h - 1), fill=item["color"])
            elif item.get("shape") == "rounded":
                draw.rounded_rectangle((0, 0, w-1, h-1), radius=min(w,h)//5, fill=item["color"])
            elif item.get("shape") == "triangle":
                draw.polygon([(w//2,0),(w-1,h-1),(0,h-1)],fill=item["color"])
            elif item.get("shape") == "arrow":
                draw.polygon([(0,h//3),(w*2//3,h//3),(w*2//3,0),(w-1,h//2),(w*2//3,h-1),(w*2//3,h*2//3),(0,h*2//3)],fill=item["color"])
            else:
                draw.rectangle((0, 0, w, h), fill=item["color"])
        result.append((image, round(item["x"] * width), round(item["y"] * height)))
    return result


def build_clip(scene, width, height):
    overlays = element_images(scene, width, height)

    def frame(t):
        image = background_frame(scene.get("background", {}), width, height, t)
        for overlay, x, y in overlays:
            image.paste(overlay, (x, y), overlay)
        return np.asarray(image)

    return VideoClip(frame_function=frame)


def export_slide(slide, scene, width, height):
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
                p.font.name = "DejaVu Sans"
                p.font.size = Pt(item.get("font_size", 0.06) * height / 12700)
                p.font.bold = item.get("bold", False)
                p.font.color.rgb = color
        elif item["type"] == "shape":
            shape = slide.shapes.add_shape(
                {"ellipse":MSO_SHAPE.OVAL,"rect":MSO_SHAPE.RECTANGLE,"rounded":MSO_SHAPE.ROUNDED_RECTANGLE,"triangle":MSO_SHAPE.ISOSCELES_TRIANGLE,"arrow":MSO_SHAPE.RIGHT_ARROW}[item.get("shape","rect")],
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
