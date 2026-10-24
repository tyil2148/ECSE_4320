from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from .common import dump_json, safe_fio_path, utcnow

MARKER = ".ssdbench-owner.json"
DATA = "workload.bin"


def target_directory(value):
    path = Path(value).expanduser().absolute()
    # Resolve ancestors only after rejecting links. We never follow a link to a target.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError(f"Symlink in test-directory path: {part}")
    path = path.resolve()
    if path == Path("/") or any(path == Path(x) or Path(x) in path.parents for x in ("/dev", "/proc", "/sys", "/etc", "/boot")):
        raise ValueError("Use a dedicated directory under your Linux home, never a device or system path")
    safe_fio_path(path)
    return path


def regular(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        raise ValueError(f"Expected a regular file with one link: {path}")
    return st


@contextmanager
def locked(directory):
    """One experiment at a time for a managed target, including initialization."""
    lock = directory / ".ssdbench.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        regular(lock)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another ssdbench process is using this target") from exc
        yield
    finally:
        os.close(fd)


def create_target(directory, size):
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise ValueError("Initialization requires a new or completely empty dedicated directory")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    free = shutil.disk_usage(directory).free
    reserve = max(1024 ** 3, size // 5)
    if free < size + reserve:
        raise ValueError(f"Need test size plus reserve: {(size + reserve) / 1024**3:.1f} GiB; Linux reports {free/1024**3:.1f} GiB free")
    return reserve


def allocate(directory, size):
    path = directory / DATA
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.ftruncate(fd, size)  # Not marked initialized until fio writes every byte.
        st = os.fstat(fd)
    finally:
        os.close(fd)
    meta = {"format": "ssdbench-owned-file-v1", "uuid": str(uuid.uuid4()),
            "created_utc": utcnow(), "size": size, "device": st.st_dev,
            "inode": st.st_ino, "initialized": False, "data_file": DATA}
    dump_json(directory / MARKER, meta)
    return meta


def validate_target(directory, require_initialized=True):
    marker = directory / MARKER
    regular(marker)
    meta = json.loads(marker.read_text(encoding="utf-8"))
    if meta.get("format") != "ssdbench-owned-file-v1" or meta.get("data_file") != DATA:
        raise ValueError("Directory was not initialized by this program")
    st = regular(directory / DATA)
    if (st.st_dev, st.st_ino, st.st_size) != (meta["device"], meta["inode"], meta["size"]):
        raise ValueError("Managed data file identity or size changed; refusing I/O")
    if require_initialized and not meta["initialized"]:
        raise ValueError("Initialization did not finish. Use cleanup, then initialize again")
    return meta


def cleanup(directory):
    meta = validate_target(directory, require_initialized=False)
    (directory / DATA).unlink()  # Never recursive deletion; retain initialization evidence.
    (directory / MARKER).unlink()
    return meta["size"]
