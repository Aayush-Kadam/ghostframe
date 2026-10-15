param([string]$PythonExe = ".\.venv\Scripts\python.exe", [string]$NpmCli = "")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$tempDir = Join-Path (Get-Location) ".ghostframe-temp"
New-Item -ItemType Directory -Force $tempDir | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir
foreach ($check in @(@("pytest", "-q"), @("ruff", "check", "ghostframe", "tests", "scripts", "examples"), @("mypy", "ghostframe"))) {
    & $PythonExe -m @check
    if ($LASTEXITCODE -ne 0) { throw "Verification failed: $($check[0])" }
}
Push-Location web
try {
    if ($NpmCli) { & node $NpmCli run build } else { & npm run build }
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
    if ($NpmCli) { & node $NpmCli test } else { & npm test }
    if ($LASTEXITCODE -ne 0) { throw "Frontend tests failed" }
} finally { Pop-Location }
