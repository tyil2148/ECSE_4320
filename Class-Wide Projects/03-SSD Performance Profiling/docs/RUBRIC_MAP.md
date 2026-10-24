# Rubric evidence map

No implementation can supply the empirical portions of the rubric until the target-laptop experiments have run. This map identifies what is automated and what you must finish in the report.

| Rubric category | Points | Supplied implementation | Evidence to add after running |
| --- | ---: | --- | --- |
| Safety and zero-queue baselines | 30 | Owned regular-file guard; no raw targets; full-file initialization; direct I/O; aligned offsets; four QD 1 cases | Actual path/filesystem/size, SSD mapping, mean and tail baseline table, successful initialization evidence |
| Block-size and pattern sweeps | 35 | All six required block sizes x two patterns x read/write at QD 16; 24 cases; throughput, IOPS, latency figures from the same runs | State units and fixed knobs; compare bytes/s, requests/s, latency and variability |
| Read/write and queue-depth analysis | 40 | Four read/write mixes, two pattern/block combinations; QD 1-256; fixed aggregate-QD worker comparison; knee rule and fallback; Little's Law CSV | Measured knee or no-knee conclusion, numeric L=lambda W calculation, saturation and controller/interface discussion |
| Tail latency and device state | 25 | p50/p95/p99/p99.9 for every active direction; adaptive middle and near-knee tails; N diagnostics; working-set sweep; sustained-window time series; optional temperature snapshots | Compare tails with central tendency; evaluate early/late differences; distinguish evidence from possible SLC/GC/thermal mechanisms |
| Reproducibility and data hygiene | 25 | Exact fio configs; raw JSON+; hashes; seeds; actual-order journal; repeated trials; unmodified failed attempts; environment/host collector; parsed CSV; SD bars | Filled host/operator notes, dates, actual versions, missing sensors, retained raw results, completed coverage check |
| AI-use transparency and pitfall analysis | 15 | Honest AI disclosure in README/report; controlled warm buffered-versus-direct experiment using the same synchronous engine | Review disclosure; explain measured cache effect or why it was not visible; acknowledge WSL host caching and durability boundaries |
| Report quality | 15 | Editable report with methods, theory, result slots, figures/tables, limitations, conclusions and references | Replace all TBD fields; add plots and concise supported interpretation; review labels and captions |
| Total | 185 | Full implementation and report framework | Complete and verify empirical evidence |

## Required figures

1. QD 1 mean latency and completion percentiles.
2. Block-size throughput and mean total latency, with random/sequential panels.
3. Block-size IOPS to separate request rate from byte rate.
4. Read/write mix throughput and mean latency.
5. A single throughput-versus-latency curve with four workloads and QD labels.
6. IOPS and latency versus QD.
7. Little's Law occupancy estimate versus configured QD.
8. Worker-count comparison holding aggregate QD and total address range fixed.
9. Tail percentiles at selected depths.
10. Pooled completion-histogram survival curves.
11. Working-set effects on IOPS and p99.
12. State-window throughput and mean completion latency over time.
13. Warm-cache buffered/direct pitfall comparison.

Full-suite figures are generated in both PNG and PDF. Labels identify fixed and varied knobs. SD bars appear where repeated trial summaries support them; the pooled survival curve and individual-trial time series use their stated statistical representations.
