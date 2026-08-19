"""Bedienelemente, die Tkinter nicht mitbringt.

Tk zeichnet Rundungen ohne Kantenglaettung und seine Schalter und Regler sehen
aus wie 1998. Hier entstehen sie stattdessen als PIL-Bilder: vierfach
ueberabgetastet gerendert und heruntergerechnet, dann als Bild in ein Label
oder Canvas gelegt.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageTk

from . import theme

_SS = 4  # Ueberabtastung


def _resample() -> int:
    return getattr(Image, "Resampling", Image).LANCZOS


def rounded_image(width: int, height: int, radius: int, fill: str, bg: str,
                  outline: str | None = None, outline_width: int = 1) -> Image.Image:
    """Abgerundetes Rechteck, fertig auf die Hintergrundfarbe gerechnet.
    Kein Alphakanal -- so gibt es keine Kompositionsueberraschungen in Tk."""
    big = Image.new("RGB", (width * _SS, height * _SS), bg)
    draw = ImageDraw.Draw(big)
    draw.rounded_rectangle(
        (0, 0, width * _SS - 1, height * _SS - 1),
        radius=radius * _SS,
        fill=fill,
        outline=outline,
        width=outline_width * _SS if outline else 0,
    )
    return big.resize((width, height), _resample())


def ring_image(size: int, fraction: float, color: str, track: str, bg: str,
               thickness: int = 8) -> Image.Image:
    """Fortschrittsring von oben im Uhrzeigersinn. fraction 1.0 = voller Ring."""
    big = Image.new("RGB", (size * _SS, size * _SS), bg)
    draw = ImageDraw.Draw(big)
    inset = thickness * _SS // 2 + _SS
    box = (inset, inset, size * _SS - inset, size * _SS - inset)
    draw.arc(box, 0, 360, fill=track, width=thickness * _SS)
    fraction = min(1.0, max(0.0, fraction))
    if fraction > 0:
        # -90 Grad: oben beginnen statt rechts.
        draw.arc(box, -90, -90 + 360 * fraction, fill=color, width=thickness * _SS)
    return big.resize((size, size), _resample())


def dot_image(diameter: int, color: str, bg: str) -> Image.Image:
    big = Image.new("RGB", (diameter * _SS, diameter * _SS), bg)
    ImageDraw.Draw(big).ellipse((0, 0, diameter * _SS - 1, diameter * _SS - 1), fill=color)
    return big.resize((diameter, diameter), _resample())


class RoundedButton(tk.Label):
    """Label mit gerendertem Hintergrund -- Text liegt mittig darueber."""

    def __init__(self, parent, text: str, command: Callable[[], None], *,
                 bg: str, fill: str = theme.ELEVATED, hover: str = theme.HOVER,
                 fg: str = theme.TEXT, width: int = 132, height: int = 34,
                 radius: int = theme.RADIUS_CONTROL, font: tuple | None = None,
                 outline: str | None = theme.BORDER) -> None:
        self._command = command
        self._images = {
            "normal": ImageTk.PhotoImage(
                rounded_image(width, height, radius, fill, bg, outline)),
            "hover": ImageTk.PhotoImage(
                rounded_image(width, height, radius, hover, bg, outline)),
            "press": ImageTk.PhotoImage(
                rounded_image(width, height, radius,
                              theme.mix(hover, "#000000", 0.25), bg, outline)),
        }
        super().__init__(
            parent, text=text, image=self._images["normal"], compound="center",
            bg=bg, fg=fg, font=font or theme.font(10), bd=0, highlightthickness=0,
            cursor="hand2",
        )
        self.bind("<Enter>", lambda _e: self._set("hover"))
        self.bind("<Leave>", lambda _e: self._set("normal"))
        self.bind("<ButtonPress-1>", lambda _e: self._set("press"))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, state: str) -> None:
        self.configure(image=self._images[state])

    def _release(self, event) -> None:
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._set("hover" if inside else "normal")
        if inside:
            self._command()


class Switch(tk.Label):
    """Schiebeschalter statt tk.Checkbutton."""

    _WIDTH, _HEIGHT = 38, 22

    def __init__(self, parent, variable: tk.BooleanVar,
                 command: Callable[[], None] | None = None, *,
                 bg: str = theme.SURFACE, accent: str = theme.ACCENT) -> None:
        self._variable = variable
        self._command = command
        self._images = {
            True: ImageTk.PhotoImage(self._render(True, bg, accent)),
            False: ImageTk.PhotoImage(self._render(False, bg, accent)),
        }
        super().__init__(parent, image=self._images[bool(variable.get())], bg=bg,
                         bd=0, highlightthickness=0, cursor="hand2")
        self.bind("<Button-1>", lambda _e: self.toggle())
        variable.trace_add("write", lambda *_: self._refresh())

    def _render(self, on: bool, bg: str, accent: str) -> Image.Image:
        w, h = self._WIDTH * _SS, self._HEIGHT * _SS
        big = Image.new("RGB", (w, h), bg)
        draw = ImageDraw.Draw(big)
        draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2,
                               fill=accent if on else theme.ELEVATED,
                               outline=None if on else theme.BORDER,
                               width=0 if on else _SS)
        pad = 3 * _SS
        knob = h - 2 * pad
        left = w - pad - knob if on else pad
        draw.ellipse((left, pad, left + knob, pad + knob),
                     fill="#ffffff" if on else theme.TEXT_MUTED)
        return big.resize((self._WIDTH, self._HEIGHT), _resample())

    def toggle(self) -> None:
        self._variable.set(not self._variable.get())
        if self._command is not None:
            self._command()

    def _refresh(self) -> None:
        try:
            self.configure(image=self._images[bool(self._variable.get())])
        except tk.TclError:
            pass  # Fenster ist bereits zu


class Slider(tk.Canvas):
    """Waagerechter Regler mit gerendertem Verlauf und Griff."""

    _HEIGHT = 26

    def __init__(self, parent, variable: tk.DoubleVar, *, minimum: float, maximum: float,
                 step: float, width: int = 190, bg: str = theme.SURFACE,
                 accent: str = theme.ACCENT,
                 command: Callable[[float], None] | None = None) -> None:
        super().__init__(parent, width=width, height=self._HEIGHT, bg=bg,
                         bd=0, highlightthickness=0, cursor="hand2")
        self._variable = variable
        self._min, self._max, self._step = minimum, maximum, step
        self._width, self._bg, self._accent = width, bg, accent
        self._command = command
        self._photo: ImageTk.PhotoImage | None = None
        self._item = self.create_image(0, 0, anchor="nw")
        self._redraw()
        for sequence in ("<Button-1>", "<B1-Motion>"):
            self.bind(sequence, self._on_drag)
        variable.trace_add("write", lambda *_: self._redraw())

    def _fraction(self) -> float:
        span = self._max - self._min
        return 0.0 if span <= 0 else (self._variable.get() - self._min) / span

    def _redraw(self) -> None:
        knob = 16
        track_h = 6
        usable = self._width - knob
        big = Image.new("RGB", (self._width * _SS, self._HEIGHT * _SS), self._bg)
        draw = ImageDraw.Draw(big)
        top = (self._HEIGHT - track_h) // 2 * _SS
        draw.rounded_rectangle(
            (knob // 2 * _SS, top, (self._width - knob // 2) * _SS, top + track_h * _SS),
            radius=track_h * _SS // 2, fill=theme.ELEVATED)
        centre = (knob // 2 + usable * self._fraction()) * _SS
        if centre > knob // 2 * _SS:
            draw.rounded_rectangle(
                (knob // 2 * _SS, top, centre, top + track_h * _SS),
                radius=track_h * _SS // 2, fill=self._accent)
        radius = knob // 2 * _SS
        middle = self._HEIGHT // 2 * _SS
        draw.ellipse((centre - radius, middle - radius, centre + radius, middle + radius),
                     fill="#ffffff")
        self._photo = ImageTk.PhotoImage(big.resize((self._width, self._HEIGHT), _resample()))
        self.itemconfigure(self._item, image=self._photo)

    def _on_drag(self, event) -> None:
        knob = 16
        usable = max(1, self._width - knob)
        fraction = min(1.0, max(0.0, (event.x - knob / 2) / usable))
        value = self._min + fraction * (self._max - self._min)
        value = round(value / self._step) * self._step
        value = min(self._max, max(self._min, value))
        if abs(value - self._variable.get()) > 1e-9:
            self._variable.set(round(value, 4))
            if self._command is not None:
                self._command(self._variable.get())


def card(parent, *, bg: str = theme.SURFACE, border: str = theme.BORDER) -> tk.Frame:
    """Flaeche mit feiner Umrandung -- ohne Rundung, dafuer ohne Treppenkanten."""
    return tk.Frame(parent, bg=bg, highlightbackground=border,
                    highlightcolor=border, highlightthickness=1, bd=0)


def polar(centre: float, radius: float, degrees: float) -> tuple[float, float]:
    radians = math.radians(degrees)
    return centre + radius * math.cos(radians), centre + radius * math.sin(radians)
