"""Tray-Icon: Statusanzeige, Pause, sofort sperren, beenden."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path

import pystray
from PIL import Image

from .icon import render
from .monitor import Monitor, State

log = logging.getLogger(__name__)

_COLORS = {
    State.ACTIVE: "#3ecf8e",
    State.WATCHING: "#4aa3ff",
    State.WARNING: "#ff9f43",
    State.LOCKED: "#8a8a96",
    State.PAUSED: "#5c5c66",
}


def _icon_image(color: str, paused: bool) -> Image.Image:
    return render(color, paused)


class Tray:
    def __init__(self, monitor: Monitor, config_path: Path, log_path: Path,
                 on_quit: Callable[[], None],
                 on_preview_toggle: Callable[[bool], None],
                 on_check_updates: Callable[[], None]) -> None:
        self._monitor = monitor
        self._on_preview_toggle = on_preview_toggle
        self._on_check_updates = on_check_updates
        self._config_path = config_path
        self._log_path = log_path
        self._on_quit = on_quit
        self._icon = pystray.Icon(
            "away-monitor",
            icon=_icon_image(_COLORS[State.ACTIVE], False),
            title="away-monitor",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, lambda: None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Live-Ansicht", self._toggle_preview,
                                 checked=lambda _item: self._monitor.preview_enabled),
                pystray.MenuItem("Pausiert", self._toggle_pause,
                                 checked=lambda _item: self._monitor.paused),
                pystray.MenuItem("Jetzt sperren", self._lock_now),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Konfiguration öffnen", self._open_config),
                pystray.MenuItem("Log öffnen", self._open_log),
                pystray.MenuItem("Nach Updates suchen", self._check_updates),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Beenden", self._quit),
            ),
        )

    def start(self) -> None:
        # Der win32-Backend von pystray pumpt seine Nachrichten im aufrufenden
        # Thread -- der Hauptthread gehoert Tk, also laeuft das Icon nebenher.
        threading.Thread(target=self._icon.run, name="tray", daemon=True).start()

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:
            log.exception("Tray-Icon liess sich nicht sauber stoppen")

    def refresh_menu(self) -> None:
        try:
            self._icon.update_menu()
        except Exception:
            log.exception("Tray-Menue konnte nicht aktualisiert werden")

    def set_state(self, state: State, note: str) -> None:
        try:
            self._icon.icon = _icon_image(_COLORS.get(state, "#8a8a96"), state is State.PAUSED)
            self._icon.title = f"away-monitor · {state.value}" + (f" · {note}" if note else "")
            self._icon.update_menu()
        except Exception:
            log.exception("Tray-Status konnte nicht aktualisiert werden")

    # ------------------------------------------------------------ Menuepunkte
    def _status_text(self, _item) -> str:
        note = self._monitor.note
        return f"Status: {self._monitor.state.value}" + (f" ({note})" if note else "")

    def _toggle_preview(self) -> None:
        self._on_preview_toggle(not self._monitor.preview_enabled)

    def _toggle_pause(self) -> None:
        self._monitor.toggle_pause()

    def _lock_now(self) -> None:
        self._monitor.lock_now()

    def _check_updates(self) -> None:
        self._on_check_updates()

    def _open_config(self) -> None:
        self._open(self._config_path)

    def _open_log(self) -> None:
        self._open(self._log_path)

    def _open(self, path: Path) -> None:
        try:
            os.startfile(path)  # noqa: S606 -- Windows-only, oeffnet mit Standard-App
        except OSError:
            log.exception("Konnte %s nicht oeffnen", path)

    def _quit(self) -> None:
        self._on_quit()
