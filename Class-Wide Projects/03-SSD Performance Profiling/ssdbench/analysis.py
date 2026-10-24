from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics as stats
from collections import defaultdict
from pathlib import Path

from .common import dump_json, read_json, write_csv

METRICS = ("iops", "mib_s", "mb_s", "mean_lat_us", "mean_clat_us", "mean_slat_us",
           "p50_us", "p95_us", "p99_us", "p999_us", "io_count", "clat_samples", "io_bytes",
           "achieved_read_pct", "little_l_total", "little_l_clat", "clat_qd_fraction")
META = ("case_id", "family", "pattern", "read_pct", "bs", "iodepth", "numjobs", "total_qd",
        "working_set", "runtime", "ramp", "direct", "engine", "role", "direction")


def latency_block(stat, kind):
    for unit, factor in (("ns", .001), ("us", 1.), ("ms", 1000.)):
        if f"{kind}_{unit}" in stat:
            return stat[f"{kind}_{unit}"], factor
    return {}, 1.


def histogram_percentile(bins, percentile):
    n = sum(bins.values())
    if n == 0:
        return math.nan
    threshold, cumulative = math.ceil(n * percentile / 100), 0
    for latency, count in sorted(bins.items()):
        cumulative += count
        if cumulative >= threshold:
            return latency
    return max(bins)


