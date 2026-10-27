import AppKit
import SwiftUI
import Combine
import QuartzCore

// This window never steals keyboard focus from the application under observation.
private final class PulsePanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }

    override func accessibilityPerformRaise() -> Bool {
        orderFrontRegardless()
        return true
    }
}

@MainActor
private final class NotchPresentation: ObservableObject {
    @Published var expanded = false
    @Published var hasNotch = false
    @Published var notchInset: CGFloat = 0
    @Published var notchWidth: CGFloat = 0
}

@MainActor
final class NotchController: NSObject {
    private let model: PulseModel
    private let presentation = NotchPresentation()
    private let preferences = LookoutPreferences.shared
    private var panel: PulsePanel?
    private var statusItem: NSStatusItem?
    private var hoverTimer: Timer?
    private var subscriptions = Set<AnyCancellable>()
    private var observers: [NSObjectProtocol] = []
    private var spaceObserver: NSObjectProtocol?
    private var mouseLeftAt: Date?
    private var expansionGraceUntil: Date?
    private var screen: NSScreen?
    private var running = false
    private let expandedWidth: CGFloat = 460
    private let expandedHeight: CGFloat = 560

    init(model: PulseModel) {
        self.model = model
        super.init()
    }

    // Render the real SwiftUI panel in isolation for fixture checks. This creates
    // no status item, panel, timer or collector and never changes the live app.
    static func renderPreview(model: PulseModel, to output: URL) throws {
        let preview = NotchPresentation()
        preview.expanded = true
        let host = NSHostingView(rootView: PulseNotchView(model: model, presentation: preview))
        host.frame = NSRect(x: 0, y: 0, width: 460, height: 560)
        host.layoutSubtreeIfNeeded()
        host.displayIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
            throw NSError(domain: "CodexPulse.Preview", code: 1, userInfo: [NSLocalizedDescriptionKey: "无法创建原生预览位图。"])
        }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "CodexPulse.Preview", code: 2, userInfo: [NSLocalizedDescriptionKey: "无法编码原生预览。"])
        }
        try png.write(to: output, options: .atomic)
    }

    func start() {
        guard !running else { return }
        running = true
        let panel = PulsePanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Codex Lookout"
        panel.setAccessibilityLabel("Codex Lookout 任务监测")
        panel.level = .statusBar
        panel.isFloatingPanel = true
        panel.becomesKeyOnlyIfNeeded = true
        panel.hidesOnDeactivate = false
        panel.isReleasedWhenClosed = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.isMovable = false
        panel.acceptsMouseMovedEvents = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .transient, .ignoresCycle]
        panel.contentView = NSHostingView(rootView: PulseNotchView(model: model, presentation: presentation))
        self.panel = panel
        configureScreen()
        panel.orderFrontRegardless()
        createStatusItem()

        model.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                // objectWillChange arrives before @Published changes are applied.
                DispatchQueue.main.async { [weak self] in
                    self?.updateStatusItem()
                    if self?.presentation.expanded == true { self?.positionPanel(animated: false) }
                }
            }
            .store(in: &subscriptions)

        observers.append(NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.configureScreen() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: .lookoutPreferencesChanged, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.configureScreen() }
        })
        spaceObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.panel?.orderFrontRegardless() }
        }
        // Reading the cursor position requires neither Accessibility nor Input Monitoring.
        let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.checkHover() }
        }
        timer.tolerance = 0.025
        RunLoop.main.add(timer, forMode: .common)
        hoverTimer = timer
        updateStatusItem()
    }

    func stop() {
        guard running else { return }
        running = false
        hoverTimer?.invalidate()
        hoverTimer = nil
        subscriptions.removeAll()
        observers.forEach { NotificationCenter.default.removeObserver($0) }
        observers.removeAll()
        if let observer = spaceObserver {
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
            spaceObserver = nil
        }
        if let item = statusItem { NSStatusBar.system.removeStatusItem(item) }
        statusItem = nil
        panel?.orderOut(nil)
        panel?.close()
        panel = nil
    }

    // Menu-driven opening remains visible long enough to move from the menu to the panel.
    func setExpanded(_ value: Bool) {
        expansionGraceUntil = value ? Date().addingTimeInterval(3) : nil
        mouseLeftAt = nil
        changeExpanded(value)
    }

    private func configureScreen() {
        // NSScreen.screens.first is the primary display; NSScreen.main follows
        // the currently focused window and is not a stable placement preference.
        let primary = NSScreen.screens.first
        let preferred = preferences.placement == .automatic ? NSScreen.screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? primary : primary
        guard let target = preferred else { return }
        screen = target
        let inset = target.safeAreaInsets.top
        let left = target.auxiliaryTopLeftArea
        let right = target.auxiliaryTopRightArea
        let measuredWidth: CGFloat
        if let left, let right { measuredWidth = max(0, right.minX - left.maxX) }
        else { measuredWidth = 0 }
        // A mirrored external display may not expose the built-in screen's notch geometry.
        // Treat that as an ordinary top-center panel; never guess camera coordinates.
        presentation.hasNotch = inset > 0 && measuredWidth > 0
        presentation.notchInset = presentation.hasNotch ? inset : 0
        presentation.notchWidth = presentation.hasNotch ? measuredWidth : 0
        positionPanel(animated: false)
        updateStatusItem()
        panel?.orderFrontRegardless()
    }

    private func targetFrame() -> NSRect? {
        guard let screen else { return nil }
        let width = presentation.expanded ? expandedWidth : presentation.hasNotch ? max(230, presentation.notchWidth + 108) : 142
        let contentHeight = model.displayGroups.isEmpty ? CGFloat(145) : model.displayGroups.reduce(CGFloat(0)) { total, group in
            let children = group.children.isEmpty ? CGFloat(0) : 30 + group.children.reduce(CGFloat(0)) { $0 + pulseEstimatedRowHeight($1) }
            let contextHeight: CGFloat = group.primaryTask.id != group.task.id ? 30 : 0
            return total + pulseEstimatedRowHeight(group.primaryTask) + children + contextHeight
        }
        let noticeHeight: CGFloat = model.snapshot == nil || model.isStale ? 82 : model.attentionTasks.isEmpty ? 0 : 32
        let desiredHeight = contentHeight + 120 + presentation.notchInset + noticeHeight
        let height = presentation.expanded ? min(expandedHeight, desiredHeight, screen.frame.height - 80) : presentation.hasNotch ? max(32, presentation.notchInset + 5) : 30
        let topGap: CGFloat = presentation.hasNotch ? 0 : 4
        return NSRect(x: screen.frame.midX - width / 2, y: screen.frame.maxY - height - topGap, width: width, height: height)
    }

    private func positionPanel(animated: Bool) {
        guard let panel, let frame = targetFrame() else { return }
        if animated && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            NSAnimationContext.runAnimationGroup { context in
                context.duration = 0.16
                context.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrame(frame, display: true)
            }
        } else { panel.setFrame(frame, display: true) }
        panel.hasShadow = presentation.expanded
        panel.ignoresMouseEvents = !presentation.expanded
    }

    private func changeExpanded(_ value: Bool) {
        guard value != presentation.expanded else { return }
        presentation.expanded = value
        positionPanel(animated: true)
        updateStatusItem()
        if value { model.refresh() }
    }

    private func checkHover() {
        guard let panel, panel.isVisible else { return }
        let isInside = panel.frame.contains(NSEvent.mouseLocation)
        if isInside {
            mouseLeftAt = nil
            expansionGraceUntil = nil
            if !presentation.expanded { changeExpanded(true) }
            return
        }
        guard presentation.expanded else { return }
        if let grace = expansionGraceUntil, grace > Date() { return }
        if mouseLeftAt == nil { mouseLeftAt = Date() }
        if let since = mouseLeftAt, Date().timeIntervalSince(since) >= 0.3 {
            mouseLeftAt = nil
            changeExpanded(false)
        }
    }

    private func createStatusItem() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        item.button?.image = NSImage(systemSymbolName: "waveform.path", accessibilityDescription: "Codex Lookout")
        item.button?.image?.isTemplate = true
        item.button?.imagePosition = .imageLeading
        let menu = NSMenu()
        let toggle = NSMenuItem(title: "展开任务", action: #selector(togglePanel), keyEquivalent: "")
        toggle.target = self
        toggle.tag = 1
        menu.addItem(toggle)
        let open = NSMenuItem(title: "打开完整观测台", action: #selector(openDashboard), keyEquivalent: "")
        open.target = self
        menu.addItem(open)
        let refresh = NSMenuItem(title: "立即刷新", action: #selector(refreshData), keyEquivalent: "")
        refresh.target = self
        menu.addItem(refresh)
        menu.addItem(.separator())
        let settings = NSMenuItem(title: "设置…", action: #selector(openSettings), keyEquivalent: ",")
        settings.target = self
        menu.addItem(settings)
        let about = NSMenuItem(title: "关于 Codex Lookout 与帮助…", action: #selector(openAbout), keyEquivalent: "")
        about.target = self
        menu.addItem(about)
        menu.addItem(.separator())
        let displayMode = NSMenuItem(title: "顶部居中模式", action: nil, keyEquivalent: "")
        displayMode.tag = 2
        menu.addItem(displayMode)
        let privacy = NSMenuItem(title: "只读本机任务 · 无需摄像头权限", action: nil, keyEquivalent: "")
        menu.addItem(privacy)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "退出 Codex Lookout", action: #selector(quitApp), keyEquivalent: "q")
        quit.target = self
        menu.addItem(quit)
        item.menu = menu
        statusItem = item
    }

    private func updateStatusItem() {
        guard let item = statusItem else { return }
        let unavailable = model.snapshot == nil || model.isStale
        item.button?.title = unavailable ? " ?" : " \(model.runningCount)"
        let place = presentation.hasNotch ? "刘海区域" : "顶部居中模式"
        item.button?.toolTip = unavailable ? "Codex Lookout · 状态待更新 · \(place)" : "Codex Lookout · \(model.runningCount) 个会话正在运行 · \(place)"
        item.menu?.item(withTag: 1)?.title = presentation.expanded ? "收起任务" : "展开任务"
        item.menu?.item(withTag: 2)?.title = presentation.hasNotch ? "刘海区域模式" : "顶部居中模式（当前屏幕无刘海几何信息）"
    }

    @objc private func togglePanel() { setExpanded(!presentation.expanded) }
    @objc private func openDashboard() { model.openDashboard() }
    @objc private func refreshData() { model.refresh() }
    @objc private func openSettings() { setExpanded(false); LookoutWindows.shared.showSettings() }
    @objc private func openAbout() { setExpanded(false); LookoutWindows.shared.showSettings(section: "about") }
    @objc private func quitApp() { NSApplication.shared.terminate(nil) }
}

private enum PulsePalette {
    static let background = Color(red: 0.055, green: 0.065, blue: 0.063)
    static let text = Color(red: 0.94, green: 0.96, blue: 0.94)
    static let secondary = Color(red: 0.65, green: 0.70, blue: 0.67)
    static let green = Color(red: 0.46, green: 0.83, blue: 0.64)
    static let amber = Color(red: 0.96, green: 0.74, blue: 0.39)
    static let separator = Color.white.opacity(0.09)
}

private struct NotchSurface: Shape {
    var attached: Bool
    var expanded: Bool

    func path(in rect: CGRect) -> Path {
        let radius: CGFloat = expanded ? 18 : 13
        let top: CGFloat = attached ? 0 : radius
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + top, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - top, y: rect.minY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY + top), control: CGPoint(x: rect.maxX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - radius))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - radius, y: rect.maxY), control: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + radius, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.maxY - radius), control: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + top))
        path.addQuadCurve(to: CGPoint(x: rect.minX + top, y: rect.minY), control: CGPoint(x: rect.minX, y: rect.minY))
        path.closeSubpath()
        return path
    }
}

