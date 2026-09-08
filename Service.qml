pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

  readonly property int producerMaxStdoutBytes: 261120
  readonly property int maxStdoutBytes: 262144
  readonly property int panelRefreshMinMs: 60000
  readonly property int panelErrorRefreshMinMs: 5000
  readonly property int sigTerm: 15
  readonly property int sigKill: 9
  readonly property int killGraceMs: 5000
  readonly property int lsTimeoutMs: 15000
  readonly property int outdatedTimeoutMs: 45000
  // The helper runs a version probe before the command, then may need time
  // to terminate and reap it. QML is only a fallback for a stuck helper.
  readonly property int versionCheckTimeoutMs: 5000
  readonly property int supervisorReapTimeoutMs: 2000
  readonly property int qmlBackupSlackMs: 2000
  readonly property string python3Path: "/usr/bin/python3"
  readonly property string killGraceSec: "1.5"

  readonly property string supervisePath: {
    var url = Qt.resolvedUrl("./supervise.py")
    var s = "" + url
    if (s.indexOf("file://") === 0)
      s = s.substring(7)
    if (!s || s.charAt(0) !== "/") return ""
    if (s.indexOf("..") !== -1) return ""
    return s
  }

  property bool miseAvailable: false
  property bool loading: false
  property var consumers: ({})
  property int nextConsumerId: 0
  readonly property int consumerCount: Object.keys(consumers).length
  readonly property bool polling: consumerCount > 0 && !destroying
  property string errorMessage: ""
  property var toolRows: []
  property int outdatedCount: 0
  property string lastChecked: ""
  property double lastRefreshAt: 0

  property string lsOutput: ""
  property string outdatedOutput: ""
  property var cachedLsJson: null
  property var cachedOutdatedJson: null
  property bool destroying: false
  property int currentRefreshId: 0
  property int lsRefreshId: -1
  property int outdatedRefreshId: -1
  property string pendingStart: ""
  property bool lsAborted: false
  property bool outdatedAborted: false

  function acquire() {
    var token = String(++root.nextConsumerId)
    var next = Object.assign({}, root.consumers)
    next[token] = true
    root.consumers = next
    if (root.consumerCount === 1) root.runRefresh()
    return token
  }

  function release(token) {
    if (!Object.prototype.hasOwnProperty.call(root.consumers, token)) return
    var next = Object.assign({}, root.consumers)
    delete next[token]
    root.consumers = next
    if (root.consumerCount > 0) return
    // Invalidate late results before cancelling. A new widget may subscribe
    // while the old helper is still shutting down.
    root.currentRefreshId += 1
    root.pendingStart = ""
    root.loading = false
    root.lastRefreshAt = 0
    root.abortAllWork()
  }

  function watchdogTimeoutMs(commandTimeoutMs) {
    return root.versionCheckTimeoutMs + commandTimeoutMs
      + Number(root.killGraceSec) * 1000 + root.supervisorReapTimeoutMs
      + root.qmlBackupSlackMs
  }

  function failRefresh(message) {
    root.errorMessage = message
    root.loading = false
    // Publish a new snapshot only after BOTH commands succeed. Keep the last
    // successful rows and timestamp when a refresh fails.
    root.cachedLsJson = null
    root.cachedOutdatedJson = null
  }

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
      root.python3Path, "-I", "-S", "-B",
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

  function processEnvironment() {
    var env = {"HOME": Quickshell.env("HOME"), "PATH": "/usr/bin:/bin",
      "LANG": "C.UTF-8", "MISE_MINIMUM_RELEASE_AGE": "0"}
    var names = ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"]
    for (var i = 0; i < names.length; i++) {
      var value = Quickshell.env(names[i])
      if (value && value.charAt(0) === "/") env[names[i]] = value
    }
    return env
  }

  function collectOutput(kind, chunk) {
    var isLs = kind === "ls"
    if (isLs ? root.lsAborted : root.outdatedAborted) return
    var previous = isLs ? root.lsOutput : root.outdatedOutput
    // The Python producer enforces bytes. This guard bounds UTF-16 storage
    // before concatenation, including if the helper itself misbehaves.
    if (previous.length + chunk.length > root.maxStdoutBytes) {
      if (isLs) { root.lsOutput = ""; root.onLsOversize() }
      else { root.outdatedOutput = ""; root.onOutdatedOversize() }
      return
    }
    if (isLs) root.lsOutput = previous + chunk
    else root.outdatedOutput = previous + chunk
  }

  function describeExit(exitCode, kind) {
    if (exitCode === 0) return ""
    if (exitCode === 124) return "mise " + kind + " timed out"
    if (exitCode === 125) return "mise output exceeded 255KiB"
    if (exitCode === 126) return root.missingMiseMessage()
    return "mise " + kind + " failed"
  }

  function dispatchPending() {
    if (!root.polling) return
    if (root.pendingStart === "") return
    if (root.anyProcessRunning()) return
    var next = root.pendingStart
    root.pendingStart = ""
    if (next === "ls") root.actuallyStartLs()
    else if (next === "outdated") root.actuallyStartOutdated()
  }

  function startLs() {
    if (!root.polling) return
    if (root.anyProcessRunning()) {
      root.pendingStart = "ls"
      root.abortAllWork()
      return
    }
    root.actuallyStartLs()
  }

  function actuallyStartLs() {
    if (!root.polling) return
    if (!root.isTrustedPath("/usr/bin/mise") || !root.isTrustedSupervisePath(root.supervisePath)) {
      root.miseAvailable = false
      root.errorMessage = root.missingMiseMessage()
      root.loading = false
      return
    }
    var cmd = root.superviseCommand(root.lsTimeoutMs / 1000, ["ls", "--json", "--current"])
    if (cmd.length === 0) {
      root.miseAvailable = false
      root.errorMessage = root.missingMiseMessage()
      root.loading = false
      return
    }
    root.lsAborted = false
    root.lsOutput = ""
    root.lsRefreshId = root.currentRefreshId
    lsProcess.command = cmd
    lsDeadline.restart()
    lsProcess.running = true
  }

  function startOutdated() {
    if (!root.polling) return
    if (root.anyProcessRunning()) {
      root.pendingStart = "outdated"
      root.abortAllWork()
      return
    }
    root.actuallyStartOutdated()
  }

  function actuallyStartOutdated() {
    if (!root.polling) return
    var cmd = root.superviseCommand(root.outdatedTimeoutMs / 1000, ["outdated", "--bump", "--json"])
    if (!root.miseAvailable || cmd.length === 0) {
      root.failRefresh(root.missingMiseMessage())
      return
    }
    root.outdatedAborted = false
    root.outdatedOutput = ""
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
    if (!root.polling) return
    var gen = root.lsRefreshId
    var current = root.currentRefreshId
    var output = root.lsOutput
    root.lsOutput = ""
    var live = (gen === current && root.pendingStart === "")
    root.dispatchPending()
    if (!live) return
    if (root.lsAborted || exitCode !== 0 || root.errorMessage !== "") {
      if (exitCode === 126) root.miseAvailable = false
      root.failRefresh(root.errorMessage || root.describeExit(exitCode, "ls"))
      return
    }
    var parsed = Model.parseJsonObject(output)
    if (parsed === null) {
      root.failRefresh("mise ls returned invalid JSON")
      return
    }
    if (Model.parseMiseList(parsed) === null) {
      root.failRefresh("mise ls returned invalid tool data")
      return
    }
    root.cachedLsJson = parsed
    root.startOutdated()
  }

  function handleOutdatedExited(exitCode) {
    outdatedDeadline.stop()
    outdatedKill.stop()
    if (!root.polling) return
    var gen = root.outdatedRefreshId
    var current = root.currentRefreshId
    var output = root.outdatedOutput
    root.outdatedOutput = ""
    var live = (gen === current && root.pendingStart === "")
    root.dispatchPending()
    if (!live) return
    if (root.outdatedAborted || exitCode !== 0 || root.errorMessage !== "") {
      root.failRefresh(root.errorMessage || root.describeExit(exitCode, "outdated"))
      return
    }
    var parsed = Model.parseJsonObject(output)
    if (parsed === null) {
      root.failRefresh("mise outdated returned invalid JSON")
      return
    }
    root.cachedOutdatedJson = parsed
    root.updateModel()
  }

  function updateModel() {
    var result = Model.buildModel(root.cachedLsJson || {}, root.cachedOutdatedJson || {})
    if (result === null) {
      root.failRefresh("mise outdated returned invalid tool data")
      return
    }
    root.toolRows = result.rows
    root.outdatedCount = result.outdatedCount
    root.lastChecked = new Date().toLocaleTimeString(Qt.locale(), "HH:mm")
    root.loading = false
  }

  function runRefresh() {
    if (!root.polling) return
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
    if (!root.polling || root.loading) return
    var since = Date.now() - root.lastRefreshAt
    var minMs = root.errorMessage === "" ? root.panelRefreshMinMs : root.panelErrorRefreshMinMs
    if (root.lastRefreshAt > 0 && since >= 0 && since < minMs) return
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
    clearEnvironment: true
    environment: root.processEnvironment()
    workingDirectory: Quickshell.env("HOME")
    command: []
    running: false
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(chunk) { root.collectOutput("ls", chunk) }
    }
    // Never forward inherited-runtime diagnostics into the shared shell log.
    stderr: SplitParser { splitMarker: ""; onRead: function(chunk) {} }
    onExited: function(exitCode) { root.handleLsExited(exitCode) }
  }

  Timer {
    id: lsDeadline
    interval: root.watchdogTimeoutMs(root.lsTimeoutMs)
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
    clearEnvironment: true
    environment: root.processEnvironment()
    workingDirectory: Quickshell.env("HOME")
    stdout: SplitParser {
      splitMarker: ""
      onRead: function(chunk) { root.collectOutput("outdated", chunk) }
    }
    // Never forward inherited-runtime diagnostics into the shared shell log.
    stderr: SplitParser { splitMarker: ""; onRead: function(chunk) {} }
    onExited: function(exitCode) { root.handleOutdatedExited(exitCode) }
  }

  Timer {
    id: outdatedDeadline
    interval: root.watchdogTimeoutMs(root.outdatedTimeoutMs)
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
    running: root.polling
    onTriggered: root.requestRefresh()
  }
}
