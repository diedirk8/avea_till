LOGO_SIZE_SELECTION = [
    ("small", "Small"),
    ("medium", "Medium"),
    ("large", "Large"),
    ("extra_large", "Extra large"),
    ("maximum", "Maximum"),
]

EMAIL_LOGO_PRESETS = {
    "small": (56, 200),
    "medium": (80, 280),
    "large": (112, 360),
    "extra_large": (144, 440),
    "maximum": (180, 520),
}

PRINT_LOGO_PRESETS = {
    "small": (48, 140),
    "medium": (64, 180),
    "large": (80, 220),
    "extra_large": (96, 260),
    "maximum": (120, 300),
}

_LOGO_BASE_STYLE = (
    "display: inline-block; width: auto; height: auto; object-fit: contain;"
)


def avea_build_logo_style(presets, size="medium", max_height=0, max_width=0):
    """Return inline CSS for a receipt logo image."""
    if max_height and max_height > 0:
        height = int(max_height)
        width = int(max_width) if max_width and max_width > 0 else 0
    else:
        size = size if size in presets else "medium"
        height, width = presets[size]
    style = f"{_LOGO_BASE_STYLE} max-height: {height}px;"
    if width:
        style += f" max-width: {width}px;"
    else:
        style += " max-width: 100%;"
    return style
