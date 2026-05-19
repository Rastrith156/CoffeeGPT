$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $projectRoot "backend"
$venvPython = Join-Path $backendRoot "venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found. Run .\scripts\bootstrap_backend.ps1 first."
}

Push-Location $backendRoot
try {
    & $venvPython -m uvicorn main:app --host 0.0.0.0 --reload
}
finally {
    Pop-Location
}
