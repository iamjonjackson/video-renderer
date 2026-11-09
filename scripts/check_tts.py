"""make one short live request and check that the audio can be decoded"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import tts


def main():
    try:
        options = tts.resolve_options()
        output = Path("output") / f"tts-{options['provider']}.{options['fmt']}"
        output.parent.mkdir(parents=True, exist_ok=True)
        # use a short sentence to keep the live check within a small quota
        tts.synth_to_file("This is a short narration test.", str(output), **options)
        print(f"[done] {output} ({tts.audio_duration(str(output)):.2f}s, decoded successfully)")
    except tts.TTSError as error:
        print(f"[error] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
