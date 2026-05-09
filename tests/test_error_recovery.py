from __future__ import annotations

from xcode_common import EXIT_CODES, enrich_failure_details, normalize_error_entry
from xcode_error_catalog import ERROR_RECOVERY, recovery_for_error_type


def test_known_recovery_values() -> None:
    assert recovery_for_error_type("scheme_not_found") == {
        "recovery": "user_input",
        "transient": False,
        "retry_after_seconds": None,
    }
    assert recovery_for_error_type("command_timeout") == {
        "recovery": "retry",
        "transient": True,
        "retry_after_seconds": 10,
    }


def test_unknown_recovery_is_conservative() -> None:
    assert recovery_for_error_type("not_real") == {
        "recovery": "unknown",
        "transient": False,
        "retry_after_seconds": None,
    }


def test_string_error_entry_becomes_object() -> None:
    entry = normalize_error_entry("bad scheme", error_type="scheme_not_found", summary="failed")
    assert entry["message"] == "bad scheme"
    assert entry["error_type"] == "scheme_not_found"
    assert entry["recovery"] == "user_input"


def test_dict_error_entry_preserves_fields() -> None:
    entry = normalize_error_entry(
        {"error_type": "simulator_boot_failed", "message": "boot", "custom": "value"},
        error_type="subprocess_failed",
        summary="failed",
    )
    assert entry["custom"] == "value"
    assert entry["recovery"] == "retry"
    assert entry["retry_after_seconds"] == 5


def test_failure_details_do_not_overwrite_explicit_recovery() -> None:
    details = enrich_failure_details({"recovery": "permanent"}, error_type="subprocess_failed")
    assert details["recovery"] == "permanent"
    assert details["transient"] is True


def test_exit_codes_have_recovery_catalog_entries() -> None:
    assert set(EXIT_CODES).issubset(set(ERROR_RECOVERY))
