# Remove the service/task, the backup task and the firewall rule. Data and backups are kept.
param([string]$ServiceName = "MFAnalyser", [switch]$DryRun)
. "$PSScriptRoot\common.ps1"
if (-not $DryRun) { Require-Elevated "Uninstalling" }
$steps = @(
    @{ what = "stop and remove service/task '$ServiceName'"; do = {
        Stop-App $ServiceName
        if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) { & $NssmExe remove $ServiceName confirm | Out-Null }
        if (Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false }
    } },
    @{ what = "remove the '$ServiceName Backup' task"; do = {
        if (Get-ScheduledTask -TaskName "$ServiceName Backup" -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName "$ServiceName Backup" -Confirm:$false }
    } },
    @{ what = "remove firewall rule 'MF Analyser'"; do = {
        Get-NetFirewallRule -DisplayName "MF Analyser" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    } }
)
foreach ($s in $steps) {
    if ($DryRun) { Write-Host "    would: $($s.what)" -ForegroundColor DarkGray } else { & $s.do; Write-Ok $s.what }
}
Write-Host ""
Write-Host "Kept: $(Get-DataDir), $(Get-BackupDir), $ConfigFile. Delete them by hand if you mean to."
