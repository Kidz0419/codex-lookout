import AppKit
import Combine
import Foundation
import ServiceManagement
import SwiftUI

extension Notification.Name {
    static let lookoutPreferencesChanged = Notification.Name("LookoutPreferencesChanged")
}

enum LookoutPlacement: String, CaseIterable, Identifiable {
    case automatic
    case mainDisplay
    var id: String { rawValue }
    var label: String { self == .automatic ? "优先使用刘海屏幕" : "使用主显示器" }
}

@MainActor
final class LookoutPreferences: ObservableObject {
    static let shared = LookoutPreferences()
    private let defaults: UserDefaults
    private let environment: [String: String]

    @Published var codexHomePath: String { didSet { persist(codexHomePath, key: "codexHomePath") } }
    @Published var refreshInterval: Double { didSet { persist(refreshInterval, key: "refreshInterval") } }
    @Published var taskLimit: Int { didSet { persist(taskLimit, key: "taskLimit") } }
    @Published var placement: LookoutPlacement { didSet { persist(placement.rawValue, key: "placement") } }
    @Published var hideSessionTitles: Bool { didSet { persist(hideSessionTitles, key: "hideSessionTitles") } }
    @Published var hasCompletedOnboarding: Bool { didSet { persist(hasCompletedOnboarding, key: "hasCompletedOnboarding") } }
    @Published private(set) var loginStatus = SMAppService.Status.notRegistered
    @Published private(set) var loginError: String?

    init(defaults: UserDefaults = .standard, environment: [String: String] = ProcessInfo.processInfo.environment) {
        self.defaults = defaults
        self.environment = environment
        codexHomePath = defaults.string(forKey: "lookout.codexHomePath") ?? ""
        let interval = defaults.double(forKey: "lookout.refreshInterval")
        refreshInterval = [2.0, 5.0, 10.0].contains(interval) ? interval : 2
        let limit = defaults.integer(forKey: "lookout.taskLimit")
        taskLimit = [100, 200, 500].contains(limit) ? limit : 200
        placement = LookoutPlacement(rawValue: defaults.string(forKey: "lookout.placement") ?? "") ?? .automatic
        hideSessionTitles = defaults.bool(forKey: "lookout.hideSessionTitles")
        hasCompletedOnboarding = defaults.bool(forKey: "lookout.hasCompletedOnboarding")
        refreshLoginStatus()
    }

