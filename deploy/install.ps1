<#
.SYNOPSIS
  Installs MF Analyser on one Windows machine as an always-on service.

.DESCRIPTION
  Run from an elevated PowerShell in the repo checkout:
      powershell -ExecutionPolicy Bypass -File deploy\install.ps1
  It installs uv + Python 3.12, the backend, builds (or requires) the UI, writes
  C:\MFAnalyser\config.env, asks for the shared password, registers the service
  (NSSM, or a Scheduled Task with -UseScheduledTask), opens the firewall port,
  schedules the 02:00 daily backup, starts everything and prints the URL to share.
  Safe to run again: every step is idempotent.

.PARAMETER DataDir        Where the database and uploaded workbooks live (never OneDrive).
.PARAMETER BackupDir      Where dated backups go; put it on another drive or a share if you can.
.PARAMETER Port           TCP port the app listens on.
.PARAMETER ServiceName    Windows service / task name.
.PARAMETER UseScheduledTask  Register a Scheduled Task instead of an NSSM service (fallback
                          when antivirus blocks nssm.exe).
.PARAMETER SkipUiBuild    Do not run npm; require an existing frontend\dist.
.PARAMETER DryRun         Print every action without changing anything.
#>
[CmdletBinding()]
param(
    [string]$DataDir = "C:\MFAnalyser\data",
    [string]$BackupDir = "C:\MFAnalyser\backups",
    [int]$Port = 8000,
    [string]$ServiceName = "MFAnalyser",
    [switch]$UseScheduledTask,
    [switch]$SkipUiBuild,
    [switch]$DryRun
)

. "$PSScriptRoot\common.ps1"

$script:ConfigFile = Join-Path (Split-Path $DataDir -Parent) "config.env"
$BackupTaskName = "$ServiceName Backup"

function Invoke-Step([string]$Description, [scriptblock]$Action) {
    if ($DryRun) { Write-Host "    would: $Description" -ForegroundColor DarkGray }
    else { & $Action; Write-Ok $Description }
}

Write-Host ""
Write-Host "MF Analyser installer" -ForegroundColor White
Write-Host "  repo:     $RepoRoot"
Write-Host "  data:     $DataDir"
Write-Host "  backups:  $BackupDir"
Write-Host "  config:   $ConfigFile"
Write-Host "  port:     $Port"
Write-Host "  mode:     $(if ($UseScheduledTask) { 'Scheduled Task' } else { 'NSSM service' })"
if ($DryRun) { Write-Host "  DRY RUN: nothing will change" -ForegroundColor Yellow }

# ---- preconditions ----------------------------------------------------------------------
Write-Step "Checking preconditions"
if (-not $DryRun) { Require-Elevated "Installing a service, a firewall rule and scheduled tasks" }
foreach ($pair in @(@("data directory", $DataDir), @("backup directory", $BackupDir))) {
    if (Test-OneDrivePath $pair[1]) {
        Write-Fail "The $($pair[0]) '$($pair[1])' is inside OneDrive. OneDrive locks and corrupts an open SQLite file. Use a local folder such as C:\MFAnalyser\data."
        exit 1
    }
}
if (Test-OneDrivePath $RepoRoot) {
    if ($DryRun) { Write-Warn2 "the checkout is under OneDrive; a real install refuses this (put the app at C:\MFAnalyser\app)" }
    else { Write-Fail "The app folder '$RepoRoot' is inside OneDrive: the sync client fights the virtual environment and the service. Put the app at C:\MFAnalyser\app and run again."; exit 1 }
} else { Write-Ok "no path is under OneDrive" }
$drive = (Split-Path -Qualifier $DataDir)
$free = (Get-PSDrive -Name $drive.TrimEnd(":") -ErrorAction SilentlyContinue).Free
if ($free) {
    $freeGb = [math]::Round($free / 1GB, 1)
    if ($freeGb -lt 20) { Write-Warn2 "only $freeGb GB free on $drive; each uploaded master is ~50-150 MB and backups keep 30 days" }
    else { Write-Ok "$freeGb GB free on $drive" }
}

# ---- uv + python --------------------------------------------------------------------------
Write-Step "Python toolchain (uv)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    $candidate = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
    if (Test-Path $candidate) { $uv = Get-Item $candidate }
}
if (-not $uv) {
    Invoke-Step "install uv (astral.sh)" {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
        $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv -and -not $DryRun) { Write-Fail "uv did not install; install it from https://docs.astral.sh/uv/ and rerun"; exit 1 }
}
$uvExe = if ($uv) { $uv.Source } else { "uv" }
Invoke-Step "uv python install 3.12" { & $uvExe python install 3.12 | Out-Null }
Invoke-Step "uv sync --extra pdf in backend (falls back to no PDF extra if GTK is absent)" {
    Push-Location $BackendDir
    try {
        & $uvExe sync --extra pdf
        if ($LASTEXITCODE -ne 0) { & $uvExe sync; if ($LASTEXITCODE -ne 0) { throw "uv sync failed" } }
    } finally { Pop-Location }
}
$python = Get-PythonExe
if (-not $python -and -not $DryRun) { Write-Fail "backend\.venv\Scripts\python.exe is missing after uv sync"; exit 1 }
if (-not $python) { $python = Join-Path $BackendDir ".venv\Scripts\python.exe" }

