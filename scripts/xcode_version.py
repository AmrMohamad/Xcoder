#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path


def plugin_version(root: Path) -> str:
    payload = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    version = payload.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("plugin manifest version is missing")
    return version
