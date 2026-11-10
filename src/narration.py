"""Server-owned, consented narration artifacts; never part of the editable spec.

Captions contain the complete scene transcript, timed over its whole audio clip.
They are coarse scene captions, not word-level alignment. No music or cloning.
Transport injection accepts ``(urllib.request.Request, timeout=seconds)`` and
returns a context-managed HTTP response. It must honour that timeout.
"""

import base64
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

MAX_BYTES = 20 * 1024 * 1024
MAX_SCENES = 12
DEADLINE_SECONDS = 180
CAPTION_DISCLOSURE = (
    "Coarse scene captions cover the whole narration clip; not word-level alignment."
)
_KEYS = {
    "mistral": "MISTRAL_API_KEY",
    "google": "GOOGLE_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


class NarrationError(ValueError):
    """Strict preparation failed; do not render a silent substitute."""


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward server credentials to a provider-selected endpoint.
        return None


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NarrationError("Narration preparation deadline exceeded")
    return remaining


def _read_response(response, deadline):
    chunks, size = [], 0
    while True:
        _remaining(deadline)
        # urllib socket reads are bounded by the remaining overall deadline,
        # including a peer that trickles its response in small chunks.
        sock = getattr(
            getattr(getattr(response, "fp", None), "raw", None), "_sock", None
        )
        if sock is not None:
            sock.settimeout(_remaining(deadline))
        read = getattr(response, "read1", response.read)
        chunk = read(min(65536, MAX_BYTES + 1 - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_BYTES:
            raise NarrationError("Narration response exceeds 20 MB")
    _remaining(deadline)
    return b"".join(chunks)


def _identifier(value, label):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise NarrationError(
            f"Explicit {label} identifier required (not a URL or path)"
        )
    return value


def _speech_request(provider, model, voice, text, key):
    headers = {"Content-Type": "application/json"}
    if provider == "mistral":
        url = "https://api.mistral.ai/v1/audio/speech"
        headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})
        payload = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "wav",
        }
    elif provider == "google":
        # Reuse the existing single-speaker wire builder, not its fallback loop.
        if __package__:
            from .tts_google import build_payload
        else:
            from tts_google import build_payload

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers.update({"x-goog-api-key": key, "Accept": "application/json"})
        payload = build_payload(text, model, voice, "")
    else:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
        headers.update({"xi-api-key": key, "Accept": "audio/mpeg"})
        payload = {"text": text, "model_id": model}
    return request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )


def _audio_bytes(provider, raw):
    try:
        if provider == "elevenlabs":
            audio = raw
        else:
            body = json.loads(raw)
            if provider == "mistral":
                audio = base64.b64decode(
                    body.get("audio_data") or body["audio"], validate=True
                )
            else:
                if __package__:
                    from .tts_google import to_wav_bytes
                else:
                    from tts_google import to_wav_bytes

                parts = body["candidates"][0]["content"]["parts"]
                inline = next(
                    part["inlineData"] for part in parts if "inlineData" in part
                )
                audio = base64.b64decode(inline["data"], validate=True)
                audio = to_wav_bytes(audio, inline.get("mimeType", ""))
        if not audio or len(audio) > MAX_BYTES:
            raise NarrationError("Empty or oversized narration audio")
        return audio
    except (KeyError, IndexError, TypeError, ValueError, StopIteration) as exc:
        raise NarrationError("Provider returned invalid narration audio") from exc


def _decoded_duration(path, deadline):
    # MoviePy launches ffmpeg with its process environment. Decode in a bounded
    # child with an allowlisted environment so no server API key is inherited.
    env = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
        if name in os.environ
    }
    script = "from moviepy import AudioFileClip; import sys\nwith AudioFileClip(sys.argv[1]) as clip: print(float(clip.duration))"
    env["PYTHON_DOTENV_DISABLED"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, "-c", script, str(path)],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=_remaining(deadline),
        )
        duration = float(result.stdout.strip())
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        raise NarrationError("Narration audio cannot be decoded") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise NarrationError("Narration audio has invalid duration")
    return duration


def transcript(scene):
    texts = scene.get("narration_per_bullet") or [scene.get("narration", "")]
    if not isinstance(texts, list) or any(not isinstance(text, str) for text in texts):
        raise NarrationError("Invalid scene narration")
    text = " ".join(texts).strip()
    if len(text) > 12000:
        raise NarrationError("Scene narration is too long")
    return text


def prepared_scene_duration(scene, audio_duration):
    """Honour authored timing; never trim narration or shorten a scene."""
    explicit = scene.get("duration")
    if explicit is not None:
        if explicit < audio_duration:
            raise NarrationError(
                "Narration exceeds explicit scene duration; extend the scene"
            )
        return explicit
    return audio_duration + scene.get("padding", 1.0)


