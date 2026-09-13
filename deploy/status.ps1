# Is it running? Service state, health, the last log lines, the latest backup.
param([string]$ServiceName = "MFAnalyser")
. "$PSScriptRoot\common.ps1"

$port = Get-Port
$dataDir = Get-DataDir
$backupDir = Get-BackupDir
Write-Host ""
Write-Host "MF Analyser status" -ForegroundColor White
Write-Host "  install:  $(Get-ServiceMode $ServiceName)  state: $(Get-AppState $ServiceName)"
Write-Host "  config:   $ConfigFile"
Write-Host "  data:     $dataDir"
Write-Host "  url:      http://$($env:COMPUTERNAME.ToLower()):$port/"
try {
    $h = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/health" -TimeoutSec 5
    Write-Ok "health: status=$($h.status) version=$($h.version) database=$($h.database)"
} catch {
    Write-Fail "no answer on http://127.0.0.1:$port/api/health ($($_.Exception.Message))"
}
$latest = Get-ChildItem $backupDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match "^\d{4}-\d{2}-\d{2}$" } | Sort-Object Name | Select-Object -Last 1
if ($latest) { Write-Host "  backup:   latest $($latest.Name) in $backupDir" } else { Write-Warn2 "no dated backup in $backupDir yet (run deploy\backup-now.ps1)" }
$log = Join-Path $dataDir "logs\mf-analyser.log"
if (Test-Path $log) {
    Write-Host ""
    Write-Host "  last 30 lines of $log" -ForegroundColor DarkGray
    Get-Content $log -Tail 30 | ForEach-Object { "    $_" }
} else {
    Write-Warn2 "no log at $log"
}
$err = Join-Path $dataDir "logs\service.err.log"
if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) {
    Write-Host ""
    Write-Host "  last 10 lines of $err" -ForegroundColor DarkGray
    Get-Content $err -Tail 10 | ForEach-Object { "    $_" }
}
Write-Host ""
