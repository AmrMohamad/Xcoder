from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from xcode_native_capabilities import NATIVE_COMMAND_CATALOG, capability_report


def test_capability_catalog_has_typed_mutation_and_forbidden_raw_routes() -> None:
    report = capability_report()
    assert report["mutation"] == [
        "typed_menu_press",
        "unique_button_press",
        "typed_control_press",
    ]
    assert "raw_mcp_ax_selector" in report["unsupported"]
    assert all(item["public_mcp"] != "raw selector" for item in NATIVE_COMMAND_CATALOG)


def test_generated_capability_docs_are_current() -> None:
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "scripts" / "generate_capability_docs.py"), "--check"],
        cwd=root,
        check=False,
    )
    assert completed.returncode == 0
