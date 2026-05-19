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
            if let outputPath = outputJSONPathArgument() {
                try data.write(to: URL(fileURLWithPath: outputPath), options: [.atomic])
            }
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

func outputJSONPathArgument() -> String? {
    let args = CommandLine.arguments
    guard let index = args.firstIndex(of: "--output-json-path"), args.indices.contains(index + 1) else {
        return nil
    }
    return args[index + 1]
}

func commandArguments() -> [String] {
    var result: [String] = []
    var iterator = CommandLine.arguments.dropFirst().makeIterator()
    while let arg = iterator.next() {
        if arg == "--json" {
            continue
        }
        if arg == "--output-json-path" {
            _ = iterator.next()
            continue
        }
        result.append(arg)
    }
    return result
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

func helperRuntimeIdentity() -> [String: Any] {
    let bundle = Bundle.main
    return [
        "bundle_identifier": bundle.bundleIdentifier ?? "",
        "bundle_path": bundle.bundleURL.path,
        "bundle_executable_path": bundle.executableURL?.path ?? "",
        "executable_path": CommandLine.arguments.first ?? "",
        "process_identifier": Int(ProcessInfo.processInfo.processIdentifier)
    ]
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

func optionalBoolAttribute(_ element: AXUIElement, _ attribute: String) -> Bool? {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return nil }
    return value as? Bool
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

func stringValue(_ value: Any?) -> String {
    guard let value else { return "" }
    if let string = value as? String {
        return string
    }
    if let number = value as? NSNumber {
        return number.stringValue
    }
    return String(describing: value)
}

func elementArrayAttribute(_ element: AXUIElement, _ attribute: String) -> [AXUIElement] {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return [] }
    return value as? [AXUIElement] ?? []
}

func elementAttribute(_ element: AXUIElement, _ attribute: String) -> AXUIElement? {
    let (value, error) = copyAttribute(element, attribute)
    guard error == .success else { return nil }
    guard let value else { return nil }
    if CFGetTypeID(value as CFTypeRef) == AXUIElementGetTypeID() {
        return (value as! AXUIElement)
    }
    return nil
}

func axErrorName(_ error: AXError) -> String {
    switch error {
    case .success: return "success"
    case .failure: return "failure"
    case .illegalArgument: return "illegalArgument"
    case .invalidUIElement: return "invalidUIElement"
    case .invalidUIElementObserver: return "invalidUIElementObserver"
    case .cannotComplete: return "cannotComplete"
    case .attributeUnsupported: return "attributeUnsupported"
    case .actionUnsupported: return "actionUnsupported"
    case .notificationUnsupported: return "notificationUnsupported"
    case .notImplemented: return "notImplemented"
    case .notificationAlreadyRegistered: return "notificationAlreadyRegistered"
    case .notificationNotRegistered: return "notificationNotRegistered"
    case .apiDisabled: return "apiDisabled"
    case .noValue: return "noValue"
    case .parameterizedAttributeUnsupported: return "parameterizedAttributeUnsupported"
    case .notEnoughPrecision: return "notEnoughPrecision"
    @unknown default: return "unknown"
    }
}

func pressAX(_ element: AXUIElement) -> AXError {
    AXUIElementPerformAction(element, kAXPressAction as CFString)
}

func argumentValue(_ args: [String], flag: String) -> String? {
    guard let index = args.firstIndex(of: flag), args.indices.contains(index + 1) else {
        return nil
    }
    return args[index + 1]
}

func intArgumentValue(_ args: [String], flag: String, default defaultValue: Int) -> Int {
    guard let raw = argumentValue(args, flag: flag), let value = Int(raw) else {
        return defaultValue
    }
    return value
}

func menuChild(named title: String, in element: AXUIElement) -> AXUIElement? {
    for child in elementArrayAttribute(element, kAXChildrenAttribute as String) {
        if stringAttribute(child, kAXTitleAttribute as String) == title {
            return child
        }
    }
    return nil
}

func menuContainer(for item: AXUIElement) -> AXUIElement? {
    if let menu = elementAttribute(item, "AXMenu") {
        return menu
    }
    for child in elementArrayAttribute(item, kAXChildrenAttribute as String) {
        if stringAttribute(child, kAXRoleAttribute as String) == "AXMenu" {
            return child
        }
    }
    return nil
}

func parseMenuPath(from args: [String]) -> [String]? {
    guard let index = args.firstIndex(of: "--menu-path-json"), args.indices.contains(index + 1) else {
        return nil
    }
    guard let data = args[index + 1].data(using: .utf8),
          let value = try? JSONSerialization.jsonObject(with: data) as? [String],
          value.count >= 2
    else {
        return nil
    }
    return value
}

func pressXcodeMenu(path: [String]) -> Never {
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Accessibility permission is not granted for XcodeNativeHelper.app",
            errorType: "accessibility_not_trusted",
            nextActions: ["Approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."],
            exitCode: 4
        )
    }
    let apps = xcodeApplications()
    guard let app = apps.first(where: { $0.isActive }) ?? apps.first else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode is not running",
            errorType: "xcode_not_running",
            exitCode: 10
        )
    }
    _ = app.activate(options: [.activateIgnoringOtherApps])
    Thread.sleep(forTimeInterval: 0.2)

    let appElement = AXUIElementCreateApplication(app.processIdentifier)
    guard let menuBar = elementAttribute(appElement, kAXMenuBarAttribute as String) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu bar was not accessible",
            errorType: "xcode_menu_item_not_found",
            exitCode: 28
        )
    }
    guard let root = menuChild(named: path[0], in: menuBar) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu bar item was not found",
            errorType: "xcode_menu_item_not_found",
            errors: [["menu_path": path]],
            exitCode: 28
        )
    }
    var pressError = pressAX(root)
    if pressError != .success && pressError != .actionUnsupported {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu bar item could not be opened",
            errorType: "xcode_menu_item_not_found",
            errors: [["menu_path": path, "ax_error": axErrorName(pressError)]],
            exitCode: 28
        )
    }
    Thread.sleep(forTimeInterval: 0.2)

    var container: AXUIElement? = menuContainer(for: root)
    var target: AXUIElement?
    for (index, label) in path.dropFirst().enumerated() {
        guard let currentContainer = container, let item = menuChild(named: label, in: currentContainer) else {
            NativeResponse.emit(
                ok: false,
                commandName: "ax.press-menu",
                summary: "Xcode menu item was not found",
                errorType: "xcode_menu_item_not_found",
                errors: [["menu_path": path, "missing_label": label]],
                exitCode: 28
            )
        }
        target = item
        if index < path.dropFirst().count - 1 {
            pressError = pressAX(item)
            if pressError != .success && pressError != .actionUnsupported {
                NativeResponse.emit(
                    ok: false,
                    commandName: "ax.press-menu",
                    summary: "Xcode submenu could not be opened",
                    errorType: "xcode_menu_item_not_found",
                    errors: [["menu_path": path, "label": label, "ax_error": axErrorName(pressError)]],
                    exitCode: 28
                )
            }
            Thread.sleep(forTimeInterval: 0.2)
            container = menuContainer(for: item)
        }
    }
    guard let target else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu item was not resolved",
            errorType: "xcode_menu_item_not_found",
            errors: [["menu_path": path]],
            exitCode: 28
        )
    }
    let enabled = boolAttribute(target, kAXEnabledAttribute as String)
    guard enabled else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu item is disabled",
            errorType: "xcode_menu_item_disabled",
            errors: [["menu_path": path]],
            exitCode: 29
        )
    }
    pressError = pressAX(target)
    guard pressError == .success else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-menu",
            summary: "Xcode menu item press failed",
            errorType: "xcode_ide_automation_failed",
            errors: [["menu_path": path, "ax_error": axErrorName(pressError)]],
            exitCode: 11
        )
    }
    NativeResponse.emit(
        ok: true,
        commandName: "ax.press-menu",
        summary: [
            "menu_path": path,
            "menu_path_text": path.joined(separator: " > "),
            "performed": true,
            "enabled_before_press": enabled,
            "xcode": appSummary(app)
        ]
    )
}

