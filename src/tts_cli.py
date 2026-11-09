"""One-shot TTS CLI: synthesize a single narration clip.

Examples:
    python src/tts_cli.py --provider google --text "Hello from Gemini." \
        --output temp/gemini.wav --voice Kore

    python src/tts_cli.py --list-providers
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:  # python -m src.tts_cli
    from .tts import (
        PROVIDERS,
        TTSError,
        resolve_format,
        resolve_provider,
        synth_to_file,
    )
except ImportError:  # python src/tts_cli.py
    from tts import (  # type: ignore[no-redef]
        PROVIDERS,
        TTSError,
        resolve_format,
        resolve_provider,
        synth_to_file,
    )


def _output_path(raw: str | None, fmt: str) -> Path:
    """Return an output path whose extension matches the provider format."""
    path = Path(raw) if raw else Path("output") / "tts"
    suffix = path.suffix.lower().lstrip(".")
    if not suffix:
        return path.with_suffix(f".{fmt}")
    if suffix != fmt:
        raise ValueError(
            f"output extension '.{suffix}' does not match the {fmt} format; "
            f"use '.{fmt}' or omit the extension"
        )
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tts_cli.py",
        description="Synthesize one narration clip without rendering a video.",
        epilog=(
            "Provider defaults to TTS_PROVIDER, then mistral. The output "
            "extension is added or validated from the provider format."
        ),
    )
    parser.add_argument(
        "--provider", choices=PROVIDERS,
        help="TTS provider (default: TTS_PROVIDER or mistral)",
    )
    parser.add_argument("--text", help="Text to synthesize")
    parser.add_argument(
        "-o", "--output",
        help="Output audio path (default: output/tts.<format>)",
    )
    parser.add_argument(
        "--voice", "--voice-slug", dest="voice", metavar="VOICE",
        help="Provider voice slug/name (Google: Kore; Mistral: built-in slug)",
    )
    parser.add_argument(
        "--voice-id", metavar="ID",
        help="Provider voice ID (ElevenLabs, cloned Mistral voices)",
    )
    parser.add_argument(
        "--model",
        help="Provider model or fal endpoint override",
    )
    parser.add_argument(
        "--format", "--fmt", dest="format", choices=("mp3", "wav"),
        help="Audio format where supported (Google is always wav)",
    )
    parser.add_argument(
        "--style",
        help="Provider style instructions (Google speech_metadata; fal Gemini)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Require an explicit voice; do not substitute provider defaults",
    )
    parser.add_argument(
        "--list-providers", action="store_true",
        help="List supported providers and exit",
    )
    args = parser.parse_args(argv)

    if args.list_providers:
        print("\n".join(PROVIDERS))
        return 0

    if not args.text:
        parser.error("--text is required (or use --list-providers)")
    if not args.text.strip():
        parser.error("--text must not be empty")

    try:
        provider = resolve_provider(
            {"provider": args.provider} if args.provider else None
        )
        fmt = resolve_format(provider, args.format, args.model)
        out_path = _output_path(args.output, fmt)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = synth_to_file(
            args.text, str(out_path),
            voice_slug=args.voice, voice_id=args.voice_id,
            model=args.model, fmt=fmt, provider=provider,
            style=args.style, strict=args.strict,
        )
    except (TTSError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"wrote: {result} [{provider} / {fmt}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
