"""Text-to-speech narration with pluggable providers.

The public contract is unchanged: ``render.py`` calls
``synth_to_file(text, out_path, voice_slug=..., voice_id=..., model=...,
fmt=..., provider=...)`` and gets back the path to a decodable audio file.

Provider selection order:
1. ``provider=`` argument (render.py passes ``voice.provider`` / ``meta.tts.provider``)
2. the ``TTS_PROVIDER`` environment variable
3. ``mistral``

Adapters are deliberately small and stdlib-only (``urllib``), mirroring the
original Mistral client. Supported providers:

- ``mistral``    — Voxtral TTS (``MISTRAL_API_KEY``)
- ``google``     — Gemini TTS (``GOOGLE_API_KEY``)
- ``elevenlabs`` — ElevenLabs TTS (``ELEVENLABS_API_KEY``)
- ``fal``        — any fal.ai TTS endpoint (``FAL_KEY``)
"""
import base64
import json
import os
import re
import ssl
import wave
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError
from urllib.parse import quote

PROVIDERS = ("mistral", "google", "elevenlabs", "fal")
DEFAULT_PROVIDER = "mistral"

# --- Mistral -----------------------------------------------------------------
API_URL = "https://api.mistral.ai/v1/audio/speech"
DEFAULT_MISTRAL_MODEL = "voxtral-mini-tts-2603"

FALLBACK_VOICE_SLUGS = [
    "gb_jane_neutral",
    "en_gb_jane_neutral",
    "en-GB-jane_neutral",
    "en_jane_neutral",
    "en_emma_neutral",
    "en_paul_neutral",
    "casual_male",
]

# --- Google (Gemini TTS) -----------------------------------------------------
# Interactions API is the current TTS surface (generateContent is legacy).
GOOGLE_API_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
DEFAULT_GOOGLE_MODEL = "gemini-3.8-flash-tts"
DEFAULT_GOOGLE_VOICE = "Kore"
DEFAULT_GOOGLE_STYLE = "Read in a neutral, warm narration voice."
DEFAULT_GOOGLE_SAMPLE_RATE = 24000

# --- ElevenLabs --------------------------------------------------------------
ELEVENLABS_API_URL = "https://api.elevenlabs.io"
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
# Sarah — default voice that works on the free-tier API; override explicitly.
DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

# --- fal.ai ------------------------------------------------------------------
FAL_API_URL = "https://fal.run"
DEFAULT_FAL_ENDPOINT = "fal-ai/elevenlabs/tts/eleven-v3"
DEFAULT_FAL_VOICE = "Rachel"
DEFAULT_FAL_GEMINI_VOICE = "Kore"

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = ssl.create_default_context()


class TTSError(RuntimeError):
    """Narration failed for a provider (API, network, or config problem)."""


class MissingAPIKey(TTSError):
    """The provider's API key env var is not set."""


class StrictVoiceError(TTSError):
    """Strict voice mode was requested but no explicit usable voice exists."""


def get_api_key(env_var: str = "MISTRAL_API_KEY", provider: str | None = None) -> str:
    key = os.environ.get(env_var)
    if not key:
        who = f" for {provider}" if provider else ""
        raise MissingAPIKey(
            f"{env_var} not set{who}. Provide it via the environment (e.g. from "
            "a .env file read at render time); never paste it in chat."
        )
    return key


def resolve_provider(cfg: dict | None = None) -> str:
    """Choose the TTS provider from spec config, then TTS_PROVIDER, then default."""
    raw = (cfg or {}).get("provider") or os.environ.get("TTS_PROVIDER") or DEFAULT_PROVIDER
    provider = str(raw).strip().lower()
    if provider not in PROVIDERS:
        raise TTSError(
            f"Unknown TTS provider '{raw}' (choose from: {', '.join(PROVIDERS)})"
        )
    return provider


VOICE_ENV_VARS = {
    "mistral": ("MISTRAL_VOICE", "slug"),
    "google": ("GOOGLE_VOICE", "slug"),
    "elevenlabs": ("ELEVENLABS_VOICE_ID", "id"),
    "fal": ("FAL_VOICE", "slug"),
}


