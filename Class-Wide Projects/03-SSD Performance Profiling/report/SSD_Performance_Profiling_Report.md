# SSD Performance Profiling

Advanced Computer Systems Project 3

Author  [TBD]     Course section  [TBD]     Measurement date  [TBD]

## 1 Objective and scope

This project characterizes how block size, access pattern, read/write mix, queue depth, worker count, and address range affect storage throughput and latency. It measures QD 1 baselines, maximum observed small-block IOPS and sequential bandwidth, the throughput versus latency tradeoff, and completion-latency tails. The experiment also tests a warm-page-cache pitfall and observes performance during sustained writes.

The target is a Windows 11 laptop using WSL2. The measurements characterize its complete virtualized storage path. The physical SSD model and interface must be established from host metadata before drawing device-specific conclusions.

### System and storage metadata

| Item | Configuration |
| --- | --- |
| Processor | AMD Ryzen 5 PRO 7530U with Radeon Graphics; advertised base 2.00 GHz |
| Host operating system | Windows 11 x64; build [TBD] |
| WSL environment | WSL version, Linux distribution, kernel, visible CPUs, memory and swap [TBD] |
| Physical SSD | Model, firmware, capacity, bus and link details [TBD] |
| Test path and filesystem | [TBD]; planned owned file under ~/ssdbench-data on Linux ext4 |
| Storage mapping | Windows volume hosting the distribution VHDX and its physical SSD [TBD] |
| Capacity and state | Test range [TBD]; host and guest free capacity before/after [TBD] |
| Power and temperature | AC power, Windows power mode, cooling, SSD temperature or unavailable [TBD] |

### Safety and initialization

The runner creates only its own disposable regular file in a new or empty directory. It refuses device paths, symbolic links, hard links, unmanaged files, and changed file identities. One full sequential direct-I/O write with a final flush initializes the tested range before reads. No raw partition, trim, or secure-erase operation is used. This is file preparation, not full-drive preconditioning.

## 2 Experimental design

The full profile uses the matrix below. The planned total file size is 16 GiB. Each ordinary run has a 3-second ramp and 15 measured seconds; each case is repeated three times. Tail runs have 45 measured seconds, and the state observation lasts 120 seconds with no ramp. The actual values and any overrides are retained in manifest.json.

| Experiment | Varied setting | Fixed settings | Cases |
| --- | --- | --- | --- |
| QD 1 baseline | Read/write; random/sequential | 4 KiB random or 128 KiB sequential; one worker | 4 |
| Block size | 4, 16, 32, 64, 128, 256 KiB; both patterns; read/write | QD 16; one worker | 24 |
| Read/write mix | 100/0, 70/30, 50/50, 0/100 | 4 KiB random or 128 KiB sequential; QD 16 | 8 |
| Queue depth | 1, 2, 4, 8, 16, 32, 64, 128, 256 | Four baseline workloads; one worker | 36 |
| Workers | 1, 2, 4, 8 workers | Aggregate QD 16 or 64; random 4 KiB read/write | 16 |
| Address range | 1/16, 1/4, full file | Random 4 KiB read/write; QD 16 | 6 |
| Cache pitfall | Direct or buffered | Warmed range; random 4 KiB reads; psync; QD 1 | 2 |
| State observation | Elapsed time in write window | Sequential 128 KiB write; QD 32 | 1 |
| Adaptive tails | Middle and near-knee QD | Four baseline workloads; one worker | 8 |

The matrix has 97 static cases and eight adaptive cases, giving 315 measured runs at three trials. The default schedule takes about 122 minutes plus initialization, process startup, and cache warming. It is write intensive; the plan displays write exposure before execution. A smoke profile checks operation with fewer settings and does not establish full rubric coverage.

### Controls and execution order

Main experiments use libaio, direct=1, aligned fixed-size transfers, and fio-generated incompressible buffers. Workers use disjoint regions while holding the total address range constant. The pitfall uses psync for both controls to isolate the direct-I/O setting. Payload refill can consume CPU and is part of this workload. Writes measure completion without per-operation fsync.

