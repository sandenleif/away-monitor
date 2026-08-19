<#
.SYNOPSIS
    Baut und veroeffentlicht ein Release: Tests, Exe, Pruefsumme, Tag, GitHub.
.PARAMETER DryRun
    Alles bis zum Veroeffentlichen, aber ohne Tag und ohne Release.
.PARAMETER Notes
    Datei mit den Release-Notizen. Ohne Angabe erzeugt GitHub sie aus den Commits.
.NOTES
    Ersetzt den CI-Workflow: braucht nur den 'repo'-Scope, nicht 'workflow'.
#>
param([switch]$DryRun, [string]$Notes)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $root
try {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) { $gh = Join-Path $env:LOCALAPPDATA 'Programs\gh\bin\gh.exe' } else { $gh = $gh.Source }
    if (-not (Test-Path $gh)) { throw "gh nicht gefunden. Siehe README." }

    $version = (Select-String -Path 'away_monitor\__init__.py' -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value
    $tag = "v$version"
    Write-Host "Release $tag" -ForegroundColor Cyan

    # Das, was die CI sonst prueft: nichts Uncommittetes, Tag noch frei.
    $dirty = git status --porcelain
    if ($dirty) {
        Write-Host "Uncommittete Aenderungen:" -ForegroundColor Yellow
        $dirty | ForEach-Object { Write-Host "  $_" }
        if (-not $DryRun) { throw "Erst committen -- sonst passt das Release nicht zum Stand im Repo." }
    }
    $existing = git tag --list $tag
    if ($existing -and -not $DryRun) {
        throw "Tag $tag existiert bereits. Erst __version__ in away_monitor\__init__.py hochsetzen."
    }

    & (Join-Path $PSScriptRoot 'build.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build fehlgeschlagen." }

    $exe = Join-Path $root 'dist\away-monitor.exe'
    $sum = "$exe.sha256"

    if ($DryRun) {
        Write-Host ""
        Write-Host "-- Probelauf, es wird nichts veroeffentlicht --" -ForegroundColor Yellow
        Write-Host "  wuerde taggen : $tag"
        Write-Host "  wuerde laden  : $(Split-Path $exe -Leaf), $(Split-Path $sum -Leaf)"
        return
    }

    git tag -a $tag -m "away-monitor $version"
    git push origin $tag
    git push

    $ghArgs = @('release','create',$tag,$exe,$sum,'--title',"away-monitor $version")
    if ($Notes) { $ghArgs += @('--notes-file',$Notes) } else { $ghArgs += '--generate-notes' }
    & $gh @ghArgs
    if ($LASTEXITCODE -ne 0) { throw "gh release create fehlgeschlagen." }

    Write-Host ""
    Write-Host "Veroeffentlicht. Der Updater findet es ab sofort." -ForegroundColor Green
}
finally { Pop-Location }
