from __future__ import annotations

import glob
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from .common import utcnow


def command(argv, timeout=15):
    try:
        p = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
        return {"argv": argv, "returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"argv": argv, "unavailable": str(e)}


def read_optional(path):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def temperatures():
    result = []
    for path in glob.glob("/sys/class/hwmon/hwmon*/temp*_input"):
        p = Path(path)
        try:
            result.append({"sensor": path, "chip": read_optional(p.parent / "name"),
                           "label": read_optional(p.with_name(p.name.replace("_input", "_label"))),
                           "celsius": float(p.read_text()) / 1000})
        except (OSError, ValueError):
            pass
    return result


def mount_info(directory):
    directory = Path(directory)
    while not directory.exists():
        directory = directory.parent
    info = command(["findmnt", "-J", "-T", str(directory), "-o", "TARGET,SOURCE,FSTYPE,OPTIONS"])
    try:
        return json.loads(info["stdout"])["filesystems"][0]
    except (KeyError, ValueError, IndexError):
        raise ValueError(f"Cannot identify target filesystem with findmnt: {info}")


def check_filesystem(directory):
    info = mount_info(directory)
    fs = info.get("fstype", "").lower()
    if fs in ("9p", "drvfs", "ntfs", "ntfs3", "cifs", "nfs", "nfs4", "tmpfs", "ramfs") or fs.startswith("fuse"):
        raise ValueError(f"Unsupported benchmark filesystem {fs}. Use WSL2 Linux ext4 under ~/ssdbench-data")
    if "microsoft" in platform.release().lower() and "wsl2" not in platform.release().lower():
        raise ValueError("WSL1 detected. Switch this distribution to WSL2 before benchmarking")
    return info


def snapshot(directory):
    usage = shutil.disk_usage(directory)
    return {"utc": utcnow(), "temperatures": temperatures(),
            "diskstats": read_optional("/proc/diskstats"),
            "meminfo": read_optional("/proc/meminfo"),
            "loadavg": read_optional("/proc/loadavg"),
            "filesystem_free_bytes": usage.free}


def collect(directory, fio="fio"):
    return {"captured_utc": utcnow(), "platform": platform.platform(),
            "kernel": platform.release(), "python": platform.python_version(),
            "wsl_distro": os.environ.get("WSL_DISTRO_NAME"), "cpu_count_visible": os.cpu_count(),
            "mount": mount_info(directory),
            "commands": [command(x) for x in (
                [fio, "--version"], ["uname", "-a"], ["lscpu"],
                ["lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,MODEL,TRAN,ROTA,MOUNTPOINTS"],
                ["df", "-B1", str(directory)], ["free", "-b"])],
            "snapshot": snapshot(directory),
            "note": "WSL virtual block devices need not expose physical SSD model, interface, SMART, or hardware queue depth. Add Windows host metadata."}
