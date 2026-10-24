from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from pathlib import Path


def read_rows(path):
    with Path(path).open(newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for k, value in list(row.items()):
            try:
                row[k] = float(value)
            except (ValueError, TypeError):
                pass
    return rows


def plot(directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    import numpy as np

    out = Path(directory)
    rows = read_rows(out / "analysis" / "summary.csv")
    rows = [r for r in rows if r["direction"] == "total"]
    figs = out / "plots"
    figs.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size":9, "axes.spines.top":False, "axes.spines.right":False,
                         "savefig.dpi":180, "figure.constrained_layout.use":True})
    saved = []

    def save(fig, stem):
        # Render complete bytes before replacing an existing figure, so readers
        # cannot observe a partially written image during regeneration.
        for extension in ("png","pdf"):
            buffer=io.BytesIO()
            fig.savefig(buffer,format=extension)
            payload=buffer.getvalue()
            if extension=="png":
                from PIL import Image
                Image.open(io.BytesIO(payload)).verify()
            final=figs/(stem+"."+extension)
            temporary=final.with_suffix(final.suffix+".tmp")
            temporary.write_bytes(payload)
            temporary.replace(final)
        plt.close(fig)
        saved.append(stem)

    def select(family, **kw):
        return [r for r in rows if r["family"] == family and all(r[k] == v for k,v in kw.items())]

    def errors(data, metric):
        # One trial has no empirical between-trial error bar.
        return [r[metric+"_sd"] if r["n"]>1 else 0. for r in data]

    def line(ax, data, x, y, label, scale_x=1, **kwargs):
        data = sorted(data, key=lambda r:r[x])
        if not data:
            return
        ax.errorbar([r[x]/scale_x for r in data], [r[y+"_mean"] for r in data],
                    yerr=errors(data,y), marker="o", capsize=2, label=label, **kwargs)

    def finish(ax, xlabel, ylabel, logx=False, logy=False):
        ax.set(xlabel=xlabel, ylabel=ylabel)
        if logx:
            ax.set_xscale("log", base=2)
            ax.xaxis.set_major_formatter(ScalarFormatter())
        if logy:
            ax.set_yscale("log")
        ax.grid(alpha=.22)

    note = "Points show trial means; error bars show between-trial sample SD (n >= 2)."
    data = select("baseline")
    if data:
        labels = [f"{r['pattern']}\n{int(r['bs']/1024)} KiB\n{'read' if r['read_pct']==100 else 'write'}" for r in data]
        fig, axs = plt.subplots(1,2,figsize=(10,4))
        x = np.arange(len(data))
        axs[0].bar(x,[r["mean_lat_us_mean"] for r in data],yerr=errors(data,"mean_lat_us"),capsize=3)
        for k,m in enumerate(("p50_us","p95_us","p99_us","p999_us")):
            axs[1].bar(x+(k-1.5)*.19,[r[m+"_mean"] for r in data],width=.19,yerr=errors(data,m),capsize=2,label=m.split("_")[0].replace("999","99.9"))
        for ax in axs:
            ax.set_xticks(x,labels)
            finish(ax,"QD 1, one worker, direct=1","Latency (us)",logy=True)
        axs[0].set_title("Mean total latency")
        axs[1].set_title("Completion latency percentiles")
        axs[1].legend()
        fig.suptitle("QD 1 baselines   |   "+note,fontsize=10)
        save(fig,"01_baseline")
    if select("block"):
        fig, axs=plt.subplots(2,2,figsize=(10,7))
        fig2, ax2=plt.subplots(figsize=(7,4))
        for j,pattern in enumerate(("random","sequential")):
            for read in (100,0):
                d=select("block",pattern=pattern,read_pct=read)
                label="Read" if read==100 else "Write"
                line(axs[0,j],d,"bs","mib_s",label,scale_x=1024)
                line(axs[1,j],d,"bs","mean_lat_us",label,scale_x=1024)
                line(ax2,d,"bs","iops",pattern+" "+label.lower(),scale_x=1024)
            axs[0,j].set_title(pattern+"   |   QD 16, one worker, direct=1")
            finish(axs[0,j],"Block size (KiB)","Throughput (MiB/s)",logx=True)
            finish(axs[1,j],"Block size (KiB)","Mean total latency (us)",logx=True)
            axs[0,j].legend()
        fig.suptitle("Block size sweep   |   "+note,fontsize=10)
        save(fig,"02_blocksize")
        finish(ax2,"Block size (KiB)","IOPS (requests/s)",logx=True)
        ax2.set_title("Block size and IOPS   |   QD 16, one worker, direct=1")
        ax2.legend(); save(fig2,"03_block_iops")
    if select("mix"):
        fig,axs=plt.subplots(1,2,figsize=(10,4))
        for pattern in ("random","sequential"):
            d=select("mix",pattern=pattern)
            label="Random 4 KiB" if pattern=="random" else "Sequential 128 KiB"
            line(axs[0],d,"read_pct","mib_s",label)
            line(axs[1],d,"read_pct","mean_lat_us",label)
        for ax,y in zip(axs,("Total throughput (MiB/s)","Mean total latency (us)")):
            finish(ax,"Requested read fraction (%)",y); ax.set_xticks((0,50,70,100)); ax.legend()
        fig.suptitle("Read and write mix   |   QD 16, one worker, direct=1\n"+note,fontsize=10)
        save(fig,"04_mix")
    if select("queue"):
        knee_rows=read_rows(out/"analysis"/"knees.csv")
        star_label_used=False
        fig,ax=plt.subplots(figsize=(8,5))
        fig2,axs=plt.subplots(1,2,figsize=(10,4))
        for pattern in ("random","sequential"):
            for read in (100,0):
                d=sorted(select("queue",pattern=pattern,read_pct=read),key=lambda r:r["iodepth"])
                if not d:
                    continue
                label=f"{pattern} {'4' if pattern=='random' else '128'} KiB {'read' if read==100 else 'write'}"
                series=ax.errorbar([r["mean_lat_us_mean"] for r in d],[r["mib_s_mean"] for r in d],
                            xerr=errors(d,"mean_lat_us"),yerr=errors(d,"mib_s"),marker="o",capsize=2,label=label)
                color=series.lines[0].get_color()
                for index,r in enumerate(d):
                    ax.annotate(str(int(r["iodepth"])),(r["mean_lat_us_mean"],r["mib_s_mean"]),xytext=(4,5 if (index+(read==100))%2 else -12),textcoords="offset points",fontsize=7,color=color)
                knee=next((k for k in knee_rows if k["pattern"]==pattern and k["read_pct"]==read and k["plateau_observed"]=="True"),None)
                if knee:
                    candidate=next(r for r in d if r["iodepth"]==knee["selected_qd"])
                    ax.scatter([candidate["mean_lat_us_mean"]],[candidate["mib_s_mean"]],marker="*",s=150,color=color,edgecolors="black",linewidths=.6,zorder=6,label="Candidate knee" if not star_label_used else None)
                    star_label_used=True
                line(axs[0],d,"iodepth","iops",label)
                line(axs[1],d,"iodepth","mean_lat_us",label)
        ax.set_xscale("log")
        finish(ax,"Mean total latency (us, log scale)","Throughput (MiB/s)")
        ax.legend(fontsize=8); ax.set_title("Throughput and latency from the same runs\nQD labels; one worker, direct=1; stars mark supported knee candidates")
        save(fig,"05_queue_tradeoff")
        finish(axs[0],"Configured QD (one worker)","IOPS (requests/s)",logx=True)
        finish(axs[1],"Configured QD (one worker)","Mean total latency (us)",logx=True,logy=True)
        axs[0].legend(fontsize=7)
        fig2.suptitle("Queue depth sweep   |   "+note,fontsize=10)
        save(fig2,"06_queue_scaling")
        fig3,ax3=plt.subplots(figsize=(7,4))
        for pattern in ("random","sequential"):
            for read in (100,0):
                d=select("queue",pattern=pattern,read_pct=read)
                line(ax3,d,"total_qd","little_l_clat",f"{pattern} {'R' if read==100 else 'W'}")
        d=sorted({r["total_qd"] for r in select("queue")})
        ax3.plot(d,d,"k--",label="Configured QD reference")
        finish(ax3,"Configured aggregate QD","L = IOPS x mean completion latency (requests)",logx=True,logy=True)
        ax3.legend(fontsize=8); ax3.set_title("Little's Law estimate at fio's submitted-I/O boundary\nVirtual storage path; configured QD is not physical hardware occupancy")
        save(fig3,"07_little_law")
    if select("parallel"):
        fig,axs=plt.subplots(1,2,figsize=(10,4))
        for read,ax in zip((100,0),axs):
            d=select("parallel",read_pct=read)
            for total in sorted({r["total_qd"] for r in d}):
                line(ax,[r for r in d if r["total_qd"]==total],"numjobs","iops",f"Aggregate QD {int(total)}")
            finish(ax,"Workers (numjobs)","IOPS (requests/s)")
            ax.set_xticks((1,2,4,8)); ax.set_title("Random 4 KiB "+("read" if read==100 else "write")); ax.legend()
        fig.suptitle("Worker count at fixed aggregate QD and fixed total address range\n"+note,fontsize=10)
        save(fig,"08_parallel")
    if select("tail"):
        fig,axs=plt.subplots(2,2,figsize=(10,7))
        for pattern,axes in zip(("random","sequential"),axs):
            for read,ax in zip((100,0),axes):
                d=select("tail",pattern=pattern,read_pct=read)
                x=np.arange(4)
                for index,r in enumerate(d):
                    values=[r[k+"_mean"] for k in ("p50_us","p95_us","p99_us","p999_us")]
                    err=[r[k+"_sd"] if r["n"]>1 else 0. for k in ("p50_us","p95_us","p99_us","p999_us")]
                    ax.bar(x+(index-(len(d)-1)/2)*.35,values,width=.35,yerr=err,capsize=2,label=f"{r['role']} QD {int(r['iodepth'])}")
                ax.set_xticks(x,("p50","p95","p99","p99.9"))
                finish(ax,"Percentile","Completion latency (us)",logy=True)
                ax.set_title(pattern+" "+("read" if read==100 else "write")); ax.legend(fontsize=7)
        fig.suptitle("Tail latency at adaptively selected depths\nMean per-trial percentiles with sample SD; inspect N in tail_table.md",fontsize=10)
        save(fig,"09_tails")
        h=read_rows(out/"analysis"/"histograms.csv")
        fig,axs=plt.subplots(2,2,figsize=(10,7))
        for pattern,axes in zip(("random","sequential"),axs):
            for read,ax in zip((100,0),axes):
                for r in select("tail",pattern=pattern,read_pct=read):
                    bins=defaultdict(int)
                    for v in h:
                        if v["case_id"]==r["case_id"] and v["direction"]=="total":
                            bins[v["clat_us"]]+=int(v["count"])
                    total=sum(bins.values()); cumulative=0; xs=[]; ys=[]
                    for value,count in sorted(bins.items()):
                        cumulative+=count
                        if cumulative<total:
                            xs.append(value); ys.append(1-cumulative/total)
                    if xs:
                        ax.step(xs,ys,where="post",label=f"{r['role']} QD {int(r['iodepth'])}")
                ax.set_xscale("log"); ax.set_yscale("log")
                finish(ax,"Completion latency (us)","Fraction above latency")
                ax.set_title(pattern+" "+("read" if read==100 else "write")); ax.legend(fontsize=7)
        fig.suptitle("Pooled histogram survival curves across trials\nHistogram bin midpoints; excludes no observations and is not a per-trial percentile average",fontsize=10)
        save(fig,"10_tail_survival")
    if select("working_set"):
        fig,axs=plt.subplots(1,2,figsize=(10,4))
        for read in (100,0):
            d=select("working_set",read_pct=read)
            label="Read" if read==100 else "Write"
            line(axs[0],d,"working_set","iops",label,scale_x=1024**3)
            line(axs[1],d,"working_set","p99_us",label,scale_x=1024**3)
        finish(axs[0],"Address range (GiB)","IOPS (requests/s)")
        finish(axs[1],"Address range (GiB)","p99 completion latency (us)")
        axs[0].legend(); axs[1].legend()
        fig.suptitle("Working set sweep   |   Random 4 KiB, QD 16, one worker, direct=1\n"+note,fontsize=10)
        save(fig,"11_working_set")
    if select("state"):
        ts=read_rows(out/"analysis"/"timeseries.csv")
        fig,axs=plt.subplots(2,1,figsize=(9,6))
        for metric,ax,ylabel in zip(("mib_s","mean_clat_us"),axs,("Throughput (MiB/s)","Mean completion latency (us)")):
            d=[r for r in ts if r["family"]=="state" and r["metric"]==metric and r["direction"]=="write"]
            for run in sorted({r["run_id"] for r in d}):
                selected=sorted([r for r in d if r["run_id"]==run],key=lambda r:r["time_s"])
                ax.plot([r["time_s"] for r in selected],[r["value"] for r in selected],label=f"Trial {int(selected[0]['trial'])}",alpha=.8)
            finish(ax,"Elapsed time in measured window (s)",ylabel); ax.legend()
        fig.suptitle("Observed write window   |   Sequential 128 KiB, QD 32, one worker, direct=1\nInterval means; final interval may include queue drain. No assumed steady state.",fontsize=10)
        save(fig,"12_state")
    if select("pitfall"):
        d=sorted(select("pitfall"),key=lambda r:-r["direct"])
        fig,axs=plt.subplots(1,2,figsize=(9,4))
        labels=["Direct I/O\nwarm-cache control" if r["direct"] else "Buffered I/O\nwarm cache" for r in d]
        for ax,metric,ylabel in zip(axs,("iops","mean_clat_us"),("IOPS (requests/s)","Mean completion latency (us)")):
            ax.bar(range(len(d)),[r[metric+"_mean"] for r in d],yerr=errors(d,metric),capsize=3)
            ax.set_xticks(range(len(d)),labels); finish(ax,"Same 256 MiB or smaller range",ylabel)
        fig.suptitle("Misleading setup test   |   Random 4 KiB reads, psync, QD 1, one worker\nBoth cases use the same buffered warm pass; direct is the changed setting",fontsize=10)
        save(fig,"13_pitfall")
    (figs/"README.txt").write_text("\n".join(saved)+"\n\nPNG and PDF versions. SD bars describe independent trial summaries, not individual-I/O variation. Time-series latency logs are means; all tail percentiles use JSON+ completion histograms.\n")
    print(f"Saved {len(saved)} figures (PNG and PDF) in {figs}")
    return saved
