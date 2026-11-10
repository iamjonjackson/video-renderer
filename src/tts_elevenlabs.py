"""ElevenLabs TTS adapter.

POST /v1/text-to-speech/{voice_id} with xi-api-key auth returns raw MP3
bytes (no base64). The default voice is resolved from the account's own
GET /v1/voices list, because which voices a key may use depends on the
plan and account age: free-tier keys cannot use Voice Library voices via
the API, and the legacy Default (premade) voices only exist on accounts
created before March 2026 (retired 31 Dec 2026). Set ELEVENLABS_VOICE_ID
(or meta.tts.voice) to pin one.

Free tier: non-commercial use only, attribution to ElevenLabs required.

Stdlib only (urllib), mirroring tts.py.
"""
import json
from pathlib import Path
from urllib import parse as _parse
from urllib import request as _rq
from urllib.error import HTTPError, URLError

from tts import TTSError, require_key

BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"
# 128 kbps MP3 at 44.1 kHz is available on every plan (192 kbps needs Creator+).
OUTPUT_FORMAT = "mp3_44100_128"

_default_voice_cache: str | None = None
_attribution_shown = False


def get_api_key() -> str:
    return require_key(
        "ELEVENLABS_API_KEY",
        hint="Create one at https://elevenlabs.io/app/settings/api-keys and "
             "export it; never paste it in chat.",
    )


def _request(method: str, path: str, payload: dict | None = None,
             accept: str = "application/json", query: dict | None = None) -> bytes:
    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + _parse.urlencode(query)
    headers = {"xi-api-key": get_api_key(), "Accept": accept}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = _rq.Request(url, data=data, headers=headers, method=method)
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            return resp.read()
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise TTSError(f"ElevenLabs API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSError(f"ElevenLabs API unreachable: {e.reason}") from e


def pick_voice(voices: list[dict]) -> str | None:
    """Prefer a premade British voice, then any premade, then the first voice."""
    usable = [v for v in voices if isinstance(v, dict) and v.get("voice_id")]
    premade = [v for v in usable if v.get("category") == "premade"]

    def british(v: dict) -> bool:
        labels = v.get("labels") or {}
        return "brit" in str(labels.get("accent", "")).lower()

    for pool in ([v for v in premade if british(v)], premade, usable):
        if pool:
            return pool[0]["voice_id"]
    return None


def default_voice() -> str:
    """First usable voice on this account (cached per process)."""
    global _default_voice_cache
    if _default_voice_cache:
        return _default_voice_cache
    try:
        body = json.loads(_request("GET", "/voices"))
    except TTSError as e:
        if "voices_read" in str(e):
            raise TTSError(
                "this ElevenLabs API key lacks the Voices (read) permission, so "
                "the default voice cannot be looked up; set ELEVENLABS_VOICE_ID, "
                "or enable Voices: Read on the key") from e
        raise TTSError(f"could not list ElevenLabs voices ({e}); set "
                       f"ELEVENLABS_VOICE_ID to a voice your plan can use") from e
    voice = pick_voice(body.get("voices", []) if isinstance(body, dict) else [])
    if not voice:
        raise TTSError(
            "no ElevenLabs voices available to this API key. Free-tier keys "
            "cannot use Voice Library voices via the API; set ELEVENLABS_VOICE_ID "
            "to a voice in your account's My Voices"
        )
    _default_voice_cache = voice
    return voice


def synth_to_file(text: str, out_path: str, voice_id: str | None = None,
                  model: str | None = None) -> str:
    """Synthesize `text` to an MP3 at `out_path`; return the path."""
    global _attribution_shown
    get_api_key()  # fail fast (TTSKeyMissing) before any request
    voice = voice_id or default_voice()
    audio = _request(
        "POST", f"/text-to-speech/{_parse.quote(voice, safe='')}",
        payload={"text": text, "model_id": model or DEFAULT_MODEL},
        accept="audio/mpeg", query={"output_format": OUTPUT_FORMAT},
    )
    # Errors arrive as JSON with a 4xx, but guard against an empty/JSON 200.
    if not audio or audio[:1] in (b"{", b"["):
        raise TTSError(f"ElevenLabs returned no audio: {audio[:200]!r}")
    Path(out_path).write_bytes(audio)
    print(f"[voice] elevenlabs '{voice}' via {model or DEFAULT_MODEL}")
    if not _attribution_shown:
        _attribution_shown = True
        print("[note] ElevenLabs free tier: non-commercial use only and "
              "attribution required (credit 'elevenlabs.io' with the video)")
    return str(out_path)
