"""Build a .pptx from the render artifacts: one slide per scene, with each
scene's narration clip (WAV or MP3) embedded on its slide.

Built from the individual artifacts (spec, narration clips, chart PNGs,
generated scene images) — never from the rendered video. Chart scenes become
native, editable PowerPoint charts; the chart PNG is the fallback.
"""

import wave
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_MARKER_STYLE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Main-sequence "play" command, as PowerPoint writes for audio set to
# Start: Automatically. python-pptx only emits the click-to-play media node.
_AUTOPLAY_SEQ = (
    '<p:seq xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
    ' concurrent="1" nextAc="seek">'
    '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
    '<p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>'
    '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
    '<p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0"'
    ' fill="hold" nodeType="afterEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
    '<p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr>'
    '<p:cTn id="6" dur="{dur}" fill="hold"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
    "</p:cBhvr></p:cmd>"
    "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>"
    "</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn>"
    '<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
    '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst>'
    "</p:seq>"
)


_AUDIO_MIME = {".wav": "audio/wav", ".mp3": "audio/mpeg"}


def _audio_mime(path: str) -> str:
    """MIME type for embedded narration (WAV from Mistral/Google, MP3 from ElevenLabs)."""
    return _AUDIO_MIME.get(Path(path).suffix.lower(), "audio/wav")


def _audio_ms(path: str) -> int:
    if Path(path).suffix.lower() == ".wav":
        with wave.open(path) as w:
            return max(1, round(w.getnframes() * 1000 / w.getframerate()))
    from moviepy import AudioFileClip  # compressed formats: decode like the video path

    with AudioFileClip(path) as clip:
        return max(1, round(clip.duration * 1000))


def _autoplay(slide, media_shape, audio_path: str):
    """Start the slide's narration when the slide opens."""
    root = slide._element.find(qn("p:timing")).find(".//" + qn("p:childTnLst"))
    seq = etree.fromstring(
        _AUTOPLAY_SEQ.format(dur=_audio_ms(audio_path), spid=media_shape.shape_id)
    )
    root.insert(0, seq)
    # Keep cTn ids unique: the media node python-pptx created follows the sequence.
    for i, ctn in enumerate(root.iter(qn("p:cTn")), start=2):
        ctn.set("id", str(i))


def _rgb(hex_color: str) -> RGBColor:
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _blend(fg: str, bg: str, alpha: float) -> RGBColor:
    """`fg` drawn at `alpha` opacity over `bg`, for faint gridlines."""
    f, b = _rgb(fg), _rgb(bg)
    return RGBColor(*(round(f[i] * alpha + b[i] * (1 - alpha)) for i in range(3)))


_NATIVE_CHART_TYPES = {
    "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
    "line": XL_CHART_TYPE.LINE_MARKERS,
    "pie": XL_CHART_TYPE.PIE,
}


def _fill_chart_space(chart, hex_color: str):
    """Solid chart-area fill. python-pptx has no API for it, and without one
    PowerPoint draws a white chart area on the dark slide."""
    sp_pr = etree.fromstring(
        f'<c:spPr xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"'
        f' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f'<a:solidFill><a:srgbClr val="{hex_color.lstrip("#").upper()}"/></a:solidFill>'
        f'<a:ln><a:noFill/></a:ln></c:spPr>')
    space = chart._chartSpace
    old = space.find(qn("c:spPr"))
    if old is not None:
        space.remove(old)
    space.find(qn("c:chart")).addnext(sp_pr)


def _add_native_chart(slide, scene: dict, theme: dict, x, y, cx, cy):
    """Editable PowerPoint chart from the scene's labels/values, themed like
    the matplotlib PNG used in the video."""
    kind = scene.get("chart_type", "bar")
    if len(scene["labels"]) != len(scene["values"]):
        raise ValueError("labels and values differ in length")
    data = CategoryChartData()
    data.categories = scene["labels"]
    data.add_series(scene.get("y_label") or scene.get("heading") or "Value",
                    scene["values"])
    frame = slide.shapes.add_chart(_NATIVE_CHART_TYPES[kind], x, y, cx, cy, data)
    try:
        _style_chart(frame.chart, scene, theme)
    except Exception:
        # Don't leave a half-styled chart under the fallback PNG.
        frame._element.getparent().remove(frame._element)
        raise


