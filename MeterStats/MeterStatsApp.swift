import SwiftUI
import WebKit

// WKWebView 消息处理器:前端请求复制文本到系统剪贴板
final class CopyToClipboardHandler: NSObject, WKScriptMessageHandler {
    weak var webView: WKWebView? = nil

    init(webView: WKWebView? = nil) {
        self.webView = webView
    }
    
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "macOSCopyToClipboard" else { return }
        print("[CopyToClipboard] 收到消息: \(String(describing: message.body).prefix(300))")
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()

        var parsedOk = false
        
        // 尝试 1: body 已经是 [String: Any] (WKWebView 自动解析)
        if let dictBody = message.body as? [String: Any],
           let html = dictBody["html"] as? String,
           let tsv = dictBody["tsv"] as? String {
            pasteboard.setString(tsv, forType: .string)
            pasteboard.setString(tsv, forType: .tabularText)
            pasteboard.setString(html, forType: .html)
            print("[CopyToClipboard] ✓ 已写入剪贴板 (HTML: \(html.count) 字符, TSV: \(tsv.count) 字符)")
            parsedOk = true
        }
        
        // 尝试 2: body 是 JSON 字符串，需要手动解析
        if !parsedOk, let textBody = message.body as? String {
            if let jsonData = try? textBody.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let html = json["html"] as? String,
               let tsv = json["tsv"] as? String {
                pasteboard.setString(tsv, forType: .string)
                pasteboard.setString(tsv, forType: .tabularText)
                pasteboard.setString(html, forType: .html)
                print("[CopyToClipboard] ✓ 已写入剪贴板 (HTML: \(html.count) 字符, TSV: \(tsv.count) 字符)")
                parsedOk = true
            }
        }

        if !parsedOk {
            // 旧格式: 纯字符串 (含 \t)
            if let text = message.body as? String {
                pasteboard.setString(text, forType: .string)
                pasteboard.setString(text, forType: .tabularText)
                print("[CopyToClipboard] ✓ 已写入剪贴板 (\(text.count) 字符, 旧格式)")
            } else {
                print("[CopyToClipboard] ✗ 无法解析 body: \(type(of: message.body))")
            }
        }

        // 回调 JS 告知结果（通过 evaluateJavaScript）
        webView?.evaluateJavaScript("window.__copyResult = 'ok';", completionHandler: nil)
    }
}

// WKWebView 消息处理器:前端请求弹出系统目录选择器(备份目录设置用)
final class BackupDirHandler: NSObject, WKScriptMessageHandler {
    // ⚠️ 不要存 weak var webView —— 注册时传 nil 就永远是 nil，
    //    目录路径永远回传不到 JS（「选择」按钮看起来毫无反应）。用 message.webView。
    override init() { super.init() }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "pickBackupDir" else { return }
        let webView = message.webView
        // kind: "backup"(默认) / "image" —— 同一个桥服务两个卡片，标题和回调不同
        let kind = ((message.body as? [String: Any])?["kind"] as? String) ?? "backup"
        let isImage = (kind == "image")
        let cbName = isImage ? "__imageDirChosen" : "__backupDirChosen"

