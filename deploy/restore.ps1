# Restore a dated backup: stops the app, copies the database and workbooks back, starts it.
#   deploy\restore.ps1 -Date 2026-09-13
param(
    [Parameter(Mandatory = $true)][string]$Date,
    [string]$ServiceName = "MFAnalyser"
)
. "$PSScriptRoot\common.ps1"
Require-Elevated "Restoring (the service must be stopped)"
$python = Get-PythonExe
if (-not $python) { Write-Fail "backend\.venv is missing; run deploy\install.ps1"; exit 1 }
$backupDir = Get-BackupDir
if (-not (Test-Path (Join-Path $backupDir "$Date\mf-analyser.db"))) {
    Write-Fail "no backup at $backupDir\$Date. Available:"
    Get-ChildItem $backupDir -Directory -ErrorAction SilentlyContinue | ForEach-Object { "    $($_.Name)" }
    exit 1
}
Write-Step "Taking a safety backup of the current state first"
$env:MFA_CONFIG_FILE = $ConfigFile
Push-Location $BackendDir
try {
    & $python -m app.tools.backup --keep 30
    Write-Step "Stopping $ServiceName"
    Stop-App $ServiceName
    Start-Sleep -Seconds 3
    Write-Step "Restoring $Date"
    & $python -m app.tools.restore $Date
    $code = $LASTEXITCODE
} finally { Pop-Location }
Write-Step "Starting $ServiceName"
Start-App $ServiceName
$h = Wait-Healthy -Port (Get-Port) -Seconds 90
if ($code -ne 0) { Write-Fail "restore reported a problem (exit $code); the app is back up on the previous data"; exit $code }
if ($h) { Write-Ok "restored $Date and healthy" } else { Write-Fail "restored but not healthy after 90 s; run deploy\status.ps1"; exit 1 }
