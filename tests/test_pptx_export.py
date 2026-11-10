"""PPTX chart export: native editable charts, theming and PNG fallback."""

import subprocess
import sys
import tempfile
import unittest
import wave
import zipfile
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


class NarrationExportTests(unittest.TestCase):
    """Narration clips embed whatever container the TTS provider produced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        wav = self.dir / "n.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(b"\x00\x00" * 12000)  # 0.5 s
        self.wav = wav
        self.mp3 = self.dir / "n.mp3"
        import imageio_ffmpeg
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                        "-i", str(wav), "-codec:a", "libmp3lame", str(self.mp3)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def media_types(self, audio):
        out = self.dir / "deck.pptx"
        spec = {"theme": THEME, "timeline": [{"type": "title", "text": "Hi", "narration": "Hi"}]}
        with redirect_stdout(StringIO()):
            pptx_export.build_pptx(spec, [{"narration_path": str(audio)}], str(out))
        with zipfile.ZipFile(out) as z:
            types = z.read("[Content_Types].xml").decode()
            names = z.namelist()
        return types, names

    def test_wav_narration_embeds_as_wav(self):
        types, names = self.media_types(self.wav)
        self.assertIn('ContentType="audio/wav"', types)
        self.assertTrue(any(n.startswith("ppt/media/") and n.endswith(".wav") for n in names))

    def test_mp3_narration_embeds_as_mpeg(self):
        types, names = self.media_types(self.mp3)
        self.assertIn('ContentType="audio/mpeg"', types)
        self.assertTrue(any(n.startswith("ppt/media/") and n.endswith(".mp3") for n in names))


if __name__ == "__main__":
    unittest.main()
