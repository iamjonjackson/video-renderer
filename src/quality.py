"""Deterministic render checks; not a substitute for factual or full-film review."""

import base64
from io import BytesIO


def _composition():
    if __package__:
        from . import composition
    else:
        import composition
    return composition


def _times(scene):
    """Sample the film and include authored cues, including group/chunk cues."""
    duration = scene["duration"]
    times = {
        duration * n / max(1, round(duration * 24))
        for n in range(max(1, round(duration * 24)) + 1)
    }
    for item in scene["elements"] + scene.get("groups", []):
        times.update(frame["time"] for frame in item.get("keyframes", []))
        for track in ("animation", "exit_animation"):
            if track in item:
                times.update(
                    (
                        item[track]["start"],
                        item[track]["start"] + item[track]["duration"],
                    )
                )
        for chunk in item.get("chunks", []):
            times.update((chunk["start"], chunk["start"] + chunk["duration"]))
    return sorted(t for t in times if 0 <= t <= duration)


def _bounds(item, state):
    left = item["x"] + state["dx"] - item["w"] * (state["scale"] - 1) / 2
    top = item["y"] + state["dy"] - item["h"] * (state["scale"] - 1) / 2
    return (
        left,
        top,
        left + item["w"] * state["scale"],
        top + item["h"] * state["scale"],
    )


def _contains(outer, inner):
    return all(a <= b + 1e-6 for a, b in zip(outer[:2], inner[:2])) and all(
        a >= b - 1e-6 for a, b in zip(outer[2:], inner[2:])
    )


def _overlaps(a, b):
    return (
        min(a[2], b[2]) - max(a[0], b[0]) > 1e-6
        and min(a[3], b[3]) - max(a[1], b[1]) > 1e-6
    )


def _fully_revealed(composition, item, t):
    if item.get("animation", {}).get("effect") == "chunks":
        return composition.chunk_visible_characters(item, t) == len(item["text"])
    return composition.reveal_progress(item, t) >= 1 - 1e-9


