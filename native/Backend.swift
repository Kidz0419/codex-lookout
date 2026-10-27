import AppKit
import Combine
import CryptoKit
import Foundation

struct PulseDiagnosis: Codable {
    let code: String
    let label: String
    let severity: String
    let summary: String
}

struct PulseTool: Codable {
    let name: String
    let elapsedSeconds: Double?
}

struct PulseStage: Codable {
    let code: String
    let label: String
    let evidence: String?
    let observedAt: String?
    let elapsedSeconds: Double?
}

struct PulseHealth: Codable {
    let level: String
    let label: String
    let summary: String
    let lastProgressAt: String?
    let silenceSeconds: Double?
}

struct PulseTask: Codable, Identifiable {
    let id: String
    let title: String
    let parentId: String?
    let status: String
    let phase: String
    let elapsedSeconds: Double?
    let silenceSeconds: Double?
    let diagnosis: PulseDiagnosis
    let currentTool: PulseTool?
    let agentPath: String?
    let updatedAt: String?
    let lastEventAt: String?
    let turnStartedAt: String?
    var stage: PulseStage? = nil
    var health: PulseHealth? = nil
}

struct PulseSource: Codable {
    let name: String
    let available: Bool
    let note: String?
}

struct PulseSnapshot: Codable {
    let generatedAt: String
    let tasks: [PulseTask]
    let sources: [PulseSource]
    let collectorError: String?
}

struct PulseGroup: Identifiable {
    let id: String
    let task: PulseTask
    let children: [PulseTask]

    var primaryTask: PulseTask {
        if ["running", "unknown", "failed"].contains(task.status) { return task }
        return children.sorted { lhs, rhs in
            let leftPriority = Self.attentionPriority(lhs)
            let rightPriority = Self.attentionPriority(rhs)
            if leftPriority != rightPriority { return leftPriority > rightPriority }
            let leftElapsed = lhs.elapsedSeconds ?? 0
            let rightElapsed = rhs.elapsedSeconds ?? 0
            return leftElapsed == rightElapsed ? lhs.id < rhs.id : leftElapsed > rightElapsed
        }.first ?? task
    }

    private static func attentionPriority(_ task: PulseTask) -> Int {
        if task.status == "failed" || task.health?.level == "error" { return 3 }
        if task.status == "unknown" || task.health?.level == "unknown" { return 2 }
        if task.health?.level == "watch" || ["warning", "error"].contains(task.diagnosis.severity) || task.diagnosis.code == "long_tool" { return 1 }
        return 0
    }
}

@MainActor
final class PulseModel: ObservableObject {
    @Published var snapshot: PulseSnapshot?
    @Published var connectionState = "正在读取任务"
    @Published var isStale = true

    private var helper: Process?
    private var output: Pipe?
    private var buffer = Data()
    private var watchdog: Timer?
    private var restartWork: DispatchWorkItem?
    private var lastReceivedAt: Date?
    private var helperStartedAt: Date?
    private var stopping = false
    private var helperFailed = false
    private var dashboard: Process?
    private var dashboardStarting = false
    private var retryDelay: TimeInterval = 2
    private var demoMode = false
    private var preferencesObserver: NSObjectProtocol?
    private var dashboardSourceID: String?

    private var freshnessWindow: TimeInterval { max(12, LookoutPreferences.shared.refreshInterval * 3) }

    static func backendCommand(_ mode: String, arguments: [String] = []) -> (URL, [String])? {
        let frozen = backendURL.appendingPathComponent("pulse-backend")
        if FileManager.default.isExecutableFile(atPath: frozen.path) { return (frozen, [mode] + arguments) }
        guard let python = pythonURL else { return nil }
        let bundled = backendURL.appendingPathComponent(mode == "monitor" ? "monitor.py" : "server.py")
        let script = FileManager.default.fileExists(atPath: bundled.path) ? bundled : backendURL.deletingLastPathComponent().appendingPathComponent("server.py")
        return (python, [script.path] + arguments)
    }

