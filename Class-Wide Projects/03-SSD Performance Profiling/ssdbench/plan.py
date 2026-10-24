from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .common import safe_fio_path

FAMILIES = ("baseline", "block", "mix", "queue", "parallel", "working_set", "pitfall", "state", "tail")
DEPTHS = (1, 2, 4, 8, 16, 32, 64, 128, 256)
BLOCKS = (4, 16, 32, 64, 128, 256)
MIB = 1024 ** 2


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    pattern: str
    read_pct: int
    bs: int
    iodepth: int
    numjobs: int
    working_set: int
    runtime: int
    ramp: int
    direct: int = 1
    engine: str = "libaio"
    role: str = ""

    @property
    def total_qd(self):
        return self.iodepth * self.numjobs

    def dictionary(self):
        return {**asdict(self), "total_qd": self.total_qd}


def build_cases(size, runtime=15, ramp=3, state_seconds=120,
                depths=DEPTHS, families=FAMILIES, smoke=False):
    if size < 64 * MIB or size % (8 * MIB):
        raise ValueError("Test file must be at least 64MiB and a multiple of 8MiB")
    if runtime < 1 or ramp < 0 or state_seconds < 1:
        raise ValueError("runtime/state-seconds must be positive; ramp must be nonnegative")
    unknown = set(families) - set(FAMILIES)
    if unknown:
        raise ValueError(f"Unknown families: {sorted(unknown)}")
    if not depths or any(d < 1 or d > 256 or d & (d - 1) for d in depths):
        raise ValueError("Depths must be powers of two from 1 through 256")
    cases = []

    def add(family, pattern, read, kib, q=1, jobs=1, ws=size, role="", direct=1, engine="libaio", seconds=None, lead=None):
        ws = (ws // (jobs * MIB)) * (jobs * MIB)
        cid = f"{family}_{pattern}_{kib}k_r{read}_q{q}_j{jobs}_s{ws // MIB}m_d{direct}"
        if role:
            cid += "_" + role
        cases.append(Case(cid, family, pattern, read, kib * 1024, q, jobs, ws,
                          runtime if seconds is None else seconds,
                          ramp if lead is None else lead, direct, engine, role))

    workloads = [("random", 4), ("sequential", 128)]
    if "baseline" in families:
        for pattern, block in workloads:
            for read in (100, 0):
                add("baseline", pattern, read, block)
    if "block" in families:
        for pattern in ("random", "sequential"):
            for block in ((4, 128) if smoke else BLOCKS):
                for read in (100, 0):
                    add("block", pattern, read, block, q=16)
    if "mix" in families:
        for pattern, block in workloads:
            for read in (0, 50, 70, 100):
                add("mix", pattern, read, block, q=16)
    if "queue" in families:
        for pattern, block in workloads:
            for read in (100, 0):
                for q in sorted(set(depths)):
                    add("queue", pattern, read, block, q=q)
    if "parallel" in families:
        for read in (100, 0):
            for total in ((16,) if smoke else (16, 64)):
                for jobs in ((1, 4) if smoke else (1, 2, 4, 8)):
                    add("parallel", "random", read, 4, q=total // jobs, jobs=jobs)
    if "working_set" in families:
        for ws in sorted({max(8 * MIB, size // 16 // MIB * MIB), size // 4 // MIB * MIB, size}):
            for read in (100, 0):
                add("working_set", "random", read, 4, q=16, ws=ws)
    if "pitfall" in families:
        for direct in (1, 0):
            add("pitfall", "random", 100, 4, ws=min(size, 256 * MIB), direct=direct, engine="psync", role="warm_cache")
    if "state" in families:
        add("state", "sequential", 0, 128, q=32, seconds=state_seconds, lead=0, role="sustained_window")
    return cases


def fio_config(case, target, seed, log_prefix=None, initialize=False, warm=False):
    """All offsets are disjoint between clones; total address range stays fixed."""
    target = safe_fio_path(target)
    per_job = case.working_set // case.numjobs
    if per_job % case.bs:
        raise ValueError("Each worker's region must be block aligned")
    if case.read_pct == 100:
        rw = "randread" if case.pattern == "random" else "read"
    elif case.read_pct == 0:
        rw = "randwrite" if case.pattern == "random" else "write"
    else:
        rw = "randrw" if case.pattern == "random" else "rw"
    opts = {
        "filename": target, "ioengine": case.engine, "direct": case.direct, "kb_base": 1024,
        "rw": rw, "bs": case.bs, "blockalign": case.bs, "size": per_job,
        "offset": 0, "offset_increment": per_job,
        "iodepth": case.iodepth, "numjobs": case.numjobs,
        "thread": 1, "group_reporting": 0, "allow_file_create": 0,
        "fallocate": "none", "overwrite": 1, "unlink": 0,
        "randseed": seed, "randrepeat": 1, "norandommap": 1,
        "refill_buffers": 1, "scramble_buffers": 1, "buffer_compress_percentage": 0,
        "invalidate": 0, "clat_percentiles": 1, "lat_percentiles": 0,
        "percentile_list": "50:95:99:99.9", "gtod_reduce": 0,
        "continue_on_error": "none", "exitall_on_error": 1,
    }
    if 0 < case.read_pct < 100:
        opts["rwmixread"] = case.read_pct
    if not (initialize or warm):
        opts.update(time_based=1, runtime=case.runtime, ramp_time=case.ramp)
    else:
        # A finite full-range pass, never a sparse allocation used as read data.
        opts["end_fsync"] = 1 if initialize else 0
    if log_prefix:
        prefix = safe_fio_path(log_prefix)
        opts.update(write_bw_log=prefix, write_iops_log=prefix, write_lat_log=prefix,
                    log_avg_msec=1000, per_job_logs=1,
                    bwavgtime=1000, iopsavgtime=1000)
    lines = ["; Generated by ssdbench. Run through the guarded Python runner.", "[global]"]
    lines += [f"{key}={value}" for key, value in opts.items()]
    lines += ["", f"[{case.case_id}]", ""]
    return "\n".join(lines)
