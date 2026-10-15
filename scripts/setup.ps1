param([string]$PythonExe = "python", [string]$NpmCli = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$tempDir = Join-Path (Get-Location) ".ghostframe-temp"
New-Item -ItemType Directory -Force $tempDir | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir
if (-not (Test-Path -LiteralPath ".\.venv\Scripts\python.exe")) {
    & $PythonExe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed" }
}
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]" -c requirements-dev-windows.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& .\.venv\Scripts\python.exe -m ghostframe.cli doctor
if ($LASTEXITCODE -ne 0) { throw "Diagnostics failed" }
Push-Location web
try {
    if ($NpmCli) { & node $NpmCli ci } else { & npm ci }
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed" }
    if ($NpmCli) { & node $NpmCli run build } else { & npm run build }
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
} finally { Pop-Location }
