"""SRT subtitle generation from narration timing.

The renderer knows every narration clip's text, absolute start time and
audio duration. This module turns those segments into readable subtitle
cues (<= 2 lines of ~42 chars, <= ~7s each) and serializes/parses SRT.
"""
import re
from pathlib import Path

MAX_LINE_CHARS = 42
MAX_LINES = 2
MAX_CUE_SECONDS = 7.0
MIN_CUE_SECONDS = 0.8


def format_timestamp(seconds: float) -> str:
    """Seconds -> 'HH:MM:SS,mmm' (SRT uses a comma before milliseconds)."""
    ms = max(0, int(round(seconds * 1000)))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_timestamp(ts: str) -> float:
    m = re.fullmatch(r"(\d+):(\d{2}):(\d{2}),(\d{3})", ts.strip())
    if not m:
        raise ValueError(f"bad SRT timestamp: {ts!r}")
    h, mi, s, ms = map(int, m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def wrap_lines(text: str, width: int = MAX_LINE_CHARS) -> list[str]:
    """Greedy word wrap; a single over-long word gets its own line."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if len(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;:])\s+", text.strip())
    return [p for p in parts if p]


def _split_clauses(text: str, max_chars: int) -> list[str]:
    """Break text into pieces that each fit in one cue (<= max_chars),
    preferring sentence, then comma, then word boundaries."""
    out = []
    for sentence in _split_sentences(text):
        if len(sentence) <= max_chars:
            out.append(sentence)
            continue
        # Pack comma-separated clauses, falling back to a word-level wrap.
        clauses = re.split(r"(?<=,)\s+", sentence)
        cur = ""
        for clause in clauses:
            trial = f"{cur} {clause}".strip()
            if len(trial) <= max_chars:
                cur = trial
                continue
            if cur:
                out.append(cur)
            if len(clause) <= max_chars:
                cur = clause
            else:
                pieces = wrap_lines(clause, max_chars)
                out.extend(pieces[:-1])
                cur = pieces[-1]
        if cur:
            out.append(cur)
    return out


def chunk_narration(text: str, start: float, duration: float,
                    max_line_chars: int = MAX_LINE_CHARS,
                    max_lines: int = MAX_LINES,
                    max_cue_seconds: float = MAX_CUE_SECONDS) -> list[dict]:
    """Split one narration clip into cues timed proportionally to length.

    Returns [{"start", "end", "text"}] with absolute times; `text` may
    contain a newline (two-line cue).
    """
    text = " ".join(text.split())
    if not text or duration <= 0:
        return []
    max_chars = max_line_chars * max_lines
    pieces = _split_clauses(text, max_chars)

    # Merge short neighbours so we don't flash tiny cues, as long as the
    # merged cue still fits on max_lines lines.
    merged: list[str] = []
    for p in pieces:
        if merged:
            trial = f"{merged[-1]} {p}"
            if len(wrap_lines(trial, max_line_chars)) <= max_lines:
                merged[-1] = trial
                continue
        merged.append(p)

    # Halve any cue that would run longer than max_cue_seconds (timing is
    # proportional to characters, so halving by characters halves its span)
    # until all fit or the cue is a single word.
    total_chars = sum(len(p) for p in merged)
    sec_per_char = duration / total_chars
    final: list[str] = []
    stack = list(reversed(merged))
    while stack:
        p = stack.pop()
        words = p.split()
        if len(p) * sec_per_char <= max_cue_seconds or len(words) == 1:
            final.append(p)
            continue
        acc, cut = 0, 1
        for k, w in enumerate(words[:-1], 1):
            acc += len(w) + 1
            cut = k
            if acc >= len(p) / 2:
                break
        stack.append(" ".join(words[cut:]))
        stack.append(" ".join(words[:cut]))

    total_chars = sum(len(p) for p in final)
    cues, t = [], start
    for idx, p in enumerate(final):
        span = duration * len(p) / total_chars
        end = start + duration if idx == len(final) - 1 else t + span
        cues.append({"start": t, "end": end,
                     "text": "\n".join(wrap_lines(p, max_line_chars))})
        t = end
    return cues


def build_cues(segments: list[dict]) -> list[dict]:
    """segments: [{"text", "start", "duration"}] (absolute seconds)."""
    cues = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        cues.extend(chunk_narration(seg["text"], seg["start"], seg["duration"]))
    return cues


def to_srt(cues: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(f"{i}\n{format_timestamp(c['start'])} --> "
                      f"{format_timestamp(c['end'])}\n{c['text']}\n")
    return "\n".join(blocks)


def parse_srt(content: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", content.strip().replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            raise ValueError(f"malformed SRT block: {block!r}")
        int(lines[0])  # sequence number
        start, end = (parse_timestamp(x) for x in lines[1].split("-->"))
        cues.append({"start": start, "end": end, "text": "\n".join(lines[2:])})
    return cues


def write_srt(segments: list[dict], path: str) -> int:
    cues = build_cues(segments)
    Path(path).write_text(to_srt(cues), encoding="utf-8")
    return len(cues)
