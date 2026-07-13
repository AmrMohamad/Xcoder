import Foundation
import XCTest
@testable import XcodeMCPServer

final class HealthRedactionTests: XCTestCase {
    func testHealthContainsArgumentShapeButNoArgumentValues() async throws {
        let registry = ActiveProcessRegistry()
        let arguments = [
            "distribution", "upload-archive",
            "--api-key-id", "SECRET123",
            "--issuer-id", "ISSUER456",
            "--api-key-path", "/Users/private-user/AuthKey_SECRET123.p8",
            "--credentials-ref", "{\"api_key_id\":\"SECRET123\"}",
            "--workspace", "/Users/private-user/CompanySecret/App.xcworkspace",
            "--json"
        ]
        await registry.register(processID: Int32(ProcessInfo.processInfo.processIdentifier), arguments: arguments)

        let json = await ServerHealth.healthJSON(registry: registry)
        let payload = try decode(json)
        let command = try XCTUnwrap(payload["active_command"] as? [String: Any])

        XCTAssertEqual(command["group"] as? String, "distribution")
        XCTAssertEqual(command["subcommand"] as? String, "upload-archive")
        XCTAssertEqual(command["argument_count"] as? Int, arguments.count)
        XCTAssertEqual(
            command["option_names"] as? [String],
            ["--api-key-id", "--issuer-id", "--api-key-path", "--credentials-ref", "--workspace", "--json"]
        )
        for forbidden in ["SECRET123", "ISSUER456", "AuthKey_SECRET123.p8", "/Users/private-user", "CompanySecret"] {
            XCTAssertFalse(json.contains(forbidden), "health leaked \(forbidden)")
        }
        XCTAssertFalse(json.contains("active_child_argv_summary"))
    }

    func testInlineOptionValuesNeverAppear() async throws {
        let registry = ActiveProcessRegistry()
        await registry.register(
            processID: Int32(ProcessInfo.processInfo.processIdentifier),
            arguments: [
                "distribution", "upload-archive",
                "--api-key-id=SECRET123",
                "--credentials-ref={\"token\":\"secret\"}",
                "HOME=/Users/private-user"
            ]
        )

        let json = await ServerHealth.healthJSON(registry: registry)
        XCTAssertTrue(json.contains("--api-key-id"))
        XCTAssertTrue(json.contains("--credentials-ref"))
        for forbidden in ["SECRET123", "\"token\":\"secret\"", "/Users/private-user"] {
            XCTAssertFalse(json.contains(forbidden), "health leaked \(forbidden)")
        }
    }

    func testGeneratedSensitiveValuesNeverAppearInHealth() async throws {
        let registry = ActiveProcessRegistry()
        for index in 0..<250 {
            let secret = "secret-\(index)-🔐-\(String(repeating: "x", count: index % 31 + 1))"
            await registry.register(
                processID: Int32(ProcessInfo.processInfo.processIdentifier),
                arguments: [
                    "distribution", "upload-archive",
                    "--token=\(secret)",
                    "--credential", "{\"password\":\"\(secret)\"}",
                    "workspace=/Users/private-\(index)/Project-\(secret).xcworkspace"
                ]
            )
            let json = await ServerHealth.healthJSON(registry: registry)
            XCTAssertFalse(json.contains(secret), "generated health value leaked at iteration \(index)")
        }
    }

    func testUnknownCommandNamesAreOmittedInsteadOfPublished() async throws {
        let registry = ActiveProcessRegistry()
        await registry.register(
            processID: Int32(ProcessInfo.processInfo.processIdentifier),
            arguments: ["CompanySecret", "PrivateProject", "--workspace", "/Users/private-user/App.xcworkspace"]
        )

        let json = await ServerHealth.healthJSON(registry: registry)
        XCTAssertFalse(json.contains("active_command"))
        XCTAssertFalse(json.contains("CompanySecret"))
        XCTAssertFalse(json.contains("PrivateProject"))
        XCTAssertFalse(json.contains("private-user"))
    }

