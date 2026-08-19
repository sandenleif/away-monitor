"""Selbstaktualisierung ueber GitHub Releases.

Der Ablauf ist bewusst in Einzelschritte zerlegt, damit nichts hinter dem
Ruecken des Nutzers passiert:

    check_for_update()  ->  fragt nur die API, laedt nichts
    download()          ->  holt die Exe in ein temporaeres Verzeichnis
    fetch_checksum()    ->  holt die veroeffentlichte SHA256
    verify()            ->  vergleicht, bevor irgendetwas ersetzt wird
    apply_update()      ->  tauscht die Datei aus
    spawn()             ->  startet die neue Version

Erst nach einer ausdruecklichen Bestaetigung im Dialog laeuft das durch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_API = "https://api.github.com/repos/{repo}/releases/latest"
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}$")

# Nur diese Hosts duerfen angefragt werden. Die Asset-URL stammt aus der
# API-Antwort und wird vor dem Abruf erneut geprueft -- GitHub leitet von dort
# auf seinen CDN weiter, weshalb zusaetzlich die Pruefsumme entscheidet.
_ALLOWED_HOSTS = frozenset({"api.github.com", "github.com"})
_ALLOWED_SCHEMES = frozenset({"https"})

_MAX_DOWNLOAD = 300 * 1024 * 1024
_MAX_JSON = 1024 * 1024
_MAX_CHECKSUM = 4096
_CHUNK = 256 * 1024
_USER_AGENT = "away-monitor-updater"
_SHA256_PATTERN = re.compile(r"\b([0-9a-fA-F]{64})\b")
_DETACHED_PROCESS = 0x00000008


class UpdateError(RuntimeError):
    """Fehler, der dem Nutzer gezeigt werden darf."""


@dataclass(frozen=True)
class Release:
    version: tuple[int, ...]
    tag: str
    notes: str
    page_url: str
    asset_name: str
    asset_url: str
    checksum_url: str | None

    @property
    def label(self) -> str:
        return ".".join(str(part) for part in self.version)


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Vorabkennungen wie '-beta' werden ignoriert,
    1.2.3-beta gilt also als identisch zu 1.2.3."""
    parts: list[int] = []
    for chunk in text.strip().lstrip("vV").split("."):
        match = re.match(r"\d+", chunk)
        if match is None:
            break
        parts.append(int(match.group()))
    return tuple(parts) if parts else (0,)


def is_frozen() -> bool:
    """True, wenn wir als gepackte Exe laufen -- nur dann ist ein Selbsttausch
    ueberhaupt sinnvoll."""
    return bool(getattr(sys, "frozen", False))


def current_executable() -> Path | None:
    return Path(sys.executable).resolve() if is_frozen() else None


def _open(url: str, timeout: float, accept: str):
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_SCHEMES or parsed.hostname not in _ALLOWED_HOSTS:
        raise UpdateError(f"Nicht erlaubte Update-URL: {url}")
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": _USER_AGENT}
    )
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 -- Schema geprueft


def _pick_asset(assets: list[dict], suffix: str) -> dict | None:
    for asset in assets:
        name = str(asset.get("name") or "")
        if name.lower().endswith(suffix) and asset.get("browser_download_url"):
            return asset
    return None


def check_for_update(repository: str, current_version: str,
                     timeout: float = 10.0) -> Release | None:
    """None heisst: kein Update, keine Konfiguration, oder Netz kaputt.
    Ein Fehler hier darf die App nie stoeren."""
    repository = repository.strip()
    if not repository:
        return None
    if not _REPO_PATTERN.match(repository):
        log.warning("Ungueltiges Repository %r -- erwartet 'besitzer/name'", repository)
        return None

    try:
        with _open(_API.format(repo=repository), timeout, "application/vnd.github+json") as r:
            payload = json.loads(r.read(_MAX_JSON).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, UpdateError) as error:
        log.warning("Updatepruefung fehlgeschlagen: %s", error)
        return None

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        log.warning("Release ohne tag_name -- ignoriert")
        return None

    latest = parse_version(tag)
    if latest <= parse_version(current_version):
        log.info("Kein Update noetig (installiert %s, neuestes Release %s)",
                 current_version, tag)
        return None

    assets = payload.get("assets") or []
    executable = _pick_asset(assets, ".exe")
    if executable is None:
        log.warning("Release %s enthaelt keine .exe -- ignoriert", tag)
        return None
    checksum = _pick_asset(assets, ".exe.sha256") or _pick_asset(assets, ".sha256")

    log.info("Update verfuegbar: %s (installiert %s)", tag, current_version)
    return Release(
        version=latest,
        tag=tag,
        notes=str(payload.get("body") or "").strip(),
        page_url=str(payload.get("html_url") or ""),
        asset_name=str(executable["name"]),
        asset_url=str(executable["browser_download_url"]),
        checksum_url=(str(checksum["browser_download_url"]) if checksum else None),
    )


