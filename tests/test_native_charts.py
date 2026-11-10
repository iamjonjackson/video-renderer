"""check editable chart data, theme colours and the unchanged video path"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pptx_export


class NativeChartTests(unittest.TestCase):
    def setUp(self):
        """give each test a clean folder, a small chart and a dark theme"""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = {"type": "chart", "chart_type": "bar", "heading": "Quarterly revenue",
                      "y_label": "Revenue ($k)", "labels": ["Q1", "Q2", "Q3"],
                      "values": [410, 455.5, 512]}
        self.theme = {"bg": "#0d1117", "fg": "#f0f6fc", "accent": "#58a6ff"}

    def export(self, scene=None, artifacts=None, theme=None):
        """save a one-slide deck and reopen it to inspect what was actually written"""
        output = self.root / "deck.pptx"
        pptx_export.build_pptx({"theme": theme or self.theme, "timeline": [scene or self.scene]},
                               [artifacts or {}], str(output))
        return output, Presentation(output).slides[0]

    def test_all_supported_types_have_native_data_and_embedded_workbooks(self):
        """check each chart type and the spreadsheet behind its edit data action"""
        for kind, expected in (("bar", XL_CHART_TYPE.COLUMN_CLUSTERED),
                               ("line", XL_CHART_TYPE.LINE_MARKERS), ("pie", XL_CHART_TYPE.PIE)):
            with self.subTest(kind=kind):
                output, slide = self.export({**self.scene, "chart_type": kind})
                charts = [shape.chart for shape in slide.shapes if shape.has_chart]
                self.assertEqual(len(charts), 1)
                chart = charts[0]
                self.assertEqual(chart.chart_type, expected)
                self.assertEqual([c.label for c in chart.plots[0].categories], self.scene["labels"])
                self.assertEqual(list(chart.series[0].values), self.scene["values"])
                self.assertEqual(chart.chart_title.text_frame.text, self.scene["heading"])
                self.assertFalse(any(shape.shape_type == 13 for shape in slide.shapes))
                # inspect the actual workbook cells as well as the chart's cached values
                with ZipFile(output) as package:
                    workbooks = [name for name in package.namelist() if name.endswith(".xlsx")]
                    self.assertEqual(len(workbooks), 1)
                    with ZipFile(io.BytesIO(package.read(workbooks[0]))) as workbook:
                        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
                        strings = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                        shared = ["".join(item.itertext()) for item in strings.findall("s:si", ns)]
                        cells = {cell.attrib["r"]: (shared[int(cell.find("s:v", ns).text)]
                                 if cell.attrib.get("t") == "s" else float(cell.find("s:v", ns).text))
                                 for cell in sheet.findall(".//s:c", ns)}
                        self.assertEqual([cells[f"A{i}"] for i in (2, 3, 4)], self.scene["labels"])
                        self.assertEqual([cells[f"B{i}"] for i in (2, 3, 4)], self.scene["values"])

    def test_dark_and_light_chart_fills_and_text_follow_the_theme(self):
        """check that colours are saved explicitly rather than left to office defaults"""
        for theme in (self.theme, {"bg": "#ffffff", "fg": "#17212b", "accent": "#be3455"}):
            for kind in ("bar", "line", "pie"):
                _, slide = self.export({**self.scene, "chart_type": kind}, theme=theme)
                chart = next(shape.chart for shape in slide.shapes if shape.has_chart)
                self.assertEqual(chart.element.xpath("./c:spPr/a:solidFill/a:srgbClr")[0].get("val"), theme["bg"][1:].upper())
                self.assertEqual(chart.element.xpath("./c:chart/c:plotArea/c:spPr/a:solidFill/a:srgbClr")[0].get("val"), theme["bg"][1:].upper())
                self.assertEqual(str(chart.font.color.rgb), theme["fg"][1:].upper())
                self.assertEqual(str(chart.series[0].format.fill.fore_color.rgb), theme["accent"][1:].upper())
                if kind != "pie":
                    self.assertEqual(str(chart.value_axis.tick_labels.font.color.rgb), theme["fg"][1:].upper())
                    self.assertEqual(chart.value_axis.axis_title.text_frame.text, self.scene["y_label"])
                else:
                    self.assertTrue(chart.plots[0].data_labels.show_percentage)

    def test_png_option_keeps_the_original_image_and_dimensions(self):
        """check that the png choice still embeds the original picture at the same size"""
        png = self.root / "chart.png"
        Image.new("RGB", (100, 80), "navy").save(png)
        _, slide = self.export({**self.scene, "pptx_chart": "png"}, {"chart_png": str(png)})
        self.assertFalse(any(shape.has_chart for shape in slide.shapes))
        picture = next(shape for shape in slide.shapes if shape.shape_type == 13)
        self.assertEqual(picture.image.blob, png.read_bytes())
        self.assertEqual((picture.left, picture.top), (pptx_export.Inches(0.8),) * 2)
        self.assertEqual((picture.width, picture.height), (pptx_export.SLIDE_W - pptx_export.Inches(1.6),
                                                         pptx_export.SLIDE_H - pptx_export.Inches(1.6)))

    def test_unsupported_native_type_falls_back_with_a_warning(self):
        """check that an unsupported type uses its png and explains the fallback"""
        png = self.root / "chart.png"
        Image.new("RGB", (100, 80), "navy").save(png)
        with contextlib.redirect_stdout(io.StringIO()) as log:
            _, slide = self.export({**self.scene, "chart_type": "scatter"}, {"chart_png": str(png)})
        self.assertIn("unsupported; using PNG", log.getvalue())
        self.assertTrue(any(shape.shape_type == 13 for shape in slide.shapes))

    def test_missing_png_and_invalid_data_fail_clearly(self):
        """reject incomplete inputs instead of leaving a blank or misleading chart"""
        for scene in ({**self.scene, "pptx_chart": "png"},
                      {**self.scene, "pptx_chart": "invalid"},
                      {**self.scene, "labels": []}, {**self.scene, "values": [1]}):
            with self.subTest(scene=scene), self.assertRaises(ValueError):
                self.export(scene)

    def test_chart_data_can_be_edited_saved_and_reopened(self):
        """change the chart data and check that the changes survive saving"""
        output, slide = self.export()
        chart = next(shape.chart for shape in slide.shapes if shape.has_chart)
        data = CategoryChartData()
        data.categories = ["Edited", "Added"]
        data.add_series("Updated values", [12, 34])
        chart.replace_data(data)
        slide.part.package.presentation_part.presentation.save(output)
        reopened = Presentation(output)
        chart = next(shape.chart for shape in reopened.slides[0].shapes if shape.has_chart)
        self.assertEqual(list(chart.series[0].values), [12, 34])
        self.assertEqual([c.label for c in chart.plots[0].categories], ["Edited", "Added"])

    def test_pptx_mode_does_not_change_chart_video_frames(self):
        """compare the actual video pixels and png bytes for both powerpoint settings"""
        import render
        theme = render.presets.dark
        first = render.build_chart(self.scene, theme, self.root)
        png = next(self.root.glob("chart_*.png")).read_bytes()
        second = render.build_chart({**self.scene, "pptx_chart": "png"}, theme, self.root)
        try:
            self.assertTrue((first.get_frame(0) == second.get_frame(0)).all())
            self.assertTrue(all(path.read_bytes() == png for path in self.root.glob("chart_*.png")))
        finally:
            first.close()
            second.close()

    def test_native_charts_keep_narration_and_other_slide_types(self):
        """check that native charts still work alongside ordinary slides and audio"""
        import wave
        audio = self.root / "voice.wav"
        with wave.open(str(audio), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 8000)
        output = self.root / "mixed.pptx"
        pptx_export.build_pptx({"theme": self.theme, "timeline": [
            {"type": "title", "text": "Title"}, self.scene, {"type": "outro", "text": "End"}]},
            [{}, {"narration_path": str(audio)}, {}], str(output))
        slides = Presentation(output).slides
        self.assertEqual(len(slides), 3)
        self.assertFalse(any(shape.has_chart for shape in slides[0].shapes))
        self.assertTrue(any(shape.has_chart for shape in slides[1].shapes))
        self.assertTrue(any(rel.target_part.content_type == "audio/wav" for rel in slides[1].part.rels.values()))


if __name__ == "__main__":
    unittest.main()