func xcodeAppElement() -> (NSRunningApplication, AXUIElement)? {
    let apps = xcodeApplications()
    guard let app = apps.first(where: { $0.isActive }) ?? apps.first else {
        return nil
    }
    return (app, AXUIElementCreateApplication(app.processIdentifier))
}

func windowsForXcode() -> (NSRunningApplication, [AXUIElement])? {
    guard let (app, appElement) = xcodeAppElement() else {
        return nil
    }
    return (app, elementArrayAttribute(appElement, kAXWindowsAttribute as String))
}

func windowMatches(_ window: AXUIElement, titleContains: String?) -> Bool {
    guard let titleContains, !titleContains.isEmpty else {
        return true
    }
    let title = stringAttribute(window, kAXTitleAttribute as String)
    let identifier = stringAttribute(window, kAXIdentifierAttribute as String)
    return title.localizedCaseInsensitiveContains(titleContains)
        || identifier.localizedCaseInsensitiveContains(titleContains)
}

func axElementSummary(_ element: AXUIElement, depth: Int, maxDepth: Int, maxChildren: Int) -> [String: Any] {
    let (rawValue, _) = copyAttribute(element, kAXValueAttribute as String)
    let children = elementArrayAttribute(element, kAXChildrenAttribute as String)
    var item: [String: Any] = [
        "role": stringAttribute(element, kAXRoleAttribute as String),
        "subrole": stringAttribute(element, kAXSubroleAttribute as String),
        "title": stringAttribute(element, kAXTitleAttribute as String),
        "description": stringAttribute(element, kAXDescriptionAttribute as String),
        "value": stringValue(rawValue),
        "enabled": boolAttribute(element, kAXEnabledAttribute as String),
        "child_count": children.count
    ]
    if let identifier = optionalStringAttribute(element, kAXIdentifierAttribute as String) {
        item["identifier"] = identifier
    }
    if let selected = optionalBoolAttribute(element, kAXSelectedAttribute as String) {
        item["selected"] = selected
    }
    if depth < maxDepth {
        item["children"] = children.prefix(maxChildren).map {
            axElementSummary($0, depth: depth + 1, maxDepth: maxDepth, maxChildren: maxChildren)
        }
    }
    return item
}