def inspect_document(spec):
    """Mechanical evidence only. Bounds/overlaps/holds are sampled at 24 Hz plus cues.

    Errors reject clipping, text collisions and insufficient text contrast. Holds
    and unknown image/pattern backgrounds are advisory, never a taste score.
    """
    composition = _composition()
    resolution = spec.get("meta", {}).get("resolution", {"width": 1920, "height": 1080})
    width, height = resolution["width"], resolution["height"]
    if __package__:
        from .images import contrast_ratio, luminance
    else:
        from images import contrast_ratio, luminance
    errors, warnings = [], []

    def issue(target, message):
        if message not in target and len(target) < 100:
            target.append(message)

    for index, scene in enumerate(spec["timeline"]):
        if scene["type"] != "composition":
            continue
        times = _times(scene)
        poses = [
            {
                item["id"]: composition.scene_motion_state(scene, item, t)
                for item in scene["elements"]
            }
            for t in times
        ]
        for z, item in enumerate(scene["elements"]):
            label = f"Scene {index + 1}, {str(item['id'])[:60]}"
            for states in poses:
                state = states[item["id"]]
                if state["opacity"] < 0.05:
                    continue
                bounds = _bounds(item, state)
                if not _contains((0, 0, 1, 1), bounds):
                    issue(errors, label + ": transformed bounds leave canvas")
            if item["type"] != "text":
                continue
            if item["font_size"] < 0.02:
                issue(errors, label + ": text below supported minimum size")
            boxw, boxh = (
                max(1, round(item["w"] * width)),
                max(1, round(item["h"] * height)),
            )
            font = composition.ImageFont.truetype(
                composition.font_path(
                    item.get("bold", False), item.get("font_family", "sans")
                ),
                max(8, round(item["font_size"] * boxh / item["h"])),
            )
            if any(
                font.getlength(word) > boxw - 8
                for paragraph in item["text"].split("\n")
                for word in paragraph.split(" ")
            ):
                issue(errors, label + ": unbreakable text exceeds its box")
            # Ask the actual renderer for its resting layout with extra vertical
            # space, preserving its rounded font size. No second wrapping engine.
            # Every space can create at most one extra line. Bound the probe
            # width and height by validated text, rather than allocating per char.
            max_lines = len(item["text"].split(" ")) + item["text"].count("\n")
            probe_height = max(boxh, (max_lines + 1) * round(font.size * 1.25))
            probe = dict(item, h=item["h"] * probe_height / boxh)
            raster = composition.text_image(probe, boxw, probe_height)
            ink = raster.getchannel("A").getbbox()
            if ink and ink[3] > boxh:
                issue(errors, label + ": text height exceeds its box")
            longest, current = 0.0, 0.0
            for n in range(1, len(times)):
                endpoints = (n - 1, n)
                if all(
                    poses[k][item["id"]]["opacity"] >= 0.95
                    and _fully_revealed(composition, item, times[k])
                    for k in endpoints
                ):
                    current += times[n] - times[n - 1]
                    longest = max(longest, current)
                else:
                    current = 0.0
            if longest + 1e-6 < max(1, len(item["text"].split()) / 4):
                issue(
                    warnings,
                    label + ": review reading hold (fully revealed, opaque text)",
                )
            target = (
                3.0 if item.get("bold", False) and item["font_size"] >= 0.04 else 4.5
            )
            for t, states in zip(times, poses):
                state = states[item["id"]]
                if state["opacity"] < 0.95 or not _fully_revealed(composition, item, t):
                    continue
                bounds = _bounds(item, state)
                background = scene.get("background", {})
                bg_color = background.get("color", "#191925")
                unknown = background.get("style", "solid") != "solid"
                for earlier in scene["elements"][:z]:
                    pose = states[earlier["id"]]
                    if pose["opacity"] < 0.05 or not _overlaps(
                        _bounds(earlier, pose), bounds
                    ):
                        continue
                    if (
                        earlier["type"] == "shape"
                        and earlier.get("shape", "rect") == "rect"
                        and pose["opacity"] >= 0.999
                        and _contains(_bounds(earlier, pose), bounds)
                    ):
                        bg_color, unknown = earlier["color"], False
                    else:
                        unknown = True
                if unknown:
                    issue(
                        warnings,
                        label
                        + ": review contrast over image, patterned or partial background",
                    )
                elif (
                    contrast_ratio(luminance(item["color"]), luminance(bg_color))
                    < target
                ):
                    issue(errors, label + f": text contrast below {target:g}:1")
                for other_z, other in enumerate(scene["elements"]):
                    # Text pairs need one report; other content matters at either z.
                    if other_z == z or (other["type"] == "text" and other_z < z):
                        continue
                    # Panels and paths are decoration, not essential content.
                    if other["type"] not in ("text", "chart", "image", "icon"):
                        continue
                    pose = states[other["id"]]
                    if (
                        pose["opacity"] >= 0.95
                        and composition.reveal_progress(other, t) > 0
                        and (
                            other["type"] != "text"
                            or _fully_revealed(composition, other, t)
                        )
                        and _overlaps(bounds, _bounds(other, pose))
                    ):
                        issue(
                            errors,
                            label
                            + f": essential content overlaps {str(other['id'])[:60]}",
                        )
    return {"errors": errors, "warnings": warnings, "requires_human_review": True}


def render_contact_frames(spec):
    """Bounded, local low-resolution evidence sent to vision only after explicit consent."""
    composition = _composition()
    resolution = spec["meta"]["resolution"]
    width = 640
    height = round(width * resolution["height"] / resolution["width"])
    frames = []
    for scene in spec["timeline"][:3]:
        if scene["type"] != "composition":
            continue
        clip = composition.build_clip(scene, width, height)
        try:
            pixels = clip.get_frame(scene["duration"] * 0.65)
            if pixels is None:
                raise ValueError("Rendered evidence frame is unavailable.")
            image = composition.Image.fromarray(pixels)
            output = BytesIO()
            image.save(output, format="JPEG", quality=75)
            frames.append(
                "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
            )
        finally:
            clip.close()
    return frames
