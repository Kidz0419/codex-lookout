import AppKit
import Foundation

@MainActor
final class PulseAppDelegate: NSObject, NSApplicationDelegate {
    var model: PulseModel?
    var controller: NotchController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let model = PulseModel()
        let controller = NotchController(model: model)
        self.model = model
        self.controller = controller
        controller.start()
        model.start()
        LookoutWindows.shared.onBegin = { [weak controller] in controller?.setExpanded(true) }
        if CommandLine.arguments.contains("--show-settings") {
            LookoutWindows.shared.showSettings()
        } else if CommandLine.arguments.contains("--show-welcome") || !LookoutPreferences.shared.hasCompletedOnboarding {
            LookoutWindows.shared.showWelcome()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        LookoutWindows.shared.close()
        controller?.stop()
        model?.stop()
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        LookoutWindows.shared.showSettings()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main
struct PulseApplication {
    @MainActor static func main() {
        // Render the real expanded SwiftUI view off-screen for layout verification.
        // This does not launch the collector or change an existing app's windows.
        if let index = CommandLine.arguments.firstIndex(of: "--render-preview") {
            guard CommandLine.arguments.count > index + 2 else {
                fputs("Usage: --render-preview fixture.json output.png\n", stderr)
                exit(2)
            }
            _ = NSApplication.shared
            let model = PulseModel()
            do {
                try model.loadFixture(URL(fileURLWithPath: CommandLine.arguments[index + 1]))
                try NotchController.renderPreview(model: model, to: URL(fileURLWithPath: CommandLine.arguments[index + 2]))
                print("Expanded native preview rendered from fixture (not live data).")
                exit(0)
            } catch {
                fputs("Unable to render native preview.\n", stderr)
                exit(1)
            }
        }
        if CommandLine.arguments.contains("--self-check") {
            let model = PulseModel()
            model.start()
            let deadline = Date().addingTimeInterval(12)
            while model.snapshot == nil && Date() < deadline {
                RunLoop.current.run(until: Date().addingTimeInterval(0.1))
            }
            let ok = model.snapshot != nil && !model.isStale
            print("Native live collector: \(ok ? "PASS" : "FAIL"); active conversations=\(model.runningCount); tasks=\(model.snapshot?.tasks.count ?? 0)")
            model.stop()
            exit(ok ? 0 : 1)
        }
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        let delegate = PulseAppDelegate()
        app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
