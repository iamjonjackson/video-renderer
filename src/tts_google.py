"""Google Gemini TTS adapter (stdlib-only REST client).

Gemini TTS returns base64-encoded raw PCM (16-bit, mono, 24 kHz) inside a
JSON body; this adapter wraps it into a WAV file MoviePy can decode.
"""
import base64
import json
import os
import wave
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError

from tts import MissingAPIKeyError, TTSProviderError

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
DEFAULT_STYLE = "Read aloud in a neutral, warm narration voice"

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # bytes (16-bit)
CHANNELS = 1


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise MissingAPIKeyError("GOOGLE_API_KEY")
    return key


def synth_to_file(text: str, out_path: str, voice: str | None = None,
                  model: str | None = None, style: str | None = None,
                  timeout: int = 300) -> str:
    """Synthesize one narration clip via Gemini TTS; return the .wav path."""
    key = get_api_key()
    model = model or os.environ.get("GOOGLE_TTS_MODEL") or DEFAULT_MODEL
    voice = voice or os.environ.get("GOOGLE_TTS_VOICE") or DEFAULT_VOICE
    style = style or os.environ.get("GOOGLE_TTS_STYLE") or DEFAULT_STYLE

    payload = {
        "contents": [{"parts": [{"text": f"{style}: {text}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }
    req = _rq.Request(
        API_URL.format(model=model),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    try:
        with _rq.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise TTSProviderError(f"Gemini TTS API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSProviderError(f"Gemini TTS request failed: {e.reason}") from e

    try:
        audio_b64 = body["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
    except (KeyError, IndexError, TypeError) as e:
        raise TTSProviderError(
            f"Unexpected Gemini TTS response: {json.dumps(body)[:300]}"
        ) from e

    out = Path(out_path).with_suffix(".wav")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(base64.b64decode(audio_b64))
    print(f"[voice] google '{voice}' ({model})")
    return str(out)