    private var helperEnvironment: [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CODEX_HOME"] = LookoutPreferences.shared.resolvedCodexHome.path
        // A frozen helper must not inherit a developer's Python injection paths.
        env.removeValue(forKey: "PYTHONHOME")
        env.removeValue(forKey: "PYTHONPATH")
        return env
    }

    private var sourceID: String {
        var home = LookoutPreferences.shared.resolvedCodexHome.resolvingSymlinksInPath().standardizedFileURL
        let nested = home.appendingPathComponent(".codex")
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: nested.path, isDirectory: &isDirectory), isDirectory.boolValue { home = nested }
        let key = home.resolvingSymlinksInPath().standardizedFileURL.path + "\n" + String(LookoutPreferences.shared.taskLimit)
        return SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func restartForPreferences() {
        guard !demoMode else { return }
        // Discard data from the old folder immediately; never label it as the new source.
        stop()
        snapshot = nil
        lastReceivedAt = nil
        helperFailed = false
        retryDelay = 2
        isStale = true
        connectionState = "正在读取任务"
        start()
    }

    var runningTasks: [PulseTask] { snapshot?.tasks.filter { $0.status == "running" } ?? [] }
    var attentionTasks: [PulseTask] {
        let now = Date()
        return snapshot?.tasks.filter { task in
            if task.status == "running" {
                if let health = task.health { return ["watch", "error", "unknown"].contains(health.level) }
                return ["warning", "error"].contains(task.diagnosis.severity) || task.diagnosis.code == "long_tool"
            }
            return Self.isRecentAttentionTask(task, now: now)
        } ?? []
    }

    nonisolated static func groups(in tasks: [PulseTask]) -> [PulseGroup] {
        grouped(tasks, including: { $0.status == "running" })
    }

    nonisolated static func displayGroups(in tasks: [PulseTask], now: Date = Date()) -> [PulseGroup] {
        grouped(tasks, including: { $0.status == "running" || isRecentAttentionTask($0, now: now) })
    }

    nonisolated private static func isRecentAttentionTask(_ task: PulseTask, now: Date) -> Bool {
        guard ["unknown", "failed"].contains(task.status),
              let stamp = date(task.lastEventAt ?? task.updatedAt) else { return false }
        let age = now.timeIntervalSince(stamp)
        return age >= 0 && age < 24 * 3600
    }

