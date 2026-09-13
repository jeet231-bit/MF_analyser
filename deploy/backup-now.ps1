# Take a backup right now (the same thing the 02:00 task does). Safe while the app runs.
param([int]$Keep = 30)
. "$PSScriptRoot\common.ps1"
$python = Get-PythonExe
if (-not $python) { Write-Fail "backend\.venv is missing; run deploy\install.ps1"; exit 1 }
$env:MFA_CONFIG_FILE = $ConfigFile
Push-Location $BackendDir
try {
    & $python -m app.tools.backup --keep $Keep
    if ($LASTEXITCODE -ne 0) { Write-Fail "backup failed"; exit 1 }
} finally { Pop-Location }