def parse_document(doc, case, run_id, trial):
    jobs = doc.get("jobs", [])
    if len(jobs) != case["numjobs"]:
        raise ValueError("Expected per-job JSON (group_reporting=0); job count differs from numjobs")
    if any(int(j.get("error", 0)) for j in jobs):
        raise ValueError("fio reported a nonzero job error")
    direction_data = defaultdict(list)
    issues = []
    for job_index, job in enumerate(jobs, 1):
        boundary_excess = 0
        for direction in ("read", "write"):
            st = job.get(direction, {})
            n = int(st.get("total_ios", 0))
            if n:
                block, _ = latency_block(st, "clat")
                samples = int(block.get("N", n))
                bins = block.get("bins", {})
                if bins and sum(int(v) for v in bins.values()) != samples:
                    raise ValueError("Completion histogram count differs from completion-latency sample N")
                delta = samples - n
                if delta:
                    if not (case["ramp"] > 0 and case["engine"] == "libaio"
                            and 0 < delta <= max(0, case["iodepth"] - 1)):
                        raise ValueError("Latency sample count differs from I/O count outside the bounded asynchronous ramp case")
                    boundary_excess += delta
                    issues.append({"run_id": run_id, "type": "ramp_boundary_accounting",
                                   "detail": f"Job {job_index} {direction}: total_ios={n}, clat_N={samples}, excess={delta}. Histogram agrees with clat_N; bounded in-flight ramp-boundary samples retained."})
                direction_data[direction].append(st)
        if boundary_excess > max(0, case["iodepth"] - 1):
            raise ValueError("Combined read/write latency excess exceeds the per-job ramp-boundary bound")
    if not direction_data:
        raise ValueError("No completed I/O")
    if case["read_pct"] == 100 and "write" in direction_data or case["read_pct"] == 0 and "read" in direction_data:
        raise ValueError("Observed I/O direction disagrees with the configured pure workload")
    if 0 < case["read_pct"] < 100 and len(direction_data) != 2:
        raise ValueError("Mixed workload has no completed I/O in one direction")
    read_n = sum(x["total_ios"] for x in direction_data.get("read", []))
    all_n = sum(x["total_ios"] for entries in direction_data.values() for x in entries)
    read_pct = 100 * read_n / all_n
    rows, hist_rows, depth_rows = [], [], []
    direction_data["total"] = [x for d in ("read", "write") for x in direction_data.get(d, [])]
    for direction, entries in direction_data.items():
        count = sum(int(x["total_ios"]) for x in entries)
        def mean(kind):
            observations = [(latency_block(x, kind), x["total_ios"]) for x in entries]
            denominator = sum(int(block.get("N", fallback)) for (block, _), fallback in observations)
            return (sum(block.get("mean", 0.) * factor * int(block.get("N", fallback))
                        for (block, factor), fallback in observations) / denominator) if denominator else 0.
        clat_samples = sum(int(latency_block(x, "clat")[0].get("N", x["total_ios"])) for x in entries)
        bins = defaultdict(int)
        for x in entries:
            block, factor = latency_block(x, "clat")
            for value, n in block.get("bins", {}).items():
                bins[float(value) * factor] += int(n)
        if len(entries) > 1 and not bins:
            raise ValueError("Cannot merge latency percentiles without JSON+ histogram bins")
        if bins and sum(bins.values()) != clat_samples:
            raise ValueError("Merged completion histogram count differs from completion-latency sample N")
        pct = {}
        for p, key in ((50, "p50_us"), (95, "p95_us"), (99, "p99_us"), (99.9, "p999_us")):
            if bins:
                pct[key] = histogram_percentile(bins, p)
            else:
                block, factor = latency_block(entries[0], "clat")
                vals = block.get("percentile", {})
                pct[key] = next((float(v)*factor for k, v in vals.items() if abs(float(k)-p)<1e-5), math.nan)
        iops = sum(float(x.get("iops", 0.)) for x in entries)
        bw = sum(float(x.get("bw_bytes", x.get("bw", 0.) * 1024)) for x in entries)
        qd = case["iodepth"] * case["numjobs"]
        row = {**case, "direction": direction, "run_id": run_id, "trial": trial,
               "io_count": count, "clat_samples": clat_samples, "io_bytes": sum(int(x.get("io_bytes", x.get("io_kbytes", 0)*1024)) for x in entries),
               "iops": iops, "mib_s": bw / 1024**2, "mb_s": bw / 1e6,
               "mean_lat_us": mean("lat"), "mean_clat_us": mean("clat"), "mean_slat_us": mean("slat"),
               "achieved_read_pct": read_pct, **pct}
        row["little_l_total"] = iops * row["mean_lat_us"] / 1e6
        row["little_l_clat"] = iops * row["mean_clat_us"] / 1e6
        row["clat_qd_fraction"] = row["little_l_clat"] / qd
        rows.append(row)
        for latency, n in sorted(bins.items()):
            hist_rows.append({"run_id": run_id, "case_id": case["case_id"], "trial": trial,
                              "direction": direction, "clat_us": latency, "count": n})
        if direction != "total" and clat_samples < 100000:
            issues.append({"run_id": run_id, "type": "tail_sample_size", "detail": f"{direction}: clat N={clat_samples}; fewer than 100 expected samples beyond p99.9. Interpret that tail cautiously."})
    total = next(x for x in rows if x["direction"] == "total")
    if case["engine"] == "libaio" and qd > 1 and total["clat_qd_fraction"] < .5:
        issues.append({"run_id": run_id, "type": "queue_occupancy", "detail": f"lambda*mean(clat)={total['little_l_clat']:.2f} versus configured aggregate QD={qd}; inspect per-job depth buckets, submission overhead, and virtualization."})
    if abs(read_pct - case["read_pct"]) > 5 and all_n > 10000:
        issues.append({"run_id": run_id, "type": "mix_deviation", "detail": f"Achieved read percentage {read_pct:.2f}, requested {case['read_pct']}"})
    for index, job in enumerate(jobs, 1):
        for bucket, pct in job.get("iodepth_level", {}).items():
            depth_rows.append({"run_id": run_id, "case_id": case["case_id"], "trial": trial,
                               "job": index, "configured_per_job_qd": case["iodepth"],
                               "bucket": str(bucket), "percent": pct,
                               "note": "64 means at least 64; buckets are not exact time-weighted hardware occupancy"})
    return rows, hist_rows, depth_rows, issues


