# Cache and Memory Performance Profiling

Advanced Computer Systems Project 2

Author [NAME]   Course section [SECTION]   Date [DATE]

## Abstract

This project characterizes how access locality, working-set size, read/write mix, and concurrency affect cache and memory performance. A custom Linux benchmark provides dependent-load latency, controlled scalar bandwidth, loaded-latency curves, and elementwise kernels with cache and TLB counter collection. The target platform is an AMD Ryzen 5 PRO 7530U laptop running x64 Windows 11 with WSL2. Repeated trials and recorded system settings make the measurements reproducible. The final results establish [INSERT MEASURED CACHE AND DRAM LATENCY RANGES], a throughput/latency knee near [INSERT THREAD COUNT OR STATE NO CLEAR KNEE], and [INSERT MAIN CACHE OR TLB FINDING].

## Objectives and scope

The experiments distinguish latency from throughput. Dependent pointer chasing estimates the time for a serialized demand load, while independent stream accesses measure useful payload transferred per unit time. A separate probe measures latency under background traffic. Cache and TLB behavior are examined using both controlled footprints and application-like kernels. A deliberately misleading cache-resident benchmark demonstrates why the working set must be checked before claiming DRAM bandwidth.

## System configuration

Table 1 records supplied hardware information and fields to complete from the saved host and guest snapshots.

| Item | Configuration |
| --- | --- |
| Host processor | AMD Ryzen 5 PRO 7530U with Radeon Graphics |
| Advertised base frequency | 2.00 GHz supplied by the student; actual frequency varies |
| Host operating system | Windows 11 x64 build [INSERT] |
| Physical RAM and memory configuration | [INSERT capacity channels and speed if known] |
| WSL and Linux environment | [INSERT WSL2 version distribution and kernel] |
| Cache capacities | [INSERT detected L1D per core L2 per core and shared LLC] |
| Runtime controls | [INSERT AC power mode SMT governor CPU order and NUMA] |
| Build and tools | [INSERT compiler flags Python version and counter support] |

The exact commands, source hashes, permitted CPU set, cache topology, page policy, and before/after settings are retained with the data. WSL guest affinity does not guarantee a fixed host physical core.

[[PAGEBREAK]]
## Measurement methods

### Timing and zero queue baselines

The latency test builds one cycle through all selected nodes and then follows the pointer stored in each node. Because the next address depends on the preceding load, the benchmark has one demand load in flight. Random traversal reduces predictable access behavior. Each node normally occupies a separate 64-byte line, although only the 8-byte pointer is loaded. Sequential traversal is also measured to expose the effect of predictable locality and prefetching.

Allocation, page initialization, permutation generation, and one complete warm traversal occur before timing. CLOCK_MONOTONIC_RAW measures batches of 4096 dependent loads. Reported latency is elapsed nanoseconds divided by completed loads. The observed value includes loop and timing overhead; minimum clock-pair overhead is recorded but is not subtracted. No cache flush is used. These are steady-state capacity experiments. The term zero queue denotes the absence of intentional competing benchmark traffic, rather than the absence of all operating-system or host activity.

Baseline candidates use half the detected L1D capacity, half the per-core L2 capacity, half the LLC capacity, and a visited line footprint of at least four times LLC. The working-set sweep spans 4 KiB through at least 256 MiB by default and includes these candidates. Candidate names are accepted only after the measured curve supports the intended cache-residency regions. The six-core aggregate L2 capacity must not be mistaken for the cache available to one pinned core.

### Bandwidth and access controls

The pattern/mix matrix crosses sequential and shuffled addresses, strides of 64, 256, and 1024 bytes, granularities of 8 and 64 bytes, and read/write mixes of 100/0, 0/100, 70/30, and 50/50. This produces 48 bandwidth configurations per repetition. Mixes are implemented by a deterministic ten-access schedule; the actual fraction is saved for remainder groups. Read accesses consume values into a checksum; write accesses store computed values without an explicit read-modify-write.

Useful bandwidth equals explicit payload bytes divided by measured wall time. GB/s uses decimal units, while KiB and MiB use binary units. Temporal stores may cause read-for-ownership and later writeback traffic. A fence drains the store buffer at batch boundaries, but does not force every dirty line to DRAM. Therefore useful bandwidth is not a direct measurement of memory-controller traffic.

