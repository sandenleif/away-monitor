"""Konfiguration aus config.toml -- fehlt sie, wird sie mit Defaults angelegt."""

from __future__ import annotations

import logging
import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def _bundle_root() -> Path:
    """Wo die mitgelieferten Daten liegen (das ONNX-Modell).
    Im Onefile-Exe ist das das Auspackverzeichnis von PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _is_writable(directory: Path) -> bool:
    probe = directory / ".away-monitor-schreibtest"
    try:
        probe.touch()
        probe.unlink()
    except OSError:
        return False
    return True


def _data_root() -> Path:
    """Wo Konfiguration und Log liegen -- normalerweise neben der Exe.

    Nicht ins Auspackverzeichnis schreiben: das wird bei jedem Start neu
    angelegt und beim Beenden geloescht, die Einstellungen waeren sofort weg.

    Liegt die Exe irgendwo, wo ein Nutzerprogramm nichts schreiben darf (etwa
    im Ordner "Programme"), weichen wir nach %LOCALAPPDATA% aus. Sonst kippt
    schon das Anlegen der Logdatei den Start -- und zwar mit einem Fehlerdialog,
    den bei einem Autostart niemand sieht."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent

    beside_executable = Path(sys.executable).parent
    if _is_writable(beside_executable):
        return beside_executable

    fallback = Path(os.environ.get("LOCALAPPDATA", beside_executable)) / "away-monitor"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        return beside_executable
    return fallback


BUNDLE_ROOT = _bundle_root()
DATA_ROOT = _data_root()
CONFIG_PATH = DATA_ROOT / "config.toml"

DEFAULT_CONFIG = """\
# away-monitor -- Konfiguration. Aenderungen wirken nach einem Neustart der App.

[timing]
# Sekunden ohne Maus/Tastatur, bevor die Kamera ueberhaupt angeht.
# Eingabe ist der zuverlaessigste Anwesenheitsbeweis -- ein Wert > 0 spart Strom,
# schont die Privatsphaere und verhindert die meisten Fehlalarme.
#
# 0 schaltet das Gate ab: die Kamera laeuft dauerhaft und entscheidet allein.
# Achtung, dann zaehlt Tippen nicht mehr als Anwesenheit -- wer aus dem
# Bildausschnitt geraet, wird gesperrt, auch wenn er gerade schreibt.
idle_before_camera = 0.0

# Sekunden ohne erkanntes Gesicht, bis die Warnung erscheint.
absence_grace = 20.0

# Laenge des Countdowns, in dem du die Sperre noch abbrechen kannst.
warning_seconds = 5.0

# Taktrate der Zustandspruefung.
tick_seconds = 0.5

[camera]
index = 0
backends = ["dshow", "msmf", "any"]
warmup_seconds = 1.5
warmup_frames = 5
# Pause nach einem gescheiterten Oeffnungsversuch (belegte/abgezogene Kamera).
open_retry_seconds = 5.0
# Kamera freigeben, sobald du wieder tippst (LED aus, andere Apps koennen sie
# nutzen). Wirkungslos, solange idle_before_camera auf 0 steht.
release_when_active = true

[detection]
model = "models/face_detection_yunet_2023mar.onnx"
# Hoeher = weniger Fehlalarme durch Poster/Fotos, aber unempfindlicher bei
# schlechtem Licht und Halbprofil.
score_threshold = 0.6

[preview]
# Takt der Live-Ansicht. Schneller = fluessigeres Bild, mehr CPU (~15 ms je Bild).
# Aendert keine Schwellwerte: der Zustandsautomat rechnet mit der Wanduhr.
tick_seconds = 0.1
# Breite des Vorschaubilds in Pixeln.
max_width = 480

[behavior]
# Was tun, wenn die Kamera nicht zu oeffnen ist (z.B. weil Teams sie belegt)?
#   "never_lock" -- als anwesend werten. Sinnvoller Default: eine belegte Kamera
#                   heisst meist Videocall, also sitzt du davor.
#   "lock"       -- als abwesend werten.
on_camera_error = "never_lock"
start_paused = false

[update]
# GitHub-Repository im Format "besitzer/name". Leer laesst die Updatesuche aus.
repository = ""
# Beim Start einmal nachsehen, ob es eine neuere Version gibt.
check_on_start = true
# Ohne veroeffentlichte SHA256-Pruefsumme wird nichts installiert.
# Nur abschalten, wenn du sehr genau weisst, warum.
require_checksum = true

[logging]
level = "info"
file = "away-monitor.log"
"""


