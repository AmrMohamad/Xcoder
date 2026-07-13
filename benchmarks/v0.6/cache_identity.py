#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from xcode_cache_identity import project_graph_files  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("project", type=Path)
args = parser.parse_args()
started = time.perf_counter()
files = project_graph_files(args.project.resolve())
print(json.dumps({"files_hashed": len(files), "seconds": time.perf_counter() - started}, sort_keys=True))
