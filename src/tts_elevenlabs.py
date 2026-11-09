"""ElevenLabs TTS adapter (stdlib-only REST client).

ElevenLabs returns raw MP3 bytes directly from /v1/text-to-speech/{voice_id}.
Free tier: ~10,000 credits/month, non-commercial use only, attribution required.
"""
import json
import os
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError

from tts import MissingAPIKeyError, TTSProviderError

BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"

_default_voice_cache: str | None = None


def get_api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise MissingAPIKeyError("ELEVENLABS_API_KEY")
    return key


def _request(req: _rq.Request, timeout: int) -> bytes:
    try:
        with _rq.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise TTSProviderError(f"ElevenLabs API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSProviderError(f"ElevenLabs request failed: {e.reason}") from e


def default_voice(key: str) -> str:
    """Pick a default voice: first 'premade' voice from /v1/voices.

    Free-tier keys may not be allowed to use Voice Library voices via the
    API, so premade voices are preferred.
    """
    global _default_voice_cache
    if _default_voice_cache:
        return _default_voice_cache
    req = _rq.Request(f"{BASE_URL}/voices",
                      headers={"xi-api-key": key, "Accept": "application/json"},
                      method="GET")
    body = json.loads(_request(req, timeout=60))
    voices = body.get("voices") or []
    premade = [v for v in voices if v.get("category") == "premade"] or voices
    if not premade:
        raise TTSProviderError("ElevenLabs returned no voices for this key")
    _default_voice_cache = premade[0]["voice_id"]
    print(f"[voice] elevenlabs default '{premade[0].get('name', '?')}'")
    return _default_voice_cache


def synth_to_file(text: str, out_path: str, voice: str | None = None,
                  model: str | None = None, timeout: int = 300) -> str:
    """Synthesize one narration clip via ElevenLabs; return the .mp3 path."""
    key = get_api_key()
    voice_id = voice or os.environ.get("ELEVENLABS_VOICE_ID") or default_voice(key)
    model = model or os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL

    req = _rq.Request(
        f"{BASE_URL}/text-to-speech/{voice_id}?output_format={OUTPUT_FORMAT}",
        data=json.dumps({"text": text, "model_id": model}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
        method="POST",
    )
    audio = _request(req, timeout=timeout)
    if not audio:
        raise TTSProviderError("ElevenLabs returned an empty audio response")

    out = Path(out_path).with_suffix(".mp3")
    out.write_bytes(audio)
    print(f"[voice] elevenlabs '{voice_id}' ({model})")
    return str(out)