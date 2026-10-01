# Builds dist\MarstekMonitor\MarstekMonitor.exe (run from any folder).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
.\.venv\Scripts\python packaging\make_icon.py
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\MarstekMonitor.spec
Write-Host "Built: dist\MarstekMonitor\MarstekMonitor.exe"