        let panel = NSOpenPanel()
        panel.title = isImage ? "选择图片目录" : "选择备份目录"
        panel.message = isImage
            ? "上传的图片会保存在所选目录中"
            : "备份数据将以「日期时间」命名的文件夹保存在所选目录中"
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
            webView?.evaluateJavaScript("window.\(cbName) && window.\(cbName)(\(jsonPath));", completionHandler: nil)
        } else {
            // 用户取消 → 回传 null
            webView?.evaluateJavaScript("window.\(cbName) && window.\(cbName)(null);", completionHandler: nil)
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
    // ⚠️ 不要存 weak var webView —— 注册时传的是 nil，之后永远是 nil，
    //    evaluateJavaScript 根本不执行（备份恢复的桥一直是这样坏的）。
    //    用 message.webView，每次调用都是活的。
    override init() { super.init() }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "macOSPickFile" else { return }
        let webView = message.webView
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
                let payload: [String: Any] = ["name": url.lastPathComponent, "content": base64]
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

/// 原生图片选择桥 —— 绕开 WKWebView 对 <input type="file"> 的限制。
///
/// 前端点 📷 时调：
///   window.webkit.messageHandlers.macOSPickImage.postMessage({ max: 3 })
/// Swift 弹 NSOpenPanel → 原生压缩（最长边 1600 / JPEG 0.82）→ base64 回传 JS：
///   window.onNativeImagePicked({ files: [{ name, content, ext }] })   // 取消传 null
final class PickImageHandler: NSObject, WKScriptMessageHandler {
    override init() { super.init() }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "macOSPickImage" else { return }
        NSLog("[PickImage] ▶ 收到选图请求")
        let webView = message.webView
        if webView == nil { NSLog("[PickImage] ⚠️ message.webView 为 nil，无法回传") }

        var maxCount = 3
        if let body = message.body as? [String: Any], let m = body["max"] as? Int, m > 0 {
            maxCount = min(m, 5)
        }

        let panel = NSOpenPanel()
        panel.title = "选择照片"
        panel.message = "最多选择 \(maxCount) 张"
        panel.prompt = "选择"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = maxCount > 1
        panel.allowedContentTypes = [.image]

        let cancelJS = "window.onNativeImagePicked && window.onNativeImagePicked(null)"

        NSLog("[PickImage] 弹出面板...")
        let modalResult = panel.runModal()
        NSLog("[PickImage] 面板返回: \(modalResult == .OK ? "选中 \(panel.urls.count) 个文件" : "取消")")
        guard modalResult == .OK, !panel.urls.isEmpty else {
            webView?.evaluateJavaScript(cancelJS, completionHandler: nil)
            return
        }

        var files: [[String: Any]] = []
        for url in panel.urls.prefix(maxCount) {
            guard let raw = try? Data(contentsOf: url) else { continue }
            let compressed = Self.compress(raw)
            let didCompress = compressed.count < raw.count
            let ext = didCompress ? "jpg" : url.pathExtension.lowercased()
            files.append([
                "name": url.lastPathComponent,
                "content": compressed.base64EncodedString(),
                "ext": ext.isEmpty ? "jpg" : ext,
            ])
        }

        guard !files.isEmpty,
              let jsonData = try? JSONSerialization.data(withJSONObject: ["files": files], options: []),
              let jsonStr = String(data: jsonData, encoding: .utf8) else {
            webView?.evaluateJavaScript(cancelJS, completionHandler: nil)
            return
        }
        NSLog("[PickImage] 压缩完成，回传 \(files.count) 张")
        // ⚠️ NSJSONSerialization 顶层必须是数组/字典（传 String 会 SIGABRT）
        webView?.evaluateJavaScript(
            "window.onNativeImagePicked && window.onNativeImagePicked(\(jsonStr))",
            completionHandler: nil
        )
    }

    /// 原生压缩：最长边 1600，JPEG 质量 0.82。压完反而更大就返回原图。
    static func compress(_ data: Data) -> Data {
        guard let src = NSImage(data: data),
              let cg = src.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return data }
        let w = CGFloat(cg.width), h = CGFloat(cg.height)
        let longest = max(w, h)
        guard longest > 0 else { return data }
        let scale = min(1, 1600 / longest)
        let nw = Int((w * scale).rounded()), nh = Int((h * scale).rounded())
        guard nw > 0, nh > 0,
              let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: nw, pixelsHigh: nh,
                bitsPerSample: 8, samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else { return data }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current?.imageInterpolation = .high
        NSImage(cgImage: cg, size: NSSize(width: cg.width, height: cg.height))
            .draw(in: NSRect(x: 0, y: 0, width: nw, height: nh))
        NSGraphicsContext.restoreGraphicsState()
        guard let jpeg = rep.representation(using: .jpeg, properties: [.compressionFactor: 0.82]),
              jpeg.count < data.count else { return data }
        return jpeg
    }
}

// 实现 WKUIDelegate: 让 <input type="file"> 也能正常弹原生文件选择器
// 作为 macOSPickFile Swift 桥的兜底(任何 <input type="file"> 都会走这里)
final class WebViewUIDelegate: NSObject, WKUIDelegate {
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        NSLog("[UIDelegate] ▶ runOpenPanelWith 被调用")
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        // ⚠️ 必须包含 .image：借出/归还/申购/工作记录都要选照片。
        // WKOpenPanelParameters 拿不到 <input accept>，只能在这里给宽集合；
        // 少写 .image 的话 input accept="image/*" 的图片会全部变灰，
        // 用户点「📷 图片」看起来就是"完全没反应"。
        panel.allowedContentTypes = [
            .image, .pdf, .zip, .json, .plainText, .text, .commaSeparatedText
        ]

        if panel.runModal() == .OK {
            completionHandler(panel.urls)
        } else {
            completionHandler(nil)
        }
    }
}

// MARK: - WKWebView delegate 强引用持有
//
// ⚠️ WKWebView.uiDelegate / navigationDelegate 都是 **weak** 引用。
// 写成 `wv.uiDelegate = WebViewUIDelegate()` 的话，对象创建完当场就释放，
// delegate 立刻变 nil —— 表现就是 App 里点任何 <input type="file"> 都毫无反应，
// 而浏览器里一切正常。必须在这里持有住。
enum WebViewDelegates {
    static let ui = WebViewUIDelegate()
    static var nav: WebViewNavigationDelegate?
}

// MARK: - WKWebView 网络错误处理

final class WebViewNavigationDelegate: NSObject, WKNavigationDelegate {
    let failMessageSetter: (String) async -> Void
    
