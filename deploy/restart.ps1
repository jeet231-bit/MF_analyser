# Restart the app (after a password change, a config edit, or when it misbehaves).
param([string]$ServiceName = "MFAnalyser")
. "$PSScriptRoot\common.ps1"
Require-Elevated "Restarting the service"
$port = Get-Port
Write-Step "Stopping $ServiceName"
Stop-App $ServiceName
Start-Sleep -Seconds 2
Write-Step "Starting $ServiceName"
Start-App $ServiceName
$h = Wait-Healthy -Port $port -Seconds 90
if ($h) { Write-Ok "healthy again: http://$($env:COMPUTERNAME.ToLower()):$port/" }
else { Write-Fail "not healthy after 90 s; run deploy\status.ps1 and read the log"; exit 1 }
