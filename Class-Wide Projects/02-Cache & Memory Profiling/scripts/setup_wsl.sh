#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v g++ >/dev/null || ! command -v python3 >/dev/null; then
    echo 'Install prerequisites: sudo apt update && sudo apt install build-essential python3 python3-venv'
    exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make
make test
echo 'Ready. See README.md for smoke and full-run commands.'
