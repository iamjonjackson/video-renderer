"""PPTX chart export: native editable charts, theming and PNG fallback."""

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pptx_export  # noqa: E402

THEME = {"bg": "#0d1117", "fg": "#f0f6fc", "accent": "#58a6ff"}


def chart_scene(**extra):
    scene = {"type": "chart", "chart_type": "bar", "heading": "MRR ($k)",
             "labels": ["Jul", "Aug", "Sep"], "values": [410, 455, 512]}
    scene.update(extra)
    return scene


class ChartExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.png = self.dir / "chart.png"
        Image.new("RGB", (64, 36), THEME["bg"]).save(self.png)

    def tearDown(self):
        self.tmp.cleanup()

    def export(self, scene):
        out = self.dir / "deck.pptx"
        log = StringIO()
        with redirect_stdout(log):
            pptx_export.build_pptx({"theme": THEME, "timeline": [scene]},
                                   [{"chart_png": str(self.png)}], str(out))
        return Presentation(str(out)).slides[0], log.getvalue()

    def charts(self, slide):
        return [s.chart for s in slide.shapes if s.has_chart]

    def pictures(self, slide):
        return [s for s in slide.shapes if s.shape_type == 13]  # PICTURE

    def test_bar_is_native_editable_chart(self):
        slide, _ = self.export(chart_scene())
        (chart,) = self.charts(slide)
        self.assertFalse(self.pictures(slide))
        self.assertEqual(chart.chart_type, XL_CHART_TYPE.COLUMN_CLUSTERED)
        self.assertEqual(list(chart.plots[0].categories), ["Jul", "Aug", "Sep"])
        self.assertEqual(list(chart.series[0].values), [410, 455, 512])
        self.assertEqual(chart.chart_title.text_frame.text, "MRR ($k)")
        # Embedded workbook is what makes "Edit Data" work in PowerPoint.
        self.assertIsNotNone(chart.part.chart_workbook.xlsx_part)

    def test_bar_follows_theme(self):
        slide, _ = self.export(chart_scene())
        (chart,) = self.charts(slide)
        fill = chart._chartSpace.find(qn("c:spPr")).find(".//" + qn("a:srgbClr"))
        self.assertEqual(fill.get("val"), "0D1117")
        self.assertEqual(chart.series[0].format.fill.fore_color.rgb,
                         RGBColor.from_string("58A6FF"))
        self.assertEqual(chart.category_axis.tick_labels.font.color.rgb,
                         RGBColor.from_string("F0F6FC"))

    def test_line_and_pie_are_native(self):
        slide, _ = self.export(chart_scene(chart_type="line", y_label="$k"))
        (line,) = self.charts(slide)
        self.assertEqual(line.chart_type, XL_CHART_TYPE.LINE_MARKERS)
        self.assertEqual(line.series[0].format.line.color.rgb,
                         RGBColor.from_string("58A6FF"))
        self.assertEqual(line.value_axis.axis_title.text_frame.text, "$k")

        slide, _ = self.export(chart_scene(chart_type="pie"))
        (pie,) = self.charts(slide)
        self.assertEqual(pie.chart_type, XL_CHART_TYPE.PIE)
        self.assertEqual(pie.series[0].points[0].format.fill.fore_color.rgb,
                         RGBColor.from_string("58A6FF"))

    def test_image_option_keeps_png(self):
        slide, _ = self.export(chart_scene(pptx_chart="image"))
        self.assertFalse(self.charts(slide))
        self.assertEqual(len(self.pictures(slide)), 1)

    def test_native_failure_falls_back_to_png_with_warning(self):
        slide, log = self.export(chart_scene(values=[1, 2]))  # labels/values mismatch
        self.assertFalse(self.charts(slide))
        self.assertEqual(len(self.pictures(slide)), 1)
        self.assertIn("[warn] native pptx chart failed", log)

    def test_unknown_chart_type_falls_back_to_png_with_warning(self):
        slide, log = self.export(chart_scene(chart_type="scatter"))
        self.assertEqual(len(self.pictures(slide)), 1)
        self.assertIn("no native pptx chart for chart_type 'scatter'", log)


if __name__ == "__main__":
    unittest.main()
