from __future__ import annotations

from xcode_ide_automation import (
    EXPECTED_DISTRIBUTION_STEP_TITLE,
    METHOD_CONFIRM_BUTTONS,
    parse_option_overrides,
    parse_distribution_sheet,
    parse_organizer_distribution_phase,
    validate_distribution_sheet,
)


def sample_distribution_native_payload(selected: bool = True, description_text: str = "Use recommended settings to upload app to App Store Connect for testing and release.") -> dict:
    return {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {
                                        "role": "AXStaticText",
                                        "identifier": "Distribution Step Title",
                                        "description": "Distribution Step Title",
                                        "value": EXPECTED_DISTRIBUTION_STEP_TITLE,
                                    },
                                    {
                                        "role": "AXButton",
                                        "title": "Cancel",
                                        "enabled": True,
                                    },
                                    {
                                        "role": "AXButton",
                                        "title": "Distribute",
                                        "enabled": True,
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": "Mazaya (Debug)",
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": "com.robusta.mazaya",
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": "3.2.0 (1)",
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": "iOS",
                                    },
                                    {
                                        "role": "AXOpaqueProviderGroup",
                                        "subrole": "AXOpaqueProviderGrid",
                                        "children": [
                                            {
                                                "role": "AXButton",
                                                "description": "App Store Connect",
                                                "enabled": True,
                                                "selected": selected,
                                            },
                                            {
                                                "role": "AXButton",
                                                "description": "Custom",
                                                "enabled": True,
                                                "selected": False,
                                            },
                                        ],
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": description_text,
                                    },
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }


def test_parse_distribution_sheet_returns_structured_phase() -> None:
    sheet = parse_distribution_sheet(sample_distribution_native_payload())

    assert sheet is not None
    assert sheet["phase_id"] == "distribution_method_selection"
    assert sheet["step_title"] == EXPECTED_DISTRIBUTION_STEP_TITLE
    assert sheet["selected_method"] == "App Store Connect"
    assert [item["method"] for item in sheet["methods"]] == ["App Store Connect", "Custom"]
    assert sheet["app_identity"]["bundle_identifier"] == "com.robusta.mazaya"


def test_parse_distribution_sheet_can_infer_selected_method_from_description_text() -> None:
    sheet = parse_distribution_sheet(
        sample_distribution_native_payload(
            selected=False,
            description_text="Use custom options to export or upload this build.",
        )
    )

    assert sheet is not None
    assert sheet["selected_method"] == "Custom"
    assert validate_distribution_sheet(sheet) is None


def test_parse_distribution_sheet_can_infer_release_testing_from_real_description() -> None:
    sheet = parse_distribution_sheet(
        sample_distribution_native_payload(
            selected=False,
            description_text="Use recommended settings to ad hoc distribute to registered devices.",
        )
    )

    assert sheet is not None
    assert sheet["selected_method"] == "Release Testing"


def test_validate_distribution_sheet_rejects_missing_sheet() -> None:
    assert validate_distribution_sheet(None) == "Xcode Organizer distribution sheet was not found"


