"""Zustandsautomat: Eingabe schlaegt Kamera, Kamera schlaegt Zweifel."""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import winapi
from .camera import Camera
from .config import Config
from .detector import Face, FaceDetector

log = logging.getLogger(__name__)

# Nach dem Sperren kurz nichts tun: LockWorkStation wirkt asynchron, der
# Sperrbildschirm ist erst nach einem Moment da.
_LOCK_COOLDOWN = 5.0


class State(enum.Enum):
    ACTIVE = "aktiv"
    WATCHING = "beobachte"
    WARNING = "Warnung"
    LOCKED = "gesperrt"
    PAUSED = "pausiert"


@dataclass(frozen=True)
class Snapshot:
    """Alles, was die Live-Ansicht braucht. Sie bekommt es vom Monitor, statt
    selbst auf die Kamera zuzugreifen -- DirectShow gibt sie nur einmal her."""

    state: State
    note: str
    idle_seconds: float
    score_threshold: float
    faces: tuple[Face, ...] = ()
    frame: object | None = None  # BGR-ndarray
    seen_ago: float | None = None
    countdown: float | None = None
    detect_ms: float = 0.0
    camera_open: bool = False


class Monitor(threading.Thread):
    def __init__(self, config: Config, ui, on_state: Callable[[State, str], None] | None = None,
                 dry_run: bool = False):
        super().__init__(name="away-monitor", daemon=True)
        self._config = config
        self._dry_run = dry_run
        self._ui = ui
        self._on_state = on_state

        self._camera = Camera(
            index=config.camera_index,
            backends=config.backends,
            warmup_seconds=config.warmup_seconds,
            warmup_frames=config.warmup_frames,
            open_retry_seconds=config.open_retry_seconds,
        )
        self._detector = FaceDetector(config.model, config.score_threshold)

        self._stopping = threading.Event()
        self._present_request = threading.Event()
        self._lock_request = threading.Event()
        self._paused = config.start_paused

        self.state = State.PAUSED if self._paused else State.ACTIVE
        self.note = ""
        self._last_present = time.monotonic()
        self._warning_until = 0.0
        self._cooldown_until = 0.0

        # Live-Ansicht
        self._preview_listener: Callable[[Snapshot], None] | None = None
        self._preview_enabled = False
        self._sticky_enabled = False
        self._last_frame = None
        self._last_faces: tuple[Face, ...] = ()
        self._last_face_seen: float | None = None
        self._detect_ms = 0.0

    # ------------------------------------------------------------------ API
    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def preview_enabled(self) -> bool:
        return self._preview_enabled

    @property
    def sticky_enabled(self) -> bool:
        return self._sticky_enabled

    @property
    def score_threshold(self) -> float:
        return self._detector.score_threshold

    def set_state_listener(self, callback: Callable[[State, str], None]) -> None:
        self._on_state = callback

    def set_preview_listener(self, callback: Callable[[Snapshot], None]) -> None:
        self._preview_listener = callback

    def set_preview_enabled(self, enabled: bool) -> None:
        if enabled == self._preview_enabled:
            return
        self._preview_enabled = enabled
        log.info("Live-Ansicht %s", "geoeffnet" if enabled else "geschlossen")

    def set_sticky_enabled(self, enabled: bool) -> None:
        """Der Notizzettel braucht Zustand und Countdown, aber kein Kamerabild --
        er beschleunigt den Takt deshalb nicht."""
        if enabled == self._sticky_enabled:
            return
        self._sticky_enabled = enabled
        log.info("Notizzettel %s", "eingeblendet" if enabled else "ausgeblendet")

    def set_score_threshold(self, value: float) -> None:
        self._detector.score_threshold = value

    def toggle_pause(self) -> None:
        self._paused = not self._paused
        log.info("Ueberwachung %s", "pausiert" if self._paused else "fortgesetzt")
        if not self._paused:
            self._last_present = time.monotonic()

    def mark_present(self) -> None:
        """Vom Ich-bin-da-Button."""
        self._present_request.set()

    def lock_now(self) -> None:
        self._lock_request.set()

    def stop(self) -> None:
        self._stopping.set()

    # ----------------------------------------------------------------- Lauf
    def run(self) -> None:
        log.info("Monitor laeuft (Takt %.1f s)", self._config.tick_seconds)
        self._announce()
        while not self._stopping.wait(self._interval()):
            try:
                self._tick()
            except Exception:  # ein Fehler pro Tick darf den Dienst nicht killen
                log.exception("Fehler im Tick -- weiter im naechsten Takt")
        self._release()
        log.info("Monitor beendet")

    def _interval(self) -> float:
        """Waehrend der Live-Ansicht schneller abtasten. Der Automat rechnet mit
        Wanduhr-Differenzen, nicht mit Takten -- haeufigeres Abtasten verschiebt
        also keine Schwelle, macht das Vorschaubild aber fluessig."""
        if self._preview_enabled:
            return min(self._config.tick_seconds, self._config.preview_tick_seconds)
        return self._config.tick_seconds

    def _tick(self) -> None:
        now = time.monotonic()

        if self._lock_request.is_set():
            self._lock_request.clear()
            self._lock(now, reason="manuell")
            return

        if now < self._cooldown_until:
            return

        idle = winapi.idle_seconds()

        if self._paused:
            # Pausiert plus Live-Ansicht ist der Einstellmodus: Bild da, Sperre aus.
            if self._preview_enabled:
                self._look(now)
            else:
                self._release()
            self._ui.hide_warning()
            self._enter(State.PAUSED, "Überwachung pausiert")
            self._publish(now, idle)
            return

        if winapi.is_session_locked():
            self._release()
            self._ui.hide_warning()
            self._last_present = now
            self._enter(State.LOCKED, "Sitzung gesperrt")
            self._publish(now, idle)
            return

        if self.state is State.LOCKED:
            log.info("Sitzung entsperrt")
            self._last_present = now

        if self._present_request.is_set():
            self._present_request.clear()
            self._last_present = now
            self._ui.hide_warning()

        if idle < self._config.idle_before_camera:
            # Eingabe ist Beweis genug -- die Kamera bleibt aus, sofern niemand zuschaut.
            self._last_present = now
            self._ui.hide_warning()
            if self._preview_enabled:
                self._look(now)  # nur fuers Bild; das Ergebnis aendert hier nichts
            elif self._config.release_when_active:
                self._release()
            self._enter(State.ACTIVE, f"Eingabe vor {idle:.0f} s")
            self._publish(now, idle)
            return

        present = self._look(now)
        if present is not False:
            # True = gesehen, None = unbekannt. Unbekannt zaehlt nie als abwesend,
            # sonst sperrt die Aufwaermphase oder eine belegte Kamera den Rechner.
            self._last_present = now

        absent = now - self._last_present

        if self.state is State.WARNING:
            if absent < self._config.absence_grace:
                self._ui.hide_warning()
                self._enter(State.WATCHING, "wieder da")
            else:
                remaining = self._warning_until - now
                if remaining <= 0:
                    self._lock(now, reason="niemand vor der Kamera")
                else:
                    self._ui.update_warning(remaining)
                    self._enter(State.WARNING, f"sperrt in {remaining:.0f} s")
        elif absent >= self._config.absence_grace:
            self._warning_until = now + self._config.warning_seconds
            self._ui.show_warning(self._config.warning_seconds)
            log.info("Niemand seit %.0f s erkannt -- Countdown laeuft", absent)
            self._enter(State.WARNING, f"sperrt in {self._config.warning_seconds:.0f} s")
        else:
            self._enter(State.WATCHING, self._watch_note(present, absent))

        self._publish(now, idle)

    # ------------------------------------------------------------- Interna
    def _look(self, now: float) -> bool | None:
        """Ein Blick durch die Kamera.
        True = Gesicht, False = niemand, None = unbekannt (nicht bewerten)."""
        if not self._camera.open():
            self._last_frame, self._last_faces = None, ()
            return False if self._config.on_camera_error == "lock" else None

        frame = self._camera.read()
        if frame is None:
            self._last_frame, self._last_faces = None, ()
            return None

        self._last_frame = frame  # auch waehrend des Aufwaermens anzeigbar
        if not self._camera.is_warm:
            self._last_faces = ()
            return None

        started = time.monotonic()
        faces = self._detector.detect(frame)
        self._detect_ms = (time.monotonic() - started) * 1000.0
        self._last_faces = tuple(faces)
        if faces:
            self._last_face_seen = now
        return bool(faces)

    def _release(self) -> None:
        self._camera.release()
        self._last_frame, self._last_faces = None, ()

    def _publish(self, now: float, idle: float) -> None:
        listener = self._preview_listener
        if listener is None or not (self._preview_enabled or self._sticky_enabled):
            return
        countdown = None
        if self.state is State.WARNING:
            countdown = max(0.0, self._warning_until - now)
        try:
            listener(Snapshot(
                state=self.state,
                note=self.note,
                idle_seconds=idle,
                score_threshold=self._detector.score_threshold,
                faces=self._last_faces,
                frame=self._last_frame,
                seen_ago=None if self._last_face_seen is None else now - self._last_face_seen,
                countdown=countdown,
                detect_ms=self._detect_ms,
                camera_open=self._camera.is_open,
            ))
        except Exception:
            log.exception("Live-Ansicht konnte nicht beliefert werden")

    def _watch_note(self, present: bool | None, absent: float) -> str:
        if present is True:
            return "Gesicht erkannt"
        if present is None:
            if not self._camera.is_open:
                return "Kamera nicht verfügbar -- sperrt nicht"
            return "Kamera wärmt auf"
        return f"niemand seit {absent:.0f} s"

    def _lock(self, now: float, reason: str) -> None:
        self._ui.hide_warning()
        self._release()
        if self._dry_run:
            log.warning("[dry-run] wuerde jetzt sperren (%s)", reason)
        else:
            log.info("Sperre Arbeitsstation (%s)", reason)
            winapi.lock_workstation()
        self._last_present = now
        self._cooldown_until = now + _LOCK_COOLDOWN
        self._enter(State.LOCKED, "gesperrt")

    def _enter(self, state: State, note: str) -> None:
        if state is not self.state:
            log.debug("Zustand %s -> %s (%s)", self.state.value, state.value, note)
        changed = state is not self.state or note != self.note
        self.state, self.note = state, note
        if changed:
            self._announce()

    def _announce(self) -> None:
        if self._on_state is not None:
            try:
                self._on_state(self.state, self.note)
            except Exception:
                log.exception("Statusanzeige konnte nicht aktualisiert werden")
