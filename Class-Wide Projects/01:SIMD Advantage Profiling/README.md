# Project 1: SIMD Advantage Profiling

Complete CPU-only, single-thread implementation of the four assigned kernels,
a reproducible experiment pipeline, and an editable report with results left blank.
Target: AMD Ryzen 5 PRO 7530U, x64 Windows 11, Linux under WSL (WSL 2 recommended).
The Radeon GPU is not used: the assignment measures CPU SIMD.

## Start on your laptop

In PowerShell, check your existing installation with `wsl --version` and `wsl -l -v`.
Record those outputs for the report. If WSL is not installed, Microsoft's documented
setup command is `wsl --install`; restart if requested and open your Linux distribution.
The commands below assume Ubuntu/Debian inside WSL. Other distributions need their
corresponding package commands.

Extract this project into the Linux filesystem, e.g. `~/simd_advantage`, then:

```bash
cd ~/simd_advantage
sudo apt update
sudo apt install -y build-essential binutils python3 python3-venv
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 scripts/build.py
python3 tests/test_correctness.py --full
python3 tests/test_analysis.py
python3 scripts/evidence.py
```

Build on the laptop: `-march=native` means the features exposed to that compiler in
that WSL session. The processor supports AVX2 and FMA3, not AVX-512 in AMD's listed
extensions [1]. Generic binaries target x86-64/SSE2. Actual loop widths must be
confirmed in compiler output and disassembly. Do not copy a native binary from
another computer. `--cxx clang++` is also supported when Clang is installed.

Use AC power and a consistent Windows power mode. Close CPU-intensive programs,
avoid activity on the selected core's SMT sibling, and allow temperature to
stabilize. Record what you actually did in `--notes`; affinity to a WSL vCPU does
not establish exclusive ownership of a physical core. Do not assume the advertised
2.00 GHz base clock is the current frequency. Windows controls laptop power and
frequency; unavailable guest settings stay marked unavailable.

## Run the experiments

Smoke checks the workflow; quick is a preliminary sweep; full is the submission
sweep. Full covers every required study and uses seven independent timed batches
per configuration. It is a sustained laptop workload; total time depends on your
compiler and host load. The default CPU is the first allowed CPU; select another
with `--cpu` if appropriate.

```bash
# Development check; do not present these as the final full sweep.
bash scripts/run_all.sh smoke results/smoke

# Full assignment, including all four kernels and both data types.
bash scripts/run_all.sh full results/full \
  --llc-mib 16 \
  --notes 'AC power; Windows power mode [fill]; WSL version [fill]; SMT [fill]; VM memory and vCPU limits [fill]; background load [fill]'
```

Replace the bracketed notes before running. AMD lists 16 MB L3 for this model [1];
`--llc-mib 16` is an explicit manual override recorded in metadata. Prefer the
observed cache size if your environment exposes accurate cache topology. Use
`lscpu -C` and `/sys/devices/system/cpu/cpu*/cache/` to check cache levels. Do not
mistake the processor's aggregate L1/L2 specifications for per-core capacities.

The default largest active working set is 64 MiB. That is four times a 16 MiB
LLC; the analyzer uses this conservative qualification for a DRAM roof. Each
process allocates three arrays, including unused buffers for some kernels,
so allocated/resident memory can exceed the active working set (about 96 MiB
at the largest dot/scale cases). Initialization also touches unused buffers.
No measured kernel uses an unused buffer. Stride sweeps cap padded footprints;
`--max-mib` accepts 1..64. Avoid VM swap/memory pressure during runs.

For more timing stability, pass `--seconds 0.25 --samples 11`. The runner uses a
seeded randomized case order and randomized build blocks. Samples within a build
are consecutive; this does not eliminate thermal drift. Repeat a complete full
run in a new directory if drift or high variability is evident; retain both runs.
An existing nonempty output directory is rejected to avoid mixing experiments.

To run stages separately:

