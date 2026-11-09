"""create subtitles from the narration text and timings already there"""
from dataclasses import dataclass
from math import ceil
from pathlib import Path
import textwrap


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str


def timestamp(milliseconds: int) -> str:
    # srt needs hours:minutes:seconds,milliseconds, with a comma before the ms
    seconds, ms = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def narration_cues(text: str, start: float, duration: float) -> list[Cue]:
    """split narration into short cues that fit on two lines

    known when the audio starts and ends, but not when each word is spoken
    use the amount of text to estimate the timings in between
    """
    text = " ".join(text.split())
    # round before formatting so 59.9996s rolls over to the next minute properly
    start_ms, end_ms = round(start * 1000), round((start + duration) * 1000)
    if not text or end_ms <= start_ms:
        return []
    # keep it readable: up to 42 characters per line and two lines per cue.
    lines = textwrap.wrap(text, width=42, break_on_hyphens=False)
    chunks = ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]
    total = sum(len(chunk) for chunk in chunks)
    cues, consumed, cursor = [], 0, start_ms
    for chunk in chunks:
        consumed += len(chunk)
        boundary = start_ms + round((end_ms - start_ms) * consumed / total)
        # for very slow speech, keep the same text across shorter cues so
        # no single cue lasts more than 6.5 seconds
        parts = max(1, ceil((boundary - cursor) / 6500))
        chunk_start = cursor
        for part in range(1, parts + 1):
            end = chunk_start + round((boundary - chunk_start) * part / parts)
            if end > cursor:
                cues.append(Cue(cursor, end, chunk))
                cursor = end
    return cues


def write_srt(path: Path, cues: list[Cue]) -> None:
    # each block needs a number, its timings, the text, then a blank line
    path.write_text("".join(
        f"{i}\n{timestamp(cue.start_ms)} --> {timestamp(cue.end_ms)}\n{cue.text}\n\n"
        for i, cue in enumerate(cues, 1)
    ), encoding="utf-8")
