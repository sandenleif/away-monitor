"""Sichert die 32-Bit-Tick-Arithmetik ab -- der Ueberlauf nach 49,7 Tagen Uptime
ist der eine Fall, den man beim Testen sonst nie sieht."""

from __future__ import annotations

import unittest
from unittest import mock

from away_monitor import winapi


def _fake_last_input(tick_value: int, ok: bool = True):
    def implementation(pointer):
        if ok:
            pointer._obj.dwTime = tick_value
        return 1 if ok else 0

    return implementation


class IdleSecondsTest(unittest.TestCase):
    def _idle(self, last_input: int, tick: int, ok: bool = True) -> float:
        with (
            mock.patch.object(winapi._user32, "GetLastInputInfo", _fake_last_input(last_input, ok)),
            mock.patch.object(winapi._kernel32, "GetTickCount", lambda: tick),
        ):
            return winapi.idle_seconds()

    def test_normalfall(self) -> None:
        self.assertAlmostEqual(self._idle(1_000, 6_000), 5.0)

    def test_ueberlauf_nach_497_tagen(self) -> None:
        # Tick ist gerade uebergelaufen: letzter Input kurz davor, jetzt kurz danach.
        idle = self._idle(0xFFFFFF00, 0x100)
        self.assertAlmostEqual(idle, 0.512)
        self.assertGreaterEqual(idle, 0.0, "darf nie negativ werden")

    def test_fehlgeschlagener_aufruf_meldet_null(self) -> None:
        # Lieber "gerade aktiv" annehmen als faelschlich sperren.
        self.assertEqual(self._idle(0, 999_999, ok=False), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SingleInstanceTest(unittest.TestCase):
    """Die Sperre, die verhindert, dass sich zwei Instanzen die Kamera streiten."""

    def setUp(self) -> None:
        # Eigener Name je Lauf, damit der Test keine echte Instanz stoert.
        self.name = f"away-monitor-test-{id(self)}"
        self.addCleanup(setattr, winapi, "_instance_handle", None)

    def test_erste_bekommt_sie_zweite_nicht(self) -> None:
        self.assertFalse(winapi.instance_is_running(self.name))
        self.assertTrue(winapi.claim_single_instance(self.name))
        self.assertTrue(winapi.instance_is_running(self.name))
        self.assertFalse(winapi.claim_single_instance(self.name),
                         "ein zweiter Anspruch muss scheitern")

    def test_unbenutzter_name_meldet_frei(self) -> None:
        self.assertFalse(winapi.instance_is_running(f"{self.name}-anders"))
