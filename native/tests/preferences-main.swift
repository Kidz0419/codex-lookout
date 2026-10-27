import Foundation

// Separate executable; never reads or writes the app's standard preference domain.
@main
struct LookoutPreferencesChecks {
    @MainActor static func main() {
        let suiteName = "codex-lookout.tests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: suiteName) else { fatalError("Cannot create test preference suite") }
        defaults.removePersistentDomain(forName: suiteName)
        defer { defaults.removePersistentDomain(forName: suiteName) }
        var failures = 0
        var checks = 0
        func check(_ condition: Bool, _ name: String) {
            checks += 1
            if condition { print("PASS: \(name)") }
            else { print("FAIL: \(name)"); failures += 1 }
        }

        let fresh = LookoutPreferences(defaults: defaults, environment: [:])
        check(fresh.refreshInterval == 2 && fresh.taskLimit == 200 && fresh.placement == .automatic,
              "empty preferences select supported monitoring defaults")
        check(!fresh.hideSessionTitles && !fresh.hasCompletedOnboarding && fresh.codexHomePath.isEmpty,
              "first run is incomplete without changing privacy or source defaults")
        check(fresh.resolvedCodexHome == FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex", isDirectory: true),
              "unset source resolves to the current user's .codex directory")

        defaults.set("not a number", forKey: "lookout.refreshInterval")
        defaults.set(-600, forKey: "lookout.taskLimit")
        defaults.set("missing-screen-mode", forKey: "lookout.placement")
        let corrupt = LookoutPreferences(defaults: defaults, environment: [:])
        check(corrupt.refreshInterval == 2 && corrupt.taskLimit == 200 && corrupt.placement == .automatic,
              "unsupported saved values fall back to supported defaults")
        defaults.set(3, forKey: "lookout.refreshInterval")
        defaults.set(201, forKey: "lookout.taskLimit")
        let unsupported = LookoutPreferences(defaults: defaults, environment: [:])
        check(unsupported.refreshInterval == 2 && unsupported.taskLimit == 200,
              "positive but unsupported intervals and limits also fall back")

        let inherited = LookoutPreferences(defaults: defaults, environment: ["CODEX_HOME": " /tmp/lookout-inherited "])
        check(inherited.resolvedCodexHome.path == "/tmp/lookout-inherited", "CODEX_HOME is used when custom source is unset")
        inherited.codexHomePath = " /tmp/lookout-custom/../lookout-selected "
        check(inherited.resolvedCodexHome.path == "/tmp/lookout-selected", "custom directory takes precedence and is normalized")
        inherited.codexHomePath = "~/lookout-preferences-test"
        check(inherited.resolvedCodexHome.path == FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("lookout-preferences-test").path,
              "custom directory expands a leading tilde")
        inherited.codexHomePath = "  "
        check(inherited.resolvedCodexHome.path == "/tmp/lookout-inherited", "blank custom directory returns to inherited source")

        let task = PulseTask(id: "12345678-1234-1234-1234-123456789012", title: "Private project\nFull private prompt", parentId: nil,
                             status: "running", phase: "model", elapsedSeconds: 10, silenceSeconds: 1,
                             diagnosis: PulseDiagnosis(code: "active", label: "Active", severity: "ok", summary: "Progress"),
                             currentTool: nil, agentPath: "/root/private-client-name", updatedAt: nil, lastEventAt: nil, turnStartedAt: nil)
        inherited.hideSessionTitles = false
        check(inherited.title(for: task) == "Private project" && inherited.title(for: task, child: true) == "private-client-name",
              "visible titles use only the first title line and child display name")
        inherited.hideSessionTitles = true
        check(inherited.title(for: task) == "会话 · 12345678" && inherited.title(for: task, child: true) == "子任务 · 12345678",
              "privacy masks both root titles and child agent names")

        inherited.codexHomePath = "/tmp/lookout-persisted"
        inherited.refreshInterval = 10
        inherited.taskLimit = 500
        inherited.placement = .mainDisplay
        inherited.hasCompletedOnboarding = true
        let reloaded = LookoutPreferences(defaults: defaults, environment: [:])
        check(reloaded.codexHomePath == "/tmp/lookout-persisted" && reloaded.refreshInterval == 10 && reloaded.taskLimit == 500,
              "monitoring settings survive a fresh preference instance")
        check(reloaded.placement == .mainDisplay && reloaded.hideSessionTitles && reloaded.hasCompletedOnboarding,
              "display, privacy and completed onboarding survive a fresh instance")

        var observedKey: String?
        var observedObject: LookoutPreferences?
        let observer = NotificationCenter.default.addObserver(forName: .lookoutPreferencesChanged, object: nil, queue: nil) { notification in
            observedKey = notification.userInfo?["key"] as? String
            observedObject = notification.object as? LookoutPreferences
        }
        reloaded.refreshInterval = 5
        NotificationCenter.default.removeObserver(observer)
        check(observedKey == "refreshInterval" && observedObject === reloaded,
              "preference notifications identify the changed setting and instance")

        print("\(checks) isolated preference checks \(failures == 0 ? "passed" : "completed with failures")")
        exit(failures == 0 ? 0 : 1)
    }
}
