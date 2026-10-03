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
# license texts next to the exe: the app's own, and those of the bundled Qt and Python
$out = "dist\MarstekMonitor"
New-Item -ItemType Directory -Force "$out\licenses" | Out-Null
Copy-Item LICENSE "$out\LICENSE.txt"
Copy-Item packaging\THIRD-PARTY-NOTICES.txt $out
Copy-Item packaging\licenses\*.txt "$out\licenses"
$pythonHome = & .\.venv\Scripts\python -c "import sys; print(sys.base_prefix)"
Copy-Item (Join-Path $pythonHome "LICENSE.txt") "$out\licenses\Python-LICENSE.txt"
# the user guides as they were for this version, with their screenshots (links stay relative)
if (Test-Path "$out\docs") { Remove-Item "$out\docs" -Recurse -Force }  # else images\ nests into images\images
New-Item -ItemType Directory -Force "$out\docs" | Out-Null
Copy-Item docs\user-guide.md, docs\user-guide.uk.md "$out\docs"
Copy-Item docs\images "$out\docs" -Recurse -Force
$required += @("$out\docs\user-guide.md", "$out\docs\user-guide.uk.md", "$out\docs\images\en\status-now.png",
               "$out\docs\images\uk\status-now.png", "$out\docs\images\tray-normal.png")
$required += @("$out\LICENSE.txt", "$out\THIRD-PARTY-NOTICES.txt", "$out\licenses\LGPL-3.0.txt",
               "$out\licenses\GPL-3.0.txt", "$out\licenses\Python-LICENSE.txt")

foreach ($file in $required) {
    if (-not (Test-Path $file)) { throw "Build is incomplete: $file is missing. Close any program showing the dist folder and build again." }
}
Write-Host "Built: dist\MarstekMonitor\MarstekMonitor.exe"
