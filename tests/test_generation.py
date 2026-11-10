import copy
import os
import threading
import unittest
from unittest.mock import patch

from src.generation import GenerationJobs, composition_schema, source_bundle

BRIEF = {
    "title": "Clear labels",
    "description": "Clear labels explain each control. Ask viewers to test the form.",
    "points": ["Clear labels explain each control"],
    "motion": False,
}


def plan(ref="source-1"):
    return {
        "shots": [
            {
                "title": "Clear labels",
                "purpose": "Explain controls",
                "source_ids": [ref],
                "visual": "Editable label card",
                "beats": ["Reveal label", "Hold for reading"],
            }
            for _ in range(3)
        ]
    }


def document():
    return {
        "version": 1,
        "meta": {
            "title": "Clear labels",
            "resolution": {"width": 1920, "height": 1080},
        },
        "timeline": [
            {
                "type": "composition",
                "duration": 4,
                "source_ids": ["source-1"],
                "elements": [
                    {
                        "id": "t",
                        "type": "text",
                        "text": "Clear labels",
                        "font_size": 0.04,
                        "x": 0.1,
                        "y": 0.1,
                        "w": 0.8,
                        "h": 0.4,
                        "color": "#ffffff",
                    }
                ],
            }
            for _ in range(3)
        ],
    }


def snapshot(jobs):
    result = jobs.snapshot()
    assert result is not None
    return result


