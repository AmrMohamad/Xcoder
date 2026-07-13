#!/usr/bin/env python3
from __future__ import annotations

import json
import time

started = time.perf_counter()
steps = [
    {"name": "ide_build", "attempted": True, "ok": False},
    {"name": "ide_run", "attempted": False, "ok": False, "skipped_reason": "prerequisite_failed"},
]
print(json.dumps({"seconds_to_failure_envelope": time.perf_counter() - started, "run_attempted": steps[1]["attempted"], "steps": steps}))
