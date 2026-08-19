<#
.SYNOPSIS
    Legt eine Verknuepfung im Autostart-Ordner an, damit away-monitor beim Anmelden startet.
.PARAMETER Remove
    Entfernt die Verknuepfung wieder.
.NOTES
    Braucht keine Adminrechte -- der Autostart-Ordner gehoert dem angemeldeten Benutzer.
#>
param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$startup = [Environment]::GetFolderPath('Startup')
$link = Join-Path $startup 'away-monitor.lnk'

if ($Remove) {
    if (Test-Path $link) {
        Remove-Item $link -Force
        Write-Host "Autostart entfernt: $link"
    } else {
        Write-Host "Kein Autostart-Eintrag vorhanden."
    }
    return
}

$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe nicht gefunden unter $pythonw -- zuerst das venv anlegen (siehe README)."
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '-m away_monitor'
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7          # minimiert, pythonw zeigt ohnehin kein Fenster
$shortcut.Description = 'away-monitor - sperrt den PC bei Abwesenheit'
$shortcut.Save()

Write-Host "Autostart eingerichtet: $link"
Write-Host "Entfernen mit:  powershell -ExecutionPolicy Bypass -File scripts\autostart.ps1 -Remove"