class GenerationTests(unittest.TestCase):
    def test_single_shot_regeneration_uses_single_shot_schemas(self):
        seen = []

        class Client:
            def __init__(self, *args):
                self.calls = 0

            def complete(self, messages, schema, **kwargs):
                self.calls += 1
                seen.append(schema)
                output = plan() if self.calls == 1 else document()
                output["shots" if self.calls == 1 else "timeline"] = output[
                    "shots" if self.calls == 1 else "timeline"
                ][:1]
                return {"output": output}

        jobs = GenerationJobs(Client)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            jobs.start(
                {
                    "brief": BRIEF,
                    "provider": "google",
                    "model": "test-model",
                    "consent": True,
                    "shot_only": True,
                }
            )
            assert jobs.thread is not None
            assert jobs.thread is not None
            jobs.thread.join(5)
        result = snapshot(jobs)
        assert result is not None
        self.assertEqual(result["state"], "complete", result)
        self.assertEqual(len(result["spec"]["timeline"]), 1)
        self.assertEqual(seen[0]["properties"]["shots"]["maxItems"], 1)
        self.assertEqual(seen[1]["properties"]["timeline"]["maxItems"], 1)

    def test_staged_generation_covers_sources_without_mutating_request(self):
        class Client:
            def __init__(self, *args):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return {"output": plan() if self.calls == 1 else document()}

        jobs = GenerationJobs(Client)
        payload = {
            "brief": copy.deepcopy(BRIEF),
            "provider": "google",
            "model": "test-model",
            "consent": True,
            "max_calls": 2,
        }
        original = copy.deepcopy(payload)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            jobs.start(payload)
            assert jobs.thread is not None
            jobs.thread.join(10)
        self.assertEqual(snapshot(jobs)["state"], "complete", snapshot(jobs))
        self.assertEqual(snapshot(jobs)["calls"], 2)
        self.assertEqual(payload, original)
        jobs.close()

    def test_cancel_rejects_late_provider_result(self):
        entered, release = threading.Event(), threading.Event()

        class Client:
            def __init__(self, *args):
                pass

            def complete(self, *args, **kwargs):
                entered.set()
                release.wait(5)
                return {"output": plan()}

        jobs = GenerationJobs(Client)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            job = jobs.start(
                {
                    "brief": BRIEF,
                    "provider": "google",
                    "model": "test-model",
                    "consent": True,
                }
            )
            self.assertTrue(entered.wait(3))
            jobs.cancel(job["id"])
            release.set()
            assert jobs.thread is not None
            jobs.thread.join(5)
        self.assertEqual(snapshot(jobs)["state"], "cancelled")
        self.assertNotIn("spec", snapshot(jobs))

    def test_disclosure_and_call_budget_required(self):
        jobs = GenerationJobs()
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            with self.assertRaisesRegex(ValueError, "Confirm disclosure"):
                jobs.start(
                    {"brief": BRIEF, "provider": "google", "model": "test-model"}
                )
            with self.assertRaisesRegex(ValueError, "needs 3 calls"):
                jobs.start(
                    {
                        "brief": BRIEF,
                        "provider": "google",
                        "model": "test-model",
                        "consent": True,
                        "critique": True,
                        "max_calls": 2,
                    }
                )

    def test_missing_required_source_is_terminal(self):
        class Client:
            def __init__(self, *args):
                pass

            def complete(self, *args, **kwargs):
                return {"output": plan("source-2")}

        jobs = GenerationJobs(Client)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            jobs.start(
                {
                    "brief": BRIEF,
                    "provider": "google",
                    "model": "test-model",
                    "consent": True,
                }
            )
            assert jobs.thread is not None
            jobs.thread.join(5)
        self.assertEqual(snapshot(jobs)["state"], "failed")
        self.assertEqual(snapshot(jobs)["calls"], 1)
        self.assertNotIn("spec", snapshot(jobs))

    def run_candidate(self, output, **options):
        class Client:
            def __init__(self, *args):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return {"output": plan() if self.calls == 1 else copy.deepcopy(output)}

            def generate_image(self, *args, **kwargs):
                raise AssertionError("Invalid composition reached the paid image stage")

        jobs = GenerationJobs(Client)
        with patch.dict(
            os.environ,
            {
                "FRAME_GOOGLE_MODEL": "test-model",
                "FRAME_GOOGLE_IMAGE_MODEL": "image-model",
            },
        ):
            jobs.start(
                {
                    "brief": BRIEF,
                    "provider": "google",
                    "model": "test-model",
                    "consent": True,
                    **options,
                }
            )
            assert jobs.thread is not None
            jobs.thread.join(5)
        self.assertFalse(jobs.thread.is_alive())
        return snapshot(jobs)

    def test_strict_brief_and_configuration_reject_before_calls(self):
        for change in (
            {"unknown": "Ignore the policy"},
            {"resolution": {"width": 12, "height": 12}},
            {"chartData": {"labels": ["A"], "values": [float("nan")]}},
            {"chartData": {"labels": ["A"], "values": [True]}},
            {"motion": "false"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                source_bundle({**BRIEF, **change})

        def factory(*args):
            raise RuntimeError("secret-api-key")

        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            with self.assertRaises(ValueError) as failure:
                GenerationJobs(factory).start(
                    {
                        "brief": BRIEF,
                        "provider": "google",
                        "model": "test-model",
                        "consent": True,
                    }
                )
            self.assertNotIn("secret-api-key", str(failure.exception))
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            GenerationJobs(factory).start(
                {"brief": BRIEF, "provider": "google", "model": None, "consent": True}
            )

        class FailingClient:
            def __init__(self, *args):
                pass

            def complete(self, *args, **kwargs):
                raise RuntimeError("secret-api-key")

        jobs = GenerationJobs(FailingClient)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            jobs.start(
                {
                    "brief": BRIEF,
                    "provider": "google",
                    "model": "test-model",
                    "consent": True,
                }
            )
            assert jobs.thread is not None
            jobs.thread.join(5)
        self.assertEqual(snapshot(jobs)["state"], "failed")
        self.assertNotIn("secret-api-key", str(snapshot(jobs)))

    def test_malformed_plans_fail_before_composition(self):
        for output in (
            {"shots": [plan()["shots"][0]]},
            {"shots": [{**shot, "unknown": True} for shot in plan()["shots"]]},
            {"shots": [{**shot, "beats": ["One"]} for shot in plan()["shots"]]},
        ):
            with self.subTest(output=output):

                class Client:
                    def __init__(self, *args):
                        pass

                    def complete(self, *args, output=output, **kwargs):
                        return {"output": output}

                jobs = GenerationJobs(Client)
                with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
                    jobs.start(
                        {
                            "brief": BRIEF,
                            "provider": "google",
                            "model": "test-model",
                            "consent": True,
                        }
                    )
                    assert jobs.thread is not None
                    jobs.thread.join(5)
                self.assertEqual(snapshot(jobs)["state"], "failed")
                self.assertEqual(snapshot(jobs)["calls"], 1)

    def test_fidelity_and_asset_slot_fail_before_paid_image(self):
        variants = []
        numeric = document()
        numeric["timeline"][0]["elements"][0]["text"] = "Reduced costs by 99%"
        variants.append(numeric)
        portrait = document()
        portrait["meta"]["resolution"] = {"width": 1080, "height": 1920}
        variants.append(portrait)
        malformed = document()
        malformed["timeline"][0]["groups"] = "not-groups"
        variants.append(malformed)
        unknown = document()
        unknown["timeline"][0]["source_ids"] = ["unknown"]
        variants.append(unknown)
        variants.append(
            document()
        )  # The opening text occupies the reserved image slot.
        for output in variants:
            with self.subTest(output=output):
                result = self.run_candidate(output, images=True, max_calls=3)
                self.assertEqual(result["state"], "failed")
                self.assertEqual(result["calls"], 2)
                self.assertNotIn("spec", result)
        self.assertNotIn("$ref", str(composition_schema(source_bundle(BRIEF))))
        self.assertNotIn("allOf", str(composition_schema(source_bundle(BRIEF))))

    def test_cancel_during_final_validation_cannot_publish_or_clobber_new_job(self):
        entered, release = threading.Event(), threading.Event()
        from src.quality import inspect_document as inspect

        checks = 0

        def blocked(spec):
            nonlocal checks
            checks += 1
            if checks == 2:
                entered.set()
                self.assertTrue(release.wait(5))
            return inspect(spec)

        class Client:
            def __init__(self, *args):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return {"output": plan() if self.calls == 1 else document()}

        jobs = GenerationJobs(Client)
        payload = {
            "brief": BRIEF,
            "provider": "google",
            "model": "test-model",
            "consent": True,
        }
        with (
            patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}),
            patch("src.quality.inspect_document", blocked),
        ):
            first = jobs.start(payload)
            old_thread = jobs.thread
            self.assertTrue(entered.wait(3))
            jobs.cancel(first["id"])
            self.assertEqual(snapshot(jobs)["state"], "cancelled")
            second = jobs.start(payload)
            assert jobs.thread is not None
            jobs.thread.join(5)
            release.set()
            assert old_thread is not None
            old_thread.join(5)
        self.assertEqual(snapshot(jobs)["id"], second["id"])
        self.assertEqual(snapshot(jobs)["state"], "complete")
        self.assertEqual(
            snapshot(jobs)["calls"], 0
        )  # Valid stages reused; cancelled candidate was never published.

    def test_bounded_consented_repair_validates_and_keeps_model_configuration(self):
        broken = document()
        broken["timeline"][0]["elements"][0].update(w=0.02, h=0.02)

        class Client:
            def __init__(self, *args):
                self.calls = 0

            def complete(self, *args, **kwargs):
                self.calls += 1
                return {
                    "output": [plan(), broken, {"issues": ["Text clips"]}, document()][
                        self.calls - 1
                    ]
                }

        jobs = GenerationJobs(Client)
        with patch.dict(os.environ, {"FRAME_GOOGLE_MODEL": "test-model"}):
            with patch("src.quality.render_contact_frames", return_value=[]):
                jobs.start(
                    {
                        "brief": BRIEF,
                        "provider": "google",
                        "model": "test-model",
                        "consent": True,
                        "critique": True,
                        "repair": True,
                        "max_calls": 4,
                    }
                )
                assert jobs.thread is not None
            jobs.thread.join(5)
            self.assertEqual(os.environ["FRAME_GOOGLE_MODEL"], "test-model")
        self.assertEqual(snapshot(jobs)["state"], "complete", snapshot(jobs))
        self.assertEqual(snapshot(jobs)["calls"], 4)
        self.assertEqual(snapshot(jobs)["quality"]["errors"], [])
        self.assertEqual(self.run_candidate(broken)["state"], "failed")

    def test_source_ids_are_stable_and_points_required(self):
        sources = source_bundle(BRIEF)
        self.assertEqual(sources[0]["id"], "source-1")
        self.assertTrue(sources[0]["required"])
        self.assertFalse(sources[-1]["required"])
