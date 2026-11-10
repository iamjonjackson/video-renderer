"""Deterministic, transparent brand marks generated from a video spec."""
import json
import math
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from themes.presets import COLOR_SCHEMES

PALETTES = {
    name: {"primary": colors["accent"], "secondary": colors["secondary"], "text": colors["fg"]}
    for name, colors in COLOR_SCHEMES.items()
}
STYLES = ("orbit", "spark", "petal")


def validate_generated(config):
    if not isinstance(config, dict):
        raise ValueError("branding.generated must be an object")
    for key, maximum in (("name", 32), ("tagline", 48)):
        value = config.get(key, "")
        if (not isinstance(value, str) or len(value) > maximum
                or "\n" in value or "\r" in value
                or (key == "name" and not value.strip())):
            raise ValueError(f"branding.generated.{key} must be a single line (1–{maximum} characters for name)")
    if not isinstance(config.get("style", "orbit"), str) or config.get("style", "orbit") not in STYLES:
        raise ValueError(f"branding.generated.style must be one of {STYLES}")
    if not isinstance(config.get("palette", "blue"), str) or config.get("palette", "blue") not in PALETTES:
        raise ValueError(f"branding.generated.palette must be one of {tuple(PALETTES)}")
    colors = config.get("colors", {})
    if (not isinstance(colors, dict) or any(
            key not in ("primary", "secondary", "text")
            or not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            for key, value in colors.items())):
        raise ValueError("branding.generated.colors accepts primary, secondary, text as #RRGGBB")


@lru_cache(maxsize=32)
def generated_logo(config_json, font_path):
    """Return RGBA pixels, supersampled for smooth small watermarks."""
    config = json.loads(config_json)
    colors = {**PALETTES[config.get("palette", "blue")], **config.get("colors", {})}
    font = ImageFont.truetype(font_path, 84)
    small = ImageFont.truetype(font_path, 25)
    name, tagline = config["name"], config.get("tagline", "")
    name_width = font.getlength(name)
    tagline_width = small.getlength(tagline)
    width = 280 + math.ceil(max(name_width, tagline_width)) + 20
    factor = 3
    mark = Image.new("RGBA", (240*factor, 240*factor))
    draw = ImageDraw.Draw(mark)
    def polygon(points, fill):
        draw.polygon([(round(x*factor), round(y*factor)) for x, y in points], fill=fill)
    def ellipse(box, **kwargs):
        draw.ellipse(tuple(round(v*factor) for v in box), **kwargs)
    primary, secondary = colors["primary"], colors["secondary"]
    style = config.get("style", "orbit")
    if style == "orbit":
        # Broken orbital rings, a tilted trajectory and a satellite.
        draw.arc((22*factor, 22*factor, 218*factor, 218*factor), 30, 302,
                 fill=primary, width=17*factor)
        draw.arc((58*factor, 58*factor, 182*factor, 182*factor), 210, 490,
                 fill=secondary, width=12*factor)
        polygon([(66, 161), (130, 63), (174, 90), (110, 188)], primary)
        ellipse((179, 25, 213, 59), fill=secondary)
    elif style == "spark":
        polygon([(120, 12), (146, 85), (218, 120), (146, 146),
                 (120, 224), (91, 148), (18, 120), (91, 91)], primary)
        polygon([(120, 62), (136, 104), (179, 120), (136, 136),
                 (120, 180), (104, 136), (62, 120), (104, 104)], secondary)
        ellipse((191, 26, 215, 50), fill=secondary)
    else:
        # Four overlapping leaves with a transparent diamond at their centre.
        for box, color in [((27, 27, 125, 125), primary), ((115, 27, 213, 125), secondary),
                           ((115, 115, 213, 213), primary), ((27, 115, 125, 213), secondary)]:
            ellipse(box, fill=color)
        polygon([(120, 93), (147, 120), (120, 147), (93, 120)], (0, 0, 0, 0))
    canvas = Image.new("RGBA", (width*factor, 240*factor))
    canvas.alpha_composite(mark)
    draw = ImageDraw.Draw(canvas)
    name_font = ImageFont.truetype(font_path, 84*factor)
    tag_font = ImageFont.truetype(font_path, 25*factor)
    draw.text((280*factor, (64 if tagline else 78)*factor), name,
              font=name_font, fill=colors["text"], anchor="lt")
    if tagline:
        draw.text((282*factor, 164*factor), tagline, font=tag_font,
                  fill=secondary, anchor="lt")
    return np.array(canvas.resize((width, 240), Image.Resampling.LANCZOS))