# ---- UI build -----------------------------------------------------------------------------
Write-Step "Web app build"
$dist = Join-Path $FrontendDir "dist\index.html"
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm -and -not $SkipUiBuild) {
    Invoke-Step "npm ci && npm run build in frontend" {
        Push-Location $FrontendDir
        try {
            & npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
        } finally { Pop-Location }
    }
} elseif (Test-Path $dist) {
    Write-Ok "using the existing frontend\dist (built elsewhere)"
} else {
    Write-Fail "Node is not installed and frontend\dist is missing. Either install Node 20+ and rerun, or run 'npm run build' on another machine and copy frontend\dist here."
    if (-not $DryRun) { exit 1 }
}

# ---- data dirs + config -------------------------------------------------------------------
Write-Step "Data directory and config"
Invoke-Step "create $DataDir, $DataDir\logs, $DataDir\inbox, $BackupDir" {
    foreach ($d in $DataDir, (Join-Path $DataDir "logs"), (Join-Path $DataDir "inbox"), $BackupDir) {
        New-Item -ItemType Directory -Force $d | Out-Null
    }
}
Invoke-Step "write $ConfigFile" {
    Set-ConfigValue "MFA_ENVIRONMENT" "production"
    Set-ConfigValue "MFA_DATA_DIR" $DataDir
    Set-ConfigValue "MFA_BACKUP_DIR" $BackupDir
    Set-ConfigValue "MFA_HOST" "0.0.0.0"
    Set-ConfigValue "MFA_PORT" "$Port"
    Set-ConfigValue "MFA_STATIC_DIR" (Join-Path $FrontendDir "dist")
    if (-not (Read-ConfigValue "MFA_AUTH_SECRET")) {
        $bytes = New-Object byte[] 48
        [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
        Set-ConfigValue "MFA_AUTH_SECRET" ([Convert]::ToBase64String($bytes))
    }
}

# ---- shared password ----------------------------------------------------------------------
Write-Step "Shared password"
if (Read-ConfigValue "MFA_AUTH_PASSWORD_HASH") {
    Write-Ok "a password is already set (change it with deploy\set-password.ps1)"
} elseif ($DryRun) {
    Write-Host "    would: prompt for the shared password and store its hash" -ForegroundColor DarkGray
} else {
    do {
        $one = Read-Host -AsSecureString "Choose the shared password (8+ characters)"
        $two = Read-Host -AsSecureString "Type it again"
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($one))
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringUni([Runtime.InteropServices.Marshal]::SecureStringToGlobalAllocUnicode($two))
        if ($p1 -ne $p2) { Write-Warn2 "they differ, try again" }
        elseif ($p1.Length -lt 8) { Write-Warn2 "use at least 8 characters" }
    } until ($p1 -eq $p2 -and $p1.Length -ge 8)
    Push-Location $BackendDir
    try {
        $p1 | & $python -m app.tools.set_password --config-file $ConfigFile --stdin
        if ($LASTEXITCODE -ne 0) { throw "set_password failed" }
    } finally { Pop-Location; $p1 = $null; $p2 = $null }
    Write-Ok "password stored as a hash in $ConfigFile"
}

