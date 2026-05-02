import Foundation
import AppKit
import ApplicationServices
import Darwin

let helperSchemaVersion = "xcode-native-helper.v0.1"
let helperVersion = "0.3.0"
let xcodeBundleIdentifier = "com.apple.dt.Xcode"

struct NativeResponse {
    static func emit(
        ok: Bool,
        commandName: String,
        summary: Any,
        errorType: String? = nil,
        warnings: [Any] = [],
        errors: [Any] = [],
        nextActions: [Any] = [],
        exitCode: Int32 = 0
    ) -> Never {
        var payload: [String: Any] = [
            "schema_version": helperSchemaVersion,
            "helper_version": helperVersion,
            "ok": ok,
            "command_name": commandName,
            "summary": summary,
            "warnings": warnings,
            "errors": errors,
            "next_actions": nextActions
        ]
        if let errorType {
            payload["error_type"] = errorType
        }
        do {
            let data = try JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            let fallbackPayload: [String: Any] = [
                "schema_version": helperSchemaVersion,
                "helper_version": helperVersion,
                "ok": false,
                "command_name": commandName,
                "error_type": "native_helper_failed",
                "summary": "JSON serialization failed",
                "warnings": [],
                "errors": ["Native helper JSON serialization failed."],
                "next_actions": []
            ]
            let fallbackData = (try? JSONSerialization.data(withJSONObject: fallbackPayload, options: [.sortedKeys]))
                ?? Data("{\"schema_version\":\"xcode-native-helper.v0.1\",\"helper_version\":\"0.3.0\",\"ok\":false,\"command_name\":\"native-helper\",\"error_type\":\"native_helper_failed\",\"summary\":\"JSON serialization failed\",\"warnings\":[],\"errors\":[\"Native helper JSON serialization failed.\"],\"next_actions\":[]}".utf8)
            let fallback = String(data: fallbackData, encoding: .utf8) ?? "{\"ok\":false,\"error_type\":\"native_helper_failed\"}"
            FileHandle.standardOutput.write(Data(fallback.utf8))
            FileHandle.standardOutput.write(Data("\n".utf8))
            exit(62)
        }
        exit(exitCode)
    }
}

func buildArch() -> String {
    #if arch(arm64)
    return "arm64"
    #elseif arch(x86_64)
    return "x86_64"
    #else
    return "unknown"
    #endif
}

func accessibilityTrusted(prompt: Bool) -> Bool {
    return AXIsProcessTrustedWithOptions(["AXTrustedCheckOptionPrompt": prompt] as CFDictionary)
}

func xcodeApplications() -> [NSRunningApplication] {
    NSWorkspace.shared.runningApplications
        .filter { $0.bundleIdentifier == xcodeBundleIdentifier }
        .sorted { $0.processIdentifier < $1.processIdentifier }
}

func installedXcodeApps() -> [[String: Any]] {
    let applicationDirs = [
        URL(fileURLWithPath: "/Applications", isDirectory: true),
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications", isDirectory: true)
    ]
    var seen = Set<String>()
    var items: [[String: Any]] = []
    for dir in applicationDirs {
        guard let children = try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.isApplicationKey],
            options: [.skipsHiddenFiles]
        ) else {
            continue
        }
        for child in children where child.pathExtension == "app" {
            guard let bundle = Bundle(url: child), bundle.bundleIdentifier == xcodeBundleIdentifier else {
                continue
            }
            let path = child.path
            guard !seen.contains(path) else {
                continue
            }
            seen.insert(path)
            let info = bundle.infoDictionary ?? [:]
            let displayName = info["CFBundleDisplayName"] as? String
                ?? info["CFBundleName"] as? String
                ?? child.deletingPathExtension().lastPathComponent
            items.append([
                "bundle_identifier": bundle.bundleIdentifier ?? "",
                "bundle_path": path,
                "version": info["CFBundleShortVersionString"] as? String ?? "",
                "build": info["CFBundleVersion"] as? String ?? "",
                "executable_path": bundle.executableURL?.path ?? "",
                "display_name": displayName
            ])
        }
    }
    return items.sorted { lhs, rhs in
        String(describing: lhs["bundle_path"] ?? "") < String(describing: rhs["bundle_path"] ?? "")
    }
}

