#!/usr/bin/env python3
"""Collect machine facts without asserting host frequency or cache visibility."""
import datetime, json, os, pathlib, platform, subprocess

def capture(cmd):
    try:
        p=subprocess.run(cmd,text=True,capture_output=True,timeout=15)
        return {'command':cmd,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    except (OSError,subprocess.TimeoutExpired) as e:
        return {'command':cmd,'unavailable':str(e)}

def collect(cpu, notes):
    caches=[]
    base=pathlib.Path(f'/sys/devices/system/cpu/cpu{cpu}/cache')
    for d in sorted(base.glob('index*')):
        item={}
        for key in ('level','type','size','coherency_line_size','shared_cpu_list','ways_of_associativity'):
            try: item[key]=(d/key).read_text().strip()
            except OSError: item[key]=None
        caches.append(item)
    settings={}
    for name in ('scaling_governor','scaling_driver','scaling_min_freq','scaling_max_freq','scaling_cur_freq'):
        try:settings[name]=pathlib.Path(f'/sys/devices/system/cpu/cpu{cpu}/cpufreq/{name}').read_text().strip()
        except OSError:settings[name]='unavailable'
    def read(path):
        try:return pathlib.Path(path).read_text()
        except OSError:return 'unavailable'
    return dict(timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),platform=platform.platform(),
        python=platform.python_version(),cpu=cpu,allowed_cpus=sorted(os.sched_getaffinity(0)),
        cpuinfo=read('/proc/cpuinfo'),meminfo=read('/proc/meminfo'),lscpu=capture(['lscpu','-J']),
        uname=capture(['uname','-a']),perf_probe=capture(['perf','stat','-e','cycles,instructions','--','true']),
        perf_paranoid=read('/proc/sys/kernel/perf_event_paranoid').strip(),
        smt_active=read('/sys/devices/system/cpu/smt/active').strip(),
        sibling_list=read(f'/sys/devices/system/cpu/cpu{cpu}/topology/thread_siblings_list').strip(),
        caches=caches,frequency_settings=settings,host_notes=notes,
        wsl=bool(os.getenv('WSL_DISTRO_NAME') or 'microsoft' in platform.release().lower()))

def cache_bytes(size):
    if not size:return None
    try:
        return int(size[:-1])*{'K':1024,'M':1024**2,'G':1024**3}[size[-1]]
    except (ValueError,KeyError):
        try:return int(size)
        except ValueError:return None
