"""Pinned, consent-gated browser AI provisioning; no package code is executed.

Create one AISetup per server. start(consent=True) launches a background thread;
start, cancel and snapshot return JSON-compatible status dictionaries. close cancels
and joins the worker before server shutdown. Startup verifies existing files offline.
Transport injection is for bounded local tests, not for user-selected URLs or pins.
"""

import base64
import hashlib
import os
import shutil
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "studio" / "ai-assets"
REVISION = "6ab461498e2023f6e3c1baea90a8f0fe38ab64d0"
INTEGRITY = "ZvoRdQAn+E+18EvQ9qS036gudiI9rbZRBJgG/qNICPPwrA0Y6SMMdbziz/j7K/0WxcbJlhaRraVIYsnEy732NA=="
ARCHIVE_URL = "https://registry.npmjs.org/@wllama/wllama/-/wllama-3.13.0.tgz"
ARCHIVE_SHA512 = base64.b64decode(INTEGRITY).hex()
MODEL_URL = f"https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF/resolve/{REVISION}/Qwen3.5-0.8B-Q4_K_M.gguf"
CHUNK_BYTES = 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 5
TOTAL_TIMEOUT_SECONDS = 900
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
MAX_DOWNLOAD_BYTES = MAX_ARCHIVE_BYTES + 532517120


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    sha256: str
    member: str | None = None


ASSETS = (
    Asset(
        "wllama.js",
        275466,
        "fffd95c16ca191f31f4303664a05189c43d0cb20c52b67276c04e8857b138b64",
        "package/esm/index.js",
    ),
    Asset(
        "wllama.wasm",
        10244628,
        "79ac5be917b71d50571a4f584436a9f6baf6b6e57719d094ed8bd950e9a65780",
        "package/esm/wasm/wllama.wasm",
    ),
    Asset(
        "WLLAMA-LICENSE",
        1071,
        "5866e3bd7e3cbd3f7c8bea6efd8a1e7fa7cc8de68c30f428aff7c6584a0fb720",
        "package/LICENCE",
    ),
    Asset(
        "qwen3.5-0.8b-q4_k_m.gguf",
        532517120,
        "bd258782e35f7f458f8aced1adc053e6e92e89bc735ba3be89d38a06121dc517",
    ),
)
MANIFEST = {
    "runtime": "wllama 3.13.0 (MIT)",
    "model": "Qwen3.5-0.8B Q4_K_M (Apache-2.0)",
    "revision": REVISION,
    "download_max_bytes": MAX_DOWNLOAD_BYTES,
    "installed_bytes": sum(asset.size for asset in ASSETS),
}


class _Cancelled(Exception):
    pass


