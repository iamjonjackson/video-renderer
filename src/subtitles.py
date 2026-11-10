"""SRT subtitle generation from narration text + timing.

Pure functions (no MoviePy / network) so they can be unit-tested:
  format_timestamp  seconds -> "HH:MM:SS,mmm"
  split_cues        narration text + start + duration -> readable timed cues
  build_srt         cues -> SRT file text
  parse_srt         SRT text -> cues (used to prove the output round-trips)

Readability conventions followed: lines <= 42 chars, <= 2 lines per cue,
cues <= ~6.5 s. Time inside a clip is shared between its cues in proportion
to their character count, so cues roughly track speaking pace.
"""
import math
import re

MAX_LINE = 42
MAX_LINES = 2
MAX_CUE_CHARS = MAX_LINE * MAX_LINES
MAX_CUE_SECONDS = 6.5

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def format_timestamp(seconds: float) -> str:
    """Seconds -> SRT timestamp (comma before milliseconds, zero padded)."""
    ms = int(round(max(seconds, 0.0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_timestamp(ts: str) -> float:
    m = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", ts.strip())
    if not m:
        raise ValueError(f"bad SRT timestamp: {ts!r}")
    h, mi, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000


def _split_words(text: str, parts: int) -> list[str]:
    """Split text into `parts` chunks of similar length, on word boundaries."""
    words = text.split()
    if parts <= 1 or len(words) <= 1:
        return [text]
    parts = min(parts, len(words))
    target = len(text) / parts
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        remaining_words = len(words) - i - 1
        remaining_chunks = parts - len(chunks) - 1
        if (len(" ".join(cur)) >= target and remaining_chunks > 0
                and remaining_words >= remaining_chunks):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def wrap_lines(text: str) -> str:
    """Wrap a cue to at most MAX_LINES balanced lines of <= MAX_LINE chars."""
    text = " ".join(text.split())
    if len(text) <= MAX_LINE:
        return text
    lines = _split_words(text, math.ceil(len(text) / MAX_LINE))
    # A single over-long word can't be wrapped; leave it rather than drop text.
    return "\n".join(lines)


def split_cues(text: str, start: float, duration: float) -> list[dict]:
    """Split one narration clip into timed cues.

    Returns [{"start", "end", "text"}] covering [start, start + duration]
    with no gaps/overlaps inside the clip. Text is never dropped or altered
    apart from whitespace normalisation and line wrapping.
    """
    text = " ".join((text or "").split())
    if not text or duration <= 0:
        return []
    total = len(text)

    # 1) sentences, each further split if too long to read or to hold on screen
    pieces = []
    for sent in _SENTENCE_END.split(text):
        est = duration * len(sent) / total
        k = max(math.ceil(len(sent) / MAX_CUE_CHARS),
                math.ceil(est / MAX_CUE_SECONDS))
        pieces.extend(_split_words(sent, k))

    # 2) pack neighbouring short pieces together while the cue stays readable
    packed = []
    for piece in pieces:
        if packed:
            merged = packed[-1] + " " + piece
            if (len(merged) <= MAX_CUE_CHARS
                    and duration * len(merged) / total <= MAX_CUE_SECONDS):
                packed[-1] = merged
                continue
        packed.append(piece)

    # 2b) uneven chunk lengths can still leave a cue over the limit: re-split
    #     any such cue (that has more than one word) until all fit
    changed = True
    while changed:
        changed = False
        out = []
        for piece in packed:
            if (duration * len(piece) / total > MAX_CUE_SECONDS
                    and len(piece.split()) > 1):
                out.extend(_split_words(piece, 2))
                changed = True
            else:
                out.append(piece)
        packed = out

    # 3) time shared in proportion to characters; last cue ends exactly at end
    cues, t = [], start
    for i, piece in enumerate(packed):
        end = (start + duration if i == len(packed) - 1
               else t + duration * len(piece) / total)
        cues.append({"start": t, "end": end, "text": wrap_lines(piece)})
        t = end
    return cues


def build_srt(cues: list[dict]) -> str:
    blocks = []
    for n, c in enumerate(cues, 1):
        blocks.append(f"{n}\n{format_timestamp(c['start'])} --> "
                      f"{format_timestamp(c['end'])}\n{c['text']}\n")
    return "\n".join(blocks)


def parse_srt(srt: str) -> list[dict]:
    """Strict-enough parser: raises ValueError on malformed blocks."""
    cues = []
    for expected, block in enumerate(re.split(r"\n\s*\n", srt.strip()), 1):
        lines = block.split("\n")
        if len(lines) < 3 or lines[0].strip() != str(expected):
            raise ValueError(f"bad cue block #{expected}: {block!r}")
        m = re.fullmatch(r"(\S+) --> (\S+)", lines[1].strip())
        if not m:
            raise ValueError(f"bad timing line in cue #{expected}: {lines[1]!r}")
        cues.append({"start": parse_timestamp(m.group(1)),
                     "end": parse_timestamp(m.group(2)),
                     "text": "\n".join(lines[2:])})
    return cues
