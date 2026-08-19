"""Zeichnet das Symbol fuer Tray und Exe -- ein Punkt, der den Zustand faerbt."""

from __future__ import annotations

from PIL import Image, ImageDraw

DARK = "#1b1b20"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(color: str, paused: bool = False, size: int = 64) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    unit = size / 64  # die Maszahlen unten sind fuer 64 px gedacht

    def box(*values: float) -> list[float]:
        return [value * unit for value in values]

    draw.ellipse(box(4, 4, 60, 60), fill=color)
    if paused:
        draw.rectangle(box(23, 20, 29, 44), fill=DARK)
        draw.rectangle(box(35, 20, 41, 44), fill=DARK)
    else:
        draw.ellipse(box(22, 22, 42, 42), fill=DARK)
    return image