func appSummary(_ app: NSRunningApplication) -> [String: Any] {
    [
        "pid": Int(app.processIdentifier),
        "bundle_identifier": app.bundleIdentifier ?? "",
        "bundle_path": app.bundleURL?.path ?? "",
        "executable_path": app.executableURL?.path ?? "",
        "localized_name": app.localizedName ?? "",
        "frontmost": app.isActive,
        "activation_policy": app.activationPolicy.rawValue
    ]
}

func xcodeStateSummary() -> [String: Any] {
    let apps = xcodeApplications()
    let frontmost = apps.first(where: { $0.isActive })
    let primary = frontmost ?? apps.first
    return [
        "xcode_running": !apps.isEmpty,
        "frontmost": frontmost != nil,
        "pid": primary.map { Int($0.processIdentifier) } as Any,
        "bundle_identifier": primary?.bundleIdentifier ?? "",
        "bundle_path": primary?.bundleURL?.path ?? "",
        "executable_path": primary?.executableURL?.path ?? "",
        "running_app_count": apps.count,
        "running_apps": apps.map(appSummary),
        "installed_xcode_count": installedXcodeApps().count
    ]
}

func waitForFrontmostXcode(attempts: Int, interval: TimeInterval) -> NSRunningApplication? {
    for _ in 0..<attempts {
        if let active = xcodeApplications().first(where: { $0.isActive }) {
            return active
        }
        Thread.sleep(forTimeInterval: interval)
    }
    return nil
}

func copyAttribute(_ element: AXUIElement, _ attribute: String) -> (Any?, AXError) {
    var value: CFTypeRef?
    let error = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
    return (value, error)
}

func stringAttribute(_ element: AXUIElement, _ attribute: String) -> String {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return "" }
    return value as? String ?? ""
}

func boolAttribute(_ element: AXUIElement, _ attribute: String) -> Bool {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return false }
    return value as? Bool ?? false
}

func axValuePair(_ element: AXUIElement, _ attribute: String) -> [String: Double]? {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success, let rawValue = value else { return nil }
    guard CFGetTypeID(rawValue as CFTypeRef) == AXValueGetTypeID() else { return nil }
    let axValue = rawValue as! AXValue
    let type = AXValueGetType(axValue)
    if type == .cgPoint {
        var point = CGPoint.zero
        if AXValueGetValue(axValue, .cgPoint, &point) {
            return ["x": point.x, "y": point.y]
        }
    }
    if type == .cgSize {
        var size = CGSize.zero
        if AXValueGetValue(axValue, .cgSize, &size) {
            return ["width": size.width, "height": size.height]
        }
    }
    return nil
}

func optionalStringAttribute(_ element: AXUIElement, _ attribute: String) -> String? {
    let value = stringAttribute(element, attribute)
    return value.isEmpty ? nil : value
}

func elementArrayAttribute(_ element: AXUIElement, _ attribute: String) -> [AXUIElement] {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return [] }
    return value as? [AXUIElement] ?? []
}

func windowSummary(_ window: AXUIElement, index: Int) -> [String: Any] {
    let role = stringAttribute(window, kAXRoleAttribute as String)
    let subrole = stringAttribute(window, kAXSubroleAttribute as String)
    let title = stringAttribute(window, kAXTitleAttribute as String)
    let sheets = elementArrayAttribute(window, "AXSheets")
    var item: [String: Any] = [
        "index": index,
        "title": title,
        "role": role,
        "subrole": subrole,
        "focused": boolAttribute(window, kAXFocusedAttribute as String),
        "main": boolAttribute(window, kAXMainAttribute as String),
        "minimized": boolAttribute(window, "AXMinimized"),
        "sheet_count": sheets.count,
        "sheets": sheets.enumerated().map { item in
            [
                "index": item.offset,
                "title": stringAttribute(item.element, kAXTitleAttribute as String),
                "role": stringAttribute(item.element, kAXRoleAttribute as String),
                "subrole": stringAttribute(item.element, kAXSubroleAttribute as String)
            ]
        }
    ]
    if let identifier = optionalStringAttribute(window, kAXIdentifierAttribute as String) {
        item["identifier"] = identifier
    }
    if let document = optionalStringAttribute(window, kAXDocumentAttribute as String) {
        item["document"] = document
    }
    if let position = axValuePair(window, kAXPositionAttribute as String) {
        item["position"] = position
    }
    if let size = axValuePair(window, kAXSizeAttribute as String) {
        item["size"] = size
    }
    return item
}

