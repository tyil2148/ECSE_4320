from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .common import parse_size
from .environment import check_filesystem, collect
from .plan import DEPTHS, FAMILIES, build_cases
from .runner import export_plan, initialize, run_suite
from .safety import cleanup, locked, target_directory, validate_target


def parser():
    p = argparse.ArgumentParser(description="Project 3 SSD Performance Profiling. Disposable regular files only.")
    sub=p.add_subparsers(dest="command",required=True)
    for name in ("inspect","init","plan","run","cleanup"):
        q=sub.add_parser(name)
        q.add_argument("--target-dir",default="~/ssdbench-data")
        q.add_argument("--fio",default="fio",help="Flexible I/O Tester 3.x executable, not Fiona's Python CLI")
        if name in ("init","plan","run"):
            q.add_argument("--size",default=None,help="init/plan default 16GiB; run uses initialized file size")
        if name in ("plan","run"):
            q.add_argument("--profile",choices=("full","smoke"),default="full")
            q.add_argument("--out",required=True)
            q.add_argument("--trials",type=int,default=None)
            q.add_argument("--runtime",type=int,default=None,help="Measured seconds per ordinary case")
            q.add_argument("--ramp",type=int,default=None)
            q.add_argument("--state-seconds",type=int,default=None)
            q.add_argument("--tail-seconds",type=int,default=None)
            q.add_argument("--depths",default=None,help="Comma-separated powers of two, max 256")
            q.add_argument("--families",default=",".join(FAMILIES))
            q.add_argument("--seed",type=int,default=7530)
            q.add_argument("--cooldown",type=float,default=2,help="Seconds between measured runs; no drive reset is implied")
        if name=="run":
            q.add_argument("--resume",action="store_true")
            q.add_argument("--host-metadata",help="JSON produced by scripts/collect_host.ps1 on Windows")
            q.add_argument("--notes",help="Filled copy of config/operator_notes.json")
            q.add_argument("--no-plots",action="store_true")
        if name=="cleanup":
            q.add_argument("--delete-owned-file",action="store_true",help="Required explicit request to delete only workload.bin")
    for name in ("analyze","plot"):
        q=sub.add_parser(name)
        q.add_argument("--results",required=True)
    return p


def main(argv=None):
    args=parser().parse_args(argv)
    try:
        if args.command=="analyze":
            from .analysis import analyze
            analyze(args.results)
            return 0
        if args.command=="plot":
            from .plotting import plot
            plot(args.results)
            return 0
        directory=target_directory(args.target_dir)
        if args.command=="inspect":
            check_filesystem(directory)
            base=directory
            while not base.exists(): base=base.parent
            print(json.dumps(collect(base,args.fio),indent=2))
            return 0
        if args.command=="init":
            size=parse_size(args.size or "16GiB")
            # Reuse plan validation for initialization alignment and minimum size.
            build_cases(size,families=())
            initialize(directory,size,args.fio)
            return 0
        if args.command=="cleanup":
            if not args.delete_owned_file:
                raise ValueError("Cleanup requires --delete-owned-file; results and initialization logs are retained")
            with locked(directory):
                count=cleanup(directory)
            print(f"Deleted only the owned data file and ownership marker ({count/1024**3:.3f} GiB). Initialization evidence is retained.")
            return 0
        smoke=args.profile=="smoke"
        size=parse_size(args.size) if args.size else (validate_target(directory)["size"] if args.command=="run" else 16*1024**3)
        runtime=args.runtime if args.runtime is not None else (2 if smoke else 15)
        ramp=args.ramp if args.ramp is not None else (0 if smoke else 3)
        trials=args.trials if args.trials is not None else (1 if smoke else 3)
        state=args.state_seconds if args.state_seconds is not None else (5 if smoke else 120)
        tail=args.tail_seconds if args.tail_seconds is not None else (3 if smoke else 45)
        depths=tuple(sorted(set(int(x) for x in args.depths.split(",")))) if args.depths else ((1,4,16) if smoke else DEPTHS)
        families=tuple(x.strip() for x in args.families.split(",") if x.strip())
        if trials<1 or tail<1 or args.cooldown<0 or args.seed<1:
            raise ValueError("trials/tail-seconds/seed must be positive; cooldown must be nonnegative")
        if "tail" in families and "queue" not in families:
            raise ValueError("Include queue when requesting adaptive tail experiments")
        cases=build_cases(size,runtime,ramp,state,depths,families,smoke)
        if not cases:
            raise ValueError("No experiments selected")
        params={"profile":args.profile,"size":size,"runtime":runtime,"ramp":ramp,"trials":trials,
                "state_seconds":state,"tail_seconds":tail,"depths":list(depths),"families":list(families),
                "seed":args.seed,"cooldown":args.cooldown}
        tail_count=8 if "tail" in families else 0
        seconds=sum(c.runtime+c.ramp+args.cooldown for c in cases)*trials+(tail+ramp+args.cooldown)*tail_count*trials
        write_seconds=sum((c.runtime+c.ramp)*(1-c.read_pct/100) for c in cases)*trials
        if tail_count: write_seconds += 4*(tail+ramp)*trials
        print(f"{len(cases)} static cases + {tail_count} adaptive tail cases; {trials} trial(s) each.")
        print(f"Nominal workload and cooldown time {seconds/60:.1f} minutes, plus startup, initialization, and cache warming.")
        print(f"Write exposure: {write_seconds:.0f} write-weighted seconds plus initialization; at 1 GiB/s this is approximately {write_seconds+size/1024**3:.0f} GiB. Actual write volume depends on each workload's rate.")
        if smoke:
            print("SMOKE PROFILE: checks the pipeline only; it does not cover the full rubric.")
        if args.command=="plan":
            export_plan(Path(args.out).expanduser(),cases,params,directory)
            print(f"Plan and non-executed fio configs: {args.out}")
        else:
            run_suite(args,cases,params)
            if not args.no_plots:
                from .plotting import plot
                plot(args.out)
        return 0
    except KeyboardInterrupt:
        print("Interrupted. Data is retained; resume with the identical command plus --resume.",file=sys.stderr)
        return 130
    except (ValueError,OSError,KeyError,ImportError,subprocess.SubprocessError) as exc:
        print(f"Error: {exc}",file=sys.stderr)
        return 2
