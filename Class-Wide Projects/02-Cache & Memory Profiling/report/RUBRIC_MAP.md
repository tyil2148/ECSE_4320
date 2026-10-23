# Rubric coverage map

The supplied rubric totals **185 points**. Code and report coverage are prepared; experimental evidence and interpretation must be completed from actual runs. This map is not a promise of a grade.

| Category | Points | Implemented evidence | Report coverage |
| --- | ---: | --- | --- |
| Zero-queue baselines | 25 | Random single-cycle pointer chase, capacity-informed candidates, clock overhead, units, measured cycles if supported; baseline_table.csv | Measurement methods; interpretation framework; baseline results table and Figure 1 |
| Pattern/granularity/RW sweeps | 35 | Full 2 patterns × 3 strides × 2 granularities × 4 mixes; matched visited line footprint; dependent pattern latency; all-mix loaded read latency | Bandwidth methods; pattern results and Figures 2–3; loaded results |
| Throughput-latency knee | 35 | Concurrent probe plus pinned private-array workers, all mixes, intensity points, tail audit, 90%-peak candidate, Little Law proxy explicitly qualified | Concurrency methods; interpretation framework; intensity table and Figure 4 |
| Working-set/cache/TLB analysis | 35 | L1-to-DRAM sweep; multiply/AXPY kernels; generic cache/L1D/DTLB events; compact/spread pages; actual base/THP/HugeTLB mapping checks | Cache/TLB methods; AMAT framework; results Figures 5–6 and correlation plots |
| Experimental rigor | 25 | Per-thread guest affinity, topology order, first touch, five randomized repetitions, raw counts and statuses, source hashes, exact argv, host/guest snapshots, SD error bars, memory budget checks | System configuration; concurrency and rigor; completeness audit and limitations |
| Abuse transparency and pitfall analysis | 15 | Honest AI disclosure; identical stream code with misleading cache reuse versus corrected DRAM-candidate footprint | Pitfall method; Figure 7 and numerical interpretation; AI disclosure |
| Report quality | 15 | Editable structured report, units, plot slots and interpretation prompts, readable generated figures, specific caveats and source references | All report sections; final concise conclusion to complete |

## Assignment requirements beyond the rubric headings

| Requirement | Implementation |
| --- | --- |
| AMD-compatible memory benchmark equivalent to MLC | Custom Linux C++ benchmark; does not require Intel MLC |
| perf or equivalent cycles/instructions/cache/TLB events | Direct perf_event_open; errors recorded per event |
| Simple loop kernels tied to misses/runtime | Multiply and AXPY with footprint and access-order sweeps |
| Outstanding requests or threads | Background thread-count sweep; count is not mislabeled as hardware requests |
| 4 KiB versus huge pages where available | MADV_NOHUGEPAGE, MADV_HUGEPAGE, explicit 2 MiB HugeTLB; observed backing recorded |
| System settings including NUMA and SMT | Host PowerShell snapshot plus Linux lscpu, topology, frequency files, SMT and numactl output |
| Raw data, processed data, plotting code | Runtime-generated raw JSONL/CSV, summaries, audit, PNG/PDF plots, source included |
| Per-level table and frequency conversion | Baseline table with valid counter cycles; report explains nominal 2 GHz conversion separately |
| Diminishing returns and Little Law | Knee table/curve; guided adjacent-point discussion; same-population caveat |
| AMAT analysis | Conditional-probability hierarchy formula and guided cache-miss interpretation |

**Platform constraint:** software implements counter and page experiments, but WSL2 may not expose the required hardware events or huge pages. The rubric's measured counter-correlation requirement cannot be guaranteed by code. Collect valid evidence on a supported Linux configuration if necessary, or explicitly identify the missing evidence. Huge-page comparisons are conditional on availability in the assignment.
