"""Offline provisioning tests: tiny pinned archives, real files and thread barriers."""

import hashlib
import http.client
import io
import sys
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import ai_setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "ai-assets"
        self.content = {
            "wllama.js": b"pinned javascript",
            "wllama.wasm": b"pinned wasm",
            "WLLAMA-LICENSE": b"license",
            "qwen3.5-0.8b-q4_k_m.gguf": b"model weights",
        }
        members = [
            "package/esm/index.js",
            "package/esm/wasm/wllama.wasm",
            "package/LICENCE",
            None,
        ]
        self.assets = tuple(
            ai_setup.Asset(name, len(data), hashlib.sha256(data).hexdigest(), member)
            for (name, data), member in zip(self.content.items(), members, strict=True)
        )
        self.archive = self.make_archive()
        self.patch = patch.multiple(
            ai_setup,
            ASSETS=self.assets,
            ARCHIVE_SHA512=hashlib.sha512(self.archive).hexdigest(),
            MAX_ARCHIVE_BYTES=len(self.archive),
            MAX_DOWNLOAD_BYTES=len(self.archive)
            + len(self.content["qwen3.5-0.8b-q4_k_m.gguf"]),
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.calls = []

    def make_archive(self, special=None):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for asset in self.assets:
                if asset.member:
                    member = tarfile.TarInfo(asset.member)
                    member.size = asset.size
                    if special and asset.name == "wllama.js":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "../../escaped.js"
                        member.size = 0
                    archive.addfile(member, io.BytesIO(self.content[asset.name]))
        return output.getvalue()

    def transport(self, url, *, timeout):
        self.assertEqual(timeout, 5)
        self.calls.append(url)
        if url == ai_setup.ARCHIVE_URL:
            return io.BytesIO(self.archive)
        self.assertEqual(url, ai_setup.MODEL_URL)
        return io.BytesIO(self.content["qwen3.5-0.8b-q4_k_m.gguf"])

    def setup(self, transport=None):
        setup = ai_setup.AISetup(self.root, transport=transport or self.transport)
        self.addCleanup(setup.close)
        return setup

    def finish(self, setup):
        result = setup.wait(timeout=3)
        self.assertNotIn(result["status"], {"downloading", "verifying"}, result)
        return result

    def assert_no_staging(self):
        self.assertEqual(list(self.root.parent.glob(".ai-setup-*")), [])

    def test_consent_is_required_and_no_network_is_used_on_construction(self):
        setup = self.setup()
        self.assertEqual(setup.snapshot()["status"], "not_installed")
        invalid_consents: tuple[Any, ...] = (False, None, "yes", 1)
        for consent in invalid_consents:
            with self.subTest(consent=consent), self.assertRaises(ValueError):
                setup.start(consent=consent)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_atomic_success_and_each_new_instance_checks_all_hashes_offline(self):
        setup = self.setup()
        setup.start(consent=True)
        result = self.finish(setup)
        self.assertEqual(result["status"], "ready", result)
        self.assertEqual(
            result["bytes_downloaded"],
            len(self.archive) + len(self.content["qwen3.5-0.8b-q4_k_m.gguf"]),
        )
        self.assertEqual({p.name for p in self.root.iterdir()}, set(self.content))
        for name, expected in self.content.items():
            self.assertEqual((self.root / name).read_bytes(), expected)
        self.assert_no_staging()
        self.calls.clear()
        self.assertEqual(self.setup().snapshot()["status"], "ready")
        self.assertEqual(self.calls, [])
        for name, original in self.content.items():
            with self.subTest(name=name):
                (self.root / name).write_bytes(b"x" * len(original))
                self.assertEqual(self.setup().snapshot()["status"], "not_installed")
                (self.root / name).write_bytes(original)

    def test_model_upgrade_reuses_runtime_and_retires_old_weights(self):
        self.root.mkdir()
        for asset in self.assets:
            if asset.member:
                (self.root / asset.name).write_bytes(self.content[asset.name])
        (self.root / "smollm2.gguf").write_bytes(b"old model")
        setup = self.setup()
        setup.start(consent=True)
        self.assertEqual(self.finish(setup)["status"], "ready")
        self.assertEqual(self.calls, [ai_setup.MODEL_URL])
        self.assertFalse((self.root / "smollm2.gguf").exists())
        self.assertEqual({path.name for path in self.root.iterdir()}, set(self.content))

    def test_retirement_failure_keeps_verified_installation_ready(self):
        self.root.mkdir()
        (self.root / "old-model.gguf").write_bytes(b"old")
        setup = self.setup()
        original = ai_setup.shutil.rmtree

        def fail_backup(path, *args, **kwargs):
            if str(path).endswith(".previous"):
                raise OSError("backup locked")
            return original(path, *args, **kwargs)

        with patch.object(ai_setup.shutil, "rmtree", side_effect=fail_backup):
            setup.start(consent=True)
            result = self.finish(setup)
        self.assertEqual(result["status"], "ready")
        self.assertIn("old assets remain", result["warning"])
        self.assertTrue(setup._verify(self.root))
        self.assertEqual(len(list(self.root.parent.glob("*.previous"))), 1)

    def test_runtime_repair_reuses_verified_model(self):
        self.root.mkdir()
        name = "qwen3.5-0.8b-q4_k_m.gguf"
        (self.root / name).write_bytes(self.content[name])
        setup = self.setup()
        setup.start(consent=True)
        self.assertEqual(self.finish(setup)["status"], "ready")
        self.assertEqual(self.calls, [ai_setup.ARCHIVE_URL])

    def test_model_failure_preserves_prior_directory_and_cleans_partial_files(self):
        self.root.mkdir()
        (self.root / "old.txt").write_text("keep")

        def fail_model(url, *, timeout):
            if url == ai_setup.MODEL_URL:
                raise OSError("network unavailable")
            return self.transport(url, timeout=timeout)

        setup = self.setup(fail_model)
        setup.start(consent=True)
        result = self.finish(setup)
        self.assertEqual(result["status"], "failed")
        self.assertIn("network unavailable", result["error"])
        self.assertEqual([p.name for p in self.root.iterdir()], ["old.txt"])
        self.assert_no_staging()

    def test_bad_checksum_and_size_limit_never_activate(self):
        for data in (b"wrong archive", self.archive + b"too many bytes"):
            with self.subTest(length=len(data)):
                setup = self.setup(lambda url, timeout, data=data: io.BytesIO(data))
                setup.start(consent=True)
                self.assertEqual(self.finish(setup)["status"], "failed")
                self.assertFalse(self.root.exists())
                self.assert_no_staging()

    def test_symlink_archive_member_is_rejected_without_extraction(self):
        archive = self.make_archive(special=True)
        with (
            patch.object(
                ai_setup, "ARCHIVE_SHA512", hashlib.sha512(archive).hexdigest()
            ),
            patch.object(ai_setup, "MAX_ARCHIVE_BYTES", len(archive)),
        ):
            setup = self.setup(lambda url, timeout: io.BytesIO(archive))
            setup.start(consent=True)
            self.assertEqual(self.finish(setup)["status"], "failed")
        self.assertFalse(self.root.exists())
        self.assertFalse((self.root.parent / "escaped.js").exists())
        self.assert_no_staging()

    def test_overlapping_starts_are_coalesced_and_cancel_prevents_activation(self):
        entered = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)

        class BlockingResponse(io.BytesIO):
            def read1(self, size: int | None = -1):
                entered.set()
                if not release.wait(2):
                    raise TimeoutError("test barrier timed out")
                return super().read(size)

        def blocking_transport(url, *, timeout):
            self.calls.append(url)
            return BlockingResponse(self.archive)

        setup = self.setup(blocking_transport)
        setup.start(consent=True)
        self.assertTrue(entered.wait(1))
        self.assertFalse(self.root.exists())
        starters = [
            threading.Thread(target=lambda: setup.start(consent=True)) for _ in range(8)
        ]
        for thread in starters:
            thread.start()
        for thread in starters:
            thread.join(1)
            self.assertFalse(thread.is_alive())
        setup.cancel()
        release.set()
        self.assertEqual(self.finish(setup)["status"], "cancelled")
        self.assertEqual(self.calls, [ai_setup.ARCHIVE_URL])
        self.assertFalse(self.root.exists())
        self.assert_no_staging()

    def test_deadline_fails_and_closed_instance_rejects_new_work(self):
        with patch.object(ai_setup, "TOTAL_TIMEOUT_SECONDS", 0):
            setup = self.setup()
            setup.start(consent=True)
            self.assertEqual(self.finish(setup)["status"], "failed")
            self.assertEqual(self.calls, [])
        setup.close()
        with self.assertRaises(RuntimeError):
            setup.start(consent=True)

    def test_incomplete_http_response_publishes_failure_and_cleans_stage(self):
        class TruncatedResponse(io.BytesIO):
            def read1(self, size: int | None = -1):
                raise http.client.IncompleteRead(b"partial", 20)

        setup = self.setup(lambda url, timeout: TruncatedResponse())
        setup.start(consent=True)
        self.assertEqual(self.finish(setup)["status"], "failed")
        self.assertFalse(self.root.exists())
        self.assert_no_staging()

    def test_cleanup_failure_still_publishes_terminal_status(self):
        setup = self.setup(lambda url, timeout: io.BytesIO(b"corrupt"))
        with patch.object(ai_setup.shutil, "rmtree", side_effect=OSError("disk error")):
            setup.start(consent=True)
            result = self.finish(setup)
        self.assertEqual(result["status"], "failed")
        self.assertIn("clean partial", result["error"])
        self.assertFalse(self.root.exists())
        # The actual directory is still owned by TemporaryDirectory cleanup.
        self.assertEqual(len(list(self.root.parent.glob(".ai-setup-*"))), 1)

    def test_http_reads_use_interruptible_read1_not_fill_buffer_read(self):
        class ReadOneResponse(io.BytesIO):
            def read(self, size: int | None = -1):
                raise AssertionError("fill-buffer read would hide deadline checks")

            def read1(self, size: int | None = -1):
                return super().read(1)

        setup = self.setup(
            lambda url, timeout: ReadOneResponse(
                self.archive
                if url == ai_setup.ARCHIVE_URL
                else self.content["qwen3.5-0.8b-q4_k_m.gguf"]
            )
        )
        setup.start(consent=True)
        self.assertEqual(self.finish(setup)["status"], "ready")
        self.assert_no_staging()

    def test_symlink_existing_asset_is_not_ready(self):
        self.root.mkdir()
        for name, content in self.content.items():
            (self.root / name).write_bytes(content)
        external = self.root.parent / "external.js"
        external.write_bytes(self.content["wllama.js"])
        (self.root / "wllama.js").unlink()
        (self.root / "wllama.js").symlink_to(external)
        self.assertEqual(self.setup().snapshot()["status"], "not_installed")


if __name__ == "__main__":
    unittest.main()
