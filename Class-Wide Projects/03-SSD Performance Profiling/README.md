# SSD Performance Profiling

Advanced Computer Systems, Project 3. This package implements the supplied assignment and 185-point rubric using the **Flexible I/O Tester (fio)**. The editable report is in `report/SSD_Performance_Profiling_Report.docx`. All empirical results and conclusions are left for your laptop measurements.

Target system: AMD Ryzen 5 PRO 7530U with Radeon Graphics, advertised base 2.00 GHz, Windows 11 x64, and a Linux distribution under **WSL2**. The CPU does not identify the SSD. Record its actual model, firmware, capacity, interface, and the Windows volume containing the WSL virtual disk.

## 1 Set up WSL2 and files

In Windows PowerShell, confirm that the chosen distribution shows VERSION 2:

```powershell
wsl.exe --list --verbose
wsl.exe --version
```

Extract the package, then put it inside your Linux home directory, for example `~/ssd_profiling`. Run the experiments against a dedicated directory such as `~/ssdbench-data`, inside the WSL Linux filesystem. Microsoft recommends this location for Linux workloads instead of `/mnt/c` [2]. The runner rejects Windows shares, RAM filesystems, and several other unsuitable paths.

```bash
cd ~/ssd_profiling
bash scripts/setup_wsl.sh
.venv/bin/python scripts/ssdbench.py inspect --target-dir ~/ssdbench-data
```

The setup script installs Ubuntu/Debian packages with `sudo`; **run all benchmark commands as your normal WSL user**. Python 3.10 or newer is required. Never install fio through pip: the similarly named Fiona command is unrelated. The runner checks for `fio-3.x` and requires successful direct I/O; it never silently switches to buffered I/O.

## 2 Record the host and conditions

From Windows PowerShell, run the supplied read-only collector, then copy its JSON into this project as `config/host_metadata.json`:

```powershell
powershell.exe -NoProfile -File .\scripts\collect_host.ps1 -OutputPath "$PWD\host_metadata.json"
```

It records available disk models, capacities, bus types, firmware, Windows/WSL versions, free space, power scheme, and optional reliability counters [4,5]. Some counters require permissions or are unavailable; missing temperature is a report limitation. To compare before and after, collect a second host snapshot under another name after the full run. Manually map your distribution's VHDX to its Windows volume and physical SSD.

Fill in `config/operator_notes.json`. Keep AC power, Windows power mode, laptop ventilation, WSL memory settings, and background activity consistent. Close unrelated I/O-heavy programs and avoid sleep or hibernation during the run. Record changes or interruptions. Keep enough free space on **both** the Windows volume hosting the VHDX and the Linux filesystem. A large free-space figure from Linux can describe the VHD maximum rather than actual host free space [3].

## 3 Review the plan before generating writes

The package includes 97 non-executed reference configs under `config/full_profile/`, using `/home/YOUR_USER/ssdbench-data` as a placeholder. Generate your own plan below; the guarded runner regenerates exact per-trial configs for your actual path.

```bash
.venv/bin/python scripts/ssdbench.py plan --profile full --out plans/full
```

This creates the full case matrix and reviewable `.fio` configurations without running I/O. The default full profile has **97 static cases and 8 adaptive tail cases, with 3 trials per case**. It includes 15 measured seconds plus 3 ramp seconds per ordinary case, 45 measured seconds per tail case, a 120-second write-state window, and 2-second pauses. Nominal workload time is about **122 minutes**, plus initialization, process startup, and cache warming.

This is a write-intensive experiment. The plan prints write-weighted runtime; at a hypothetical sustained 1 GiB/s for those write portions, the default schedule corresponds to about 3.4 TiB, including the 16 GiB initialization. This is an exposure illustration, not a prediction or hard write limit. Actual rates vary greatly by workload. Increasing runtime, trials, or the state window increases write volume. `analysis/coverage.json` reports measured guest write bytes, excluding ramps and initialization. These are not physical NAND writes or a SMART endurance measurement.

## 4 Initialize one owned disposable file

