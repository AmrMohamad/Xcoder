#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("report", type=Path)
args = parser.parse_args()
stages = json.loads(args.report.read_text(encoding="utf-8"))
print(json.dumps({"stage_seconds": {stage["name"]: stage.get("seconds", 0) for stage in stages}, "total_seconds": sum(stage.get("seconds", 0) for stage in stages)}, indent=2, sort_keys=True))
