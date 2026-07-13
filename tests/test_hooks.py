from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


def test_hooks_select_highest_semantic_plugin_version_not_newest_mtime(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    hooks = json.loads((repository / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    home = tmp_path / "home"
    marker = tmp_path / "selected-version.txt"

    for event in hooks.values():
        command = event[0]["hooks"][0]["command"]
        script_name = re.search(r'xcode/\*/scripts/([^"\\]+)', command).group(1)
        for version in ("0.5.0", "0.6.0"):
            script = home / ".codex" / "plugins" / "cache" / "local" / "xcode" / version / "scripts" / script_name
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(
                "import os\nfrom pathlib import Path\n"
                f"Path(os.environ['MARKER']).write_text('{version}', encoding='utf-8')\n",
                encoding="utf-8",
            )
            timestamp = 2_000_000_000 if version == "0.5.0" else 1_000_000_000
            os.utime(script, (timestamp, timestamp))

        completed = subprocess.run(
            ["/bin/sh", "-c", command],
            env={**os.environ, "HOME": str(home), "MARKER": str(marker)},
            text=True,
            capture_output=True,
        )
        assert completed.returncode == 0, completed.stderr
        assert marker.read_text(encoding="utf-8") == "0.6.0"