**Never point fio at a partition or a file containing valuable data.** This implementation accepts only a dedicated directory and creates its own `workload.bin`. It refuses pre-existing unmanaged contents, device paths, symlinks, hard links, and changed file identities. It does not expose a raw-device mode.

```bash
.venv/bin/python scripts/ssdbench.py init --target-dir ~/ssdbench-data --size 16GiB
```

The directory must be new or completely empty. Initialization performs one full sequential direct-I/O write and a final flush before reads are allowed. This avoids using unwritten sparse regions as data. It initializes the tested file; it does not establish a fresh or steady-state physical drive. The same file is reused for smoke and full runs. Change `16GiB` only if free space requires it, and record the chosen size. Sizes must be multiples of 8 MiB and at least 64 MiB; 64 MiB is for development, not a representative working set.

## 5 Check the pipeline, then collect real data

```bash
.venv/bin/python scripts/ssdbench.py run \
  --profile smoke --target-dir ~/ssdbench-data --out results/smoke_01

.venv/bin/python scripts/ssdbench.py run \
  --profile full --target-dir ~/ssdbench-data --out results/full_01 \
  --host-metadata config/host_metadata.json --notes config/operator_notes.json
```

Smoke covers representative settings with short runs and one trial. It **does not satisfy the full matrix or repetition requirements**. Run the full command once: it already performs three trials at every setting. For five trials, add `--trials 5` before starting. Choose a new output directory for an independent repeat. Do not run two benchmarks on the same SSD at once, even if they use different files.

The runner automatically parses completed results and generates all applicable PNG/PDF plots. If a run is interrupted, keep the files and resume with the **identical command**, adding `--resume`. Resume checks the target identity, settings, source hashes, fio version, and retained raw hashes. A failed attempt remains archived and is retried under a new name. If plots fail because a package is missing, install requirements and regenerate them; the measurements remain intact.

Optional overrides, with effects recorded in the manifest:

```bash
# A longer observation window can reveal changes hidden by short tests.
# This performs additional writes and does not guarantee steady state.
.venv/bin/python scripts/ssdbench.py run --profile full \
  --target-dir ~/ssdbench-data --out results/full_longer \
  --runtime 30 --tail-seconds 90 --state-seconds 300 --trials 3
```

Use `--families baseline,block,...` or `--depths 1,2,4,8,16,32,64` only for deliberate subsets or unsupported high depths. Include `queue` with `tail`; the latter is adaptive. Document omissions, and do not label a subset as complete rubric coverage. `--size` on run must match the owned file. The CLI's `--help` lists every option.

## 6 Regenerate analysis, plots, and a populated report copy

```bash
.venv/bin/python scripts/ssdbench.py analyze --results results/full_01
.venv/bin/python scripts/ssdbench.py plot --results results/full_01
.venv/bin/python scripts/build_report.py --results results/full_01 \
  --output report/SSD_Performance_Profiling_With_Data.docx
```

The report builder inserts available tables and figures into a **new** report copy and retains interpretation prompts. Your supplied report remains editable in Word. Add the measured hardware metadata, discuss the actual curves and any diagnostics, and replace every `TBD` before submission. The builder's output-path check avoids overwriting your edited report. Optional report generation uses `python-docx`, already in requirements. Tail tables contain p50, p95, p99, and p99.9; all use completion latency histograms, not percentiles of one-second mean latency logs.

## 7 What gets saved

| Location | Contents |
| --- | --- |
| `plan.json`, `cases.csv` | Exact knobs and schedule parameters; adaptive tail rules |
| `manifest.json` | CPU/kernel/mount/fio metadata, operator notes, source hashes, target identity |
| `configs/` | Exact per-attempt fio configs, including cache warm passes |
| `raw/` | Unmodified fio JSON+, stderr, and auxiliary stdout for every attempt |
| `journal.jsonl` | Actual execution order, trial seeds, status, commands, elapsed time, raw SHA256 |
| `telemetry/` | Before/after temperature sensors, memory, disk counters, free-space snapshots |
| `adaptive_tails.json` | Selected middle and near-knee depths, or highest-tested fallback with reason |
| `analysis/` | Trial metrics, repeated-trial summaries, histograms, depth buckets, time series, knees, Little's Law, maxima, diagnostics, coverage, and table snippets |
| `plots/` | 13 figures in PNG and PDF for the full suite |