Each trial visits the experiment families in the table order, with deterministically shuffled cases within each static family. Tail depths are selected after all queue trials. Trial-specific random seeds and actual execution order are recorded. A two-second pause separates measured runs. Shared drive history, prior writes, and incomplete thermal recovery remain possible sources of dependence.

## 3 Code structure and reproducibility

| Component | Responsibility |
| --- | --- |
| scripts/ssdbench.py | Entry point for inspect, init, plan, run, analyze, plot, and cleanup |
| ssdbench/plan.py | Case matrix, alignment, disjoint worker ranges, and fio configuration generation |
| ssdbench/safety.py | Ownership marker, file identity checks, locking, and guarded deletion |
| ssdbench/runner.py | Initialization, trials, exact commands, failures, checkpoints, resume, and adaptive tails |
| ssdbench/analysis.py | Unit conversion, directional metrics, merged histograms, trial statistics, knee rule and coverage |
| ssdbench/plotting.py | Labeled figures with units and repeated-trial SD bars where applicable |
| ssdbench/environment.py | Guest kernel, CPU, mount, memory, disk-counter and available temperature records |
| scripts/collect_host.ps1 | Read-only Windows disk, power, free-space and optional reliability metadata |
| scripts/build_report.py | Editable report generation and optional insertion of measured tables and figures |
| tests/test_project.py | Safety, matrix completeness, aggregation, quantiles, statistics and knee selection checks |

### Workflow

Inspect the WSL mount and host storage mapping, fill operator notes, and review the generated plan. Initialize the disposable file once. Check the smoke profile, then run the full profile once; that command already includes repeated trials. Preserve the output directory, regenerate analysis and figures as needed, and add the empirical interpretation to this report. Resume uses the same command plus --resume and verifies settings, source hashes, fio version, target identity, and retained raw hashes. The Windows collector uses the disk and reliability interfaces documented by Microsoft [4, 5].

### Data hygiene

Each attempt retains its exact fio configuration, unmodified JSON+ output, stderr, auxiliary stdout, command, seed, elapsed time, and SHA256 hash. The journal records actual order and status. Before/after snapshots retain available guest temperatures, memory and disk counters. Failed attempts stay archived and are excluded from analysis. The latest valid completed attempt for each case and trial is used once. No measured outlier is silently discarded.

analysis/coverage.json identifies missing runs and pending adaptive cases. analysis/issues.csv flags invalid data, unusually low queue occupancy estimates, read/write-mix deviations, and small p99.9 sample counts. All submitted plots and tables must be traceable to the retained raw outputs. Host metadata, operator notes, and any unavailable sensors complete the environment record.

## 4 Analysis framework

### Metrics and aggregation

IOPS counts requests per second. Throughput is retained as MiB/s = bytes/s divided by 2^20 and MB/s = bytes/s divided by 10^6. For a fixed block size, bytes/s is approximately IOPS times bytes/request. Larger blocks can increase bandwidth while reducing request rate, so the two metrics must be interpreted together.

Curves use mean total latency. Baseline and tail percentiles use completion latency, clat; submission latency, slat, is retained separately. Means are weighted by completed-I/O counts across workers and read/write directions. Aggregate percentiles come from merged JSON+ completion-histogram counts. fio bins have finite resolution and are represented by midpoint values [1]. One-second latency logs contain means and are not used to estimate tails.

Tables retain each trial plus its mean, median, sample SD, minimum, and maximum. Plot error bars show mean plus/minus between-trial sample SD when at least two trials exist. SD is neither a confidence interval nor an individual-I/O percentile. Per-trial N is reported with p99.9; N below 100000 gives fewer than 100 expected observations beyond that percentile and receives a diagnostic note.

### Queueing and the knee

Little's Law relates average work in the system to throughput and residence time: L = lambda W. Using aggregate IOPS and mean completion latency in seconds estimates work within fio's submitted-I/O boundary. The total-latency version also includes submission. For a mixed workload, L is approximately lambda_read W_read + lambda_write W_write. The configured cap is iodepth times numjobs; neither the cap nor this estimate establishes physical NAND concurrency.

