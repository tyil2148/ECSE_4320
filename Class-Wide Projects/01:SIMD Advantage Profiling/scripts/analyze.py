#!/usr/bin/env python3
"""Summarize real raw samples, uncertainty, traffic models and a DRAM roofline."""
import argparse, collections, csv, json, math, pathlib, random, statistics
from environment import cache_bytes
KEYS=['study','variant','kernel','dtype','n','stride','shift','pattern']

def quantile(values,q):
    values=sorted(values);pos=(len(values)-1)*q;lo=int(pos);hi=min(lo+1,len(values)-1)
    return values[lo]+(values[hi]-values[lo])*(pos-lo)

def traffic(kernel,n,stride,element):
    arrays=3 if kernel=='mul' else 2
    halo=2 if kernel=='stencil' else 0
    footprint=(arrays*((n-1)*stride+1)+halo*stride)*element
    flops={'saxpy':2,'dot':2,'mul':1,'stencil':5,'strictdot':2,'bandwidth':1}[kernel]*n
    useful={'saxpy':3,'dot':2,'mul':3,'stencil':4,'strictdot':2,'bandwidth':2}[kernel]*n*element
    # One line allocation serves several unit-stride elements. At stride >=
    # line_size/element, each element can consume a full 64-byte cache line.
    delivered=min(64,stride*element)
    streams={'saxpy':3,'dot':2,'mul':4,'stencil':3,'strictdot':2,'bandwidth':3}[kernel]
    model=streams*n*delivered
    if kernel=='stencil':model+=2*delivered
    return footprint,flops,useful,model

