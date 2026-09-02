import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

Item {
  id: root

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
  property bool initialCheckDone: false
  property bool needsOutdatedCheck: false

  function resolveMisePath() {
    pathResolver.running = true
  }

  function runRefresh() {
    if (!root.miseAvailable || !root.misePath) {
      root.loading = false
      return
    }

    root.loading = true
    root.errorMessage = ""
    root.cachedLsJson = null
    root.cachedOutdatedJson = null
    root.needsOutdatedCheck = false

    lsProcess.command = [root.misePath, "ls", "--json", "--current"]
    lsProcess.running = true
  }

  function runOutdatedCheck() {
    if (!root.miseAvailable || !root.misePath) {
      root.updateModel()
      return
    }

    outdatedProcess.command = ["env", "MISE_MINIMUM_RELEASE_AGE=0", root.misePath, "outdated", "--bump", "--json"]
    outdatedProcess.running = true
  }

  function updateModel() {
    const result = Model.buildModel(root.cachedLsJson || {}, root.cachedOutdatedJson || {})
    root.toolRows = result.rows
    root.outdatedCount = result.outdatedCount
    root.lastChecked = new Date().toLocaleTimeString(Qt.locale(), "HH:mm")
    root.loading = false
  }

  function requestRefresh() {
    if (!root.loading) {
      root.runRefresh()
    }
  }

  Component.onCompleted: {
    root.resolveMisePath()
  }

  Process {
    id: pathResolver
    command: ["sh", "-c", "command -v mise || echo ~/.local/bin/mise"]
    running: false

    stdout: StdioCollector {
      onStreamFinished: {
        const output = String(text).trim()
        if (output && output.length > 0)
          root.misePath = output
      }
    }

    onExited: function(exitCode) {
      if (root.misePath) {
        miseTestProcess.command = ["test", "-x", root.misePath]
        miseTestProcess.running = true
      } else {
        root.miseAvailable = false
        root.errorMessage = "mise binary not found in PATH or ~/.local/bin/mise"
        root.loading = false
        root.initialCheckDone = true
      }
    }
  }

  Process {
    id: miseTestProcess
    command: []
    running: false

    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.miseAvailable = true
        root.initialCheckDone = true
        root.runRefresh()
      } else {
        root.miseAvailable = false
        root.errorMessage = "mise binary not found or not executable"
        root.loading = false
        root.initialCheckDone = true
      }
    }
  }

  Process {
    id: lsProcess
    command: []
    running: false

    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.cachedLsJson = JSON.parse(String(text))
          root.needsOutdatedCheck = true
        } catch (e) {
          console.warn("mise: failed to parse ls JSON:", e)
          root.cachedLsJson = {}
        }
      }
    }

    onExited: function(exitCode) {
      if (exitCode !== 0) {
        console.warn("mise ls exited with code", exitCode)
        if (!root.cachedLsJson) root.cachedLsJson = {}
      }
      if (root.needsOutdatedCheck) {
        root.runOutdatedCheck()
      } else {
        root.updateModel()
      }
    }
  }

  Process {
    id: outdatedProcess
    command: []
    running: false

    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.cachedOutdatedJson = JSON.parse(String(text))
        } catch (e) {
          console.warn("mise: failed to parse outdated JSON:", e)
          root.cachedOutdatedJson = {}
        }
      }
    }

    onExited: function(exitCode) {
      if (exitCode !== 0) {
        console.warn("mise outdated exited with code", exitCode)
        if (!root.cachedOutdatedJson) root.cachedOutdatedJson = {}
      }
      root.updateModel()
    }
  }

  Timer {
    interval: 4 * 60 * 60 * 1000
    repeat: true
    running: root.miseAvailable
    onTriggered: root.runRefresh()
  }
}