The knee heuristic uses median trial throughput for each workload. It selects the earliest adjacent QD pair where both reach at least 90% of peak observed throughput, the next point adds at most 10% throughput, and mean total latency rises at least 25%. It is a candidate for inspection, not proof of a physical-device limit. If no pair qualifies, the report must say the tested range did not establish a knee; tail comparisons then use the highest tested depth. The middle depth is the tested value nearest half the comparison QD.

### Mechanisms to evaluate

More concurrency can hide latency until a controller, media, interface, CPU, or virtualization limit dominates. Beyond saturation, additional work can increase waiting and tail latency while adding little throughput. Sequential locality, transfer overhead, random mapping work, and shared read/write resources may change the curve. Working-set size can change locality and cache reuse. These are explanations to test against the measurements, not experimental findings supplied in advance.

Flash updates typically write to new locations. Garbage collection can move valid data and erase blocks, competing with foreground requests. Fast SLC write caching can favor short write bursts; a longer write window may expose different behavior as cache space or temperature changes. Correlate any transition with elapsed time, bytes written, and available SSD sensors before assigning a cause.

Any interface-ceiling discussion must use the actual physical SSD bus and link. The processor model and guest virtual SCSI identity do not establish SATA, NVMe, or PCIe generation. The fio depth histogram is retained, but its highest bucket groups 64 and above; it cannot by itself prove achieved QD 128 or 256.

## 5 Baseline and block size results

Measured baseline values are entered below. All latencies are microseconds. The mean column uses total latency; percentile columns use completion latency. Add between-trial SD and trial count from summary.csv when reporting the final values.

| QD 1 workload | Mean total | p50 clat | p95 clat | p99 clat | p99.9 clat | n |
| --- | --- | --- | --- | --- | --- | --- |
| 4 KiB random read | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 KiB random write | TBD | TBD | TBD | TBD | TBD | TBD |
| 128 KiB sequential read | TBD | TBD | TBD | TBD | TBD | TBD |
| 128 KiB sequential write | TBD | TBD | TBD | TBD | TBD | TBD |

[Insert 01_baseline.png] Figure 1 QD 1 baseline means and completion percentiles for the four workloads

[TBD Compare read and write baselines and central versus tail latency. Explain that QD 1 minimizes application queueing but retains filesystem, virtualization, controller and device overhead.]

### Block size and access pattern

[Insert 02_blocksize.png] Figure 2 Throughput and mean total latency from the same block-size runs at QD 16

[Insert 03_block_iops.png] Figure 3 IOPS versus block size for random and sequential reads and writes

[TBD Identify the block sizes with the highest observed bandwidth and IOPS, distinguish MiB/s from MB/s, and compare random with sequential patterns. Explain any rise in bandwidth accompanied by lower IOPS using the fixed-size conversion. Discuss repeat variability rather than attributing every small difference to a device effect.]

Maximum observed random 4 KiB IOPS  Read [TBD]  Write [TBD]
Maximum observed sequential throughput  Read [TBD] MiB/s  Write [TBD] MiB/s
Case identifiers and fixed knobs for each maximum  [TBD]

Use analysis/maxima.csv to identify the maximum within the tested matrix. This is an observed profile maximum, not a manufacturer specification or proof of the device's absolute capability.

## 6 Mix queue depth and worker results

[Insert 04_mix.png] Figure 4 Read/write mix at fixed QD and block size within each pattern

[TBD Compare 100/0, 70/30, 50/50 and 0/100. Use achieved read fractions and separate read/write rows to explain any asymmetric latency effect. Evaluate possible controller or shared-media contention with evidence.]

[Insert 05_queue_tradeoff.png] Figure 5 Single throughput versus mean total latency curve with QD labels for all four workloads

[Insert 06_queue_scaling.png] Figure 6 Throughput and mean latency as configured QD increases

