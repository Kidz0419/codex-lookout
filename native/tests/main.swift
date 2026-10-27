import Foundation

var failures = 0
var checks = 0
func check(_ condition: Bool, _ name: String) {
    checks += 1
    if condition { print("PASS: \(name)") }
    else { print("FAIL: \(name)"); failures += 1 }
}

func task(_ id: String, _ status: String = "running", parent: String? = nil, start: String = "2026-10-27T12:00:00Z", elapsed: Double = 60) -> PulseTask {
    PulseTask(id: id, title: id, parentId: parent, status: status, phase: "model", elapsedSeconds: elapsed,
              silenceSeconds: 1, diagnosis: PulseDiagnosis(code: "active", label: "有活动", severity: "ok", summary: "测试"),
              currentTool: nil, agentPath: nil, updatedAt: start, lastEventAt: start, turnStartedAt: start)
}

check(PulseModel.groups(in: []).isEmpty, "empty is zero conversations")
let grouped = PulseModel.groups(in: [task("root"), task("child", parent: "root"), task("grandchild", parent: "child"), task("finished", "completed")])
check(grouped.count == 1 && grouped[0].id == "root" && grouped[0].children.count == 2, "nested active agents belong to one conversation")
let activeChild = PulseModel.groups(in: [task("root", "completed"), task("child", parent: "root")])
check(activeChild.count == 1 && activeChild[0].id == "root", "active child keeps completed parent conversation visible")
let missingParent = PulseModel.groups(in: [task("child", parent: "missing")])
check(missingParent.count == 1 && missingParent[0].id == "child", "missing ancestor does not hide an active task")
let stale = PulseModel.groups(in: [task("old", "unknown"), task("failed", "failed"), task("stopped", "interrupted")])
check(stale.isEmpty, "unknown and terminal records are not counted as running")
let cycle = PulseModel.groups(in: [task("a", parent: "b"), task("b", parent: "a")])
check(cycle.count == 1 && cycle[0].id == "a" && cycle[0].children.map(\.id) == ["b"], "bad parent cycle has one stable conversation")
check(PulseModel.date("2026-10-27T12:00:00.123Z") != nil && PulseModel.date("2026-10-27T12:00:00Z") != nil, "both timestamp formats decode")
check(PulseModel.date("not a date") == nil, "invalid dates remain unknown")

let now = PulseModel.date("2026-10-27T13:00:00Z")!
let unknownTasks = [task("uncertain", "unknown")]
check(PulseModel.displayGroups(in: unknownTasks, now: now).map(\.id) == ["uncertain"] && PulseModel.groups(in: unknownTasks).isEmpty,
      "recent unknown conversation is visible without counting as running")
let failedTasks = [task("failed", "failed")]
check(PulseModel.displayGroups(in: failedTasks, now: now).map(\.id) == ["failed"] && PulseModel.groups(in: failedTasks).isEmpty,
      "recent failure is visible without counting as running")
let excluded = [task("old-unknown", "unknown", start: "2026-10-25T12:00:00Z"),
                task("old-failure", "failed", start: "2026-10-25T12:00:00Z"),
                task("future", "unknown", start: "2026-10-27T14:00:00Z"),
                task("invalid", "failed", start: "not a date"), task("done", "completed")]
check(PulseModel.displayGroups(in: excluded, now: now).isEmpty, "old, future, invalid and completed attention candidates are excluded")
let normalWithUnknown = [task("root"), task("uncertain-child", "unknown", parent: "root")]
let normalDisplay = PulseModel.displayGroups(in: normalWithUnknown, now: now)
check(normalDisplay.count == 1 && normalDisplay[0].children.map(\.id) == ["uncertain-child"] && PulseModel.groups(in: normalWithUnknown)[0].children.isEmpty,
      "running root includes uncertain child in hover while running membership stays exact")
let orphanDisplay = PulseModel.displayGroups(in: [task("orphan", "unknown", parent: "missing"), task("nested", parent: "orphan")], now: now)
check(orphanDisplay.count == 1 && orphanDisplay[0].id == "orphan" && orphanDisplay[0].children.map(\.id) == ["nested"],
      "missing ancestor preserves nearest known parent and descendant")
let repeated = [task("root", "completed"), task("child", "unknown", parent: "root"), task("grandchild", parent: "child"),
                task("child", "unknown", parent: "root"), task("grandchild", parent: "child")]
let repeatedDisplay = PulseModel.displayGroups(in: repeated, now: now)
check(repeatedDisplay.count == 1 && repeatedDisplay[0].id == "root" && repeatedDisplay[0].children.map(\.id) == ["child", "grandchild"],
      "duplicate tasks and intermediate parents appear only once under the root")
let cycleTasks = [task("z", "unknown", parent: "b"), task("b", parent: "a"), task("a", "failed", parent: "b")]
let cycleDisplay = PulseModel.displayGroups(in: cycleTasks, now: now)
let reversedCycle = PulseModel.displayGroups(in: Array(cycleTasks.reversed()), now: now)
check(cycleDisplay.count == 1 && cycleDisplay[0].id == "a" && cycleDisplay[0].children.map(\.id) == ["b", "z"] && reversedCycle[0].id == "a",
      "attention parent cycle and descendants merge deterministically")
let rootWithAttention = PulseGroup(id: "root", task: task("root"), children: [task("broken", "failed", parent: "root")])
check(rootWithAttention.primaryTask.id == "root", "running root remains the primary task")
let completedWithAttention = PulseGroup(id: "root", task: task("root", "completed"), children: [task("long", parent: "root", elapsed: 800), task("broken", "failed", parent: "root", elapsed: 5)])
check(completedWithAttention.primaryTask.id == "broken", "completed root chooses an attention child before duration")
let completedWithRunning = PulseGroup(id: "root", task: task("root", "completed"), children: [task("short", parent: "root", elapsed: 5), task("long", parent: "root", elapsed: 800)])
check(completedWithRunning.primaryTask.id == "long", "completed root otherwise chooses its longest running child")
if failures > 0 { exit(1) }
print("\(checks) native model checks passed")
