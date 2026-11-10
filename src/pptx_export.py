"""build a pptx from the spec and scene assets, with narration on each slide

charts stay editable by default, with the existing png available as an opt-out
slides use the original data and assets rather than frames from the video
"""
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.fill import FillFormat
from pptx.dml.line import LineFormat
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Emu, Inches, Pt

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
# bar means vertical columns here, matching the existing video charts
CHART_TYPES = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
               "line": XL_CHART_TYPE.LINE_MARKERS,
               "pie": XL_CHART_TYPE.PIE}


def _rgb(hex_color: str) -> RGBColor:
    """turn a hex colour from the spec into a colour powerpoint can use"""
    h = hex_color.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _chart_background(element, color):
    """set the background of either the whole chart or its plotting area"""
    # chart and plot backgrounds need explicit fills to avoid a white box
    # python-pptx has no public background setter for these two chart elements
    props = OxmlElement("c:spPr")
    # powerpoint expects these appearance settings in a specific xml order
    element.insert_element_before(props, "c:txPr", "c:externalData",
                                  "c:printSettings", "c:userShapes", "c:extLst")
    fill = FillFormat.from_fill_parent(props)
    fill.solid()
    fill.fore_color.rgb = color
    # remove the outline so the chart blends into the slide
    LineFormat(props).fill.background()


def _add_native_chart(slide, scene, bg, fg, accent):
    """add an editable chart using the scene data and the slide's colours"""
    # every category needs a value so the chart and its workbook stay in sync
    labels, values = scene["labels"], scene["values"]
    if not labels or len(labels) != len(values):
        raise ValueError("Native charts need matching, non-empty labels and values")
    data = CategoryChartData()
    data.categories = labels
    # the series name becomes the column heading in the embedded spreadsheet
    data.add_series(scene.get("y_label") or scene.get("heading") or "Values", values)
    stype = scene.get("chart_type", "bar")
    # category data also creates an embedded workbook for powerpoint's edit data action
    chart = slide.shapes.add_chart(
        CHART_TYPES[stype], Inches(0.8), Inches(0.8),
        SLIDE_W - Inches(1.6), SLIDE_H - Inches(1.6), data,
    ).chart
    # colour both backgrounds since changing just the slide does not colour the chart
    _chart_background(chart.element, bg)
    _chart_background(chart.element.chart.plotArea, bg)
    chart.font.color.rgb = fg
    chart.font.size = Pt(16)
    # leave the title out when the scene has no heading
    chart.has_title = bool(scene.get("heading"))
    if chart.has_title:
        chart.chart_title.text_frame.text = scene["heading"]
        font = chart.chart_title.text_frame.paragraphs[0].font
        font.color.rgb, font.size, font.bold = fg, Pt(24), True
    series = chart.series[0]
    # a series is the set of values drawn as bars, a line or pie slices
    series.format.fill.solid()
    series.format.fill.fore_color.rgb = accent
    series.format.line.color.rgb = accent
    plot = chart.plots[0]
    chart.has_legend = stype == "pie"
    if stype == "pie":
        # pie charts have no axes, so the legend identifies the categories
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.color.rgb = fg
        chart.legend.font.size = Pt(14)
        # use the existing palette so neighbouring slices remain distinguishable
        palette = (accent, fg, RGBColor(136, 136, 136))
        for i, point in enumerate(series.points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = palette[i % len(palette)]
            point.format.line.color.rgb = bg
        # put percentages outside the slices so they stay readable on every colour
        plot.has_data_labels = True
        plot.data_labels.show_percentage = True
        plot.data_labels.show_value = False
        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        plot.data_labels.number_format = "0%"
        plot.data_labels.font.color.rgb = fg
        plot.data_labels.font.size = Pt(14)
    else:
        plot.vary_by_categories = False
        # axis labels and gridlines need to stay legible on dark slides too
        for axis in (chart.category_axis, chart.value_axis):
            axis.tick_labels.font.color.rgb = fg
            axis.tick_labels.font.size = Pt(16)
            axis.format.line.color.rgb = fg
        chart.value_axis.has_major_gridlines = True
        chart.value_axis.major_gridlines.format.line.color.rgb = fg
        chart.value_axis.major_gridlines.format.line.width = Pt(0.5)
        chart.value_axis.has_title = bool(scene.get("y_label"))
        if chart.value_axis.has_title:
            chart.value_axis.axis_title.text_frame.text = scene["y_label"]
            font = chart.value_axis.axis_title.text_frame.paragraphs[0].font
            font.color.rgb, font.size = fg, Pt(16)
        if stype == "line":
            # make the line and its data points visible against the slide background
            series.format.line.width = Pt(3)
            series.marker.size = 7
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = accent
            series.marker.format.line.color.rgb = accent


def build_pptx(spec: dict, scene_artifacts: list, output_path: str):
    """build and save the deck using the spec and each scene's prepared files

    scene_artifacts holds optional narration_path, chart_png, image_png,
    bg_image_png and scrim entries in the same order as the timeline
    """
    # bg is the background, fg is the text colour and accent colours the chart series
    theme = spec.get("theme", {})
    bg = _rgb(theme.get("bg", "#0d1117"))
    fg = _rgb(theme.get("fg", "#f0f6fc"))
    accent = _rgb(theme.get("accent", "#58a6ff"))

    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H
    # use blank slides so a template does not add unwanted titles or placeholders
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
            # title and outro scenes keep their existing centred text layout
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
            # leave room beside the text when the slide has an image panel
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
            # only the powerpoint output uses this setting, the video keeps its png
            mode = scene.get("pptx_chart", "native")
            if mode == "native" and scene.get("chart_type", "bar") in CHART_TYPES:
                _add_native_chart(slide, scene, bg, fg, accent)
            else:
                # keep the image route for an explicit png choice or an unsupported type
                if mode == "native":
                    print(f"[warn] native chart type '{scene.get('chart_type')}' unsupported; using PNG")
                elif mode != "png":
                    raise ValueError(f"Unknown pptx_chart mode '{mode}'; use native or png")
                if not art.get("chart_png"):
                    raise ValueError("PNG chart export needs a chart_png artifact")
                slide.shapes.add_picture(
                    art["chart_png"],
                    left=Inches(0.8), top=Inches(0.8),
                    width=SLIDE_W - Inches(1.6),
                    height=SLIDE_H - Inches(1.6))
        elif stype == "image" and art.get("image_png"):
            # image scenes keep their existing full-slide picture and optional caption
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

        # embed narration audio on the slide
        if art.get("narration_path"):
            slide.shapes.add_movie(
                art["narration_path"],
                left=SLIDE_W - Inches(1.05), top=SLIDE_H - Inches(1.05),
                width=Inches(0.8), height=Inches(0.8),
                poster_frame_image=None, mime_type="audio/wav"
            )

    # save once after every slide and its narration have been added
    prs.save(output_path)
    return output_path