def summarize_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["case_id"], row["direction"])].append(row)
    summaries = []
    for key, group in sorted(groups.items()):
        result = {k: group[0].get(k, "") for k in META}
        result["n"] = len(group)
        for metric in METRICS:
            values = [float(r[metric]) for r in group if math.isfinite(float(r[metric]))]
            for suffix, value in (("mean", stats.mean(values) if values else math.nan),
                                  ("median", stats.median(values) if values else math.nan),
                                  ("sd", stats.stdev(values) if len(values)>1 else 0.),
                                  ("min", min(values) if values else math.nan),
                                  ("max", max(values) if values else math.nan)):
                result[f"{metric}_{suffix}"] = value
        summaries.append(result)
    return summaries


def choose_knee(curve):
    """A declared saturation heuristic, never an assertion of a physical device knee."""
    curve = sorted(curve, key=lambda x: x["iodepth"])
    maximum = max(r["mib_s_median"] for r in curve)
    for a, b in zip(curve, curve[1:]):
        if (maximum > 0 and a["mib_s_median"] >= .9*maximum and b["mib_s_median"] >= .9*maximum
                and b["mib_s_median"] <= 1.1*a["mib_s_median"]
                and b["mean_lat_us_median"] >= 1.25*a["mean_lat_us_median"]):
            return {"selected_qd": a["iodepth"], "plateau_observed": True,
                    "reason": "Earliest adjacent pair at >=90% of peak median throughput, <=10% throughput gain, and >=25% latency growth"}
    return {"selected_qd": curve[-1]["iodepth"], "plateau_observed": False,
            "reason": "No adjacent pair satisfied the declared plateau rule; use highest tested QD for tail comparison and report knee not established"}


def load_events(out):
    path = out / "journal.jsonl"
    if not path.exists():
        return []
    events = []
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        try:
            events.append(json.loads(line))
        except ValueError:
            if i != len(lines)-1:
                # Runner repairs a truncated record by adding a newline; retain an explicit issue.
                events.append({"status": "corrupt", "error": f"Invalid journal line {i+1}"})
    return events


def time_logs(out, event):
    rows = []
    for kind, metric, factor in (("bw", "mib_s", 1/1024), ("iops", "iops", 1),
                                 ("clat", "mean_clat_us", 1/1000), ("lat", "mean_lat_us", 1/1000)):
        for path in sorted((out / "logs").glob(f"{event['run_id']}_{kind}.*.log")):
            job = path.name.rsplit(".", 2)[-2]
            with path.open() as f:
                for line in csv.reader(f):
                    if len(line) < 3:
                        continue
                    try:
                        rows.append({"run_id": event["run_id"], "case_id": event["case"]["case_id"],
                                     "family": event["case"]["family"], "trial": event["trial"], "job": job,
                                     "time_s": float(line[0])/1000,
                                     "direction": {0:"read", 1:"write", 2:"trim"}.get(int(line[2]), "other"),
                                     "metric": metric, "value": float(line[1])*factor})
                    except (ValueError, IndexError):
                        raise ValueError(f"Malformed fio time log: {path}")
    return rows


def markdown_table(path, headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in rows]
    path.write_text("\n".join(lines) + "\n")


def interval_window_mean(values, start, end):
    """Weight interval means by overlap with a fixed observation horizon.

    fio may emit a tiny final interval during queue drain. It remains in the
    raw logs and plots, but cannot receive the weight of a full second here.
    """
    previous = 0.
    weighted = duration = 0.
    for row in sorted(values,key=lambda r:r["time_s"]):
        timestamp = row["time_s"]
        overlap = max(0.,min(timestamp,end)-max(previous,start))
        weighted += row["value"] * overlap
        duration += overlap
        previous = max(previous,timestamp)
    return weighted/duration if duration else ""


