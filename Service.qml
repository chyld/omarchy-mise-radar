import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  readonly property int maxStdoutBytes: 262144
  readonly property int sigTerm: 15
  readonly property int sigKill: 9
  readonly property int killGraceMs: 1500
  readonly property int probeTimeoutMs: 5000
  readonly property int lsTimeoutMs: 15000
  readonly property int outdatedTimeoutMs: 45000

  property var shell: null
  property string misePath: ""
  property bool miseAvailable: false
  property bool loading: true
  property string errorMessage: ""
  property var toolRows: []
  property int outdatedCount: 0
  property string lastChecked: ""

  property var cachedLsJson: null
  property var cachedOutdatedJson: null
  property bool destroying: false
  property int currentRefreshId: 0
  property int lsRefreshId: -1
  property int outdatedRefreshId: -1
  property int probeRunId: 0
  property int probeIndex: 0
  property string probePathTrying: ""
  property string pendingStart: ""
  property bool lsAborted: false
  property bool outdatedAborted: false

  function isTrustedPath(path) {
    if (!path || typeof path !== "string") return false
    if (path.length < 2) return false
    if (path.charAt(0) !== "/") return false
    if (path.indexOf("..") !== -1) return false
    if (path === "/usr/bin/mise") return true
    var home = Quickshell.env("HOME") || ""
    if (home && home.charAt(0) === "/" && home.indexOf("..") === -1) {
      if (path === home + "/.local/bin/mise") return true
    }
    return false
  }

  function trustedCandidates() {
    var list = []
    if (root.isTrustedPath("/usr/bin/mise")) list.push("/usr/bin/mise")
    var home = Quickshell.env("HOME") || ""
    if (home && home.charAt(0) === "/" && home.indexOf("..") === -1) {
      var localPath = home + "/.local/bin/mise"
      if (root.isTrustedPath(localPath)) list.push(localPath)
    }
    return list
  }

  function anyProcessRunning() {
    return probeProcess.running || lsProcess.running || outdatedProcess.running
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
    root.abortProc(probeProcess, probeDeadline, probeKill)
    root.abortProc(lsProcess, lsDeadline, lsKill)
    root.abortProc(outdatedProcess, outdatedDeadline, outdatedKill)
  }

  function killNow(proc) {
    if (proc && proc.running) {
      proc.signal(root.sigTerm)
      proc.signal(root.sigKill)
    }
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

  function dispatchPending() {
    if (root.destroying) return
    if (root.pendingStart === "") return
    if (root.anyProcessRunning()) return
    var next = root.pendingStart
    root.pendingStart = ""
    if (next === "probe") root.actuallyStartProbe()
    else if (next === "ls") root.actuallyStartLs()
    else if (next === "outdated") root.actuallyStartOutdated()
  }

  function startProbe() {
    if (root.destroying) return
    root.probeIndex = 0
    if (root.anyProcessRunning()) {
      root.pendingStart = "probe"
      root.abortAllWork()
      return
    }
    root.actuallyStartProbe()
  }

  function actuallyStartProbe() {
    if (root.destroying) return
    var candidates = root.trustedCandidates()
    if (root.probeIndex >= candidates.length) {
      root.miseAvailable = false
      root.misePath = ""
      root.errorMessage = "mise not found at /usr/bin/mise or ~/.local/bin/mise"
      root.loading = false
      return
    }
    var path = candidates[root.probeIndex]
    if (!root.isTrustedPath(path)) {
      root.probeIndex += 1
      root.actuallyStartProbe()
      return
    }
    root.probePathTrying = path
    root.probeRunId += 1
    probeProcess.command = [path, "--version"]
    probeDeadline.restart()
    probeProcess.running = true
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
    if (!root.isTrustedPath(root.misePath)) {
      root.miseAvailable = false
      root.misePath = ""
      root.errorMessage = "mise not found at /usr/bin/mise or ~/.local/bin/mise"
      root.loading = false
      return
    }
    root.lsAborted = false
    root.lsRefreshId = root.currentRefreshId
    lsProcess.command = [root.misePath, "ls", "--json", "--current"]
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
    if (!root.isTrustedPath(root.misePath)) {
      root.updateModel()
      return
    }
    root.outdatedAborted = false
    root.outdatedRefreshId = root.currentRefreshId
    outdatedProcess.command = [root.misePath, "outdated", "--bump", "--json"]
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

  function handleProbeExited(exitCode) {
    probeDeadline.stop()
    probeKill.stop()
    if (root.destroying) return
    var path = root.probePathTrying
    var live = (root.pendingStart === "")
    root.dispatchPending()
    if (!live) return
    if (exitCode === 0 && root.isTrustedPath(path)) {
      root.misePath = path
      root.miseAvailable = true
      root.errorMessage = ""
      root.runRefresh()
      return
    }
    root.probeIndex += 1
    root.actuallyStartProbe()
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
    } else {
      var parsed = Model.parseJsonObject(output)
      root.cachedLsJson = parsed ? parsed : {}
      if (exitCode !== 0 && root.errorMessage === "")
        root.errorMessage = "mise ls failed"
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
        root.errorMessage = "mise outdated failed"
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
    if (!root.miseAvailable || !root.isTrustedPath(root.misePath)) {
      if (!root.miseAvailable) return
      root.loading = false
      return
    }
    root.currentRefreshId += 1
    root.loading = true
    root.errorMessage = ""
    root.cachedLsJson = null
    root.cachedOutdatedJson = null
    root.startLs()
  }

  function requestRefresh() {
    if (root.destroying) return
    if (!root.miseAvailable || !root.isTrustedPath(root.misePath)) return
    root.runRefresh()
  }

  Component.onCompleted: {
    root.startProbe()
  }

  Component.onDestruction: {
    root.destroying = true
    root.pendingStart = ""
    probeDeadline.stop()
    probeKill.stop()
    lsDeadline.stop()
    lsKill.stop()
    outdatedDeadline.stop()
    outdatedKill.stop()
    root.killNow(probeProcess)
    root.killNow(lsProcess)
    root.killNow(outdatedProcess)
  }

  Process {
    id: probeProcess
    command: []
    running: false
    onExited: function(exitCode) { root.handleProbeExited(exitCode) }
  }

  Timer {
    id: probeDeadline
    interval: root.probeTimeoutMs
    repeat: false
    onTriggered: {
      if (!probeProcess.running) return
      root.abortProc(probeProcess, probeDeadline, probeKill)
    }
  }

  Timer {
    id: probeKill
    interval: root.killGraceMs
    repeat: false
    onTriggered: {
      if (probeProcess.running) probeProcess.signal(root.sigKill)
    }
  }

  Process {
    id: lsProcess
    command: []
    running: false
    stdout: StdioCollector {
      id: lsStdout
      waitForEnd: false
      onDataChanged: {
        if (root.collectorLength(lsStdout) > root.maxStdoutBytes)
          root.onLsOversize()
      }
    }
    onExited: function(exitCode) { root.handleLsExited(exitCode) }
  }

  Timer {
    id: lsDeadline
    interval: root.lsTimeoutMs
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
      waitForEnd: false
      onDataChanged: {
        if (root.collectorLength(outdatedStdout) > root.maxStdoutBytes)
          root.onOutdatedOversize()
      }
    }
    onExited: function(exitCode) { root.handleOutdatedExited(exitCode) }
  }

  Timer {
    id: outdatedDeadline
    interval: root.outdatedTimeoutMs
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
    running: root.miseAvailable
    onTriggered: root.runRefresh()
  }
}
