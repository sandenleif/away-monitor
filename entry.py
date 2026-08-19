"""Startpunkt fuer den PyInstaller-Build.

away_monitor/__main__.py nutzt relative Importe; PyInstaller wuerde die Datei
als lose Skriptdatei analysieren und daran scheitern. Dieser Umweg laedt sie
als Teil des Pakets.
"""

from away_monitor.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
