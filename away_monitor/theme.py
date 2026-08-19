"""Gestaltungsgrundlage: Farben, Abstaende, Schriften, Fensterdekoration.

Alles an einer Stelle, damit Overlay, Live-Ansicht und Notizzettel nicht
auseinanderdriften. Tkinter kennt keine Themes in diesem Sinn -- die Werte hier
sind die einzige Quelle.
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger(__name__)

# --------------------------------------------------------------------- Farben
# Dunkle Flaechen in drei Stufen: je weiter vorn ein Element liegt, desto heller.
BG = "#0f1115"
SURFACE = "#171a21"
ELEVATED = "#1e222b"
HOVER = "#272c37"
BORDER = "#2b3140"

TEXT = "#e8eaed"
TEXT_MUTED = "#9aa0ac"
TEXT_FAINT = "#6b7280"

ACCENT = "#4c8dff"
SUCCESS = "#34d399"
WARNING = "#fbbf24"
DANGER = "#f87171"
NEUTRAL = "#8b93a3"

# Zustandsfarben -- dieselben in Tray, Overlay, Live-Ansicht und Notizzettel.
STATE_COLORS = {
    "aktiv": SUCCESS,
    "beobachte": ACCENT,
    "Warnung": WARNING,
    "gesperrt": NEUTRAL,
    "pausiert": NEUTRAL,
}

# ------------------------------------------------------------------ Abstaende
# Vielfache von 4, damit nichts "fast ausgerichtet" wirkt.
SPACE_XS = 4
SPACE_S = 8
SPACE_M = 12
SPACE_L = 16
SPACE_XL = 24

RADIUS_CARD = 12
RADIUS_CONTROL = 8

# ------------------------------------------------------------------- Schriften
_PREFERRED = ("Segoe UI Variable Display", "Segoe UI", "Tahoma")
_PREFERRED_MONO = ("Cascadia Mono", "Consolas", "Courier New")

_family: str | None = None
_family_mono: str | None = None


def _pick(candidates: tuple[str, ...], fallback: str) -> str:
    try:
        from tkinter import font as tkfont

        available = {name.lower() for name in tkfont.families()}
    except Exception:  # noqa: BLE001 -- ohne Tk-Root nicht abfragbar
        log.debug("Schriftliste nicht abfragbar", exc_info=True)
        return fallback
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


def family() -> str:
    """Beste verfuegbare UI-Schrift. Erst nach dem Tk-Root aufrufbar."""
    global _family
    if _family is None:
        _family = _pick(_PREFERRED, "Segoe UI")
    return _family


def mono() -> str:
    global _family_mono
    if _family_mono is None:
        _family_mono = _pick(_PREFERRED_MONO, "Consolas")
    return _family_mono


def font(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return (family(), size, weight)


def font_mono(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return (mono(), size, weight)


# ------------------------------------------------------- Windows-Fensterrahmen
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_DWMWCP_ROUNDSMALL = 3


def _dwm_set(hwnd: int, attribute: int, value: int) -> bool:
    try:
        dwm = ctypes.WinDLL("dwmapi")
    except OSError:
        return False
    data = ctypes.c_int(value)
    result = dwm.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), ctypes.c_uint(attribute),
        ctypes.byref(data), ctypes.sizeof(data),
    )
    return result == 0


def _hwnd_of(window) -> int | None:
    """Fenstergriff des *aeusseren* Fensters -- winfo_id() liefert das innere."""
    try:
        return int(window.frame(), 16)
    except (ValueError, AttributeError):
        log.debug("Fenstergriff nicht ermittelbar", exc_info=True)
        return None


def apply_dark_titlebar(window) -> None:
    """Dunkle Titelleiste. Ohne das klebt ein weisser Balken ueber dem Fenster.
    Braucht Windows 10 ab Build 18985; sonst passiert schlicht nichts."""
    hwnd = _hwnd_of(window)
    if hwnd is not None and not _dwm_set(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1):
        log.debug("Dunkle Titelleiste nicht unterstuetzt")


def apply_rounded_corners(window, small: bool = False) -> None:
    """Abgerundete Ecken wie bei Windows-11-Fenstern. Aeltere Versionen
    ignorieren das Attribut."""
    hwnd = _hwnd_of(window)
    if hwnd is None:
        return
    preference = _DWMWCP_ROUNDSMALL if small else _DWMWCP_ROUND
    _dwm_set(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE, preference)


def mix(color_a: str, color_b: str, ratio: float) -> str:
    """Farbe zwischen zwei Hex-Werten -- fuer Hover- und Verlaufszustaende."""
    ratio = min(1.0, max(0.0, ratio))
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    blended = tuple(round(x + (y - x) * ratio) for x, y in zip(a, b))
    return "#{:02x}{:02x}{:02x}".format(*blended)