Submit your filled report together with **the code and your actual results directory**. Generated raw results are intentionally absent from the starter package. `docs/RUBRIC_MAP.md` maps every rubric row to its implementation and final evidence.

## 8 How to interpret WSL results

WSL2 stores the distribution in an ext4 virtual disk [3]. Here the measured path includes fio, the Linux filesystem, the guest virtual block device, host storage layers, and the SSD. `direct=1` requests bypass of the guest page cache; it does not establish bypass of every host cache or prove durable NAND writes. The write tests use completion without per-I/O fsync, so do not interpret their latency as power-loss-safe commit latency. The report explicitly limits its conclusions to the observed WSL storage path.

Watch `analysis/issues.csv` and `analysis/coverage.json`. Requested QD can differ from achieved occupancy. fio's highest depth histogram bucket is `>=64`, so that bucket alone cannot prove QD 128 or 256. Throughput divided by block size gives IOPS for fixed-size operations; a larger block can raise MB/s while reducing IOPS. MiB/s is bytes/s divided by 2^20; MB/s is divided by 10^6. Both are retained in CSV.

## 9 Cleanup and troubleshooting

After copying or archiving the results, delete only the managed disposable data file:

```bash
.venv/bin/python scripts/ssdbench.py cleanup \
  --target-dir ~/ssdbench-data --delete-owned-file
```

Initialization evidence is retained, so this directory is no longer empty. Use a new empty directory for a new initialization. Deleting data inside WSL does not necessarily shrink the host VHDX immediately. Do not manually delete or modify the VHDX.

| Problem | Action |
| --- | --- |
| `No module named matplotlib` | `.venv/bin/python -m pip install -r requirements.txt`, then rerun `plot` |
| fio version is not `fio-3.x` | Install Ubuntu `fio`; pass `--fio /usr/bin/fio` if another program shadows it |
| Direct I/O or libaio fails | Check WSL2, target mount, fio stderr, and Linux-local path. Do not change direct=1 to bypass the failure |
| Target remains uninitialized | Inspect `initialize.json`/stderr; use guarded cleanup, then a new empty directory |
| Host disk space is low | Stop; check the Windows volume hosting the VHDX as well as Linux `df` |
| No knee is found | Report that the tested range did not establish a plateau; tails use the highest tested depth and say so |
| High p99.9 with few samples | Inspect per-trial counts; extend tail runs if appropriate and report uncertainty |
| Low achieved QD or CPU saturation | Inspect depth buckets, Little's Law estimates, guest CPU stats in raw JSON, and host activity before attributing a bottleneck to the SSD |

## Verification

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Unit tests check safety guards, the matrix, region alignment, mixed I/O accounting, histogram merging, repeated-trial statistics, and the knee fallback. See `docs/VALIDATION.md` for validation performed on the delivered version and its environment limits.

## References

1. fio project, [official fio documentation](https://fio.readthedocs.io/en/latest/fio_doc.html), including direct I/O, iodepth, JSON+, and logging.
2. Microsoft, [Working across Windows and Linux file systems](https://learn.microsoft.com/en-us/windows/wsl/filesystems).
3. Microsoft, [How to manage WSL disk space](https://learn.microsoft.com/en-us/windows/wsl/disk-space).
4. Microsoft, [Get-PhysicalDisk](https://learn.microsoft.com/en-us/powershell/module/storage/get-physicaldisk).
5. Microsoft, [Get-StorageReliabilityCounter](https://learn.microsoft.com/en-us/powershell/module/storage/get-storagereliabilitycounter).

## AI use

OpenAI ChatGPT generated the starter implementation, documentation, analysis code, and report structure from the supplied assignment. The student must run the laptop experiments, inspect raw data and diagnostics, verify generated statements, and write the final empirical interpretation. No target-laptop results or performance claims are supplied.