@MainActor
private struct PulseNotchView: View {
    @ObservedObject var model: PulseModel
    @ObservedObject var presentation: NotchPresentation
    @ObservedObject var preferences = LookoutPreferences.shared

    private var unavailable: Bool { model.snapshot == nil || model.isStale }
    private var needsAttention: Bool { !model.attentionTasks.isEmpty }
    private var stateColor: Color {
        if unavailable || needsAttention { return PulsePalette.amber }
        let hasActiveTask = model.runningTasks.contains { task in
            if let health = task.health { return health.level == "active" }
            return task.phase != "waiting" && task.phase != "unknown"
        }
        return hasActiveTask ? PulsePalette.green : PulsePalette.secondary
    }

    var body: some View {
        Group {
            if presentation.expanded { expandedContent }
            else { collapsedContent }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .foregroundStyle(PulsePalette.text)
        .background(PulsePalette.background)
        .clipShape(NotchSurface(attached: presentation.hasNotch, expanded: presentation.expanded))
        .environment(\.colorScheme, .dark)
        .accessibilityLabel("Codex Lookout，\(unavailable ? "状态待更新" : "\(model.runningCount) 个会话运行中")")
    }

    private var collapsedContent: some View {
        HStack(spacing: 8) {
            Image(systemName: "waveform.path")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(stateColor)
            if presentation.hasNotch {
                Spacer(minLength: presentation.notchWidth)
            } else {
                Text("Codex").font(.system(size: 12, weight: .semibold))
                Spacer(minLength: 0)
            }
            if unavailable {
                Image(systemName: "clock.badge.exclamationmark").font(.system(size: 12, weight: .medium)).foregroundStyle(PulsePalette.amber)
            } else {
                Text("\(model.runningCount)").font(.system(size: 13, weight: .semibold, design: .rounded)).monospacedDigit()
                    .foregroundStyle(stateColor)
                Circle().fill(stateColor).frame(width: 5, height: 5)
            }
        }
        .padding(.horizontal, presentation.hasNotch ? 18 : 14)
        .help(unavailable ? "状态待更新，移入查看连接状态" : "\(model.runningCount) 个主会话正在运行，移入查看")
    }

    private var expandedContent: some View {
        VStack(spacing: 0) {
            if presentation.hasNotch { Color.clear.frame(height: presentation.notchInset) }
            HStack(alignment: .center) {
                HStack(spacing: 7) {
                    Image(systemName: "waveform.path").foregroundStyle(stateColor)
                    Text("Codex Lookout").font(.system(size: 14, weight: .semibold))
                }
                Spacer()
                Text(unavailable ? "状态待更新" : "\(model.runningCount) 个会话运行中")
                    .font(.system(size: 12, weight: .medium)).foregroundStyle(stateColor)
            }
            .padding(.horizontal, 20).padding(.top, presentation.hasNotch ? 8 : 18).padding(.bottom, 15)

            if unavailable {
                HStack(alignment: .top, spacing: 9) {
                    Image(systemName: "exclamationmark.circle").foregroundStyle(PulsePalette.amber)
                    VStack(alignment: .leading, spacing: 4) {
                        Text(model.connectionState).font(.system(size: 12, weight: .medium))
                        Text(model.snapshot == nil ? "正在等待本机任务记录。" : "以下保留上次记录，运行状态可能已变化。")
                            .font(.system(size: 12)).foregroundStyle(PulsePalette.secondary)
                    }
                    Spacer(minLength: 0)
                }
                .padding(12).background(PulsePalette.amber.opacity(0.09)).clipShape(RoundedRectangle(cornerRadius: 8))
                .padding(.horizontal, 15).padding(.bottom, 12)
            } else if needsAttention {
                HStack(spacing: 7) {
                    Image(systemName: "exclamationmark.circle")
                    Text("需关注的会话已列在下方")
                    Spacer(minLength: 0)
                    Text("\(model.attentionTasks.count) 项").monospacedDigit()
                }.font(.system(size: 12)).foregroundStyle(PulsePalette.amber)
                    .padding(.horizontal, 20).padding(.bottom, 13)
            }

            Rectangle().fill(PulsePalette.separator).frame(height: 1)
            if model.displayGroups.isEmpty {
                Spacer(minLength: 20)
                VStack(spacing: 12) {
                    Image(systemName: unavailable ? "arrow.triangle.2.circlepath" : "checkmark.circle")
                        .font(.system(size: 27, weight: .light)).foregroundStyle(unavailable ? PulsePalette.amber : PulsePalette.green)
                    Text(unavailable ? "正在读取会话状态" : "当前没有运行中的会话")
                        .font(.system(size: 14, weight: .medium))
                    Text(unavailable ? "连接恢复后会自动更新。" : "开始新的 Codex 任务后，会自动出现在这里。")
                        .font(.system(size: 12)).foregroundStyle(PulsePalette.secondary).multilineTextAlignment(.center)
                }.padding(.horizontal, 30)
                Spacer(minLength: 20)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(model.displayGroups) { group in
                            PulseConversationRow(group: group, model: model)
                            Rectangle().fill(PulsePalette.separator).frame(height: 1).padding(.horizontal, 19)
                        }
                    }
                }
                .scrollIndicators(.visible)
            }

            Rectangle().fill(PulsePalette.separator).frame(height: 1)
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("每 \(Int(preferences.refreshInterval)) 秒更新 · 本机只读")
                    Text("点击会话打开 Codex")
                }.font(.system(size: 11)).foregroundStyle(PulsePalette.secondary)
                Spacer(minLength: 8)
                Button { model.refresh() } label: {
                    HStack(spacing: 5) { Image(systemName: "arrow.clockwise").font(.system(size: 11, weight: .semibold)); Text("刷新") }
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(PulsePalette.green)
                }.buttonStyle(.plain).help("刷新本机任务状态")
            }.padding(.horizontal, 20).padding(.vertical, 14)
        }
    }
}