def resolve_voice(provider: str, voice_slug: str | None = None,
                  voice_id: str | None = None) -> tuple[str | None, str | None]:
    """Apply the provider's env voice override when the spec has no voice.

    Spec ``voice.slug`` / ``voice.name`` / ``voice.voice_id`` always wins;
    environment variables are only a fallback. Returns ``(slug, voice_id)``.
    """
    if voice_slug or voice_id:
        return voice_slug, voice_id
    env_var, kind = VOICE_ENV_VARS.get(provider, (None, None))
    value = os.environ.get(env_var) if env_var else None
    if not value:
        return voice_slug, voice_id
    if kind == "id":
        return voice_slug, value
    return value, voice_id


def resolve_format(provider: str, fmt: str | None = None,
                   model: str | None = None) -> str:
    """Return the audio file extension a provider will actually produce.

    Google always returns WAV (PCM from Gemini is wrapped). ElevenLabs
    defaults to MP3 because its free tier cannot request PCM/WAV; WAV is
    only used when explicitly requested (Pro tier). fal is MP3 unless a
    Gemini endpoint is asked for WAV. Mistral honours mp3/wav (default wav).
    """
    fmt = (fmt or "").strip().lower()
    if provider == "google":
        return "wav"
    if provider == "elevenlabs":
        return "wav" if fmt == "wav" else "mp3"
    if provider == "fal":
        endpoint = (model or os.environ.get("FAL_ENDPOINT") or DEFAULT_FAL_ENDPOINT).lower()
        if "gemini" in endpoint and fmt == "wav":
            return "wav"
        return "mp3"
    return "mp3" if fmt == "mp3" else "wav"


def _http_bytes(url: str, provider: str, payload: dict | None = None,
                headers: dict | None = None, method: str = "GET",
                timeout: int = 300) -> bytes:
    data = json.dumps(payload).encode() if payload is not None else None
    if payload is not None:
        method = "POST"
    req = _rq.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with _rq.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
            return resp.read()
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise TTSError(f"{provider} API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSError(f"{provider} network error: {e.reason}") from e


def _http_json(url: str, provider: str, payload: dict | None = None,
               headers: dict | None = None, method: str = "GET",
               timeout: int = 300) -> dict:
    raw = _http_bytes(url, provider, payload, headers, method, timeout)
    try:
        return json.loads(raw)
    except ValueError as e:
        raise TTSError(f"{provider} returned invalid JSON") from e


def _write_pcm_wav(pcm: bytes, out_path: str, rate: int = 24000,
                   channels: int = 1, sample_width: int = 2) -> str:
    """Wrap raw little-endian PCM in a RIFF/WAVE container."""
    if sample_width > 1 and len(pcm) % sample_width:
        pcm += b"\x00" * (sample_width - len(pcm) % sample_width)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sample_width)
        w.setframerate(rate)
        w.writeframes(pcm)
    return str(out_path)


# --- Mistral -----------------------------------------------------------------