    nonisolated private static func grouped(_ tasks: [PulseTask], including include: (PulseTask) -> Bool) -> [PulseGroup] {
        let byID = Dictionary(tasks.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var activeGroups: [String: [PulseTask]] = [:]
        for task in byID.values where include(task) {
            var current = task
            var path: [String] = []
            var seen: [String: Int] = [:]
            let rootID: String
            while true {
                if let cycleStart = seen[current.id] {
                    // Every member or descendant of a bad parent cycle uses one stable root.
                    rootID = path[cycleStart...].min() ?? current.id
                    break
                }
                seen[current.id] = path.count
                path.append(current.id)
                guard let parent = current.parentId, let candidate = byID[parent] else {
                    rootID = current.id
                    break
                }
                current = candidate
            }
            activeGroups[rootID, default: []].append(task)
        }
        return activeGroups.compactMap { id, active -> PulseGroup? in
            guard let root = byID[id] else { return nil }
            return PulseGroup(id: id, task: root, children: active.filter { $0.id != id }.sorted { $0.id < $1.id })
        }.sorted {
            let lhs = $0.task.turnStartedAt ?? $0.task.updatedAt ?? ""
            let rhs = $1.task.turnStartedAt ?? $1.task.updatedAt ?? ""
            return lhs == rhs ? $0.id < $1.id : lhs > rhs
        }
    }

    var groups: [PulseGroup] { Self.groups(in: snapshot?.tasks ?? []) }
    var displayGroups: [PulseGroup] { Self.displayGroups(in: snapshot?.tasks ?? []) }
    var runningCount: Int { groups.count }

    nonisolated static func date(_ value: String?) -> Date? {
        guard let value else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: value) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value)
    }

    static var backendURL: URL {
        if let bundled = Bundle.main.resourceURL?.appendingPathComponent("backend"),
           (FileManager.default.fileExists(atPath: bundled.appendingPathComponent("monitor.py").path) || FileManager.default.isExecutableFile(atPath: bundled.appendingPathComponent("pulse-backend").path)) {
            return bundled
        }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent()
    }

    static var pythonURL: URL? {
        ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"].first(where: {
            FileManager.default.isExecutableFile(atPath: $0)
        }).map { URL(fileURLWithPath: $0) }
    }

    func start() {
        guard watchdog == nil else { return }
        preferencesObserver = NotificationCenter.default.addObserver(forName: .lookoutPreferencesChanged, object: nil, queue: .main) { [weak self] note in
            guard let key = note.userInfo?["key"] as? String, ["codexHomePath", "refreshInterval", "taskLimit"].contains(key) else { return }
            Task { @MainActor in self?.restartForPreferences() }
        }
        stopping = false
        startHelper()
        watchdog = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.updateFreshness() }
        }
    }

    func stop() {
        stopping = true
        if let observer = preferencesObserver { NotificationCenter.default.removeObserver(observer) }
        preferencesObserver = nil
        dashboardStarting = false
        dashboardSourceID = nil
        watchdog?.invalidate()
        watchdog = nil
        restartWork?.cancel()
        restartWork = nil
        output?.fileHandleForReading.readabilityHandler = nil
        if helper?.isRunning == true { helper?.terminate() }
        helper = nil
        helperStartedAt = nil
        if dashboard?.isRunning == true { dashboard?.terminate() }
        dashboard = nil
    }

    func refresh() {
        guard !demoMode else { return }
        let lastActivity = [lastReceivedAt, helperStartedAt].compactMap { $0 }.max()
        if isStale && helper?.isRunning == true && lastActivity.map({ Date().timeIntervalSince($0) > freshnessWindow }) == true {
            helper?.terminate()
        } else if helper?.isRunning != true { startHelper() }
        updateFreshness()
    }

    private func startHelper() {
        guard !stopping, !demoMode, helper?.isRunning != true else { return }
        restartWork?.cancel()
        let prefs = LookoutPreferences.shared
        guard let (executable, arguments) = Self.backendCommand("monitor", arguments: ["--interval", String(prefs.refreshInterval), "--limit", String(prefs.taskLimit)]) else {
            connectionState = "找不到采集器，请重新安装应用或安装 Python 3"
            isStale = true
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = executable
        process.arguments = arguments
        process.currentDirectoryURL = Self.backendURL
        process.environment = helperEnvironment
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        buffer.removeAll(keepingCapacity: true)
        pipe.fileHandleForReading.readabilityHandler = { [weak self, weak process] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let process else { return }
                self?.receive(data, from: process)
            }
        }
        process.terminationHandler = { [weak self] ended in
            DispatchQueue.main.async {
                guard let self, !self.stopping, self.helper === ended else { return }
                self.helperFailed = true
                self.isStale = true
                self.connectionState = "读取中断，正在重新连接"
                self.scheduleRestart()
            }
        }
        helper = process
        output = pipe
        do {
            try process.run()
            helperStartedAt = Date()
        }
        catch {
            pipe.fileHandleForReading.readabilityHandler = nil
            helper = nil
            helperFailed = true
            connectionState = "无法启动本机采集器"
            isStale = true
            scheduleRestart()
        }
    }

    private func scheduleRestart() {
        guard !stopping else { return }
        restartWork?.cancel()
        let work = DispatchWorkItem { [weak self] in self?.startHelper() }
        restartWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + retryDelay, execute: work)
        retryDelay = min(30, retryDelay * 2)
    }

    private func receive(_ data: Data, from process: Process) {
        guard !stopping, helper === process, process.isRunning else { return }
        buffer.append(data)
        if buffer.count > 8 * 1024 * 1024 {
            buffer.removeAll()
            helperFailed = true
            connectionState = "采集数据过大，等待下一次更新"
            isStale = true
            return
        }
        while let newline = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<newline])
            buffer.removeSubrange(...newline)
            do {
                let value = try JSONDecoder().decode(PulseSnapshot.self, from: line)
                snapshot = value
                lastReceivedAt = Date()
                helperFailed = value.collectorError != nil
                retryDelay = 2
                updateFreshness()
            } catch {
                helperFailed = true
                connectionState = "采集暂不可用，保留上次状态"
                isStale = true
            }
        }
    }

    private func updateFreshness() {
        guard !demoMode else { return }
        guard let snapshot, let received = lastReceivedAt else {
            isStale = true
            if !helperFailed, let started = helperStartedAt, Date().timeIntervalSince(started) > freshnessWindow {
                connectionState = "读取任务超时，可从菜单刷新重连"
            }
            return
        }
        let sourceMissing = !snapshot.sources.contains { $0.name == "state_5.sqlite" && $0.available }
        let timestamp = Self.date(snapshot.generatedAt)
        let expired = timestamp == nil || Date().timeIntervalSince(timestamp!) > freshnessWindow || Date().timeIntervalSince(timestamp!) < -2 || Date().timeIntervalSince(received) > freshnessWindow
        isStale = helperFailed || expired || sourceMissing
        if sourceMissing { connectionState = "任务数据源不可用" }
        else if helperFailed { connectionState = "采集暂不可用，显示上次状态" }
        else if expired { connectionState = "状态已过期，等待更新" }
        else { connectionState = "本机任务 · 每 \(Int(LookoutPreferences.shared.refreshInterval)) 秒更新" }
    }

    func openTask(_ id: String) {
        guard UUID(uuidString: id) != nil, let url = URL(string: "codex://threads/\(id)") else { return }
        NSWorkspace.shared.open(url)
    }

    func openDashboard() {
        guard !dashboardStarting else { return }
        dashboardStarting = true
        dashboardSourceID = sourceID
        probeDashboard(remaining: 20, mayStart: true)
    }

    private func probeDashboard(remaining: Int, mayStart: Bool) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:4318/api/health")!)
        request.timeoutInterval = 1
        request.cachePolicy = .reloadIgnoringLocalCacheData
        let expectedSource = dashboardSourceID
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            let object = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let isOurs = object?["service"] as? String == "codex-lookout" && object?["sourceId"] as? String == expectedSource
            DispatchQueue.main.async {
                guard let self, !self.stopping, self.dashboardSourceID == expectedSource else { return }
                if isOurs {
                    self.dashboardStarting = false
                    NSWorkspace.shared.open(URL(string: "http://127.0.0.1:4318")!)
                } else if remaining == 0 || (error == nil && response != nil) {
                    self.dashboardStarting = false
                    self.showDashboardError()
                } else if mayStart, let (executable, arguments) = Self.backendCommand("server", arguments: ["--port", "4318", "--limit", String(LookoutPreferences.shared.taskLimit)]) {
                    let process = Process()
                    process.executableURL = executable
                    process.arguments = arguments
                    process.standardOutput = FileHandle.nullDevice
                    process.standardError = FileHandle.nullDevice
                    process.environment = self.helperEnvironment
                    do { try process.run(); self.dashboard = process }
                    catch { self.dashboardStarting = false; self.showDashboardError(); return }
                    self.retryDashboard(remaining: remaining - 1)
                } else { self.retryDashboard(remaining: remaining - 1) }
            }
        }.resume()
    }

    private func retryDashboard(remaining: Int) {
        let expectedSource = dashboardSourceID
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { [weak self] in
            guard let self, self.dashboardStarting, self.dashboardSourceID == expectedSource else { return }
            self.probeDashboard(remaining: remaining, mayStart: false)
        }
    }

    private func showDashboardError() {
        let alert = NSAlert()
        alert.messageText = "暂时无法打开完整面板"
        alert.informativeText = "本机 4318 端口可能被其他程序或使用另一数据目录的面板占用。请关闭旧面板后重试。顶部会话监测仍可独立运行。"
        alert.addButton(withTitle: "知道了")
        alert.runModal()
    }

    func loadFixture(_ url: URL) throws {
        demoMode = true
        snapshot = try JSONDecoder().decode(PulseSnapshot.self, from: Data(contentsOf: url))
        isStale = false
        connectionState = "测试快照 · 非实时"
    }
}
