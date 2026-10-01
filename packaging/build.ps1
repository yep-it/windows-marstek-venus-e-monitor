# Builds dist\MarstekMonitor\MarstekMonitor.exe (run from any folder).
# Fails loudly: native commands don't trip $ErrorActionPreference, so every exit code is checked,
# and the result is verified (a half-deleted dist folder once produced an exe without its i18n files).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Step($what, [scriptblock]$command) {
    & $command
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

Invoke-Step "Rendering the icon" { .\.venv\Scripts\python packaging\make_icon.py }
Invoke-Step "PyInstaller" { .\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\MarstekMonitor.spec }

$required = @(
    "dist\MarstekMonitor\MarstekMonitor.exe",
    "dist\MarstekMonitor\_internal\marstek_monitor\i18n\en.json",
    "dist\MarstekMonitor\_internal\marstek_monitor\i18n\uk.json"
)
foreach ($file in $required) {
    if (-not (Test-Path $file)) { throw "Build is incomplete: $file is missing. Close any program showing the dist folder and build again." }
}
Write-Host "Built: dist\MarstekMonitor\MarstekMonitor.exe"
