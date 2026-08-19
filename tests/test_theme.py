"""Gestaltungsgrundlage und die selbstgezeichneten Bedienelemente.

Alles hier laeuft ohne Fenster: die Bildfunktionen sind reine PIL-Aufrufe.
"""

from __future__ import annotations

import unittest

from away_monitor import theme, widgets
from away_monitor.ui import clamp_to_screens
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



class TrayColorTest(unittest.TestCase):
    """Die Tray-Farben kommen aus theme.STATE_COLORS -- das ist mit den
    Beschriftungen indiziert, nicht mit den Enum-Mitgliedern. Genau daran ist
    der Start einmal zerbrochen."""

    def test_jeder_zustand_findet_seine_theme_farbe(self) -> None:
        from away_monitor.tray import state_color

        for state in State:
            self.assertEqual(state_color(state), theme.STATE_COLORS[state.value],
                             state.name)

    def test_die_aktiven_zustaende_sind_unterscheidbar(self) -> None:
        from away_monitor.tray import state_color

        colors = {state_color(s) for s in (State.ACTIVE, State.WATCHING, State.WARNING)}
        self.assertEqual(len(colors), 3, "sonst sieht man im Tray keinen Unterschied")

    def test_symbol_laesst_sich_fuer_jeden_zustand_zeichnen(self) -> None:
        from away_monitor.icon import render
        from away_monitor.tray import state_color

        for state in State:
            image = render(state_color(state), state is State.PAUSED)
            self.assertEqual(image.size, (64, 64), state.name)


class TrayConstructionTest(unittest.TestCase):
    """Der Absturz lag im Konstruktor -- also wird er gebaut."""

    def test_tray_laesst_sich_anlegen(self) -> None:
        from pathlib import Path
        from unittest import mock

        from away_monitor.tray import Tray

        monitor = mock.Mock()
        monitor.state = State.ACTIVE
        monitor.note = ""
        monitor.paused = False
        monitor.preview_enabled = False
        monitor.sticky_enabled = False

        noop = lambda *_a, **_k: None  # noqa: E731
        tray = Tray(monitor, Path("config.toml"), Path("away-monitor.log"),
                    on_quit=noop, on_preview_toggle=noop, on_check_updates=noop,
                    on_sticky_toggle=noop)
        self.assertIsNotNone(tray)
        # Statuszeile und Zustandswechsel laufen ueber dieselbe Farbtabelle.
        self.assertIn("aktiv", tray._status_text(None))


class ScreenClampTest(unittest.TestCase):
    """Mehrere Bildschirme: links oder oberhalb des Hauptbildschirms sind die
    Koordinaten negativ. Gegen 0 geklemmt springt ein Fenster von dort bei
    jedem Start zurueck -- beim Autostart also taeglich."""

    # Drei Monitore nebeneinander, der Hauptbildschirm in der Mitte.
    BOUNDS = (-2048, 0, 6144, 1152)

    def test_position_auf_dem_linken_monitor_bleibt(self) -> None:
        self.assertEqual(clamp_to_screens(-2044, 7, 224, 62, self.BOUNDS), (-2044, 7))

    def test_position_auf_dem_rechten_monitor_bleibt(self) -> None:
        self.assertEqual(clamp_to_screens(3000, 500, 224, 62, self.BOUNDS), (3000, 500))

    def test_zu_weit_links_landet_am_rand(self) -> None:
        self.assertEqual(clamp_to_screens(-99999, 0, 224, 62, self.BOUNDS), (-2048, 0))

    def test_zu_weit_rechts_bleibt_ganz_sichtbar(self) -> None:
        x, y = clamp_to_screens(99999, 99999, 224, 62, self.BOUNDS)
        self.assertEqual(x, -2048 + 6144 - 224)
        self.assertEqual(y, 1152 - 62)

    def test_einzelner_bildschirm_verhaelt_sich_wie_frueher(self) -> None:
        bounds = (0, 0, 1920, 1080)
        self.assertEqual(clamp_to_screens(-50, -50, 224, 62, bounds), (0, 0))
        self.assertEqual(clamp_to_screens(100, 100, 224, 62, bounds), (100, 100))


if __name__ == "__main__":
    unittest.main(verbosity=2)