def prepare_narration(
    spec,
    directory,
    provider,
    model,
    voice,
    consent,
    transport=None,
    cancelled=None,
    max_requests=12,
):
    """Return an absolute manifest Path, or None if consent is explicitly False.

    One request per narrated scene (at most 12); no retries, provider/model/voice
    substitution or dotenv reads. ``directory`` must be a server-owned root.
    A unique child directory contains sceneNN.wav/mp3 and media-manifest.json.
    Failures remove this call's incomplete artifacts and publish no manifest.
    """
    if consent is False:
        return None
    if consent is not True:
        raise NarrationError("Explicit narration consent required")
    if provider not in _KEYS:
        raise NarrationError("Select mistral, google or elevenlabs explicitly")
    _identifier(model, "model")
    _identifier(voice, "voice")
    scenes = spec.get("timeline")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise NarrationError("Narration supports 1 to 12 scenes")
    texts = [transcript(scene) for scene in scenes]
    if (
        type(max_requests) is not int
        or not 1 <= max_requests <= 12
        or sum(bool(t) for t in texts) > max_requests
    ):
        raise NarrationError("Narration request budget exceeded")

    def check_cancelled():
        if cancelled is not None and cancelled.is_set():
            raise NarrationError("Narration cancelled")

    check_cancelled()
    key = os.environ.get(_KEYS[provider])
    if provider == "google" and not key:
        key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise NarrationError(f"{_KEYS[provider]} is not configured on the server")
    deadline = time.monotonic() + DEADLINE_SECONDS
    transport = transport or request.build_opener(_NoRedirect()).open
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="narration-", dir=root) as scratch:
        scratch = Path(scratch)
        entries = []
        for index, (scene, text) in enumerate(zip(scenes, texts)):
            if not text:
                continue
            check_cancelled()
            req = _speech_request(provider, model, voice, text, key)
            try:
                with transport(req, timeout=_remaining(deadline)) as response:
                    raw = _read_response(response, deadline)
            except (HTTPError, URLError, OSError) as exc:
                # Never echo a provider body, request headers or secret-bearing URL.
                code = exc.code if isinstance(exc, HTTPError) else "unavailable"
                if isinstance(exc, HTTPError):
                    exc.close()
                raise NarrationError(
                    f"{provider} narration request failed ({code})"
                ) from None
            check_cancelled()
            audio = _audio_bytes(provider, raw)
            path = (
                scratch
                / f"scene{index:02d}.{'mp3' if provider == 'elevenlabs' else 'wav'}"
            )
            path.write_bytes(audio)
            duration = _decoded_duration(path, deadline)
            prepared_scene_duration(scene, duration)
            entries.append(
                {
                    "index": index,
                    "path": path.name,
                    "duration": duration,
                    "captions": [{"start": 0, "end": duration, "text": text}],
                }
            )
        check_cancelled()
        _remaining(deadline)
        manifest = scratch / "media-manifest.json"
        manifest.write_text(
            json.dumps({"scenes": entries, "caption_disclosure": CAPTION_DISCLOSURE}),
            encoding="utf-8",
        )
        # Publish only the fully prepared directory; TemporaryDirectory cleans
        # the emptied scratch directory without touching completed artifacts.
        published = scratch.with_name(scratch.name + "-ready")
        scratch.rename(published)
    return published / manifest.name


def load_media_manifest(manifest_path, spec):
    """Validate a server-provided manifest; resolve every audio path in its root."""
    manifest = Path(manifest_path).resolve(strict=True)
    if manifest.stat().st_size > MAX_BYTES:
        raise NarrationError("Media manifest exceeds 20 MB")
    body = json.loads(manifest.read_text(encoding="utf-8"))
    entries = body.get("scenes") if isinstance(body, dict) else None
    timeline = spec["timeline"]
    if (
        not isinstance(entries, list)
        or len(entries) > MAX_SCENES
        or len(timeline) > MAX_SCENES
    ):
        raise NarrationError("Media manifest supports at most 12 scenes")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise NarrationError("Invalid media scene")
        index = entry.get("index")
        if type(index) is not int or not 0 <= index < len(timeline) or index in result:
            raise NarrationError("Invalid or duplicate media scene index")
        name = entry.get("path")
        if not isinstance(name, str) or not re.fullmatch(
            r"scene\d{2}\.(wav|mp3)", name
        ):
            raise NarrationError("Media audio path must be a controlled scene filename")
        path = (manifest.parent / name).resolve(strict=True)
        if (
            not path.is_relative_to(manifest.parent)
            or not path.is_file()
            or path.stat().st_size > MAX_BYTES
        ):
            raise NarrationError("Media audio path escapes its root or exceeds 20 MB")
        duration = entry.get("duration")
        if (
            type(duration) not in (float, int)
            or not math.isfinite(duration)
            or duration <= 0
        ):
            raise NarrationError("Invalid media audio duration")
        captions = entry.get("captions")
        text = transcript(timeline[index])
        if captions != [{"start": 0, "end": duration, "text": text}] or not text:
            raise NarrationError("Media captions must match the whole scene transcript")
        prepared_scene_duration(timeline[index], duration)
        result[index] = {**entry, "path": str(path)}
    if set(result) != {i for i, scene in enumerate(timeline) if transcript(scene)}:
        raise NarrationError("Media manifest must cover every narrated scene")
    return result


def write_srt(output, entries, durations):
    """Write coarse captions beside the video, preserving scene offsets."""

    def stamp(seconds):
        milliseconds = round(seconds * 1000)
        seconds, ms = divmod(milliseconds, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"

    lines, cursor = [], 0.0
    for index, duration in enumerate(durations):
        entry = entries.get(index)
        if entry:
            caption = entry["captions"][0]
            lines.append(
                f"{len(lines) + 1}\n{stamp(cursor)} --> {stamp(cursor + caption['end'])}\n{caption['text']}\n"
            )
        cursor += duration
    Path(output).with_suffix(".srt").write_text("\n".join(lines), encoding="utf-8")
