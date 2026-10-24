# Validation of the starter package

These are implementation checks, not performance results from the target laptop. No validation measurements or figures are included as project findings.

| Check | Outcome |
| --- | --- |
| Python unit suite | 15 tests pass, including matrix completeness, aligned regions, weighted means, pooled quantiles, sample SD, knee fallback, invalid raw hashes, crash-truncated journals, file safety, and correct weighting of partial state intervals |
| Python syntax | All project modules and scripts compile |
| Setup script | Bash syntax check passes |
| Fio configurations | All 97 static reference configurations pass real fio 3.36 `--parse-only` validation |
| Initialization | A dedicated 64 MiB regular file was fully initialized with direct I/O and a final flush |
| Real I/O integration | A short two-trial smoke suite completed 106 measured runs across every family, including adaptive tail selection and the cache controls |
| High queue depths | Twelve additional short direct-I/O runs completed at QD 64, 128, and 256 across four workloads |
| Resume | Completed smoke and high-depth runs resumed without rerunning completed measurements |
| Parsing | Integration outputs parsed without invalid-result errors; diagnostics remained visible rather than suppressing small tail samples or low occupancy estimates |
| Plotting | All 13 plot types generated as PNG and PDF; PNG structures were verified, and figure labels/layouts were reviewed |
| Report population | The report builder successfully embedded all 13 figures and populated available baseline, knee, and tail tables in a separate verification copy |
| Starter report | Nine Letter-size pages rendered and inspected, with measurements and empirical interpretation fields left TBD |

Validation used fio 3.36 in a Linux container, a small disposable file, and deliberately short runtimes. It verifies program operation and data handling, not target-laptop throughput, thermal behavior, or SSD steady state. The Windows PowerShell metadata collector was not executed on Windows in this environment. Run the supplied inspection and smoke workflow on your WSL2 installation before the full suite.

Commands used for the portable checks:

```bash
python -m unittest discover -s tests -v
python -m compileall -q ssdbench scripts
bash -n scripts/setup_wsl.sh
fio --parse-only path/to/generated-config.fio
```

The full run on the target laptop remains necessary to produce the assignment's raw results, tables, plots, hardware details, and final causal interpretation. A completed subset is recorded separately from coverage of the default full matrix with repeated trials.