class AISetup:
    def __init__(self, root=ROOT, *, transport=urlopen):
        self.root = Path(root)
        self._transport = transport
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker = None
        self._closed = False
        self._deadline = None
        self._status = {
            "status": "verifying",
            "bytes_downloaded": 0,
            "total_bytes": MANIFEST["download_max_bytes"],
            "asset": None,
            "error": None,
            "manifest": dict(MANIFEST),
        }
        self._set(status="ready" if self._verify(self.root) else "not_installed")

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def _set(self, **values):
        with self._lock:
            self._status.update(values)

    def start(self, *, consent=False):
        """Reject absent consent; coalesce overlapping starts without queuing."""
        if not isinstance(consent, bool) or not consent:
            raise ValueError("Explicit download consent is required")
        with self._lock:
            if self._closed:
                raise RuntimeError("AI setup is closed")
            if self._status["status"] == "ready" or (
                self._worker and self._worker.is_alive()
            ):
                return self.snapshot()
            self._cancel.clear()
            self._set(
                status="downloading",
                bytes_downloaded=0,
                asset=None,
                error=None,
                warning=None,
            )
            self._worker = threading.Thread(
                target=self._run, name="browser-ai-setup", daemon=True
            )
            self._worker.start()
            return self.snapshot()

    def cancel(self):
        """Request cancellation; terminal status follows bounded reads and cleanup."""
        with self._lock:
            self._cancel.set()
            return self.snapshot()

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel.set()
            worker = self._worker
        if worker:
            worker.join()

    def wait(self, timeout=None):
        """CLI/test completion boundary; does not cancel on timeout."""
        with self._lock:
            worker = self._worker
        if worker:
            worker.join(timeout)
        return self.snapshot()

    def _check(self):
        if self._cancel.is_set():
            raise _Cancelled()
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError("AI setup exceeded its total time limit")

    def _verify_asset(self, directory, asset):
        try:
            if directory.is_symlink() or not directory.is_dir():
                return False
            self._check()
            path = directory / asset.name
            if (
                path.is_symlink()
                or not path.is_file()
                or path.stat().st_size != asset.size
            ):
                return False
            digest = hashlib.sha256()
            with path.open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    self._check()
                    digest.update(chunk)
            return digest.hexdigest() == asset.sha256
        except OSError:
            return False

    def _verify(self, directory):
        return all(self._verify_asset(directory, asset) for asset in ASSETS)

    def _download(self, url, path, expected_digest, algorithm, limit):
        self._set(asset=path.name)
        digest = hashlib.new(algorithm)
        received = 0
        self._check()
        with (
            self._transport(url, timeout=REQUEST_TIMEOUT_SECONDS) as response,
            path.open("xb") as output,
        ):
            # HTTPResponse.read(n) can wait indefinitely under a trickle of bytes.
            # read1 returns after one underlying read, allowing deadline/cancel
            # checks even while a peer continuously makes slow progress.
            read_chunk = getattr(response, "read1", response.read)
            while True:
                self._check()
                chunk = read_chunk(CHUNK_BYTES)
                self._check()
                if not chunk:
                    break
                received += len(chunk)
                if (
                    received > limit
                    or self.snapshot()["bytes_downloaded"] + len(chunk)
                    > MAX_DOWNLOAD_BYTES
                ):
                    raise ValueError("Download exceeds pinned size limit")
                output.write(chunk)
                digest.update(chunk)
                with self._lock:
                    self._status["bytes_downloaded"] += len(chunk)
        if digest.hexdigest() != expected_digest:
            raise ValueError(f"Checksum mismatch: {path.name}")

    def _extract(self, archive, stage):
        # Never extract paths from the archive. Copy only exact regular members
        # to manifest-owned filenames, with fixed expanded-size budgets.
        with tarfile.open(archive, "r:gz") as package:
            found = set()
            for member in package:
                self._check()
                asset = next(
                    (item for item in ASSETS if item.member == member.name), None
                )
                if asset is None:
                    continue
                if (
                    member.name in found
                    or not member.isfile()
                    or member.size != asset.size
                ):
                    raise ValueError("Invalid pinned archive member")
                found.add(member.name)
                source = package.extractfile(member)
                if source is None:
                    raise ValueError("Missing archive member data")
                with source, (stage / asset.name).open("xb") as output:
                    remaining = asset.size
                    while remaining:
                        self._check()
                        chunk = source.read(min(CHUNK_BYTES, remaining))
                        if not chunk:
                            raise ValueError("Truncated archive member")
                        output.write(chunk)
                        remaining -= len(chunk)
            if found != {item.member for item in ASSETS if item.member}:
                raise ValueError("Missing pinned archive members")

    def _activate(self, stage):
        # Preserve an invalid prior installation if the final rename fails.
        # All four assets become visible together, never file-by-file.
        backup = stage.parent / (stage.name + ".previous")
        with self._lock:
            self._check()
            had_previous = self.root.exists() or self.root.is_symlink()
            if had_previous:
                os.replace(self.root, backup)
            try:
                os.replace(stage, self.root)
            except OSError:
                if had_previous:
                    os.replace(backup, self.root)
                raise
            self._set(status="ready", asset=None, error=None)
        try:
            if backup.is_symlink() or backup.is_file():
                backup.unlink()
            elif backup.exists():
                shutil.rmtree(backup)
        except OSError as exc:
            # The verified installation has committed; retirement failure is not
            # an inference failure, but retained disk usage must be visible.
            self._set(
                warning=f"Local AI is ready, but old assets remain at {backup}: {exc}"
            )

    def _run(self):
        stage = None
        terminal = None
        error = None
        self._deadline = time.monotonic() + TOTAL_TIMEOUT_SECONDS
        try:
            self._check()
            self.root.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".ai-setup-", dir=self.root.parent))
            runtime = [asset for asset in ASSETS if asset.member]
            if all(self._verify_asset(self.root, asset) for asset in runtime):
                for asset in runtime:
                    self._check()
                    shutil.copyfile(self.root / asset.name, stage / asset.name)
            else:
                archive = stage / "runtime.tgz"
                self._download(
                    ARCHIVE_URL, archive, ARCHIVE_SHA512, "sha512", MAX_ARCHIVE_BYTES
                )
                self._set(status="verifying")
                self._extract(archive, stage)
                archive.unlink()
            self._set(status="downloading")
            model = ASSETS[-1]
            if self._verify_asset(self.root, model):
                shutil.copyfile(self.root / model.name, stage / model.name)
            else:
                self._download(
                    MODEL_URL, stage / model.name, model.sha256, "sha256", model.size
                )
            self._set(status="verifying")
            if not self._verify(stage):
                raise ValueError("Installed asset verification failed")
            self._activate(stage)
        except _Cancelled:
            terminal = "cancelled"
        except Exception as exc:
            # Own all worker failures, including HTTP IncompleteRead; no dead
            # thread may leave callers polling a running status indefinitely.
            terminal = "cancelled" if self._cancel.is_set() else "failed"
            error = None if terminal == "cancelled" else str(exc)
        finally:
            try:
                if stage is not None and stage.exists():
                    shutil.rmtree(stage)
            except OSError as exc:
                terminal = "failed"
                error = f"Could not clean partial setup directory: {exc}"
            finally:
                self._deadline = None
                if terminal:
                    self._set(status=terminal, asset=None, error=error)