    func testUnknownSubcommandIsOmittedButKnownGroupRemains() async throws {
        let registry = ActiveProcessRegistry()
        await registry.register(
            processID: Int32(ProcessInfo.processInfo.processIdentifier),
            arguments: ["ide", "CompanySecret", "--workspace-path", "/Users/private-user/App.xcworkspace"]
        )

        let payload = try decode(await ServerHealth.healthJSON(registry: registry))
        let command = try XCTUnwrap(payload["active_command"] as? [String: Any])
        XCTAssertEqual(command["group"] as? String, "ide")
        XCTAssertTrue(command["subcommand"] is NSNull)
        XCTAssertFalse(String(describing: payload).contains("CompanySecret"))
    }

    func testPublishedStateUsesRestrictiveModes() async throws {
        let directory = temporaryDirectory().appendingPathComponent("health", isDirectory: true)
        let stateURL = directory.appendingPathComponent("one.json")
        await ServerHealth.publishRuntimeHealth(registry: ActiveProcessRegistry(), stateURL: stateURL)

        let directoryMode = try posixMode(directory)
        let fileMode = try posixMode(stateURL)
        XCTAssertEqual(directoryMode, 0o700)
        XCTAssertEqual(fileMode, 0o600)
    }

    func testAggregateRejectsStaleDeadAndPermissiveFilesWithoutCollapsingInstances() throws {
        let directory = temporaryDirectory().appendingPathComponent("health", isDirectory: true)
        try FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try writeState(directory.appendingPathComponent("first.json"), instanceID: "FIRST")
        try writeState(directory.appendingPathComponent("second.json"), instanceID: "SECOND")
        try writeState(
            directory.appendingPathComponent("stale.json"),
            instanceID: "STALE",
            updatedAt: Date().addingTimeInterval(-60)
        )
        try writeState(
            directory.appendingPathComponent("dead.json"),
            instanceID: "DEAD",
            pid: 999_999
        )
        let permissive = directory.appendingPathComponent("permissive.json")
        try writeState(permissive, instanceID: "PERMISSIVE")
        try FileManager.default.setAttributes([.posixPermissions: 0o644], ofItemAtPath: permissive.path)

        let payload = try decode(ServerHealth.aggregateHealthJSON(directoryURL: directory))
        XCTAssertEqual(payload["schema_version"] as? String, XcodeMCPConstants.healthAggregateSchemaVersion)
        XCTAssertEqual(payload["server_count"] as? Int, 2)
        let servers = try XCTUnwrap(payload["servers"] as? [[String: Any]])
        XCTAssertEqual(Set(servers.compactMap { $0["instance_id"] as? String }), ["FIRST", "SECOND"])
        XCTAssertFalse(String(describing: payload).contains(directory.path))
    }

    func testShutdownRemovesOnlyCurrentInstanceFile() async throws {
        let directory = temporaryDirectory().appendingPathComponent("health", isDirectory: true)
        let owned = directory.appendingPathComponent("owned.json")
        let other = directory.appendingPathComponent("other.json")
        await ServerHealth.publishRuntimeHealth(registry: ActiveProcessRegistry(), stateURL: owned)
        try writeState(other, instanceID: "OTHER")

        ServerHealth.clearPublishedHealth(stateURL: owned)
        ServerHealth.clearPublishedHealth(stateURL: other)

        XCTAssertFalse(FileManager.default.fileExists(atPath: owned.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: other.path))
    }

    private func writeState(
        _ url: URL,
        instanceID: String,
        pid: Int = Int(ProcessInfo.processInfo.processIdentifier),
        updatedAt: Date = Date()
    ) throws {
        let payload: [String: Any] = [
            "schema_version": XcodeMCPConstants.healthSchemaVersion,
            "server": XcodeMCPConstants.serverName,
            "version": XcodeMCPConstants.serverVersion,
            "pid": pid,
            "instance_id": instanceID,
            "started_at_epoch": updatedAt.addingTimeInterval(-1).timeIntervalSince1970,
            "state_updated_at_epoch": updatedAt.timeIntervalSince1970,
            "tool_running": false,
            "queued_tool_count": 0
        ]
        try JSONSerialization.data(withJSONObject: payload).write(to: url)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private func decode(_ json: String) throws -> [String: Any] {
        let data = try XCTUnwrap(json.data(using: .utf8))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }

    private func posixMode(_ url: URL) throws -> Int {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        return try XCTUnwrap(attributes[.posixPermissions] as? NSNumber).intValue
    }

    private func temporaryDirectory() -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}
