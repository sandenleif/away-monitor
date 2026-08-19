"""Kamerazugriff mit Backend-Fallback und Aufwaermphase."""

from __future__ import annotations

import logging
import time

import cv2

log = logging.getLogger(__name__)

# DSHOW zuerst: oeffnet auf typischer Hardware in ~0,7 s, MSMF braucht dafuer
# ueber 10 s. MSMF bleibt als Fallback, weil es sich die Kamera ueber den
# Windows Frame Server eher mit anderen Apps teilt.
_BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}

_MAX_READ_FAILURES = 8


class Camera:
    """Oeffnet die Webcam nur solange sie gebraucht wird."""

    def __init__(
        self,
        index: int = 0,
        backends: tuple[str, ...] = ("dshow", "msmf", "any"),
        warmup_seconds: float = 1.5,
        warmup_frames: int = 5,
        flush_frames: int = 2,
        open_retry_seconds: float = 5.0,
    ) -> None:
        self._index = index
        self._backends = backends
        self._warmup_seconds = warmup_seconds
        self._warmup_frames = warmup_frames
        self._flush_frames = max(0, flush_frames)
        self._open_retry_seconds = open_retry_seconds
        self._cap: cv2.VideoCapture | None = None
        self._opened_at = 0.0
        self._good_frames = 0
        self._failures = 0
        self._open_error_logged = False
        self._retry_after = 0.0

    @property
    def is_open(self) -> bool:
        return self._cap is not None

    @property
    def is_warm(self) -> bool:
        """Erst nach Aufwaermen sind die Bilder belastbar (erste Frames sind oft schwarz)."""
        return (
            self._cap is not None
            and self._good_frames >= self._warmup_frames
            and (time.monotonic() - self._opened_at) >= self._warmup_seconds
        )

    def open(self) -> bool:
        if self._cap is not None:
            return True
        # Nach einem Fehlschlag kurz Ruhe geben: bei belegter oder abgezogener
        # Kamera sonst zwei Oeffnungsversuche pro Sekunde, dauerhaft.
        now = time.monotonic()
        if now < self._retry_after:
            return False
        for name in self._backends:
            api = _BACKENDS.get(name)
            if api is None:
                log.warning("Unbekanntes Kamera-Backend %r wird uebersprungen", name)
                continue
            started = time.monotonic()
            cap = cv2.VideoCapture(self._index, api)
            if cap.isOpened():
                # Kleiner Puffer: sonst liefert read() bei 0,5-s-Takt veraltete Bilder.
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._cap = cap
                self._opened_at = time.monotonic()
                self._good_frames = 0
                self._failures = 0
                self._open_error_logged = False
                log.info(
                    "Kamera %d geoeffnet (Backend %s, %.1f s)",
                    self._index, name, self._opened_at - started,
                )
                return True
            cap.release()
            log.debug("Backend %s konnte Kamera %d nicht oeffnen", name, self._index)
        self._retry_after = time.monotonic() + self._open_retry_seconds
        if not self._open_error_logged:
            log.warning(
                "Kamera %d mit keinem Backend zu oeffnen -- belegt sie eine andere App?",
                self._index,
            )
            self._open_error_logged = True
        return False

    def read(self):
        """Aktuellstes Bild oder None. None heisst *unbekannt*, nicht *niemand da*."""
        if self._cap is None:
            return None
        for _ in range(self._flush_frames):
            self._cap.grab()
        ok, frame = self._cap.retrieve() if self._flush_frames else self._cap.read()
        if not ok or frame is None:
            self._failures += 1
            if self._failures >= _MAX_READ_FAILURES:
                log.warning("%d Lesefehler in Folge -- Kamera wird neu geoeffnet", self._failures)
                self.release()
            return None
        self._failures = 0
        self._good_frames += 1
        return frame

    def release(self) -> None:
        self._retry_after = 0.0
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self._good_frames = 0
            self._failures = 0
            log.info("Kamera freigegeben")