@MainActor
private struct PulseConversationRow: View {
    let group: PulseGroup
    @ObservedObject var model: PulseModel
    @ObservedObject var preferences = LookoutPreferences.shared

    private var contextNote: String? {
        guard group.primaryTask.id != group.task.id else { return nil }
        return "主会话已结束 · 以下状态来自子任务"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            PulseTaskCard(task: group.primaryTask, title: preferences.title(for: group.task), contextNote: contextNote) {
                model.openTask(group.task.id)
            }
            if !group.children.isEmpty {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.triangle.branch").font(.system(size: 11))
                        Text("\(group.children.count) 个子任务 · \(group.children.filter { $0.status == "running" }.count) 运行中")
                    }.font(.system(size: 11, weight: .medium)).foregroundStyle(PulsePalette.secondary)
                        .padding(.leading, 15).padding(.top, 2).padding(.bottom, 4)
                    ForEach(group.children) { child in
                        PulseTaskCard(task: child, title: preferences.title(for: child, child: true), isChild: true) {
                            model.openTask(child.id)
                        }
                    }
                }.padding(.leading, 15)
            }
        }
    }
}

@MainActor
private struct PulseTaskCard: View {
    let task: PulseTask
    let title: String
    var contextNote: String? = nil
    var isChild = false
    let open: () -> Void
    @State private var hovering = false

