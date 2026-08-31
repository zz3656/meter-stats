import SwiftUI
import WebKit

// WKWebView 消息处理器:前端请求弹出系统目录选择器(备份目录设置用)
final class BackupDirHandler: NSObject, WKScriptMessageHandler {
    weak var webView: WKWebView?

    init(webView: WKWebView) {
        self.webView = webView
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "pickBackupDir" else { return }
        let panel = NSOpenPanel()
        panel.title = "选择备份目录"
        panel.message = "备份数据将以「日期时间」命名的文件夹保存在所选目录中"
        panel.prompt = "选择此目录"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false

        if panel.runModal() == .OK, let url = panel.url {
            // 序列化路径为 JSON 字符串,安全回传 JS(处理引号/反斜杠/中文)
            // ⚠️ dataWithJSONObject 顶层必须传数组/字典,直接传 String 会崩溃(SIGABRT)
            let jsonPath = (try? JSONSerialization.data(withJSONObject: [url.path], options: []))
                .flatMap { String(data: $0, encoding: .utf8) }
                .map { String($0.dropFirst().dropLast()) } ?? "\"\""
            webView?.evaluateJavaScript("window.__backupDirChosen && window.__backupDirChosen(\(jsonPath));", completionHandler: nil)
        } else {
            // 用户取消 → 回传 null,前端回退默认目录
            webView?.evaluateJavaScript("window.__backupDirChosen && window.__backupDirChosen(null);", completionHandler: nil)
        }
    }
}

// WKWebView 消息处理器:前端请求弹出系统文件选择器(恢复备份选 zip 文件用)
//
// 为什么需要这个桥?
// macOS WKWebView 默认不实现 WKUIDelegate.runOpenPanel,导致 <input type="file"> 的
// .click() 调用静默失败(用户看不到任何反馈)。实现 WKUIDelegate 是修复方案之一,但
// 走 Swift 桥调用 NSOpenPanel 更直接、和现有架构一致。
//
// 协议: JS postMessage({ accept: ".zip" }),Swift 弹文件选择器,返回
// { name, content } (base64) 或 null(用户取消)。
final class PickFileHandler: NSObject, WKScriptMessageHandler {
    weak var webView: WKWebView?

    init(webView: WKWebView) {
        self.webView = webView
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "macOSPickFile" else { return }
        // 解析前端传入的过滤扩展名(默认 .zip)
        var acceptExts: [String] = ["zip"]
        if let body = message.body as? [String: Any], let accept = body["accept"] as? String {
            acceptExts = accept.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces).replacingOccurrences(of: ".", with: "") }
        }

        let panel = NSOpenPanel()
        panel.title = "选择备份文件"
        panel.message = "请选择一个 ZIP 备份文件"
        panel.prompt = "选择"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = acceptExts.isEmpty ? [.zip] : acceptExts.compactMap { ext in
            switch ext.lowercased() {
            case "zip": return .zip
            case "json": return .json
            default: return nil
            }
        }

        if panel.runModal() == .OK, let url = panel.url {
            // 读取文件内容 → base64 编码 → 回传 JS
            // ⚠️ 大文件需要分块读取避免一次性读入内存爆掉;但备份 zip 通常几 MB,
            // 一次性读取可接受。
            do {
                let data = try Data(contentsOf: url)
                let base64 = data.base64EncodedString()
                // JSON 序列化:{name, content}
                let payload: [String: Any] = ["name": url.lastPath, "content": base64]
                let jsonData = try JSONSerialization.data(withJSONObject: payload, options: [])
                let jsonStr = String(data: jsonData, encoding: .utf8) ?? "null"
                webView?.evaluateJavaScript("window.__macOSFileChosen && window.__macOSFileChosen(\(jsonStr));", completionHandler: nil)
            } catch {
                webView?.evaluateJavaScript("window.__macOSFileChosen && window.__macOSFileChosen(null);", completionHandler: nil)
            }
        } else {
            // 用户取消
            webView?.evaluateJavaScript("window.__macOSFileChosen && window.__macOSFileChosen(null);", completionHandler: nil)
        }
    }
}

// 实现 WKUIDelegate: 让 <input type="file"> 也能正常弹原生文件选择器
// 作为 macOSPickFile Swift 桥的兜底(任何 <input type="file"> 都会走这里)
final class WebViewUIDelegate: NSObject, WKUIDelegate {
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        // 允许 zip / json / 文本类文件
        panel.allowedContentTypes = [.zip, .json, .plainText, .text]

        if panel.runModal() == .OK {
            completionHandler(panel.urls)
        } else {
            completionHandler(nil)
        }
    }
}

@main
struct MeterStatsApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate

    var body: some Scene {
        WindowGroup("工程部管理系统") {
            ContentView()
                .frame(minWidth: 1100, minHeight: 750)
        }
        .windowStyle(.titleBar)
        .windowResizability(.contentMinSize)
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        ServerManager.shared.stop()
    }
}

// 启动阶段:用于 UI 显示分步进度
enum BootStep: String {
    case none                  = "启动后端服务..."
    case checking_pid          = "检查残留进程..."
    case killing               = "清理残留进程..."
    case startingPython        = "启动 Python 后端..."
    case waitingBackend        = "等待后端就绪..."
    case loadingPage           = "加载管理页面..."
    case ready                 = ""
}

