dark = {
    "bg": "#0d1117",
    "fg": "#f0f6fc",
    "accent": "#58a6ff",
    "font_size": 64,
    "title_font_size": 96,
}

light = {
    "bg": "#ffffff",
    "fg": "#111827",
    "accent": "#0969da",
    "font_size": 64,
    "title_font_size": 96,
}


# Semantic colours shared by scenes, charts, panels and generated branding.
# Dark schemes use pale accents; white uses dark accents on a light canvas.
COLOR_SCHEMES = {
    "red": {"bg": "#200F14", "surface": "#341820", "fg": "#FFF1F2",
            "accent": "#FDA4AF", "secondary": "#FECDD3",
            "chart_colors": ["#FDA4AF", "#FECDD3", "#FB7185"]},
    "orange": {"bg": "#21140D", "surface": "#352215", "fg": "#FFF7ED",
               "accent": "#FDBA74", "secondary": "#FED7AA",
               "chart_colors": ["#FDBA74", "#FED7AA", "#FB923C"]},
    "yellow": {"bg": "#1C190C", "surface": "#302A13", "fg": "#FEFCE8",
               "accent": "#FDE047", "secondary": "#FEF08A",
               "chart_colors": ["#FDE047", "#FEF08A", "#FACC15"]},
    "green": {"bg": "#0D1D17", "surface": "#163127", "fg": "#ECFDF5",
              "accent": "#6EE7B7", "secondary": "#A7F3D0",
              "chart_colors": ["#6EE7B7", "#A7F3D0", "#34D399"]},
    "blue": {"bg": "#101A2B", "surface": "#192C46", "fg": "#EFF6FF",
             "accent": "#93C5FD", "secondary": "#BFDBFE",
             "chart_colors": ["#93C5FD", "#BFDBFE", "#60A5FA"]},
    "purple": {"bg": "#1A1229", "surface": "#2C1E43", "fg": "#FAF5FF",
               "accent": "#D8B4FE", "secondary": "#E9D5FF",
               "chart_colors": ["#D8B4FE", "#E9D5FF", "#C084FC"]},
    "pink": {"bg": "#241020", "surface": "#391A33", "fg": "#FDF2F8",
             "accent": "#F9A8D4", "secondary": "#FBCFE8",
             "chart_colors": ["#F9A8D4", "#FBCFE8", "#F472B6"]},
    "white": {"bg": "#FFFFFF", "surface": "#F1F5F9", "fg": "#1E293B",
              "accent": "#334155", "secondary": "#475569", "chart_text": "#FFFFFF",
              "chart_colors": ["#334155", "#475569", "#1E293B"]},
    "grey": {"bg": "#18181B", "surface": "#27272A", "fg": "#FAFAFA",
             "accent": "#D4D4D8", "secondary": "#E4E4E7",
             "chart_colors": ["#D4D4D8", "#E4E4E7", "#A1A1AA"]},
}


def resolve_theme(config):
    """Apply one whole-video colour choice, then explicit token overrides."""
    import copy
    preset = config.get("preset", "dark")
    if preset not in ("dark", "light"):
        raise ValueError("theme.preset must be dark or light")
    theme = dict(dark if preset == "dark" else light)
    if "color_scheme" in config:
        scheme = config["color_scheme"]
        if not isinstance(scheme, str) or scheme not in COLOR_SCHEMES:
            raise ValueError(f"theme.color_scheme must be one of {tuple(COLOR_SCHEMES)}")
        theme.update(copy.deepcopy(COLOR_SCHEMES[scheme]))
        theme.setdefault("chart_text", "#111827")
    theme.update({k: v for k, v in config.items() if k != "preset"})
    return theme
