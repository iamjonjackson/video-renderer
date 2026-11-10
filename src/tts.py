"""Narration TTS: public contract + provider dispatch.

render.py calls `synth_to_file(text, out_path, ...)` (text in, audio file
out, path returned). The provider is chosen by, in order:

1. `TTS_PROVIDER` env var (`mistral` | `google` | `elevenlabs`)
2. spec `"meta": {"tts": {"provider": ...}}`
3. `mistral` (default; unchanged behaviour when nothing is set)

Mistral Voxtral lives here; Google (Gemini TTS) and ElevenLabs are adapters
in tts_google.py / tts_elevenlabs.py, all stdlib-only (urllib).

Every TTS failure raises TTSError (missing key: TTSKeyMissing) so the
renderer can degrade to silent scenes instead of aborting.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError, URLError

PROVIDERS = ("mistral", "google", "elevenlabs")
DEFAULT_PROVIDER = "mistral"

# Output container per provider (drives the cache file extension).
# Mistral honours the spec's voice.format; the others are fixed.
PROVIDER_FORMATS = {"google": "wav", "elevenlabs": "mp3"}

MISTRAL_MODEL = "voxtral-mini-tts-2603"

API_URL = "https://api.mistral.ai/v1/audio/speech"
VOICES_URL = "https://api.mistral.ai/v1/audio/voices"

_default_voice_cache: str | None = None


class TTSError(RuntimeError):
    """Any narration synthesis failure; render.py degrades to silence."""


class TTSKeyMissing(TTSError):
    """The selected provider's API key env var is unset."""


def require_key(*env_vars: str, hint: str = "") -> str:
    """Return the first non-empty env var; raise TTSKeyMissing naming them."""
    for name in env_vars:
        key = os.environ.get(name)
        if key:
            return key
    names = " / ".join(env_vars)
    raise TTSKeyMissing(f"{names} not set. {hint}".strip())


# --------------------------------------------------------------------------
# Provider selection and cache keys
# --------------------------------------------------------------------------

def selected_provider(spec_provider: str | None = None) -> str:
    """Effective provider: TTS_PROVIDER env > spec meta.tts.provider > mistral."""
    name = (os.environ.get("TTS_PROVIDER") or spec_provider or DEFAULT_PROVIDER)
    name = name.strip().lower()
    if name not in PROVIDERS:
        raise TTSError(f"unknown TTS provider '{name}' (choose one of: {', '.join(PROVIDERS)})")
    return name


def resolve_config(spec: dict) -> dict:
    """Narration settings for the effective provider.

    - Top-level `voice` block: Mistral settings (slug / voice_id / model / format).
    - `meta.tts` {provider, voice, model, style}: settings for the provider it
      names (mistral if it names none). They are ignored when TTS_PROVIDER
      switches to a different provider, so a Voxtral slug is never sent to
      Google, and vice versa.
    - Per-provider env overrides: GOOGLE_TTS_VOICE / GOOGLE_TTS_MODEL /
      GOOGLE_TTS_STYLE, ELEVENLABS_VOICE_ID / ELEVENLABS_MODEL.
    """
    meta_tts = (spec.get("meta") or {}).get("tts") or {}
    voice_block = spec.get("voice") or {}
    provider = selected_provider(meta_tts.get("provider"))
    own = meta_tts if (meta_tts.get("provider") or DEFAULT_PROVIDER).lower() == provider else {}

    if provider == "mistral":
        return {
            "provider": "mistral",
            "slug": own.get("voice") or voice_block.get("slug"),
            "voice_id": voice_block.get("voice_id"),
            "model": own.get("model") or voice_block.get("model", MISTRAL_MODEL),
            "format": voice_block.get("format", "wav"),
            "style": None,
        }
    if provider == "google":
        return {
            "provider": "google",
            "slug": os.environ.get("GOOGLE_TTS_VOICE") or own.get("voice"),
            "voice_id": None,
            "model": os.environ.get("GOOGLE_TTS_MODEL") or own.get("model"),
            "format": PROVIDER_FORMATS["google"],
            "style": os.environ.get("GOOGLE_TTS_STYLE") or own.get("style"),
        }
    return {
        "provider": "elevenlabs",
        "slug": None,
        "voice_id": os.environ.get("ELEVENLABS_VOICE_ID") or own.get("voice"),
        "model": os.environ.get("ELEVENLABS_MODEL") or own.get("model"),
        "format": PROVIDER_FORMATS["elevenlabs"],
        "style": None,
    }


def cache_key(text: str, cfg: dict) -> str:
    """Stable narration cache key covering text + provider + voice + model.

    Uses the *configured* voice ('default' when unset) rather than a
    network-resolved one, so a warm cache still needs no API calls.
    """
    parts = {
        "text": text,
        "provider": cfg.get("provider", DEFAULT_PROVIDER),
        "voice": cfg.get("voice_id") or cfg.get("slug") or "default",
        "model": cfg.get("model") or "default",
        "style": cfg.get("style") or "",
    }
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------
# Public contract
# --------------------------------------------------------------------------

def synth_to_file(text: str, out_path: str, voice_slug: str | None = None,
                  voice_id: str | None = None, model: str | None = None,
                  fmt: str = "wav", provider: str | None = None,
                  style: str | None = None) -> str:
    """Synthesize one narration clip with the selected provider; return its path.

    `provider=None` resolves via TTS_PROVIDER (default mistral). `voice_slug`
    / `voice_id` / `model` are interpreted by that provider; None means the
    provider's own default.
    """
    provider = provider or selected_provider()
    if provider == "mistral":
        return _mistral_synth(text, out_path, voice_slug, voice_id,
                              model or MISTRAL_MODEL, fmt)
    if provider == "google":
        import tts_google
        return tts_google.synth_to_file(text, out_path, voice=voice_slug,
                                        model=model, style=style)
    if provider == "elevenlabs":
        import tts_elevenlabs
        return tts_elevenlabs.synth_to_file(text, out_path,
                                            voice_id=voice_id or voice_slug,
                                            model=model)
    raise TTSError(f"unknown TTS provider '{provider}'")


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


# --------------------------------------------------------------------------
# Mistral Voxtral (default provider)
# --------------------------------------------------------------------------

def get_api_key() -> str:
    return require_key(
        "MISTRAL_API_KEY",
        hint="Provide it via environment (e.g. from a Drive file read into "
             "the env at render time); never paste it in chat.",
    )


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
        raise TTSError(f"voices list HTTP {e.code}: {detail}") from e
    except URLError as e:
        raise TTSError(f"voices list unreachable: {e.reason}") from e
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
        raise TTSError(f"Mistral TTS API error {e.code}: {detail}") from e
    except URLError as e:
        raise TTSError(f"Mistral TTS API unreachable: {e.reason}") from e


def _mistral_synth(text: str, out_path: str, voice_slug: str | None,
                   voice_id: str | None, model: str, fmt: str) -> str:
    """Synthesize one clip via the Mistral TTS REST API; return its path."""
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
            except TTSError as e:
                msg = str(e)
                if "invalid_voice" in msg or "Voice" in msg or " not found" in msg:
                    print(f"[warn] voice '{slug}' rejected, trying next")
                    tried.append(slug)
                    last_err = e
                    continue
                raise
        if body is None:
            raise TTSError(
                f"No usable voice (tried: {tried}). Last error: {last_err}"
            )

    audio_b64 = body.get("audio_data") or body.get("audio")
    if not audio_b64:
        raise TTSError(f"Unexpected TTS response keys: {list(body)}")
    Path(out_path).write_bytes(base64.b64decode(audio_b64))
    return str(out_path)
