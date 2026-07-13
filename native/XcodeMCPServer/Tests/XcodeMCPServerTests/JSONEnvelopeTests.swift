import XCTest
@testable import XcodeMCPServer

final class JSONEnvelopeTests: XCTestCase {
    func testUsageFailureIncludesRecoveryMetadata() throws {
        let envelope = try decode(JSONEnvelope.failure(errorType: "usage_error", summary: "Bad input"))
        XCTAssertEqual(envelope["schema_version"] as? String, XcodeMCPConstants.pluginEnvelopeSchemaVersion)
        XCTAssertEqual(envelope["ok"] as? Bool, false)
        XCTAssertEqual(envelope["error_type"] as? String, "usage_error")

        let details = try XCTUnwrap(envelope["details"] as? [String: Any])
        XCTAssertEqual(details["recovery"] as? String, "user_input")
        XCTAssertEqual(details["transient"] as? Bool, false)
        XCTAssertTrue(details["retry_after_seconds"] is NSNull)

        let errors = try XCTUnwrap(envelope["errors"] as? [[String: Any]])
        XCTAssertEqual(errors.first?["error_type"] as? String, "usage_error")
        XCTAssertEqual(errors.first?["recovery"] as? String, "user_input")
    }

    func testTimeoutFailureIsRetryable() throws {
        let envelope = try decode(XcodeToolError.timeout(.execution).envelopeJSON)
        let details = try XCTUnwrap(envelope["details"] as? [String: Any])
        XCTAssertEqual(details["recovery"] as? String, "retry")
        XCTAssertEqual(details["transient"] as? Bool, true)
        XCTAssertEqual(details["retry_after_seconds"] as? Int, 10)
    }

    func testRedactedArgumentsHideAppleCredentialsAndKeyPaths() {
        let arguments = [
            "distribution",
            "upload-archive",
            "--ipa-path",
            "/tmp/App.ipa",
            "--api-key-id",
            "ABC123SECRET",
            "--issuer-id",
            "ISSUER456SECRET",
            "--api-key-path",
            "/tmp/AuthKey_ABC123SECRET.p8",
            "--credentials-ref",
            #"{"api_key_id":"ABC123SECRET","issuer_id":"ISSUER456SECRET","api_key_path":"/tmp/AuthKey_ABC123SECRET.p8"}"#,
            "--timeout-seconds=1200"
        ]

        let redacted = JSONEnvelope.redactedArguments(arguments).joined(separator: " ")

        XCTAssertFalse(redacted.contains("ABC123SECRET"))
        XCTAssertFalse(redacted.contains("ISSUER456SECRET"))
        XCTAssertFalse(redacted.contains("AuthKey_ABC123SECRET.p8"))
        XCTAssertTrue(redacted.contains("--api-key-id <redacted>"))
        XCTAssertTrue(redacted.contains("--issuer-id <redacted>"))
        XCTAssertTrue(redacted.contains("--api-key-path <redacted>"))
        XCTAssertTrue(redacted.contains("--credentials-ref <redacted>"))
        XCTAssertTrue(redacted.contains("/tmp/App.ipa"))
    }

    func testCompactRedactedTextHidesAppleCredentialsAndKeyPaths() {
        let output = #"upload failed --api-key-id ABC123SECRET --issuer-id ISSUER456SECRET --api-key-path /tmp/AuthKey_ABC123SECRET.p8 {"api_key_path":"/tmp/AuthKey_ABC123SECRET.p8"}"#

        let redacted = JSONEnvelope.compactRedactedText(output)

        XCTAssertFalse(redacted.contains("ABC123SECRET"))
        XCTAssertFalse(redacted.contains("ISSUER456SECRET"))
        XCTAssertFalse(redacted.contains("AuthKey_ABC123SECRET.p8"))
        XCTAssertTrue(redacted.contains("--api-key-id <redacted>"))
        XCTAssertTrue(redacted.contains("--issuer-id <redacted>"))
        XCTAssertTrue(redacted.contains("--api-key-path <redacted>"))
    }

    private func decode(_ json: String) throws -> [String: Any] {
        let data = try XCTUnwrap(json.data(using: .utf8))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}