The visited line footprint is fixed across strides, and virtual span expands with stride. With a 16 MiB LLC and a 64 MiB visited line footprint, spans are 64, 256, and 1024 MiB. Both access patterns use a precomputed address-order array, adding index traffic that is excluded from the useful byte count. Volatile scalar accesses and disabled vectorization make the comparisons controlled; they do not establish peak optimized STREAM bandwidth.

[[PAGEBREAK]]
## Concurrency and experimental rigor

### Loaded latency sweep

A pinned random dependent-load probe accesses a DRAM-candidate footprint while background threads stream through private arrays. The default intensity points are 0, 1, 2, 3, 4, 5, 7, 9, and all remaining permitted vCPUs, restricted to the available CPU set. The probe reserves its own vCPU. Guest topology places one thread on each reported physical core before using SMT siblings. This order and the point where siblings become necessary must be recorded.

The sweep repeats for all four read/write mixes. Probe latency is always read latency, including when the load workers perform only stores. It therefore compares read response under different traffic mixes, rather than claiming a direct write-latency measurement. Worker arrays are first-touched on their pinned vCPUs, and workers wait at a common start gate after initialization and warmup.

Each worker finishes its current full-array pass after the probe stops. Load bandwidth is the sum of per-worker useful-byte rates over their active intervals. The maximum duration overrun is recorded as load_tail_ns. If the overrun is substantial relative to the probe interval, the sweep is repeated with a longer duration, such as 1000 ms. This reduces finite-window mismatch between the probe and load traffic.

### Repetition and control

Five independently launched trials are collected by default. A fixed seed shuffles the experiment/trial order to reduce systematic thermal or temporal drift. Matched configurations share the repetition seed, and seeds change between repetitions. All raw samples are retained. Summary tables report mean, median, sample standard deviation, extrema, and sample count. Plots use mean plus or minus one sample standard deviation; these bars do not represent confidence intervals.

CPU pinning is applied before first touch. Linux affinity cannot isolate the workload from Windows activity or prevent host scheduling changes in WSL2. Measurements should use AC power, a documented Windows power mode, minimal background work, and stable cooling. Governor, frequency, SMT, NUMA and topology settings are saved where exposed. Missing governor files do not establish a constant CPU frequency.

Configurations estimated to consume more than 65 percent of currently available guest memory are explicitly skipped. The suite does not silently shrink their working sets. Skipped or failed required cases must be rerun or reported as limitations. Major faults, minor faults and involuntary switches are recorded for chase tests. Before/after metadata and host notes help diagnose pressure and drift. The exact executable is copied into the run directory.

### Reproducibility record

The submission retains source code, build flags, scripts, plan.json, commands.jsonl, raw.jsonl, raw.csv, system_before.json, system_after.json, host_configuration.txt, and processed outputs. The smoke profile checks correctness and output generation only; its small working sets are excluded from the final analysis.

[[PAGEBREAK]]
## Cache and TLB experiments

### Kernel correlation

Two simple kernels provide a connection to useful computation: z[i] = x[i] * y[i] and y[i] = 0.5*x[i] + y[i]. Sequential and shuffled element orders are measured across the working-set range. Each update accounts for two 8-byte reads and one 8-byte write, or 24 useful bytes per element. The index-array load is additional traffic. Time is reported in ns per element. The controlled scalar implementation is not an optimized vectorized numerical library.

Direct perf_event_open collection requests user-space cycles, instructions, generic cache references and misses, L1D read misses, and DTLB read misses. Counters exclude allocation, setup and warmup; they include the timed kernel and small measurement overhead. Raw counts, enabled time, running time, and scaled counts are retained separately. Missing events remain unavailable rather than becoming zeros. Normalized analysis excludes events whose running fraction is below 90 percent. Independent event scheduling means ratios may still reflect slightly different sampling intervals. [1]

Generic cache-miss events are architecture dependent and must not automatically be called L1 misses or DRAM transactions. DTLB read misses are not automatically completed page walks. Supported event meanings are checked against the kernel and AMD event descriptions before level-specific claims. If WSL provides no usable hardware events, counter correlation cannot be established on that platform; the missing evidence is stated, or a separate native-Linux run is identified explicitly.

