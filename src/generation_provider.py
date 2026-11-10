"""Strict hosted generation boundary; consent and schema semantics belong to the caller.

Only Google generateContent and Mistral chat/completions are used. Every operation
makes at most one POST, never retries or follows redirects, and returns an envelope
with output, numeric usage and a bounded response_id. Vision accepts only explicitly
passed, validated PNG/JPEG data URLs (at most three). Image generation is separately
configured and Google-only; no URL acquisition or agent tools are available.

Wire references: https://ai.google.dev/api/generate-content and
https://docs.mistral.ai/api/endpoint/chat (checked during implementation).
"""

import base64
import binascii
import http.client
import json
import math
import os
import re
from io import BytesIO
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from PIL import Image, UnidentifiedImageError

if __package__:
    from . import canvas_assets
else:
    import canvas_assets

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_IMAGES = 3
MAX_GENERATED_DIMENSION = 4096
MAX_GENERATED_PIXELS = 16_000_000
MODEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}\Z", re.ASCII)
KEY_NAMES = {
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
}
GOOGLE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
)
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"


class ProviderError(RuntimeError):
    """Terminal, safe-to-display failure; no raw response or credential details."""

    def __init__(self, code: str, *, status: int | None = None):
        self.code = code
        self.status = status
        super().__init__(
            f"Generation failed: {code}"
            + (f" (HTTP {status})" if status is not None else "")
        )


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urlopen(req, *, timeout):
    # Redirects could leak credentials or turn one authorised call into two.
    return request.build_opener(_NoRedirect()).open(req, timeout=timeout)


def validate_model(model: str) -> str:
    """Accept a public identity, not a URL, filesystem path or traversal segment."""
    if (
        not isinstance(model, str)
        or not MODEL_PATTERN.fullmatch(model)
        or any(part in ("", ".", "..") for part in model.split("/"))
    ):
        raise ValueError("Model must be a public identity of at most 100 characters.")
    return model


def _json_object(text):
    def reject_constant(value):
        raise ValueError("Non-finite JSON")

    try:
        value = json.loads(text, parse_constant=reject_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProviderError("invalid_json") from None
    if not isinstance(value, dict):
        raise ProviderError("invalid_response")
    return value


def _google_parts(body):
    feedback = body.get("promptFeedback", {})
    if not isinstance(feedback, dict):
        raise ProviderError("invalid_response")
    if feedback.get("blockReason") not in (None, "BLOCK_REASON_UNSPECIFIED"):
        raise ProviderError("refused")
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ProviderError("invalid_response")
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ProviderError("invalid_response")
    if candidate.get("finishReason") != "STOP":
        raise ProviderError("incomplete_or_refused")
    content = candidate.get("content")
    if not isinstance(content, dict):
        raise ProviderError("invalid_response")
    parts = content.get("parts")
    if (
        not isinstance(parts, list)
        or not parts
        or not all(isinstance(p, dict) for p in parts)
    ):
        raise ProviderError("invalid_response")
    return parts


def _metadata(body, provider):
    raw = body.get("usageMetadata" if provider == "google" else "usage", {})
    names = (
        ("promptTokenCount", "candidatesTokenCount", "totalTokenCount")
        if provider == "google"
        else ("prompt_tokens", "completion_tokens", "total_tokens")
    )
    usage = {}
    if isinstance(raw, dict):
        for source, target in zip(
            names, ("input_tokens", "output_tokens", "total_tokens")
        ):
            value = raw.get(source)
            if type(value) is int and 0 <= value <= 10**12:
                usage[target] = value
    response_id = body.get("responseId" if provider == "google" else "id")
    if not isinstance(response_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,200}", response_id
    ):
        response_id = None
    return {"usage": usage, "response_id": response_id}