def analyze(directory):
    out = Path(directory)
    dest = out / "analysis"
    dest.mkdir(exist_ok=True)
    events = load_events(out)
    completed = {}
    for e in events:
        if e.get("phase") == "measured" and e.get("status") == "complete":
            completed[(e["case"]["case_id"], e["trial"])] = e
    rows, hist, depths, issues, times = [], [], [], [], []
    valid = set()
    for key, e in sorted(completed.items()):
        try:
            raw = out / e["raw"]
            if e.get("raw_sha256") and hashlib.sha256(raw.read_bytes()).hexdigest() != e["raw_sha256"]:
                raise ValueError("Raw SHA256 differs from journal")
            r, h, d, i = parse_document(read_json(raw), e["case"], e["run_id"], e["trial"])
            t = time_logs(out, e)
            rows.extend(r); hist.extend(h); depths.extend(d); issues.extend(i); times.extend(t)
            valid.add(key)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append({"run_id": e["run_id"], "type": "invalid_result", "detail": str(exc)})
    for e in events:
        if e.get("status") in ("failed", "corrupt"):
            issues.append({"run_id": e.get("run_id", "journal"), "type": "execution_failure", "detail": e.get("error", "unknown")})
    summary = summarize_rows(rows)
    write_csv(dest / "measurements.csv", rows, [*META, "run_id", "trial", *METRICS])
    write_csv(dest / "summary.csv", summary, [*META, "n", *(f"{m}_{s}" for m in METRICS for s in ("mean", "median", "sd", "min", "max"))])
    write_csv(dest / "histograms.csv", hist, ["run_id", "case_id", "trial", "direction", "clat_us", "count"])
    write_csv(dest / "depths.csv", depths, ["run_id", "case_id", "trial", "job", "configured_per_job_qd", "bucket", "percent", "note"])
    write_csv(dest / "issues.csv", issues, ["run_id", "type", "detail"])
    write_csv(dest / "timeseries.csv", times, ["run_id", "case_id", "family", "trial", "job", "time_s", "direction", "metric", "value"])
    knees = []
    for pattern in ("random", "sequential"):
        for read in (100, 0):
            curve = [r for r in summary if r["family"]=="queue" and r["direction"]=="total" and r["pattern"]==pattern and r["read_pct"]==read]
            if curve:
                knees.append({"pattern": pattern, "read_pct": read, **choose_knee(curve)})
    write_csv(dest / "knees.csv", knees, ["pattern", "read_pct", "selected_qd", "plateau_observed", "reason"])
    little = [{k:r[k] for k in ("case_id", "pattern", "read_pct", "iodepth", "numjobs", "total_qd",
                "iops_mean", "mean_lat_us_mean", "mean_clat_us_mean", "little_l_total_mean", "little_l_clat_mean", "clat_qd_fraction_mean")}
              for r in summary if r["direction"]=="total" and r["family"] in ("queue", "parallel")]
    write_csv(dest / "little_law.csv", little)
    state = []
    for key, e in sorted(completed.items()):
        if key not in valid or e["case"]["family"] != "state":
            continue
        for metric in ("mib_s", "mean_clat_us"):
            values = sorted([t for t in times if t["run_id"]==e["run_id"] and t["metric"]==metric and t["direction"]=="write"], key=lambda t:t["time_s"])
            if not values:
                continue
            # Equal-duration thirds (not an assertion that the last third is a steady state).
            duration = e["case"]["runtime"]
            state.append({"run_id":e["run_id"], "trial":e["trial"], "metric":metric,
                          "first_third_mean":interval_window_mean(values,0,duration/3),
                          "last_third_mean":interval_window_mean(values,2*duration/3,duration),
                          "note":"Interval means weighted by time overlap with measured horizon; queue drain after runtime has zero weight. No steady-state claim."})
    write_csv(dest / "state_windows.csv", state, ["run_id", "trial", "metric", "first_third_mean", "last_third_mean", "note"])
    manifest = read_json(out / "manifest.json") if (out / "manifest.json").exists() else {"parameters":{}}
    params = manifest["parameters"]
    expected_cases = read_json(out / "plan.json")["cases"] if (out / "plan.json").exists() else []
    if (out / "adaptive_tails.json").exists():
        expected_cases += read_json(out / "adaptive_tails.json")["cases"]
    expected = {(c["case_id"],t) for c in expected_cases for t in range(1, params.get("trials",1)+1)}
    coverage = {"expected_runs_selected_so_far":len(expected), "valid_runs":len(valid),
                "missing_runs":[{"case_id":k[0],"trial":k[1]} for k in sorted(expected-valid)],
                "adaptive_tails_pending":"tail" in params.get("families",[]) and not (out/"adaptive_tails.json").exists(),
                "requested_families":params.get("families",[]), "profile":params.get("profile", "unknown"),
                "all_selected_runs_complete":expected.issubset(valid) and bool(expected),
                "warnings":len(issues), "measured_write_gib_excluding_ramp_and_initialization":sum(r["io_bytes"] for r in rows if r["direction"]=="write")/1024**3}
    coverage["all_selected_runs_complete"] &= not coverage["adaptive_tails_pending"]
    # A successful subset or smoke run must never imply full assignment coverage.
    from .plan import build_cases
    required_ids = {c.case_id for c in build_cases(params.get("size",16*1024**3))}
    repeated_ids = {cid for cid in {k[0] for k in valid} if sum(k[0]==cid for k in valid)>=2}
    tail_ids = {c["case_id"] for c in expected_cases if c["family"]=="tail"}
    coverage["full_default_setting_matrix_with_repeats"] = required_ids.issubset(repeated_ids) and len(tail_ids)==8 and tail_ids.issubset(repeated_ids)
    coverage["coverage_note"] = "Selected-run completion and matrix coverage are separate checks; neither establishes report quality or causal interpretation."
    dump_json(dest/"coverage.json", coverage)
    baselines = [r for r in summary if r["family"]=="baseline" and r["direction"]!="total"]
    markdown_table(dest/"baseline_table.md", ["Pattern", "KiB", "Direction", "n", "IOPS", "MiB/s", "Mean total us", "p50 clat us", "p95 clat us", "p99 clat us", "p99.9 clat us"],
                   [[r["pattern"], r["bs"]//1024, r["direction"], r["n"], *(f"{r[m+'_mean']:.3f}" for m in ("iops","mib_s","mean_lat_us","p50_us","p95_us","p99_us","p999_us"))] for r in baselines])
    tails = [r for r in summary if r["family"]=="tail" and r["direction"]!="total"]
    markdown_table(dest/"tail_table.md", ["Pattern", "Direction", "Role", "QD", "n", "Mean N", "p50 us", "p95 us", "p99 us", "p99.9 us"],
                   [[r["pattern"],r["direction"],r["role"],r["iodepth"],r["n"],int(r["clat_samples_mean"]),*(f"{r[m+'_mean']:.3f}" for m in ("p50_us","p95_us","p99_us","p999_us"))] for r in tails])
    maxima=[]
    for read in (100,0):
        for name, pattern, bs, metric in (("small_block_iops","random",4096,"iops"),("sequential_throughput","sequential",None,"mib_s")):
            candidates=[r for r in summary if r["direction"]=="total" and r["read_pct"]==read and r["pattern"]==pattern and (bs is None or r["bs"]==bs) and r["direct"]==1 and r["family"] in ("block","queue","parallel")]
            if candidates:
                r=max(candidates,key=lambda r:r[metric+"_median"])
                maxima.append({"measurement":name,"read_pct":read,"metric":metric,"median":r[metric+"_median"],"case_id":r["case_id"],"note":"Maximum observed in tested matrix, not a device specification"})
    write_csv(dest/"maxima.csv",maxima,["measurement","read_pct","metric","median","case_id","note"])
    print(f"Parsed {len(valid)} valid measured runs; {len(expected-valid)} missing; {len(issues)} diagnostic notes. {dest}")
    return coverage
