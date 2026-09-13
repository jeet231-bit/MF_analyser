# Wrapper used by the Scheduled Task route: runs the API in the foreground and appends its
# output to the service logs. NSSM installs do not use this file.
param([string]$ConfigFile = "C:\MFAnalyser\config.env")
. "$PSScriptRoot\common.ps1"

$env:MFA_CONFIG_FILE = $ConfigFile
$env:PYTHONUNBUFFERED = "1"
$script:ConfigFile = $ConfigFile
$port = Get-Port
$logDir = Join-Path (Get-DataDir) "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$python = Get-PythonExe
if (-not $python) { throw "backend\.venv is missing; run deploy\install.ps1" }
Set-Location $BackendDir
& $python -m uvicorn app.main:app --host 0.0.0.0 --port $port --workers 1 2>&1 |
    ForEach-Object { "$(Get-Date -Format s) $_" } |
    Out-File -FilePath (Join-Path $logDir "service.out.log") -Append -Encoding utf8
exit $LASTEXITCODE
