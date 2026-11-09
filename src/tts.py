import os
import json
import importlib
import io
import tempfile
import wave
import base64
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError

API_URL = "https://api.mistral.ai/v1/audio/speech"
VOICES_URL = "https://api.mistral.ai/v1/audio/voices"

_default_voice_cache: str | None = None


class TTSError(RuntimeError):
    """narration is unavailable but the scene can still render"""


def get_provider(provider=None):
    name = (provider if provider is not None else os.environ.get("TTS_PROVIDER", "mistral")).strip().lower()
    if name not in ("mistral", "google", "elevenlabs"):
        raise TTSError(f"Unknown TTS provider '{name}'; use mistral, google or elevenlabs")
    return name


def provider_request(req, provider, as_json=False, timeout=300):
    # keep provider failures separate from errors in the rest of the renderer
    try:
        with _rq.urlopen(req, timeout=timeout) as response:
            data = response.read()
        return json.loads(data) if as_json else data
    except HTTPError as error:
        with error:
            try:
                detail = error.read().decode(errors="replace")[:500]
            except OSError:
                detail = "could not read the error response"
        # api responses can echo credentials, so keep them out of render logs
        for name in ("MISTRAL_API_KEY", "GOOGLE_API_KEY", "ELEVENLABS_API_KEY"):
            key = os.environ.get(name)
            if key:
                detail = detail.replace(key, "[redacted]")
        raise TTSError(f"{provider} TTS API error {error.code}: {detail}") from None
    except (URLError, OSError, ValueError) as error:
        raise TTSError(f"{provider} TTS request failed ({type(error).__name__})") from None


def pcm_wav(pcm, rate=24000, channels=1):
    # raw pcm needs a wav header before audio players can read it
    if rate <= 0 or channels <= 0 or not pcm or len(pcm) % (2 * channels):
        raise TTSError("TTS returned empty or incomplete PCM audio")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    return buffer.getvalue()


def resolve_options(provider=None, voice_slug=None, voice_id=None, model=None, fmt=None, style=None):
    provider = get_provider(provider)
    if provider == "mistral":
        default_model, default_voice, default_format = "voxtral-mini-tts-2603", FALLBACK_VOICE_SLUGS[0], "wav"
    else:
        adapter = importlib.import_module(f"tts_{provider}")
        default_model, default_voice, default_format = adapter.DEFAULT_MODEL, adapter.DEFAULT_VOICE, adapter.DEFAULT_FORMAT
    if provider == "elevenlabs":
        voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or adapter.default_voice()
        voice_slug = None
    else:
        voice_slug = voice_slug or default_voice
    if provider == "google":
        style = style if style is not None else adapter.DEFAULT_STYLE
    else:
        style = None
    fmt = fmt or default_format
    if fmt not in (("wav",) if provider == "google" else ("wav", "mp3")):
        raise TTSError(f"{provider} does not support narration format '{fmt}'")
    return dict(provider=provider, voice_slug=voice_slug, voice_id=voice_id,
                model=model or default_model, fmt=fmt, style=style)


def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str | None = None,
                  fmt: str | None = None, *, provider=None, style=None) -> str:
    """send narration to the selected provider and return the audio path"""
    options = resolve_options(provider, voice_slug, voice_id, model, fmt, style)
    provider = options.pop("provider")
    synth = _synth_mistral if provider == "mistral" else importlib.import_module(f"tts_{provider}").synth_to_file
    target = Path(out_path)
    # only replace the cache file after the audio has been written and decoded
    with tempfile.TemporaryDirectory(prefix=".tts-", dir=target.parent) as tmp:
        staged = Path(tmp) / ("narration." + options["fmt"])
        try:
            synth(text, str(staged), **options)
            if audio_duration(str(staged)) <= 0:
                raise TTSError(f"{provider} returned empty audio")
        except TTSError:
            raise
        except (RuntimeError, ValueError, KeyError, IndexError, TypeError, AttributeError, wave.Error) as error:
            raise TTSError(f"{provider} TTS returned an invalid response ({type(error).__name__})") from None
        staged.replace(target)
    return str(out_path)


def get_api_key(name="MISTRAL_API_KEY") -> str:
    key = os.environ.get(name)
    if not key:
        raise TTSError(f"{name} not set; provide it via the environment")
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
    body = provider_request(req, "Mistral", as_json=True, timeout=60)
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
    return provider_request(req, "Mistral", as_json=True)


def _synth_mistral(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str = "voxtral-mini-tts-2603",
                  fmt: str = "wav", style=None) -> str:
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
                print(f"[voice] using '{slug}'")
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
    Path(out_path).write_bytes(base64.b64decode(audio_b64, validate=True))
    return str(out_path)


def audio_duration(path: str) -> float:
    """Duration of an audio file as MoviePy will decode/play it.

    Container-level probes (ffprobe/ffmpeg time=) underestimate MP3s by
    tens of ms versus the decoded stream, clipping the last word of
    narration. Measuring with AudioFileClip matches the render path
    exactly.
    """
    from moviepy import AudioFileClip
    try:
        with AudioFileClip(path) as clip:
            return float(clip.duration)
    except (OSError, ValueError) as error:
        raise TTSError(f"TTS audio could not be decoded ({type(error).__name__})") from None
