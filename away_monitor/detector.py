"""Gesichtserkennung via YuNet (in OpenCV enthalten, ~230 KB ONNX-Modell)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2

log = logging.getLogger(__name__)

_NMS_THRESHOLD = 0.3
_TOP_K = 5000
_MIN_SCORE = 0.05
_MAX_SCORE = 0.95


@dataclass(frozen=True)
class Face:
    """Ein Treffer in Bildkoordinaten."""

    x: int
    y: int
    width: int
    height: int
    score: float


class FaceDetector:
    """Beantwortet die eine Frage -- ist jemand im Bild? -- und zeigt auf Wunsch,
    *wo*: die Live-Ansicht braucht die Boxen, der Monitor nur ihre Anzahl."""

    def __init__(self, model_path: Path, score_threshold: float = 0.6) -> None:
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Modell fehlt: {model_path}\n"
                r"Einmalig laden mit:  .venv\Scripts\python.exe scripts\fetch_model.py"
            )
        self._size = (320, 320)
        self._score_threshold = _clamp(score_threshold)
        self._detector = cv2.FaceDetectorYN.create(
            str(model_path), "", self._size, self._score_threshold, _NMS_THRESHOLD, _TOP_K
        )
        log.info("YuNet geladen (Schwelle %.2f)", self._score_threshold)

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @score_threshold.setter
    def score_threshold(self, value: float) -> None:
        value = _clamp(value)
        if value == self._score_threshold:
            return
        self._score_threshold = value
        # YuNet kann die Schwelle im laufenden Betrieb aendern -- kein Neuaufbau noetig.
        self._detector.setScoreThreshold(value)
        log.info("Erkennungsschwelle auf %.2f gesetzt", value)

    def detect(self, frame) -> list[Face]:
        height, width = frame.shape[:2]
        if (width, height) != self._size:
            self._size = (width, height)
            self._detector.setInputSize(self._size)
        try:
            _, rows = self._detector.detect(frame)
        except cv2.error:
            log.exception("Erkennung fehlgeschlagen -- Bild wird verworfen")
            return []
        if rows is None:
            return []
        # YuNet liefert je Zeile: x, y, w, h, 5 Landmarken (10 Werte), Score.
        return [
            Face(int(row[0]), int(row[1]), int(row[2]), int(row[3]), float(row[-1]))
            for row in rows
        ]


def _clamp(value: float) -> float:
    return min(_MAX_SCORE, max(_MIN_SCORE, float(value)))
