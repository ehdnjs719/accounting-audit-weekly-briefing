# Downloads weekly PDFs that GitHub Actions committed to <repo>/reports into a local folder.
# Runs from Task Scheduler at logon and every Monday 08:15, so even if the laptop was off
# on Monday morning, the folder catches up the moment the PC is turned on.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\sync_reports.ps1 -Repo "github-id/accounting-audit-weekly-briefing"
# Private repo: set a fine-grained token (Contents: read) in env var GITHUB_TOKEN.
param(
    [string]$Repo = "",
    [string]$Dest = (Join-Path $env:USERPROFILE "Documents\CPA_Weekly_Briefing"),
    [string]$Branch = "main"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ConfigFile = Join-Path $PSScriptRoot "sync_config.json"
if (-not $Repo -and (Test-Path $ConfigFile)) {
    $Repo = (Get-Content $ConfigFile -Raw | ConvertFrom-Json).repo
}
if (-not $Repo) { throw "Repo not set. Pass -Repo owner/name or create scripts\sync_config.json" }

$LogDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir "sync.log"
function Write-Log($msg) { "$(Get-Date -Format s)  $msg" | Out-File -Append -Encoding utf8 $Log }

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Headers = @{ "User-Agent" = "weekly-briefing-sync"; "Accept" = "application/vnd.github+json" }
if ($env:GITHUB_TOKEN) { $Headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }

New-Item -ItemType Directory -Force $Dest | Out-Null
try {
    $items = Invoke-RestMethod -Headers $Headers -Uri "https://api.github.com/repos/$Repo/contents/reports?ref=$Branch"
} catch {
    Write-Log "List failed: $($_.Exception.Message)"
    exit 1
}
$new = 0
foreach ($it in $items) {
    if ($it.type -ne "file" -or $it.name -notlike "*.pdf") { continue }
    $target = Join-Path $Dest $it.name
    if (Test-Path $target) { continue }
    Invoke-WebRequest -Headers $Headers -Uri $it.download_url -OutFile $target -UseBasicParsing
    Write-Log "Downloaded $($it.name)"
    $new++
}
Write-Log "Sync done: $new new file(s) -> $Dest"