# ---- service ------------------------------------------------------------------------------
Write-Step "Service registration ($ServiceName)"
$logDir = Join-Path $DataDir "logs"
$uvicornArgs = "-m uvicorn app.main:app --host 0.0.0.0 --port $Port --workers 1"
if (-not $UseScheduledTask) {
    if (Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue) {
        Invoke-Step "remove the earlier scheduled-task install" { Stop-App $ServiceName; Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false }
    }
    $expected = ((Get-Content $NssmHashFile -TotalCount 1) -split "\s+")[0].ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 $NssmExe).Hash.ToLower()
    if ($expected -ne $actual) { Write-Fail "deploy\tools\nssm.exe does not match its pinned SHA-256 ($expected). Refusing to use it."; exit 1 }
    Write-Ok "nssm.exe hash verified"
    Invoke-Step "nssm install/configure $ServiceName" {
        if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        } else {
            & $NssmExe install $ServiceName $python | Out-Null
        }
        & $NssmExe set $ServiceName Application $python | Out-Null
        & $NssmExe set $ServiceName AppParameters $uvicornArgs | Out-Null
        & $NssmExe set $ServiceName AppDirectory $BackendDir | Out-Null
        & $NssmExe set $ServiceName AppEnvironmentExtra "MFA_CONFIG_FILE=$ConfigFile" "PYTHONUNBUFFERED=1" | Out-Null
        & $NssmExe set $ServiceName DisplayName "MF Analyser" | Out-Null
        & $NssmExe set $ServiceName Description "Excel-driven research analytics platform (FastAPI, port $Port)" | Out-Null
        & $NssmExe set $ServiceName Start SERVICE_AUTO_START | Out-Null
        & $NssmExe set $ServiceName ObjectName LocalSystem | Out-Null
        & $NssmExe set $ServiceName AppStdout (Join-Path $logDir "service.out.log") | Out-Null
        & $NssmExe set $ServiceName AppStderr (Join-Path $logDir "service.err.log") | Out-Null
        & $NssmExe set $ServiceName AppRotateFiles 1 | Out-Null
        & $NssmExe set $ServiceName AppRotateOnline 1 | Out-Null
        & $NssmExe set $ServiceName AppRotateBytes 10485760 | Out-Null
        & $NssmExe set $ServiceName AppExit Default Restart | Out-Null
        & $NssmExe set $ServiceName AppRestartDelay 5000 | Out-Null
        & $NssmExe set $ServiceName AppStopMethodConsole 10000 | Out-Null
    }
} else {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
        Invoke-Step "remove the earlier NSSM install" { & $NssmExe stop $ServiceName | Out-Null; & $NssmExe remove $ServiceName confirm | Out-Null }
    }
    Invoke-Step "register scheduled task $ServiceName (at startup, SYSTEM, restarts on failure)" {
        $runner = Join-Path $PSScriptRoot "run.ps1"
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -ConfigFile `"$ConfigFile`"" -WorkingDirectory $BackendDir
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
        $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
        if (Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue) { Stop-App $ServiceName; Unregister-ScheduledTask -TaskName $ServiceName -Confirm:$false }
        Register-ScheduledTask -TaskName $ServiceName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "MF Analyser (port $Port)" | Out-Null
    }
}

# ---- firewall -----------------------------------------------------------------------------
Write-Step "Firewall"
Invoke-Step "allow inbound TCP $Port on Domain and Private networks (rule 'MF Analyser')" {
    Get-NetFirewallRule -DisplayName "MF Analyser" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName "MF Analyser" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain, Private | Out-Null
}

# ---- daily backup -------------------------------------------------------------------------
Write-Step "Daily backup task ($BackupTaskName, 02:00)"
Invoke-Step "register the backup task" {
    # The tool reads the config file for the data and backup dirs; cmd.exe sets it and keeps a log.
    $command = "/c set MFA_CONFIG_FILE=$ConfigFile&& `"$python`" -m app.tools.backup --keep 30 >> `"$logDir\backup.log`" 2>&1"
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $command -WorkingDirectory $BackendDir
    $trigger = New-ScheduledTaskTrigger -Daily -At 02:00
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable -AllowStartIfOnBatteries
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    if (Get-ScheduledTask -TaskName $BackupTaskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $BackupTaskName -Confirm:$false }
    Register-ScheduledTask -TaskName $BackupTaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "MF Analyser daily backup to $BackupDir" | Out-Null
}

# ---- start and verify ---------------------------------------------------------------------
Write-Step "Start"
if ($DryRun) {
    Write-Host "    would: start $ServiceName and poll http://127.0.0.1:$Port/api/health for 60 s" -ForegroundColor DarkGray
} else {
    Start-App $ServiceName
    $health = Wait-Healthy -Port $Port -Seconds 90
    if ($health) { Write-Ok "healthy: status=$($health.status) version=$($health.version)" }
    else {
        Write-Fail "no answer on http://127.0.0.1:$Port/api/health after 90 s. Read $logDir\mf-analyser.log and $logDir\service.err.log, then run deploy\status.ps1."
        exit 1
    }
}

# ---- the URL to share ---------------------------------------------------------------------
Write-Step "Open it from another machine"
$hostName = $env:COMPUTERNAME
$fqdn = try { [Net.Dns]::GetHostEntry($hostName).HostName } catch { $hostName }
Write-Host ""
Write-Host "    Type this in a browser on any PC on the office network:" -ForegroundColor White
Write-Host ""
Write-Host "        http://$($hostName.ToLower()):$Port/" -ForegroundColor Green
if ($fqdn -and $fqdn -ne $hostName) { Write-Host "        http://$($fqdn.ToLower()):$Port/" -ForegroundColor Green }
$addresses = @(Get-LanAddresses)
foreach ($a in $addresses) { Write-Host "        http://$($a.IPAddress):$Port/    (if the name does not resolve)" -ForegroundColor Green }
Write-Host ""
$dhcp = $addresses | Where-Object { $_.PrefixOrigin -eq "Dhcp" }
if ($dhcp) {
    Write-Warn2 "This machine gets its address by DHCP ($($dhcp.IPAddress -join ', ')). Ask IT for a DHCP reservation or a static address so the numeric URL never changes; the name-based URL keeps working either way."
}
Write-Host "    Then sign in with the shared password. Print deploy\CHECKLIST.md and work through it."
Write-Host ""
