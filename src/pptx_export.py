"""Build a .pptx from the render artifacts: one slide per scene, with each
scene's narration WAV embedded on its slide.

Built from the individual artifacts (spec, narration clips, chart PNGs,
generated scene images) — never from the rendered video.
"""
import json
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def _rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


FRAME_W, FRAME_H = 1920, 1080  # video frame the branding spec is expressed in


def _branding_applies(branding, scene) -> bool:
    if not branding or not branding.get("logo"):
        return False
    scenes = branding.get("scenes", "all")
    return scenes == "all" or scene["type"] in scenes


def _add_logo(slide, branding):
    """Place the branding logo using the same rules as the video overlay:
    corner + margin + max_height (fractions/pixels of the 1920x1080 frame),
    PNG alpha kept, opacity applied as picture transparency."""
    from PIL import Image
    from pptx.oxml.ns import qn
    from lxml import etree

    logo_path = Path(branding["logo"])
    if not logo_path.exists():
        print(f"[warn] branding logo not found: {logo_path} — skipping on slides")
        return
    with Image.open(logo_path) as im:
        lw, lh = im.size
    margin = int(branding.get("margin", 40))
    max_h = FRAME_H * float(branding.get("max_height", 0.1))
    scale = min(max_h / lh, (FRAME_W - 2 * margin) / lw)
    w_px, h_px = lw * scale, lh * scale
    v, h = branding.get("position", "bottom-right").split("-")
    x_px = margin if h == "left" else FRAME_W - margin - w_px
    y_px = margin if v == "top" else FRAME_H - margin - h_px
    emu = SLIDE_W / FRAME_W  # EMU per frame pixel
    pic = slide.shapes.add_picture(str(logo_path), Emu(int(x_px * emu)),
                                   Emu(int(y_px * emu)),
                                   width=Emu(int(w_px * emu)),
                                   height=Emu(int(h_px * emu)))
    opacity = float(branding.get("opacity", 1.0))
    if opacity < 1.0:
        blip = pic._element.find(".//" + qn("a:blip"))
        mod = etree.SubElement(blip, qn("a:alphaModFix"))
        mod.set("amt", str(int(opacity * 100000)))


def build_pptx(spec: dict, scene_artifacts: list, output_path: str):
    """scene_artifacts: per-scene dicts with optional keys
    narration_path, chart_png, image_png, bg_image_png, scrim (0-1)."""
    theme = spec.get("theme", {})
    bg = _rgb(theme.get("bg", "#0d1117"))
    fg = _rgb(theme.get("fg", "#f0f6fc"))
    accent = _rgb(theme.get("accent", "#58a6ff"))

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    blank = prs.slide_layouts[6]

    for scene, art in zip(spec["timeline"], scene_artifacts):
        slide = prs.slides.add_slide(blank)

        # background fill (or faded image background)
        if art.get("bg_image_png"):
            slide.shapes.add_picture(art["bg_image_png"], 0, 0,
                                     width=SLIDE_W, height=SLIDE_H)
            scrim = art.get("scrim", 0.5)
            box = slide.shapes.add_shape(1, 0, 0, SLIDE_W, SLIDE_H)  # rectangle
            box.fill.solid()
            box.fill.fore_color.rgb = bg
            box.fill.transparency = 1.0 - scrim  # pptx: transparency of the fill
            box.line.fill.background()
        else:
            box = slide.shapes.add_shape(1, 0, 0, SLIDE_W, SLIDE_H)
            box.fill.solid()
            box.fill.fore_color.rgb = bg
            box.line.fill.background()

        stype = scene["type"]
        if stype in ("title", "outro"):
            tb = slide.shapes.add_textbox(Inches(1), Inches(2.6),
                                          SLIDE_W - Inches(2), Inches(1.5))
            tf = tb.text_frame
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = scene["text"]
            f = r.font
            f.size = Pt(scene.get("_title_pt", 44))
            f.bold = True
            f.color.rgb = accent if stype == "outro" else fg
            if scene.get("subtitle"):
                p2 = tf.add_paragraph()
                p2.alignment = PP_ALIGN.CENTER
                r2 = p2.add_run()
                r2.text = scene["subtitle"]
                r2.font.size = Pt(20)
                r2.font.color.rgb = accent
        elif stype == "bullets":
            has_panel = art.get("image_png")
            text_w = Inches(5.6) if has_panel else SLIDE_W - Inches(2.4)
            tx = Inches(1.2)
            if scene.get("heading"):
                hb = slide.shapes.add_textbox(tx, Inches(0.7), text_w, Inches(0.9))
                hp = hb.text_frame.paragraphs[0]
                hr = hp.add_run()
                hr.text = scene["heading"]
                hr.font.size = Pt(28)
                hr.font.bold = True
                hr.font.color.rgb = accent
            bb = slide.shapes.add_textbox(tx, Inches(1.9), text_w,
                                          SLIDE_H - Inches(2.6))
            btf = bb.text_frame
            for i, item in enumerate(scene.get("items", [])):
                p = btf.paragraphs[0] if i == 0 else btf.add_paragraph()
                p.alignment = PP_ALIGN.LEFT
                r = p.add_run()
                r.text = "\u2022 " + item
                r.font.size = Pt(18)
                r.font.color.rgb = fg
                p.space_after = Pt(12)
            if has_panel:
                slide.shapes.add_picture(
                    art["image_png"],
                    left=SLIDE_W - Inches(5.4), top=Inches(1.2),
                    width=Inches(4.8), height=Inches(4.8))
        elif stype == "chart":
            if art.get("chart_png"):
                slide.shapes.add_picture(
                    art["chart_png"],
                    left=Inches(0.8), top=Inches(0.8),
                    width=SLIDE_W - Inches(1.6),
                    height=SLIDE_H - Inches(1.6))
        elif stype == "image" and art.get("image_png"):
            slide.shapes.add_picture(art["image_png"], 0, 0,
                                     width=SLIDE_W, height=SLIDE_H)
            if scene.get("caption"):
                cb = slide.shapes.add_textbox(
                    Inches(1), SLIDE_H - Inches(1.1),
                    SLIDE_W - Inches(2), Inches(0.7))
                cp = cb.text_frame.paragraphs[0]
                cp.alignment = PP_ALIGN.CENTER
                cr = cp.add_run()
                cr.text = scene["caption"]
                cr.font.size = Pt(16)
                cr.font.color.rgb = fg

        branded = _branding_applies(spec.get("branding"), scene)
        if branded:
            _add_logo(slide, spec["branding"])

        # embed narration audio on the slide; keep its icon clear of a
        # bottom-right logo by moving it to the bottom-left corner
        if art.get("narration_path"):
            icon_left = SLIDE_W - Inches(1.05)
            if branded and spec["branding"].get("position", "bottom-right") == "bottom-right":
                icon_left = Inches(0.25)
            slide.shapes.add_movie(
                art["narration_path"],
                left=icon_left, top=SLIDE_H - Inches(1.05),
                width=Inches(0.8), height=Inches(0.8),
                poster_frame_image=None, mime_type="audio/wav"
            )

    prs.save(output_path)
    return output_path
