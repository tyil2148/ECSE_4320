from __future__ import annotations

import hashlib
import json
import os
import random
import re
import signal
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from .common import digest, dump_json, read_json, utcnow, write_csv
from .environment import check_filesystem, collect, snapshot
from .plan import Case, FAMILIES, fio_config
from .safety import DATA, MARKER, allocate, create_target, locked, target_directory, validate_target


def fio_binary(binary):
    try:
        p = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Install the Flexible I/O Tester: sudo apt install fio. Do not pip install fio (Fiona has a different fio command).") from exc
    if p.returncode or not re.match(r"^fio-3\.", p.stdout.strip()):
        raise ValueError(f"Expected Flexible I/O Tester fio 3.x, received {p.stdout.strip()!r}")
    return p.stdout.strip()


def execute(binary, config, raw, stderr, timeout=None, readonly=False):
    argv = [binary, "--eta=never", "--output-format=json+", f"--output={raw}"]
    if readonly:
        argv.append("--readonly")
    argv.append(str(config))
    started = time.monotonic()
    process = None
    try:
        with stderr.open("w", encoding="utf-8") as err, raw.with_suffix(".stdout.txt").open("w", encoding="utf-8") as stdout:
            process = subprocess.Popen(argv, stdout=stdout, stderr=err, start_new_session=True)
            try:
                rc = process.wait(timeout=timeout)
            except (KeyboardInterrupt, subprocess.TimeoutExpired):
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=10)
                raise
    except OSError as exc:
        raise ValueError(f"Cannot execute fio: {exc}") from exc
    if rc:
        raise ValueError(f"fio exited {rc}; inspect {stderr} and {raw}")
    try:
        data = read_json(raw)
        jobs = data["jobs"]
    except (OSError, ValueError, KeyError) as exc:
        raise ValueError(f"Invalid fio JSON in {raw}") from exc
    if not jobs or any(int(j.get("error", 0)) for j in jobs):
        raise ValueError(f"fio job reported an error; inspect {raw}")
    if not sum(j.get(d, {}).get("total_ios", 0) for j in jobs for d in ("read", "write")):
        raise ValueError("fio completed no I/O")
    return {"argv": argv, "elapsed_s": time.monotonic() - started,
            "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}


def initialize(value, size, binary):
    directory = target_directory(value)
    check_filesystem(directory)
    fio_binary(binary)
    reserve = create_target(directory, size)
    with locked(directory):
        meta = allocate(directory, size)
        case = Case("initialize", "initialize", "sequential", 0, 1024**2, 16, 1, size, 0, 0)
        config = directory / "initialize.fio"
        config.write_text(fio_config(case, directory / DATA, 8128, initialize=True))
        dump_json(directory / "environment_before.json", collect(directory, binary))
        print(f"Writing all {size / 1024**3:.3f} GiB once to {directory / DATA}; Linux reserve {reserve/1024**3:.1f} GiB", flush=True)
        result = execute(binary, config, directory / "initialize.json", directory / "initialize.stderr.txt")
        raw = read_json(directory / "initialize.json")
        written = sum(j.get("write", {}).get("io_bytes", 0) for j in raw["jobs"])
        if written < size:
            raise ValueError(f"Initialization wrote only {written} of {size} bytes; target remains uninitialized")
        validate_target(directory, require_initialized=False)
        meta.update(initialized=True, initialized_utc=utcnow(), initialization=result)
        dump_json(directory / MARKER, meta)
        print("Initialization completed. All tested regions contain written data.")
    return meta


def source_hashes(root):
    result = {}
    for subdir in ("ssdbench", "scripts"):
        for p in sorted((root / subdir).glob("*.py")):
            result[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def journal_events(out):
    path = out / "journal.jsonl"
    events = []
    if path.exists():
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            try:
                events.append(json.loads(line))
            except ValueError:
                # A killed process may leave one truncated final record, never ignore an interior one.
                if index != len(lines) - 1:
                    raise ValueError(f"Corrupt journal line {index+1}")
    return events


def append_event(out, event):
    # Repair a crash-truncated final line before appending an independent JSON record.
    path = out / "journal.jsonl"
    if path.exists():
        content = path.read_bytes()
        if content and not content.endswith(b"\n"):
            final_line = content.rsplit(b"\n", 1)[-1]
            try:
                json.loads(final_line)
            except ValueError:
                fragment = out / f"journal_fragment_{time.time_ns()}.txt"
                fragment.write_bytes(final_line)
                path.write_bytes(content[:-len(final_line)])
            else:
                with path.open("ab") as f:
                    f.write(b"\n")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"utc": utcnow(), **event}, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def export_plan(out, cases, params, directory, initialize_only=False):
    out.mkdir(parents=True, exist_ok=False)
    (out / "configs").mkdir()
    dump_json(out / "plan.json", {"parameters": params, "cases": [c.dictionary() for c in cases],
                                "adaptive_tails": "Selected from repeated queue curves after static runs; see methodology"})
    write_csv(out / "cases.csv", [c.dictionary() for c in cases])
    for c in cases:
        (out / "configs" / f"{c.case_id}.fio").write_text(fio_config(c, directory / DATA, params["seed"]))


def run_suite(args, cases, params):
    from .analysis import analyze, choose_knee, summarize_rows, parse_document

    directory = target_directory(args.target_dir)
    check_filesystem(directory)
    version = fio_binary(args.fio)
    out = Path(args.out).expanduser().absolute()
    for p in (out, *out.parents):
        if p.is_symlink():
            raise ValueError("Symlinks are not allowed in the output directory path")
    if out == directory or directory in out.parents:
        raise ValueError("Keep results outside the disposable test directory")
    with locked(directory):
        meta = validate_target(directory)
        if meta["size"] != params["size"]:
            raise ValueError("Plan size differs from the initialized data file")
        fingerprint = digest({"parameters": params, "target_uuid": meta["uuid"],
                              "source": source_hashes(Path(__file__).resolve().parent.parent), "fio_version": version})
        if args.resume:
            if read_json(out / "manifest.json")["fingerprint"] != fingerprint:
                raise ValueError("Resume requires the same parameters, target, code, and fio version")
        else:
            export_plan(out, cases, params, directory)
            for folder in ("raw", "logs", "telemetry", "analysis"):
                (out / folder).mkdir()
            manifest = {"schema": "ssdbench-run-v1", "fingerprint": fingerprint, "created_utc": utcnow(),
                        "parameters": params, "target": meta, "target_directory": str(directory),
                        "source_sha256": source_hashes(Path(__file__).resolve().parent.parent),
                        "fio_version": version, "environment": collect(directory, args.fio)}
            if args.host_metadata:
                manifest["host_metadata"] = read_json(args.host_metadata)
            if args.notes:
                manifest["operator_notes"] = read_json(args.notes)
            dump_json(out / "manifest.json", manifest)

        done = {(e["case"]["case_id"], e["trial"]): e for e in journal_events(out)
                if e.get("status") == "complete" and e.get("phase") == "measured"}
        # Validate retained raw bytes, so resume never silently treats missing/corrupted data as done.
        for event in done.values():
            p = out / event["raw"]
            if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != event["raw_sha256"]:
                raise ValueError(f"Retained raw result missing or changed: {p}")

        def run_one(case, trial):
            if (case.case_id, trial) in done:
                return
            validate_target(directory)
            events = journal_events(out)
            base = f"{case.case_id}_t{trial:02d}"
            attempt = 1 + sum(e.get("base") == base and e.get("status") == "started" for e in events)
            run_id = f"{base}_a{attempt:02d}"
            config = out / "configs" / f"{run_id}.fio"
            raw = out / "raw" / f"{run_id}.json"
            seed = params["seed"] + trial * 100003 + int(digest(case.case_id)[:6], 16)
            event = {"run_id": run_id, "base": base, "trial": trial, "case": case.dictionary(),
                     "phase": "measured", "raw": str(raw.relative_to(out)), "seed": seed}
            append_event(out, {**event, "status": "started"})
            print(f"[{trial}/{params['trials']}] {case.case_id} ({case.runtime}+{case.ramp}s)", flush=True)
            dump_json(out / "telemetry" / f"{run_id}_before.json", snapshot(directory))
            try:
                if case.family == "pitfall":
                    # Both controls start with an identical finite buffered sequential warm pass.
                    warm_case = replace(case, case_id=run_id + "_warm", pattern="sequential", bs=128*1024, direct=0)
                    warm_config = out / "configs" / f"{run_id}_warm.fio"
                    warm_config.write_text(fio_config(warm_case, directory / DATA, seed, warm=True))
                    warm_raw = out / "raw" / f"{run_id}_warm.json"
                    warm_result = execute(args.fio, warm_config, warm_raw, warm_raw.with_suffix(".stderr.txt"), timeout=180, readonly=True)
                    append_event(out, {**event, "phase": "cache_warm", "raw": str(warm_raw.relative_to(out)),
                                       "status": "complete", **warm_result})
                config.write_text(fio_config(case, directory / DATA, seed, log_prefix=out / "logs" / run_id))
                result = execute(args.fio, config, raw, raw.with_suffix(".stderr.txt"),
                                 timeout=case.runtime + case.ramp + 120, readonly=case.read_pct == 100)
                # Parsing is also a validity check, including completion counts and direction consistency.
                parse_document(read_json(raw), case.dictionary(), run_id, trial)
                dump_json(out / "telemetry" / f"{run_id}_after.json", snapshot(directory))
                append_event(out, {**event, "status": "complete", **result})
                done[(case.case_id, trial)] = {**event, **result}
            except BaseException as exc:
                append_event(out, {**event, "status": "failed", "error": str(exc) or type(exc).__name__})
                raise
            if args.cooldown:
                time.sleep(args.cooldown)

        try:
            for trial in range(1, params["trials"] + 1):
                for family in FAMILIES:
                    selected = [c for c in cases if c.family == family]
                    random.Random(params["seed"] + trial * 1009 + FAMILIES.index(family)).shuffle(selected)
                    for c in selected:
                        run_one(c, trial)
            if "tail" in params["families"]:
                selection_path = out / "adaptive_tails.json"
                if selection_path.exists():
                    tails = [Case(**{k: v for k, v in row.items() if k != "total_qd"}) for row in read_json(selection_path)["cases"]]
                else:
                    rows = []
                    for event in done.values():
                        if event["case"]["family"] == "queue":
                            rows.extend(parse_document(read_json(out / event["raw"]), event["case"], event["run_id"], event["trial"])[0])
                    tails, selections = [], []
                    for pattern, bs in (("random", 4096), ("sequential", 131072)):
                        for read in (100, 0):
                            curve = [r for r in summarize_rows(rows) if r["direction"] == "total" and r["pattern"] == pattern and r["read_pct"] == read]
                            if not curve:
                                raise ValueError("Adaptive tails require queue runs. Include queue and tail together")
                            knee = choose_knee(curve)
                            near = knee["selected_qd"]
                            available = sorted({r["iodepth"] for r in curve})
                            mid = min(available, key=lambda q: abs(q - max(1, near / 2)))
                            selections.append({"pattern": pattern, "read_pct": read, "mid_qd": mid, **knee})
                            for q, role in ((mid, "mid"), (near, "near_knee" if knee["plateau_observed"] else "highest_tested")):
                                cid = f"tail_{pattern}_{bs//1024}k_r{read}_q{q}_{role}"
                                tails.append(Case(cid, "tail", pattern, read, bs, q, 1, params["size"], params["tail_seconds"], params["ramp"], role=role))
                    dump_json(selection_path, {"selections": selections, "cases": [c.dictionary() for c in tails]})
                for trial in range(1, params["trials"] + 1):
                    selected = list(tails)
                    random.Random(params["seed"] + trial * 1013).shuffle(selected)
                    for c in selected:
                        run_one(c, trial)
        finally:
            # Preserve useful parsed output even when interrupted or when an experiment fails.
            analyze(out)
        dump_json(out / "completed.json", {"utc": utcnow(), "fingerprint": fingerprint})
    print(f"Complete. Raw data and analysis: {out}")
