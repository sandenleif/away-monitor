"""Zustandsautomat gegen Fakes -- sperrt nie wirklich, laeuft an einer Fake-Uhr."""

from __future__ import annotations

import unittest
from unittest import mock

from away_monitor.config import Config
from away_monitor.detector import Face
from away_monitor.monitor import Monitor, State


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeCamera:
    def __init__(self, *, can_open: bool = True, warm: bool = True) -> None:
        self.can_open = can_open
        self.warm = warm
        self.is_open = False
        self.releases = 0

    def open(self) -> bool:
        self.is_open = self.can_open
        return self.can_open

    def read(self):
        return "frame" if self.is_open else None

    @property
    def is_warm(self) -> bool:
        return self.is_open and self.warm

    def release(self) -> None:
        if self.is_open:
            self.releases += 1
        self.is_open = False


class FakeDetector:
    def __init__(self) -> None:
        self.faces = 1
        self.score_threshold = 0.6

    def detect(self, _frame) -> list[Face]:
        return [Face(10, 20, 30, 40, 0.9) for _ in range(self.faces)]


class Recorder:
    """Sammelt die Schnappschuesse, die der Monitor an die Live-Ansicht schickt."""

    def __init__(self) -> None:
        self.snapshots: list = []

    def __call__(self, snapshot) -> None:
        self.snapshots.append(snapshot)


class FakeUI:
    def __init__(self) -> None:
        self.shown = 0
        self.hidden = 0
        self.last_remaining: float | None = None

    def show_warning(self, remaining: float) -> None:
        self.shown += 1
        self.last_remaining = remaining

    def update_warning(self, remaining: float) -> None:
        self.last_remaining = remaining

    def hide_warning(self) -> None:
        self.hidden += 1


CONFIG = Config(
    idle_before_camera=5.0,
    absence_grace=3.0,
    warning_seconds=2.0,
    tick_seconds=0.5,
    release_when_active=True,
)


class MonitorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.camera = FakeCamera()
        self.detector = FakeDetector()
        self.ui = FakeUI()
        self.idle = 0.0
        self.locked_calls = 0

        self.winapi = mock.Mock()
        self.winapi.idle_seconds.side_effect = lambda: self.idle
        self.winapi.is_session_locked.side_effect = lambda: False
        self.winapi.lock_workstation.side_effect = self._fake_lock

        patches = [
            mock.patch("away_monitor.monitor.time", self.clock),
            mock.patch("away_monitor.monitor.winapi", self.winapi),
            mock.patch("away_monitor.monitor.Camera", lambda **_kw: self.camera),
            mock.patch("away_monitor.monitor.FaceDetector", lambda *_a, **_kw: self.detector),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _fake_lock(self) -> bool:
        self.locked_calls += 1
        return True

    def _monitor(self, config: Config = CONFIG) -> Monitor:
        return Monitor(config, self.ui)

    def _run(self, monitor: Monitor, seconds: float, step: float = 0.5) -> None:
        for _ in range(int(seconds / step)):
            self.clock.advance(step)
            monitor._tick()

    # ------------------------------------------------------------------ Faelle
    def test_eingabe_haelt_wach_und_gibt_kamera_frei(self) -> None:
        monitor = self._monitor()
        self.idle = 1.0
        self._run(monitor, 30)
        self.assertIs(monitor.state, State.ACTIVE)
        self.assertEqual(self.locked_calls, 0)
        self.assertFalse(self.camera.is_open)

    def test_gesicht_vor_kamera_verhindert_sperre(self) -> None:
        monitor = self._monitor()
        self.idle = 600.0
        self.detector.faces = 1
        self._run(monitor, 120)
        self.assertIs(monitor.state, State.WATCHING)
        self.assertEqual(self.locked_calls, 0)
        self.assertEqual(self.ui.shown, 0)

    def test_niemand_da_fuehrt_ueber_warnung_zur_sperre(self) -> None:
        monitor = self._monitor()
        self.idle = 600.0
        self.detector.faces = 0

        self._run(monitor, 3.5)
        self.assertIs(monitor.state, State.WARNING)
        self.assertEqual(self.ui.shown, 1)
        self.assertEqual(self.locked_calls, 0)

        self._run(monitor, 2.5)
        self.assertEqual(self.locked_calls, 1)
        self.assertIs(monitor.state, State.LOCKED)
        self.assertFalse(self.camera.is_open, "Kamera muss beim Sperren frei sein")

    def test_rueckkehr_waehrend_countdown_bricht_ab(self) -> None:
        monitor = self._monitor()
        self.idle = 600.0
        self.detector.faces = 0
        self._run(monitor, 3.5)
        self.assertIs(monitor.state, State.WARNING)

        self.detector.faces = 1
        self._run(monitor, 1.0)
        self.assertIs(monitor.state, State.WATCHING)
        self.assertEqual(self.locked_calls, 0)
        self.assertGreaterEqual(self.ui.hidden, 1)

    def test_aufwaermphase_zaehlt_nicht_als_abwesenheit(self) -> None:
        monitor = self._monitor()
        self.idle = 600.0
        self.camera.warm = False
        self.detector.faces = 0
        self._run(monitor, 60)
        self.assertEqual(self.locked_calls, 0)
        self.assertIs(monitor.state, State.WATCHING)

    def test_belegte_kamera_sperrt_per_default_nicht(self) -> None:
        self.camera.can_open = False
        monitor = self._monitor()
        self.idle = 600.0
        self._run(monitor, 60)
        self.assertEqual(self.locked_calls, 0)

    def test_belegte_kamera_sperrt_wenn_so_konfiguriert(self) -> None:
        self.camera.can_open = False
        from dataclasses import replace

        monitor = self._monitor(replace(CONFIG, on_camera_error="lock"))
        self.idle = 600.0
        self._run(monitor, 10)
        self.assertEqual(self.locked_calls, 1)

    def test_pause_stoppt_alles(self) -> None:
        monitor = self._monitor()
        monitor.toggle_pause()
        self.idle = 600.0
        self.detector.faces = 0
        self._run(monitor, 60)
        self.assertIs(monitor.state, State.PAUSED)
        self.assertEqual(self.locked_calls, 0)

    def test_gesperrte_sitzung_loest_nicht_erneut_aus(self) -> None:
        monitor = self._monitor()
        self.winapi.is_session_locked.side_effect = lambda: True
        self.idle = 600.0
        self.detector.faces = 0
        self._run(monitor, 60)
        self.assertEqual(self.locked_calls, 0)
        self.assertIs(monitor.state, State.LOCKED)

    def test_ich_bin_da_setzt_timer_zurueck(self) -> None:
        monitor = self._monitor()
        self.idle = 600.0
        self.detector.faces = 0
        self._run(monitor, 3.5)
        self.assertIs(monitor.state, State.WARNING)

        monitor.mark_present()
        self._run(monitor, 1.0)
        self.assertIs(monitor.state, State.WATCHING)
        self.assertEqual(self.locked_calls, 0)

    # ------------------------------------------------------------ Live-Ansicht
    def test_live_ansicht_haelt_kamera_offen_trotz_eingabe(self) -> None:
        monitor = self._monitor()
        recorder = Recorder()
        monitor.set_preview_listener(recorder)
        monitor.set_preview_enabled(True)

        self.idle = 0.0  # der Nutzer tippt -- ohne Vorschau waere die Kamera aus
        self._run(monitor, 5)

        self.assertIs(monitor.state, State.ACTIVE)
        self.assertTrue(self.camera.is_open, "Vorschau braucht laufende Bilder")
        self.assertGreater(len(recorder.snapshots), 0)
        self.assertEqual(self.locked_calls, 0)

    def test_ohne_live_ansicht_keine_schnappschuesse(self) -> None:
        monitor = self._monitor()
        recorder = Recorder()
        monitor.set_preview_listener(recorder)  # aber nicht eingeschaltet

        self.idle = 600.0
        self._run(monitor, 5)

        self.assertEqual(recorder.snapshots, [], "ohne offene Ansicht nichts senden")

    def test_schnappschuss_traegt_boxen_und_countdown(self) -> None:
        monitor = self._monitor()
        recorder = Recorder()
        monitor.set_preview_listener(recorder)
        monitor.set_preview_enabled(True)

        self.idle = 600.0
        self.detector.faces = 2
        self._run(monitor, 2)
        with_faces = recorder.snapshots[-1]
        self.assertEqual(len(with_faces.faces), 2)
        self.assertEqual(with_faces.faces[0].score, 0.9)
        self.assertIsNone(with_faces.countdown)
        self.assertAlmostEqual(with_faces.idle_seconds, 600.0)

        self.detector.faces = 0
        self._run(monitor, 3.5)
        warning = recorder.snapshots[-1]
        self.assertIs(warning.state, State.WARNING)
        self.assertIsNotNone(warning.countdown)
        self.assertGreater(warning.countdown, 0.0)
        self.assertEqual(len(warning.faces), 0)

    def test_pausiert_plus_live_ansicht_zeigt_weiter_bild(self) -> None:
        monitor = self._monitor()
        recorder = Recorder()
        monitor.set_preview_listener(recorder)
        monitor.set_preview_enabled(True)
        monitor.toggle_pause()

        self.idle = 600.0
        self.detector.faces = 0
        self._run(monitor, 30)

        self.assertIs(monitor.state, State.PAUSED)
        self.assertEqual(self.locked_calls, 0, "im Einstellmodus wird nie gesperrt")
        self.assertTrue(self.camera.is_open)
        self.assertGreater(len(recorder.snapshots), 0)

    def test_takt_folgt_der_live_ansicht(self) -> None:
        from dataclasses import replace

        config = replace(CONFIG, tick_seconds=0.5, preview_tick_seconds=0.1)
        monitor = self._monitor(config)
        self.assertAlmostEqual(monitor._interval(), 0.5)
        monitor.set_preview_enabled(True)
        self.assertAlmostEqual(monitor._interval(), 0.1)

    def test_schwelle_geht_an_den_detektor(self) -> None:
        monitor = self._monitor()
        monitor.set_score_threshold(0.35)
        self.assertAlmostEqual(self.detector.score_threshold, 0.35)
        self.assertAlmostEqual(monitor.score_threshold, 0.35)

    def test_manuelles_sperren(self) -> None:
        monitor = self._monitor()
        self.idle = 0.0
        monitor.lock_now()
        self._run(monitor, 0.5)
        self.assertEqual(self.locked_calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