    var resolvedCodexHome: URL {
        let configured = codexHomePath.trimmingCharacters(in: .whitespacesAndNewlines)
        let inherited = environment["CODEX_HOME"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let path = configured.isEmpty ? inherited : configured
        if path.isEmpty { return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex", isDirectory: true) }
        return URL(fileURLWithPath: NSString(string: path).expandingTildeInPath, isDirectory: true).standardizedFileURL
    }

    var hasReadableDatabase: Bool {
        let nested = resolvedCodexHome.appendingPathComponent(".codex", isDirectory: true)
        var isDirectory: ObjCBool = false
        let hasNested = FileManager.default.fileExists(atPath: nested.path, isDirectory: &isDirectory) && isDirectory.boolValue
        let home = hasNested ? nested : resolvedCodexHome
        return FileManager.default.isReadableFile(atPath: home.appendingPathComponent("state_5.sqlite").path)
    }

    private func persist(_ value: Any, key: String) {
        defaults.set(value, forKey: "lookout.\(key)")
        NotificationCenter.default.post(name: .lookoutPreferencesChanged, object: self, userInfo: ["key": key])
    }

    func chooseCodexHome() {
        let picker = NSOpenPanel()
        picker.title = "选择 Codex 数据目录"
        picker.message = "通常是用户目录中的 .codex 文件夹。Lookout 仅以只读方式读取任务记录。"
        picker.prompt = "使用此目录"
        picker.canChooseDirectories = true
        picker.canChooseFiles = false
        picker.allowsMultipleSelection = false
        picker.showsHiddenFiles = true
        picker.canCreateDirectories = false
        picker.directoryURL = resolvedCodexHome
        if let window = NSApp.keyWindow {
            picker.beginSheetModal(for: window) { [weak self] result in
                guard result == .OK, let url = picker.url else { return }
                MainActor.assumeIsolated { self?.codexHomePath = url.path }
            }
        } else if picker.runModal() == .OK, let url = picker.url { codexHomePath = url.path }
    }

    func refreshLoginStatus() {
        loginStatus = SMAppService.mainApp.status
    }

    func setLaunchAtLogin(_ enabled: Bool) {
        loginError = nil
        do {
            if enabled {
                if SMAppService.mainApp.status != .enabled { try SMAppService.mainApp.register() }
            } else if SMAppService.mainApp.status != .notRegistered {
                try SMAppService.mainApp.unregister()
            }
        } catch {
            loginError = "未能\(enabled ? "开启" : "关闭")登录时启动：\(error.localizedDescription)"
        }
        refreshLoginStatus()
    }

    func title(for task: PulseTask, child: Bool = false) -> String {
        if hideSessionTitles { return "\(child ? "子任务" : "会话") · \(task.id.prefix(8))" }
        if child, let name = task.agentPath?.split(separator: "/").last { return String(name) }
        let title = task.title.split(whereSeparator: \.isNewline).first.map(String.init)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return title.isEmpty ? "未命名会话" : title
    }
}

@MainActor
final class LookoutWindows: ObservableObject {
    static let shared = LookoutWindows()
    @Published var settingsSection = "general"
    private var settingsWindow: NSWindow?
    private var welcomeWindow: NSWindow?
    var onBegin: (() -> Void)?

    func showSettings(section: String = "general") {
        settingsSection = section
        LookoutPreferences.shared.refreshLoginStatus()
        if settingsWindow == nil {
            settingsWindow = makeWindow(title: "Codex Lookout 设置", size: NSSize(width: 560, height: 620))
            settingsWindow?.contentView = NSHostingView(rootView: LookoutSettingsView(windows: self))
        }
        bringForward(settingsWindow)
    }

    func showWelcome() {
        if welcomeWindow == nil {
            welcomeWindow = makeWindow(title: "欢迎使用 Codex Lookout", size: NSSize(width: 540, height: 570))
            welcomeWindow?.contentView = NSHostingView(rootView: LookoutWelcomeView {
                LookoutPreferences.shared.hasCompletedOnboarding = true
                self.welcomeWindow?.close()
                self.onBegin?()
            })
        }
        bringForward(welcomeWindow)
    }

    func close() {
        settingsWindow?.close()
        welcomeWindow?.close()
    }

    private func makeWindow(title: String, size: NSSize) -> NSWindow {
        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size), styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = title
        window.isReleasedWhenClosed = false
        window.center()
        return window
    }

    private func bringForward(_ window: NSWindow?) {
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }
}

private struct LookoutSectionTitle: View {
    let title: String
    var body: some View { Text(title).font(.system(size: 13, weight: .semibold)) }
}

@MainActor
private struct LookoutDataFolder: View {
    @ObservedObject var preferences = LookoutPreferences.shared
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Label(preferences.hasReadableDatabase ? "已找到本机 Codex 记录" : "尚未找到 Codex 记录", systemImage: preferences.hasReadableDatabase ? "checkmark.circle" : "exclamationmark.circle")
                    .foregroundStyle(preferences.hasReadableDatabase ? Color(red: 0.14, green: 0.41, blue: 0.32) : .secondary)
                Spacer()
                Button("选择目录…") { preferences.chooseCodexHome() }
            }
            Text(preferences.resolvedCodexHome.path).font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
            if !preferences.hasReadableDatabase {
                Text("先在 Codex 中创建一个本机任务，或选择已有数据目录。记录出现后会自动更新。")
                    .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
            if !preferences.codexHomePath.isEmpty {
                Button("恢复默认目录") { preferences.codexHomePath = "" }.font(.system(size: 12))
            }
        }
    }
}

@MainActor
private struct LookoutSettingsView: View {
    @ObservedObject var windows: LookoutWindows
    @ObservedObject var preferences = LookoutPreferences.shared

