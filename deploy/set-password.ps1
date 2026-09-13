# Change the shared password, then restart so it takes effect.
param([string]$ServiceName = "MFAnalyser")
. "$PSScriptRoot\common.ps1"
Require-Elevated "Changing the password (the service restarts)"
$python = Get-PythonExe
if (-not $python) { Write-Fail "backend\.venv is missing; run deploy\install.ps1"; exit 1 }
Push-Location $BackendDir
try {
    & $python -m app.tools.set_password --config-file $ConfigFile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally { Pop-Location }
& "$PSScriptRoot\restart.ps1" -ServiceName $ServiceName
