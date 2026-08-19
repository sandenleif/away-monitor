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

# Woher diese Version stammt. Steht bewusst im Code und nicht nur in der
# config.toml: eine frisch ausgepackte Exe soll ihre Updates von allein finden.
DEFAULT_REPOSITORY = "sandenleif/away-monitor"


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

[sticky]
# Kleiner Notizzettel, der Zustand und Countdown immer im Vordergrund haelt.
# Laesst sich auch ueber das Tray-Menue ein- und ausschalten.
enabled = false
# Merkt sich, wohin du ihn geschoben hast. -1 heisst: rechts oben einblenden.
x = -1
y = -1
# Deckkraft zwischen 0.3 und 1.0.
opacity = 0.92

[behavior]
# Was tun, wenn die Kamera nicht zu oeffnen ist (z.B. weil Teams sie belegt)?
#   "never_lock" -- als anwesend werten. Sinnvoller Default: eine belegte Kamera
#                   heisst meist Videocall, also sitzt du davor.
#   "lock"       -- als abwesend werten.
on_camera_error = "never_lock"
start_paused = false

[update]
# Herkunft der App im Format "besitzer/name". Wird die Zeile geleert oder
# entfernt, traegt die App die Voreinstellung beim naechsten Start wieder ein --
# sie soll ihre eigene Herkunft nie verlieren. Auf einen Fork zeigen laesst sie
# von dort aktualisieren.
repository = "sandenleif/away-monitor"
# Updatepruefung abschalten: hier auf false setzen (nicht das Repository leeren).
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

    sticky_enabled: bool = False
    sticky_x: int = -1
    sticky_y: int = -1
    sticky_opacity: float = 0.92

    on_camera_error: str = "never_lock"
    start_paused: bool = False

    update_repository: str = DEFAULT_REPOSITORY
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
        text = path.read_text(encoding="utf-8")
        raw = tomllib.loads(text)
    except (OSError, tomllib.TOMLDecodeError):
        log.exception("config.toml unlesbar -- es gelten die Defaults")
        return Config()

    timing = raw.get("timing", {})
    camera = raw.get("camera", {})
    detection = raw.get("detection", {})
    preview = raw.get("preview", {})
    sticky = raw.get("sticky", {})
    behavior = raw.get("behavior", {})
    update = raw.get("update", {})
    logging_ = raw.get("logging", {})
    defaults = Config()

    repository = str(update.get("repository", "")).strip()
    if not repository:
        # Weder leeren noch Loeschen darf die App ihre Herkunft kosten -- sonst
        # sucht eine ueber Versionen mitgeschleppte config.toml nie nach Updates,
        # ohne dass irgendetwas sichtbar kaputt waere.
        repository = DEFAULT_REPOSITORY
        _restore_repository(path, text)

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
        sticky_enabled=bool(sticky.get("enabled", defaults.sticky_enabled)),
        sticky_x=int(sticky.get("x", defaults.sticky_x)),
        sticky_y=int(sticky.get("y", defaults.sticky_y)),
        sticky_opacity=min(1.0, max(0.3, float(sticky.get("opacity", defaults.sticky_opacity)))),
        on_camera_error=on_error,
        start_paused=bool(behavior.get("start_paused", defaults.start_paused)),
        update_repository=repository,
        update_check_on_start=bool(
            update.get("check_on_start", defaults.update_check_on_start)
        ),
        update_require_checksum=bool(
            update.get("require_checksum", defaults.update_require_checksum)
        ),
        log_level=str(logging_.get("level", defaults.log_level)),
        log_file=_resolve(str(logging_.get("file", "away-monitor.log")), DATA_ROOT),
    )


_REPOSITORY_LINE = re.compile(r'^(\s*repository\s*=\s*).*$', re.MULTILINE)
_UPDATE_SECTION = re.compile(r'^\[update\]\s*$', re.MULTILINE)

_UPDATE_BLOCK = """

[update]
# Herkunft der App im Format "besitzer/name" -- nachgetragen, weil sie fehlte.
repository = "{repository}"
# Updatepruefung abschalten: hier auf false setzen (nicht das Repository leeren).
check_on_start = true
# Ohne veroeffentlichte SHA256-Pruefsumme wird nichts installiert.
require_checksum = true
"""


def _restore_repository(path: Path, text: str) -> None:
    """Traegt die Voreinstellung in die Datei zurueck.

    Betrifft mit aelteren Versionen angelegte Dateien: dort stand die Zeile leer,
    weil es noch keine Voreinstellung gab. Ohne diesen Schritt bliebe sie leer,
    und die App wuerde nie nach Updates sehen -- unauffaellig, weil nichts
    fehlschlaegt."""
    if _REPOSITORY_LINE.search(text):
        updated = _REPOSITORY_LINE.sub(
            lambda m: f'{m.group(1)}"{DEFAULT_REPOSITORY}"', text, count=1
        )
    elif _UPDATE_SECTION.search(text):
        replacement = "\n".join(["[update]", f'repository = "{DEFAULT_REPOSITORY}"'])
        updated = _UPDATE_SECTION.sub(replacement, text, count=1)
    else:
        updated = text.rstrip("\n") + _UPDATE_BLOCK.format(repository=DEFAULT_REPOSITORY)

    if updated == text:
        return
    try:
        path.write_text(updated, encoding="utf-8")
        log.info("Update-Repository in %s nachgetragen: %s", path, DEFAULT_REPOSITORY)
    except OSError:
        # Nicht schlimm: im Speicher gilt die Voreinstellung ohnehin.
        log.warning("Konnte %s nicht ergaenzen", path, exc_info=True)


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


_STICKY_SECTION = re.compile(r"^\[sticky\]$", re.MULTILINE)


def save_sticky(enabled: bool | None = None, x: int | None = None,
                y: int | None = None, path: Path = CONFIG_PATH) -> bool:
    """Merkt Sichtbarkeit und Position des Notizzettels.

    Aendert nur die betroffenen Zeilen im [sticky]-Abschnitt; Kommentare und
    alles ausserhalb bleiben unangetastet."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        log.warning("config.toml nicht lesbar: %s", path, exc_info=True)
        return False

    section = _STICKY_SECTION.search(text)
    if section is None:
        log.debug("Kein [sticky]-Abschnitt -- Position wird nicht gemerkt")
        return False

    # Der Abschnitt endet beim naechsten "[" am Zeilenanfang.
    following = re.search(r"^\[", text[section.end():], re.MULTILINE)
    end = section.end() + (following.start() if following else len(text) - section.end())

    block = text[section.end():end]
    wanted: dict[str, str] = {}
    if enabled is not None:
        wanted["enabled"] = "true" if enabled else "false"
    if x is not None:
        wanted["x"] = str(int(x))
    if y is not None:
        wanted["y"] = str(int(y))

    updated = block
    for key, value in wanted.items():
        pattern = re.compile(rf"^(\s*{key}\s*=\s*).*$", re.MULTILINE)
        if pattern.search(updated) is None:
            updated = updated.rstrip("\n") + f"\n{key} = {value}\n"
        else:
            updated = pattern.sub(lambda m, v=value: f"{m.group(1)}{v}", updated, count=1)

    if updated == block:
        return True
    try:
        path.write_text(text[:section.end()] + updated + text[end:], encoding="utf-8")
    except OSError:
        log.warning("config.toml nicht schreibbar: %s", path, exc_info=True)
        return False
    return True