func modalBlockers(from windows: [[String: Any]]) -> [[String: Any]] {
    windows.compactMap { window in
        let title = window["title"] as? String ?? ""
        let role = window["role"] as? String ?? ""
        let subrole = window["subrole"] as? String ?? ""
        let sheetCount = window["sheet_count"] as? Int ?? 0
        let blocker = sheetCount > 0 || subrole.localizedCaseInsensitiveContains("dialog") || role.localizedCaseInsensitiveContains("dialog")
        if blocker {
            return [
                "title": title,
                "role": role,
                "subrole": subrole,
                "sheet_count": sheetCount
            ]
        }
        return nil
    }
}

func requirePathArgument(_ args: [String]) -> String? {
    guard let index = args.firstIndex(of: "--path"), args.indices.contains(index + 1) else {
        return nil
    }
    return args[index + 1]
}

func usage() -> Never {
    NativeResponse.emit(
        ok: false,
        commandName: "usage",
        summary: "Unsupported native helper command",
        errorType: "usage_error",
        errors: [CommandLine.arguments.dropFirst().joined(separator: " ")],
        nextActions: [
            "Use helper version, permissions status, permissions request, app xcode-state, app activate-xcode, app open-workspace, or ax xcode-windows."
        ],
        exitCode: 2
    )
}

func handleHelper(_ args: [String]) -> Never {
    guard args.first == "version" else { usage() }
    NativeResponse.emit(
        ok: true,
        commandName: "helper.version",
        summary: [
            "helper_schema_version": helperSchemaVersion,
            "helper_version": helperVersion,
            "build_arch": buildArch(),
            "swift_version": "unknown",
            "process_identifier": Int(ProcessInfo.processInfo.processIdentifier),
            "executable_path": CommandLine.arguments.first ?? ""
        ]
    )
}

func handlePermissions(_ args: [String]) -> Never {
    guard let command = args.first else { usage() }
    switch command {
    case "status":
        let trusted = accessibilityTrusted(prompt: false)
        NativeResponse.emit(
            ok: true,
            commandName: "permissions.status",
            summary: [
                "accessibility_trusted": trusted,
                "prompted": false
            ],
            nextActions: trusted ? [] : ["Run bin/xcode native permissions request --json if you want macOS to show the Accessibility prompt."]
        )
    case "request":
        let trusted = accessibilityTrusted(prompt: true)
        NativeResponse.emit(
            ok: true,
            commandName: "permissions.request",
            summary: [
                "accessibility_trusted": trusted,
                "prompted": true
            ]
        )
    default:
        usage()
    }
}

