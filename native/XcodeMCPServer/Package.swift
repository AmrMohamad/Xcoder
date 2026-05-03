// swift-tools-version: 6.1

import PackageDescription

let package = Package(
    name: "XcodeMCPServer",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "xcode-mcp-server", targets: ["XcodeMCPServer"])
    ],
    dependencies: [
        .package(url: "https://github.com/modelcontextprotocol/swift-sdk.git", exact: "0.12.0")
    ],
    targets: [
        .executableTarget(
            name: "XcodeMCPServer",
            dependencies: [
                .product(name: "MCP", package: "swift-sdk")
            ]
        )
    ]
)
