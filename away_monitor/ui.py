"""Alle Fenster. Tk laeuft im Hauptthread, der Monitor spricht ueber eine Queue
bzw. ein Schnappschuss-Fach mit ihm -- Tk-Aufrufe aus fremden Threads sind nicht
sicher und kippen die App frueher oder spaeter.

Drei Fenster haengen an einem gemeinsamen Tk-Root:
  * das Warn-Overlay mit dem Countdown vor dem Sperren,
  * die Live-Ansicht zum Einstellen von Schwelle und Kameraposition,
  * der Notizzettel, der Zustand und Countdown im Vordergrund haelt.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import messagebox

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from . import theme, widgets, winapi

log = logging.getLogger(__name__)

_PUMP_MS = 100
_OVERLAY_W, _OVERLAY_H = 360, 320
_RING = 116
_STICKY_W, _STICKY_H = 224, 62


@dataclass(frozen=True)
class UiCallbacks:
    on_present: Callable[[], None]
    on_threshold: Callable[[float], None]
    on_threshold_save: Callable[[float], bool]
    on_pause_toggle: Callable[[bool], None]
    on_preview_closed: Callable[[], None]
    on_sticky_moved: Callable[[int, int], None]


class UiHost:
    """Besitzt den Tk-Root und verteilt Kommandos aus anderen Threads."""

    def __init__(self, callbacks: UiCallbacks, preview_max_width: int = 480,
                 sticky_position: tuple[int, int] = (-1, -1),
                 sticky_opacity: float = 0.92) -> None:
        self._callbacks = callbacks
        self._preview_max_width = preview_max_width
        self._sticky_position = sticky_position
        self._sticky_opacity = sticky_opacity

        self._queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._lock = threading.Lock()
        self._want_warning = False
        self._snapshot = None  # nur das juengste zaehlt, alte Bilder sind wertlos

        self._root = tk.Tk()
        self._root.withdraw()
        self._root.title("away-monitor")
        self._root.configure(bg=theme.BG)
        self._overlay: _Overlay | None = None
        self._preview: _PreviewWindow | None = None
        self._sticky: _StickyNote | None = None
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
        """Vom Monitor-Thread. Ueberschreibt bewusst: laufen wir der Anzeige
        davon, ist das juengste Bild das einzig interessante."""
        with self._lock:
            self._snapshot = snapshot

    def open_preview(self) -> None:
        self._queue.put(("preview_open", None))

    def close_preview(self) -> None:
        self._queue.put(("preview_close", None))

    def open_sticky(self) -> None:
        self._queue.put(("sticky_open", None))

    def close_sticky(self) -> None:
        self._queue.put(("sticky_close", None))

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
                        self._overlay.set_remaining(float(value))
                elif command == "warn_hide":
                    self._destroy_overlay()
                elif command == "preview_open":
                    self._open_preview()
                elif command == "preview_close":
                    self._destroy_preview(notify=False)
                elif command == "sticky_open":
                    self._open_sticky()
                elif command == "sticky_close":
                    self._destroy_sticky()
                elif command == "update_offer":
                    self._offer_update(*value)
                elif command == "message":
                    title, text = value
                    messagebox.showinfo(title, text)
                elif command == "quit":
                    self._destroy_overlay()
                    self._destroy_preview(notify=False)
                    self._destroy_sticky()
                    self._root.quit()
                    return
        except queue.Empty:
            pass
        except Exception:
            log.exception("Fehler im UI-Pump")

        if self._preview is not None or self._sticky is not None:
            with self._lock:
                snapshot = self._snapshot
            if snapshot is not None:
                self._render(snapshot)

        self._root.after(_PUMP_MS, self._pump)

    def _render(self, snapshot) -> None:
        if self._preview is not None:
            try:
                self._preview.render(snapshot)
            except Exception:
                log.exception("Live-Ansicht konnte nicht gezeichnet werden")
        if self._sticky is not None:
            try:
                self._sticky.render(snapshot)
            except Exception:
                log.exception("Notizzettel konnte nicht gezeichnet werden")

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
        if notify:
            self._callbacks.on_preview_closed()

    # ----------------------------------------------------------------- Sticky
    def _open_sticky(self) -> None:
        if self._sticky is not None:
            return
        self._sticky = _StickyNote(
            self._root,
            position=self._sticky_position,
            opacity=self._sticky_opacity,
            on_moved=self._callbacks.on_sticky_moved,
        )

    def _destroy_sticky(self) -> None:
        if self._sticky is not None:
            self._sticky.destroy()
            self._sticky = None


class _Overlay:
    """Warnfenster: Fortschrittsring als Blickfang, ein Knopf zum Abbrechen."""

    def __init__(self, root: tk.Tk, on_dismiss: Callable[[], None]) -> None:
        self._on_dismiss = on_dismiss
        self._total = 1.0
        self._ring_photo: ImageTk.PhotoImage | None = None

        window = tk.Toplevel(root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.configure(bg=theme.WARNING)

        x = (window.winfo_screenwidth() - _OVERLAY_W) // 2
        y = int(window.winfo_screenheight() * 0.22)
        window.geometry(f"{_OVERLAY_W}x{_OVERLAY_H}+{x}+{y}")

        # Ein Pixel Rahmen in der Warnfarbe: der einzige Akzent, den ein
        # randloses Fenster ohne Zeichenarbeit bekommt.
        body = tk.Frame(window, bg=theme.SURFACE)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        self._ring = tk.Label(body, bg=theme.SURFACE, bd=0)
        self._ring.pack(pady=(theme.SPACE_XL, 0))

        self._seconds = tk.Label(body, text="", bg=theme.SURFACE, fg=theme.WARNING,
                                 font=theme.font(30, "bold"))
        self._seconds.place(x=_OVERLAY_W // 2, y=theme.SPACE_XL + _RING // 2 + 1,
                            anchor="center")

        tk.Label(body, text="Niemand vor der Kamera", bg=theme.SURFACE, fg=theme.TEXT,
                 font=theme.font(15, "bold")).pack(pady=(theme.SPACE_L, 2))
        tk.Label(body, text="Der Rechner wird gleich gesperrt", bg=theme.SURFACE,
                 fg=theme.TEXT_MUTED, font=theme.font(10)).pack()

        widgets.RoundedButton(
            body, "Ich bin da", self._dismiss, bg=theme.SURFACE,
            fill=theme.ACCENT, hover=theme.mix(theme.ACCENT, "#ffffff", 0.15),
            fg="#0b1220", width=146, height=38, outline=None,
            font=theme.font(11, "bold"),
        ).pack(pady=(theme.SPACE_L, theme.SPACE_S))

        tk.Label(body, text="oder Maus bewegen  ·  Esc", bg=theme.SURFACE,
                 fg=theme.TEXT_FAINT, font=theme.font(9)).pack()

        window.bind("<Escape>", lambda _e: self._dismiss())
        try:
            # Fokus holen, damit Esc greift. Vertretbar: hier gilt der Nutzer
            # laengst als abwesend, es wird also nichts unterbrochen.
            window.focus_force()
        except tk.TclError:
            log.debug("Fokus fuer das Overlay nicht zu bekommen", exc_info=True)

        self._window = window

    def show(self, remaining: float) -> None:
        self._total = max(0.001, remaining)
        self.set_remaining(remaining)

    def set_remaining(self, remaining: float) -> None:
        try:
            fraction = min(1.0, max(0.0, remaining / self._total))
            self._ring_photo = ImageTk.PhotoImage(widgets.ring_image(
                _RING, fraction, theme.WARNING, theme.ELEVATED, theme.SURFACE, thickness=9))
            self._ring.configure(image=self._ring_photo)
            self._seconds.configure(text=str(max(0, int(remaining + 0.5))))
        except tk.TclError:
            log.debug("Overlay ist bereits weg", exc_info=True)

    def _dismiss(self) -> None:
        self._on_dismiss()

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except tk.TclError:
            log.debug("Overlay war bereits zerstoert", exc_info=True)


class _StickyNote:
    """Kleiner Zettel, der immer oben bleibt: Zustand und Countdown auf einen Blick.
    Verschiebbar durch Ziehen; die Position wird gemerkt."""

    def __init__(self, root: tk.Tk, position: tuple[int, int], opacity: float,
                 on_moved: Callable[[int, int], None]) -> None:
        self._on_moved = on_moved
        self._drag: tuple[int, int] | None = None
        self._dot_photo: ImageTk.PhotoImage | None = None
        self._dot_color: str | None = None

        window = tk.Toplevel(root)
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        window.attributes("-alpha", opacity)
        window.configure(bg=theme.BORDER)

        x, y = position
        if x == -1 and y == -1:
            x = window.winfo_screenwidth() - _STICKY_W - 24
            y = 24
        x, y = clamp_to_screens(x, y, _STICKY_W, _STICKY_H, winapi.virtual_screen())
        window.geometry(f"{_STICKY_W}x{_STICKY_H}+{x}+{y}")

        body = tk.Frame(window, bg=theme.ELEVATED)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        self._dot = tk.Label(body, bg=theme.ELEVATED, bd=0)
        self._dot.place(x=14, y=_STICKY_H // 2, anchor="center")

        self._state = tk.Label(body, text="—", bg=theme.ELEVATED, fg=theme.TEXT,
                               font=theme.font(11, "bold"), anchor="w")
        self._state.place(x=28, y=18, anchor="w")

        self._note = tk.Label(body, text="", bg=theme.ELEVATED, fg=theme.TEXT_FAINT,
                              font=theme.font(8), anchor="w")
        self._note.place(x=28, y=38, anchor="w")

        self._countdown = tk.Label(body, text="", bg=theme.ELEVATED, fg=theme.WARNING,
                                   font=theme.font_mono(19, "bold"), anchor="e")
        self._countdown.place(x=_STICKY_W - 16, y=_STICKY_H // 2, anchor="e")

        self._window = window
        self._bind_drag(window)
        self._bind_drag(body)
        for child in body.winfo_children():
            self._bind_drag(child)
        self._set_dot(theme.NEUTRAL)

    def _bind_drag(self, widget) -> None:
        widget.bind("<Button-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._move)
        widget.bind("<ButtonRelease-1>", self._end_drag)

    def _start_drag(self, event) -> None:
        self._drag = (event.x_root - self._window.winfo_x(),
                      event.y_root - self._window.winfo_y())

    def _move(self, event) -> None:
        if self._drag is None:
            return
        self._window.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _end_drag(self, _event) -> None:
        if self._drag is None:
            return
        self._drag = None
        try:
            self._on_moved(self._window.winfo_x(), self._window.winfo_y())
        except Exception:
            log.exception("Position des Notizzettels nicht gemerkt")

    def _set_dot(self, color: str) -> None:
        if color == self._dot_color:
            return
        self._dot_color = color
        self._dot_photo = ImageTk.PhotoImage(widgets.dot_image(10, color, theme.ELEVATED))
        self._dot.configure(image=self._dot_photo)

    def render(self, snapshot) -> None:
        try:
            self._set_dot(theme.STATE_COLORS.get(snapshot.state.value, theme.NEUTRAL))
            self._state.configure(text=snapshot.state.value)
            self._note.configure(text=(snapshot.note or "")[:34])
            if snapshot.countdown is None:
                self._countdown.configure(text="")
            else:
                self._countdown.configure(text=f"{max(0, int(snapshot.countdown + 0.5))}s")
        except tk.TclError:
            log.debug("Notizzettel ist bereits weg", exc_info=True)

    def destroy(self) -> None:
        try:
            self._window.destroy()
        except tk.TclError:
            log.debug("Notizzettel war bereits zerstoert", exc_info=True)


class _PreviewWindow:
    """Live-Ansicht: zeigt, was der Detektor sieht, und laesst die Schwelle regeln."""

    def __init__(self, root: tk.Tk, callbacks: UiCallbacks, max_width: int,
                 on_close: Callable[[], None]) -> None:
        self._callbacks = callbacks
        self._max_width = max_width
        self._photo: ImageTk.PhotoImage | None = None  # Referenz halten, sonst GC
        self._dot_photo: ImageTk.PhotoImage | None = None
        self._dot_color: str | None = None
        self._font = _load_font(13)
        self._synced_threshold = False
        self._save_hint_after: str | None = None

        window = tk.Toplevel(root)
        window.title("away-monitor · Live")
        window.configure(bg=theme.BG)
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", on_close)
        self._window = window
        window.update_idletasks()
        theme.apply_dark_titlebar(window)
        theme.apply_rounded_corners(window)

        outer = tk.Frame(window, bg=theme.BG)
        outer.pack(fill="both", expand=True, padx=theme.SPACE_L, pady=theme.SPACE_L)

        self._image_label = tk.Label(outer, bg="#000000", bd=0)
        self._image_label.pack()

        # ------------------------------------------------------------ Zustand
        status = tk.Frame(outer, bg=theme.BG)
        status.pack(fill="x", pady=(theme.SPACE_M, theme.SPACE_S))
        self._dot = tk.Label(status, bg=theme.BG, bd=0)
        self._dot.pack(side="left", padx=(2, theme.SPACE_S))
        texts = tk.Frame(status, bg=theme.BG)
        texts.pack(side="left", fill="x", expand=True)
        self._state_label = tk.Label(texts, text="—", bg=theme.BG, fg=theme.TEXT,
                                     font=theme.font(14, "bold"), anchor="w")
        self._state_label.pack(fill="x")
        self._note_label = tk.Label(texts, text="", bg=theme.BG, fg=theme.TEXT_MUTED,
                                    font=theme.font(9), anchor="w")
        self._note_label.pack(fill="x")

        # -------------------------------------------------------------- Zahlen
        stats = widgets.card(outer)
        stats.pack(fill="x", pady=(0, theme.SPACE_M))
        inner = tk.Frame(stats, bg=theme.SURFACE)
        inner.pack(fill="x", padx=theme.SPACE_M, pady=theme.SPACE_M)
        self._stats: dict[str, tk.Label] = {}
        for row, (key, caption) in enumerate([
            ("idle", "Leerlauf"),
            ("seen", "Gesicht zuletzt"),
            ("countdown", "Sperre in"),
            ("detect", "Erkennung"),
            ("camera", "Kamera"),
        ]):
            tk.Label(inner, text=caption, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                     font=theme.font(9), anchor="w").grid(
                row=row, column=0, sticky="w", pady=2)
            value = tk.Label(inner, text="—", bg=theme.SURFACE, fg=theme.TEXT,
                             font=theme.font_mono(10), anchor="e")
            value.grid(row=row, column=1, sticky="e", pady=2)
            self._stats[key] = value
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=0)

        # ------------------------------------------------------------ Regelung
        controls = widgets.card(outer)
        controls.pack(fill="x")
        pad = tk.Frame(controls, bg=theme.SURFACE)
        pad.pack(fill="x", padx=theme.SPACE_M, pady=theme.SPACE_M)

        row = tk.Frame(pad, bg=theme.SURFACE)
        row.pack(fill="x")
        tk.Label(row, text="Schwelle", bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(9)).pack(side="left")
        self._threshold = tk.DoubleVar(value=0.6)
        self._threshold_label = tk.Label(row, text="0.60", bg=theme.SURFACE,
                                         fg=theme.TEXT, font=theme.font_mono(10))
        self._threshold_label.pack(side="right")
        widgets.Slider(row, self._threshold, minimum=0.05, maximum=0.95, step=0.05,
                       width=170, bg=theme.SURFACE,
                       command=self._on_threshold).pack(side="right",
                                                        padx=theme.SPACE_S)

        buttons = tk.Frame(pad, bg=theme.SURFACE)
        buttons.pack(fill="x", pady=(theme.SPACE_S, 0))
        self._save_button = widgets.RoundedButton(
            buttons, "Schwelle speichern", self._on_save, bg=theme.SURFACE,
            width=152, height=32, font=theme.font(9))
        self._save_button.pack(side="right")

        toggles = tk.Frame(pad, bg=theme.SURFACE)
        toggles.pack(fill="x", pady=(theme.SPACE_M, 0))
        self._show_image = tk.BooleanVar(value=True)
        self._paused = tk.BooleanVar(value=False)
        self._toggle_row(toggles, "Kamerabild anzeigen", self._show_image, None)
        self._toggle_row(toggles, "Überwachung pausiert", self._paused, self._on_pause)

        self._set_dot(theme.NEUTRAL)

    def _toggle_row(self, parent, text: str, variable: tk.BooleanVar,
                    command: Callable[[], None] | None) -> None:
        row = tk.Frame(parent, bg=theme.SURFACE)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=text, bg=theme.SURFACE, fg=theme.TEXT_MUTED,
                 font=theme.font(9), anchor="w").pack(side="left")
        widgets.Switch(row, variable, command, bg=theme.SURFACE).pack(side="right")

    # ------------------------------------------------------------- Zeichnen
    def _set_dot(self, color: str) -> None:
        if color == self._dot_color:
            return
        self._dot_color = color
        self._dot_photo = ImageTk.PhotoImage(widgets.dot_image(12, color, theme.BG))
        self._dot.configure(image=self._dot_photo)

    def render(self, snapshot) -> None:
        self._render_image(snapshot)

        self._set_dot(theme.STATE_COLORS.get(snapshot.state.value, theme.TEXT))
        self._state_label.configure(text=snapshot.state.value)
        self._note_label.configure(text=snapshot.note or "")

        self._stats["idle"].configure(text=f"{snapshot.idle_seconds:.1f} s")
        self._stats["seen"].configure(
            text="—" if snapshot.seen_ago is None else f"{snapshot.seen_ago:.1f} s")
        self._stats["countdown"].configure(
            text="—" if snapshot.countdown is None else f"{snapshot.countdown:.1f} s")
        self._stats["detect"].configure(
            text=f"{snapshot.detect_ms:.1f} ms · {len(snapshot.faces)}")
        self._stats["camera"].configure(text="offen" if snapshot.camera_open else "zu")

        # Die Schwelle nur einmal uebernehmen -- danach ist der Regler die Quelle,
        # sonst zappelt er beim Ziehen gegen den Zustrom aus dem Monitor.
        if not self._synced_threshold:
            self._threshold.set(round(snapshot.score_threshold, 2))
            self._threshold_label.configure(text=f"{snapshot.score_threshold:.2f}")
            self._synced_threshold = True

        is_paused = snapshot.state.value == "pausiert"
        if is_paused != self._paused.get():
            self._paused.set(is_paused)

    def _render_image(self, snapshot) -> None:
        frame = snapshot.frame
        if frame is None:
            height = self._max_width * 3 // 4
            image = Image.new("RGB", (self._max_width, height), "#05070a")
            draw = ImageDraw.Draw(image)
            draw.text((14, 14), "kein Kamerabild", fill=theme.TEXT_FAINT, font=self._font)
            self._show(image)
            return

        height, width = frame.shape[:2]
        if self._show_image.get():
            # OpenCV liefert BGR, PIL erwartet RGB.
            image = Image.fromarray(np.ascontiguousarray(frame[:, :, ::-1]))
        else:
            image = Image.new("RGB", (width, height), "#05070a")

        # Erst skalieren, dann zeichnen: so bleiben Rahmen und Text scharf.
        scale = self._max_width / width
        image = image.resize((self._max_width, max(1, int(height * scale))))

        draw = ImageDraw.Draw(image)
        for face in snapshot.faces:
            left, top = int(face.x * scale), int(face.y * scale)
            right = int((face.x + face.width) * scale)
            bottom = int((face.y + face.height) * scale)
            draw.rounded_rectangle([left, top, right, bottom], radius=6,
                                   outline=theme.SUCCESS, width=2)
            label = f"{face.score:.2f}"
            draw.rounded_rectangle([left, max(0, top - 19), left + 8 * len(label) + 10, top],
                                   radius=4, fill=theme.SUCCESS)
            draw.text((left + 5, max(0, top - 18)), label, fill="#05070a", font=self._font)

        if not snapshot.faces:
            draw.rounded_rectangle([10, 8, 118, 30], radius=6, fill="#000000")
            draw.text((18, 12), "kein Gesicht", fill=theme.WARNING, font=self._font)

        self._show(image)

    def _show(self, image: Image.Image) -> None:
        self._photo = ImageTk.PhotoImage(image)
        self._image_label.configure(image=self._photo)

    # ------------------------------------------------------------ Bedienung
    def _on_threshold(self, value: float) -> None:
        self._threshold_label.configure(text=f"{value:.2f}")
        self._callbacks.on_threshold(value)

    def _on_save(self) -> None:
        ok = self._callbacks.on_threshold_save(self._threshold.get())
        self._save_button.configure(text="gespeichert" if ok else "Fehler")
        if self._save_hint_after is not None:
            self._window.after_cancel(self._save_hint_after)
        self._save_hint_after = self._window.after(1800, self._reset_save_button)

    def _reset_save_button(self) -> None:
        self._save_hint_after = None
        try:
            self._save_button.configure(text="Schwelle speichern")
        except tk.TclError:
            log.debug("Speichern-Knopf ist weg", exc_info=True)

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


def clamp_to_screens(x: int, y: int, width: int, height: int,
                     bounds: tuple[int, int, int, int]) -> tuple[int, int]:
    """Haelt ein Fenster im sichtbaren Bereich -- ueber alle Bildschirme hinweg.

    bounds ist (x, y, breite, hoehe) des virtuellen Desktops. Auf einem Monitor
    links des Hauptbildschirms ist x negativ; dagegen auf 0 zu klemmen wuerde
    das Fenster jedes Mal zurueckholen."""
    left, top, total_width, total_height = bounds
    x = max(left, min(x, left + total_width - width))
    y = max(top, min(y, top + total_height - height))
    return int(x), int(y)


def _load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # aeltere Pillow-Versionen kennen den Parameter nicht
        return ImageFont.load_default()
