#!/usr/bin/env python3
"""Run balanced, single-CPU sweeps and preserve raw data plus exact commands."""
import argparse, csv, datetime, io, json, math, os, pathlib, random, subprocess
from environment import collect, cache_bytes
from build import ROOT, VARIANTS
KERNELS=('saxpy','dot','mul','stencil')

def active_arrays(kernel):return 3 if kernel=='mul' else 2

def cases(profile,max_mib):
    if profile=='smoke': sizes=[4096,65536,1048576]
    elif profile=='quick':sizes=[4096,32768,262144,2097152,16777216,max_mib*1024**2]
    else:sizes=[2**k for k in range(12,27) if 2**k<=max_mib*1024**2]+[max_mib*1024**2]
    output=[]
    def add(study,kernel,dtype,n,stride=1,shift=0):
        n=max(16,(int(n)+15)//16*16)
        output.append(dict(study=study,kernel=kernel,dtype=dtype,n=n,stride=stride,shift=shift))
    for kernel in KERNELS:
        for dtype,element in [('f32',4),('f64',8)]:
            for working in sorted(set(sizes)):
                add('locality',kernel,dtype,working//(active_arrays(kernel)*element))
    # Orthogonal studies: shift changes alone; N changes alone; stride changes
    # with fixed N, then with fixed footprint, to separate access and capacity.
    for dtype,element in [('f32',4),('f64',8)]:
        for n in ([256,8192] if profile=='smoke' else [256,8192,262144]):
            for shift in ([0,1] if profile!='full' else [0,1,3,7]):
                add('alignment','mul',dtype,n,shift=shift)
        for n in ([16,256] if profile=='smoke' else [16,64,256,4096]):
            for delta in range(0,9 if profile=='full' else 3):
                # Preserve tails here; add() intentionally rounds locality only.
                output.append(dict(study='tail',kernel='mul',dtype=dtype,n=n+delta,stride=1,shift=0))
        for working in ([65536,1048576] if profile=='smoke' else [65536,1048576,max_mib*1024**2]):
            base=max(128,working//(3*element)//128*128)
            for stride in [1,2,4,8]:
                # Cap the logical N for the fixed-N sweep so max padded active
                # footprint remains within the requested memory budget.
                add('stride_fixed_n','mul',dtype,max(16,base//8),stride)
                add('stride_fixed_footprint','mul',dtype,max(16,base//stride),stride)
        for n in ([4096] if profile=='smoke' else [4096,262144]):
            add('negative','strictdot',dtype,n)
        # Bandwidth calibration touches a footprint >= 4x a 16 MiB LLC by
        # default. The analyzer checks observed/user-specified LLC, not a guess.
        add('bandwidth','bandwidth',dtype,max_mib*1024**2//(2*element))
    unique={tuple(c.values()):c for c in output}
    return list(unique.values())

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['smoke','quick','full'],default='full')
    p.add_argument('--build',type=pathlib.Path,default=ROOT/'build')
    p.add_argument('--out',type=pathlib.Path,default=ROOT/'results')
    p.add_argument('--cpu',type=int,default=None)
    p.add_argument('--samples',type=int,default=None)
    p.add_argument('--seconds',type=float,default=None)
    p.add_argument('--max-mib',type=int,default=64,help='largest active working set; padded allocation is larger')
    p.add_argument('--seed',type=int,default=7530)
    p.add_argument('--notes',default='UNFILLED: record Windows power mode, AC/battery, WSL version and VM limits, SMT and background load')
    p.add_argument('--llc-mib',type=float,default=None,help='manual cache override, explicitly recorded')
    a=p.parse_args()
    samples=a.samples if a.samples is not None else (3 if a.profile=='smoke' else 7)
    seconds=a.seconds if a.seconds is not None else (0.01 if a.profile=='smoke' else 0.1)
    if not 1<=a.max_mib<=64:p.error('--max-mib must be 1..64 (bounds float reduction error and memory)')
    if samples<1 or samples>1000 or not math.isfinite(seconds) or seconds<=0 or seconds>10:p.error('invalid samples/seconds')
    if a.llc_mib is not None and (not math.isfinite(a.llc_mib) or a.llc_mib<=0):p.error('--llc-mib must be finite and positive')
    allowed=sorted(os.sched_getaffinity(0))
    cpu=allowed[0] if a.cpu is None else a.cpu
    if cpu not in allowed:p.error(f'CPU {cpu} not allowed; choose from {allowed}')
    for v in VARIANTS:
        if not (a.build/v/'benchmark').is_file():p.error('missing binaries: run scripts/build.py first')
    buildmeta=json.loads((a.build/'build.json').read_text())
    if buildmeta.get('sanitizer'):p.error('sanitizer binaries are for correctness checks, not measurements')
    out=a.out.resolve()
    if out.exists() and any(out.iterdir()):p.error('output directory must be new or empty; avoids mixing runs')
    out.mkdir(parents=True,exist_ok=True)
    environment=collect(cpu,a.notes)
    observed=max([cache_bytes(c.get('size')) or 0 for c in environment['caches'] if c.get('type') in ('Unified','Data')],default=0)
    environment['llc_bytes_used']=int(a.llc_mib*1024**2) if a.llc_mib is not None else observed or None
    environment['llc_source']='manual_override' if a.llc_mib is not None else 'WSL sysfs' if observed else 'unavailable'
    (out/'environment.json').write_text(json.dumps(environment,indent=2)+'\n')
    (out/'build.json').write_text(json.dumps(buildmeta,indent=2)+'\n')
    plan=cases(a.profile,a.max_mib)
    rng=random.Random(a.seed);rng.shuffle(plan)
    manifest=dict(profile=a.profile,samples=samples,target_seconds=seconds,seed=a.seed,cpu=cpu,max_mib=a.max_mib,cases=plan,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),commands=[])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    # Affinity inherited by every child. Record the original allowed set above.
    os.sched_setaffinity(0,{cpu})
    with (out/'raw.csv').open('w',newline='') as raw, (out/'commands.jsonl').open('w') as commands:
        writer=None
        for i,case in enumerate(plan):
            # Rotate the four build orders in a seeded random starting order.
            # Samples run in blocks; the order and thermal limitation are explicit.
            variants=list(VARIANTS);rng.shuffle(variants)
            for variant in variants:
                cmd=[str((a.build/variant/'benchmark').resolve()),'--kernel',case['kernel'],'--dtype',case['dtype'],
                     '--n',str(case['n']),'--stride',str(case['stride']),'--shift',str(case['shift']),
                     '--samples',str(samples),'--seconds',str(seconds)]
                commands.write(json.dumps(dict(case=case,variant=variant,command=cmd))+'\n');commands.flush()
                proc=subprocess.run(cmd,text=True,capture_output=True)
                if proc.returncode:
                    (out/'failure.txt').write_text(json.dumps(cmd)+'\n'+proc.stdout+proc.stderr)
                    raise RuntimeError(f'failed {variant} {case}: {proc.stderr}')
                reader=csv.DictReader(io.StringIO(proc.stdout));rows=list(reader)
                if len(rows)!=samples:raise RuntimeError('incomplete benchmark output')
                if writer is None:
                    writer=csv.DictWriter(raw,fieldnames=['study']+reader.fieldnames);writer.writeheader()
                for row in rows:writer.writerow(dict(study=case['study'],**row))
                raw.flush()
            print(f'[{i+1}/{len(plan)}] {case["study"]}: {case["kernel"]} {case["dtype"]} N={case["n"]} stride={case["stride"]} shift={case["shift"]}',flush=True)
    manifest['completed_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    manifest['complete']=True
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Raw measurements: {out / "raw.csv"}')
if __name__=='__main__':main()
