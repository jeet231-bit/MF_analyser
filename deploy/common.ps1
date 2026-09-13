# Shared helpers for the deploy scripts. Dot-source it: . "$PSScriptRoot\common.ps1"
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:BackendDir = Join-Path $RepoRoot "backend"
$script:FrontendDir = Join-Path $RepoRoot "frontend"
$script:DefaultRoot = "C:\MFAnalyser"
$script:ConfigFile = Join-Path $DefaultRoot "config.env"
$script:NssmExe = Join-Path $PSScriptRoot "tools\nssm.exe"
$script:NssmHashFile = Join-Path $PSScriptRoot "tools\nssm.sha256"

function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "    OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "    !!  $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "    XX  $Text" -ForegroundColor Red }

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Require-Elevated([string]$What) {
    if (-not (Test-Elevated)) {
        Write-Fail "$What needs an elevated PowerShell. Right-click PowerShell, 'Run as administrator', and run this again."
        exit 1
    }
}

function Test-OneDrivePath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if ($full -match "(?i)onedrive") { return $true }
    foreach ($name in "OneDrive", "OneDriveCommercial", "OneDriveConsumer") {
        $root = [Environment]::GetEnvironmentVariable($name)
        if ($root -and $full.StartsWith([IO.Path]::GetFullPath($root), [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Read-ConfigValue([string]$Key, [string]$File = $script:ConfigFile) {
    if (-not (Test-Path $File)) { return $null }
    foreach ($line in Get-Content $File) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.*)$") { return $Matches[1].Trim() }
    }
    return $null
}

function Set-ConfigValue([string]$Key, [string]$Value, [string]$File = $script:ConfigFile) {
    $lines = @()
    if (Test-Path $File) { $lines = @(Get-Content $File) }
    $done = $false
    $out = foreach ($line in $lines) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=") { $done = $true; "$Key=$Value" } else { $line }
    }
    $out = @($out)
    if (-not $done) { $out += "$Key=$Value" }
    New-Item -ItemType Directory -Force (Split-Path $File) | Out-Null
    [IO.File]::WriteAllLines($File, [string[]]$out, (New-Object Text.UTF8Encoding $false))
}

function Get-PythonExe {
    $venv = Join-Path $script:BackendDir ".venv\Scripts\python.exe"
    if (Test-Path $venv) { return $venv }
    return $null
}

function Get-Port {
    $p = Read-ConfigValue "MFA_PORT"
    if ($p) { return [int]$p } else { return 8000 }
}

function Get-DataDir {
    $d = Read-ConfigValue "MFA_DATA_DIR"
    if ($d) { return $d } else { return (Join-Path $script:DefaultRoot "data") }
}

function Get-BackupMirror {
    $d = Read-ConfigValue "MFA_BACKUP_MIRROR"
    if ($d) { return $d } else { return $null }
}

# The GTK3 runtime WeasyPrint needs for PDF export: on PATH or in its default install folder.
function Find-Gtk {
    $dll = "libgobject-2.0-0.dll"
    foreach ($dir in ($env:Path -split ";") + @("C:\Program Files\GTK3-Runtime Win64\bin")) {
        if ($dir -and (Test-Path (Join-Path $dir $dll))) { return (Join-Path $dir $dll) }
    }
    return $null
}
$script:GtkInstallerUrl = "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases"

function Get-BackupDir {
    $d = Read-ConfigValue "MFA_BACKUP_DIR"
    if ($d) { return $d } else { return (Join-Path $script:DefaultRoot "backups") }
}

function Get-ServiceMode([string]$ServiceName) {
    if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) { return "service" }
    if (Get-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue) { return "task" }
    return $null
}

function Start-App([string]$ServiceName) {
    switch (Get-ServiceMode $ServiceName) {
        "service" { Start-Service -Name $ServiceName }
        "task" { Start-ScheduledTask -TaskName $ServiceName }
        default { throw "Nothing named '$ServiceName' is installed. Run deploy\install.ps1 first." }
    }
}

function Stop-App([string]$ServiceName) {
    switch (Get-ServiceMode $ServiceName) {
        "service" { Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue }
        "task" {
            Stop-ScheduledTask -TaskName $ServiceName -ErrorAction SilentlyContinue
            # The task wrapper starts python as a child; make sure the listener is gone too.
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
                Where-Object { $_.CommandLine -match "uvicorn app\.main:app" } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
    }
}

function Get-AppState([string]$ServiceName) {
    switch (Get-ServiceMode $ServiceName) {
        "service" { return (Get-Service -Name $ServiceName).Status.ToString() }
        "task" { return (Get-ScheduledTask -TaskName $ServiceName).State.ToString() }
        default { return "not installed" }
    }
}

function Wait-Healthy([int]$Port, [int]$Seconds = 60) {
    $url = "http://127.0.0.1:$Port/api/health"
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod -Uri $url -TimeoutSec 5
            if ($r.status) { return $r }
        } catch { Start-Sleep -Seconds 2 }
    }
    return $null
}

function Get-LanAddresses {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -ne "WellKnown" } |
        Sort-Object InterfaceMetric, IPAddress
}