```bash
python3 scripts/run_experiments.py --profile full --out results/full --llc-mib 16 --notes 'Your actual settings'
python3 scripts/analyze.py results/full --peak-ghz 2.0 --vector-bits 256 --fma-units 2
python3 scripts/plot.py results/full
```

The roofline peak is an explicitly assumed single-core FMA hardware model,
not a measured clock or compute throughput. Test sensitivity by changing
`--peak-ghz`, saving the corresponding output copies first. Kernels disable FMA
contraction in every build, so the FMA peak is a hardware upper ceiling, not an
attainable instruction mix guarantee.

## Build comparisons and numerical semantics

| Build | Target | Primary kernels | Scalar baseline used |
|---|---|---|---|
| scalar | x86-64 generic | vectorization disabled | itself |
| generic | x86-64 generic | compiler auto-vectorization | scalar |
| scalar_native | current CPU | vectorization disabled | itself |
| native | current CPU | compiler auto-vectorization | scalar_native |

The extra native scalar build keeps target ISA and tuning fixed when isolating
native SIMD effects. Speedups use these matched baselines. Generic-versus-native
also includes target/tuning changes and must not be described as a pure width
comparison. Scalar x86-64 arithmetic still uses scalar SSE/AVX registers; the
absence of XMM registers is NOT the test for absence of SIMD.

All primary kernel objects use `-O3 -ffast-math -ffp-contract=off`. Scalar objects
add GCC's `-fno-tree-loop-vectorize -fno-tree-slp-vectorize` or Clang's
`-fno-vectorize -fno-slp-vectorize`. Vector objects request compiler diagnostics.
The harness is compiled separately with ordinary `-O2`, and every build disables
LTO. Full commands, compiler version and target feature macros are recorded.
The strict dot object uses `-O3 -fno-fast-math -ffp-contract=off` in every build.
Its ordered reduction is a negative example candidate; it may still contain
packed multiplication followed by scalar summation. Inspect the entire reduction
path before claiming it is unvectorized.

The relaxed dot can reorder sums. Validation uses compensated long-double
references. Elementwise checks use a rounding-scaled tolerance. Reductions use
a conservative forward-error bound `gamma_(N+2) * sum(abs(x*y))`, where
`gamma_k = k*u/(1-k*u)` and `u = epsilon/2`. This can be loose for large float32 N;
raw output records both actual absolute error and the bound. Small boundary and
alternating-sign tests complement that bound. Values are finite, normal, binary
fractions; this is not a study of NaNs, infinities, subnormals or arbitrary ill-
conditioned reductions. Numerical equality across fast-math builds is not promised.

## What the pipeline produces

