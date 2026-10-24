# Assignment coverage

Source: the two supplied project screenshots, Project 1 SIMD Advantage Profiling.

| Requirement / rubric | Implementation / report location |
|---|---|
| At least three kernels | All four: SAXPY/AXPY, dot, multiplication, 1D three-point stencil in src/kernels.cpp |
| Required experiments single-threaded | No threads/OpenMP; inherited one-CPU affinity in run_experiments.py |
| GCC/Clang optimizations and flags | build.py supports both; full commands/version recorded in build.json |
| Scalar versus auto-vectorized across working sets | locality study, matched generic and native scalar baselines, figures 01 and 02 |
| L1/L2/LLC/DRAM locality sweep | Full profile 4 KiB through 64 MiB active footprints; cache annotations and explicit DRAM qualification |
| Float32 versus float64 | Both types for every study; figure 06 and report data type interpretation |
| Aligned versus shifted arrays | 64-byte bases and shifts 0, 1, 3, 7 elements in full alignment study |
| Vector remainders and tail handling | N near 16/64/256/4096, offsets 0 through 8, figure 04; inspect compiler tails |
| Unit stride versus stride 2/4/8 | Specialized loops; fixed-N and fixed-footprint studies and figure 05 |
| Gather where meaningful | Optional in assignment; not added because regular strides already isolate non-unit access; inspect any compiler-generated gather if present |
| Scalar/default/widest-targeted ISA | generic and native variants; matched scalar_native added to avoid target confounding |
| Runtime, GFLOP/s or GB/s, cycles/element | raw and summary CSV; actual cycles when PMU available, explicitly labeled TSC fallback otherwise |
| Correctness and realistic timing | Long-double references, guard/halo/hole checks, cancellation/boundary tests; warm-up, calibration, repeated batches and checksums |
| SIMD verification | GCC/Clang reports, kernel-only disassembly, target macros, evidence.py and report evidence placeholders |
| Roofline for at least one kernel | Scale bandwidth calibration, operation/traffic model, explicit peak estimate, figure 07; only qualified DRAM points |
| Negative/misleading example | Strict ordered dot candidate; second candidate is vectorized DRAM case with compressed gains; report requires measured verification |
| Variability/error bars | Per-batch raw data; median/IQR/SD/CV; unpaired 95% bootstrap speedup intervals; plot IQR and interval lines |
| CPU/ISA/compiler/OS/frequency/SMT/timing/data methodology | environment.json and build.json plus host notes and report sections 1 through 3 |
| perf or similar recommended counters | Timed cycles via perf_event_open; optional whole-process perf audit with attribution caveat |
| GitHub source/build/raw/processed/plots | Git-ready directory and publication instructions; add YOUR laptop results and publish before submission |
| Short report connecting concepts/anomalies | Six-page report structure with methodology, analytic counts, evidence/measurement slots, limitations and conclusion |
| AI use transparency | Report contains a factual code/draft assistance statement to adapt to course policy and actual validation |

## What remains after running on the laptop

Record real host settings, insert actual results and figures, verify per-loop SIMD
and tails, interpret cache transitions and negative cases, report unavailable PMU
measurements honestly, complete the conclusion and repository URL, and publish
source plus actual data/evidence. These depend on your laptop run and are
intentionally not supplied as fabricated results.