| Workload | Selected QD | Plateau assessment | Supporting throughput and latency |
| --- | --- | --- | --- |
| random read | TBD | TBD | TBD |
| random write | TBD | TBD | TBD |
| sequential read | TBD | TBD | TBD |
| sequential write | TBD | TBD | TBD |

[TBD Accept or qualify the heuristic candidate using adjacent points and SD. If no plateau is observed, state that the knee was not established in this range and identify the fallback depth. Explain whether the plateau could reflect host CPU, virtualization, interface or media limits; do not choose a cause without evidence.]

[Insert 07_little_law.png] Figure 7 IOPS times mean completion latency compared with configured aggregate QD

Numeric Little's Law check  Workload and QD [TBD]; lambda [TBD] requests/s; W [TBD] us / 1000000; L [TBD] requests; configured QD [TBD]. Compare submitted and total-latency estimates and discuss underfilling, submission overhead, or nonstationarity. Use analysis/little_law.csv and per-job depth buckets.

[Insert 08_parallel.png] Figure 8 Worker count at fixed aggregate QD and fixed total address range

[TBD Compare one deep queue with several shallower workers at aggregate QD 16 and 64. Relate changes to CPU overhead or submission parallelism while checking achieved occupancy.]

## 7 Tail latency working set and device state

Completion percentiles below are microseconds and are mean per-trial percentile values. N is the mean completed-I/O count per trial; include its range and SD when interpreting a sparse tail. The comparison depth is near-knee only when the declared rule has evidence for a plateau.

| Workload and role | QD | p50 | p95 | p99 | p99.9 | Mean N |
| --- | --- | --- | --- | --- | --- | --- |
| random R mid | TBD | TBD | TBD | TBD | TBD | TBD |
| random R comparison | TBD | TBD | TBD | TBD | TBD | TBD |
| random W mid | TBD | TBD | TBD | TBD | TBD | TBD |
| random W comparison | TBD | TBD | TBD | TBD | TBD | TBD |
| sequential R mid | TBD | TBD | TBD | TBD | TBD | TBD |
| sequential R comparison | TBD | TBD | TBD | TBD | TBD | TBD |
| sequential W mid | TBD | TBD | TBD | TBD | TBD | TBD |
| sequential W comparison | TBD | TBD | TBD | TBD | TBD | TBD |

[Insert 09_tails.png] Figure 9 Completion-latency percentiles at middle and selected comparison QD

[Insert 10_tail_survival.png] Figure 10 Labeled pooled histogram survival curves across trials

[TBD Compare p99.9/p50 and p99/p50 across depths. State trial counts and any small-N diagnostics. Explain whether increased concurrency mainly changes central latency, tails, or both, and what that means for response-time-sensitive workloads.]

### Working set and observed write state

[Insert 11_working_set.png] Figure 11 Guest address-range effects at random 4 KiB and QD 16

[Insert 12_state.png] Figure 12 Throughput and mean completion latency during each sustained write window

[TBD Record tested ranges, compare IOPS and p99, and explain that guest address windows do not select physical flash LBAs. For each state trial, compare first and last thirds using state_windows.csv. Pair changes with available SSD temperature or host reliability observations. If no change occurs, limit the conclusion to this duration and range.]

## 8 Misleading setup and limitations

### Warm buffered reads as an SSD benchmark pitfall

The controlled pitfall experiment uses a finite buffered sequential read to warm the same initialized 256 MiB or smaller range before each case. Both measured cases use random 4 KiB reads, psync, QD 1, one worker, and the same range. Only direct=1 versus direct=0 changes. Holding the engine constant avoids confusing the cache effect with asynchronous submission overhead.

[Insert 13_pitfall.png] Figure 13 Direct and warmed buffered reads under the same synchronous workload

Buffered reads can be satisfied from guest RAM, so presenting their request rate as physical SSD IOPS can be misleading. A cache benefit depends on effective cache residency and the storage layers involved. If the two controls are similar, check whether warming completed, whether the range fits available memory, and whether host/virtualization overhead dominates. No global page-cache flush is performed. direct=1 concerns the guest cache and cannot certify the behavior of every host cache.

