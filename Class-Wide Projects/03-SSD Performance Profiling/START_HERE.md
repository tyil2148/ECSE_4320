# Start here

This is **Project 3 SSD Performance Profiling**. Read `README.md` before the write tests. The report with results left blank is `report/SSD_Performance_Profiling_Report.docx`.

1. Confirm WSL2 with `wsl.exe --list --verbose` in Windows PowerShell.
2. Put this project under your WSL Linux home, e.g. `~/ssd_profiling`, rather than `/mnt/c`.
3. Collect host metadata using `scripts/collect_host.ps1` in Windows and fill `config/operator_notes.json`. Identify the physical SSD and the volume hosting the WSL VHDX. Check actual host free space.
4. In WSL, from this project directory:

```bash
bash scripts/setup_wsl.sh

# Review settings without running the I/O tests.
.venv/bin/python scripts/ssdbench.py plan --profile full --out plans/full

# This writes one owned disposable file; use a new or completely empty directory.
.venv/bin/python scripts/ssdbench.py init --target-dir ~/ssdbench-data --size 16GiB

# Check the pipeline first.
.venv/bin/python scripts/ssdbench.py run --profile smoke \
  --target-dir ~/ssdbench-data --out results/smoke_01

# Run once. Three trials at each setting are already included.
.venv/bin/python scripts/ssdbench.py run --profile full \
  --target-dir ~/ssdbench-data --out results/full_01 \
  --host-metadata config/host_metadata.json --notes config/operator_notes.json
```

If host metadata could not be collected, omit its option and document what is unavailable. Never pass an SSD, partition, or valuable file as a fio target. The runner accepts only its owned test directory.

The default full suite takes about two hours plus startup and initialization. It can generate substantial writes; review the plan's exposure estimate before running. Keep AC power, cooling, power mode, and background activity consistent.

Plots are generated automatically. To regenerate them later:

```bash
.venv/bin/python scripts/ssdbench.py analyze --results results/full_01
.venv/bin/python scripts/ssdbench.py plot --results results/full_01
.venv/bin/python scripts/build_report.py --results results/full_01 \
  --output report/SSD_Performance_Profiling_With_Data.docx
```

Inspect `analysis/coverage.json` and `analysis/issues.csv`. Replace every TBD in your report with actual metadata or supported interpretation. Submit the completed report, code, configs, and actual raw/parsed results together. The starter package contains no target-laptop measurements.
