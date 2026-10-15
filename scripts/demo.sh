#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
.venv/bin/python -m ghostframe.cli demo
.venv/bin/python -m ghostframe.cli serve
