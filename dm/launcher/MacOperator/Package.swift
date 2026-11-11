// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Game2MobileOperator",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "Game2MobileOperator", targets: ["Game2MobileOperator"]),
        .library(name: "OperatorCore", targets: ["OperatorCore"]),
    ],
    targets: [
        .target(name: "OperatorCore"),
        .executableTarget(name: "Game2MobileOperator", dependencies: ["OperatorCore"]),
        .testTarget(name: "OperatorCoreTests", dependencies: ["OperatorCore"]),
    ]
)
