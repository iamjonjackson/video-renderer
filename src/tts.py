import os
import json
import base64
import subprocess
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError

API_URL = "https://api.mistral.ai/v1/audio/speech"


def get_api_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise RuntimeError(
            "MISTRAL_API_KEY not set. Provide it via environment (e.g. from a "
            "Drive file read into the env at render time); never paste it in chat."
        )
    return key


def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str = "voxtral-mini-tts-2603",
                  fmt: str = "mp3") -> str:
    """Synthesize one narration clip via the Mistral TTS REST API; return its path."""
    payload: dict = {"model": model, "input": text, "response_format": fmt}
    if voice_id:
        payload["voice_id"] = voice_id
    elif voice_slug:
        payload["voice"] = voice_slug

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
    """Duration of an audio file in seconds via ffprobe (falls back to bundled ffmpeg)."""
    probe = _ffprobe_path()
    out = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _ffprobe_path() -> str:
    from shutil import which
    p = which("ffprobe")
    if p:
        return p
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cand = str(Path(ffmpeg).with_name("ffprobe"))
    if Path(cand).exists():
        return cand
    raise RuntimeError("ffprobe not found; install ffmpeg or imageio-ffmpeg")
