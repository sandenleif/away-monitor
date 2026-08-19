"""Einstiegspunkt: Konfiguration laden, Threads starten, Tk im Hauptthread halten."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import shutil
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

from . import __version__
from . import config as config_module
from . import updater, winapi
from .camera import Camera
from .detector import FaceDetector
from .monitor import Monitor
from .tray import Tray
from .ui import UiCallbacks, UiHost

log = logging.getLogger("away_monitor")

_LOG_BYTES = 512_000
_LOG_BACKUPS = 2
_CHECK_FRAMES = 15
_CHECK_TIMEOUT = 12.0
_MUTEX_NAME = "away-monitor-single-instance"
_UPDATE_START_DELAY = 8.0  # erst laufen lassen, dann im Hintergrund nachsehen


def _report(text: str = "") -> None:
    """Ausgabe fuer Konsole *und* Log -- die gepackte Exe hat keine Konsole,
    dort waere das Ergebnis von --check sonst unsichtbar."""
    print(text)
    if text.strip():
        log.info("%s", text.rstrip())


def _setup_logging(cfg: config_module.Config, verbose: bool) -> None:
    level = logging.DEBUG if verbose else getattr(logging, cfg.log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            cfg.log_file, maxBytes=_LOG_BYTES, backupCount=_LOG_BACKUPS, encoding="utf-8"
        )
    ]
    if sys.stderr is not None:  # unter pythonw.exe gibt es keine Konsole
        handlers.append(logging.StreamHandler(sys.stderr))
    # Root bleibt auf WARNING, damit PIL/comtypes das Log nicht zumuellen; nur
    # unsere eigenen Logger laufen auf der konfigurierten Stufe.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("away_monitor").setLevel(level)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="away-monitor",
        description="Sperrt Windows, wenn die Kamera niemanden mehr vor dem Rechner sieht.",
    )
    parser.add_argument("--config", type=Path, default=config_module.CONFIG_PATH,
                        help="Pfad zur config.toml")
    parser.add_argument("--live", action="store_true",
                        help="Live-Ansicht direkt beim Start oeffnen")
    parser.add_argument("--sticky", action="store_true",
                        help="Notizzettel direkt beim Start einblenden")
    parser.add_argument("--dry-run", action="store_true",
                        help="nur protokollieren statt wirklich zu sperren")
    parser.add_argument("--check", action="store_true",
                        help="Kamera und Erkennung einmal pruefen und beenden")
    parser.add_argument("--check-update", action="store_true",
                        help="einmal nach einem Update sehen und beenden")
    parser.add_argument("--version", action="version", version=f"away-monitor {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Logging")
    return parser.parse_args(argv)


def _check(cfg: config_module.Config) -> int:
    """Einmaliger Selbsttest -- beantwortet 'warum reagiert das Ding nicht?'."""
    _report(f"Modell:  {cfg.model}")
    try:
        detector = FaceDetector(cfg.model, cfg.score_threshold)
    except FileNotFoundError as error:
        _report(f"  FEHLER: {error}")
        return 2
    _report("  ok")

    _report(f"Kamera:  Index {cfg.camera_index}, Backends {', '.join(cfg.backends)}")
    camera = Camera(
        index=cfg.camera_index, backends=cfg.backends,
        warmup_seconds=cfg.warmup_seconds, warmup_frames=cfg.warmup_frames,
    )
    if not camera.open():
        _report("  FEHLER: kein Backend konnte die Kamera oeffnen.")
        if winapi.instance_is_running(_MUTEX_NAME):
            _report("  Es laeuft bereits eine away-monitor-Instanz -- die haelt die Kamera")
            _report("  exklusiv. Erst ueber das Tray-Icon beenden, dann erneut pruefen.")
        else:
            _report("  Belegt eine andere App (Teams, Zoom) die Kamera? Kamerazugriff in den")
            _report("  Windows-Datenschutzeinstellungen fuer Desktop-Apps erlaubt?")
        return 3
    _report("  geoeffnet")

    # Nur aufgewaermte Bilder zaehlen -- die ersten Frames nach dem Oeffnen sind
    # oft schwarz und wuerden das Ergebnis systematisch nach unten ziehen.
    hits = evaluated = 0
    deadline = time.monotonic() + _CHECK_TIMEOUT
    while evaluated < _CHECK_FRAMES and time.monotonic() < deadline:
        frame = camera.read()
        if frame is None or not camera.is_warm:
            time.sleep(0.1)
            continue
        evaluated += 1
        if detector.detect(frame):
            hits += 1
        time.sleep(0.1)
    camera.release()

    if evaluated == 0:
        _report("  FEHLER: kein verwertbares Bild -- Kamera liefert nichts.")
        return 3
    _report(f"Erkennung: {hits} von {evaluated} ausgewerteten Bildern mit Gesicht")
    _report(f"Sitzung:   {'gesperrt' if winapi.is_session_locked() else 'entsperrt'}, "
          f"Leerlauf {winapi.idle_seconds():.1f} s")
    if hits == 0:
        _report("\nKein Gesicht erkannt. Sitzt du gerade davor? Dann hilft meist:")
        _report("  - mehr Licht von vorn (Gegenlicht ist der haeufigste Grund)")
        _report("  - score_threshold senken -- am besten in der Live-Ansicht (--live)")
        return 4
    _report("\nAlles in Ordnung.")
    return 0


def _check_update_only(cfg: config_module.Config) -> int:
    _report(f"Installiert: {__version__}")
    if not cfg.update_repository:
        _report("Kein Repository konfiguriert -- [update] repository in der config.toml setzen.")
        return 1
    _report(f"Repository:  {cfg.update_repository}")
    release = updater.check_for_update(cfg.update_repository, __version__)
    if release is None:
        _report("Kein Update verfuegbar (oder nicht erreichbar -- siehe Log).")
        return 0
    _report(f"Verfuegbar:  {release.label} ({release.tag})")
    _report(f"Datei:       {release.asset_name}")
    _report(f"Pruefsumme:  {'ja' if release.checksum_url else 'NEIN -- wird nicht installiert'}")
    _report(f"Seite:       {release.page_url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = config_module.load(args.config)
    _setup_logging(cfg, args.verbose)

    if args.check:
        return _check(cfg)
    if args.check_update:
        return _check_update_only(cfg)

    # Zwei Instanzen vertragen sich nicht: DirectShow gibt die Kamera exklusiv
    # heraus, die zweite bekaeme nie ein Bild und wuerde nur stoeren.
    if not winapi.claim_single_instance(_MUTEX_NAME):
        log.warning("away-monitor laeuft bereits -- dieser Start endet hier")
        _report("away-monitor laeuft bereits (siehe Infobereich der Taskleiste).")
        return 0

    log.info("away-monitor %s startet%s", __version__, " (dry-run)" if args.dry_run else "")
    # Reste eines vorherigen Updates wegraeumen, solange nichts sie sperrt.
    updater.cleanup_previous(updater.current_executable())

    # monitor und tray entstehen erst weiter unten; die Callbacks werden aber
    # schon fuer den UiHost gebraucht und laufen ohnehin erst nach dem Start.
    monitor: Monitor | None = None
    tray: Tray | None = None

    def set_paused(want_paused: bool) -> None:
        if monitor is not None and monitor.paused != want_paused:
            monitor.toggle_pause()

    def toggle_preview(enabled: bool) -> None:
        if monitor is None:
            return
        monitor.set_preview_enabled(enabled)
        if enabled:
            ui.open_preview()
        else:
            ui.close_preview()
        if tray is not None:
            tray.refresh_menu()

    def toggle_sticky(enabled: bool) -> None:
        if monitor is None:
            return
        monitor.set_sticky_enabled(enabled)
        if enabled:
            ui.open_sticky()
        else:
            ui.close_sticky()
        config_module.save_sticky(enabled=enabled, path=args.config)
        if tray is not None:
            tray.refresh_menu()

    def sticky_moved(x: int, y: int) -> None:
        config_module.save_sticky(x=x, y=y, path=args.config)

    def preview_closed() -> None:
        if monitor is not None:
            monitor.set_preview_enabled(False)
        if tray is not None:
            tray.refresh_menu()

    ui = UiHost(
        UiCallbacks(
            on_present=lambda: monitor.mark_present() if monitor else None,
            on_threshold=lambda value: monitor.set_score_threshold(value) if monitor else None,
            on_threshold_save=lambda value: config_module.save_score_threshold(value, args.config),
            on_pause_toggle=set_paused,
            on_preview_closed=preview_closed,
            on_sticky_moved=sticky_moved,
        ),
        preview_max_width=cfg.preview_max_width,
        sticky_position=(cfg.sticky_x, cfg.sticky_y),
        sticky_opacity=cfg.sticky_opacity,
    )

    try:
        monitor = Monitor(cfg, ui, dry_run=args.dry_run)
    except FileNotFoundError as error:
        log.error("%s", error)
        print(error, file=sys.stderr)
        return 2

    def shutdown() -> None:
        log.info("Beenden angefordert")
        monitor.stop()
        tray.stop()
        ui.quit()

    # ----------------------------------------------------------------- Update
    def check_updates(manual: bool) -> None:
        """Laeuft im Hintergrund -- ein Netzfehler darf die App nie aufhalten."""
        if not cfg.update_repository:
            if manual:
                ui.show_message(
                    "away-monitor",
                    "Es ist kein GitHub-Repository eingetragen.\n\n"
                    "In der config.toml unter [update] repository = \"besitzer/name\" "
                    "setzen und die App neu starten.",
                )
            return
        release = updater.check_for_update(cfg.update_repository, __version__)
        if release is None:
            if manual:
                ui.show_message(
                    "away-monitor",
                    f"Du hast bereits die neueste Version ({__version__}).",
                )
            return
        ui.offer_update(release, __version__, lambda: _start_install(release))

    def _start_install(release) -> None:
        # Aus dem Tk-Thread heraus aufgerufen -- Download gehoert nicht dorthin.
        threading.Thread(target=_install, args=(release,), name="update",
                         daemon=True).start()

    def _install(release) -> None:
        executable = updater.current_executable()
        if executable is None:
            ui.show_message(
                "away-monitor",
                "Aus dem Quellcode gestartet -- hier gibt es nichts auszutauschen.\n\n"
                "Die Release-Seite wird im Browser geoeffnet.",
            )
            if release.page_url:
                webbrowser.open(release.page_url)
            return
        try:
            staged = executable.with_name(f"{executable.stem}.new{executable.suffix}")
            with tempfile.TemporaryDirectory() as tmp:
                downloaded = updater.download(release, Path(tmp))
                checksum = updater.fetch_checksum(release)
                if checksum is None:
                    if cfg.update_require_checksum:
                        raise updater.UpdateError(
                            "Zu diesem Release ist keine SHA256-Pruefsumme veroeffentlicht.\n"
                            "Es wird nichts installiert."
                        )
                    log.warning("Keine Pruefsumme vorhanden -- Installation trotzdem erlaubt")
                elif not updater.verify(downloaded, checksum):
                    raise updater.UpdateError(
                        "Die Pruefsumme der geladenen Datei stimmt nicht.\n"
                        "Es wird nichts installiert."
                    )
                # Neben die Exe holen, bevor das Temp-Verzeichnis verschwindet:
                # ein Umbenennen ueber Laufwerksgrenzen hinweg schlaegt fehl.
                shutil.move(str(downloaded), str(staged))

            updater.apply_update(staged, executable)
            updater.spawn(executable)
        except updater.UpdateError as error:
            log.error("Update abgebrochen: %s", error)
            ui.show_message("Update fehlgeschlagen", str(error))
            return
        except OSError as error:
            log.exception("Update fehlgeschlagen")
            ui.show_message("Update fehlgeschlagen", str(error))
            return
        shutdown()

    tray = Tray(monitor, args.config, cfg.log_file,
                on_quit=shutdown, on_preview_toggle=toggle_preview,
                on_check_updates=lambda: threading.Thread(
                    target=check_updates, args=(True,), name="update-check", daemon=True
                ).start(),
                on_sticky_toggle=toggle_sticky)
    monitor.set_state_listener(tray.set_state)
    monitor.set_preview_listener(ui.push_snapshot)

    monitor.start()
    tray.start()
    if args.live:
        toggle_preview(True)
    if args.sticky or cfg.sticky_enabled:
        toggle_sticky(True)
    if cfg.update_check_on_start and cfg.update_repository:
        timer = threading.Timer(_UPDATE_START_DELAY, check_updates, args=(False,))
        timer.daemon = True
        timer.start()

    try:
        ui.run()
    except KeyboardInterrupt:
        shutdown()
    monitor.stop()
    monitor.join(timeout=3.0)
    tray.stop()
    log.info("away-monitor beendet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
