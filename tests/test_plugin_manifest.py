from __future__ import annotations

import json
from pathlib import Path


def test_plugin_manifest_uses_conventional_hooks_discovery() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert "hooks" not in manifest
    assert (root / "hooks" / "hooks.json").is_file()