func handleApp(_ args: [String]) -> Never {
    guard let command = args.first else { usage() }
    switch command {
    case "xcode-state":
        NativeResponse.emit(ok: true, commandName: "app.xcode-state", summary: xcodeStateSummary())
    case "installed-xcodes":
        let apps = installedXcodeApps()
        NativeResponse.emit(
            ok: true,
            commandName: "app.installed-xcodes",
            summary: [
                "installed_xcode_count": apps.count,
                "installed_xcodes": apps
            ]
        )
    case "activate-xcode":
        let apps = xcodeApplications()
        guard let app = apps.first(where: { $0.isActive }) ?? apps.first else {
            NativeResponse.emit(
                ok: false,
                commandName: "app.activate-xcode",
                summary: "Xcode is not running",
                errorType: "xcode_not_running",
                nextActions: ["Open Xcode or use app open-workspace with an existing .xcodeproj/.xcworkspace."],
                exitCode: 10
            )
        }
        let requested = app.activate(options: [.activateAllWindows])
        if let active = waitForFrontmostXcode(attempts: 10, interval: 0.1) {
            NativeResponse.emit(ok: true, commandName: "app.activate-xcode", summary: appSummary(active))
        }
        var openedBundleFallback = false
        if let bundleURL = app.bundleURL {
            openedBundleFallback = NSWorkspace.shared.open(bundleURL)
            _ = app.activate(options: [.activateAllWindows])
            if let active = waitForFrontmostXcode(attempts: 10, interval: 0.1) {
                var summary = appSummary(active)
                summary["activation_requested"] = requested
                summary["opened_bundle_fallback"] = openedBundleFallback
                NativeResponse.emit(ok: true, commandName: "app.activate-xcode", summary: summary)
            }
        }
        var summary = appSummary(xcodeApplications().first ?? app)
        summary["activation_requested"] = requested
        summary["opened_bundle_fallback"] = openedBundleFallback
        NativeResponse.emit(
            ok: false,
            commandName: "app.activate-xcode",
            summary: summary,
            errorType: "xcode_activation_failed",
            errors: ["Native activation attempts did not make Xcode frontmost."],
            nextActions: ["Bring Xcode forward manually before GUI-only actions, or use read-only native state and workspace-info commands that do not require frontmost focus."],
            exitCode: 24
        )
    case "open-workspace":
        guard let requestedPath = requirePathArgument(args) else {
            NativeResponse.emit(
                ok: false,
                commandName: "app.open-workspace",
                summary: "Missing --path",
                errorType: "usage_error",
                exitCode: 2
            )
        }
        let expanded = NSString(string: requestedPath).expandingTildeInPath
        let url = URL(fileURLWithPath: expanded)
        let ext = url.pathExtension.lowercased()
        guard url.isFileURL, ext == "xcodeproj" || ext == "xcworkspace" else {
            NativeResponse.emit(
                ok: false,
                commandName: "app.open-workspace",
                summary: "Workspace/project path must be a local .xcodeproj or .xcworkspace",
                errorType: "path_violation",
                errors: [url.path],
                exitCode: 6
            )
        }
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            NativeResponse.emit(
                ok: false,
                commandName: "app.open-workspace",
                summary: "Workspace/project path does not exist or is not a directory",
                errorType: "workspace_open_failed",
                errors: [url.path],
                exitCode: 25
            )
        }
        if NSWorkspace.shared.open(url) {
            NativeResponse.emit(
                ok: true,
                commandName: "app.open-workspace",
                summary: [
                    "path": url.path,
                    "opened": true
                ],
                nextActions: ["Verify workspace document load through bin/xcode ide workspace-info --workspace-path <path> --json."]
            )
        }
        NativeResponse.emit(
            ok: false,
            commandName: "app.open-workspace",
            summary: "NSWorkspace could not open the requested Xcode container",
            errorType: "workspace_open_failed",
            errors: [url.path],
            exitCode: 25
        )
    default:
        usage()
    }
}

func handleAX(_ args: [String]) -> Never {
    guard args.first == "xcode-windows" else { usage() }
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.xcode-windows",
            summary: "Accessibility permission is not granted for xcode-native-helper",
            errorType: "accessibility_not_trusted",
            nextActions: ["Run bin/xcode native permissions request --json if you want macOS to show the Accessibility prompt."],
            exitCode: 4
        )
    }
    let apps = xcodeApplications()
    guard let app = apps.first(where: { $0.isActive }) ?? apps.first else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.xcode-windows",
            summary: "Xcode is not running",
            errorType: "xcode_not_running",
            exitCode: 10
        )
    }
    let appElement = AXUIElementCreateApplication(app.processIdentifier)
    let windows = elementArrayAttribute(appElement, kAXWindowsAttribute as String)
    let summaries = windows.enumerated().map { windowSummary($0.element, index: $0.offset) }
    let blockers = modalBlockers(from: summaries)
    let focused = summaries.first { ($0["focused"] as? Bool) == true }
    let blockerStatus = blockers.isEmpty ? "clear" : "blocked"
    NativeResponse.emit(
        ok: true,
        commandName: "ax.xcode-windows",
        summary: [
            "accessibility_trusted": true,
            "xcode": appSummary(app),
            "window_count": summaries.count,
            "windows": summaries,
            "focused_window": focused ?? [:],
            "modal_blockers_status": blockerStatus,
            "ax_partial_failure_count": 0,
            "modal_blockers": blockers
        ],
        warnings: blockers.isEmpty ? [] : ["Xcode has windows or sheets that may block automation."]
    )
}

let rawArgs = Array(CommandLine.arguments.dropFirst()).filter { $0 != "--json" }
guard let group = rawArgs.first else { usage() }
let rest = Array(rawArgs.dropFirst())

switch group {
case "helper":
    handleHelper(rest)
case "permissions":
    handlePermissions(rest)
case "app":
    handleApp(rest)
case "ax":
    handleAX(rest)
default:
    usage()
}
