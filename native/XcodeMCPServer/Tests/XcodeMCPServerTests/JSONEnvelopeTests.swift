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
        let envelope = try decode(XcodeToolError.timeout.envelopeJSON)
        let details = try XCTUnwrap(envelope["details"] as? [String: Any])
        XCTAssertEqual(details["recovery"] as? String, "retry")
        XCTAssertEqual(details["transient"] as? Bool, true)
        XCTAssertEqual(details["retry_after_seconds"] as? Int, 10)
    }

    private func decode(_ json: String) throws -> [String: Any] {
        let data = try XCTUnwrap(json.data(using: .utf8))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}