struct ContentView: View {
    @State private var bootStep: BootStep = .none
    @State private var webView: WKWebView?
    @State private var failMessage: String?

    var body: some View {
        ZStack {
            switch bootStep {
            case .ready:
                if let wv = webView {
                    WebViewContainer(webView: wv)
                        .ignoresSafeArea(.container, edges: .bottom)
                }
            default:
                statusView
            }
        }
        .task {
            await bootstrap()
        }
    }

    @ViewBuilder
    private var statusView: some View {
        VStack(spacing: 20) {
            Image(systemName: "bolt.fill")
                .font(.system(size: 48))
                .foregroundStyle(.tint)

            Text(stepTitle)
                .font(.title2.weight(.medium))
                .multilineTextAlignment(.center)

            ProgressView(value: progressValue, total: 1.0)
                .progressViewStyle(LinearProgressViewStyle())
                .padding(.horizontal, 40)

            if stepDetail != nil {
                Text(stepDetail!)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            if let msg = failMessage {
                Text(msg)
                    .font(.callout)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
                Button("退出") { NSApp.terminate(nil) }
                    .padding(.top, 8)
            } else if bootStep == .none {
                ProgressView()
                    .progressViewStyle(.circular)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(NSColor.windowBackgroundColor))
    }

    private var progressValue: Double {
        switch bootStep {
        case .none:          return 0.0
        case .checking_pid:  return 0.1
        case .killing:       return 0.2
        case .startingPython: return 0.35
        case .waitingBackend: return 0.5
        case .loadingPage:   return 0.7
        case .ready:         return 1.0
        }
    }

    private var stepTitle: String {
        switch bootStep {
        case .none:         return "电表统计"
        case .checking_pid: return "检查残留进程..."
        case .killing:      return "清理残留进程..."
        case .startingPython: return "启动 Python 后端..."
        case .waitingBackend: return "等待后端就绪..."
        case .loadingPage:  return "加载管理页面..."
        case .ready:        return ""
        }
    }

    private var stepDetail: String? {
        switch bootStep {
        case .none, .ready: return nil
        case .checking_pid: return "使用 PID 文件检测残留..."
        case .killing:      return "上次未正常退出,正在清理..."
        case .startingPython: return nil
        case .waitingBackend: return nil
        case .loadingPage:  return "请稍候..."
        }
    }

    private func setStep(_ step: BootStep, on failure: ((String) -> Void)? = nil) async {
        await MainActor.run {
            bootStep = step
        }
        if failure != nil {
            try? await Task.sleep(nanoseconds: 150_000_000)
        }
    }

    private func bootstrap() async {
        // 1. 优先用 PID 文件检测残留（比端口扫描更精确）
        if ServerManager.shared.isServerPidAlive {
            await setStep(.checking_pid)
            try? await Task.sleep(nanoseconds: 200_000_000)
            await setStep(.killing)
            ServerManager.shared.killPortOccupants()
            try? await Task.sleep(nanoseconds: 300_000_000)
        } else if ServerManager.shared.isPortBusy {
            // PID 文件不存在, 回退到端口扫描
            await setStep(.killing)
            ServerManager.shared.killPortOccupants()
            try? await Task.sleep(nanoseconds: 300_000_000)
        }

        // 2. 启动 Python
        await setStep(.startingPython)
        do {
            try ServerManager.shared.start()
        } catch {
            await MainActor.run {
                failMessage = "无法启动 Python: \(error.localizedDescription)"
                bootStep = .none
            }
            return
        }

        // 3. 等健康端点响应
        await setStep(.waitingBackend)
        let ready = await ServerManager.shared.waitForReady(timeout: 8.0)
        guard ready else {
            await MainActor.run {
                failMessage = "后端启动超时,请检查 logs/server.log"
                bootStep = .none
            }
            return
        }

        // 4. 创建 WKWebView 并加载
        await setStep(.loadingPage)
        await MainActor.run {
            let cfg = WKWebViewConfiguration()
            cfg.websiteDataStore = .default()
            // 注册备份目录选择桥(前端 window.webkit.messageHandlers.pickBackupDir)
            // ⚠️ 必须创建 WKWebView 之前挂到 config(WKWebViewConfiguration 是值快照)
            let userContentController = WKUserContentController()
            cfg.userContentController = userContentController
            let wv = WKWebView(frame: .zero, configuration: cfg)
            wv.setValue(false, forKey: "drawsBackground")
            userContentController.add(BackupDirHandler(webView: wv), name: "pickBackupDir")
            // macOS 选文件桥(恢复数据时选 zip)
            userContentController.add(PickFileHandler(webView: wv), name: "macOSPickFile")
            // WKUIDelegate: 让所有 <input type="file"> 也能弹原生选择器(兜底)
            wv.uiDelegate = WebViewUIDelegate()
            let req = URLRequest(url: URL(string: "http://localhost:8765")!)
            wv.load(req)
            self.webView = wv
            self.bootStep = .ready
        }
    }
}

struct WebViewContainer: NSViewRepresentable {
    let webView: WKWebView

    func makeNSView(context: Context) -> NSView {
        let container = NSView()
        webView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.topAnchor.constraint(equalTo: container.topAnchor),
            webView.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            webView.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: container.trailingAnchor),
        ])
        return container
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}
