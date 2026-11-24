# Runs the full pipeline locally and writes a dated log (used by Task Scheduler -Mode Local).
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$env:PYTHONIOENCODING = "utf-8"
& (Join-Path $Root ".venv\Scripts\python.exe") main.py *>> (Join-Path $LogDir "run_$(Get-Date -Format yyyy-MM-dd).log")
exit $LASTEXITCODE
