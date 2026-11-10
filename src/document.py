"""Versioned production documents shared by Studio and the legacy CLI."""

import copy
import importlib
import math
import re


class SpecError(ValueError):
    """A document cannot be rendered under the selected input policy."""


def validate_spec(value, studio=True):
    """Return a validated copy, migrating unversioned documents to version 1.

    Studio enforces a 12-scene/60-second envelope and disallows filesystem image
    scenes and provider-generated legacy images. CLI retains legacy timing,
    theme sizes, frame rates and image settings; compositions share one validator.
    Validation never opens legacy image paths or calls a provider.
    """

    def object_fields(obj, allowed, where):
        if where == "Canvas scene":
            allowed = tuple(allowed) + ("source_ids", "beats", "groups")
        if not isinstance(obj, dict) or set(obj) - set(allowed):
            raise SpecError(f"{where}: expected an object with supported fields only.")

    def text(value, where, maximum=600):
        if not isinstance(value, str) or len(value) > maximum:
            raise SpecError(f"{where}: use text of at most {maximum} characters.")

    def legacy_text(value, where, maximum):
        if studio:
            text(value, where, maximum)
        elif not isinstance(value, str):
            raise SpecError(f"{where}: use text.")

    def number(value, where, low, high):
        if (
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not low <= value <= high
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise SpecError(f"{where}: use a number between {low} and {high}.")

    object_fields(value, ("version", "meta", "theme", "timeline", "voice") + (() if studio else ("branding",)), "Project")
    if "branding" in value:
        branding = value["branding"]
        object_fields(branding, ("logo", "position", "margin", "opacity", "max_height", "scenes"), "Branding")
        text(branding.get("logo"), "Branding logo", 4096)
        if not branding["logo"].strip():
            raise SpecError("Branding logo must be a non-empty path.")
        if branding.get("position", "bottom-right") not in ("top-left", "top-right", "bottom-left", "bottom-right"):
            raise SpecError("Choose a supported branding corner.")
        margin = branding.get("margin", 40)
        if type(margin) is not int or margin < 1:
            raise SpecError("Branding margin must be a positive integer.")
        number(branding.get("opacity", .85), "Branding opacity", 0, 1)
        number(branding.get("max_height", .10), "Branding height", .000001, 1)
        selected = branding.get("scenes", "all")
        if selected != "all" and (not isinstance(selected, list) or any(kind not in ("title", "bullets", "image", "chart", "outro", "composition") for kind in selected)):
            raise SpecError("Branding scenes must be all or supported scene types.")
    version = value.get("version", 1)
    if type(version) is not int or version != 1:
        raise SpecError("Project: only document version 1 is supported.")
    spec = copy.deepcopy(value)
    spec["version"] = 1
    meta = spec.setdefault("meta", {})
    object_fields(meta, ("title", "fps", "resolution", "tts"), "Project settings")
    if "tts" in meta:
        object_fields(meta["tts"], ("provider", "voice", "model", "style"), "Narration")
        for key, item in meta["tts"].items():
            legacy_text(item, f"Narration {key}", 200)
    legacy_text(meta.get("title", ""), "Project title", 100)
    fps = meta.get("fps", 30)
    if studio:
        if fps not in (24, 30):
            raise SpecError("Frame rate: choose 24 or 30 fps.")
    else:
        number(fps, "Frame rate", 0, float("inf"))
        if fps <= 0:
            raise SpecError("Frame rate must be positive.")
    composition = importlib.import_module(
        "src.composition" if __package__ else "composition"
    )
    resolution = meta.get("resolution", {"width": 1920, "height": 1080})
    object_fields(resolution, ("width", "height"), "Resolution")
    if any(
        type(resolution.get(key)) is not int or resolution[key] <= 0
        for key in ("width", "height")
    ):
        raise SpecError("Resolution dimensions must be positive whole numbers.")
    if (
        studio
        and (resolution["width"], resolution["height"]) not in composition.RESOLUTIONS
    ):
        raise SpecError("Choose a supported landscape, portrait or square resolution.")
    theme = spec.setdefault("theme", {})
    object_fields(
        theme, ("preset", "bg", "fg", "accent", "font_size", "title_font_size"), "Theme"
    )
    if theme.get("preset", "dark") not in ("dark", "light"):
        raise SpecError("Theme: choose dark or light.")
    for key in ("bg", "fg", "accent"):
        if key in theme and (
            not isinstance(theme[key], str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", theme[key])
        ):
            raise SpecError(f"Theme {key}: use a six-digit hex colour.")
    for key in ("font_size", "title_font_size"):
        if key in theme:
            number(
                theme[key],
                f"Theme {key}",
                24 if studio else 1,
                120 if studio else float("inf"),
            )
            if not isinstance(theme[key], int):
                raise SpecError(f"Theme {key}: use a whole number.")
    if "voice" in spec:
        object_fields(spec["voice"], ("slug", "voice_id", "model", "format"), "Voice")
        for key, item in spec["voice"].items():
            legacy_text(item, f"Voice {key}", 100)
    scenes = spec.get("timeline")
    if not isinstance(scenes, list) or not scenes or (studio and len(scenes) > 12):
        raise SpecError(
            "Timeline: include between 1 and 12 scenes."
            if studio
            else "Timeline: include at least one scene."
        )
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            raise SpecError(f"Scene {index}: expected an object.")
        # Legacy scenes without explicit timing remain audio/bullet driven.
        if studio or scene.get("type") == "composition":
            scene.setdefault("duration", 4)
        if "duration" in scene:
            number(
                scene["duration"],
                f"Scene {index} duration",
                1 if studio else 0,
                15 if studio else float("inf"),
            )
            if scene["duration"] <= 0:
                raise SpecError(f"Scene {index}: duration must be positive.")
    duration = 0
    common = ("type", "duration", "anim", "narration", "padding")
    fields = {
        "title": ("text", "subtitle"),
        "outro": ("text",),
        "bullets": ("heading", "items", "stagger", "narration_per_bullet"),
        "chart": ("heading", "chart_type", "labels", "values", "y_label", "pptx_chart"),
        "composition": (
            "name",
            "elements",
            "background",
            "motion_version",
            "transition",
            "source_ids",
            "beats",
            "groups",
        ),
    }
    if not studio:
        fields["image"] = ("src", "caption")
    for index, scene in enumerate(scenes, 1):
        where = f"Scene {index}"
        if not isinstance(scene.get("type"), str) or scene["type"] not in fields:
            raise SpecError(
                f"{where}: choose title, bullets, chart, composition or outro. Image scenes are CLI-only."
            )
        kind = scene["type"]
        extra = () if studio or kind == "composition" else ("image", "transition")
        object_fields(scene, common + fields[kind] + extra, where)
        if kind == "composition":
            try:
                composition.validate_composition(scene, text, number, object_fields)
            except ValueError as error:
                raise SpecError(f"{where}: {error}") from error
            if "source_ids" in scene:
                refs = scene["source_ids"]
                if not isinstance(refs, list) or not 1 <= len(refs) <= 20:
                    raise SpecError(f"{where}: include 1–20 source IDs.")
                for ref in refs:
                    text(ref, f"{where} source ID", 60)
                    if not ref.strip():
                        raise SpecError(f"{where}: source IDs cannot be empty.")
            if "beats" in scene:
                beats = scene["beats"]
                if not isinstance(beats, list) or len(beats) > 8:
                    raise SpecError(f"{where}: use at most 8 beats.")
                previous = -1
                for beat in beats:
                    object_fields(beat, ("label", "time"), f"{where} beat")
                    text(beat.get("label"), f"{where} beat label", 80)
                    number(beat.get("time"), f"{where} beat time", 0, scene["duration"])
                    if beat["time"] <= previous:
                        raise SpecError(f"{where}: beat times must strictly increase.")
                    previous = beat["time"]
        for key in ("text", "subtitle", "heading", "y_label", "caption", "narration"):
            if key in scene:
                maximum = (
                    (7205 if kind == "composition" else 1200)
                    if key == "narration"
                    else 300
                )
                (text if kind == "composition" else legacy_text)(
                    scene[key], f"{where} {key}", maximum
                )
                if key != "narration":
                    try:
                        composition.check_glyphs(scene[key], f"{where} {key}")
                    except ValueError as error:
                        raise SpecError(str(error)) from error
        if kind in ("title", "outro") and not scene.get("text", "").strip():
            raise SpecError(f"{where}: add some text.")
        if "transition" in scene:
            transition = scene["transition"]
            if kind == "composition":
                object_fields(transition, ("effect", "duration"), "Scene transition")
                if scene.get("motion_version") != 1 or transition.get("effect") not in (
                    "crossfade",
                    "slide-left",
                ):
                    raise SpecError("Choose a supported v1 scene transition.")
                number(transition.get("duration"), "Transition duration", 0.1, 1)
                if index == len(scenes):
                    raise SpecError(
                        "The final scene cannot transition to a missing scene."
                    )
                if transition["duration"] > scenes[index].get("duration", 4):
                    raise SpecError("Transition must fit the following scene.")
            elif transition not in ("none", "fade", "slide-left", "wipe"):
                raise SpecError(f"{where}: unsupported legacy transition.")
        animations = (
            ("fade", "kenburns") if kind == "image" else ("fade", "slide-up", "zoom-in")
        )
        if scene.get("anim", "fade") not in animations:
            raise SpecError(f"{where}: unsupported animation.")
        if "padding" in scene:
            number(
                scene["padding"], f"{where} padding", 0, 3 if studio else float("inf")
            )
        if kind == "image":
            text(scene.get("src"), f"{where} image source", 4096)
            if not scene["src"].strip():
                raise SpecError(f"{where}: image source cannot be empty.")
        if "image" in scene:
            image = scene["image"]
            object_fields(
                image,
                ("prompt", "model", "placement", "opacity", "style"),
                f"{where} image",
            )
            legacy_text(image.get("prompt"), f"{where} image prompt", 600)
            for key in ("model", "style"):
                if key in image:
                    legacy_text(image[key], f"{where} image {key}", 200)
            if image.get("placement", "background") not in (
                "background",
                "left",
                "right",
            ):
                raise SpecError(f"{where}: unsupported image placement.")
            if "opacity" in image:
                number(image["opacity"], f"{where} image opacity", 0, 1)
        if kind == "bullets":
            items = scene.get("items")
            if not isinstance(items, list) or not items or (studio and len(items) > 6):
                raise SpecError(
                    f"{where}: add between 1 and 6 bullets."
                    if studio
                    else f"{where}: add at least one bullet."
                )
            for item in items:
                legacy_text(item, f"{where} bullet", 180)
                try:
                    composition.check_glyphs(item, f"{where} bullet")
                except ValueError as error:
                    raise SpecError(str(error)) from error
                if not item.strip():
                    raise SpecError(f"{where}: bullets cannot be empty.")
            number(
                scene.get("stagger", 0.4),
                f"{where} stagger",
                0,
                2 if studio else float("inf"),
            )
            if "narration_per_bullet" in scene:
                narrations = scene["narration_per_bullet"]
                if not isinstance(narrations, list) or len(narrations) != len(items):
                    raise SpecError(
                        f"{where}: per-bullet narration must match the bullets."
                    )
                for item in narrations:
                    legacy_text(item, f"{where} narration", 1200)
        if kind == "chart":
            labels, values = scene.get("labels"), scene.get("values")
            if (
                not isinstance(labels, list)
                or not isinstance(values, list)
                or not labels
                or len(labels) != len(values)
                or (studio and len(labels) > 8)
            ):
                raise SpecError(
                    f"{where}: supply matching chart labels and values (1–8 in Studio)."
                )
            for label in labels:
                legacy_text(label, f"{where} label", 40)
                try:
                    composition.check_glyphs(label, f"{where} label")
                except ValueError as error:
                    raise SpecError(str(error)) from error
            for item in values:
                number(
                    item,
                    f"{where} chart value",
                    -1000000 if studio else -float("inf"),
                    1000000 if studio else float("inf"),
                )
            scene.setdefault("chart_type", "bar")
            if scene["chart_type"] not in ("bar", "line", "pie"):
                raise SpecError(f"{where}: choose bar, line or pie.")
            if scene.get("pptx_chart", "native") not in ("native", "image"):
                raise SpecError(f"{where}: pptx_chart must be native or image.")
            if scene["chart_type"] == "pie" and (
                any(v < 0 for v in values) or sum(values) <= 0
            ):
                raise SpecError(
                    f"{where}: pie values must be non-negative with a positive total."
                )
        duration += scene.get("duration", 4)
    if studio and duration > 60:
        raise SpecError("Timeline: keep the total duration at 60 seconds or less.")
    if __package__:
        from .canvas_assets import image_bytes
    else:
        from canvas_assets import image_bytes
    total_assets = sum(
        len(image_bytes(item["src"]))
        for scene in spec["timeline"]
        for item in scene.get("elements", [])
        if item.get("type") == "image"
    )
    if total_assets > 2 * 1024 * 1024:
        raise SpecError(
            "Project image assets exceed 2 MiB. Use smaller or fewer images."
        )
    return spec