func collectMatchingElements(
    _ element: AXUIElement,
    title: String?,
    role: String?,
    maxDepth: Int,
    depth: Int = 0,
    matches: inout [[String: Any]],
    elements: inout [AXUIElement]
) {
    let elementTitle = stringAttribute(element, kAXTitleAttribute as String)
    let elementDescription = stringAttribute(element, kAXDescriptionAttribute as String)
    let elementRole = stringAttribute(element, kAXRoleAttribute as String)
    let titleMatches = title == nil
        || elementTitle.localizedCaseInsensitiveCompare(title!) == .orderedSame
        || elementDescription.localizedCaseInsensitiveCompare(title!) == .orderedSame
    let roleMatches = role == nil || elementRole == role
    if titleMatches && roleMatches {
        matches.append(axElementSummary(element, depth: 0, maxDepth: 0, maxChildren: 0))
        elements.append(element)
    }
    guard depth < maxDepth else {
        return
    }
    for child in elementArrayAttribute(element, kAXChildrenAttribute as String) {
        collectMatchingElements(child, title: title, role: role, maxDepth: maxDepth, depth: depth + 1, matches: &matches, elements: &elements)
    }
}

func inspectXcodeAX(args: [String]) -> Never {
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.inspect",
            summary: "Accessibility permission is not granted for XcodeNativeHelper.app",
            errorType: "accessibility_not_trusted",
            nextActions: ["Approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."],
            exitCode: 4
        )
    }
    guard let (app, windows) = windowsForXcode() else {
        NativeResponse.emit(ok: false, commandName: "ax.inspect", summary: "Xcode is not running", errorType: "xcode_not_running", exitCode: 10)
    }
    let titleContains = argumentValue(args, flag: "--window-title-contains")
    let maxDepth = intArgumentValue(args, flag: "--max-depth", default: 3)
    let maxChildren = intArgumentValue(args, flag: "--max-children", default: 80)
    let selectedWindows = windows.enumerated().filter { windowMatches($0.element, titleContains: titleContains) }
    NativeResponse.emit(
        ok: true,
        commandName: "ax.inspect",
        summary: [
            "xcode": appSummary(app),
            "window_filter": titleContains ?? "",
            "window_count": selectedWindows.count,
            "windows": selectedWindows.map { item in
                var summary = windowSummary(item.element, index: item.offset)
                summary["tree"] = axElementSummary(item.element, depth: 0, maxDepth: maxDepth, maxChildren: maxChildren)
                return summary
            }
        ]
    )
}

