@echo off
rem Startet away-monitor ohne Konsolenfenster. Argumente werden durchgereicht,
rem z.B.:  run.cmd --live
rem Funktioniert aus jedem Verzeichnis -- %~dp0 ist der Ordner dieser Datei.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m away_monitor %*
