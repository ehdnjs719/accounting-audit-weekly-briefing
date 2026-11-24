# One-time local setup: venv, dependencies, Chromium, .env template.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path ".venv")) {
    Write-Host "[1/4] Creating virtual environment (.venv)"
    python -m venv .venv
}
$Py = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "[2/4] Installing Python packages"
& $Py -m pip install --upgrade pip -q
& $Py -m pip install -r requirements.txt -q

Write-Host "[3/4] Installing Chromium for Playwright"
& $Py -m playwright install chromium

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[4/4] Created .env from template - open it and fill in SMTP_USER / SMTP_PASSWORD / MAIL_TO"
} else {
    Write-Host "[4/4] .env already exists - left unchanged"
}
Write-Host "Done. Test with:  .\.venv\Scripts\python.exe main.py --no-email"