@dataclass(frozen=True)
class Config:
    idle_before_camera: float = 0.0
    absence_grace: float = 20.0
    warning_seconds: float = 5.0
    tick_seconds: float = 0.5

    camera_index: int = 0
    backends: tuple[str, ...] = ("dshow", "msmf", "any")
    warmup_seconds: float = 1.5
    warmup_frames: int = 5
    open_retry_seconds: float = 5.0
    release_when_active: bool = True

    model: Path = field(
        default=BUNDLE_ROOT / "models" / "face_detection_yunet_2023mar.onnx"
    )
    score_threshold: float = 0.6

    preview_tick_seconds: float = 0.1
    preview_max_width: int = 480

    on_camera_error: str = "never_lock"
    start_paused: bool = False

    update_repository: str = ""
    update_check_on_start: bool = True
    update_require_checksum: bool = True

    log_level: str = "info"
    log_file: Path = field(default=DATA_ROOT / "away-monitor.log")


def _resolve(value: str, base: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def load(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        try:
            path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            log.info("Standardkonfiguration angelegt: %s", path)
        except OSError:
            log.exception("config.toml nicht anlegbar (%s) -- es gelten die Defaults", path)
            return Config()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        log.exception("config.toml unlesbar -- es gelten die Defaults")
        return Config()

    timing = raw.get("timing", {})
    camera = raw.get("camera", {})
    detection = raw.get("detection", {})
    preview = raw.get("preview", {})
    behavior = raw.get("behavior", {})
    update = raw.get("update", {})
    logging_ = raw.get("logging", {})
    defaults = Config()

    on_error = str(behavior.get("on_camera_error", defaults.on_camera_error))
    if on_error not in ("never_lock", "lock"):
        log.warning("on_camera_error=%r ungueltig -- nutze 'never_lock'", on_error)
        on_error = "never_lock"

    return Config(
        idle_before_camera=float(timing.get("idle_before_camera", defaults.idle_before_camera)),
        absence_grace=float(timing.get("absence_grace", defaults.absence_grace)),
        warning_seconds=float(timing.get("warning_seconds", defaults.warning_seconds)),
        tick_seconds=max(0.1, float(timing.get("tick_seconds", defaults.tick_seconds))),
        camera_index=int(camera.get("index", defaults.camera_index)),
        backends=tuple(camera.get("backends", defaults.backends)),
        warmup_seconds=float(camera.get("warmup_seconds", defaults.warmup_seconds)),
        warmup_frames=int(camera.get("warmup_frames", defaults.warmup_frames)),
        open_retry_seconds=float(camera.get("open_retry_seconds", defaults.open_retry_seconds)),
        release_when_active=bool(camera.get("release_when_active", defaults.release_when_active)),
        model=_resolve(
            str(detection.get("model", "models/face_detection_yunet_2023mar.onnx")),
            BUNDLE_ROOT,
        ),
        score_threshold=float(detection.get("score_threshold", defaults.score_threshold)),
        preview_tick_seconds=max(
            0.05, float(preview.get("tick_seconds", defaults.preview_tick_seconds))
        ),
        preview_max_width=int(preview.get("max_width", defaults.preview_max_width)),
        on_camera_error=on_error,
        start_paused=bool(behavior.get("start_paused", defaults.start_paused)),
        update_repository=str(update.get("repository", defaults.update_repository)).strip(),
        update_check_on_start=bool(
            update.get("check_on_start", defaults.update_check_on_start)
        ),
        update_require_checksum=bool(
            update.get("require_checksum", defaults.update_require_checksum)
        ),
        log_level=str(logging_.get("level", defaults.log_level)),
        log_file=_resolve(str(logging_.get("file", "away-monitor.log")), DATA_ROOT),
    )


_THRESHOLD_LINE = re.compile(r"^(\s*score_threshold\s*=\s*)[0-9.]+", re.MULTILINE)


def save_score_threshold(value: float, path: Path = CONFIG_PATH) -> bool:
    """Schreibt nur diese eine Zeile neu -- Kommentare und Reihenfolge bleiben."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.exception("config.toml nicht lesbar: %s", path)
        return False

    new_text, hits = _THRESHOLD_LINE.subn(lambda m: f"{m.group(1)}{value:.2f}", text)
    if hits != 1:
        log.warning("score_threshold in %s nicht eindeutig gefunden (%d Treffer)", path, hits)
        return False

    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        log.exception("config.toml nicht schreibbar: %s", path)
        return False
    log.info("score_threshold = %.2f in %s gespeichert", value, path)
    return True
