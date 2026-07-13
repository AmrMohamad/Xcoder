#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("archive", type=Path)
args = parser.parse_args()
started = time.perf_counter()
total = 0
with zipfile.ZipFile(args.archive) as archive:
    for info in archive.infolist():
        with archive.open(info) as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                total += len(chunk)
print(json.dumps({"bytes_hashed": total, "seconds": time.perf_counter() - started}))