func pressXcodeButton(args: [String]) -> Never {
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-button",
            summary: "Accessibility permission is not granted for XcodeNativeHelper.app",
            errorType: "accessibility_not_trusted",
            nextActions: ["Approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."],
            exitCode: 4
        )
    }
    guard let title = argumentValue(args, flag: "--title"), !title.isEmpty else {
        usage()
    }
    guard let (app, windows) = windowsForXcode() else {
        NativeResponse.emit(ok: false, commandName: "ax.press-button", summary: "Xcode is not running", errorType: "xcode_not_running", exitCode: 10)
    }
    let titleContains = argumentValue(args, flag: "--window-title-contains")
    let selectedWindows = windows.enumerated().filter { windowMatches($0.element, titleContains: titleContains) }
    var matches: [[String: Any]] = []
    var elements: [AXUIElement] = []
    for item in selectedWindows {
        collectMatchingElements(item.element, title: title, role: "AXButton", maxDepth: 10, matches: &matches, elements: &elements)
    }
    guard elements.count == 1, let target = elements.first else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-button",
            summary: elements.isEmpty ? "Xcode button was not found" : "Xcode button match is ambiguous",
            errorType: elements.isEmpty ? "xcode_menu_item_not_found" : "destination_ambiguous",
            errors: [["title": title, "window_filter": titleContains ?? "", "matches": matches]],
            exitCode: elements.isEmpty ? 28 : 17
        )
    }
    let enabled = boolAttribute(target, kAXEnabledAttribute as String)
    guard enabled else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-button",
            summary: "Xcode button is disabled",
            errorType: "xcode_menu_item_disabled",
            errors: [["title": title, "matches": matches]],
            exitCode: 29
        )
    }
    let error = pressAX(target)
    guard error == .success else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-button",
            summary: "Xcode button press failed",
            errorType: "xcode_ide_automation_failed",
            errors: [["title": title, "ax_error": axErrorName(error)]],
            exitCode: 11
        )
    }
    NativeResponse.emit(
        ok: true,
        commandName: "ax.press-button",
        summary: [
            "title": title,
            "performed": true,
            "enabled_before_press": enabled,
            "window_filter": titleContains ?? "",
            "match": matches.first ?? [:],
            "xcode": appSummary(app)
        ]
    )
}

