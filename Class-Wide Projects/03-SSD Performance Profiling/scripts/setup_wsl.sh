#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
sudo apt-get update
sudo apt-get install -y fio python3 python3-venv python3-pip util-linux
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
fio --version
.venv/bin/python scripts/ssdbench.py --help
echo "Setup finished. Run the benchmark as your ordinary WSL user."
