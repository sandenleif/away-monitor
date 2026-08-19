"""Updater: Versionsvergleich, URL-Absicherung, Dateitausch und ein kompletter
Durchlauf gegen einen lokalen HTTP-Server."""

from __future__ import annotations

import hashlib
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from away_monitor import updater


class VersionTest(unittest.TestCase):
    def test_uebliche_formen(self) -> None:
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("V10.0"), (10, 0))
        self.assertEqual(updater.parse_version("  v2.0.1  "), (2, 0, 1))

    def test_muell_wird_nicht_zum_update(self) -> None:
        self.assertEqual(updater.parse_version(""), (0,))
        self.assertEqual(updater.parse_version("release"), (0,))

    def test_vergleich_ordnet_richtig(self) -> None:
        self.assertGreater(updater.parse_version("v1.10.0"), updater.parse_version("v1.9.9"))
        self.assertGreater(updater.parse_version("v2.0"), updater.parse_version("v1.99.99"))
        self.assertEqual(updater.parse_version("v1.2.3-beta"), updater.parse_version("v1.2.3"))


class UrlGuardTest(unittest.TestCase):
    def test_fremder_host_wird_abgelehnt(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater._open("https://evil.example/payload.exe", 1.0, "*/*")

    def test_klartext_http_wird_abgelehnt(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater._open("http://github.com/owner/repo", 1.0, "*/*")

    def test_dateipfad_wird_abgelehnt(self) -> None:
        with self.assertRaises(updater.UpdateError):
            updater._open("file:///C:/Windows/System32/calc.exe", 1.0, "*/*")


class RepositoryTest(unittest.TestCase):
    """Diese Faelle duerfen gar nicht erst ins Netz gehen."""

    def test_leeres_repository_prueft_nicht(self) -> None:
        with mock.patch.object(updater, "_open", side_effect=AssertionError("kein Netz")):
            self.assertIsNone(updater.check_for_update("", "1.0.0"))
            self.assertIsNone(updater.check_for_update("   ", "1.0.0"))

    def test_unsinniges_repository_prueft_nicht(self) -> None:
        with mock.patch.object(updater, "_open", side_effect=AssertionError("kein Netz")):
            for bad in ["nurname", "a/b/c", "besitzer/name?x=1", "../../etc", "o/r name"]:
                self.assertIsNone(updater.check_for_update(bad, "1.0.0"), bad)

    def test_netzfehler_bleibt_folgenlos(self) -> None:
        with mock.patch.object(updater, "_open", side_effect=OSError("kein Netz")):
            self.assertIsNone(updater.check_for_update("owner/repo", "1.0.0"))


class ChecksumTest(unittest.TestCase):
    def test_verify_erkennt_gleich_und_ungleich(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "datei.bin"
            path.write_bytes(b"inhalt")
            digest = hashlib.sha256(b"inhalt").hexdigest()
            self.assertTrue(updater.verify(path, digest))
            self.assertTrue(updater.verify(path, digest.upper()), "Grossschreibung egal")
            self.assertFalse(updater.verify(path, "0" * 64))


class SwapTest(unittest.TestCase):
    def test_tausch_legt_sicherung_an_und_raeumt_auf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "away-monitor.exe"
            current.write_bytes(b"alte version")
            downloaded = root / "heruntergeladen.exe"
            downloaded.write_bytes(b"neue version")

            updater.apply_update(downloaded, current)

            self.assertEqual(current.read_bytes(), b"neue version")
            backup = root / "away-monitor.old.exe"
            self.assertTrue(backup.exists(), "Vorversion muss zur Seite gelegt werden")
            self.assertEqual(backup.read_bytes(), b"alte version")

            updater.cleanup_previous(current)
            self.assertFalse(backup.exists())

    def test_zweites_update_ueberschreibt_alte_sicherung(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "away-monitor.exe"
            current.write_bytes(b"v2")
            (root / "away-monitor.old.exe").write_bytes(b"v1")
            downloaded = root / "neu.exe"
            downloaded.write_bytes(b"v3")

            updater.apply_update(downloaded, current)

            self.assertEqual(current.read_bytes(), b"v3")
            self.assertEqual((root / "away-monitor.old.exe").read_bytes(), b"v2")

    def test_rollback_wenn_einsetzen_scheitert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / "away-monitor.exe"
            current.write_bytes(b"alte version")
            downloaded = root / "neu.exe"
            downloaded.write_bytes(b"neue version")

            with mock.patch.object(Path, "replace", side_effect=OSError("belegt")):
                with self.assertRaises(updater.UpdateError):
                    updater.apply_update(downloaded, current)

            self.assertTrue(current.exists(), "alte Version muss wieder da sein")
            self.assertEqual(current.read_bytes(), b"alte version")

    def test_aufraeumen_ohne_sicherung_ist_harmlos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            updater.cleanup_previous(Path(tmp) / "away-monitor.exe")
            updater.cleanup_previous(None)


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, tuple[str, bytes]] = {}

    def do_GET(self) -> None:  # noqa: N802 -- von BaseHTTPRequestHandler vorgegeben
        entry = self.routes.get(self.path)
        if entry is None:
            self.send_error(404)
            return
        content_type, body = entry
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        pass


class EndToEndTest(unittest.TestCase):
    """Kompletter Ablauf gegen einen echten (lokalen) HTTP-Server."""

    def setUp(self) -> None:
        self.payload = b"MZ" + b"vorgetaeuschte Exe" * 500
        self.digest = hashlib.sha256(self.payload).hexdigest()

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        port = self.server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        release = {
            "tag_name": "v2.3.0",
            "body": "Schnellere Erkennung",
            "html_url": "https://github.com/owner/repo/releases/tag/v2.3.0",
            "assets": [
                # Absichtlich zuerst: die Pruefsummendatei darf nicht als Exe
                # durchgehen, nur weil ihr Name '.exe' enthaelt.
                {"name": "away-monitor.exe.sha256",
                 "browser_download_url": f"{base}/away-monitor.exe.sha256"},
                {"name": "away-monitor.exe",
                 "browser_download_url": f"{base}/away-monitor.exe"},
            ],
        }
        _Handler.routes = {
            "/repos/owner/repo/releases/latest":
                ("application/json", json.dumps(release).encode()),
            "/away-monitor.exe": ("application/octet-stream", self.payload),
            "/away-monitor.exe.sha256":
                ("text/plain", f"{self.digest}  away-monitor.exe\n".encode()),
        }
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

        for patch in [
            mock.patch.object(updater, "_API", base + "/repos/{repo}/releases/latest"),
            mock.patch.object(updater, "_ALLOWED_HOSTS", frozenset({"127.0.0.1"})),
            mock.patch.object(updater, "_ALLOWED_SCHEMES", frozenset({"http"})),
        ]:
            patch.start()
            self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_pruefen_laden_verifizieren(self) -> None:
        release = updater.check_for_update("owner/repo", "1.0.0")
        self.assertIsNotNone(release)
        self.assertEqual(release.tag, "v2.3.0")
        self.assertEqual(release.label, "2.3.0")
        self.assertEqual(release.asset_name, "away-monitor.exe")
        self.assertTrue(release.checksum_url.endswith(".sha256"))

        with tempfile.TemporaryDirectory() as tmp:
            downloaded = updater.download(release, Path(tmp))
            self.assertEqual(downloaded.read_bytes(), self.payload)
            checksum = updater.fetch_checksum(release)
            self.assertEqual(checksum, self.digest)
            self.assertTrue(updater.verify(downloaded, checksum))

    def test_manipulierte_datei_faellt_durch(self) -> None:
        release = updater.check_for_update("owner/repo", "1.0.0")
        with tempfile.TemporaryDirectory() as tmp:
            downloaded = updater.download(release, Path(tmp))
            downloaded.write_bytes(b"etwas ganz anderes")
            self.assertFalse(updater.verify(downloaded, self.digest))

    def test_gleiche_oder_neuere_version_meldet_nichts(self) -> None:
        self.assertIsNone(updater.check_for_update("owner/repo", "2.3.0"))
        self.assertIsNone(updater.check_for_update("owner/repo", "9.0.0"))

    def test_zu_grosser_download_wird_abgebrochen(self) -> None:
        release = updater.check_for_update("owner/repo", "1.0.0")
        with (mock.patch.object(updater, "_MAX_DOWNLOAD", 100),
              tempfile.TemporaryDirectory() as tmp):
            with self.assertRaises(updater.UpdateError):
                updater.download(release, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [], "Bruchstueck muss weg sein")


if __name__ == "__main__":
    unittest.main(verbosity=2)
