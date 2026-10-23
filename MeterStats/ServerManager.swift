import Foundation
import Darwin  // for open(), O_CREAT, O_WRONLY, O_APPEND

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
            .appendingPathComponent("com.meter.stats")
    }

    private func getRuntimeDir() -> URL {
        return projectRoot
    }

    private func getBundleResources() -> URL? {
        // 从 ~/MeterStats/MeterStats.app 读取（不受 SIP 保护）
        let appPath = URL(fileURLWithPath: "/Applications/MeterStats.app")
        if FileManager.default.fileExists(atPath: appPath.appendingPathComponent("Contents/Resources").path) {
            return appPath.appendingPathComponent("Contents/Resources")
        }
        // 回退：从 /Applications/MeterStats.app 读取（Swift Bundle.main 指向这里）
        let bundlePath = URL(fileURLWithPath: "/Applications/MeterStats.app")
        if FileManager.default.fileExists(atPath: bundlePath.appendingPathComponent("Contents/Resources").path) {
            return bundlePath.appendingPathComponent("Contents/Resources")
        }
        // 回退：尝试从当前运行的 .app 路径获取
        if let bundle = Bundle.main.resourceURL {
            return bundle
        }
        // 最后回退：从项目目录获取（开发环境）
        return URL(fileURLWithPath: ".").appendingPathComponent("MeterStats").appendingPathComponent("Contents/Resources")
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

        guard let bundleResources = getBundleResources() else {
            throw NSError(domain: "MeterStats", code: 1, userInfo: [NSLocalizedDescriptionKey: "找不到 bundle Resources"])
        }

        // ⚠️ 不能用 VERSION 相同就跳过复制:版本号不变但文件内容可能已更新
        // (如 0.1.0 内部多次构建修复 UI),否则 runtime 会一直用旧文件。
        // 改为始终按 mtime 对比,有变化的文件才复制(数据文件不在列表内,不受影响)。

        let files = ["server.py", "app_handler.py", "report.py", "storage.py", "routing.py", "constants.py", "index.html", "style.css", "app.js", "admin.js", "favicon.svg", "favicon-16.png", "favicon-32.png", "Linclub.entitlements"]
        for filename in files {
            let src = bundleResources.appendingPathComponent(filename)
            let dst = runtime.appendingPathComponent(filename)

            guard FileManager.default.fileExists(atPath: src.path) else {
                continue
            }

            // server.py 每次都必须覆盖（内容可能包含新的 fallback 逻辑）
            if filename == "server.py" && FileManager.default.fileExists(atPath: dst.path) {
                try FileManager.default.removeItem(at: dst)
                try FileManager.default.copyItem(at: src, to: dst)
            } else {
                // 其他文件：按 mtime 对比,有变化的文件才复制(数据文件不在列表内,不受影响)。
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
        }

        // SwiftPM .process("Resources") 不拷贝子目录，需要手动复制
        for subdir in ["handlers", "js", "utils"] {
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
        // 每次启动时先检查端口是否被占用，如果被占用就杀掉再启动
        if isPortBusy {
            print("[ServerManager] 端口被占用，先杀掉旧服务...")
            killPortOccupants()
            Thread.sleep(forTimeInterval: 3.0)  // 等待端口释放和旧服务完全退出
        }
        
        if isRunning { return }
        if process != nil { return }

        // 每次启动都重新同步 runtime 文件（确保 server.py 等更新）
        try ensureRuntimeFiles()

        let proc = Process()
        // 直接使用 /usr/bin/python3，避免 /usr/bin/env python3 在打包 app 中找不到 Python
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        // server.py 已包含 sys.path.insert(0, ...) 修复，确保模块优先级
        proc.arguments = ["server.py"]
        // 工作目录设为运行时目录（包含 server.py 和所有依赖文件）
        proc.currentDirectoryURL = getRuntimeDir()
        
        // 设置 METER_DATA_DIR 指向项目下的 .data/ 目录（与本地运行一致）
        let dataDir = projectRoot.appendingPathComponent(".data")
        try? FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true)
        proc.environment = ["METER_DATA_DIR": dataDir.path]

        let logDir = projectRoot.appendingPathComponent("logs")
        try? FileManager.default.createDirectory(at: logDir, withIntermediateDirectories: true)
        let logFile = logDir.appendingPathComponent("server.log")
        
        // 以追加模式打开 server.log，获取文件描述符
        let logFD = open(logFile.path, O_CREAT | O_WRONLY | O_APPEND, 0o644)
        guard logFD >= 0 else {
            throw NSError(domain: "MeterStats", code: 2, userInfo: [NSLocalizedDescriptionKey: "无法打开 server.log"])
        }
        
        // 将 Python 子进程的 stdout/stderr 重定向到 server.log 的文件描述符
        let logHandle = FileHandle(fileDescriptor: logFD, closeOnDealloc: false)
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

    // MARK: - NAS 数据同步

    /// 从 NAS Docker 实例拉取全部数据文件到本地。
    /// - Parameter remoteUrl: NAS 访问地址，如 "http://lin.icafe.top"
    /// - Returns: (ok, filesSynced, error?) 其中 filesSynced 是成功同步的文件名列表
    func syncFromNAS(remoteUrl: String) async -> (ok: Bool, filesSynced: [String], error: String?) {
        let dataDir = getRuntimeDir()
        guard var components = URLComponents(string: remoteUrl),
              components.url?.scheme == "http" || components.url?.scheme == "https" else {
            return (false, [], "NAS 地址格式不正确，需要 http:// 或 https:// 开头的 URL")
        }
        // 确保路径为 /api/admin/data-files
        let basePath = components.path ?? ""
        components.path = (basePath as NSString).appendingPathComponent("api/admin/data-files")
        guard let fetchUrl = components.url else {
            return (false, [], "无法构造请求 URL")
        }

        // /api/admin/data-files 是公开接口，无需认证
        var request = URLRequest(url: fetchUrl)
        request.timeoutInterval = 15.0

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
                let txt = String(data: data, encoding: .utf8) ?? "无法连接 NAS 服务"
                return (false, [], "NAS 服务不可达: \(txt)")
            }

            let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard let ok = json?["ok"] as? Bool, ok,
                  let files = json?["files"] as? [String: String] else {
                let err = json?["error"] as? String ?? "无法解析 NAS 返回数据"
                return (false, [], "NAS 返回错误: \(err)")
            }

            // 写入本地数据文件（覆盖）
            var syncedFiles: [String] = []
            for (fileName, fileContent) in files {
                let targetFile = dataDir.appendingPathComponent(fileName)
                try fileContent.write(to: targetFile, atomically: true, encoding: .utf8)
                syncedFiles.append(fileName)
                print("[ServerManager] 已同步 \(fileName)")
            }

            // 清除 JSON 缓存（等价于 storage._cache_clear()）
            // 重启 Python 服务即可生效（或调用 /api/health 触发重载）
            print("[ServerManager] NAS 同步完成: \(syncedFiles.count) 个文件")
            return (true, syncedFiles, nil)

        } catch let urlError as URLError {
            if urlError.code == .timedOut {
                return (false, [], "连接 NAS 超时，请检查网络是否能访问 \(remoteUrl)")
            } else if urlError.code == .notConnectedToInternet {
                return (false, [], "当前网络无法访问 NAS 地址 \(remoteUrl)")
            }
            return (false, [], "请求失败: \(urlError.localizedDescription)")
        } catch {
            return (false, [], "同步失败: \(error.localizedDescription)")
        }
    }
}