class ProviderClient:
    """A server-configured identity. Construction/readiness performs no network IO.

    transport is a urlopen-compatible callable accepting (Request, timeout=...).
    Tests may inject a loopback transport; production endpoints are not configurable.
    env supplies keys without changing process environment. Schema validation of the
    returned object remains the coordinator's responsibility. image_model has no default.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        transport=None,
        env=None,
        image_model: str | None = None,
        timeout: float = 60,
    ):
        if not isinstance(provider, str) or provider not in KEY_NAMES:
            raise ValueError("Provider must be google or mistral.")
        self.provider = provider
        self.model = validate_model(model)
        self.image_model = (
            validate_model(image_model) if image_model is not None else None
        )
        if self.image_model is not None and provider != "google":
            raise ValueError("Native image generation is Google-only.")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or not 0 < timeout <= 60
        ):
            raise ValueError("Timeout must be positive and at most 60 seconds.")
        self.timeout = timeout
        self._transport = transport if transport is not None else _urlopen
        self._env = os.environ if env is None else env

    def _key(self):
        for name in KEY_NAMES[self.provider]:
            value = self._env.get(name)
            if isinstance(value, str) and value:
                if not value.isascii() or any(
                    ord(c) <= 32 or ord(c) == 127 for c in value
                ):
                    return None
                return value
        return None

    def ready(self, capability: str = "text") -> bool:
        """Configuration readiness only, not a claim of model/account capability."""
        if capability not in ("text", "vision", "image"):
            return False
        return bool(self._key()) and (
            capability != "image"
            or (self.provider == "google" and self.image_model is not None)
        )

    def _post(self, payload, *, model):
        key = self._key()
        if not key:
            raise ProviderError("missing_key")
        url = (
            GOOGLE_URL.format(quote(model, safe=""))
            if self.provider == "google"
            else MISTRAL_URL
        )
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.provider == "google":
            headers["x-goog-api-key"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"
        try:
            data = json.dumps(payload, allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ValueError("Request must be JSON serializable.") from None
        req = request.Request(url, data=data, headers=headers, method="POST")
        try:
            with self._transport(req, timeout=self.timeout) as response:
                status = response.getcode()
                if status != 200:
                    raise ProviderError("http_error", status=status)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            code = (
                "authentication"
                if status in (401, 403)
                else "quota"
                if status == 429
                else "http_error"
            )
            raise ProviderError(code, status=status) from None
        except (URLError, OSError, http.client.HTTPException):
            raise ProviderError("transport_error") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("response_too_large")
        return _json_object(raw)

    def complete(self, messages: list[dict], schema: dict, images=None) -> dict:
        """Return {output: dict, usage: token counts, response_id: str | None}.

        Messages have role system/user/assistant and string content. Additional
        remote content blocks are rejected. Approved images attach to the last user
        message only. No filesystem paths or remote URLs are accepted.
        """
        if not isinstance(schema, dict) or not schema:
            raise ValueError("A non-empty JSON schema is required.")
        if not isinstance(messages, list) or not messages:
            raise ValueError("Messages must be a non-empty list.")
        for message in messages:
            if (
                not isinstance(message, dict)
                or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant")
                or not isinstance(message["content"], str)
            ):
                raise ValueError(
                    "Messages require a supported role and string content only."
                )
        approved = [] if images is None else images
        if not isinstance(approved, list) or len(approved) > MAX_IMAGES:
            raise ValueError("At most three approved image data URLs are permitted.")
        for src in approved:
            with canvas_assets.decode_image(src):
                pass
        users = [i for i, message in enumerate(messages) if message["role"] == "user"]
        if not users:
            raise ValueError("At least one user message is required.")
        last_user = users[-1]
        if self.provider == "google":
            contents, system = [], []
            for i, message in enumerate(messages):
                parts = [{"text": message["content"]}]
                if i == last_user:
                    for src in approved:
                        header, data = src.split(",", 1)
                        parts.append(
                            {
                                "inlineData": {
                                    "mimeType": header[5:].split(";")[0],
                                    "data": data,
                                }
                            }
                        )
                if message["role"] == "system":
                    system.extend(parts)
                else:
                    contents.append(
                        {
                            "role": "model"
                            if message["role"] == "assistant"
                            else "user",
                            "parts": parts,
                        }
                    )
            payload = {
                "contents": contents,
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "responseJsonSchema": schema,
                    "candidateCount": 1,
                    "maxOutputTokens": 16384,
                },
            }
            if system:
                payload["systemInstruction"] = {"parts": system}
        else:
            wire_messages = [dict(message) for message in messages]
            if approved:
                wire_messages[last_user]["content"] = [
                    {"type": "text", "text": messages[last_user]["content"]},
                    *[
                        {"type": "image_url", "image_url": {"url": src}}
                        for src in approved
                    ],
                ]
            payload = {
                "model": self.model,
                "messages": wire_messages,
                "stream": False,
                "max_tokens": 16384,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "generation_output",
                        "schema": schema,
                        "strict": True,
                    },
                },
            }
        body = self._post(payload, model=self.model)
        if self.provider == "google":
            parts = _google_parts(body)
            visible = [p for p in parts if not p.get("thought", False)]
            if not visible or any(not isinstance(p.get("text"), str) for p in visible):
                raise ProviderError("invalid_response")
            text = "".join(p["text"] for p in visible)
        else:
            choices = body.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
            ):
                raise ProviderError("invalid_response")
            choice = choices[0]
            message = choice.get("message")
            if not isinstance(message, dict):
                raise ProviderError("invalid_response")
            if message.get("refusal") or choice.get("finish_reason") != "stop":
                raise ProviderError("incomplete_or_refused")
            if message.get("tool_calls"):
                raise ProviderError("invalid_response")
            text = message.get("content")
            if not isinstance(text, str):
                raise ProviderError("invalid_response")
        return {"output": _json_object(text), **_metadata(body, self.provider)}

    def generate_image(self, prompt: str, *, model: str | None = None) -> dict:
        """Generate one native Google image; return the same envelope with a data URL.

        Requires an explicit image_model at construction or server-owned model here.
        Raster validation precedes resizing (1600px) and fixed JPEG encoding; assets
        exceeding 256 KiB fail rather than retry. Never use the text model by default.
        """
        image_model = validate_model(model) if model is not None else self.image_model
        if self.provider != "google" or image_model is None:
            raise ProviderError("image_not_configured")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("A non-empty image prompt is required.")
        body = self._post(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "candidateCount": 1,
                    "maxOutputTokens": 16384,
                },
            },
            model=image_model,
        )
        images = [
            p["inlineData"]
            for p in _google_parts(body)
            if "inlineData" in p and not p.get("thought", False)
        ]
        if len(images) != 1 or not isinstance(images[0], dict):
            raise ProviderError("invalid_image_response")
        src = _generated_asset(images[0])
        return {"output": src, **_metadata(body, self.provider)}


def _generated_asset(inline):
    mime = inline.get("mimeType")
    encoded = inline.get("data")
    if mime not in ("image/png", "image/jpeg") or not isinstance(encoded, str):
        raise ProviderError("invalid_image_response")
    try:
        data = base64.b64decode(encoded, validate=True)
        expected = "PNG" if mime == "image/png" else "JPEG"
        with Image.open(BytesIO(data)) as image:
            if (
                image.format != expected
                or getattr(image, "n_frames", 1) != 1
                or max(image.size) > MAX_GENERATED_DIMENSION
                or image.width * image.height > MAX_GENERATED_PIXELS
            ):
                raise ProviderError("invalid_image_response")
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
            raster = image.convert("RGB")
        with raster:
            raster.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            output = BytesIO()
            raster.save(output, format="JPEG", quality=80, optimize=True)
        src = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode(
            "ascii"
        )
        with canvas_assets.decode_image(src):
            pass
        return src
    except (
        ValueError,
        binascii.Error,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ProviderError("invalid_image_response") from None
