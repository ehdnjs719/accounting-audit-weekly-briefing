# Registers Windows Task Scheduler jobs for the current user (no admin needed).
#
#   -Mode Sync  (recommended with GitHub Actions)
#       GitHub Actions sends the email every Monday 07:30 KST even when the laptop is off.
#       This task only copies the new PDFs into the local folder: at logon + Monday 08:15,
#       and "run as soon as possible after a missed start" is enabled.
#   -Mode Local (no GitHub)
#       Runs the full pipeline on this PC every Monday 08:00. If the PC is off at 08:00,
#       it runs right after the next boot/logon (StartWhenAvailable) and can wake from sleep.
#   -Unregister removes both tasks.
param(
    [ValidateSet("Sync", "Local")] [string]$Mode = "Sync",
    [string]$Repo = "",
    [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$SyncName = "CPA Weekly Briefing - Sync"
$LocalName = "CPA Weekly Briefing - Local Run"

if ($Unregister) {
    foreach ($n in @($SyncName, $LocalName)) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "Removed: $n"
        }
    }
    return
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if ($Mode -eq "Sync") {
    if ($Repo) { @{ repo = $Repo } | ConvertTo-Json | Out-File -Encoding ascii (Join-Path $PSScriptRoot "sync_config.json") }
    $script = Join-Path $PSScriptRoot "sync_reports.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
    $triggers = @(
        (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:15"),
        (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
    )
    Register-ScheduledTask -TaskName $SyncName -Action $action -Trigger $triggers -Settings $settings `
        -Principal $principal -Description "Copies weekly accounting/audit briefing PDFs from GitHub to Documents\CPA_Weekly_Briefing" -Force | Out-Null
    Write-Host "Registered: $SyncName (Monday 08:15 + at logon)"
} else {
    $settings.WakeToRun = $true
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    $runner = Join-Path $PSScriptRoot "run_local.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $Root
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "08:00"
    Register-ScheduledTask -TaskName $LocalName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "Builds and emails the weekly accounting/audit briefing" -Force | Out-Null
    Write-Host "Registered: $LocalName (Monday 08:00, catch-up after boot, wake from sleep)"
}
Get-ScheduledTask -TaskName "CPA Weekly Briefing*" | Select-Object TaskName, State | Format-Table -AutoSize
