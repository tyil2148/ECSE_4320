#!/usr/bin/env python3
"""Optional whole-process hardware-counter audit. Not kernel-only attribution."""
import argparse, os, pathlib, shutil, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--build',type=pathlib.Path,default=ROOT/'build');p.add_argument('--out',type=pathlib.Path,default=ROOT/'perf-audit')
p.add_argument('--cpu',type=int,default=min(os.sched_getaffinity(0)))
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
if a.cpu not in os.sched_getaffinity(0):p.error('CPU not allowed')
os.sched_setaffinity(0,{a.cpu})
if not shutil.which('perf'):
    (a.out/'unavailable.txt').write_text('perf command unavailable; use wall time and disassembly. No counters invented.\n');sys.exit(0)
probe=subprocess.run(['perf','stat','-e','cycles,instructions','--','true'],text=True,capture_output=True)
(a.out/'probe.txt').write_text(probe.stdout+probe.stderr)
if probe.returncode:
    print('Hardware counters unavailable; retained diagnostic. Timing and disassembly remain usable.');sys.exit(0)
for kernel in ('saxpy','dot','mul','stencil','strictdot'):
    cmd=['perf','stat','-x,','-e','cycles,instructions,cache-references,cache-misses','-o',str(a.out/f'{kernel}.perf.csv'),'--',str((a.build/'native'/'benchmark').resolve()),'--kernel',kernel,'--dtype','f64','--n','1048576','--seconds','0.5','--samples','1']
    r=subprocess.run(cmd,text=True,capture_output=True)
    (a.out/f'{kernel}.stdout.csv').write_text(r.stdout);(a.out/f'{kernel}.stderr.txt').write_text(r.stderr)
print('Audit includes allocation, validation and calibration; do not label its counts as timed-kernel counts. Inner timed core cycles are in raw.csv when available.')
