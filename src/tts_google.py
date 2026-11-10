"""Google Gemini TTS adapter (Gemini API / Google AI Studio key).

POST {BASE}/models/{model}:generateContent with x-goog-api-key auth. The
audio comes back base64-encoded in candidates[0].content.parts[0].inlineData:
Gemini 3.8+ TTS models return a complete WAV for unary requests, while
earlier models (2.5 / 3.1 preview) return headerless 16-bit PCM that we wrap
into a WAV here. Both are handled, so the model can be swapped freely.

Stdlib only (urllib + wave), mirroring tts.py.
"""
import base64
import io
import json
import re
import wave
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError

from tts import TTSError, require_key

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# First entry is the default; the rest are tried in order if a model is
# unavailable (404 / NOT_FOUND), e.g. retired or not enabled for the key.
DEFAULT_MODELS = [
    "gemini-3.8-flash-lite-tts",
    "gemini-3.8-flash-tts",
    "gemini-3.1-flash-tts-preview",
]
DEFAULT_VOICE = "Kore"
DEFAULT_STYLE = "Read aloud in a neutral, warm narration voice"

# Earlier Gemini TTS models take style as a spoken-prompt prefix and return
# raw PCM; 3.8+ take speechMetadata.style and read the text verbatim.
_LEGACY_MODEL = re.compile(r"^gemini-(2\.|3\.[0-5](?!\d))")


def get_api_key() -> str:
    return require_key(
        "GOOGLE_API_KEY", "GEMINI_API_KEY",
        hint="Create a free key at https://aistudio.google.com/apikey and "
             "export it; never paste it in chat.",
    )


def is_legacy_model(model: str) -> bool:
    return bool(_LEGACY_MODEL.match(model))


def build_payload(text: str, model: str, voice: str, style: str) -> dict:
    """generateContent body for single-speaker narration."""
    # prebuiltVoiceConfig.voiceName works on every generation for prebuilt voices.
    speech_config = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
    if is_legacy_model(model):
        part = {"text": f"{style}: {text}" if style else text}
    else:
        part = {"text": text}
        if style:
            part["speechMetadata"] = {"style": style}
    return {
        "contents": [{"role": "user", "parts": [part]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": speech_config,
        },
    }


def _post(model: str, payload: dict) -> dict:
    req = _rq.Request(
        f"{BASE_URL}/models/{model}:generateContent",
        data=json.dumps(payload).encode(),
        headers={
            "x-goog-api-key": get_api_key(),
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
        raise TTSError(f"Google TTS API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSError(f"Google TTS API unreachable: {e.reason}") from e


def _pcm_rate(mime: str, default: int = 24000) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else default


def to_wav_bytes(audio: bytes, mime: str = "") -> bytes:
    """Return WAV bytes: pass through RIFF/WAV, wrap headerless L16 PCM."""
    if audio[:4] == b"RIFF":
        return audio
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(_pcm_rate(mime))
        w.writeframes(audio)
    return buf.getvalue()


def _extract_audio(body: dict) -> tuple[bytes, str]:
    try:
        for part in body["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), inline.get("mimeType", "")
    except (KeyError, IndexError, TypeError):
        pass
    reason = ""
    if isinstance(body, dict):
        fb = body.get("promptFeedback") or {}
        cand = (body.get("candidates") or [{}])[0]
        reason = fb.get("blockReason") or cand.get("finishReason") or ""
    raise TTSError(f"Google TTS returned no audio{f' ({reason})' if reason else ''}; "
                   f"keys: {list(body) if isinstance(body, dict) else type(body).__name__}")


def _is_model_missing(err: TTSError) -> bool:
    msg = str(err)
    return " 404" in msg or "NOT_FOUND" in msg or "is not found" in msg


def _is_rate_limited(err: TTSError) -> bool:
    msg = str(err)
    return " 429" in msg or "RESOURCE_EXHAUSTED" in msg


def _is_voice_rejected(err: TTSError) -> bool:
    msg = str(err).lower()
    return " 400" in msg and "voice" in msg


def synth_to_file(text: str, out_path: str, voice: str | None = None,
                  model: str | None = None, style: str | None = None) -> str:
    """Synthesize `text` to a WAV at `out_path`; return the path."""
    get_api_key()  # fail fast (TTSKeyMissing) before any request
    voice = voice or DEFAULT_VOICE
    style = DEFAULT_STYLE if style is None else style
    models = [model] if model else list(DEFAULT_MODELS)
    last_err: TTSError | None = None
    for m in models:
        try:
            body = _post(m, build_payload(text, m, voice, style))
        except TTSError as e:
            if voice != DEFAULT_VOICE and _is_voice_rejected(e):
                print(f"[warn] Google voice '{voice}' rejected, falling back to '{DEFAULT_VOICE}'")
                voice = DEFAULT_VOICE
                body = _post(m, build_payload(text, m, voice, style))
            elif not model and (_is_model_missing(e) or _is_rate_limited(e)):
                # Free-tier quotas are per model, so the next model may still have headroom.
                why = "rate-limited" if _is_rate_limited(e) else "unavailable"
                print(f"[warn] Google TTS model '{m}' {why}, trying next")
                last_err = e
                continue
            else:
                raise
        audio, mime = _extract_audio(body)
        Path(out_path).write_bytes(to_wav_bytes(audio, mime))
        print(f"[voice] google '{voice}' via {m}")
        return str(out_path)
    raise TTSError(f"No usable Google TTS model (tried: {models}). Last error: {last_err}")
