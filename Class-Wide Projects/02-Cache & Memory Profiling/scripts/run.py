#!/usr/bin/env python3
"""Reproducible experiment runner; Python standard library only."""
import argparse, csv, hashlib, itertools, json, os, platform, random, shutil, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MIB=1024**2

def read(p):
    try:return Path(p).read_text().strip()
    except OSError:return 'unavailable'

def command(argv):
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=20)
        return {'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    except (OSError,subprocess.TimeoutExpired) as e:return {'argv':argv,'error':str(e)}

def cache_info(cpu):
    out=[]
    for p in sorted(Path(f'/sys/devices/system/cpu/cpu{cpu}/cache').glob('index*')):
        d={k:read(p/k) for k in ['level','type','size','coherency_line_size','shared_cpu_list','ways_of_associativity','number_of_sets']}
        try:d['bytes']=int(d['size'][:-1])*{'K':1024,'M':MIB}[d['size'][-1]]
        except (ValueError,KeyError):d['bytes']=None
        out.append(d)
    return out

def cpu_order(allowed):
    # Prefer distinct physical cores before sibling vCPUs, using guest topology.
    groups={}
    for cpu in allowed:
        root=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        key=(read(root/'physical_package_id'),read(root/'core_id'))
        groups.setdefault(key,[]).append(cpu)
    primary=[v[0] for v in groups.values()]
    siblings=[c for v in groups.values() for c in v[1:]]
    return primary+siblings

def memory_available():
    m={x.split(':')[0]:int(x.split()[1])*1024 for x in read('/proc/meminfo').splitlines() if ':' in x and len(x.split())>1 and x.split()[1].isdigit()}
    available=m.get('MemAvailable',m.get('MemTotal',2**30))
    # Respect a container limit if the suite is tested within one.
    try:
        lim=int(read('/sys/fs/cgroup/memory.max'));cur=int(read('/sys/fs/cgroup/memory.current'))
        available=min(available,max(0,lim-cur))
    except ValueError:pass
    return available

def metadata(args,cpus,caches):
    paths=['/etc/os-release','/proc/cpuinfo','/proc/meminfo','/proc/sys/kernel/perf_event_paranoid','/sys/devices/system/cpu/smt/active','/sys/kernel/mm/transparent_hugepage/enabled','/sys/kernel/mm/transparent_hugepage/defrag','/proc/sys/vm/nr_hugepages','/proc/self/status']
    d={'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'platform':platform.platform(),'python':sys.version,'wsl_detected':'microsoft' in platform.release().lower(),'arguments':vars(args),'allowed_cpus':sorted(os.sched_getaffinity(0)),'cpu_order':cpus,'cache_info':caches,'files':{p:read(p) for p in paths},'tools':[command(x) for x in [['g++','--version'],['make','--version'],['uname','-a'],['lscpu'],['numactl','--hardware'],['perf','--version'],['perf','list']]]}
    for cpu in cpus:
        d['files'][f'cpu{cpu}_topology']={x:read(f'/sys/devices/system/cpu/cpu{cpu}/topology/{x}') for x in ['core_id','physical_package_id','thread_siblings_list']}
        d['files'][f'cpu{cpu}_frequency']={x:read(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/{x}') for x in ['scaling_governor','scaling_driver','scaling_min_freq','scaling_max_freq','scaling_cur_freq']}
    d['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for folder in ['src','scripts'] for p in (ROOT/folder).glob('*') if p.is_file()}
    return d

def plan(profile,caches,cpus,dram_mib=None):
    smoke=profile=='smoke'
    # Guest-reported capacities take precedence. Fallbacks are planning values,
    # never recorded as observed hardware facts.
    cap={1:32*1024,2:512*1024,3:16*MIB}
    for c in caches:
        if c['type'] in ['Data','Unified'] and c['bytes']:
            cap[int(c['level'])]=c['bytes']
    dram=(dram_mib*MIB if dram_mib else max(64*MIB,4*cap[3]))
    jobs=[]
    def add(experiment,mode,**kw):jobs.append(dict(experiment=experiment,mode=mode,**kw))
    base_sizes=[4*1024,8*1024,16*1024,32*1024,64*1024,128*1024,256*1024,512*1024,MIB,2*MIB,4*MIB,8*MIB,16*MIB,32*MIB,64*MIB,128*MIB,256*MIB]
    sizes=[4096,65536,2*MIB] if smoke else sorted(set(base_sizes+[max(4096,cap[1]//2),cap[2]//2,cap[3]//2,dram]))
    for size in sizes:
        add('working_set','chase',bytes=size,stride=64,pattern='random',pages='base')
    baseline=[('L1_candidate',max(4096,cap[1]//2)),('L2_candidate',max(cap[1]*2,cap[2]//2)),('LLC_candidate',max(cap[2]*2,cap[3]//2)),('DRAM_candidate',dram)]
    for label,size in baseline:
        add('baseline','chase',bytes=min(size,2*MIB) if smoke else size,stride=64,pattern='random',pages='base',level_candidate=label)
    for pattern,stride,gran,r in itertools.product(['sequential','random'],[64,256,1024],[8,64],[100,0,70,50]):
        # Match visited line footprint across strides; virtual span grows.
        span=(256*1024 if smoke else dram)*stride//64
        add('pattern_mix','stream',bytes=span,stride=stride,granularity=gran,read_pct=r,pattern=pattern,pages='base')
    for pattern,stride in itertools.product(['sequential','random'],[64,256,1024]):
        add('pattern_latency','chase',bytes=(256*1024 if smoke else dram)*stride//64,stride=stride,pattern=pattern,pages='base')
    for n in ([16,512] if smoke else [16,32,64,128,256,512,1024,2048,4096,8192,16384,32768]):
        for locality,pages in itertools.product(['compact','spread'],['base','thp','hugetlb']):
            add('tlb','chase',bytes=n*(64 if locality=='compact' else 4096),nodes=n,stride=64,locality=locality,pattern='random',pages=pages)
    for size,pat,kernel in itertools.product(sizes if not smoke else [65536,2*MIB],['sequential','random'],['multiply','axpy']):
        add('cache_kernel','kernel',bytes=size,element_stride=1,kernel=kernel,pattern=pat,pages='base')
    counts=sorted(set([0,1,2,3,4,5,7,9,len(cpus)-1]))
    if smoke:counts=[0,min(1,len(cpus)-1)]
    for n,r in itertools.product([n for n in counts if n<len(cpus)],[100,0,70,50] if not smoke else [100]):
        add('loaded','loaded',bytes=2*MIB if smoke else dram,probe_bytes=2*MIB if smoke else dram,load_cpus=','.join(map(str,cpus[1:1+n])),load_threads_requested=n,read_pct=r,pattern='sequential',pages='base')
    for label,size in [('misleading_cache_reuse',cap[1]//2),('correct_dram_footprint',dram)]:
        add('pitfall','stream',bytes=min(size,2*MIB) if smoke else size,stride=64,granularity=64,read_pct=100,pattern='sequential',pages='base',pitfall_case=label)
    return jobs,{'capacities_for_planning':cap,'dram_line_footprint_bytes':dram,'cache_source':'sysfs_with_documented_fallbacks','smoke_not_valid_for_report':smoke}

def peak_bytes(j):
    # Buffer + temporary permutation + conservative allocator margin.
    n=j.get('nodes',j['bytes']//j.get('stride',64))
    if j['mode']=='loaded':return int((j['bytes']*(j['load_threads_requested']+1))*1.3+64*MIB)
    if j['mode']=='kernel':return int(j['bytes']*1.5+64*MIB)
    return int(max(2*MIB,j['bytes'])+n*16+64*MIB)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile',choices=['smoke','full'],default='full');p.add_argument('--out',type=Path,required=True)
    p.add_argument('--trials',type=int,default=5);p.add_argument('--ms',type=int,default=250);p.add_argument('--seed',type=int,default=7530)
    p.add_argument('--cpu',type=int);p.add_argument('--cpus',help='ordered comma separated vCPUs; first is probe')
    p.add_argument('--dram-mib',type=int,help='override visited cache-line footprint; use at least 4 times LLC')
    p.add_argument('--experiments',help='comma separated subset');p.add_argument('--plan-only',action='store_true')
    a=p.parse_args()
    if a.trials<1 or a.ms<1 or (a.dram_mib is not None and a.dram_mib<1):p.error('positive trials, ms and dram-mib required')
    allowed=sorted(os.sched_getaffinity(0));cpus=cpu_order(allowed)
    if a.cpus:cpus=list(map(int,a.cpus.split(',')))
    if a.cpu is not None:cpus=[a.cpu]+[c for c in cpus if c!=a.cpu]
    if not cpus or len(cpus)!=len(set(cpus)) or any(c not in allowed for c in cpus):p.error('CPUs must be unique and within allowed affinity')
    out=a.out.resolve()
    if out.exists() and any(out.iterdir()):p.error('output directory must be empty; choose a new run name')
    out.mkdir(parents=True,exist_ok=True)
    caches=cache_info(cpus[0]);jobs,settings=plan(a.profile,caches,cpus,a.dram_mib)
    if a.experiments:jobs=[j for j in jobs if j['experiment'] in a.experiments.split(',')]
    if not jobs:p.error('no experiments selected')
    (out/'plan.json').write_text(json.dumps({'settings':settings,'jobs':jobs},indent=2))
    (out/'system_before.json').write_text(json.dumps(metadata(a,cpus,caches),indent=2,default=str))
    if a.plan_only:print(f'{len(jobs)} configurations; inspect {out}/plan.json');return
    binary=ROOT/'build/membench'
    if not binary.exists():raise SystemExit('Run make first')
    shutil.copy2(binary,out/'membench_used')
    rows=[];tasks=[(trial,j) for trial in range(a.trials) for j in jobs]
    random.Random(a.seed).shuffle(tasks) # Interleave repetitions to reduce drift.
    with (out/'raw.jsonl').open('w') as raw,(out/'commands.jsonl').open('w') as log:
        for k,(trial,j) in enumerate(tasks):
            row=dict(j,trial=trial,seed=a.seed+trial,cpu=cpus[0],ms=a.ms,profile=a.profile)
            # A paired seed within each repetition controls rings across pages/mixes.
            if peak_bytes(j)>memory_available()*0.65:
                row.update(status='skipped',error='estimated memory exceeds 65 percent of current available memory')
            else:
                excluded={'experiment','level_candidate','pitfall_case','load_threads_requested'}
                argv=[str(binary)]
                for key,val in row.items():
                    if key not in excluded|{'profile','trial'}:argv.extend(['--'+key,str(val)])
                start=time.time();result=command_benchmark(argv,max(120,a.ms/1000*30));result.update(trial=trial,experiment=j['experiment'],started_unix=start)
                log.write(json.dumps(result)+'\n');log.flush()
                try:
                    parsed=json.loads(result.get('stdout',''));row.update(parsed)
                    if result.get('returncode')!=0 and row.get('status')=='ok':row.update(status='error',error='nonzero process status')
                except (ValueError,TypeError):row.update(status='error',error=result.get('error',result.get('stderr','no JSON output')))
                if row.get('status')=='error' and j.get('pages')=='hugetlb' and 'hugetlb unavailable' in row.get('error',''):row['status']='unsupported'
            raw.write(json.dumps(row)+'\n');raw.flush();rows.append(row)
            print(f'[{k+1}/{len(tasks)}] {j["experiment"]} {row["status"]}',flush=True)
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with (out/'raw.csv').open('w',newline='') as f:w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
    (out/'system_after.json').write_text(json.dumps(metadata(a,cpus,caches),indent=2,default=str))
    print(f'Raw data saved in {out}. Run scripts/analyze.py next.')

def command_benchmark(argv,timeout):
    try:
        r=subprocess.run(argv,capture_output=True,text=True,timeout=timeout)
        return dict(argv=argv,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)
    except (OSError,subprocess.TimeoutExpired) as e:return dict(argv=argv,error=str(e))

if __name__=='__main__':main()
