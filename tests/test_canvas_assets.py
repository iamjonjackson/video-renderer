"""Raster security bounds and independent aspect-ratio pixel expectations."""

import base64
from io import BytesIO
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.canvas_assets import decode_image, image_bytes, raster_image


def data_url(image, format="PNG", **kwargs):
    stream = BytesIO()
    image.save(stream, format=format, **kwargs)
    mime = "png" if format == "PNG" else "jpeg"
    return f"data:image/{mime};base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def striped_src():
    image = Image.new("RGB", (120, 40), "green")
    image.paste("red", (0, 0, 40, 40))
    image.paste("blue", (80, 0, 120, 40))
    return data_url(image)


class CanvasAssetTests(unittest.TestCase):
    def test_png_jpeg_decode_and_cached_raster_is_not_mutable_by_callers(self):
        for format in ("PNG", "JPEG"):
            src = data_url(Image.new("RGB", (12, 8), "red"), format)
            image = decode_image(src)
            self.assertEqual(image.size, (12, 8))
            self.assertEqual(image.mode, "RGBA")
            image.putpixel((0, 0), (0, 0, 0, 0))
            self.assertEqual(decode_image(src).getpixel((0, 0))[3], 255)

    def test_cover_center_crops_and_contain_letterboxes_without_distortion(self):
        item = {"src": striped_src()}
        cover = raster_image(item, 40, 40)
        self.assertEqual(cover.getpixel((20, 20)), (0, 128, 0, 255))
        self.assertEqual(cover.getpixel((2, 20)), (0, 128, 0, 255))
        contain = raster_image({**item, "fit": "contain"}, 120, 120)
        self.assertEqual(contain.getpixel((60, 20))[3], 0)
        self.assertEqual(contain.getpixel((20, 60)), (255, 0, 0, 255))
        self.assertEqual(contain.getpixel((60, 60)), (0, 128, 0, 255))
        self.assertEqual(contain.getpixel((100, 60)), (0, 0, 255, 255))
        self.assertEqual(contain.getpixel((60, 100))[3], 0)

    def test_nonportable_bad_mime_and_noncanonical_base64_are_rejected(self):
        png = data_url(Image.new("RGB", (4, 4)))
        for src in (None, [], {}, "/tmp/image.png", "https://example.com/image.png",
                    "data:image/svg+xml;base64,PHN2Zy8+", "data:image/gif;base64,R0lG",
                    "data:image/png;base64,", "data:image/png;base64,!!!!",
                    "data:image/png;base64,AB==", png + "\n",
                    png.replace("image/png", "image/jpeg")):
            with self.subTest(src=str(src)[:50]), self.assertRaises(ValueError):
                decode_image(src)

    def test_truncated_malformed_and_animated_images_are_rejected(self):
        png = data_url(Image.new("RGB", (12, 8)))
        raw = image_bytes(png)
        animated = data_url(Image.new("RGBA", (12, 8), "red"), save_all=True,
                            append_images=[Image.new("RGBA", (12, 8), "blue")], duration=100)
        for src in ("data:image/png;base64," + base64.b64encode(raw[:-15]).decode(),
                    "data:image/png;base64," + base64.b64encode(b"not a raster").decode(),
                    animated):
            with self.subTest(src=src[:70]), self.assertRaises(ValueError):
                decode_image(src)

    def test_byte_side_and_total_pixel_budgets_are_enforced(self):
        src = "data:image/png;base64," + base64.b64encode(b"x" * (256 * 1024 + 1)).decode()
        with self.assertRaises(ValueError):
            decode_image(src)
        for size in ((2049, 1), (1, 2049), (2048, 2048)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                decode_image(data_url(Image.new("RGB", size)))
        self.assertEqual(decode_image(data_url(Image.new("RGB", (2000, 2000)))).size,
                         (2000, 2000))

    def test_transparency_survives_fitting(self):
        image = Image.new("RGBA", (12, 8), (255, 0, 0, 128))
        fitted = raster_image({"src": data_url(image)}, 12, 8)
        self.assertEqual(fitted.getpixel((6, 4)), (255, 0, 0, 128))


if __name__ == "__main__":
    unittest.main()
