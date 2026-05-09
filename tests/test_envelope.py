from __future__ import annotations

from xcode_common import build_envelope, emit_failure


def test_success_envelope_shape() -> None:
    envelope = build_envelope(
        command_name="unit",
        ok=True,
        status="success",
        summary="ok",
        error_type=None,
    )

    assert envelope["schema_version"] == "xcode-plugin.v0.3"
    assert envelope["ok"] is True
    assert envelope["status"] == "success"
    assert envelope["error_type"] is None
    assert envelope["errors"] == []


def test_failure_emit_adds_recovery_metadata(capsys) -> None:
    exit_code = emit_failure("unit", "simulator_boot_failed", "boot failed")
    captured = capsys.readouterr()

    assert exit_code == 30
    assert '"recovery": "retry"' in captured.out
    assert '"transient": true' in captured.out
    assert '"retry_after_seconds": 5' in captured.out
