import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  readonly property int producerMaxStdoutBytes: 261120
  readonly property int maxStdoutBytes: 262144
  readonly property int panelRefreshMinMs: 60000
  readonly property int sigTerm: 15
  readonly property int sigKill: 9
  readonly property int killGraceMs: 5000
  readonly property int lsTimeoutMs: 15000
  readonly property int outdatedTimeoutMs: 45000
  readonly property int qmlBackupSlackMs: 2000
  readonly property string python3Path: "/usr/bin/python3"
  readonly property string killGraceSec: "1.5"
  readonly property string trustedMisePath: "/usr/bin/mise"

  readonly property string supervisePath: {
    var url = Qt.resolvedUrl("./supervise.py")
    var s = "" + url
    if (s.indexOf("file://") === 0)
      s = s.substring(7)
    if (!s || s.charAt(0) !== "/") return ""
    if (s.indexOf("..") !== -1) return ""
    return s
  }

  property var shell: null
  property string misePath: "/usr/bin/mise"
  property bool miseAvailable: false
  property bool loading: true
  property string errorMessage: ""
  property var toolRows: []
  property int outdatedCount: 0
  property string lastChecked: ""
  property double lastRefreshAt: 0

  property var cachedLsJson: null
  property var cachedOutdatedJson: null
  property bool destroying: false
  property int currentRefreshId: 0
  property int lsRefreshId: -1
  property int outdatedRefreshId: -1
  property string pendingStart: ""
  property bool lsAborted: false
  property bool outdatedAborted: false

  function isTrustedPath(path) {
    if (!path || typeof path !== "string") return false
    if (path.length < 2) return false
    if (path.charAt(0) !== "/") return false
    if (path.indexOf("..") !== -1) return false
    return path === "/usr/bin/mise"
  }

  function isTrustedSupervisePath(path) {
    if (!path || typeof path !== "string") return false
    if (path.charAt(0) !== "/") return false
    if (path.indexOf("..") !== -1) return false
    return true
  }

  function missingMiseMessage() {
    return "Omarchy mise-bin (/usr/bin/mise) is missing or untrusted"
  }

  function superviseCommand(timeoutSec, miseArgs) {
    if (!root.isTrustedSupervisePath(root.supervisePath)) return []
    if (!root.isTrustedPath("/usr/bin/mise")) return []
    var cmd = [
      root.python3Path,
      root.supervisePath,
      String(timeoutSec),
      String(root.producerMaxStdoutBytes),
      root.killGraceSec,
      "/usr/bin/mise",
      "--"
    ]
    var i
    for (i = 0; i < miseArgs.length; i++)
      cmd.push(miseArgs[i])
    return cmd
  }

  function anyProcessRunning() {
    return lsProcess.running || outdatedProcess.running
  }

  function abortProc(proc, deadlineTimer, killTimer) {
    deadlineTimer.stop()
    if (proc && proc.running) {
      proc.signal(root.sigTerm)
      killTimer.restart()
    } else {
      killTimer.stop()
    }
  }

  function abortAllWork() {
    root.abortProc(lsProcess, lsDeadline, lsKill)
    root.abortProc(outdatedProcess, outdatedDeadline, outdatedKill)
  }

  function collectorLength(collector) {
    if (!collector) return 0
    var blob = collector.data
    if (blob && typeof blob.length === "number") return blob.length
    if (blob && typeof blob.byteLength === "number") return blob.byteLength
    var text = collector.text
    if (text && typeof text.length === "number") return text.length
    return 0
  }

  function describeExit(exitCode, kind) {
    if (exitCode === 0) return ""
    if (exitCode === 124) return "mise " + kind + " timed out"
    if (exitCode === 125) return "mise output exceeded 256KiB"
    if (exitCode === 126) return root.missingMiseMessage()
    return "mise " + kind + " failed"
  }

  function dispatchPending() {
    if (root.destroying) return
    if (root.pendingStart === "") return
    if (root.anyProcessRunning()) return
    var next = root.pendingStart
    root.pendingStart = ""
    if (next === "ls") root.actuallyStartLs()
    else if (next === "outdated") root.actuallyStartOutdated()
  }

  function startLs() {
    if (root.destroying) return
    if (root.anyProcessRunning()) {
      root.pendingStart = "ls"
      root.abortAllWork()
      return
    }
    root.actuallyStartLs()
  }

  function actuallyStartLs() {
    if (root.destroying) return
    if (!root.isTrustedPath("/usr/bin/mise") || !root.isTrustedSupervisePath(root.supervisePath)) {
      root.miseAvailable = false
      root.errorMessage = root.missingMiseMessage()
      root.loading = false
      return
    }
    var cmd = root.superviseCommand(15, ["ls", "--json", "--current"])
    if (cmd.length === 0) {
      root.miseAvailable = false
      root.errorMessage = root.missingMiseMessage()
      root.loading = false
      return
    }
    root.lsAborted = false
    root.lsRefreshId = root.currentRefreshId
    lsProcess.command = cmd
    lsDeadline.restart()
    lsProcess.running = true
  }

  function startOutdated() {
    if (root.destroying) return
    if (root.anyProcessRunning()) {
      root.pendingStart = "outdated"
      root.abortAllWork()
      return
    }
    root.actuallyStartOutdated()
  }

  function actuallyStartOutdated() {
    if (root.destroying) return
    if (!root.miseAvailable) {
      root.updateModel()
      return
    }
    if (!root.isTrustedPath("/usr/bin/mise") || !root.isTrustedSupervisePath(root.supervisePath)) {
      root.updateModel()
      return
    }
    var cmd = root.superviseCommand(45, ["outdated", "--bump", "--json"])
    if (cmd.length === 0) {
      root.updateModel()
      return
    }
    root.outdatedAborted = false
    root.outdatedRefreshId = root.currentRefreshId
    outdatedProcess.command = cmd
    outdatedDeadline.restart()
    outdatedProcess.running = true
  }

  function onLsOversize() {
    root.lsAborted = true
    root.errorMessage = "mise output exceeded 256KiB"
    root.abortProc(lsProcess, lsDeadline, lsKill)
  }

  function onOutdatedOversize() {
    root.outdatedAborted = true
    root.errorMessage = "mise output exceeded 256KiB"
    root.abortProc(outdatedProcess, outdatedDeadline, outdatedKill)
  }

  function handleLsExited(exitCode) {
    lsDeadline.stop()
    lsKill.stop()
    if (root.destroying) return
    var gen = root.lsRefreshId
    var current = root.currentRefreshId
    var output = lsStdout.text
    var live = (gen === current && root.pendingStart === "")
    root.dispatchPending()
    if (!live) return
    if (root.lsAborted) {
      root.cachedLsJson = {}
    } else if (exitCode === 126) {
      root.miseAvailable = false
      root.cachedLsJson = {}
      if (root.errorMessage === "")
        root.errorMessage = root.missingMiseMessage()
      root.updateModel()
      return
    } else {
      var parsed = Model.parseJsonObject(output)
      root.cachedLsJson = parsed ? parsed : {}
      if (exitCode !== 0 && root.errorMessage === "")
        root.errorMessage = root.describeExit(exitCode, "ls")
    }
    root.startOutdated()
  }

  function handleOutdatedExited(exitCode) {
    outdatedDeadline.stop()
    outdatedKill.stop()
    if (root.destroying) return
    var gen = root.outdatedRefreshId
    var current = root.currentRefreshId
    var output = outdatedStdout.text
    var live = (gen === current && root.pendingStart === "")
    root.dispatchPending()
    if (!live) return
    if (root.outdatedAborted) {
      root.cachedOutdatedJson = {}
    } else {
      var parsed = Model.parseJsonObject(output)
      root.cachedOutdatedJson = parsed ? parsed : {}
      if (exitCode !== 0 && root.errorMessage === "")
        root.errorMessage = root.describeExit(exitCode, "outdated")
    }
    root.updateModel()
  }

  function updateModel() {
    var result = Model.buildModel(root.cachedLsJson || {}, root.cachedOutdatedJson || {})
    root.toolRows = result.rows
    root.outdatedCount = result.outdatedCount
    root.lastChecked = new Date().toLocaleTimeString(Qt.locale(), "HH:mm")
    root.loading = false
  }

  function runRefresh() {
    if (root.destroying) return
    if (!root.isTrustedPath("/usr/bin/mise") || !root.isTrustedSupervisePath(root.supervisePath)) {
      root.miseAvailable = false
      root.errorMessage = root.missingMiseMessage()
      root.loading = false
      return
    }
    root.miseAvailable = true
    root.lastRefreshAt = Date.now()
    root.currentRefreshId += 1
    root.loading = true
    root.errorMessage = ""
    root.cachedLsJson = null
    root.cachedOutdatedJson = null
    root.startLs()
  }

  function requestRefresh() {
    if (root.destroying) return
    if (root.lastRefreshAt > 0 && (Date.now() - root.lastRefreshAt) < root.panelRefreshMinMs)
      return
    root.runRefresh()
  }

  Component.onCompleted: {
    root.runRefresh()
  }

  Component.onDestruction: {
    root.destroying = true
    root.pendingStart = ""
    lsDeadline.stop()
    outdatedDeadline.stop()
    root.abortProc(lsProcess, lsDeadline, lsKill)
    root.abortProc(outdatedProcess, outdatedDeadline, outdatedKill)
  }

  Process {
    id: lsProcess
    command: []
    running: false
    stdout: StdioCollector {
      id: lsStdout
      waitForEnd: true
      onDataChanged: {
        if (root.collectorLength(lsStdout) >= root.maxStdoutBytes)
          root.onLsOversize()
      }
    }
    onExited: function(exitCode) { root.handleLsExited(exitCode) }
  }

  Timer {
    id: lsDeadline
    interval: root.lsTimeoutMs + root.qmlBackupSlackMs
    repeat: false
    onTriggered: {
      if (!lsProcess.running) return
      if (root.errorMessage === "") root.errorMessage = "mise ls timed out"
      root.abortProc(lsProcess, lsDeadline, lsKill)
    }
  }

  Timer {
    id: lsKill
    interval: root.killGraceMs
    repeat: false
    onTriggered: {
      if (lsProcess.running) lsProcess.signal(root.sigKill)
    }
  }

  Process {
    id: outdatedProcess
    command: []
    running: false
    clearEnvironment: false
    environment: ({
      "MISE_MINIMUM_RELEASE_AGE": "0"
    })
    stdout: StdioCollector {
      id: outdatedStdout
      waitForEnd: true
      onDataChanged: {
        if (root.collectorLength(outdatedStdout) >= root.maxStdoutBytes)
          root.onOutdatedOversize()
      }
    }
    onExited: function(exitCode) { root.handleOutdatedExited(exitCode) }
  }

  Timer {
    id: outdatedDeadline
    interval: root.outdatedTimeoutMs + root.qmlBackupSlackMs
    repeat: false
    onTriggered: {
      if (!outdatedProcess.running) return
      if (root.errorMessage === "") root.errorMessage = "mise outdated timed out"
      root.abortProc(outdatedProcess, outdatedDeadline, outdatedKill)
    }
  }

  Timer {
    id: outdatedKill
    interval: root.killGraceMs
    repeat: false
    onTriggered: {
      if (outdatedProcess.running) outdatedProcess.signal(root.sigKill)
    }
  }

  Timer {
    interval: 4 * 60 * 60 * 1000
    repeat: true
    running: true
    onTriggered: root.runRefresh()
  }
}