    var body: some View {
        TabView(selection: $windows.settingsSection) {
            Form {
                Section {
                    LookoutDataFolder()
                    Picker("刷新间隔", selection: $preferences.refreshInterval) {
                        ForEach([2.0, 5.0, 10.0], id: \.self) { Text("\(Int($0)) 秒").tag($0) }
                    }
                    Picker("最近未归档任务", selection: $preferences.taskLimit) {
                        ForEach([100, 200, 500], id: \.self) { Text("\($0) 个").tag($0) }
                    }
                } header: { LookoutSectionTitle(title: "监测") }
                Section {
                    Picker("显示位置", selection: $preferences.placement) {
                        ForEach(LookoutPlacement.allCases) { Text($0.label).tag($0) }
                    }
                    Toggle("在悬浮窗中隐藏会话标题", isOn: $preferences.hideSessionTitles)
                    Text("隐藏后以会话 ID 显示。仅影响原生悬浮窗；网页观测台仍会显示标题。")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                } header: { LookoutSectionTitle(title: "显示") }
                Section {
                    Toggle("登录 Mac 时启动", isOn: Binding(
                        get: { preferences.loginStatus == .enabled || preferences.loginStatus == .requiresApproval },
                        set: { preferences.setLaunchAtLogin($0) }
                    ))
                    if preferences.loginStatus == .requiresApproval {
                        Text("已请求启动，但还需要在系统设置中允许。")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                        Button("打开登录项设置…") { SMAppService.openSystemSettingsLoginItems() }
                    } else if preferences.loginStatus == .notFound {
                        Text("请将完整的 Codex Lookout.app 放到“应用程序”文件夹后再开启。")
                            .font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                    if let error = preferences.loginError {
                        Text(error).font(.system(size: 12)).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
                    }
                } header: { LookoutSectionTitle(title: "启动") }
                Text("设置会立即保存到本机。Lookout 不会修改或中断 Codex 任务。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
            .formStyle(.grouped)
            .tabItem { Label("通用", systemImage: "slider.horizontal.3") }.tag("general")
            LookoutAboutView().tabItem { Label("关于与帮助", systemImage: "info.circle") }.tag("about")
        }
        .padding(16)
        .frame(width: 560, height: 620)
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            preferences.refreshLoginStatus()
        }
    }
}

@MainActor
private struct LookoutWelcomeView: View {
    let begin: () -> Void
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            HStack(alignment: .center, spacing: 16) {
                Image(systemName: "binoculars").font(.system(size: 36, weight: .regular)).foregroundStyle(Color(red: 0.14, green: 0.29, blue: 0.38))
                VStack(alignment: .leading, spacing: 5) {
                    Text("Codex Lookout").font(.system(size: 25, weight: .semibold))
                    Text("瞭望台 · 让任务进展看得见").font(.system(size: 13)).foregroundStyle(.secondary)
                }
            }
            Text("把鼠标移到屏幕顶部，就能看到哪些会话在运行、最近发生了什么，以及哪里值得留意。")
                .font(.system(size: 15)).lineSpacing(5).fixedSize(horizontal: false, vertical: true)
            VStack(alignment: .leading, spacing: 14) {
                Label("绿色：近期有进展；黄色：有异常或长时间无进展。", systemImage: "circle.lefthalf.filled")
                Label("点击会话回到 Codex，移开鼠标收起。", systemImage: "cursorarrow")
                Label("只读本机记录，无需摄像头或辅助功能权限。", systemImage: "lock")
            }.font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
            Divider()
            LookoutDataFolder()
            Text("记录可能延迟。没有新事件不代表卡死；连接错误也无法区分本地网络和上游故障。")
                .font(.system(size: 12)).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            HStack {
                Button("调整设置…") { LookoutWindows.shared.showSettings() }
                Spacer()
                Button("开始使用", action: begin).keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
            }
        }.padding(30).frame(width: 540, height: 570)
    }
}

@MainActor
private struct LookoutAboutView: View {
    private var version: String { Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.1.0" }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 13) {
                    Image(systemName: "binoculars").font(.system(size: 30)).foregroundStyle(Color(red: 0.14, green: 0.29, blue: 0.38))
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Codex Lookout").font(.system(size: 22, weight: .semibold))
                        Text("Codex 会话健康瞭望台 · 版本 \(version)").font(.system(size: 12)).foregroundStyle(.secondary)
                    }
                }
                Text("鼠标移到顶部展开列表，点击会话打开 Codex。菜单栏图标提供刷新、设置与退出。")
                    .font(.system(size: 13)).fixedSize(horizontal: false, vertical: true)
                Divider()
                VStack(alignment: .leading, spacing: 10) {
                    LookoutSectionTitle(title: "如何理解状态")
                    Text("阶段来自本机事件：最近的推理、输出、工具执行、等待和压缩记录。它们描述最近可见的活动，不代表模型此刻的内部状态。")
                    Text("健康度同时看进展和异常证据。长时间无新事件只提示留意；明确的连接错误会提示连接问题，但不能判定是本地网络还是上游服务。")
                    Text("无精确流式数据时，不推算实时 token 速度、完成百分比或剩余时间。灰色表示等待、未知或当前无运行任务。")
                }.font(.system(size: 13)).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
                VStack(alignment: .leading, spacing: 10) {
                    LookoutSectionTitle(title: "隐私与覆盖范围")
                    Text("本地处理，无遥测，不读取认证文件；只提取状态与时间信息，不展示完整提示词、思考内容和工具输出。会话标题可能包含私人信息，可在设置中隐藏。")
                    Text("本版支持 macOS 上可读取的 Codex 本机任务记录。远端任务、未落盘事件和未知数据格式无法完整观察；数据不可用时会明确提示。")
                }.font(.system(size: 13)).lineSpacing(3).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 18) {
                    Link("开源仓库", destination: URL(string: "https://github.com/Kidz0419/codex-lookout")!)
                    Link("反馈问题", destination: URL(string: "https://github.com/Kidz0419/codex-lookout/issues")!)
                    Button("再次查看使用引导") { LookoutWindows.shared.showWelcome() }.buttonStyle(.link)
                }.font(.system(size: 12))
                Text("独立社区工具，与 OpenAI 无隶属或官方合作关系。")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }.padding(20)
        }
    }
}