def bootstrap_ratio(base,optimized,rng,reps=2000):
    values=[]
    for _ in range(reps):
        b=statistics.median(rng.choices(base,k=len(base)))
        o=statistics.median(rng.choices(optimized,k=len(optimized)))
        values.append(b/o)
    return quantile(values,.025),quantile(values,.975)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('results',type=pathlib.Path)
    p.add_argument('--peak-ghz',type=float,default=2.0,help='assumed core clock, NOT measured; vary for sensitivity')
    p.add_argument('--vector-bits',type=int,choices=[128,256,512],default=256)
    p.add_argument('--fma-units',type=float,default=2.0,help='explicit hardware model assumption')
    p.add_argument('--seed',type=int,default=7530)
    a=p.parse_args()
    if not math.isfinite(a.peak_ghz) or not math.isfinite(a.fma_units) or a.peak_ghz<=0 or a.fma_units<=0:p.error('peak parameters must be finite and positive')
    out=a.results
    env=json.loads((out/'environment.json').read_text())
    manifest=json.loads((out/'manifest.json').read_text())
    if not manifest.get('complete'):p.error('run incomplete; do not silently analyze partial measurements')
    groups=collections.defaultdict(list)
    with (out/'raw.csv').open() as f:
        for r in csv.DictReader(f):groups[tuple(r[k] for k in KEYS)].append(r)
    summaries=[];times={};rng=random.Random(a.seed)
    for key,rows in sorted(groups.items()):
        r=dict(zip(KEYS,key));n=int(r['n']);stride=int(r['stride']);element=4 if r['dtype']=='f32' else 8
        secs=[float(x['seconds'])/int(x['iterations']) for x in rows]
        if any(t<=0 or not math.isfinite(t) for t in secs):raise ValueError('invalid elapsed time')
        times[key]=secs
        median=statistics.median(secs)
        footprint,flops,useful,model=traffic(r['kernel'],n,stride,element)
        cpes=[float(x['core_cycles'])/(int(x['iterations'])*n) for x in rows if x['core_cycles']]
        tc=[float(x['tsc_ticks'])/(int(x['iterations'])*n) for x in rows]
        mean=statistics.mean(secs)
        r.update(samples=len(secs),working_set_bytes=footprint,median_seconds=median,q1_seconds=quantile(secs,.25),q3_seconds=quantile(secs,.75),
                 sd_seconds=statistics.stdev(secs) if len(secs)>1 else 0,cv=statistics.stdev(secs)/mean if len(secs)>1 else 0,
                 ns_per_element=median*1e9/n,gflops=flops/median/1e9,useful_gbps=useful/median/1e9,
                 modeled_traffic_gbps=model/median/1e9,flops=flops,useful_bytes=useful,modeled_traffic_bytes=model,
                 intensity_flops_per_byte=flops/model,core_cycles_per_element=statistics.median(cpes) if len(cpes)==len(rows) else '',
                 tsc_ticks_per_element=statistics.median(tc),validation_max_abs_error=max(float(x['validation_max_abs_error']) for x in rows),
                 validation_bound=max(float(x['validation_bound']) for x in rows),speedup='',speedup_ci_low='',speedup_ci_high='',matched_baseline='')
        if r['variant'] in ('generic','native'):
            baseline='scalar' if r['variant']=='generic' else 'scalar_native'
            basekey=list(key);basekey[1]=baseline;basekey=tuple(basekey)
            if basekey not in groups:raise ValueError('missing matched scalar baseline')
            bs=[float(x['seconds'])/int(x['iterations']) for x in groups[basekey]]
            lo,hi=bootstrap_ratio(bs,secs,rng)
            r.update(speedup=statistics.median(bs)/median,speedup_ci_low=lo,speedup_ci_high=hi,matched_baseline=baseline)
        summaries.append(r)
    with (out/'summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(summaries[0]));writer.writeheader();writer.writerows(summaries)
    llc=env.get('llc_bytes_used')
    roofs=[];calibration={}
    for dtype in ('f32','f64'):
        candidates=[r for r in summaries if r['study']=='bandwidth' and r['variant']=='native' and r['dtype']==dtype]
        if not candidates:continue
        cal=max(candidates,key=lambda x:x['working_set_bytes'])
        valid=llc is not None and cal['working_set_bytes']>=4*llc
        calibration[dtype]=dict(working_set_bytes=cal['working_set_bytes'],llc_bytes=llc,
            qualified_dram=valid,modeled_gbps=cal['modeled_traffic_gbps'],useful_gbps=cal['useful_gbps'])
        peak=a.peak_ghz*a.fma_units*(a.vector_bits//(32 if dtype=='f32' else 64))*2
        for r in summaries:
            if r['study']!='locality' or r['variant']!='native' or r['dtype']!=dtype:continue
            is_dram=llc is not None and r['working_set_bytes']>=4*llc
            bound=min(peak,cal['modeled_traffic_gbps']*r['intensity_flops_per_byte'])
            roofs.append(dict(kernel=r['kernel'],dtype=dtype,n=r['n'],working_set_bytes=r['working_set_bytes'],
                intensity=r['intensity_flops_per_byte'],measured_gflops=r['gflops'],assumed_peak_gflops=peak,
                bandwidth_model_gbps=cal['modeled_traffic_gbps'],roofline_bound_gflops=bound,
                fraction_of_bound=r['gflops']/bound,qualified_dram=valid and is_dram,
                interpretation='DRAM model' if valid and is_dram else 'cache resident or unqualified; do not compare against a DRAM roof'))
    if roofs:
        with (out/'roofline.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(roofs[0]));w.writeheader();w.writerows(roofs)
    analysis=dict(peak_model=dict(assumed_ghz=a.peak_ghz,vector_bits=a.vector_bits,fma_units=a.fma_units,
        note='Single-core FMA hardware ceiling assumption; kernels disable contraction. Clock is not a measurement.'),
        bandwidth_calibration=calibration,traffic_model='64-byte cache lines; temporal stores; write-allocate plus writeback; no measured DRAM bytes',
        uncertainty='Unpaired bootstrap interval of median ratio, 2000 resamples, 95%; block sampling can understate host drift.',
        counter_note='core_cycles_per_element is blank when PMU unavailable; TSC ticks are reference-clock ticks, not core cycles.',
        warnings=(["Cache metadata absent: supply --llc-mib to qualify DRAM observations"] if llc is None else [])+
        [f'{d}: bandwidth footprint below 4x LLC; DRAM roof not qualified' for d,c in calibration.items() if not c['qualified_dram']])
    (out/'analysis.json').write_text(json.dumps(analysis,indent=2)+'\n')
    (out/'report_values.md').write_text('# Values to transfer into the report\n\nUse summary.csv, roofline.csv and figures. Complete every [ADD ...] marker in report/report.md.\n\n'+
        '\n'.join('- '+x for x in analysis['warnings'])+'\n\nBandwidth calibration and peak assumptions:\n\n```json\n'+json.dumps(analysis,indent=2)+'\n```\n')
    print(f'Processed {len(summaries)} configurations; {len(roofs)} roofline rows. Raw samples retained.')
if __name__=='__main__':main()