### Page locality and actual huge page backing

The TLB test compares equal numbers of visited cache lines placed compactly or one line per 4 KiB page. Spread-node offsets rotate through line positions within the page, reducing the conflict effect of accessing the same cache set on every page. Random traversal visits the same logical nodes in matched tests. The full sweep uses 16 through 32768 nodes. Virtual span changes between layouts; visited cache-line footprint remains matched. Physical placement and cache effects can still differ, so a latency change alone does not prove a TLB cause.

Three page policies are attempted: base pages using MADV_NOHUGEPAGE, transparent huge pages using MADV_HUGEPAGE, and explicit 2 MiB HugeTLB mappings. The program reads the tested mapping in /proc/self/smaps and records AnonHugePages and kernel/MMU page sizes. An advice request alone does not prove huge-page backing. Full, partial and unobserved THP backing are distinguished; explicit allocation failures are saved as unsupported. No privileged system policy is changed. [2]

### Benchmark pitfall

The same read-only stream kernel is run first over a warmed cache-resident footprint and then over a DRAM-candidate footprint. Calling the first bandwidth result DRAM bandwidth would measure cache reuse under a misleading label. The comparison holds code, access size, stride, mix and timing method constant while changing capacity pressure. The measured contrast is inserted in the results section without assuming its size or direction in advance.

[[PAGEBREAK]]
## Interpretation framework

### AMAT and cache transitions

A hierarchy model uses conditional miss probabilities and incremental miss penalties:

AMAT = tL1 + mL1 × (tL2 + mL2 × (tLLC + mLLC × tDRAM))

Here mL2 is the probability of an L2 miss conditional on reaching L2, and mLLC is conditional on reaching LLC. The latency plateaus measured by pointer chasing are end-to-end observations that include loop and translation costs. They cannot simply be added as incremental penalties. Generic cache counters do not supply all conditional miss probabilities; the formula supports qualitative interpretation unless valid level-specific measurements are available.

A transition near a reported cache capacity is consistent with reduced residency, but effective capacity also depends on associativity, sharing, indexing, replacement and interference. For each candidate transition, compare latency, kernel ns per element and valid misses per 1000 updates. Correlation supports an explanation, while a causal claim requires controlling other changing costs, including translation and index access.

### Throughput latency and concurrency

Little's Law relates the mean in-system request count N, completion rate lambda and response time W for the same steady-state request population:

N = lambda × W

For true 64-byte transaction bandwidth B, lambda = B/64. If B is expressed in GB/s and W in ns, N = B × W / 64. The suite measures useful mixed stream bandwidth and a separate serialized read probe, so the computed quantity B × Wprobe / 64 is only an illustrative proxy. It is not observed queue depth or memory-level parallelism. Store traffic, write allocation, access granularity, and unequal request populations prevent that direct interpretation.

The conceptual prediction is that added concurrency initially exposes more memory parallelism and raises throughput. Once a bottleneck dominates, further load may add response time while yielding little extra bandwidth. Background-thread count is a controlled intensity knob, rather than a count of outstanding hardware requests.

The analysis marks the first positive intensity point reaching 90 percent of observed peak useful bandwidth as a knee candidate. This reproducible threshold is reviewed against neighboring points, error bars, marginal bandwidth gains and probe-latency costs. A candidate at the last sampled point does not demonstrate a plateau. A generator or scheduling bottleneck can create a knee without saturating the DRAM bus.

### Frequency conversion

Nanoseconds are the primary latency unit. At a nominal 2.00 GHz, a reference conversion is cycles = 2.00 × latency_ns. This is a nominal illustration, not a measured operating-clock conversion. Where valid cycles counters are available, cycles per completed operation and effective counted cycles per elapsed nanosecond are reported separately, with multiplexing and host-scheduling qualifications. No fixed 2.00 GHz assumption is used to time the benchmark.

[[PAGEBREAK]]
## Results for baseline latency and access patterns

### Baseline latency and working set

Table 2 is completed from processed/baseline_table.csv after validating candidate levels against the working-set curve. Report mean plus or minus sample SD and retain n for every row.

