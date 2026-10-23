# Complete the report after running the experiments

1. Fill ENVIRONMENT_NOTES.md and capture Windows configuration with host_configuration.ps1. Record build/compiler settings and actual CPU order, not just model specifications.
2. Run the smoke profile and check that it completes. Do not copy its small-buffer data into the report.
3. Run the full profile with at least five repetitions. Keep all raw and metadata files. If memory checks skip cases, resolve the limit and rerun in a new directory, retaining the original attempt.
4. Run analyze.py. Read processed/audit.json before interpreting plots. Inspect counter support, page backing, successful counts, major faults, and load-tail fraction. Increase loaded-sweep duration if tails are material. Counter plots are absent if no valid events exist; that absence is not zero misses.
5. Fill the system table from system_before.json, system_after.json and host_configuration.txt. Use per-core L2 and actual reported LLC. Distinguish nominal base frequency from measured cycles.
6. Inspect 01_working_set.png. Assign L1D/L2/LLC/DRAM labels only where the footprint/transition evidence supports them. Copy mean, SD, n and valid cycles from baseline_table.csv into Table 2. If regions are ambiguous, explain that instead of forcing a label.
7. Insert plots 02 and 03. Quantify sequential/random changes, stride and 8-byte versus 64-byte granularity effects, and the four traffic mixes. Keep units explicit and distinguish useful bandwidth from actual DRAM traffic.
8. Insert plot 04 and use knee_candidates.csv. Review the 90%-peak candidate against the shape, errors, later intensity points and SMT placement. Mark the reviewed knee in Word or the plotting source if it differs from the automatic marker. Give two adjacent-point bandwidth/latency comparisons. Do not claim saturation if the final sampled point is the candidate. Compute the Little Law proxy and retain its caveats.
9. Insert kernel-runtime and valid cache-counter plots. Compare time and misses per 1000 operations across footprint/order. Discuss AMAT with conditional miss probabilities; do not treat generic cache misses as every level's miss rate.
10. Insert page-locality and valid TLB plots. Compare equal node counts. State full/partial/unobserved THP and explicit allocation failures. Discuss cache-conflict and translation confounders. Report missing counters plainly if WSL blocks them; separate any alternate-platform run.
11. Insert plot 10 for the pitfall. Report both footprints, mean bandwidth, SD and their ratio. Explain precisely why the smaller warmed case is mislabeled if called DRAM bandwidth.
12. Fill the abstract and conclusion last, edit the AI disclosure to match what you actually reviewed, remove bracketed instructions only after replacing them with measured evidence, and check all figure captions and units. Expand the Word document naturally as you add plots; the prepared pagination is not a report length requirement.

## Useful normalized quantities

- Useful GB/s = explicitly counted bytes / elapsed ns.
- Chase ns/load = elapsed ns / completed dependent loads.
- Kernel ns/element = elapsed ns / completed element updates.
- Counter misses per 1000 operations = scaled valid misses × 1000 / operations.
- Cycles per operation = scaled valid cycles / operations. This includes benchmark-loop work.
- Sample coefficient of variation = SD / mean; use it to discuss variability, not to delete outliers automatically.
- Nominal 2 GHz illustration = 2 × latency_ns cycles. This is not a measured CPU clock conversion.
- Little Law illustrative proxy = useful GB/s × probe latency_ns / 64. It is not observed queue depth.

## Validation performed while preparing this package

The C++ self-test verifies single-cycle ring coverage, explicit stores and numerical multiply/AXPY output. Automated checks also cover byte accounting, all required mixes, sparse-stride DRAM footprints, loaded-worker operation, summary statistics, suppression of missing or heavily multiplexed counters, and a runner/analysis smoke workflow. A full small-footprint integration run exercises every experiment type and plot generation. These checks establish implementation behavior in a Linux test environment, not laptop performance or WSL PMU availability. No such test values belong in the experimental results.
