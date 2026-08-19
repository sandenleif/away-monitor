"""Gestaltungsgrundlage und die selbstgezeichneten Bedienelemente.

Alles hier laeuft ohne Fenster: die Bildfunktionen sind reine PIL-Aufrufe.
"""

from __future__ import annotations

import unittest

from away_monitor import theme, widgets
from away_monitor.monitor import State


class ColorTest(unittest.TestCase):
    def test_jeder_zustand_hat_eine_farbe(self) -> None:
        """Ein neuer Zustand ohne Farbe faellt sonst nur im Betrieb auf --
        und zwar als grauer Punkt, den niemand als Fehler erkennt."""
        for state in State:
            self.assertIn(state.value, theme.STATE_COLORS, state.name)

    def test_farben_sind_hexwerte(self) -> None:
        for name, value in theme.STATE_COLORS.items():
            self.assertRegex(value, r"^#[0-9a-fA-F]{6}$", name)

    def test_mix_an_den_raendern(self) -> None:
        self.assertEqual(theme.mix("#000000", "#ffffff", 0.0), "#000000")
        self.assertEqual(theme.mix("#000000", "#ffffff", 1.0), "#ffffff")

    def test_mix_in_der_mitte(self) -> None:
        self.assertEqual(theme.mix("#000000", "#ffffff", 0.5), "#808080")

    def test_mix_klemmt_ausreisser(self) -> None:
        self.assertEqual(theme.mix("#000000", "#ffffff", -2.0), "#000000")
        self.assertEqual(theme.mix("#000000", "#ffffff", 9.0), "#ffffff")

    def test_schrift_faellt_zurueck_ohne_tk(self) -> None:
        """Ohne Tk-Root ist keine Schriftliste abfragbar -- es muss trotzdem
        ein brauchbarer Name herauskommen."""
        name, size, weight = theme.font(11, "bold")
        self.assertTrue(name)
        self.assertEqual((size, weight), (11, "bold"))


class ImageTest(unittest.TestCase):
    def test_rundes_rechteck_hat_die_bestellte_groesse(self) -> None:
        image = widgets.rounded_image(120, 40, 8, theme.ACCENT, theme.SURFACE)
        self.assertEqual(image.size, (120, 40))
        self.assertEqual(image.mode, "RGB", "kein Alphakanal -- Tk komponiert sonst falsch")

    def test_rundes_rechteck_ist_innen_gefuellt_und_aussen_hintergrund(self) -> None:
        image = widgets.rounded_image(120, 40, 12, "#ff0000", "#0000ff")
        self.assertEqual(image.getpixel((60, 20)), (255, 0, 0), "Mitte ist gefuellt")
        corner = image.getpixel((0, 0))
        self.assertGreater(corner[2], corner[0], "die Ecke bleibt Hintergrund")

    def test_ring_fuellt_sich_mit_dem_anteil(self) -> None:
        empty = widgets.ring_image(64, 0.0, "#ff0000", "#202020", "#000000")
        full = widgets.ring_image(64, 1.0, "#ff0000", "#202020", "#000000")
        self.assertEqual(empty.size, (64, 64))

        def red_pixels(image) -> int:
            return sum(1 for pixel in image.getdata() if pixel[0] > 120 and pixel[1] < 90)

        self.assertEqual(red_pixels(empty), 0, "bei 0 ist nichts eingefaerbt")
        self.assertGreater(red_pixels(full), 100, "bei 1 laeuft der Ring rundherum")

    def test_ring_klemmt_werte_ausserhalb(self) -> None:
        for fraction in (-0.5, 1.7):
            image = widgets.ring_image(48, fraction, "#ff0000", "#202020", "#000000")
            self.assertEqual(image.size, (48, 48))

    def test_punkt_traegt_die_farbe(self) -> None:
        image = widgets.dot_image(16, "#00ff00", "#000000")
        self.assertEqual(image.size, (16, 16))
        self.assertGreater(image.getpixel((8, 8))[1], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