def _style_chart(chart, scene: dict, theme: dict):
    kind = scene.get("chart_type", "bar")
    bg, fg, accent = theme["bg"], theme["fg"], theme["accent"]
    _fill_chart_space(chart, bg)
    chart.font.color.rgb = _rgb(fg)
    chart.font.size = Pt(16)
    chart.has_legend = False

    if scene.get("heading"):
        chart.has_title = True
        title = chart.chart_title.text_frame
        title.text = scene["heading"]
        title.paragraphs[0].runs[0].font.size = Pt(24)
        title.paragraphs[0].runs[0].font.color.rgb = _rgb(fg)
    else:
        chart.has_title = False

    plot = chart.plots[0]
    series = plot.series[0]
    if kind == "pie":
        # Same colour cycle as the matplotlib pie in the video.
        palette = [accent, fg, "#888888"]
        for i, point in enumerate(series.points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = _rgb(palette[i % len(palette)])
            point.format.line.color.rgb = _rgb(bg)
        plot.has_data_labels = True
        labels = plot.data_labels
        labels.show_category_name = True
        labels.show_percentage = True
        labels.show_value = False
        labels.number_format = "0%"
        labels.number_format_is_linked = False
        labels.position = XL_LABEL_POSITION.OUTSIDE_END
        return

    plot.vary_by_categories = False
    if kind == "bar":
        plot.gap_width = 80
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = _rgb(accent)
    else:
        series.smooth = False
        series.format.line.color.rgb = _rgb(accent)
        series.format.line.width = Pt(3.5)
        series.marker.style = XL_MARKER_STYLE.CIRCLE
        series.marker.size = 10
        series.marker.format.fill.solid()
        series.marker.format.fill.fore_color.rgb = _rgb(accent)
        series.marker.format.line.color.rgb = _rgb(accent)

    for axis in (chart.category_axis, chart.value_axis):
        axis.format.line.color.rgb = _rgb(fg)
        axis.tick_labels.font.color.rgb = _rgb(fg)
        axis.tick_labels.font.size = Pt(16)
    chart.value_axis.has_major_gridlines = True
    chart.value_axis.major_gridlines.format.line.color.rgb = _blend(fg, bg, 0.25)
    if scene.get("y_label"):
        chart.value_axis.has_title = True
        axis_title = chart.value_axis.axis_title.text_frame
        axis_title.text = scene["y_label"]
        axis_title.paragraphs[0].runs[0].font.size = Pt(16)
        axis_title.paragraphs[0].runs[0].font.color.rgb = _rgb(fg)


def _add_chart_scene(slide, scene: dict, art: dict, theme: dict):
    """Native chart by default; the matplotlib PNG when the scene asks for
    `"pptx_chart": "image"` or the native chart can't be built."""
    x, y = Inches(0.8), Inches(0.8)
    cx, cy = SLIDE_W - Inches(1.6), SLIDE_H - Inches(1.6)
    mode = scene.get("pptx_chart", "native")
    kind = scene.get("chart_type", "bar")
    if mode == "native":
        if kind not in _NATIVE_CHART_TYPES:
            print(f"[warn] no native pptx chart for chart_type '{kind}'; using PNG")
        else:
            try:
                _add_native_chart(slide, scene, theme, x, y, cx, cy)
                return
            except Exception as e:
                print(f"[warn] native pptx chart failed ({e}); using PNG")
    if art.get("chart_png"):
        slide.shapes.add_picture(art["chart_png"], left=x, top=y, width=cx, height=cy)


def build_pptx(spec: dict, scene_artifacts: list, output_path: str):
    """scene_artifacts: per-scene dicts with optional keys
    narration_path, chart_png, image_png, bg_image_png, scrim (0-1)."""
    theme = spec.get("theme", {})
    bg = _rgb(theme.get("bg", "#0d1117"))
    fg = _rgb(theme.get("fg", "#f0f6fc"))
    accent = _rgb(theme.get("accent", "#58a6ff"))
    chart_theme = {"bg": theme.get("bg", "#0d1117"), "fg": theme.get("fg", "#f0f6fc"),
                   "accent": theme.get("accent", "#58a6ff")}

    prs = Presentation()
    resolution = spec.get("meta", {}).get("resolution", {"width": 1920, "height": 1080})
    prs.slide_width = SLIDE_W
    prs.slide_height = Emu(round(SLIDE_W * resolution["height"] / resolution["width"]))
    blank = prs.slide_layouts[6]

    for scene, art in zip(spec["timeline"], scene_artifacts):
        slide = prs.slides.add_slide(blank)

        if scene["type"] == "composition":
            import composition

            if art.get("composition_background"):
                slide.shapes.add_picture(
                    art["composition_background"],
                    0,
                    0,
                    width=prs.slide_width,
                    height=prs.slide_height,
                )
            composition.export_slide(slide, scene, prs.slide_width, prs.slide_height)
            if scene.get("narration"):
                notes = slide.notes_slide.notes_text_frame
                if notes is not None:
                    notes.text = scene["narration"]
            if art.get("narration_path"):
                media = slide.shapes.add_movie(
                    art["narration_path"],
                    left=prs.slide_width - Inches(0.8),
                    top=prs.slide_height - Inches(0.8),
                    width=Inches(0.6),
                    height=Inches(0.6),
                    mime_type=_audio_mime(art["narration_path"]),
                )
                _autoplay(slide, media, art["narration_path"])
            continue

        # Legacy layout retains its original aspect ratio on a resized slide.
        # background fill (or faded image background)
        if art.get("bg_image_png"):
            slide.shapes.add_picture(
                art["bg_image_png"], 0, 0, width=SLIDE_W, height=SLIDE_H
            )
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
            tb = slide.shapes.add_textbox(
                Inches(1), Inches(2.6), SLIDE_W - Inches(2), Inches(1.5)
            )
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
            bb = slide.shapes.add_textbox(
                tx, Inches(1.9), text_w, SLIDE_H - Inches(2.6)
            )
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
                    left=SLIDE_W - Inches(5.4),
                    top=Inches(1.2),
                    width=Inches(4.8),
                    height=Inches(4.8),
                )
        elif stype == "chart":
            _add_chart_scene(slide, scene, art, chart_theme)
        elif stype == "image" and art.get("image_png"):
            slide.shapes.add_picture(
                art["image_png"], 0, 0, width=SLIDE_W, height=SLIDE_H
            )
            if scene.get("caption"):
                cb = slide.shapes.add_textbox(
                    Inches(1), SLIDE_H - Inches(1.1), SLIDE_W - Inches(2), Inches(0.7)
                )
                cp = cb.text_frame.paragraphs[0]
                cp.alignment = PP_ALIGN.CENTER
                cr = cp.add_run()
                cr.text = scene["caption"]
                cr.font.size = Pt(16)
                cr.font.color.rgb = fg

        # embed narration audio on the slide
        if art.get("narration_path"):
            media = slide.shapes.add_movie(
                art["narration_path"],
                left=SLIDE_W - Inches(1.05),
                top=SLIDE_H - Inches(1.05),
                width=Inches(0.8),
                height=Inches(0.8),
                poster_frame_image=None,
                mime_type=_audio_mime(art["narration_path"]),
            )
            _autoplay(slide, media, art["narration_path"])

        if (prs.slide_width, prs.slide_height) != (SLIDE_W, SLIDE_H):
            scale = min(prs.slide_width / SLIDE_W, prs.slide_height / SLIDE_H)
            dx, dy = (
                (prs.slide_width - SLIDE_W * scale) / 2,
                (prs.slide_height - SLIDE_H * scale) / 2,
            )
            for shape in slide.shapes:
                shape.left = Emu(round(dx + shape.left * scale))
                shape.top = Emu(round(dy + shape.top * scale))
                shape.width = Emu(round(shape.width * scale))
                shape.height = Emu(round(shape.height * scale))
                if shape.has_text_frame:
                    for paragraph in shape.text_frame.paragraphs:
                        for run in paragraph.runs:
                            if run.font.size is not None:
                                run.font.size = Emu(round(run.font.size * scale))

    prs.save(output_path)
    return output_path
