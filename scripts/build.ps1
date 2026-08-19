<#
.SYNOPSIS
    Baut dist\away-monitor.exe samt SHA256-Pruefsumme.
.PARAMETER SkipTests
    Tests ueberspringen (nur fuer schnelle Zwischenstaende).
#>
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root
try {
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) {
        throw "venv fehlt unter $python -- siehe README, Abschnitt Installation."
    }

    $version = (Select-String -Path 'away_monitor\__init__.py' -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
    Write-Host "Baue away-monitor $version"

    if (-not $SkipTests) {
        & $python -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) { throw "Tests fehlgeschlagen -- kein Build." }
    }

    & $python 'scripts\make_icon.py'
    & (Join-Path $root '.venv\Scripts\pyinstaller.exe') 'away-monitor.spec' --noconfirm --clean --log-level WARN
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist fehlgeschlagen." }

    $exe = Join-Path $root 'dist\away-monitor.exe'
    if (-not (Test-Path $exe)) { throw "Build lieferte keine Exe." }

    # Die Pruefsumme entscheidet spaeter, ob ein Update installiert wird.
    $hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    # Ueber .NET schreiben: Set-Content setzt in PowerShell 5.1 ein BOM davor.
    [IO.File]::WriteAllText("$exe.sha256", "$hash  away-monitor.exe`n")

    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Fertig:  $exe  ($size MB)"
    Write-Host "SHA256:  $hash"
    Write-Host ""
    Write-Host "Veroeffentlichen:  git tag v$version; git push origin v$version"
}
finally { Pop-Location }
