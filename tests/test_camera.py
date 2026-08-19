"""Kamera-Logik gegen ein Fake-cv2: Backoff und Aufwaermphase."""

from __future__ import annotations

import unittest
from unittest import mock

from away_monitor.camera import Camera


class FakeClock:
    def __init__(self) -> None:
        self.now = 500.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FailingCapture:
    attempts = 0

    def __init__(self, *_args) -> None:
        FailingCapture.attempts += 1

    def isOpened(self) -> bool:  # noqa: N802 -- cv2-Namensgebung
        return False

    def release(self) -> None:
        pass


class WorkingCapture:
    def __init__(self, *_args) -> None:
        pass

    def isOpened(self) -> bool:  # noqa: N802
        return True

    def set(self, *_args) -> bool:
        return True

    def grab(self) -> bool:
        return True

    def retrieve(self):
        return True, "frame"

    def release(self) -> None:
        pass


class OpenBackoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        FailingCapture.attempts = 0
        patches = [
            mock.patch("away_monitor.camera.time", self.clock),
            mock.patch("away_monitor.camera.cv2.VideoCapture", FailingCapture),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_fehlschlag_pausiert_weitere_versuche(self) -> None:
        camera = Camera(index=0, backends=("dshow", "msmf"), open_retry_seconds=5.0)

        self.assertFalse(camera.open())
        self.assertEqual(FailingCapture.attempts, 2, "beide Backends einmal probiert")

        # Waehrend der Sperrfrist darf gar nichts passieren.
        for _ in range(20):
            self.clock.advance(0.2)
            self.assertFalse(camera.open())
        self.assertEqual(FailingCapture.attempts, 2)

        self.clock.advance(2.0)  # jetzt ist die Sperrfrist vorbei
        self.assertFalse(camera.open())
        self.assertEqual(FailingCapture.attempts, 4)


class WarmupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        patches = [
            mock.patch("away_monitor.camera.time", self.clock),
            mock.patch("away_monitor.camera.cv2.VideoCapture", WorkingCapture),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_warm_erst_nach_zeit_und_bildern(self) -> None:
        camera = Camera(index=0, backends=("dshow",), warmup_seconds=1.5, warmup_frames=5)
        self.assertTrue(camera.open())
        self.assertFalse(camera.is_warm, "direkt nach dem Oeffnen nie warm")

        for _ in range(5):  # genug Bilder, aber zu frueh
            camera.read()
        self.assertFalse(camera.is_warm)

        self.clock.advance(2.0)  # Zeit erfuellt, Bilder auch
        self.assertTrue(camera.is_warm)

    def test_zu_wenige_bilder_bleiben_kalt(self) -> None:
        camera = Camera(index=0, backends=("dshow",), warmup_seconds=1.5, warmup_frames=5)
        camera.open()
        self.clock.advance(10.0)
        camera.read()
        camera.read()
        self.assertFalse(camera.is_warm, "Zeit allein reicht nicht")

    def test_release_setzt_sperrfrist_zurueck(self) -> None:
        camera = Camera(index=0, backends=("dshow",))
        camera.open()
        camera.release()
        self.assertFalse(camera.is_open)
        self.assertTrue(camera.open(), "nach release sofort wieder oeffenbar")


if __name__ == "__main__":
    unittest.main(verbosity=2)
