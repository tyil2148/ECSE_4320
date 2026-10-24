# Methodology and analysis contract

The default full suite uses one initialized 16 GiB disposable file, incompressible fio-generated buffers, block-aligned offsets, no per-I/O fsync, and `libaio` with `direct=1`. Initialization writes every byte once with a final flush. Payload refill work is part of the measured workload and can consume CPU. All worker clones use disjoint parts of the same fixed total address range. There are no trims, raw-device writes, secure erases, global page-cache drops, or automatic power-setting changes.

| Experiment | Varied | Fixed | Cases |
| --- | --- | --- | ---: |
| QD 1 baseline | Random 4 KiB and sequential 128 KiB; read or write | QD 1, one worker, entire file | 4 |
| Block size | 4, 16, 32, 64, 128, 256 KiB; random/sequential; read/write | QD 16, one worker, entire file | 24 |
| Mix | 100/0, 70/30, 50/50, 0/100 read/write | Random 4 KiB or sequential 128 KiB; QD 16 | 8 |
| Queue depth | 1, 2, 4, 8, 16, 32, 64, 128, 256 | Four baseline workloads, one worker | 36 |
| Worker count | 1, 2, 4, 8 workers | Aggregate QD 16 or 64; random 4 KiB read/write; total range constant | 16 |
| Working set | File size /16, /4, full size | Random 4 KiB read/write; QD 16, one worker | 6 |
| Cache pitfall | Direct versus buffered read | psync, QD 1, one worker, same warmed 256 MiB or smaller range | 2 |
| Device-state window | Time within a continuous 120 s write run | Sequential 128 KiB, QD 32, one worker, no ramp | 1 |
| Adaptive tails | Middle versus near-knee QD for each baseline workload | 45 s measured; entire file; one worker | 8 |

All counts are per trial. Three trials give 315 measured runs. For the ordinary cases, each run has 3 ramp seconds followed by 15 measured seconds. The state window has zero ramp so its early behavior is visible. Tail runs use 3 ramp seconds plus 45 measured seconds. All defaults and overrides are written to the manifest. Smoke is intentionally shorter and incomplete.

## Ordering and repeated trials

Each trial visits baseline, block size, mix, queue, worker count, working set, cache pitfall, and state families in that order. Case order is deterministically shuffled within each family. Trial-specific seeds vary the random sequence; fixed seeds make the selected sequence reproducible. The actual order and before/after observations are retained. Adaptive tails run after all static trials. Repeats share the same evolving physical drive state; they are repeated workload trials, not independent freshly erased drives. The two-second pause is a scheduling pause, not a thermal reset or SLC-cache recovery guarantee.

The parser produces per-trial values, arithmetic means, medians, sample standard deviations, and minima/maxima. Plots use mean plus/minus sample SD for n >= 2; one-trial plots have no empirical SD bar. Between-trial SD is neither a confidence interval nor the spread of individual I/O latencies. Temporal samples are not substituted for independent repetitions. Raw outliers are retained; none are silently removed.

## Latency and Little's Law

`slat` is fio submission latency, `clat` is completion latency after submission, and `lat` is total latency. Curves use mean total latency. Baseline and tail percentiles use `clat`. Completed-I/O counts weight means across workers and read/write directions. The program merges JSON+ completion-histogram counts for aggregate quantiles rather than averaging worker percentiles. Histogram bins are represented by their midpoints, so quantiles have fio's histogram resolution. Mixed workloads retain read, write, and total rows.

For a stationary measurement interval, Little's Law is L = lambda W. The submitted-I/O estimate uses lambda = aggregate IOPS and W = mean completion latency in seconds. A second estimate uses mean total latency to include submission. For mixed work, L is approximately lambda_read W_read + lambda_write W_write. The configured upper limit is iodepth times numjobs; it need not equal observed occupancy, and neither value identifies physical NAND concurrency. fio's depth buckets are retained separately; the `64` bucket covers 64 and above. No exact occupancy above 64 is inferred from it.

## Knee selection

Use only valid repeated-trial queue runs for the same workload. Sort by QD and examine median throughput and median mean total latency. The candidate is the earliest adjacent pair for which both points reach at least 90% of the observed maximum throughput, the next point adds at most 10% throughput, and latency grows at least 25%. This is a declared heuristic for the observed storage path. Inspect variability, nonmonotonic behavior, and the figures before accepting the candidate. It does not prove a controller bottleneck.

If no adjacent pair passes, state that no knee was established within the tested range. Tail runs then label the comparison point `highest_tested`, not `near_knee`. The middle point is the tested depth closest to half the comparison QD, with a minimum of one. A knee at QD 1 can make both comparisons use QD 1; retain that fact instead of inventing distinct depths. Tail role labels and selection evidence are saved in `adaptive_tails.json`.

## Tail statistics

Report p50, p95, p99, p99.9, mean, N, and between-trial variation. A trial with N < 100000 has fewer than 100 expected observations beyond p99.9 and receives a diagnostic note. Longer measurement helps sampling but does not remove systematic bias or prove independence. Histograms can be pooled for a labeled survival plot; mean per-trial percentile values in tables remain a different statistic. Never compute percentiles of the one-second mean-latency time series.

## Device state and the cache pitfall

Working-set tests vary an address window within the file. That is an indirect guest-address-range experiment, not a claim to select physical SSD LBAs; the filesystem, VHDX, and flash translation layer mediate mapping. Controller caching, translation locality, free capacity, previous writes, and garbage collection can influence performance. The 120-second state run compares first and last thirds of one observation window. A fall in throughput may be consistent with SLC exhaustion, thermal throttling, or background work, but these explanations require corroborating temperature/SMART and timing evidence. Absence of a change only establishes what this duration and range exposed. Do not call the start a factory-fresh state or the end a proven steady state.

The misleading-setup experiment warms an initialized range with a finite buffered sequential read before each measured control. Both cases then perform random 4 KiB reads with psync, QD 1, one worker, and the same range. Only `direct` changes. A fast buffered read can be a RAM/cache result that would overstate storage performance if presented as SSD IOPS. A benefit is not guaranteed when the range does not fit the effective guest cache or other layers dominate. Direct I/O addresses guest caching only. No global drop_caches operation is used.

## Interpretation boundaries

State-window comparisons weight each logged interval mean by its time overlap with the first or last third of the configured measurement horizon. A tiny final interval or queue drain after runtime is retained in raw logs and plots but does not receive a full second's weight in the window comparison. An end-of-run spike alone is not evidence of thermal throttling or SLC exhaustion.

QD 1 is a minimum-queue baseline, not a measurement without all queues or overhead. At low QD, concurrency may hide storage latency and raise throughput. Near saturation, more work often raises waiting time with small throughput gains. Larger transfers can improve bytes/s through amortization while lowering requests/s; IOPS and bandwidth answer different questions. Sequential patterns may exploit locality and controller scheduling; random traffic can stress mapping and small-transfer overhead. Mixed writes can alter read tails through shared controller and media resources. These are mechanisms to evaluate against data, not supplied findings.

Use the actual SSD bus/link when discussing interface ceilings. Do not infer SATA, NVMe, or a PCIe generation from the Ryzen processor or virtual SCSI identity. Account for protocol/filesystem/virtualization overhead and CPU saturation before attributing a plateau to the interface. WSL results characterize the complete measured virtualized storage path. Write completion without per-operation synchronization is not a durability guarantee. Temperature unavailability prevents a confident thermal-causation claim.
