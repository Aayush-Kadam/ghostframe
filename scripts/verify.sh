#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check ghostframe tests scripts
.venv/bin/python -m mypy ghostframe
