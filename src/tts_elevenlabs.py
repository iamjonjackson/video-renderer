"""elevenlabs narration using formats available on the free tier"""
import json
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request

from tts import TTSError, get_api_key, pcm_wav, provider_request

DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_VOICE = None
DEFAULT_FORMAT = "mp3"


def default_voice():
    try:
        return _account_voice(get_api_key("ELEVENLABS_API_KEY"))
    except (AttributeError, KeyError, TypeError):
        raise TTSError("ElevenLabs returned an invalid voice list") from None


@lru_cache(maxsize=8)
def _account_voice(key):
    # library voices need a paid plan, so choose a built-in voice from the account
    req = Request(
        "https://api.elevenlabs.io/v2/voices?category=premade&page_size=100&sort=name&sort_direction=asc",
        headers={"xi-api-key": key},
    )
    body = provider_request(req, "ElevenLabs", as_json=True)
    voices = [voice for voice in body.get("voices", [])
              if voice.get("category") == "premade" and voice.get("voice_id")]
    if not voices:
        raise TTSError("ElevenLabs returned no built-in voices; select an API-eligible voice with ELEVENLABS_VOICE_ID")
    # keep the selected voice stable and reuse the lookup for the rest of the render
    return sorted(voices, key=lambda voice: (voice.get("name", ""), voice["voice_id"]))[0]["voice_id"]


def synth_to_file(text, out_path, voice_slug=None, voice_id=None,
                  model=DEFAULT_MODEL, fmt=DEFAULT_FORMAT, style=None):
    # 44.1 khz pcm needs a paid plan, so wav uses the free 24 khz output
    output_format = "pcm_24000" if fmt == "wav" else "mp3_44100_128"
    req = Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{quote(voice_id or default_voice(), safe='')}?output_format={output_format}",
        data=json.dumps({"text": text, "model_id": model}).encode(),
        headers={"xi-api-key": get_api_key("ELEVENLABS_API_KEY"),
                 "Content-Type": "application/json", "Accept": "application/octet-stream"},
        method="POST",
    )
    audio = provider_request(req, "ElevenLabs")
    if fmt == "wav":
        audio = pcm_wav(audio)
    Path(out_path).write_bytes(audio)
    return str(out_path)
