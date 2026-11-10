import copy
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

inspect_document = importlib.import_module("src.quality").inspect_document


def text(**changes):
    return {"id": "claim", "type": "text", "text": "Readable text",
            "x": .1, "y": .1, "w": .8, "h": .2,
            "font_size": .04, "color": "#ffffff", **changes}


def document(elements=None, **scene):
    return {"meta": {"resolution": {"width": 1280, "height": 720}},
            "timeline": [{"type": "composition", "duration": 4,
                          "elements": elements or [text()], **scene}]}


def pose(time, **changes):
    return {"time": time, "x": 0, "y": 0, "scale": 1, "opacity": 1, **changes}


class QualityTests(unittest.TestCase):
    def test_newlines_follow_renderer_without_double_counting(self):
        report = inspect_document(document([text(text="First line\nSecond line", h=.10)]))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_clipped_line_and_long_token_are_rejected(self):
        report = inspect_document(document([text(text="First\nSecond\nThird", h=.08)]))
        self.assertTrue(any("text height" in error for error in report["errors"]))
        report = inspect_document(document([text(text="W" * 80, w=.2)]))
        self.assertTrue(any("unbreakable text" in error for error in report["errors"]))

    def test_eight_pixel_wrap_margin_is_not_full_box_width(self):
        # DejaVuSans at 29px renders this token at ~76px: the 80px box
        # has only 72px after the renderer's horizontal inset.
        report = inspect_document(document([text(text="WWW", w=80/1280)]))
        self.assertTrue(any("unbreakable text" in error for error in report["errors"]))

    def test_group_offsets_and_scale_are_included_at_group_cues(self):
        group = {"id": "moving", "keyframes": [pose(0), pose(.13, x=.5, scale=1.5), pose(4)]}
        report = inspect_document(document([text(group="moving")], groups=[group]))
        self.assertTrue(any("transformed bounds" in error for error in report["errors"]))

    def test_invisible_group_does_not_report_off_canvas(self):
        group = {"id": "hidden", "keyframes": [pose(0, x=.5, opacity=0), pose(4, x=.5, opacity=0)]}
        report = inspect_document(document([text(group="hidden")], groups=[group]))
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("reading hold" in warning for warning in report["warnings"]))

    def test_contrast_uses_last_containing_panel_before_text(self):
        panel = {"id": "panel", "type": "shape", "shape": "rect", "x": 0,
                 "y": 0, "w": 1, "h": 1, "color": "#ffffff"}
        report = inspect_document(document([panel, text()]))
        self.assertTrue(any("contrast below 4.5" in error for error in report["errors"]))
        dark = dict(panel, id="dark", color="#000000")
        self.assertEqual(inspect_document(document([panel, dark, text()]))["errors"], [])
        # A later panel is not the background behind the text.
        self.assertEqual(inspect_document(document([text(), panel]))["errors"], [])

    def test_large_bold_text_has_three_to_one_target(self):
        background = {"style": "solid", "color": "#ffffff"}
        regular = inspect_document(document([text(color="#888888")], background=background))
        bold = inspect_document(document([text(color="#888888", bold=True)], background=background))
        self.assertTrue(any("contrast below 4.5" in error for error in regular["errors"]))
        self.assertEqual(bold["errors"], [])
        too_low = inspect_document(document([text(color="#bbbbbb", bold=True)], background=background))
        self.assertTrue(any("contrast below 3" in error for error in too_low["errors"]))

    def test_unknown_image_background_is_advisory_and_collision_is_error(self):
        image = {"id": "photo", "type": "image", "x": 0, "y": 0, "w": 1, "h": 1,
                 "color": "#ffffff"}
        report = inspect_document(document([image, text()]))
        self.assertTrue(any("review contrast" in warning for warning in report["warnings"]))
        self.assertTrue(any("essential content overlaps photo" in error for error in report["errors"]))

    def test_text_overlap_ignores_decorative_path_and_panel(self):
        decoration = {"id": "line", "type": "path", "x": 0, "y": 0,
                      "w": 1, "h": 1, "color": "#ffffff"}
        report = inspect_document(document([decoration, text(), text(id="second")]))
        collisions = [error for error in report["errors"] if "overlaps" in error]
        self.assertEqual(collisions, ["Scene 1, claim: essential content overlaps second"])
        report = inspect_document(document([decoration, text(), text(id="second", y=.4)]))
        self.assertFalse(any("overlaps" in error for error in report["errors"]))

    def test_chunk_and_exit_cues_limit_actual_opaque_reading_hold(self):
        item = text(text="Read this", chunks=[{"text": "Read ", "start": 0, "duration": .5},
                                             {"text": "this", "start": 3, "duration": .5}],
                    animation={"effect": "chunks", "start": 0, "duration": .5, "easing": "linear"})
        report = inspect_document(document([item]))
        self.assertTrue(any("reading hold" in warning for warning in report["warnings"]))
        item = text(exit_animation={"effect": "fade", "start": .5, "duration": .5, "easing": "linear"})
        report = inspect_document(document([item]))
        self.assertTrue(any("reading hold" in warning for warning in report["warnings"]))

    def test_evidence_copy_preserves_square_aspect_timing_and_source(self):
        from scripts.evaluate_generation import render_evidence
        from src import composition
        spec = document()
        spec["meta"]["resolution"] = {"width": 1080, "height": 1080}
        spec["timeline"].append(copy.deepcopy(spec["timeline"][0]))
        spec["timeline"][0]["transition"] = {"effect": "crossfade", "duration": .4}
        original = copy.deepcopy(spec)
        renderer = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "square"
            evidence = render_evidence(spec, output, renderer, composition)
            silent = json.loads((output / "silent-evidence.json").read_text())
            self.assertEqual(evidence["resolution"], {"width": 1080, "height": 1080})
            self.assertEqual(evidence["duration_seconds"], 8)
            self.assertEqual(silent["timeline"], spec["timeline"])
            self.assertTrue((output / "scene-01.png").is_file())
        self.assertEqual(spec, original)
        renderer.render.assert_called_once()

    def test_quality_never_calls_image_generation_or_changes_source(self):
        spec = document()
        original = copy.deepcopy(spec)
        with patch("src.images.generate_image", side_effect=AssertionError("remote call")):
            report = inspect_document(spec)
        self.assertEqual(spec, original)
        self.assertEqual(set(report), {"errors", "warnings", "requires_human_review"})
        self.assertTrue(report["requires_human_review"])


if __name__ == "__main__":
    unittest.main()