    init(failMessageSetter: @escaping (String) async -> Void) {
        self.failMessageSetter = failMessageSetter
    }
    
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        let msg = error.localizedDescription
        NSLog("[WebViewNavigationDelegate] 页面加载失败: \(msg)")
        Task {
            await failMessageSetter(msg)
        }
    }
    
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        let msg = error.localizedDescription
        NSLog("[WebViewNavigationDelegate] 请求失败: \(msg)")
        Task {
            await failMessageSetter(msg)
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

// 添加"显示日志"菜单项到窗口菜单
extension Scene {
    func withDebugMenu() -> some Scene {
        self
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSLog("[App] AppDelegate.applicationDidFinishLaunching")
    }

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
        NSLog("[App] bootstrap() called — step: %d", bootStep.rawValue)
        // 1. 优先用 PID 文件检测残留（比端口扫描更精确）
        if ServerManager.shared.isServerPidAlive {
            await setStep(.checking_pid)
            try? await Task.sleep(nanoseconds: 200_000_000)
            await setStep(.killing)
            ServerManager.shared.killPortOccupants()
            // 异步等待端口释放（最多等 2 秒）
            let pollDeadline = Date().addingTimeInterval(2.0)
            while ServerManager.shared.isPortBusy && Date() < pollDeadline {
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
            }
        } else if ServerManager.shared.isPortBusy {
            // PID 文件不存在, 回退到端口扫描
            await setStep(.killing)
            ServerManager.shared.killPortOccupants()
            // 异步等待端口释放（最多等 2 秒）
            let pollDeadline = Date().addingTimeInterval(2.0)
            while ServerManager.shared.isPortBusy && Date() < pollDeadline {
                try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
            }
        }

        // 2. 启动 Python
        await setStep(.startingPython)
        do {
            try await ServerManager.shared.start()
            NSLog("[App] ✓ Python 后端启动成功")
        } catch {
            await MainActor.run {
                failMessage = "无法启动 Python: \(error.localizedDescription)"
                bootStep = .none
            }
            NSLog("[App] ✗ Python 启动失败: %@", error.localizedDescription)
            return
        }

        // 3. 等健康端点响应
        await setStep(.waitingBackend)
        NSLog("[App] 等待后端就绪 (timeout: 8s)...")
        let ready = await ServerManager.shared.waitForReady(timeout: 8.0)
        NSLog("[App] 后端就绪: %d", ready ? 1 : 0)
        guard ready else {
            await MainActor.run {
                failMessage = "后端启动超时,请检查 logs/server.log"
                bootStep = .none
            }
            return
        }

        // 4. 创建 WKWebView 并加载
        await setStep(.loadingPage)
        // 仅清除 cache（不清 cookies/session），避免过度清理
        let dataStore = WKWebsiteDataStore.default()
        await dataStore.removeData(
            ofTypes: ["cache"],
            modifiedSince: Date.distantPast
        )

        await MainActor.run {
            let cfg = WKWebViewConfiguration()
            cfg.websiteDataStore = dataStore
            // 注册备份目录选择桥(前端 window.webkit.messageHandlers.pickBackupDir)
            // ⚠️ 必须创建 WKWebView 之前挂到 config(WKWebViewConfiguration 是值快照)
            let userContentController = WKUserContentController()
            cfg.userContentController = userContentController
            // ⚠️ 必须在 WKWebView 创建之前注册所有 handler（userContentController 是值快照）
            userContentController.add(CopyToClipboardHandler(webView: nil), name: "macOSCopyToClipboard")
            NSLog("[App] ✓ CopyToClipboard handler registered as 'macOSCopyToClipboard'")
            userContentController.add(BackupDirHandler(), name: "pickBackupDir")
            userContentController.add(PickFileHandler(), name: "macOSPickFile")
            // 原生图片选择（借出人/归还人/申购名称/故障信息等所有 📷 都走这里）
            userContentController.add(PickImageHandler(), name: "macOSPickImage")
            NSLog("[App] ✓ PickImage handler registered as 'macOSPickImage'")
            let wv = WKWebView(frame: .zero, configuration: cfg)
            // WKNavigationDelegate: 捕获网络错误，显示友好的错误提示
            // ⚠️ navigationDelegate 也是 weak，必须存到静态变量里保活
            let navDel = WebViewNavigationDelegate(failMessageSetter: { msg in
                await MainActor.run {
                    self.failMessage = "网络连接失败: \(msg)\n请确认后端服务正在运行。"
                    self.bootStep = .none
                }
            })
            WebViewDelegates.nav = navDel
            wv.navigationDelegate = navDel
            // WKUIDelegate: 让所有 <input type="file"> 也能弹原生选择器(兜底)
            // ⚠️ uiDelegate 同样是 weak —— 直接写 WebViewUIDelegate() 会被立刻释放，
            //    导致 App 里点图片永远没反应（浏览器正常）。必须用静态实例。
            wv.uiDelegate = WebViewDelegates.ui
            let req = URLRequest(url: URL(string: "http://127.0.0.1:8765")!)
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
