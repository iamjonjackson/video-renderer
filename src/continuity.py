"""Compile explicit shared IDs into incoming pose continuity, without content morphing."""

import copy


def compile_continuity(spec):
    candidate = copy.deepcopy(spec)
    for previous, scene in zip(
        candidate["timeline"], candidate["timeline"][1:], strict=False
    ):
        if previous["type"] != "composition" or scene["type"] != "composition":
            continue
        duration = previous.get("transition", {}).get("duration")
        if not duration:
            continue
        old = {item["id"]: item for item in previous["elements"]}
        for item in scene["elements"]:
            origin = old.get(item["id"])
            if (
                not origin
                or item["type"] != origin["type"]
                or item.get("keyframes")
                or item.get("group")
            ):
                continue
            content = {
                "text": ("text", "font_family"),
                "image": ("src", "fit"),
                "icon": ("icon",),
                "shape": ("shape",),
                "chart": ("chart_type", "labels", "values"),
                "path": ("points",),
            }[item["type"]]
            if (
                any(item.get(key) != origin.get(key) for key in content)
                or item["w"] != origin["w"]
                or item["h"] != origin["h"]
            ):
                continue
            # Equal-size, same-content objects can move continuously without inventing a morph.
            start = {
                "time": 0,
                "x": origin["x"] - item["x"],
                "y": origin["y"] - item["y"],
                "scale": 1,
                "opacity": 1,
            }
            end = {"time": duration, "x": 0, "y": 0, "scale": 1, "opacity": 1}
            item["keyframes"] = [start, end]
            item.pop("animation", None)
            scene["motion_version"] = 1
    return candidate