[TBD Report each control's IOPS and latency with trial variation, compute buffered/direct IOPS, and explain the observed direction and size of the effect. State whether the experiment demonstrated an effect or only bounded it.]

### Storage path and durability

WSL2 stores a distribution in an ext4 virtual hard disk [3]. This experiment includes the Linux filesystem, virtual disk and host storage layers. Linux-local storage avoids the separate Windows-mounted file path that Microsoft advises against for Linux performance work [2], but the results still describe a virtualized path. Physical SSD temperature, interface detail and hardware queue depth may not be exposed to the guest. Guest free space may reflect the VHD limit rather than actual remaining host capacity [3].

Write completion is measured without per-I/O fsync or a power-loss test. Consequently these write latencies do not establish durable NAND commit latency. The full-file initialization does not reset physical drive history or force a standardized steady state. Address ranges within a file are mediated by filesystem allocation, VHDX mapping and the flash translation layer.

### Attribution and uncertainty

SLC caching, garbage collection, thermal throttling, host caching, background I/O and CPU limits can produce similar changes. A throughput drop alone does not distinguish them. Use measured temperature and chronology where available, and label other explanations as hypotheses. The final part of a 120-second write window is an observed late window, not automatically a steady state. Shared drive history also limits independence between repeated trials.

[TBD List unavailable sensors, unexplained anomalies, incomplete settings, interruptions, CPU or memory pressure, and the limitations that materially affect the final conclusion.]

## 9 Conclusions and submission evidence

[TBD Summarize the measured QD 1 latency, maximum observed random IOPS and sequential bandwidth, knee or lack of one, and tail-latency tradeoff. Explain which tested settings best serve latency-sensitive and throughput-oriented work. State the strongest supported device-state observation and the effect of the misleading setup. Keep every numerical claim traceable to a case and acknowledge the WSL scope.]

### Rubric coverage

| Category | Points | Evidence |
| --- | --- | --- |
| Safety and QD 1 baselines | 30 | Owned-file guards, initialization evidence, metadata and Section 5 |
| Block size and patterns | 35 | Complete 24-case matrix; Figures 2 and 3; Section 5 |
| Mix and queue analysis | 40 | Mix/QD/worker sweeps, knee evidence and numeric Little's Law check; Section 6 |
| Tails and device state | 25 | p50/p95/p99/p99.9, N, ranges, state chronology and temperature limits; Section 7 |
| Reproducibility and hygiene | 25 | Configs, raw data, hashes, repeated trials, environment, diagnostics and coverage |
| AI and pitfall analysis | 15 | Disclosure below and controlled cache experiment; Section 8 |
| Report quality | 15 | Labeled figures, units, concise supported interpretation and limitations |
| Total | 185 | Final empirical evidence must accompany the implementation |

### AI use disclosure

OpenAI ChatGPT assisted in generating the experiment code, parsing and plotting routines, documentation, and report structure from the supplied assignment. The author is responsible for running the target-laptop experiments, verifying raw results and generated statements, and writing the final empirical interpretation. No target-laptop performance results are supplied in the starter report. Update this disclosure to reflect any additional assistance.

### References

[1] fio project. Official fio documentation. https://fio.readthedocs.io/en/latest/fio_doc.html

[2] Microsoft. Working across Windows and Linux file systems. https://learn.microsoft.com/en-us/windows/wsl/filesystems

[3] Microsoft. How to manage WSL disk space. https://learn.microsoft.com/en-us/windows/wsl/disk-space

[4] Microsoft. Get PhysicalDisk. https://learn.microsoft.com/en-us/powershell/module/storage/get-physicaldisk

[5] Microsoft. Get StorageReliabilityCounter. https://learn.microsoft.com/en-us/powershell/module/storage/get-storagereliabilitycounter

[6] Advanced Computer Systems. Project 3 SSD Performance Profiling assignment and 185-point grading rubric supplied with the project.
