"""Der echte Detektor -- braucht das ONNX-Modell, sonst wird uebersprungen."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from away_monitor.detector import FaceDetector

MODEL = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"


@unittest.skipUnless(MODEL.is_file(), f"Modell fehlt: {MODEL}")
class DetectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.detector = FaceDetector(MODEL, 0.6)

    def test_leeres_bild_liefert_keine_gesichter(self) -> None:
        black = np.zeros((240, 320, 3), dtype=np.uint8)
        self.assertEqual(self.detector.detect(black), [])

    def test_schwelle_wird_geklemmt(self) -> None:
        self.detector.score_threshold = 9.0
        self.assertAlmostEqual(self.detector.score_threshold, 0.95)
        self.detector.score_threshold = -1.0
        self.assertAlmostEqual(self.detector.score_threshold, 0.05)

    def test_wechselnde_bildgroesse_bringt_ihn_nicht_aus_dem_tritt(self) -> None:
        for width, height in [(320, 240), (640, 480), (320, 240)]:
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            self.assertEqual(self.detector.detect(frame), [])


class MissingModelTest(unittest.TestCase):
    def test_fehlendes_modell_nennt_den_ausweg(self) -> None:
        with self.assertRaises(FileNotFoundError) as caught:
            FaceDetector(Path("gibt/es/nicht.onnx"))
        self.assertIn("fetch_model.py", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class DataRootTest(unittest.TestCase):
    """Der Ausweichpfad, wenn neben der Exe nicht geschrieben werden darf."""

    def test_schreibtest_erkennt_beschreibbar(self) -> None:
        import tempfile

        from away_monitor.config import _is_writable

        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(_is_writable(Path(tmp)))

    def test_schreibtest_bei_fehlendem_ordner(self) -> None:
        from away_monitor.config import _is_writable

        self.assertFalse(_is_writable(Path("Z:/gibt/es/nicht/hoffentlich")))
