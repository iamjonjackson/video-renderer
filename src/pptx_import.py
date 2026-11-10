"""read slide edits and prepare slide images without changing the original files"""
import copy
import json
import math
from pathlib import Path
import shutil
import subprocess

from PIL import Image
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE

import pptx_export

CHART_TYPES = {value: key for key, value in pptx_export.CHART_TYPES.items()}
CHART_TYPES[XL_CHART_TYPE.LINE] = "line"


def chart_readout(scene):
    """describe the saved labels and values without inventing a trend or explanation"""
    parts = []
    for text in (scene.get("heading"), scene.get("y_label")):
        if text and text not in parts:
            parts.append(text.rstrip("."))
    if not parts:
        parts.append("Chart values")
    for label, value in zip(scene["labels"], scene["values"]):
        parts.append(f"{label}: {value}")
    return ". ".join(parts) + "."


def _text_edits(scene, slide):
    """read the existing slide text boxes in the order used by the exporter"""
    kind = scene["type"]
    boxes = [shape.text_frame for shape in slide.shapes if shape.has_text_frame
             and shape.text.strip()]
    # background rectangles have empty text frames and are not narration
    if kind in ("title", "outro"):
        expected = 1
    elif kind == "bullets":
        expected = int(bool(scene.get("heading"))) + int(bool(scene.get("items")))
    elif kind == "image":
        expected = int(bool(scene.get("caption")))
    else:
        raise ValueError(f"Text import does not support scene type '{kind}'")
    # extra or deleted boxes make field matching ambiguous in older decks
    if len(boxes) != expected:
        raise ValueError("Keep the existing text boxes when editing wording; added or empty boxes cannot be matched safely")
    if kind in ("title", "outro"):
        lines = [paragraph.text for paragraph in boxes[0].paragraphs]
        updates = {"text": lines[0]}
        if len(lines) > 1 or scene.get("subtitle"):
            updates["subtitle"] = "\n".join(lines[1:])
    elif kind == "bullets":
        updates = {}
        if scene.get("heading"):
            updates["heading"] = boxes.pop(0).text
        if scene.get("items"):
            # only remove the bullet prefix inserted by the exporter
            updates["items"] = [p.text.removeprefix("\u2022 ") for p in boxes[0].paragraphs
                                if p.text.strip()]
    else:
        updates = {"caption": boxes[0].text} if boxes else {}
    if all(scene.get(key, "") == value for key, value in updates.items()):
        return False
    scene.update(updates)
    # read the revised wording directly rather than guessing how an old script should change
    words = ([scene.get("text"), scene.get("subtitle")] if kind in ("title", "outro")
             else [scene.get("heading"), *scene.get("items", [])] if kind == "bullets"
             else [scene.get("caption")])
    scene["narration"] = " ".join(text.strip() + ("" if text.rstrip().endswith((".", "!", "?")) else ".")
                                  for text in words if text and text.strip())
    scene.pop("narration_per_bullet", None)
    return True


