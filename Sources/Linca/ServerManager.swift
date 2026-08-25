import Foundation

/// 管理 python3 server.py 子进程
/// 单例:app 全局只允许一个 server 实例
final class ServerManager {
    static let shared = ServerManager()

    private var process: Process?
    private let projectRoot: URL
    private let port: UInt16 = 8765

    private init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        self.projectRoot = home
            .appendingPathComponent("Library")
            .appendingPathComponent("Application Support")
            .appendingPathComponent("com.linca.electricity-stats")
    }

    private func getRuntimeDir() -> URL {
        return projectRoot
    }

    /// 获取版本号: bundle 侧传一个 VERSION 文件给 runtime
    private func bundleVersion() -> String? {
        guard let bundleResources = Bundle.main.resourceURL else { return nil }
        let verFile = bundleResources.appendingPathComponent("VERSION")
        if FileManager.default.fileExists(atPath: verFile.path) {
            return try? String(contentsOf: verFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return nil
    }

    private func runtimeVersion() -> String? {
        let verFile = getRuntimeDir().appendingPathComponent("VERSION")
        if FileManager.default.fileExists(atPath: verFile.path) {
            return try? String(contentsOf: verFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return nil
    }

    private func ensureRuntimeFiles() throws {
        let runtime = getRuntimeDir()
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)

        guard let bundleResources = Bundle.main.resourceURL else {
            throw NSError(domain: "Linca", code: 1, userInfo: [NSLocalizedDescriptionKey: "找不到 bundle Resources"])
        }

        if let bv = bundleVersion(), let rv = runtimeVersion(), bv == rv {
            return
        }

        let files = ["server.py", "app_handler.py", "report.py", "storage.py", "routing.py", "index.html", "style.css", "app.js", "admin.js"]
        for filename in files {
            let src = bundleResources.appendingPathComponent(filename)
            let dst = runtime.appendingPathComponent(filename)

            guard FileManager.default.fileExists(atPath: src.path) else {
                continue
            }

            var needsCopy = true
            if FileManager.default.fileExists(atPath: dst.path) {
                let srcAttrs = try? FileManager.default.attributesOfItem(atPath: src.path)
                let dstAttrs = try? FileManager.default.attributesOfItem(atPath: dst.path)
                if let srcMod = srcAttrs?[.modificationDate] as? Date,
                   let dstMod = dstAttrs?[.modificationDate] as? Date,
                   srcMod == dstMod {
                    needsCopy = false
                }
            }

            if needsCopy {
                do {
                    if FileManager.default.fileExists(atPath: dst.path) {
                        try FileManager.default.removeItem(at: dst)
                    }
                    try FileManager.default.copyItem(at: src, to: dst)
                } catch {
                    throw error
                }
            }
        }

        // SwiftPM .process("Resources") 不拷贝子目录，需要手动复制
        for subdir in ["handlers", "utils"] {
            let srcDir = bundleResources.appendingPathComponent(subdir)
            let dstDir = runtime.appendingPathComponent(subdir)
            guard FileManager.default.fileExists(atPath: srcDir.path) else { continue }
            do {
                if FileManager.default.fileExists(atPath: dstDir.path) {
                    try FileManager.default.removeItem(at: dstDir)
                }
                try FileManager.default.copyItem(at: srcDir, to: dstDir)
            } catch {
                throw error
            }
        }

        if let version = bundleVersion() {
            let verFile = runtime.appendingPathComponent("VERSION")
            try? version.write(to: verFile, atomically: true, encoding: .utf8)
        }
    }

    func start() throws {
        if isRunning { return }
        if process != nil { return }

        try ensureRuntimeFiles()

        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        proc.arguments = ["python3", "server.py"]
        proc.currentDirectoryURL = projectRoot

        let logDir = projectRoot.appendingPathComponent("logs")
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
        let logFile = logDir.appendingPathComponent("server.log")
        FileManager.default.createFile(atPath: logFile.path, contents: nil)
        let logHandle = try FileHandle(forWritingTo: logFile)
        proc.standardOutput = logHandle
        proc.standardError = logHandle

        try proc.run()
        self.process = proc
    }

    func stop() {
        guard let p = process, p.isRunning else { return }
        p.terminate()
        let deadline = Date().addingTimeInterval(2)
        while p.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.1)
        }
        if p.isRunning {
            kill(p.processIdentifier, SIGKILL)
        }
        process = nil
    }

    func waitForReady(timeout: TimeInterval = 8.0) async -> Bool {
        let url = URL(string: "http://127.0.0.1:\(port)/api/health")!
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await ping(url) { return true }
            try? await Task.sleep(nanoseconds: 200_000_000)
        }
        return false
    }

    private func ping(_ url: URL) async -> Bool {
        do {
            let (_, resp) = try await URLSession.shared.data(from: url)
            return (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    var isPortBusy: Bool {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        proc.arguments = ["-ti:\(port)"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = Pipe()
        do {
            try proc.run()
            proc.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            return !data.isEmpty
        } catch {
            return false
        }
    }

    var isServerPidAlive: Bool {
        let pidFile = getRuntimeDir().appendingPathComponent("server.pid")
        guard let pidStr = try? String(contentsOf: pidFile, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines),
              let pid = Int32(pidStr) else {
            return false
        }
        return kill(pid, 0) == 0
    }

    func killPortOccupants() {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/bin/sh")
        proc.arguments = ["-c", "lsof -ti:\(port) | xargs kill -TERM 2>/dev/null || true"]
        proc.standardOutput = Pipe()
        proc.standardError = Pipe()
        try? proc.run()
        proc.waitUntilExit()

        Thread.sleep(forTimeInterval: 2.0)

        let proc2 = Process()
        proc2.executableURL = URL(fileURLWithPath: "/bin/sh")
        proc2.arguments = ["-c", "lsof -ti:\(port) | xargs kill -9 2>/dev/null || true"]
        proc2.standardOutput = Pipe()
        proc2.standardError = Pipe()
        try? proc2.run()
        proc2.waitUntilExit()
    }

    private var isRunning: Bool {
        guard let p = process else { return false }
        return p.isRunning
    }
}
