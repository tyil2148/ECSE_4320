#!/usr/bin/env python3
"""Generate assignment figures from processed measurements only."""
import argparse, csv, json, pathlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from environment import cache_bytes
COLORS={'scalar':'#7e8792','generic':'#008c95','scalar_native':'#b58538','native':'#184e9c'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('results',type=pathlib.Path);a=p.parse_args()
    with (a.results/'summary.csv').open() as f:rows=list(csv.DictReader(f))
    for r in rows:
        for k in ('n','stride','shift','working_set_bytes'):r[k]=int(r[k])
        for k in ('speedup','speedup_ci_low','speedup_ci_high','median_seconds','q1_seconds','q3_seconds','gflops','useful_gbps','modeled_traffic_gbps','ns_per_element','tsc_ticks_per_element','core_cycles_per_element'):
            r[k]=float(r[k]) if r[k] else None
    env=json.loads((a.results/'environment.json').read_text());analysis=json.loads((a.results/'analysis.json').read_text())
    out=a.results/'figures';out.mkdir(exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':.22,'figure.dpi':120})
    def save(fig,name):
        fig.tight_layout();fig.savefig(out/f'{name}.png',dpi=180,bbox_inches='tight');fig.savefig(out/f'{name}.pdf',bbox_inches='tight');plt.close(fig)
    def select(study,**kw):return [r for r in rows if r['study']==study and all(r[k]==v for k,v in kw.items())]
    def cache_lines(ax):
        used=set()
        for c in env['caches']:
            b=cache_bytes(c.get('size'));level=c.get('level')
            if b and c.get('type') in ('Data','Unified') and b not in used and ax.get_xlim()[0] <= b/1024 <= ax.get_xlim()[1]:
                used.add(b);ax.axvline(b/1024,color='#777777',ls=':',lw=.7)
                ax.text(b/1024,.96,f'L{level}',transform=ax.get_xaxis_transform(),rotation=90,va='top',fontsize=8)
    kernels=('saxpy','dot','mul','stencil')
    for metric,label,name in [('speedup','Speedup versus matched scalar','01_speedup'),('useful_gbps','Effective useful bandwidth (GB/s)','02_throughput')]:
        fig,axs=plt.subplots(2,2,figsize=(12,8))
        for ax,kernel in zip(axs.flat,kernels):
            variants=('generic','native') if metric=='speedup' else ('scalar','generic','scalar_native','native')
            for variant in variants:
                for dtype,style in [('f32','-'),('f64','--')]:
                    data=sorted(select('locality',kernel=kernel,variant=variant,dtype=dtype),key=lambda r:r['working_set_bytes'])
                    x=[r['working_set_bytes']/1024 for r in data];y=[r[metric] for r in data]
                    if metric=='speedup':
                        # Bootstrap percentile intervals need not contain the
                        # observed statistic. Draw intervals directly, not as a
                        # possibly negative Matplotlib yerr.
                        ax.plot(x,y,style+'o',ms=3,color=COLORS[variant],label=f'{variant} {dtype}')
                        ax.vlines(x,[r['speedup_ci_low'] for r in data],[r['speedup_ci_high'] for r in data],color=COLORS[variant],alpha=.45)
                    else:
                        ax.plot(x,y,style+'o',ms=3,color=COLORS[variant],label=f'{variant} {dtype}')
                        lower=[r[metric]*r['median_seconds']/r['q3_seconds'] for r in data]
                        upper=[r[metric]*r['median_seconds']/r['q1_seconds'] for r in data]
                        ax.fill_between(x,lower,upper,color=COLORS[variant],alpha=.08)
            cache_lines(ax);ax.set_xscale('log',base=2);ax.set_title(kernel.upper());ax.set_xlabel('Active padded working set (KiB)');ax.set_ylabel(label)
            if metric=='speedup':ax.axhline(1,color='black',lw=.7)
        axs.flat[0].legend(fontsize=8,ncol=2)
        fig.suptitle('SIMD across cache levels | 95% bootstrap speedup intervals' if metric=='speedup' else 'Throughput across cache levels | bands show sample IQR',y=1.02)
        save(fig,name)
    for study,name,xkey,xlabel in [('alignment','03_alignment','shift','Start shift (elements)'),('tail','04_tail','n','Remainder relative to base N (elements)')]:
        fig,axs=plt.subplots(1,2,figsize=(12,4.5))
        for ax,dtype in zip(axs,('f32','f64')):
            for variant in ('generic','native'):
                data=select(study,dtype=dtype,variant=variant)
                bases=sorted(set((r['n'] if study=='alignment' else r['n']//16*16) for r in data))
                for idx,base in enumerate(bases):
                    subset=sorted([r for r in data if (r['n'] if study=='alignment' else r['n']//16*16)==base],key=lambda r:r[xkey])
                    if not subset:continue
                    x=[r[xkey] if study=='alignment' else r['n']-base for r in subset];y=[r['ns_per_element'] for r in subset]
                    ax.plot(x,y,marker='o',ms=3,ls=['-','--',':','-.'][idx%4],color=COLORS[variant],label=f'{variant} base N={base}')
                    ax.vlines(x,[r['q1_seconds']*1e9/r['n'] for r in subset],[r['q3_seconds']*1e9/r['n'] for r in subset],color=COLORS[variant],alpha=.4)
            ax.set_title(f'Multiply {dtype}');ax.set_xlabel(xlabel);ax.set_ylabel('Runtime (ns/output)');ax.legend(fontsize=7,ncol=2)
        fig.suptitle('Alignment cost | sample IQR' if study=='alignment' else 'Tail handling | sample IQR',y=1.02);save(fig,name)
    fig,axs=plt.subplots(2,2,figsize=(12,8))
    for row,study in enumerate(('stride_fixed_n','stride_fixed_footprint')):
        for col,dtype in enumerate(('f32','f64')):
            ax=axs[row,col];data=select(study,dtype=dtype)
            def group(r):return r['n'] if study=='stride_fixed_n' else r['n']*r['stride']
            bases=sorted(set(group(r) for r in data))
            for variant in ('generic','native'):
                for idx,base in enumerate(bases):
                    sub=sorted([r for r in data if r['variant']==variant and group(r)==base],key=lambda r:r['stride'])
                    ax.plot([r['stride'] for r in sub],[r['useful_gbps'] for r in sub],marker='o',ls=['-','--',':'][idx%3],color=COLORS[variant],label=f'{variant}, N×stride={base}' if study!='stride_fixed_n' else f'{variant}, N={base}')
                    ax.vlines([r['stride'] for r in sub],[r['useful_gbps']*r['median_seconds']/r['q3_seconds'] for r in sub],[r['useful_gbps']*r['median_seconds']/r['q1_seconds'] for r in sub],color=COLORS[variant],alpha=.4)
            ax.set_title(f'{study.replace("_"," ")} {dtype}');ax.set_xlabel('Stride (elements)');ax.set_xticks([1,2,4,8]);ax.set_ylabel('Useful bandwidth (GB/s)');ax.legend(fontsize=7)
    fig.suptitle('Stride costs with capacity controlled separately',y=1.02);save(fig,'05_stride')
    fig,axs=plt.subplots(1,2,figsize=(12,4.5))
    for ax,dtype in zip(axs,('f32','f64')):
        for kernel in kernels:
            data=sorted(select('locality',variant='native',dtype=dtype,kernel=kernel),key=lambda r:r['working_set_bytes'])
            ax.plot([r['working_set_bytes']/1024 for r in data],[r['gflops'] for r in data],'-o',ms=3,label=kernel)
            ax.fill_between([r['working_set_bytes']/1024 for r in data],[r['gflops']*r['median_seconds']/r['q3_seconds'] for r in data],[r['gflops']*r['median_seconds']/r['q1_seconds'] for r in data],alpha=.1)
        cache_lines(ax);ax.set_xscale('log',base=2);ax.set_title(dtype);ax.set_xlabel('Active working set (KiB)');ax.set_ylabel('GFLOP/s');ax.legend()
    fig.suptitle('Data type comparison at matched working-set budgets',y=1.02);save(fig,'06_dtype')
    fig,axs=plt.subplots(1,2,figsize=(12,4.5))
    for ax,dtype in zip(axs,('f32','f64')):
        cal=analysis['bandwidth_calibration'].get(dtype,{})
        peakmodel=analysis['peak_model'];peak=peakmodel['assumed_ghz']*peakmodel['fma_units']*peakmodel['vector_bits']/(32 if dtype=='f32' else 64)*2
        x=np.logspace(-3,2,200)
        if cal.get('qualified_dram'):
            ax.loglog(x,np.minimum(peak,cal['modeled_gbps']*x),color='black',label='Estimated single-core DRAM roof')
            with (a.results/'roofline.csv').open() as f:rr=list(csv.DictReader(f))
            for r in rr:
                if r['dtype']==dtype and r['qualified_dram']=='True':ax.scatter(float(r['intensity']),float(r['measured_gflops']),label=f'{r["kernel"]} N={r["n"]}',s=35)
        else:ax.text(.5,.5,'DRAM roof not qualified\nConfirm LLC and bandwidth footprint',transform=ax.transAxes,ha='center')
        ax.set_xscale('log');ax.set_yscale('log');ax.set_title(dtype);ax.set_xlabel('Modeled DRAM arithmetic intensity (FLOP/byte)');ax.set_ylabel('GFLOP/s')
        if cal.get('qualified_dram'):ax.legend(fontsize=8)
    fig.suptitle(f'Roofline | assumed clock {analysis["peak_model"]["assumed_ghz"]} GHz; traffic modeled',y=1.02);save(fig,'07_roofline')
    fig,axs=plt.subplots(1,2,figsize=(12,4.5))
    for ax,dtype in zip(axs,('f32','f64')):
        for variant in ('generic','native'):
            data=sorted(select('negative',variant=variant,dtype=dtype),key=lambda r:r['n'])
            x=[r['n'] for r in data]
            ax.plot(x,[r['speedup'] for r in data],'-o',color=COLORS[variant],label=variant)
            ax.vlines(x,[r['speedup_ci_low'] for r in data],[r['speedup_ci_high'] for r in data],color=COLORS[variant],alpha=.5)
        ax.axhline(1,color='black',lw=.7);ax.set_xscale('log');ax.set_title(f'Strict ordered dot {dtype}');ax.set_xlabel('N');ax.set_ylabel('Speedup versus matched scalar');ax.legend()
    fig.suptitle('Negative example candidate | verify the reduction in disassembly',y=1.02);save(fig,'08_negative')
    fig,axs=plt.subplots(1,2,figsize=(12,4.5));has_core=all(r['core_cycles_per_element'] is not None for r in rows)
    metric='core_cycles_per_element' if has_core else 'tsc_ticks_per_element'
    for ax,dtype in zip(axs,('f32','f64')):
        for variant in ('scalar_native','native'):
            data=sorted(select('locality',kernel='mul',variant=variant,dtype=dtype),key=lambda r:r['working_set_bytes'])
            ax.plot([r['working_set_bytes']/1024 for r in data],[r[metric] for r in data],'-o',color=COLORS[variant],label=variant)
        cache_lines(ax);ax.set_xscale('log',base=2);ax.set_title(dtype);ax.set_xlabel('Active working set (KiB)');ax.set_ylabel('Core cycles/output' if has_core else 'TSC reference ticks/output');ax.legend()
    fig.suptitle('Hardware cycles per element' if has_core else 'TSC ticks per element | PMU cycles unavailable, not core cycles',y=1.02);save(fig,'09_cycles')
    print(f'Wrote nine PNG/PDF figures to {out}')
if __name__=='__main__':main()
