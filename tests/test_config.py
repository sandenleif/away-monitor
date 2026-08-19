"""Konfiguration: Voreinstellungen, Vorlage und das Nachtragen der Herkunft."""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from away_monitor import config as config_module
from away_monitor.updater import _REPO_PATTERN


class UpdateRepositoryTest(unittest.TestCase):
    """Ohne hinterlegte Herkunft findet eine frisch ausgepackte Exe nie ein
    Update -- und man merkt es nicht, weil nichts kaputtgeht."""

    def test_voreinstellung_ist_gesetzt_und_gueltig(self) -> None:
        self.assertTrue(config_module.DEFAULT_REPOSITORY,
                        "ohne Repository laeuft die Selbstaktualisierung nie an")
        self.assertRegex(config_module.DEFAULT_REPOSITORY, _REPO_PATTERN)

    def test_vorlage_traegt_dasselbe_repository(self) -> None:
        parsed = tomllib.loads(config_module.DEFAULT_CONFIG)
        self.assertEqual(parsed["update"]["repository"], config_module.DEFAULT_REPOSITORY)

    def test_dataclass_faellt_auf_dasselbe_zurueck(self) -> None:
        self.assertEqual(config_module.Config().update_repository,
                         config_module.DEFAULT_REPOSITORY)

    def test_frisch_angelegte_konfiguration_enthaelt_es(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            cfg = config_module.load(path)
            self.assertTrue(path.exists(), "beim ersten Start muss sie entstehen")
            self.assertEqual(cfg.update_repository, config_module.DEFAULT_REPOSITORY)
            self.assertIn(config_module.DEFAULT_REPOSITORY, path.read_text(encoding="utf-8"))

    def test_geleerte_zeile_wird_nachgetragen(self) -> None:
        """Eine ueber Versionen mitgeschleppte config.toml darf die App nicht ihre
        Herkunft kosten -- sonst sucht sie nie nach Updates, ohne dass irgendetwas
        sichtbar fehlschlaegt."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(
                "\n".join([
                    "[timing]",
                    "absence_grace = 20.0",
                    "",
                    "[update]",
                    "# eigener Kommentar",
                    'repository = ""',
                    "check_on_start = true",
                ]),
                encoding="utf-8",
            )
            cfg = config_module.load(path)

            self.assertEqual(cfg.update_repository, config_module.DEFAULT_REPOSITORY)
            written = path.read_text(encoding="utf-8")
            self.assertIn(f'repository = "{config_module.DEFAULT_REPOSITORY}"', written)
            self.assertIn("# eigener Kommentar", written, "Kommentare bleiben erhalten")
            self.assertEqual(config_module.load(path).absence_grace, 20.0,
                             "andere Werte bleiben unangetastet")

    def test_fehlender_abschnitt_wird_ergaenzt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text("[timing]\nabsence_grace = 33.0\n", encoding="utf-8")
            cfg = config_module.load(path)

            self.assertEqual(cfg.update_repository, config_module.DEFAULT_REPOSITORY)
            self.assertIn("[update]", path.read_text(encoding="utf-8"))
            self.assertEqual(config_module.load(path).absence_grace, 33.0)

    def test_eigener_fork_bleibt_unberuehrt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[update]\nrepository = "jemand/fork"\n', encoding="utf-8")

            self.assertEqual(config_module.load(path).update_repository, "jemand/fork")
            self.assertIn('"jemand/fork"', path.read_text(encoding="utf-8"))

    def test_abschalten_laeuft_ueber_check_on_start(self) -> None:
        """Das Repository zu leeren schaltet nichts ab -- dafuer gibt es den
        eigenen Schalter, und der bleibt unangetastet."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[update]\nrepository = ""\ncheck_on_start = false\n',
                            encoding="utf-8")
            cfg = config_module.load(path)

            self.assertEqual(cfg.update_repository, config_module.DEFAULT_REPOSITORY)
            self.assertFalse(cfg.update_check_on_start)

    def test_nicht_schreibbare_datei_kippt_nichts(self) -> None:
        """Laesst sich die Datei nicht ergaenzen, gilt die Voreinstellung
        wenigstens im Speicher."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text('[update]\nrepository = ""\n', encoding="utf-8")
            with mock.patch.object(Path, "write_text", side_effect=OSError("schreibgeschuetzt")):
                cfg = config_module.load(path)
            self.assertEqual(cfg.update_repository, config_module.DEFAULT_REPOSITORY)


class DefaultConfigTest(unittest.TestCase):
    def test_vorlage_ist_gueltiges_toml(self) -> None:
        parsed = tomllib.loads(config_module.DEFAULT_CONFIG)
        for section in ["timing", "camera", "detection", "preview", "behavior",
                        "update", "logging"]:
            self.assertIn(section, parsed)

    def test_vorlage_und_dataclass_stimmen_ueberein(self) -> None:
        """Sonst verhaelt sich die App je nachdem anders, ob die Datei da ist."""
        parsed = tomllib.loads(config_module.DEFAULT_CONFIG)
        defaults = config_module.Config()
        self.assertEqual(parsed["timing"]["idle_before_camera"], defaults.idle_before_camera)
        self.assertEqual(parsed["timing"]["absence_grace"], defaults.absence_grace)
        self.assertEqual(parsed["timing"]["warning_seconds"], defaults.warning_seconds)
        self.assertEqual(parsed["detection"]["score_threshold"], defaults.score_threshold)
        self.assertEqual(parsed["behavior"]["on_camera_error"], defaults.on_camera_error)
        self.assertEqual(parsed["update"]["require_checksum"], defaults.update_require_checksum)

    def test_jeder_abschnitt_ist_kommentiert(self) -> None:
        lines = config_module.DEFAULT_CONFIG.splitlines()
        self.assertGreater(len([line for line in lines if line.startswith("#")]), 15,
                           "die Datei ist die einzige Dokumentation am Zielrechner")


if __name__ == "__main__":
    unittest.main(verbosity=2)
