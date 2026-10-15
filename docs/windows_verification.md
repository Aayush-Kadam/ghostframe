# Windows setup and verification

Native Windows Python3.12 tests, fresh installation, CLI and browser workflows have been executed. Exact build and results are recorded in the M9-RC report. PowerShell setup accepts -PythonExe and -NpmCli for portable runtimes. Python>=3.11 and Node/npm (frontend build only) are prerequisites; compiled assets work without Node.

Use the direct .venv/Scripts/python.exe paths in README if activation is blocked. Do not change system execution policy. Mypy may be blocked by Windows Application Control; preserve that result and do not evade the restriction. Other platforms/Python3.11 remain guidance/configuration unless an actual executed result is supplied.
