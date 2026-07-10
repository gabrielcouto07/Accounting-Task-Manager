$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$hostName = if ($env:APP_HOST) { $env:APP_HOST } else { "0.0.0.0" }
$port = if ($env:APP_PORT) { $env:APP_PORT } else { "8000" }
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m uvicorn app.main:app --host $hostName --port $port