| File | Purpose |
|---|---|
| raw.csv | Per-batch elapsed time, iterations, cycles if available, TSC ticks, validation error and checksum |
| summary.csv | Medians, IQR, sample SD/CV, useful GB/s, GFLOP/s, cycles/element and matched speedup CI |
| roofline.csv | Arithmetic intensity, assumed compute ceiling, calibrated bandwidth model and DRAM qualification |
| environment.json | CPU/OS/cache/SMT visibility, affinity, perf probe, settings and your host notes |
| build.json | Compiler version and exact compile/link commands |
| manifest.json / commands.jsonl | Planned cases, seed, completion status and each executed command |
| analysis.json | Explicit assumptions, statistical method, unavailable metrics and roofline warnings |
| figures/*.png / *.pdf | Nine figure groups, with axes, legends and uncertainty where appropriate |
| report_values.md | Reminder of values/assumptions to transfer into the report |
| build/*/*.vectorization.txt / compile-*.log | GCC or Clang optimization evidence |
| build/*/*.disasm.txt / target_macros.txt | Kernel-only disassembly and compiler target features |
| build/evidence.md | Search aid for manual per-kernel evidence review |

The nine figure groups cover speedup/locality, useful throughput/locality,
alignment, tails, strides, data type GFLOP/s, roofline, the negative example,
and cycles/element (or explicitly labeled reference ticks if cycles are absent).
The scale loop uses y = 1.25x to avoid replacement by a libc copy routine with an unknown store policy. Bandwidth and roofline traffic are distinct: useful bytes count source-level
loads/stores; modeled DRAM bytes include reuse, cache-line utilization and
write-allocate/writeback. Actual DRAM traffic is not claimed without hardware
events. Stencil coefficients are constant; interior outputs have two halo inputs
and no extra boundary output stores.

## Counters and WSL limitations

The timing harness probes Linux `perf_event_open` for user-space hardware cycles
and enables/disables it around each batch. `core_cycles` is blank when unavailable.
`tsc_ticks` comes from serialized RDTSCP and is always labeled reference ticks,
not core cycles. Do not multiply seconds by 2 GHz and call that measured cycles.
The counter interval includes timer/readout overhead around the batch; batching
makes it small, but it is not instruction-exact kernel attribution.

Optional whole-process audit:

```bash
python3 scripts/profile_perf.py --out results/perf-audit
```

If `perf` is not installed or hardware counters are blocked/unexposed, the script
records the diagnostic and exits gracefully. Installing a matching perf tool
depends on the installed WSL kernel/distribution. Probe before trying to change
system permissions. The audit includes allocation, reference validation,
warm-up and calibration: do not divide those process totals by only timed
iterations. Model-specific vector instructions, cache misses and DRAM traffic
are recommended extensions when actually supported (`perf list`); unsupported
PMU events must be reported as unavailable. Required timing and compiler/disassembly
evidence work without PMU support.

## Finish the report and repository

Edit `report/report.md` or the delivered Word report. Every `[ADD ...]` marker
identifies information that needs your own run. Insert the real figures and
representative measurements, verify the vectorization snippets, write the
result-specific interpretations and conclusion, and replace the name/repository
placeholders. The tables of operation/byte counts are analytic, not benchmark
results. No performance results or example charts are bundled.

The Word report can be regenerated after editing Markdown:

```bash
python3 -m pip install -r requirements-report.txt
python3 scripts/make_report.py --output report/report.docx
```

The builder uses `<!-- PAGE -->` as a page break and Markdown paragraphs,
headings, pipe tables and simple equations. It also supports figure lines
`![caption](relative/path.png)`; paths resolve from the Markdown file's directory.
Keep the report concise after inserting figures; move detailed raw tables to
the repository. Word or LibreOffice can export PDF for submission.

Publish your completed repository using GitHub's normal upload or git workflow:

```bash
git init
git add .
git commit -m 'Implement SIMD profiling project'
# Create an empty GitHub repository, then use its actual URL here:
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git branch -M main
git push -u origin main
```

Commit source, report, real raw/processed measurements, figures, machine notes,
and the compiler/disassembly evidence. Build objects are ignored; force-add the
text evidence you use, for example `git add -f build/*/*.txt build/*/*.log
build/build.json build/evidence.md`. Do not commit the virtual environment.
This package does not create or publish a GitHub account/repository for you.

## References

1. AMD, Ryzen 5 PRO 7530U specifications: https://www.amd.com/en/support/downloads/drivers.html/processors/ryzen-pro/ryzen-pro-7000-series/amd-ryzen-5-pro-7530u.html
2. GCC optimization flags: https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html
3. GCC optimization diagnostics: https://gcc.gnu.org/onlinedocs/gcc/Developer-Options.html
4. Microsoft WSL configuration: https://learn.microsoft.com/en-us/windows/wsl/wsl-config
5. S. Williams, A. Waterman, D. Patterson, Roofline, CACM 2009, DOI: https://doi.org/10.1145/1498765.1498785
6. Linux perf stat documentation: https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/tools/perf/Documentation/perf-stat.txt

## Requirement coverage

See `REQUIREMENTS.md` for the assignment-to-file mapping and the remaining
measurement-dependent submission items.