def _speech(payload: dict) -> dict:
    headers = {
        "Authorization": f"Bearer {get_api_key('MISTRAL_API_KEY', 'Mistral')}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    return _http_json(API_URL, "Mistral TTS", payload, headers, "POST")


def _synth_mistral(text: str, out_path: str, voice_slug: str | None,
                   voice_id: str | None, model: str, fmt: str,
                   strict: bool = False) -> str:
    payload: dict = {"model": model, "input": text, "response_format": fmt}
    tried = []

    if voice_id:
        body = _speech({**payload, "voice_id": voice_id})
    else:
        if strict:
            if not voice_slug:
                raise StrictVoiceError(
                    "Strict voice mode: no Mistral voice specified "
                    "(set voice.slug/voice_id or MISTRAL_VOICE)."
                )
            candidates = [voice_slug]
        else:
            candidates = ([voice_slug] if voice_slug else []) + \
                [s for s in FALLBACK_VOICE_SLUGS if s != voice_slug]
        last_err = None
        body = None
        for slug in candidates:
            try:
                body = _speech({**payload, "voice": slug})
                print(f"[voice] using '{slug}'")
                break
            except TTSError as e:
                msg = str(e)
                if "invalid_voice" in msg or "Voice" in msg or " not found" in msg:
                    print(f"[warn] voice '{slug}' rejected, trying next")
                    tried.append(slug)
                    last_err = e
                    continue
                raise
        if body is None:
            if strict:
                raise StrictVoiceError(
                    f"Strict voice mode: Mistral voice '{voice_slug}' was "
                    f"rejected. Last error: {last_err}"
                )
            raise TTSError(f"No usable Mistral voice (tried: {tried}). Last error: {last_err}")

    audio_b64 = body.get("audio_data") or body.get("audio")
    if not audio_b64:
        raise TTSError(f"Unexpected Mistral TTS response keys: {list(body)}")
    Path(out_path).write_bytes(base64.b64decode(audio_b64))
    return str(out_path)


# --- Google (Gemini TTS) -----------------------------------------------------

def _google_audio(body: dict) -> tuple[bytes, str]:
    """Extract base64 audio from the Interactions response."""
    for step in reversed(body.get("steps") or []):
        if step.get("type") != "model_output":
            continue
        for item in step.get("content") or []:
            if item.get("type") == "audio" and item.get("data"):
                mime = item.get("mime_type") or item.get("mimeType") or ""
                return base64.b64decode(item["data"]), mime
    reason = body.get("error") or body.get("promptFeedback")
    raise TTSError(f"Google TTS returned no audio ({reason or list(body)})")


def _synth_google(text: str, out_path: str, voice: str | None,
                  style: str | None, model: str, strict: bool = False) -> str:
    model = model or DEFAULT_GOOGLE_MODEL
    if model.startswith("models/"):
        model = model[len("models/"):]
    if not voice:
        if strict:
            raise StrictVoiceError(
                "Strict voice mode: no Google voice specified "
                "(set voice.slug/voice.name or GOOGLE_VOICE)."
            )
        voice = DEFAULT_GOOGLE_VOICE
    style = DEFAULT_GOOGLE_STYLE if style is None else style
    key = get_api_key("GOOGLE_API_KEY", "Google TTS")

    part: dict = {"type": "text", "text": text}
    if style:
        part["annotations"] = [{"type": "speech_metadata", "style": style}]
    payload = {
        "model": model,
        "input": [{"type": "user_input", "content": [part]}],
        "response_format": {
            "type": "audio",
            "mime_type": "audio/l16",
            "sample_rate": DEFAULT_GOOGLE_SAMPLE_RATE,
        },
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    body = _http_json(GOOGLE_API_URL, "Google TTS", payload,
                      {"x-goog-api-key": key, "Content-Type": "application/json",
                       "Accept": "application/json"},
                      "POST")

    data, mime = _google_audio(body)
    if "wav" in mime.lower():
        Path(out_path).write_bytes(data)
    else:
        match = re.search(r"rate[=:](\d+)", mime)
        rate = int(match.group(1)) if match else DEFAULT_GOOGLE_SAMPLE_RATE
        _write_pcm_wav(data, out_path, rate=rate)
    return str(out_path)


# --- ElevenLabs --------------------------------------------------------------

def _synth_elevenlabs(text: str, out_path: str, voice_slug: str | None,
                      voice_id: str | None, model: str, fmt: str,
                      strict: bool = False) -> str:
    voice = voice_id or voice_slug
    if not voice:
        if strict:
            raise StrictVoiceError(
                "Strict voice mode: no ElevenLabs voice specified "
                "(set voice.voice_id/voice.slug or ELEVENLABS_VOICE_ID)."
            )
        voice = DEFAULT_ELEVENLABS_VOICE_ID
    key = get_api_key("ELEVENLABS_API_KEY", "ElevenLabs")
    if fmt == "mp3":
        output_format, wrap = "mp3_44100_128", False
        accept = "audio/mpeg"
    else:
        output_format, wrap = "pcm_44100", True
        accept = "audio/pcm"

    url = f"{ELEVENLABS_API_URL}/v1/text-to-speech/{quote(voice, safe='')}?output_format={output_format}"
    payload = {"text": text, "model_id": model or DEFAULT_ELEVENLABS_MODEL}
    data = _http_bytes(
        url, "ElevenLabs", payload,
        {"xi-api-key": key, "Content-Type": "application/json", "Accept": accept},
        "POST",
    )
    if wrap:
        _write_pcm_wav(data, out_path, rate=44100)
    else:
        Path(out_path).write_bytes(data)
    return str(out_path)


# --- fal.ai ------------------------------------------------------------------

def _fal_payload(endpoint: str, text: str, voice: str | None,
                 fmt: str, style: str | None, strict: bool = False) -> dict:
    if not voice:
        if strict:
            raise StrictVoiceError(
                "Strict voice mode: no fal voice specified "
                "(set voice.slug/voice.name or FAL_VOICE)."
            )
        voice = DEFAULT_FAL_GEMINI_VOICE if "gemini" in endpoint.lower() else DEFAULT_FAL_VOICE
    if "gemini" in endpoint.lower():
        payload = {
            "prompt": text,
            "voice": voice,
            "output_format": "wav" if fmt == "wav" else "mp3",
        }
        if style:
            payload["style_instructions"] = style
        return payload
    return {"text": text, "voice": voice}


def _synth_fal(text: str, out_path: str, voice: str | None, style: str | None,
               endpoint: str, fmt: str, strict: bool = False) -> str:
    endpoint = (endpoint or DEFAULT_FAL_ENDPOINT).strip("/")
    payload = _fal_payload(endpoint, text, voice, fmt, style, strict)
    key = get_api_key("FAL_KEY", "fal.ai")
    body = _http_json(
        f"{FAL_API_URL}/{endpoint}", "fal.ai", payload,
        {"Authorization": f"Key {key}", "Content-Type": "application/json",
         "Accept": "application/json"},
        "POST",
    )
    audio = body.get("audio")
    if isinstance(audio, dict):
        url = audio.get("url")
    elif isinstance(audio, str):
        url = audio
    else:
        url = None
    if not url:
        raise TTSError(f"fal.ai returned no audio URL (keys: {list(body)})")
    # Audio URLs are signed/public; do not send the FAL key to the storage host.
    data = _http_bytes(url, "fal.ai")
    Path(out_path).write_bytes(data)
    return str(out_path)


# --- Public contract ---------------------------------------------------------

def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str | None = None,
                  fmt: str | None = None, provider: str | None = None,
                  style: str | None = None, strict: bool = False) -> str:
    """Synthesize one narration clip; return its path.

    ``provider`` overrides ``TTS_PROVIDER``; ``voice_slug``/``voice_id`` and
    ``model`` are interpreted per provider. ``fmt`` is normalised via
    :func:`resolve_format` so the file extension matches the bytes written.
    ``strict`` disables provider defaults/fallbacks: a missing or rejected
    voice raises :class:`StrictVoiceError` instead of substituting another.
    """
    provider = resolve_provider({"provider": provider} if provider else None)
    fmt = resolve_format(provider, fmt, model)
    voice_slug, voice_id = resolve_voice(provider, voice_slug, voice_id)

    if provider == "mistral":
        return _synth_mistral(text, out_path, voice_slug, voice_id,
                              model or DEFAULT_MISTRAL_MODEL, fmt, strict)
    if provider == "google":
        return _synth_google(text, out_path, voice_slug or voice_id, style,
                             model or DEFAULT_GOOGLE_MODEL, strict)
    if provider == "elevenlabs":
        return _synth_elevenlabs(text, out_path, voice_slug, voice_id,
                                 model or DEFAULT_ELEVENLABS_MODEL, fmt, strict)
    endpoint = model or os.environ.get("FAL_ENDPOINT") or DEFAULT_FAL_ENDPOINT
    return _synth_fal(text, out_path, voice_slug or voice_id, style, endpoint, fmt, strict)


def audio_duration(path: str) -> float:
    """Duration of an audio file as MoviePy will decode/play it.

    Container-level probes (ffprobe/ffmpeg time=) underestimate MP3s by
    tens of ms versus the decoded stream, clipping the last word of
    narration. Measuring with AudioFileClip matches the render path
    exactly.
    """
    from moviepy import AudioFileClip
    with AudioFileClip(path) as clip:
        return float(clip.duration)
