import os
import json
import base64
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError

API_URL = "https://api.mistral.ai/v1/audio/speech"
VOICES_URL = "https://api.mistral.ai/v1/audio/voices"

_default_voice_cache: str | None = None

PROVIDERS = ("mistral", "google", "elevenlabs")
DEFAULT_MISTRAL_MODEL = "voxtral-mini-tts-2603"


class MissingAPIKeyError(RuntimeError):
    """A provider's API key env var is not set."""

    def __init__(self, env_var: str):
        super().__init__(f"{env_var} not set")
        self.env_var = env_var


class TTSProviderError(RuntimeError):
    """A TTS provider request failed (HTTP error, bad response, no usable voice)."""


def get_api_key() -> str:
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise MissingAPIKeyError("MISTRAL_API_KEY")
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
        raise TTSProviderError(f"Mistral TTS API error {e.code}: {detail}") from e


def _synth_mistral(text: str, out_path: str, voice_slug: str | None = None,
                   voice_id: str | None = None, model: str = DEFAULT_MISTRAL_MODEL,
                   fmt: str = "wav") -> str:
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
            raise TTSProviderError(
                f"No usable voice (tried: {tried}). Last error: {last_err}"
            )

    audio_b64 = body.get("audio_data") or body.get("audio")
    if not audio_b64:
        raise TTSProviderError(f"Unexpected TTS response keys: {list(body)}")
    Path(out_path).write_bytes(base64.b64decode(audio_b64))
    return str(out_path)


def resolve_provider(voice_cfg: dict | None = None) -> str:
    """Pick the TTS provider: spec "voice.provider", then TTS_PROVIDER, then mistral."""
    provider = ((voice_cfg or {}).get("provider")
                or os.environ.get("TTS_PROVIDER")
                or "mistral").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown TTS provider {provider!r}; expected one of {', '.join(PROVIDERS)}"
        )
    return provider


def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str | None = None,
                  fmt: str = "wav", provider: str | None = None) -> str:
    """Synthesize one narration clip with the selected provider; return its path.

    The returned path may have a different extension from out_path
    (Google always writes .wav, ElevenLabs always writes .mp3).
    """
    provider = provider or resolve_provider()
    if provider == "google":
        import tts_google
        return tts_google.synth_to_file(text, out_path, voice=voice_slug, model=model)
    if provider == "elevenlabs":
        import tts_elevenlabs
        return tts_elevenlabs.synth_to_file(text, out_path,
                                            voice=voice_id or voice_slug, model=model)
    return _synth_mistral(text, out_path, voice_slug=voice_slug, voice_id=voice_id,
                          model=model or DEFAULT_MISTRAL_MODEL, fmt=fmt)


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