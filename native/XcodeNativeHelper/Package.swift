// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "XcodeNativeHelper",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "xcode-native-helper", targets: ["XcodeNativeHelper"])
    ],
    targets: [
        .executableTarget(name: "XcodeNativeHelper")
    ]
)