    private var color: Color { pulseHealthColor(task) }
    private var progress: String {
        if let health = task.health {
            return health.silenceSeconds == nil ? "尚无进展记录" : pulseDuration(health.silenceSeconds)
        }
        return pulseDuration(task.silenceSeconds)
    }

    var body: some View {
        Button(action: open) {
            VStack(alignment: .leading, spacing: 9) {
                HStack(alignment: .top, spacing: 9) {
                    Circle().fill(color).frame(width: isChild ? 5 : 6, height: isChild ? 5 : 6).padding(.top, 6)
                    Text(title).font(.system(size: 13, weight: .medium)).lineLimit(2).multilineTextAlignment(.leading)
                    Spacer(minLength: 0)
                    Image(systemName: "arrow.up.right").font(.system(size: 10, weight: .medium)).foregroundStyle(PulsePalette.secondary).padding(.top, 3)
                }
                VStack(alignment: .leading, spacing: 7) {
                    if let contextNote {
                        Text(contextNote).font(.system(size: 11)).foregroundStyle(PulsePalette.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("阶段").foregroundStyle(PulsePalette.secondary)
                        Text(pulseStageLabel(task)).foregroundStyle(PulsePalette.text).fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text("健康").foregroundStyle(PulsePalette.secondary)
                        Text(task.health?.label ?? task.diagnosis.label).foregroundStyle(color).fixedSize(horizontal: false, vertical: true)
                        Spacer(minLength: 0)
                    }
                    if let tool = task.currentTool {
                        HStack(alignment: .firstTextBaseline, spacing: 12) {
                            Text("工具").foregroundStyle(PulsePalette.secondary)
                            Text(tool.name).lineLimit(1).truncationMode(.middle).foregroundStyle(PulsePalette.text)
                            Spacer(minLength: 0)
                            Text("已执行 \(pulseDuration(tool.elapsedSeconds))").monospacedDigit().foregroundStyle(PulsePalette.secondary)
                        }
                    }
                    HStack(alignment: .firstTextBaseline, spacing: 16) {
                        Text("本轮耗时 \(pulseDuration(task.elapsedSeconds))")
                        Text("\(task.health == nil ? "距新记录" : "距最近进展") \(progress)")
                        Spacer(minLength: 0)
                    }.font(.system(size: 11)).monospacedDigit().foregroundStyle(PulsePalette.secondary)
                    if pulseNeedsExplanation(task) {
                        Text(task.health?.summary ?? task.diagnosis.summary)
                            .font(.system(size: 11)).foregroundStyle(PulsePalette.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 2)
                    }
                }.font(.system(size: 12)).padding(.leading, 15)
            }.padding(.horizontal, isChild ? 15 : 19).padding(.vertical, 14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(hovering ? Color.white.opacity(0.045) : isChild ? Color.white.opacity(0.018) : .clear)
                .contentShape(Rectangle())
        }.buttonStyle(.plain)
            .help(task.health?.summary ?? task.diagnosis.summary)
            .onHover { hovering = $0 }
    }
}

private func pulseStageLabel(_ task: PulseTask) -> String {
    if let stage = task.stage { return stage.label }
    switch task.phase {
    case "tool": return "工具执行中"
    case "model": return "模型处理中"
    case "waiting": return "等待中"
    case "idle": return "已结束"
    default: return "阶段暂未确认"
    }
}

private func pulseNeedsExplanation(_ task: PulseTask) -> Bool {
    if let health = task.health { return ["watch", "error", "unknown", "waiting"].contains(health.level) }
    return ["warning", "error"].contains(task.diagnosis.severity) || task.status == "unknown"
}

private func pulseEstimatedRowHeight(_ task: PulseTask) -> CGFloat {
    let summary = task.health?.summary ?? task.diagnosis.summary
    let explanationHeight: CGFloat = pulseNeedsExplanation(task) ? CGFloat(max(1, Int(ceil(Double(summary.count) / 30))) * 16 + 9) : 0
    return 133 + (task.currentTool == nil ? 0 : 24) + explanationHeight
}

private func pulseHealthColor(_ task: PulseTask) -> Color {
    if let health = task.health {
        switch health.level {
        case "watch", "error": return PulsePalette.amber
        case "active": return PulsePalette.green
        default: return PulsePalette.secondary
        }
    }
    if ["warning", "error"].contains(task.diagnosis.severity) { return PulsePalette.amber }
    return task.status == "unknown" ? PulsePalette.secondary : PulsePalette.green
}

private func pulseDuration(_ value: Double?) -> String {
    guard let value, value.isFinite, value >= 0 else { return "—" }
    let seconds = Int(value)
    if seconds < 60 { return "\(seconds) 秒" }
    let minutes = seconds / 60
    if minutes < 60 { return "\(minutes) 分" }
    let hours = minutes / 60
    if hours < 24 { return "\(hours) 时 \(minutes % 60) 分" }
    return "\(hours / 24) 天" 
}