def download(release: Release, target_dir: Path, timeout: float = 120.0) -> Path:
    target = target_dir / release.asset_name
    written = 0
    try:
        with _open(release.asset_url, timeout, "application/octet-stream") as response:
            with target.open("wb") as handle:
                while chunk := response.read(_CHUNK):
                    written += len(chunk)
                    if written > _MAX_DOWNLOAD:
                        raise UpdateError("Download ist unplausibel gross -- abgebrochen")
                    handle.write(chunk)
    except (urllib.error.URLError, OSError) as error:
        target.unlink(missing_ok=True)
        raise UpdateError(f"Download fehlgeschlagen: {error}") from error
    except UpdateError:
        target.unlink(missing_ok=True)
        raise
    log.info("Heruntergeladen: %s (%d Bytes)", target, written)
    return target


def fetch_checksum(release: Release, timeout: float = 20.0) -> str | None:
    """Liest die erste SHA256 aus der veroeffentlichten Pruefsummendatei."""
    if not release.checksum_url:
        return None
    try:
        with _open(release.checksum_url, timeout, "text/plain") as response:
            text = response.read(_MAX_CHECKSUM).decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, UpdateError) as error:
        log.warning("Pruefsumme nicht abrufbar: %s", error)
        return None
    match = _SHA256_PATTERN.search(text)
    if match is None:
        log.warning("Pruefsummendatei enthaelt keine SHA256")
        return None
    return match.group(1).lower()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected: str) -> bool:
    actual = sha256(path)
    if actual == expected.lower():
        return True
    log.error("Pruefsumme passt nicht!\n  erwartet: %s\n  bekommen: %s", expected, actual)
    return False


def _backup_path(current: Path) -> Path:
    return current.with_name(f"{current.stem}.old{current.suffix}")


def apply_update(downloaded: Path, current: Path) -> None:
    """Tauscht die laufende Exe aus.

    Windows laesst eine laufende Exe nicht loeschen -- aber umbenennen. Also
    erst zur Seite schieben, dann die neue an ihren Platz. Schlaegt der zweite
    Schritt fehl, wird der erste zurueckgenommen."""
    backup = _backup_path(current)
    try:
        backup.unlink(missing_ok=True)
    except OSError:
        log.debug("Alte Sicherung nicht loeschbar -- wird ueberschrieben", exc_info=True)

    try:
        current.rename(backup)
    except OSError as error:
        raise UpdateError(f"Konnte {current.name} nicht zur Seite schieben: {error}") from error

    try:
        downloaded.replace(current)
    except OSError as error:
        try:
            backup.rename(current)
            log.info("Update zurueckgerollt, alte Version ist wieder aktiv")
        except OSError:
            log.exception("Rollback fehlgeschlagen -- %s liegt noch als %s",
                          current.name, backup.name)
        raise UpdateError(f"Konnte neue Version nicht einsetzen: {error}") from error

    log.info("Update eingesetzt: %s -> %s", downloaded.name, current.name)


def cleanup_previous(current: Path | None) -> None:
    """Beim Start die zur Seite geschobene Vorversion wegraeumen."""
    if current is None:
        return
    backup = _backup_path(current)
    if not backup.exists():
        return
    try:
        backup.unlink()
        log.info("Vorversion entfernt: %s", backup.name)
    except OSError:
        log.debug("Vorversion noch gesperrt, naechster Start versucht es erneut",
                  exc_info=True)


def spawn(executable: Path) -> None:
    """Startet die neue Version losgeloest -- der Aufrufer beendet sich danach."""
    subprocess.Popen(  # noqa: S603 -- fester Pfad, keine Shell
        [str(executable)],
        cwd=str(executable.parent),
        close_fds=True,
        creationflags=_DETACHED_PROCESS,
    )
    log.info("Neue Version gestartet: %s", executable)
