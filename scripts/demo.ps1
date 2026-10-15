param([string]$PythonExe = ".\.venv\Scripts\python.exe", [string]$Database = ".ghostframe\ghostframe.db")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
& $PythonExe -m ghostframe.cli --db $Database demo
if ($LASTEXITCODE -ne 0) { throw "Demo failed" }
