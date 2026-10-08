import os
import json
import os
import base64
import subprocess
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError

API_URL = "https://api.mistral.ai/v1/audio/speech"
VOICES_URL = "https://api.mistral.ai/v1/audio/voices"

_default_voice_cache: str | None = None


def get_api_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise RuntimeError(
            "MISTRAL_API_KEY not set. Provide it via environment (e.g. from a "
            "Drive file read into the env at render time); never paste it in chat."
        )
    return key


FALLBACK_VOICE_SLUGS = [
    "gb_jane_neutral",
    "en_gb_jane_neutral",
    "en-GB-jane_neutral",
    "en_jane_neutral",
    "en_emma_neutral",
    "en_paul_neutral",
    "casual_male",
]


def default_voice() -> str:
    """Pick a default voice: first en_* slug from /v1/audio/voices."""
    global _default_voice_cache
    if _default_voice_cache:
        return _default_voice_cache
    req = _rq.Request(
        VOICES_URL,
        headers={"Authorization": f"Bearer {get_api_key()}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with _rq.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"voices list HTTP {e.code}: {detail}") from e
    voices = None
    if isinstance(body, list):
        voices = body
    elif isinstance(body, dict):
        for key in ("voices", "data", "results", "items"):
            if isinstance(body.get(key), list):
                voices = body[key]
                break
    slugs = []
    if voices is not None:
        for v in voices:
            if isinstance(v, str):
                slugs.append(v)
            elif isinstance(v, dict):
                s = v.get("slug") or v.get("id") or v.get("name")
                if s:
                    slugs.append(s)
    for s in slugs:
        if s.startswith("en_gb") or s.startswith("gb_"):
            _default_voice_cache = s
            return s
    for s in slugs:
        if s.startswith("en_"):
            _default_voice_cache = s
            return s
    if slugs:
        _default_voice_cache = slugs[0]
        return slugs[0]
    print(f"[warn] voices list empty (body keys: "
          f"{list(body) if isinstance(body, dict) else type(body).__name__}); "
          f"falling back to {FALLBACK_VOICE_SLUGS[0]}")
    _default_voice_cache = FALLBACK_VOICE_SLUGS[0]
    return _default_voice_cache


def _speech(payload: dict) -> dict:
    req = _rq.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {get_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Mistral TTS API error {e.code}: {detail}") from e


def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str = "voxtral-mini-tts-2603",
                  fmt: str = "mp3") -> str:
    """Synthesize one narration clip via the Mistral TTS REST API; return its path."""
    payload: dict = {"model": model, "input": text, "response_format": fmt}
    tried = []

    def base(voice: str | None, use_id: bool = False) -> dict:
        p = dict(payload)
        if use_id:
            p["voice_id"] = voice
        else:
            p["voice"] = voice
        return p

    if voice_id:
        body = _speech(base(voice_id, use_id=True))
    else:
        candidates = ([voice_slug] if voice_slug else []) + \
            [s for s in FALLBACK_VOICE_SLUGS if s != voice_slug]
        if not candidates:
            candidates = [default_voice()]
        last_err = None
        body = None
        for slug in candidates:
            try:
                body = _speech(base(slug))
                break
            except RuntimeError as e:
                msg = str(e)
                if "invalid_voice" in msg or "Voice" in msg or " not found" in msg:
                    print(f"[warn] voice '{slug}' rejected, trying next")
                    tried.append(slug)
                    last_err = e
                    continue
                raise
        if body is None:
            raise RuntimeError(
                f"No usable voice (tried: {tried}). Last error: {last_err}"
            )

    audio_b64 = body.get("audio_data") or body.get("audio")
    if not audio_b64:
        raise RuntimeError(f"Unexpected TTS response keys: {list(body)}")
    Path(out_path).write_bytes(base64.b64decode(audio_b64))
    return str(out_path)

    req = _rq.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {get_api_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Mistral TTS API error {e.code}: {detail}") from e

    audio_b64 = body.get("audio_data") or body.get("audio")
    if not audio_b64:
        raise RuntimeError(f"Unexpected TTS response keys: {list(body)}")
    Path(out_path).write_bytes(base64.b64decode(audio_b64))
    return str(out_path)


def audio_duration(path: str) -> float:
    """Duration of an audio file in seconds via ffprobe or ffmpeg fallback."""
    from shutil import which
    if which("ffprobe"):
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    # No ffprobe: ask ffmpeg to decode and report duration from stderr.
    ffmpeg = which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-i", path, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    import re
    matches = re.findall(r"time=(\d+):(\d+):(\d+\.\d+)", proc.stderr)
    if not matches:
        raise RuntimeError(f"Could not determine duration of {path}")
    h, m, s = matches[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)
