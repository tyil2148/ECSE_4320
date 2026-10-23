#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
profile="${1:-full}"
output="${2:-results/$(date -u +%Y%m%dT%H%M%SZ)}"
python3 scripts/build.py
python3 tests/test_correctness.py
python3 tests/test_analysis.py
python3 scripts/evidence.py
python3 scripts/run_experiments.py --profile "$profile" --out "$output" "${@:3}"
python3 scripts/analyze.py "$output"
python3 scripts/plot.py "$output"
printf 'Completed. Data and figures: %s\n' "$output"
