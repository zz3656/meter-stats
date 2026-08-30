// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "MeterStats",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "MeterStats",
            path: "MeterStats",
            exclude: [
                "__pycache__",
                "handlers/__pycache__",
                "utils/__pycache__",
                "AppIcon.appiconset",
                "AppIcon.icns",
                "Info.plist",
                ".data",
                ".server.log",
            ],
            resources: [
                .process("server.py"),
                .process("index.html"),
                .process("app.js"),
                .process("admin.js"),
                .process("style.css"),
                .process("app_handler.py"),
                .process("report.py"),
                .process("storage.py"),
                .process("routing.py"),
                .copy("handlers"),
                .copy("utils"),
                .process("VERSION"),
                .process("favicon.svg"),
                .process("favicon-16.png"),
                .process("favicon-32.png"),
                .process("Linclub.entitlements"),
                .process("run.sh"),
            ]
        )
    ]
)
