#!/usr/bin/env python3
"""Summarize actual raw trials and make labeled plots; never fabricates data."""
import argparse, csv, json, math, statistics
from collections import defaultdict, Counter
from pathlib import Path
CONFIG=['experiment','mode','bytes','stride','granularity','read_pct','pattern','pages','locality','nodes','kernel','element_stride','load_cpus','load_threads_requested','level_candidate','pitfall_case','profile','cpu','ms']
EVENTS=['cycles','instructions','cache_references','cache_misses','l1d_read_misses','dtlb_read_misses']
METRICS=['latency_ns','ns_per_operation','useful_gbps','load_useful_gbps','cycles_per_operation','counted_cycles_per_elapsed_ns','instructions_per_operation','cache_misses_per_1000_operations','l1d_read_misses_per_1000_operations','dtlb_read_misses_per_1000_operations','cache_miss_fraction','cpi','load_tail_fraction']

def number(x):return isinstance(x,(float,int)) and math.isfinite(x)
def mean(xs):return statistics.mean(xs)
def derive(r):
    r=dict(r)
    # Suppress unreliable event normalization instead of turning missing PMU into 0.
    for ev in EVENTS:
        if r.get(ev+'_status')!='ok' or r.get(ev+'_running_fraction',0)<0.9:r.pop(ev+'_scaled',None)
    ops=r.get('operations',0)
    if number(r.get('cycles_scaled')) and r.get('elapsed_ns',0)>0:r['counted_cycles_per_elapsed_ns']=r['cycles_scaled']/r['elapsed_ns']
    if ops:
        for ev in ['cycles','instructions']:
            if number(r.get(ev+'_scaled')):r[ev+'_per_operation']=r[ev+'_scaled']/ops
        for ev in ['cache_misses','l1d_read_misses','dtlb_read_misses']:
            if number(r.get(ev+'_scaled')):r[ev+'_per_1000_operations']=1000*r[ev+'_scaled']/ops
    if r.get('cache_references_scaled',0)>0 and number(r.get('cache_misses_scaled')):r['cache_miss_fraction']=r['cache_misses_scaled']/r['cache_references_scaled']
    if r.get('instructions_scaled',0)>0 and number(r.get('cycles_scaled')):r['cpi']=r['cycles_scaled']/r['instructions_scaled']
    if r.get('load_tail_ns') is not None:r['load_tail_fraction']=r['load_tail_ns']/r['elapsed_ns']
    return r

def summarize(rows):
    groups=defaultdict(list)
    for r in rows:
        if r.get('status')=='ok':groups[tuple(r.get(k,'') for k in CONFIG)].append(derive(r))
    summary=[]
    for key,rs in groups.items():
        s=dict(zip(CONFIG,key));s['trials']=len(rs)
        for m in METRICS:
            v=[r[m] for r in rs if number(r.get(m))]
            if v:
                s.update({m+'_n':len(v),m+'_mean':mean(v),m+'_median':statistics.median(v),m+'_sd':statistics.stdev(v) if len(v)>1 else 0,m+'_min':min(v),m+'_max':max(v)})
        # Preserve observed page backing, not just the requested policy.
        s['page_status_observed']=';'.join(sorted({r.get('page_status','unverified') for r in rs}))
        s['anon_huge_kib_min']=min((r.get('anon_huge_kib',0) for r in rs),default=0)
        summary.append(s)
    return summary

def writecsv(p,rows):
    if not rows:p.write_text('');return
    fields=sorted(set().union(*(r.keys() for r in rows)))
    with p.open('w',newline='') as f:w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)

def knee_table(summary):
    result=[]
    mixes=sorted({r.get('read_pct') for r in summary if r['experiment']=='loaded'})
    for mix in mixes:
        rs=sorted([r for r in summary if r['experiment']=='loaded' and r['read_pct']==mix],key=lambda r:r['load_threads_requested'])
        positive=[r for r in rs if r['load_threads_requested']>0 and r.get('load_useful_gbps_mean',0)>0]
        if not positive:continue
        peak=max(r['load_useful_gbps_mean'] for r in positive)
        candidate=next(r for r in positive if r['load_useful_gbps_mean']>=0.9*peak)
        later=[r for r in positive if r['load_threads_requested']>candidate['load_threads_requested']]
        # Operational 90%-of-observed-peak marker, not proof of DRAM saturation.
        status='candidate_requires_visual_review' if later else 'no_plateau_demonstrated'
        for r in rs:
            b=r.get('load_useful_gbps_mean',0);l=r['latency_ns_mean']
            result.append({'read_pct':mix,'threads':r['load_threads_requested'],'bandwidth_useful_gbps':b,'probe_latency_ns':l,'candidate_threads':candidate['load_threads_requested'],'knee_status':status,'little_law_64B_proxy':b*l/64,'proxy_is_not_measured_queue_depth':True,'max_tail_fraction':r.get('load_tail_fraction_max',0),'low_repetition_count':r['trials']<3})
    return result