| Validated region | Visited footprint | Latency ns per load | Cycles per load if valid | n |
| --- | --- | --- | --- | --- |
| L1D | [INSERT] | [INSERT] | [INSERT or unavailable] | [INSERT] |
| L2 | [INSERT] | [INSERT] | [INSERT or unavailable] | [INSERT] |
| LLC | [INSERT] | [INSERT] | [INSERT or unavailable] | [INSERT] |
| DRAM candidate | [INSERT] | [INSERT] | [INSERT or unavailable] | [INSERT] |

Figure 1 [INSERT 01_working_set.png with cache-capacity annotations].

[INSERT INTERPRETATION: identify supported transition ranges, compare them with detected capacities, describe variance and any ambiguous plateaus, and state whether the DRAM candidate exceeds effective LLC capacity. Do not force four distinct plateaus if the data does not support them.]

### Pattern granularity and read write mix

Figure 2 [INSERT 02_pattern_mix.png].

Figure 3 [INSERT 03_pattern_latency.png].

[INSERT INTERPRETATION: compare sequential and random useful bandwidth at each granularity and stride. Give at least two numerical comparisons with units and variability. State the fixed visited line footprint and expanding virtual spans. Explain how sparse 8-byte access uses only part of each fetched line and how the order array and scalar execution affect the measured rates.]

