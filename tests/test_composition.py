"""Canvas geometry, glyphs and actual render/export invariants."""

import copy
import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
composition = importlib.import_module("src.composition")
validate = importlib.import_module("src.studio").validate_spec

BASE: dict[str, Any] = {
    "timeline": [
        {
            "type": "composition",
            "duration": 1,
            "background": {
                "style": "grid",
                "color": "#191925",
                "accent": "#6750a4",
                "motion": "drift",
            },
            "elements": [
                {
                    "id": "text",
                    "type": "text",
                    "text": "Café • canvas",
                    "x": 0.1,
                    "y": 0.1,
                    "w": 0.8,
                    "h": 0.3,
                    "font_size": 0.07,
                    "color": "#ffffff",
                },
                {
                    "id": "shape",
                    "type": "shape",
                    "shape": "ellipse",
                    "x": 0.1,
                    "y": 0.6,
                    "w": 0.15,
                    "h": 0.2,
                    "color": "#6750a4",
                },
                {
                    "id": "chart",
                    "type": "chart",
                    "chart_type": "bar",
                    "labels": ["A", "B"],
                    "values": [2, 4],
                    "x": 0.3,
                    "y": 0.5,
                    "w": 0.6,
                    "h": 0.4,
                    "color": "#bba5ff",
                },
            ],
        }
    ]
}


class CanvasTests(unittest.TestCase):
    def test_validation_bounds_and_glyphs(self):
        validate(BASE)
        for key, value in [
            ("x", 0.5),
            ("w", -1),
            ("font_size", float("nan")),
            ("text", "Unsupported 🧑‍🚀"),
            ("id", "chart"),
        ]:
            spec = copy.deepcopy(BASE)
            spec["timeline"][0]["elements"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate(spec)
        spec = copy.deepcopy(BASE)
        spec["timeline"][0]["elements"][2]["values"] = [1]
        with self.assertRaises(ValueError):
            validate(spec)

    def test_defaults_and_integer_resolution(self):
        spec = copy.deepcopy(BASE)
        spec["timeline"][0].pop("background")
        spec["timeline"][0]["elements"][0].pop("font_size")
        result = validate(spec)
        self.assertEqual(result["timeline"][0]["background"]["motion"], "none")
        self.assertEqual(result["timeline"][0]["elements"][0]["font_size"], 0.06)
        self.assertNotIn("background", spec["timeline"][0])
        spec["meta"] = {"resolution": {"width": 1280.0, "height": 720.0}}
        with self.assertRaises(ValueError):
            validate(spec)

    def test_background_motion_and_static_time_zero(self):
        import numpy as np

        for style in composition.BACKGROUNDS:
            config = {
                "style": style,
                "color": "#191925",
                "accent": "#6750a4",
                "motion": "drift",
            }
            first = np.asarray(composition.background_frame(config, 320, 180, 0))
            last = np.asarray(composition.background_frame(config, 320, 180, 3))
            self.assertEqual(first.shape, (180, 320, 3))
            if style in ("gradient", "grid", "orbits", "waves"):
                self.assertFalse(np.array_equal(first, last))

    def test_gradient_pulse_changes_and_still_remains_static(self):
        import numpy as np

        config = {
            "style": "gradient",
            "color": "#191925",
            "accent": "#6750a4",
            "motion": "pulse",
        }
        first = np.asarray(composition.background_frame(config, 320, 180, 0))
        last = np.asarray(composition.background_frame(config, 320, 180, 2))
        self.assertFalse(np.array_equal(first, last))
        config["motion"] = "none"
        self.assertTrue(
            np.array_equal(
                np.asarray(composition.background_frame(config, 320, 180, 0)),
                np.asarray(composition.background_frame(config, 320, 180, 2)),
            )
        )

    def test_pptx_elements_remain_editable_and_positioned(self):
        from pptx import Presentation
        from pptx.util import Inches

        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        composition.export_slide(slide, BASE["timeline"][0], Inches(10), Inches(5.625))
        self.assertEqual(len(slide.shapes), 3)
        self.assertEqual(slide.shapes[0].text, "Café • canvas")
        self.assertAlmostEqual(slide.shapes[0].left / Inches(10), 0.1)
        self.assertTrue(slide.shapes[2].has_chart)
        self.assertEqual(list(slide.shapes[2].chart.series[0].values), [2, 4])

    def test_chart_types_and_shapes_render_and_export_natively(self):
        from pptx import Presentation
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches
        for kind, expected in [('bar',XL_CHART_TYPE.COLUMN_CLUSTERED),('horizontal',XL_CHART_TYPE.BAR_CLUSTERED),('line',XL_CHART_TYPE.LINE),('area',XL_CHART_TYPE.AREA),('pie',XL_CHART_TYPE.PIE),('doughnut',XL_CHART_TYPE.DOUGHNUT)]:
            with self.subTest(chart=kind):
                spec=copy.deepcopy(BASE)
                spec['timeline'][0]['elements'][2]['chart_type']=kind
                scene=validate(spec)['timeline'][0]
                self.assertEqual(composition.element_images(scene,320,180)[2][0].size,(192,72))
                prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
                composition.export_slide(slide,scene,Inches(10),Inches(5.625))
                self.assertEqual(slide.shapes[2].chart.chart_type,expected)
        for kind,expected in [('rounded',MSO_SHAPE.ROUNDED_RECTANGLE),('triangle',MSO_SHAPE.ISOSCELES_TRIANGLE),('arrow',MSO_SHAPE.RIGHT_ARROW)]:
            spec=copy.deepcopy(BASE);spec['timeline'][0]['elements'][1]['shape']=kind
            scene=validate(spec)['timeline'][0]
            composition.element_images(scene,320,180)
            prs=Presentation();slide=prs.slides.add_slide(prs.slide_layouts[6])
            composition.export_slide(slide,scene,Inches(10),Inches(5.625))
            self.assertEqual(slide.shapes[1].auto_shape_type,expected)
        for kind in ('pie','doughnut'):
            spec=copy.deepcopy(BASE);spec['timeline'][0]['elements'][2].update(chart_type=kind,values=[-1,2])
            with self.assertRaises(ValueError):validate(spec)

    def test_real_mp4_and_pptx_dimensions_for_all_presets(self):
        from pptx import Presentation

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            for width, height in composition.RESOLUTIONS:
                directory = Path(temp) / f"{width}x{height}"
                directory.mkdir()
                spec = copy.deepcopy(BASE)
                spec["meta"] = {
                    "resolution": {"width": width, "height": height},
                    "fps": 24,
                }
                path = directory / "spec.json"
                path.write_text(json.dumps(validate(spec)))
                subprocess.run(
                    [
                        sys.executable,
                        str(root / "src/render.py"),
                        str(path),
                        "-o",
                        str(directory / "video.mp4"),
                        "--workdir",
                        str(directory / "cache"),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    timeout=60,
                )
                import imageio_ffmpeg

                probe = subprocess.run(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-i",
                        str(directory / "video.mp4"),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertIn(f"{width}x{height}", probe.stderr)
                prs = Presentation(str(directory / "video.pptx"))
                self.assertAlmostEqual(
                    int(prs.slide_width or 0) / int(prs.slide_height or 1),
                    width / height,
                    places=5,
                )
                self.assertTrue(any(shape.has_chart for shape in prs.slides[0].shapes))


if __name__ == "__main__":
    unittest.main()
