from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def dump_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def write_csv(path, rows, columns=None):
    rows = list(rows)
    columns = columns or (list(rows[0]) if rows else [])
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_size(value):
    m = re.fullmatch(r"(\d+)(B|KiB|MiB|GiB|TiB)?", str(value), re.IGNORECASE)
    if not m:
        raise ValueError("Use an integer with B, KiB, MiB, GiB, or TiB, e.g. 16GiB")
    powers = {"b": 0, "kib": 1, "mib": 2, "gib": 3, "tib": 4}
    return int(m[1]) * 1024 ** powers[(m[2] or "B").lower()]


def safe_fio_path(path):
    path = str(Path(path).absolute())
    if any(c in path for c in "\n\r:\\[]#;\x00"):
        raise ValueError("fio paths must not contain newlines, colon, backslash, brackets, #, or ;")
    return path