[INSERT MIX DISCUSSION: rank measured read/write mixes using actual useful bandwidth. Account for temporal-store allocation and writeback costs without treating useful bytes as bus bytes. Use the loaded-latency results for the latency response under each mix. A stream's elapsed time per access is reciprocal throughput rather than dependent-load latency.]

[[PAGEBREAK]]
## Results for access intensity

Figure 4 [INSERT 04_loaded_latency.png with background thread counts and the reviewed knee candidate marked].

| Traffic mix read write | Observed peak useful GB per s | Reviewed knee threads | Probe latency at knee ns | Evidence of plateau |
| --- | --- | --- | --- | --- |
| 100 0 | [INSERT] | [INSERT] | [INSERT] | [INSERT] |
| 0 100 | [INSERT] | [INSERT] | [INSERT] | [INSERT] |
| 70 30 | [INSERT] | [INSERT] | [INSERT] | [INSERT] |
| 50 50 | [INSERT] | [INSERT] | [INSERT] | [INSERT] |

[INSERT INTERPRETATION: identify the knee using the 90-percent candidate, explain whether a plateau is actually demonstrated, and state the thread count where SMT siblings begin. Compare adjacent intensities using numerical marginal bandwidth gains and probe-latency increases, including error bars. If a clear knee is absent, state that outcome and explain whether additional points are necessary.]

### Queueing interpretation

At the selected point, useful load bandwidth is [B] GB/s and probe latency is [W] ns. The illustrative 64-byte proxy is B × W / 64 = [INSERT]. This value is not a measured queue depth because bandwidth and latency refer to different traffic populations and useful bytes omit bus overhead. [INSERT EXPLANATION OF HOW THE OBSERVED TREND SUPPORTS OR FAILS TO SUPPORT THE EXPECTED CONCURRENCY AND QUEUEING TRADEOFF.]

### Measurement quality for the intensity sweep

The largest load-tail fraction is [INSERT], using an observation duration of [INSERT] ms. [INSERT WHETHER A LONGER RERUN WAS NEEDED.] The peak and knee estimates are based on [INSERT] trials per point. [INSERT WHETHER VARIANCE OR HOST ACTIVITY MAKES A CANDIDATE AMBIGUOUS.] An observed throughput limit is attributed to [INSERT SUPPORTED BOTTLENECK OR STATE UNCERTAIN], rather than automatically to the memory controller.

[[PAGEBREAK]]
## Results for cache TLB and the benchmark pitfall

### Cache miss impact on kernels

Figure 5 [INSERT 06_kernel_runtime.png and 07_cache_miss_correlation.png if valid counters exist].

[INSERT NUMERICAL COMPARISONS of multiply and AXPY time per element for sequential/random order and at least one cache transition. Include valid generic cache or L1D misses per 1000 element updates, cycles per operation and instructions per operation where available. Explain the AMAT connection without substituting one generic aggregate miss count for every conditional rate. If counters are unavailable, identify the missing events and restrict claims to the measured performance trend.]

### Page locality and TLB impact

Figure 6 [INSERT 05_page_locality.png and 09_tlb_counter_impact.png if valid counters exist].

[INSERT MATCHED-NODE COMPARISONS of compact and spread layouts, including latency and DTLB misses per 1000 loads where valid. State actual observed base/THP/HugeTLB backing, including partial or failed mappings. Explain whether huge pages changed latency and counter behavior. Distinguish translation evidence from residual cache effects. Add 08_tlb_miss_correlation.png if it provides useful kernel context.]

### Pitfall demonstration

Figure 7 [INSERT 10_pitfall.png].

The cache-reuse case achieved [INSERT] GB/s over [INSERT] bytes, while the corrected DRAM-candidate case achieved [INSERT] GB/s over [INSERT] bytes. Both used the same read-only stream code, granularity, stride and timing method. [INSERT THE OBSERVED RATIO WITH ITS DIRECTION AND VARIABILITY.] Reporting the small warmed case as DRAM bandwidth would assign cache service to the wrong memory level. The corrected claim identifies the actual footprint and calls the metric useful bandwidth, with no assumption that it equals bus traffic.

### Completeness of measured evidence

The run audit contains [INSERT] successful, [INSERT] unsupported, [INSERT] skipped and [INSERT] failed trials. [INSERT EVENT AVAILABILITY AND LOW RUNNING FRACTION COUNTS.] Required cases with missing evidence are [INSERT RERUNS OR LIMITATIONS]. No unsupported measurement is filled with zero or an estimated result.

[[PAGEBREAK]]
## Limitations and conclusion

### Limitations

WSL2 adds a guest/host scheduling and address-translation layer. Linux vCPU pinning improves repeatability but does not reserve physical cores or suppress Windows activity. Windows controls power policy and may hide frequency details from Linux. WSL VM memory limits, reclaim, swapping, SMT competition, thermal changes and host interference can alter measurements. Host and guest snapshots identify the configuration actually used. Microsoft documents VM memory and processor controls separately from per-distribution settings. [3]

The pointer chase measures serialized steady-state latency with loop overhead, rather than a pure hardware hit time. Random streams incur order-array traffic and scalar execution costs. Temporal stores do not reveal exact DRAM write traffic. Generic counter semantics and independent multiplexing limit exact ratios. Huge-page requests are interpreted using observed mapping information, and unavailable counters or pages restrict the corresponding conclusions. [INSERT ADDITIONAL LIMITATIONS SUPPORTED BY THE ACTUAL RUN, SUCH AS FAILED PMU ACCESS, THERMAL DRIFT OR MISSING PLATEAUS.]

### Conclusion

[INSERT A SHORT EVIDENCE BASED CONCLUSION: give the measured hierarchy latency ranges, the strongest locality/granularity effect, the reviewed throughput/latency knee or its absence, and the supported cache/TLB finding. State what the pitfall demonstrated and the practical implication for memory-sensitive code. Do not claim hardware features or measured bottlenecks unsupported by the data.]

### AI use disclosure

AI assistance was used to draft the C++ benchmark, Python orchestration and plotting code, documentation, and the report framework. The experimental results and final interpretation were completed by [NAME]. I reviewed the implementation, ran the experiments, checked the saved outputs and supported counter definitions, and take responsibility for the submitted analysis. [EDIT TO ACCURATELY DESCRIBE THE REVIEW AND VALIDATION ACTUALLY PERFORMED AND COMPLY WITH COURSE POLICY.]

### References

[1] Linux man-pages project. perf_event_open manual. Counter types, permissions, event grouping and enabled/running-time scaling. https://man7.org/linux/man-pages/man2/perf_event_open.2.html. Accessed 21 October 2026.

[2] Linux kernel documentation. Transparent Hugepage Support. Page advice, backing and mapping inspection. https://docs.kernel.org/admin-guide/mm/transhuge.html. Accessed 21 October 2026.

[3] Microsoft Learn. Advanced settings configuration in WSL. Host and distribution configuration. https://learn.microsoft.com/en-us/windows/wsl/wsl-config. Accessed 21 October 2026.

[4] Advanced Computer Systems. Project 2 Cache and Memory Performance Profiling assignment and grading rubric. Course handout supplied by the student.
