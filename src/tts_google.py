"""gemini narration through the google ai studio api"""
import base64
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import Request

from tts import TTSError, get_api_key, pcm_wav, provider_request

DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
DEFAULT_FORMAT = "wav"
DEFAULT_STYLE = "Read aloud in a neutral, warm narration voice"


def synth_to_file(text, out_path, voice_slug=None, voice_id=None,
                  model=DEFAULT_MODEL, fmt=DEFAULT_FORMAT, style=DEFAULT_STYLE):
    payload = {
        "contents": [{"parts": [{"text": f"{style}:\n{text}" if style else text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                "voiceName": voice_slug or DEFAULT_VOICE,
            }}},
        },
    }
    req = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
        data=json.dumps(payload).encode(),
        headers={"x-goog-api-key": get_api_key("GOOGLE_API_KEY"), "Content-Type": "application/json"},
        method="POST",
    )
    body = provider_request(req, "Google", as_json=True)
    candidates = body.get("candidates", [])
    if not candidates or candidates[0].get("finishReason", "STOP") != "STOP":
        raise TTSError("Google TTS returned no complete audio candidate")
    parts = candidates[0].get("content", {}).get("parts", [])
    audio = []
    for part in parts:
        if part.get("thought") or "inlineData" not in part:
            continue
        inline = part["inlineData"]
        mime = inline.get("mimeType", "").lower()
        data = base64.b64decode(inline["data"], validate=True)
        if mime.startswith("audio/l16"):
            # the gemini tts pcm output is little-endian, 16-bit and mono
            rate = re.search(r"rate=(\d+)", mime)
            data = pcm_wav(data, rate=int(rate[1]) if rate else 24000)
        elif mime not in ("audio/wav", "audio/x-wav"):
            raise TTSError(f"Google TTS returned unsupported audio type '{mime}'")
        audio.append(data)
    if len(audio) != 1:
        raise TTSError("Google TTS did not return a single audio clip")
    Path(out_path).write_bytes(audio[0])
    return str(out_path)