def import_chart_edits(spec_path, pptx_path):
    """copy chart and wording edits into a new spec while retaining unchanged narration"""
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    prs = Presentation(pptx_path)
    if len(prs.slides) != len(spec["timeline"]):
        raise ValueError("The edited deck must keep the original slide count and order")
    if abs(prs.slide_width / prs.slide_height - 16 / 9) > 0.01:
        raise ValueError("The edited deck must keep the renderer's 16:9 slide size")
    chart_indices, changed = [], []
    for index, (scene, slide) in enumerate(zip(spec["timeline"], prs.slides)):
        charts = [shape for shape in slide.shapes if shape.has_chart]
        if scene["type"] != "chart":
            if charts:
                raise ValueError(f"Slide {index + 1} does not match the original scene order")
            if _text_edits(scene, slide):
                changed.append(index)
            continue
        chart_indices.append(index)
        if not charts and scene.get("pptx_chart") == "png":
            continue
        if len(charts) != 1:
            raise ValueError(f"Slide {index + 1} needs one native chart")
        shape = charts[0]
        if shape.name.startswith("renderer-chart-") and shape.name != f"renderer-chart-{index}":
            raise ValueError(f"Slide {index + 1} was reordered; restore the original slide order")
        chart = shape.chart
        if chart.chart_type not in CHART_TYPES or len(chart.series) != 1 or len(chart.plots) != 1:
            raise ValueError(f"Slide {index + 1} needs a single-series bar, line or pie chart")
        if chart.plots[0].categories.depth != 1:
            raise ValueError(f"Slide {index + 1} needs a single level of category labels")
        labels = [category.label for category in chart.plots[0].categories]
        values = list(chart.series[0].values)
        if not labels or len(labels) != len(values) or any(v is None or not math.isfinite(v) for v in values):
            raise ValueError(f"Slide {index + 1} has empty or incomplete chart data")
        values = [int(v) if v.is_integer() else v for v in values]
        kind = CHART_TYPES[chart.chart_type]
        updates = dict(labels=labels, values=values, chart_type=kind,
                       heading=chart.chart_title.text_frame.text if chart.has_title else "")
        if kind != "pie":
            updates["y_label"] = chart.value_axis.axis_title.text_frame.text if chart.value_axis.has_title else ""
        if any(scene.get(key, "bar" if key == "chart_type" else "") != value for key, value in updates.items()):
            scene.update(updates)
            # changed data needs new speech, rather than audio describing the old numbers
            scene["narration"] = chart_readout(scene)
            scene.pop("narration_per_bullet", None)
            changed.append(index)
    # changed text slides use saved slide images too, so video and deck show the same wording
    return spec, sorted(set(chart_indices + changed)), changed


def chart_slide_images(pptx_path, indices, directory, width=1920, height=1080, slides_dir=None):
    """render saved slides so their wording and formatting do not need to be guessed"""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if slides_dir:
        # powerpoint exports slides as slide1.png, slide2.png and so on
        files = {path.name.lower(): path for path in Path(slides_dir).iterdir() if path.is_file()}
        result = {}
        for index in indices:
            path = files.get(f"slide{index + 1}.png")
            if not path:
                raise ValueError(f"Missing Slide{index + 1}.png in the exported slide folder")
            with Image.open(path) as image:
                if abs(image.width / image.height - width / height) > 0.01:
                    raise ValueError(f"Slide{index + 1}.png has the wrong aspect ratio")
                output = directory / f"slide{index + 1}.png"
                image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS).save(output)
                result[index] = output
        return result
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        candidate = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
        executable = str(candidate) if candidate.exists() else None
    if not executable:
        raise RuntimeError("Install LibreOffice for automatic slide rendering, or pass --slides-dir with PowerPoint-exported PNGs")
    try:
        import pymupdf
    except ImportError:
        raise RuntimeError("Automatic slide rendering also needs: python -m pip install pymupdf") from None
    # render a copy without narration icons, retaining the actual edited chart styling
    visual_deck = directory / "visuals.pptx"
    prs = Presentation(pptx_path)
    for slide in prs.slides:
        pptx_export.remove_narration(slide)
    prs.save(visual_deck)
    profile = (directory / "libreoffice-profile").resolve().as_uri()
    subprocess.run([executable, f"-env:UserInstallation={profile}", "--headless", "--convert-to",
                    "pdf:impress_pdf_Export", "--outdir", str(directory), str(visual_deck)],
                   check=True, capture_output=True, text=True, timeout=120)
    pdf = visual_deck.with_suffix(".pdf")
    if not pdf.exists():
        raise RuntimeError("LibreOffice did not produce the slide PDF")
    result = {}
    with pymupdf.open(pdf) as document:
        if len(document) != len(prs.slides):
            raise ValueError("The rendered PDF has an unexpected slide count")
        for index in indices:
            page = document[index]
            matrix = pymupdf.Matrix(width / page.rect.width, height / page.rect.height)
            output = directory / f"slide{index + 1}.png"
            page.get_pixmap(matrix=matrix, alpha=False).save(output)
            result[index] = output
    return result


def video_spec(spec, images):
    """use saved chart slide images only for the video, keeping the published spec editable"""
    result = copy.deepcopy(spec)
    for index, path in images.items():
        scene = result["timeline"][index]
        result["timeline"][index] = {
            key: value for key, value in scene.items()
            if key in ("narration", "narration_per_bullet", "duration", "padding", "anim")
        }
        result["timeline"][index].update(type="image", src=str(path.resolve()))
    return result
