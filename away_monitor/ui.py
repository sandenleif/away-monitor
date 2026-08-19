"""Alle Fenster. Tk laeuft im Hauptthread, der Monitor spricht ueber eine Queue
bzw. ein Schnappschuss-Fach mit ihm -- Tk-Aufrufe aus fremden Threads sind nicht
sicher und kippen die App frueher oder spaeter.

Zwei Fenster haengen an einem gemeinsamen Tk-Root:
  * das Warn-Overlay mit dem Countdown vor dem Sperren,
  * die Live-Ansicht zum Einstellen von Schwelle und Kameraposition.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

log = logging.getLogger(__name__)

_BG = "#17171c"
_PANEL = "#1f1f26"
_FG = "#f2f2f5"
_MUTED = "#9a9aa6"
_ACCENT = "#ff9f43"
_GREEN = "#3ecf8e"
_BLUE = "#4aa3ff"

_STATE_COLORS = {
    "aktiv": _GREEN,
    "beobachte": _BLUE,
    "Warnung": _ACCENT,
    "gesperrt": _MUTED,
    "pausiert": _MUTED,
}

_OVERLAY_W, _OVERLAY_H = 460, 210
_PUMP_MS = 100


@dataclass(frozen=True)
class UiCallbacks:
    on_present: Callable[[], None]
    on_threshold: Callable[[float], None]
    on_threshold_save: Callable[[float], bool]
    on_pause_toggle: Callable[[bool], None]
    on_preview_closed: Callable[[], None]


class UiHost:
    """Besitzt den Tk-Root und verteilt Kommandos aus anderen Threads."""

    def __init__(self, callbacks: UiCallbacks, preview_max_width: int = 480) -> None:
        self._callbacks = callbacks
        self._preview_max_width = preview_max_width

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._lock = threading.Lock()
        self._want_warning = False
        self._snapshot = None  # nur das juengste zaehlt, alte Bilder sind wertlos

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("away-monitor")
        self._overlay: _Overlay | None = None
        self._preview: _PreviewWindow | None = None
        self._root.after(_PUMP_MS, self._pump)

    # ------------------------------------ thread-sichere API (Monitor/Tray)
    def show_warning(self, remaining: float) -> None:
        with self._lock:
            already = self._want_warning
            self._want_warning = True
        self._queue.put(("warn_update" if already else "warn_show", remaining))

    def update_warning(self, remaining: float) -> None:
        with self._lock:
            if not self._want_warning:
                return
        self._queue.put(("warn_update", remaining))

    def hide_warning(self) -> None:
        with self._lock:
            if not self._want_warning:
                return
            self._want_warning = False
        self._queue.put(("warn_hide", None))

    def push_snapshot(self, snapshot) -> None:
        """Vom Monitor-Thread, bis zu 10x/s. Ueberschreibt bewusst: laufen wir
        der Anzeige davon, ist das juengste Bild das einzig interessante."""
        with self._lock:
            self._snapshot = snapshot

    def open_preview(self) -> None:
        self._queue.put(("preview_open", None))

    def close_preview(self) -> None:
        self._queue.put(("preview_close", None))

    def offer_update(self, release, installed: str,
                     on_install: Callable[[], None]) -> None:
        self._queue.put(("update_offer", (release, installed, on_install)))

    def show_message(self, title: str, text: str) -> None:
        self._queue.put(("message", (title, text)))

    def quit(self) -> None:
        self._queue.put(("quit", None))

    def run(self) -> None:
        """Blockiert bis quit() -- muss im Hauptthread laufen."""
        self._root.mainloop()

    # -------------------------------------------------------- nur Hauptthread
    def _pump(self) -> None:
        try:
            while True:
                command, value = self._queue.get_nowait()
                if command == "warn_show":
                    self._ensure_overlay().show(float(value))
                elif command == "warn_update":
                    if self._overlay is not None:
                        self._overlay.set_countdown(float(value))
                elif command == "warn_hide":
                    self._destroy_overlay()
                elif command == "preview_open":
                    self._open_preview()
                elif command == "preview_close":
                    self._destroy_preview(notify=False)
                elif command == "update_offer":
                    self._offer_update(*value)
                elif command == "message":
                    title, text = value
                    messagebox.showinfo(title, text)
                elif command == "quit":
                    self._destroy_overlay()
                    self._destroy_preview(notify=False)
                    self._root.quit()
                    return
        except queue.Empty:
            pass
        except Exception:
            log.exception("Fehler im UI-Pump")

        if self._preview is not None:
            with self._lock:
                snapshot = self._snapshot
            if snapshot is not None:
                try:
                    self._preview.render(snapshot)
                except Exception:
                    log.exception("Live-Ansicht konnte nicht gezeichnet werden")

        self._root.after(_PUMP_MS, self._pump)

    def _offer_update(self, release, installed: str,
                      on_install: Callable[[], None]) -> None:
        notes = release.notes.strip()
        if len(notes) > 600:
            notes = notes[:600].rstrip() + " ..."
        text = "\n".join([
            f"Version {release.label} ist verfügbar.",
            f"Installiert ist {installed}.",
            "",
            notes or "Keine Anmerkungen veröffentlicht.",
            "",
            "Jetzt herunterladen, prüfen und neu starten?",
        ])
        if messagebox.askyesno("away-monitor · Update", text):
            on_install()

    # --------------------------------------------------------------- Overlay
    def _ensure_overlay(self) -> _Overlay:
        if self._overlay is None:
            self._overlay = _Overlay(self._root, on_dismiss=self._dismiss_warning)
        return self._overlay

    def _dismiss_warning(self) -> None:
        self._destroy_overlay()
        with self._lock:
            self._want_warning = False
        self._callbacks.on_present()

    def _destroy_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.destroy()
            self._overlay = None

    # ---------------------------------------------------------------- Preview
    def _open_preview(self) -> None:
        if self._preview is not None:
            self._preview.focus()
            return
        self._preview = _PreviewWindow(
            self._root,
            callbacks=self._callbacks,
            max_width=self._preview_max_width,
            on_close=lambda: self._destroy_preview(notify=True),
        )

    def _destroy_preview(self, notify: bool) -> None:
        if self._preview is None:
            return
        self._preview.destroy()
        self._preview = None
        with self._lock:
            self._snapshot = None
        if notify:
            self._callbacks.on_preview_closed()


class _Overlay:
    """Randloses Warnfenster mit Countdown."""

    def __init__(self, root: tk.Tk, on_dismiss: Callable[[], None]) -> None:
        self._on_dismiss = on_dismiss
        window = tk.Toplevel(root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=_ACCENT)

        x = (window.winfo_screenwidth() - _OVERLAY_W) // 2
        y = int(window.winfo_screenheight() * 0.20)
        window.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{x}+{y}")

        inner = tk.Frame(window, bg=_BG)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        tk.Label(inner, text="Niemand vor der Kamera", bg=_BG, fg=_FG,
                 font=("Segoe UI", 16, "bold")).pack(pady=(26, 6))

        self._countdown = tk.Label(inner, text="", bg=_BG, fg=_ACCENT,
                                   font=("Segoe UI", 30, "bold"))
        self._countdown.pack()

        tk.Button(inner, text="Ich bin da", command=self._dismiss,
                  bg="#2c2c34", fg=_FG, activebackground="#3a3a44", activeforeground=_FG,
                  relief="flat", font=("Segoe UI", 11), padx=22, pady=7,
                  cursor="hand2").pack(pady=(14, 4))

        tk.Label(inner, text="oder einfach Maus bewegen  ·  Esc", bg=_BG, fg=_MUTED,
                 font=("Segoe UI", 9)).pack()

        window.bind("<Escape>", lambda _event: self._dismiss())
        try:
            # Fokus holen, damit Esc greift. Vertretbar: der Nutzer gilt hier seit
            # ueber einer Minute als untaetig, es wird also nichts unterbrochen.
            window.focus_force()
        except tk.TclError:
            log.debug("Fokus fuer das Overlay nicht zu bekommen", exc_info=True)

        self._window = window

    def show(self, remaining: float) -> None:
        self.set_countdown(remaining)

    def set_countdown(self, remaining: float) -> None:
        try:
            self._countdown.configure(text=f"Sperre in {max(0, int(remaining + 0.5))} s")
        except tk.TclError:
            log.debug("Countdown-Label ist weg", exc_info=True)

    def _dismiss(self) -> None:
        self._on_dismiss()

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except tk.TclError:
            log.debug("Overlay war bereits zerstoert", exc_info=True)


class _PreviewWindow:
    """Live-Ansicht: zeigt, was der Detektor sieht, und laesst die Schwelle regeln."""

    def __init__(self, root: tk.Tk, callbacks: UiCallbacks, max_width: int,
                 on_close: Callable[[], None]) -> None:
        self._callbacks = callbacks
        self._max_width = max_width
        self._photo: ImageTk.PhotoImage | None = None  # Referenz halten, sonst GC
        self._font = _load_font(13)
        self._synced_threshold = False
        self._save_hint_after: str | None = None

        window = tk.Toplevel(root)
        window.title("away-monitor · Live")
        window.configure(bg=_BG)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", on_close)
        self._window = window

        self._image_label = tk.Label(window, bg="#000000", bd=0)
        self._image_label.pack(padx=12, pady=(12, 8))

        self._state_label = tk.Label(window, text="—", bg=_BG, fg=_FG,
                                     font=("Segoe UI", 14, "bold"), anchor="w")
        self._state_label.pack(fill="x", padx=14)

        self._note_label = tk.Label(window, text="", bg=_BG, fg=_MUTED,
                                    font=("Segoe UI", 9), anchor="w")
        self._note_label.pack(fill="x", padx=14, pady=(0, 8))

        stats = tk.Frame(window, bg=_PANEL)
        stats.pack(fill="x", padx=12, pady=(0, 10))
        self._stats: dict[str, tk.Label] = {}
        for row, (key, caption) in enumerate([
            ("idle", "Leerlauf"),
            ("seen", "Gesicht zuletzt"),
            ("countdown", "Sperre in"),
            ("detect", "Erkennung"),
            ("camera", "Kamera"),
        ]):
            tk.Label(stats, text=caption, bg=_PANEL, fg=_MUTED, font=("Segoe UI", 9),
                     anchor="w").grid(row=row, column=0, sticky="w", padx=(10, 16), pady=1)
            value = tk.Label(stats, text="—", bg=_PANEL, fg=_FG,
                             font=("Consolas", 10), anchor="w")
            value.grid(row=row, column=1, sticky="w", pady=1)
            self._stats[key] = value
        stats.grid_columnconfigure(1, weight=1)

        control = tk.Frame(window, bg=_BG)
        control.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(control, text="Schwelle", bg=_BG, fg=_MUTED,
                 font=("Segoe UI", 9)).pack(side="left")
        self._threshold = tk.DoubleVar(value=0.6)
        tk.Scale(control, from_=0.05, to=0.95, resolution=0.05, orient="horizontal",
                 variable=self._threshold, command=self._on_threshold, length=210,
                 bg=_BG, fg=_FG, troughcolor="#3a3a44", highlightthickness=0,
                 activebackground=_BLUE, bd=0).pack(side="left", padx=8)
        self._save_button = tk.Button(control, text="Speichern", command=self._on_save,
                                      bg="#2c2c34", fg=_FG, activebackground="#3a3a44",
                                      activeforeground=_FG, relief="flat",
                                      font=("Segoe UI", 9), padx=10, cursor="hand2")
        self._save_button.pack(side="left")

        toggles = tk.Frame(window, bg=_BG)
        toggles.pack(fill="x", padx=12, pady=(0, 12))
        self._show_image = tk.BooleanVar(value=True)
        self._paused = tk.BooleanVar(value=False)
        tk.Checkbutton(toggles, text="Kamerabild anzeigen", variable=self._show_image,
                       bg=_BG, fg=_MUTED, selectcolor=_PANEL, activebackground=_BG,
                       activeforeground=_FG, font=("Segoe UI", 9),
                       highlightthickness=0, bd=0).pack(side="left")
        tk.Checkbutton(toggles, text="Überwachung pausiert", variable=self._paused,
                       command=self._on_pause, bg=_BG, fg=_MUTED, selectcolor=_PANEL,
                       activebackground=_BG, activeforeground=_FG, font=("Segoe UI", 9),
                       highlightthickness=0, bd=0).pack(side="left", padx=(14, 0))

    # ------------------------------------------------------------- Zeichnen
    def render(self, snapshot) -> None:
        self._render_image(snapshot)

        color = _STATE_COLORS.get(snapshot.state.value, _FG)
        self._state_label.configure(text=snapshot.state.value, fg=color)
        self._note_label.configure(text=snapshot.note or "")

        self._stats["idle"].configure(text=f"{snapshot.idle_seconds:6.1f} s")
        self._stats["seen"].configure(
            text="—" if snapshot.seen_ago is None else f"{snapshot.seen_ago:6.1f} s"
        )
        self._stats["countdown"].configure(
            text="—" if snapshot.countdown is None else f"{snapshot.countdown:6.1f} s"
        )
        self._stats["detect"].configure(
            text=f"{snapshot.detect_ms:5.1f} ms   {len(snapshot.faces)} Gesicht(er)"
        )
        self._stats["camera"].configure(text="offen" if snapshot.camera_open else "zu")

        # Die Schwelle nur einmal uebernehmen -- danach ist der Regler die Quelle,
        # sonst zappelt er beim Ziehen gegen den Zustrom aus dem Monitor.
        if not self._synced_threshold:
            self._threshold.set(round(snapshot.score_threshold, 2))
            self._synced_threshold = True

        is_paused = snapshot.state.value == "pausiert"
        if is_paused != self._paused.get():
            self._paused.set(is_paused)

    def _render_image(self, snapshot) -> None:
        frame = snapshot.frame
        if frame is None:
            image = Image.new("RGB", (self._max_width, self._max_width * 3 // 4), "#0d0d11")
            draw = ImageDraw.Draw(image)
            draw.text((14, 14), "kein Kamerabild", fill=_MUTED, font=self._font)
            self._show(image)
            return

        height, width = frame.shape[:2]
        if self._show_image.get():
            # OpenCV liefert BGR, PIL erwartet RGB.
            rgb = np.ascontiguousarray(frame[:, :, ::-1])
            image = Image.fromarray(rgb)
        else:
            image = Image.new("RGB", (width, height), "#0d0d11")

        # Erst skalieren, dann zeichnen: so bleiben Rahmen und Text scharf.
        scale = self._max_width / width
        image = image.resize((self._max_width, max(1, int(height * scale))))

        draw = ImageDraw.Draw(image)
        for face in snapshot.faces:
            left, top = int(face.x * scale), int(face.y * scale)
            right = int((face.x + face.width) * scale)
            bottom = int((face.y + face.height) * scale)
            draw.rectangle([left, top, right, bottom], outline=_GREEN, width=3)
            label = f"{face.score:.2f}"
            draw.rectangle([left, max(0, top - 18), left + 8 * len(label) + 8, top],
                           fill=_GREEN)
            draw.text((left + 4, max(0, top - 17)), label, fill="#0d0d11", font=self._font)

        if not snapshot.faces:
            draw.text((10, 8), "kein Gesicht", fill=_ACCENT, font=self._font)

        self._show(image)

    def _show(self, image: Image.Image) -> None:
        self._photo = ImageTk.PhotoImage(image)
        self._image_label.configure(image=self._photo)

    # ------------------------------------------------------------ Bedienung
    def _on_threshold(self, _value: str) -> None:
        self._callbacks.on_threshold(self._threshold.get())

    def _on_save(self) -> None:
        ok = self._callbacks.on_threshold_save(self._threshold.get())
        self._save_button.configure(text="gespeichert" if ok else "Fehler")
        if self._save_hint_after is not None:
            self._window.after_cancel(self._save_hint_after)
        self._save_hint_after = self._window.after(1800, self._reset_save_button)

    def _reset_save_button(self) -> None:
        self._save_hint_after = None
        try:
            self._save_button.configure(text="Speichern")
        except tk.TclError:
            log.debug("Speichern-Button ist weg", exc_info=True)

    def _on_pause(self) -> None:
        self._callbacks.on_pause_toggle(self._paused.get())

    def focus(self) -> None:
        try:
            self._window.deiconify()
            self._window.lift()
        except tk.TclError:
            log.debug("Live-Ansicht liess sich nicht nach vorn holen", exc_info=True)

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except tk.TclError:
            log.debug("Live-Ansicht war bereits zerstoert", exc_info=True)


def _load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # aeltere Pillow-Versionen kennen den Parameter nicht
        return ImageFont.load_default()
