import hashlib
import json
import os
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError

BASE_URL = "https://api.mistral.ai/v1"
DEFAULT_IMAGE_MODEL = "mistral-medium-latest"


def _headers(api_key: str, ctype: str = "application/json") -> dict:
    h = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    if ctype:
        h["Content-Type"] = ctype
    return h


def _post(path: str, payload: dict, api_key: str) -> dict:
    req = _rq.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers=_headers(api_key),
        method="POST",
    )
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Image API error {e.code} on {path}: {detail}") from e


def _get(path: str, api_key: str, accept: str = "application/json") -> bytes:
    req = _rq.Request(
        BASE_URL + path,
        headers={"Authorization": f"Bearer {api_key}", "Accept": accept},
        method="GET",
    )
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            return resp.read()
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Image API error {e.code} on {path}: {detail}") from e


def _find_file_chunk(obj) -> str | None:
    """Recursively find the first tool_file chunk with a file_id."""
    if isinstance(obj, dict):
        if obj.get("type") == "tool_file" and obj.get("file_id"):
            return obj["file_id"]
        for v in obj.values():
            found = _find_file_chunk(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_file_chunk(item)
            if found:
                return found
    return None


def _find_image_url(obj) -> str | None:
    """Recursively find an image URL in tool.execution info.result strings."""
    if isinstance(obj, dict):
        info = obj.get("info")
        if isinstance(info, dict):
            result = info.get("result")
            if isinstance(result, str):
                try:
                    parsed = json.loads(result)
                    url = parsed.get("url") or parsed.get("image_url")
                    if isinstance(url, str) and url.startswith("http"):
                        return url
                except (ValueError, AttributeError):
                    pass
        for v in obj.values():
            found = _find_image_url(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_image_url(item)
            if found:
                return found
    return None


def generate_image(prompt: str, out_path: str, model: str | None = None,
                   workdir: Path | None = None) -> str:
    """Generate an image via the Mistral agents image_generation tool.

    Flow: create (or reuse cached) image-gen agent, start a conversation
    with the prompt, download the tool_file via /v1/files. Cached by
    prompt+model hash in workdir, mirroring narration caching.
    """
    key = hashlib.sha1(f"{prompt}|{model or DEFAULT_IMAGE_MODEL}".encode()).hexdigest()[:12]
    if workdir:
        cached = Path(workdir) / f"img_{key}.png"
        if cached.exists():
            return str(cached)
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY not set; cannot generate images")

    cache_path = Path(workdir or ".") / f"imgagent_{key}.id"
    agent_id = None
    if cache_path.exists():
        agent_id = cache_path.read_text().strip()

    if not agent_id:
        agent = _post("/agents", {
            "model": model or DEFAULT_IMAGE_MODEL,
            "name": f"video-renderer-img-{key}",
            "description": "Generates scene images for video-renderer specs.",
            "instructions": "Generate the requested image directly, no commentary.",
            "tools": [{"type": "image_generation"}],
        }, api_key)
        agent_id = agent.get("id")
        if not agent_id:
            raise RuntimeError(f"No agent id in response keys: {list(agent)}")
        if workdir:
            cache_path.write_text(agent_id)

    conv = _post("/conversations", {
        "agent_id": agent_id,
        "inputs": prompt,
    }, api_key)

    file_id = _find_file_chunk(conv)
    if file_id:
        data = _get(f"/files/{file_id}/content", api_key,
                    accept="application/octet-stream")
    else:
        url = _find_image_url(conv)
        if not url:
            if os.environ.get("IMAGE_DEBUG"):
                print(f"[debug] conversation response: "
                      f"{json.dumps(conv)[:2000]}")
            raise RuntimeError("No image tool_file or image URL in "
                               f"conversation output; keys: {list(conv)}")
        req = _rq.Request(url)
        with _rq.urlopen(req, timeout=300) as r:
            data = r.read()
    Path(out_path).write_bytes(data)
    return str(out_path)


def luminance(hex_color: str) -> float:
    """WCAG relative luminance of a hex color."""
    h = hex_color.lstrip("#")
    def chan(v):
        c = v / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def image_region_luminance(image_path: str, x_frac: float = 0.5, y_frac: float = 0.5,
                           w_frac: float = 0.6, h_frac: float = 0.3) -> float:
    """Mean WCAG luminance of a region of an image (fractions of its extent)."""
    from PIL import Image
    import numpy as np
    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    x0 = max(0, int(W * (x_frac - w_frac / 2)))
    x1 = min(W, int(W * (x_frac + w_frac / 2)))
    y0 = max(0, int(H * (y_frac - h_frac / 2)))
    y1 = min(H, int(H * (y_frac + h_frac / 2)))
    arr = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.float32) / 255.0
    def chan(c):
        return np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = chan(arr[..., 0]), chan(arr[..., 1]), chan(arr[..., 2])
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return float(lum.mean())


def contrast_ratio(l1: float, l2: float) -> float:
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def scrim_for_contrast(image_path: str, fg_color: str, bg_color: str,
                       text_area=(0.5, 0.5, 0.6, 0.3), img_opacity: float = 0.25,
                       target_ratio: float = 4.5, max_scrim: float = 0.85) -> tuple[float, bool]:
    """Best-effort scrim opacity so text meets WCAG AA contrast over a faded image.

    Returns (scrim_opacity, passes). Never raises; on any analysis failure
    returns a safe default scrim.
    """
    try:
        l_fg = luminance(fg_color)
        l_bg = luminance(bg_color)
        x, y, w, h = text_area
        l_img = image_region_luminance(image_path, x, y, w, h)
        passes = False
        scrim = 0.0
        for cand in [i / 20 for i in range(0, int(max_scrim * 20) + 1)]:
            l_eff = cand * l_bg + (1 - cand) * (img_opacity * l_img + (1 - img_opacity) * l_bg)
            if contrast_ratio(l_fg, l_eff) >= target_ratio:
                scrim = cand
                passes = True
                break
        if not passes:
            scrim = max_scrim
        return scrim, passes
    except Exception:
        return 0.6, False
