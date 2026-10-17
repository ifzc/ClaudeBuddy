"""Render the Claude Code inspired pixel crab at native Windows icon sizes."""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "src" / "desktop_timezone" / "assets"
ORANGE = "#D97757"
EYES = "#2B2420"
RECTANGLES = [
    (3, 4, 10, 6, ORANGE),
    (2, 5, 12, 4, ORANGE),
    (1, 6, 2, 2, ORANGE),
    (13, 6, 2, 2, ORANGE),
    (4, 10, 8, 1, ORANGE),
    (3, 10, 2, 3, ORANGE),
    (6, 10, 1, 2, ORANGE),
    (9, 10, 1, 2, ORANGE),
    (11, 10, 2, 3, ORANGE),
    (5, 6, 1, 2, EYES),
    (10, 6, 1, 2, EYES),
]


def main():
    ASSETS.mkdir(exist_ok=True)
    sprite = Image.new("RGBA", (16, 16))
    draw = ImageDraw.Draw(sprite)
    for x, y, width, height, color in RECTANGLES:
        draw.rectangle((x, y, x + width - 1, y + height - 1), fill=color)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [sprite.resize((size, size), Image.Resampling.NEAREST) for size in sizes]
    frames[-1].save(ASSETS / "claudebuddy.png")
    frames[-1].save(
        ASSETS / "claudebuddy.ico",
        format="ICO",
        sizes=[(size, size) for size in sizes],
        append_images=frames[:-1],
    )
    rectangles = "\n".join(
        f'  <rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{color}"/>'
        for x, y, width, height, color in RECTANGLES
    )
    (ASSETS / "claudebuddy.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
        'shape-rendering="crispEdges">\n' + rectangles + "\n</svg>\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