def test_parse_organizer_distribution_phase_reports_downstream_buttons_and_guards() -> None:
    payload = {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {
                                        "role": "AXStaticText",
                                        "identifier": "Distribution Step Title",
                                        "description": "Distribution Step Title",
                                        "value": "Upload for App Store Connect:",
                                    },
                                    {
                                        "role": "AXStaticText",
                                        "value": "Signing FirebaseFirestoreInternal.framework…",
                                    },
                                    {
                                        "role": "AXButton",
                                        "title": "Cancel",
                                        "enabled": True,
                                    },
                                    {
                                        "role": "AXButton",
                                        "title": "Upload",
                                        "enabled": True,
                                    },
                                    {
                                        "role": "AXCheckBox",
                                        "title": "Include app symbols",
                                        "value": "1",
                                        "enabled": True,
                                    },
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    phase = parse_organizer_distribution_phase(payload)

    assert phase is not None
    assert phase["phase_kind"] == "downstream_distribution"
    assert phase["phase_id"] == "upload_for_app_store_connect"
    assert phase["recognized"] is True
    assert phase["route_context"]["top_level_method"] == "App Store Connect"
    assert phase["progress_text"] == ["Signing FirebaseFirestoreInternal.framework…"]
    assert phase["safe_navigation"] == [{"title": "Cancel", "enabled": True, "selected": False}]
    assert phase["guarded_final_actions"] == [{"title": "Upload", "enabled": True, "selected": False}]
    assert phase["controls"][0]["title"] == "Include app symbols"


def test_parse_organizer_distribution_phase_reuses_method_selection_parser() -> None:
    phase = parse_organizer_distribution_phase(sample_distribution_native_payload())

    assert phase is not None
    assert phase["phase_kind"] == "method_selection"
    assert phase["phase_id"] == "distribution_method_selection"
    assert phase["selected_method"] == "App Store Connect"


def test_parse_organizer_distribution_phase_reports_custom_routes() -> None:
    payload = {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {
                                        "role": "AXStaticText",
                                        "identifier": "Distribution Step Title",
                                        "description": "Distribution Step Title",
                                        "value": "Select a method of distribution:",
                                    },
                                    {
                                        "role": "AXRadioButton",
                                        "title": "App Store Connect, Distribute with App Store Connect for testing and release.",
                                        "enabled": True,
                                        "selected": False,
                                        "value": "0",
                                    },
                                    {
                                        "role": "AXRadioButton",
                                        "title": "Debugging, Distribute with development signing to registered devices.",
                                        "enabled": True,
                                        "selected": True,
                                        "value": "1",
                                    },
                                    {"role": "AXButton", "title": "Cancel", "enabled": True},
                                    {"role": "AXButton", "title": "Next", "enabled": True},
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    phase = parse_organizer_distribution_phase(payload)

    assert phase is not None
    assert phase["phase_kind"] == "custom_method_selection"
    assert phase["selected_custom_route"] == "Debugging"
    assert [item["route"] for item in phase["custom_routes"]] == ["App Store Connect", "Debugging"]


def test_parse_organizer_distribution_phase_normalizes_custom_destination_options() -> None:
    payload = {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {
                                        "role": "AXStaticText",
                                        "identifier": "Distribution Step Title",
                                        "description": "Distribution Step Title",
                                        "value": "Select a destination:",
                                    },
                                    {"role": "AXRadioButton", "title": "Upload", "enabled": True, "selected": False, "value": "0"},
                                    {"role": "AXRadioButton", "title": "Export", "enabled": True, "selected": True, "value": "1"},
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    phase = parse_organizer_distribution_phase(payload)

    assert phase is not None
    assert phase["phase_kind"] == "custom_destination_selection"
    assert phase["selected_options"]["custom_destination"] == "export"


def test_parse_organizer_distribution_phase_normalizes_checkbox_options() -> None:
    payload = {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {
                                        "role": "AXStaticText",
                                        "identifier": "Distribution Step Title",
                                        "description": "Distribution Step Title",
                                        "value": "Release Testing distribution options:",
                                    },
                                    {"role": "AXCheckBox", "title": "Strip Swift symbols", "enabled": True, "selected": False, "value": "0"},
                                    {"role": "AXCheckBox", "title": "Include manifest for over-the-air installation", "enabled": True, "selected": False, "value": "1"},
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    phase = parse_organizer_distribution_phase(payload)

    assert phase is not None
    assert phase["phase_kind"] == "custom_options"
    assert phase["selected_options"]["strip_swift_symbols"] is False
    assert phase["selected_options"]["include_manifest"] is True


def test_parse_organizer_distribution_phase_collects_error_messages() -> None:
    payload = {
        "ok": True,
        "summary": {
            "windows": [
                {
                    "title": "Archives",
                    "tree": {
                        "role": "AXWindow",
                        "children": [
                            {
                                "role": "AXSheet",
                                "children": [
                                    {"role": "AXStaticText", "identifier": "Distribution Step Title", "description": "Distribution Step Title", "value": "An error was encountered:"},
                                    {"role": "AXStaticText", "value": "No profiles were found"},
                                ],
                            }
                        ],
                    },
                }
            ]
        },
    }

    phase = parse_organizer_distribution_phase(payload)

    assert phase is not None
    assert phase["phase_kind"] == "error"
    assert phase["error_messages"] == ["No profiles were found"]


def test_parse_option_overrides_accepts_json_object() -> None:
    parsed = parse_option_overrides('{"custom_destination":"upload","include_manifest":true}')

    assert parsed == {"custom_destination": "upload", "include_manifest": True}


def test_method_confirm_buttons_map_custom_to_next() -> None:
    assert METHOD_CONFIRM_BUTTONS["Custom"] == "Next"
    assert METHOD_CONFIRM_BUTTONS["App Store Connect"] == "Distribute"
