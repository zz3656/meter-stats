// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "MeterStats",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "MeterStats"
            // 资源不通过 SwiftPM 打包:handlers/ 与 utils/ 各有 __init__.py,
            // .process("Resources") 会因同名资源冲突报错。
            // 全部资源由 build-app.sh 从 Sources/App/Resources/ 直接拷贝。
        )
    ]
)
