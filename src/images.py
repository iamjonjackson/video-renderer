import base64
import hashlib
import json
import os
from pathlib import Path
from urllib import request as _rq
from urllib.error import HTTPError

IMAGES_URL = "https://api.mistral.ai/v1/images/generations"
DEFAULT_IMAGE_MODEL = "flux-schnell"


def generate_image(prompt: str, out_path: str, model: str | None = None,
                   workdir: Path | None = None) -> str:
    """Generate an image via the Mistral images API; return its path.

    Cached by prompt+model hash in workdir, mirroring narration caching.
    """
    key = hashlib.sha1(f"{prompt}|{model or DEFAULT_IMAGE_MODEL}".encode()).hexdigest()[:12]
    if workdir:
        cached = Path(workdir) / f"img_{key}.png"
        if cached.exists():
            return str(cached)
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY not set; cannot generate images")

    payload = {"model": model or DEFAULT_IMAGE_MODEL, "prompt": prompt}
    req = _rq.Request(
        IMAGES_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with _rq.urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read())
    except HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"Image API error {e.code}: {detail}") from e

    items = body.get("data") or []
    if not items:
        raise RuntimeError(f"Unexpected image response keys: {list(body)}")
    item = items[0]
    if item.get("b64_json"):
        data = base64.b64decode(item["b64_json"])
    elif item.get("url"):
        with _rq.urlopen(item["url"], timeout=300) as r:
            data = r.read()
    else:
        raise RuntimeError(f"No image data in response item keys: {list(item)}")

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
