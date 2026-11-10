"""Portable, bounded PNG/JPEG canvas assets; no filesystem or network sources."""

import base64
import binascii
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 256 * 1024
MAX_IMAGE_DIMENSION = 2048
MAX_IMAGE_PIXELS = 4_000_000


def image_bytes(src: str) -> bytes:
    """Decode only canonical base64 PNG/JPEG data URLs within the byte budget."""
    if not isinstance(src, str):
        raise ValueError("Image src must be a PNG or JPEG data URL.")
    header, separator, payload = src.partition(",")
    if not separator or header not in ("data:image/png;base64", "data:image/jpeg;base64"):
        raise ValueError("Image src must be a PNG or JPEG data URL.")
    if not payload or len(payload) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError("Image asset exceeds 256 KiB or is empty.")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image src must contain canonical base64.") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image asset exceeds 256 KiB.")
    if base64.b64encode(data).decode("ascii") != payload:
        raise ValueError("Image src must contain canonical base64.")
    return data


@lru_cache(maxsize=8)
def _decoded_image(src: str) -> Image.Image:
    data = image_bytes(src)
    expected = "PNG" if src.startswith("data:image/png;") else "JPEG"
    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != expected:
                raise ValueError("Image MIME type must match its raster format.")
            width, height = image.size
            if (width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS):
                raise ValueError("Image dimensions exceed 2048 per side or 4 million pixels.")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Animated images are not supported.")
            image.verify()
        # verify() checks container integrity; load() also rejects broken raster data.
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.convert("RGBA")
    except (OSError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image src contains an invalid raster image.") from exc


def decode_image(src: str) -> Image.Image:
    """Validate and fully decode an asset; callers own a copy of the cached raster."""
    if not isinstance(src, str):
        raise ValueError("Image src must be a PNG or JPEG data URL.")
    return _decoded_image(src).copy()


def raster_image(item, width: int, height: int) -> Image.Image:
    """Fit an asset to its RGBA box without distortion; contain stays transparent."""
    image = decode_image(item["src"])
    fit = item.get("fit", "cover")
    if fit == "cover":
        return ImageOps.fit(image, (width, height), method=Image.Resampling.LANCZOS)
    if fit != "contain":
        raise ValueError("Image fit must be cover or contain.")
    fitted = ImageOps.contain(image, (width, height), method=Image.Resampling.LANCZOS)
    box = Image.new("RGBA", (width, height))
    box.alpha_composite(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return box
