from __future__ import annotations

from pathlib import Path


def test_release_workflow_preserves_clean_checkout_and_propagates_gate_failure() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github" / "workflows" / "release-verify.yml").read_text(encoding="utf-8")

    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert "set -o pipefail" in workflow
    assert "$RUNNER_TEMP/xcoder-release-artifacts" in workflow
    assert 'mkdir -p artifacts' not in workflow
    assert "needs: verify" in workflow
    assert "runs-on: macos-14" in workflow
    assert "actions/download-artifact@v8" in workflow
    assert "xcode_package.py audit" in workflow
    assert "macos-14-audit.json" in workflow