func pressXcodeControl(args: [String]) -> Never {
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-control",
            summary: "Accessibility permission is not granted for XcodeNativeHelper.app",
            errorType: "accessibility_not_trusted",
            nextActions: ["Approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."],
            exitCode: 4
        )
    }
    guard let title = argumentValue(args, flag: "--title"), !title.isEmpty else {
        usage()
    }
    guard let role = argumentValue(args, flag: "--role"), !role.isEmpty else {
        usage()
    }
    let allowedRoles = Set(["AXRadioButton", "AXCheckBox", "AXPopUpButton"])
    guard allowedRoles.contains(role) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-control",
            summary: "Unsupported AX control role",
            errorType: "usage_error",
            errors: [["role": role, "allowed_roles": Array(allowedRoles).sorted()]],
            exitCode: 2
        )
    }
    guard let (app, windows) = windowsForXcode() else {
        NativeResponse.emit(ok: false, commandName: "ax.press-control", summary: "Xcode is not running", errorType: "xcode_not_running", exitCode: 10)
    }
    let titleContains = argumentValue(args, flag: "--window-title-contains")
    let selectedWindows = windows.enumerated().filter { windowMatches($0.element, titleContains: titleContains) }
    var matches: [[String: Any]] = []
    var elements: [AXUIElement] = []
    for item in selectedWindows {
        collectMatchingElements(item.element, title: title, role: role, maxDepth: 10, matches: &matches, elements: &elements)
    }
    guard elements.count == 1, let target = elements.first else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-control",
            summary: elements.isEmpty ? "Xcode control was not found" : "Xcode control match is ambiguous",
            errorType: elements.isEmpty ? "xcode_menu_item_not_found" : "destination_ambiguous",
            errors: [["title": title, "role": role, "window_filter": titleContains ?? "", "matches": matches]],
            exitCode: elements.isEmpty ? 28 : 17
        )
    }
    let enabled = boolAttribute(target, kAXEnabledAttribute as String)
    let selectedBeforePress = optionalBoolAttribute(target, kAXSelectedAttribute as String)
    let (rawValueBeforePress, _) = copyAttribute(target, kAXValueAttribute as String)
    guard enabled else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-control",
            summary: "Xcode control is disabled",
            errorType: "xcode_menu_item_disabled",
            errors: [["title": title, "role": role, "matches": matches]],
            exitCode: 29
        )
    }
    let error = pressAX(target)
    guard error == .success else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.press-control",
            summary: "Xcode control press failed",
            errorType: "xcode_ide_automation_failed",
            errors: [["title": title, "role": role, "ax_error": axErrorName(error)]],
            exitCode: 11
        )
    }
    NativeResponse.emit(
        ok: true,
        commandName: "ax.press-control",
        summary: [
            "title": title,
            "role": role,
            "performed": true,
            "enabled_before_press": enabled,
            "selected_before_press": selectedBeforePress as Any,
            "value_before_press": stringValue(rawValueBeforePress),
            "window_filter": titleContains ?? "",
            "match": matches.first ?? [:],
            "xcode": appSummary(app)
        ]
    )
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
            "Use helper version, permissions status, permissions request, app xcode-state, app activate-xcode, app open-workspace, ax xcode-windows, ax press-menu, ax inspect, ax press-button, or ax press-control."
        ],
        exitCode: 2
    )
}

func handleHelper(_ args: [String]) -> Never {
    guard args.first == "version" else { usage() }
    var summary = helperRuntimeIdentity()
    summary["helper_schema_version"] = helperSchemaVersion
    summary["helper_version"] = helperVersion
    summary["build_arch"] = buildArch()
    summary["swift_version"] = "unknown"
    NativeResponse.emit(
        ok: true,
        commandName: "helper.version",
        summary: summary
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
            nextActions: trusted ? [] : ["Run bin/xcode native permissions request --json, then approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."]
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
    if args.first == "press-menu" {
        guard let path = parseMenuPath(from: args) else { usage() }
        pressXcodeMenu(path: path)
    }
    if args.first == "inspect" {
        inspectXcodeAX(args: args)
    }
    if args.first == "press-button" {
        pressXcodeButton(args: args)
    }
    if args.first == "press-control" {
        pressXcodeControl(args: args)
    }
    guard args.first == "xcode-windows" else { usage() }
    guard accessibilityTrusted(prompt: false) else {
        NativeResponse.emit(
            ok: false,
            commandName: "ax.xcode-windows",
            summary: "Accessibility permission is not granted for xcode-native-helper",
            errorType: "accessibility_not_trusted",
            nextActions: ["Run bin/xcode native permissions request --json, then approve XcodeNativeHelper.app in System Settings > Privacy & Security > Accessibility."],
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

let rawArgs = commandArguments()
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