def plots(summary,out,caches):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.grid':True,'grid.alpha':0.25,'figure.dpi':140,'savefig.bbox':'tight'})
    out.mkdir(exist_ok=True)
    def save(fig,name):fig.tight_layout();fig.savefig(out/(name+'.png'));fig.savefig(out/(name+'.pdf'));plt.close(fig)
    def err(ax,rs,x,y,label=None,**kw):
        rs=[r for r in rs if y+'_mean' in r]
        if not rs:return
        ax.errorbar([r[x] for r in rs],[r[y+'_mean'] for r in rs],yerr=[r[y+'_sd'] for r in rs],marker='o',capsize=3,label=label,**kw)
    rs=sorted([r for r in summary if r['experiment']=='working_set'],key=lambda r:r['bytes'])
    if rs:
        fig,ax=plt.subplots(figsize=(8,4.5));err(ax,rs,'bytes','latency_ns');ax.set_xscale('log',base=2);ax.set_xlabel('Address span (bytes), one node per 64 B');ax.set_ylabel('Dependent read latency (ns/load)')
        for c in caches:
            if c.get('bytes') and c.get('type') in ['Data','Unified']:
                ax.axvline(c['bytes'],color='gray',ls='--',alpha=.5);ax.text(c['bytes'],ax.get_ylim()[1]*.85,'L'+c['level'],rotation=90)
        ax.set_title('Working set sweep | means ± sample SD');save(fig,'01_working_set')
    for exp,prefix in [('pattern_mix','02_pattern_mix')]:
        rs=[r for r in summary if r['experiment']==exp]
        if rs:
            fig,axes=plt.subplots(2,2,figsize=(11,8),sharex=True)
            for ax,mix in zip(axes.flat,[100,0,70,50]):
                for pat in ['sequential','random']:
                    for g in [8,64]:
                        rr=sorted([r for r in rs if r['read_pct']==mix and r['pattern']==pat and r['granularity']==g],key=lambda r:r['stride']);err(ax,rr,'stride','useful_gbps',f'{pat}, {g} B')
                ax.set_title(f'{mix}% read, {100-mix}% write');ax.set_xlabel('Stride (bytes)');ax.set_ylabel('Useful bandwidth (GB/s)');ax.legend(fontsize=8)
            save(fig,prefix)
    rs=[r for r in summary if r['experiment']=='pattern_latency']
    if rs:
        fig,ax=plt.subplots(figsize=(7,4))
        for p in ['sequential','random']:err(ax,sorted([r for r in rs if r['pattern']==p],key=lambda r:r['stride']),'stride','latency_ns',p)
        ax.set_xlabel('Node spacing (bytes)');ax.set_ylabel('Dependent read latency (ns/load)');ax.legend();save(fig,'03_pattern_latency')
    rs=[r for r in summary if r['experiment']=='loaded']
    if rs:
        fig,(ax,bx)=plt.subplots(1,2,figsize=(11,4.5))
        for mix in sorted({r['read_pct'] for r in rs}):
            rr=sorted([r for r in rs if r['read_pct']==mix],key=lambda r:r['load_threads_requested']);label=f'{mix}% read'
            ax.errorbar([r['load_useful_gbps_mean'] for r in rr],[r['latency_ns_mean'] for r in rr],xerr=[r['load_useful_gbps_sd'] for r in rr],yerr=[r['latency_ns_sd'] for r in rr],marker='o',capsize=3,label=label)
            for r in rr:ax.annotate(str(r['load_threads_requested']),(r['load_useful_gbps_mean'],r['latency_ns_mean']),fontsize=7)
            err(bx,rr,'load_threads_requested','load_useful_gbps',label)
            positive=[r for r in rr if r['load_threads_requested']>0 and r.get('load_useful_gbps_mean',0)>0]
            if positive:
                peak=max(r['load_useful_gbps_mean'] for r in positive);candidate=next(r for r in positive if r['load_useful_gbps_mean']>=.9*peak)
                ax.scatter([candidate['load_useful_gbps_mean']],[candidate['latency_ns_mean']],marker='D',s=45,facecolors='none',edgecolors='black',zorder=7)
                bx.scatter([candidate['load_threads_requested']],[candidate['load_useful_gbps_mean']],marker='D',s=45,facecolors='none',edgecolors='black',zorder=7)
        ax.set_xlabel('Load traffic useful bandwidth (GB/s)');ax.set_ylabel('Probe dependent read latency (ns/load)');ax.set_title('Thread counts labeled; diamonds mark 90% candidate');bx.set_xlabel('Background threads');bx.set_ylabel('Load traffic useful bandwidth (GB/s)');ax.legend();bx.legend();save(fig,'04_loaded_latency')
    rs=[r for r in summary if r['experiment']=='tlb']
    if rs:
        fig,axes=plt.subplots(1,2,figsize=(12,4.5))
        for ax,loc in zip(axes,['compact','spread']):
            for pages in ['base','thp','hugetlb']:
                rr=sorted([r for r in rs if r['locality']==loc and r['pages']==pages],key=lambda r:r['nodes'])
                observed=' / '.join(sorted({r['page_status_observed'] for r in rr}))
                err(ax,rr,'nodes','latency_ns',f'{pages}: {observed}')
            ax.set_xscale('log',base=2);ax.set_xlabel('Visited cache lines (spread uses one per 4 KiB page)');ax.set_ylabel('Dependent read latency (ns/load)');ax.set_title(loc);ax.legend(fontsize=7)
        save(fig,'05_page_locality')
    rs=[r for r in summary if r['experiment']=='cache_kernel']
    if rs:
        fig,axes=plt.subplots(1,2,figsize=(11,4.5))
        for ax,k in zip(axes,['multiply','axpy']):
            for pat in ['sequential','random']:err(ax,sorted([r for r in rs if r['kernel']==k and r['pattern']==pat],key=lambda r:r['bytes']),'bytes','ns_per_operation',pat)
            ax.set_xscale('log',base=2);ax.set_xlabel('Combined array footprint (bytes)');ax.set_ylabel('Time (ns/element)');ax.set_title(k);ax.legend()
        save(fig,'06_kernel_runtime')
        for event,name in [('cache_misses','07_cache_miss_correlation'),('dtlb_read_misses','08_tlb_miss_correlation')]:
            metric=event+'_per_1000_operations'
            rr=[r for r in rs if metric+'_mean' in r]
            if rr:
                fig,ax=plt.subplots(figsize=(7,4.5))
                for pat in ['sequential','random']:
                    rrr=[r for r in rr if r['pattern']==pat]
                    ax.errorbar([r[metric+'_mean'] for r in rrr],[r['ns_per_operation_mean'] for r in rrr],xerr=[r[metric+'_sd'] for r in rrr],yerr=[r['ns_per_operation_sd'] for r in rrr],fmt='o',capsize=3,label=pat)
                ax.set_xlabel(event+' per 1000 element updates');ax.set_ylabel('Time (ns/element)');ax.legend();save(fig,name)
    rs=[r for r in summary if r['experiment']=='tlb' and 'dtlb_read_misses_per_1000_operations_mean' in r]
    if rs:
        fig,ax=plt.subplots(figsize=(7,4.5))
        for loc in ['compact','spread']:
            rr=sorted([r for r in rs if r['locality']==loc and r['pages']=='base'],key=lambda r:r['nodes']);err(ax,rr,'nodes','dtlb_read_misses_per_1000_operations',loc)
        ax.set_xscale('log',base=2);ax.set_xlabel('Visited cache lines');ax.set_ylabel('DTLB read misses per 1000 loads');ax.legend();save(fig,'09_tlb_counter_impact')
    rs=[r for r in summary if r['experiment']=='pitfall']
    if rs:
        fig,ax=plt.subplots(figsize=(7,4));ax.bar([r['pitfall_case'].replace('_','\n') for r in rs],[r['useful_gbps_mean'] for r in rs],yerr=[r['useful_gbps_sd'] for r in rs],capsize=4);ax.set_ylabel('Useful bandwidth (GB/s)');ax.set_title('Cache reuse pitfall with identical access code');save(fig,'10_pitfall')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--no-plots',action='store_true');a=p.parse_args();out=a.run/'processed';out.mkdir(exist_ok=True)
    rows=[json.loads(x) for x in (a.run/'raw.jsonl').read_text().splitlines() if x.strip()];s=summarize(rows)
    writecsv(out/'summary.csv',s);writecsv(out/'knee_candidates.csv',knee_table(s));writecsv(out/'baseline_table.csv',[r for r in s if r['experiment']=='baseline'])
    faults=[r for r in rows if r.get('major_faults',0)>0 or r.get('minor_faults',0)>0]
    available=Counter((ev,r.get(ev+'_status','not_collected')) for r in rows for ev in EVENTS)
    audit={'status_counts':dict(Counter(r.get('status') for r in rows)),'counter_status_counts':{ev:dict((status,n) for (e,status),n in available.items() if e==ev) for ev in EVENTS},'page_status_counts':dict(Counter(r.get('page_status','not_recorded') for r in rows)),'trials_with_faults':len(faults),'single_trial_groups':sum(r['trials']<2 for r in s),'smoke_data_present':any(r.get('profile')=='smoke' for r in rows),'notes':['Error bars are sample standard deviation, not confidence intervals.','Missing counters stay missing; event running fraction below 0.9 is excluded from normalization.','Review failure/skip counts and observed page backing before interpreting results.','No PMU counter plots are produced when valid PMU events are unavailable.']}
    (out/'audit.json').write_text(json.dumps(audit,indent=2))
    if not a.no_plots:
        try:plots(s,out/'plots',json.loads((a.run/'system_before.json').read_text()).get('cache_info',[]))
        except ImportError as e:raise SystemExit(f'{e}. Install requirements.txt in your virtual environment, then rerun analysis. Raw data is intact.')
    print(f'{len(s)} groups processed. See {out}')
if __name__=='__main__':main()
