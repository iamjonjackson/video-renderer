import copy
import unittest

from src.continuity import compile_continuity


class ContinuityTests(unittest.TestCase):
    def test_shared_identity_compiles_without_mutating_document(self):
        item = {
            "id": "anchor",
            "type": "text",
            "text": "Same idea",
            "x": 0.1,
            "y": 0.2,
            "w": 0.4,
            "h": 0.2,
        }
        second = {**item, "x": 0.5}
        spec = {
            "timeline": [
                {
                    "type": "composition",
                    "transition": {"duration": 0.5},
                    "elements": [item],
                },
                {"type": "composition", "elements": [second]},
            ]
        }
        original = copy.deepcopy(spec)
        result = compile_continuity(spec)
        self.assertEqual(
            result["timeline"][1]["elements"][0]["keyframes"][0]["x"], -0.4
        )
        self.assertEqual(spec, original)
        second["text"] = "Different idea"
        self.assertNotIn(
            "keyframes", compile_continuity(spec)["timeline"][1]["elements"][0]
        )
