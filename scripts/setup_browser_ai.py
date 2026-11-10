"""Install pinned browser AI data assets without executing package scripts."""

import base64
import hashlib
import tarfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1] / "studio" / "ai-assets"
REVISION = "391ed11137586e383b1be0fab9acf01d282c2e11"
INTEGRITY = "ZvoRdQAn+E+18EvQ9qS036gudiI9rbZRBJgG/qNICPPwrA0Y6SMMdbziz/j7K/0WxcbJlhaRraVIYsnEy732NA=="


def download(url, target, digest, algorithm="sha256"):
    target.parent.mkdir(parents=True, exist_ok=True)
    if (
        target.exists()
        and hashlib.new(algorithm, target.read_bytes()).hexdigest() == digest
    ):
        print(f"Verified {target.name}", flush=True)
        return
    temporary = target.with_suffix(target.suffix + ".partial")
    checksum = hashlib.new(algorithm)
    print(f"Downloading {target.name}", flush=True)
    with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            checksum.update(chunk)
            output.write(chunk)
    if checksum.hexdigest() != digest:
        temporary.unlink()
        raise ValueError(f"Checksum mismatch: {target.name}")
    temporary.replace(target)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    archive = ROOT / "wllama-3.13.0.tgz"
    download(
        "https://registry.npmjs.org/@wllama/wllama/-/wllama-3.13.0.tgz",
        archive,
        base64.b64decode(INTEGRITY).hex(),
        "sha512",
    )
    with tarfile.open(archive) as package:
        for name, target in [
            ("esm/index.js", "wllama.js"),
            ("esm/wasm/wllama.wasm", "wllama.wasm"),
            ("LICENCE", "WLLAMA-LICENSE"),
        ]:
            source = package.extractfile("package/" + name)
            if source is None:
                raise ValueError(f"Missing asset: {name}")
            (ROOT / target).write_bytes(source.read())
    archive.unlink()
    download(
        f"https://huggingface.co/unsloth/SmolLM2-360M-Instruct-GGUF/resolve/{REVISION}/SmolLM2-360M-Instruct-Q8_0.gguf",
        ROOT / "smollm2.gguf",
        "fcb111da119fa42ab856d491088a844b290579e9810bd0792252297d8c6cd7a8",
    )
    print(
        "Browser AI ready: SmolLM2-360M-Instruct Q8_0 (Apache-2.0), wllama 3.13.0 (MIT).",
        flush=True,
    )


if __name__ == "__main__":
    main()
