import QtQuick
import Quickshell
import qs.Commons
import "plugin" as Backend

Scope {
  id: test
  property var service: Backend.MiseService
  property var widgetA: null
  property var widgetB: null
  property int phase: 0
  property int ticks: 0
  property string snapshot: ""
  property string checked: ""
  property var widgetComponent: null

  function check(condition, message) {
    if (!condition) {
      console.error("FAIL " + message)
      Qt.quit()
      throw new Error(message)
    }
  }
  function makeWidget() {
    var widget = widgetComponent.createObject(test)
    check(widget !== null, "widget creation")
    return widget
  }
  function periodicTimerRunning() {
    for (var i = 0; i < service.resources.length; i++) {
      var item = service.resources[i]
      if ("interval" in item && item.interval === 14400000) return item.running
    }
    check(false, "periodic timer exists")
    return false
  }
  function panelFor(widget) {
    for (var i = 0; i < widget.children.length; i++) {
      var child = widget.children[i]
      if ("item" in child && child.item && "service" in child.item) return child.item
    }
    return null
  }
  function checkPopupTheme(widget) {
    var popup = panelFor(widget)
    var texts = []
    function collect(item) {
      if ("text" in item && "textFormat" in item) texts.push(item)
      var children = item.children || []
      for (var i = 0; i < children.length; i++) collect(children[i])
    }
    for (var i = 0; i < popup.resources.length; i++) {
      var resource = popup.resources[i]
      if ("focusTarget" in resource && resource.focusTarget) collect(resource.focusTarget)
    }
    check(texts.length > 10, "popup text items found")
    var saved = Color.shellValues
    // Bar/wallpaper foreground can be dark while popup text must stay light.
    // Update the real Color singleton in this private test process only.
    var palettes = [
      {"bar.text": "#282020", "popups.background": "#282020", "popups.text": "#fff1d2"},
      {"bar.text": "#fff1d2", "popups.background": "#fff1d2", "popups.text": "#282020"}
    ]
    for (var j = 0; j < palettes.length; j++) {
      Color.shellValues = palettes[j]
      var checked = 0
      for (var k = 0; k < texts.length; k++) {
        var item = texts[k]
        if (["mise radar", "tool", "requested", "installed", "latest", "Loading…", "No tools configured"].indexOf(item.text) >= 0
            || item.text.indexOf("last successful check ") === 0) {
          check(Qt.colorEqual(item.color, palettes[j]["popups.text"]), "popup text follows theme: " + item.text)
          checked++
        }
      }
      check(checked >= 8, "header and status theme coverage")
    }
    Color.shellValues = saved
  }
  Component.onCompleted: {
    check(!service.polling && !periodicTimerRunning(), "idle before first consumer")
    check(service.versionCheckTimeoutMs === Number(Quickshell.env("RADAR_TEST_PROBE_MS")), "version budget matches Python supervisor")
    check(service.supervisorReapTimeoutMs === Number(Quickshell.env("RADAR_TEST_REAP_MS")), "cleanup budget matches Python supervisor")
    check(service.watchdogTimeoutMs(service.lsTimeoutMs) === 25500, "complete ls timeout budget")
    check(service.watchdogTimeoutMs(service.outdatedTimeoutMs) === 55500, "complete outdated timeout budget")
    widgetComponent = Qt.createComponent("plugin/BarWidget.qml")
    check(widgetComponent.status === Component.Ready, widgetComponent.errorString())
    widgetA = makeWidget()
    widgetB = makeWidget()
    check(service.consumerCount === 2, "two widget subscriptions")
    check(service.currentRefreshId === 1, "second monitor does not launch another refresh")
    service.release("unknown")
    check(service.consumerCount === 2, "unknown release cannot remove a subscriber")
    check(widgetA.miseService === widgetB.miseService, "shared backend")
  }
  Timer {
    interval: 50
    repeat: true
    running: true
    onTriggered: {
      ticks++
      if (phase <= 8 && service.loading) return
      if (phase === 0) {
        check(service.errorMessage.indexOf("invalid tool data") !== -1, "first failure is an error")
        check(service.toolRows.length === 0 && service.lastChecked === "", "first failure has no fabricated snapshot")
        var panel = panelFor(widgetA)
        check(panel && panel.service === service, "actual popup receives service")
        phase = 1
        service.runRefresh()
      } else if (phase === 1) {
        check(service.errorMessage === "" && service.outdatedCount === 1, "successful refresh")
        check(panelFor(widgetB).service.toolRows[0].latest === "2.0", "second popup receives result")
        checkPopupTheme(widgetA)
        checkPopupTheme(widgetB)
        snapshot = JSON.stringify(service.toolRows)
        checked = service.lastChecked
        phase = 2
        service.runRefresh()
      } else if (phase >= 2 && phase <= 7) {
        check(service.errorMessage !== "", "failed refresh reports error at phase " + phase)
        check(JSON.stringify(service.toolRows) === snapshot && service.lastChecked === checked, "failed refresh preserves snapshot")
        check(widgetA.stale, "known update stays indicated")
        if (phase === 6) check(service.errorMessage.indexOf("timed out") !== -1, "timeout reported distinctly")
        phase++
        service.runRefresh()
      } else if (phase === 8) {
        check(service.errorMessage === "" && service.outdatedCount === 0, "valid empty outdated response recovers")
        widgetA.destroy()
        phase = 9
        ticks = 0
      } else if (phase === 9 && ticks > 2) {
        check(service.consumerCount === 1 && periodicTimerRunning(), "one remaining monitor keeps polling")
        service.runRefresh()
        phase = 10
        ticks = 0
      } else if (phase === 10 && ticks > 10) {
        check(service.loading && service.anyProcessRunning(), "refresh active before last widget removal")
        widgetB.destroy()
        phase = 11
        ticks = 0
      } else if (phase === 11 && ticks > 2) {
        check(service.consumerCount === 0 && !periodicTimerRunning() && !service.loading, "last removal stops polling")
        if (service.anyProcessRunning()) return
        widgetA = makeWidget()
        phase = 12
      } else if (phase === 12 && !service.loading) {
        check(service.errorMessage === "" && service.outdatedCount === 1, "re-enable refreshes successfully")
        console.log("PASS service errors, snapshots, popup injection, shared lifecycle, cancellation, re-enable, timeout budgets, popup theme changes")
        Qt.quit()
      }
    }
  }
  Timer {
    interval: 15000
    running: true
    onTriggered: { console.error("FAIL integration test timed out at phase " + phase); Qt.quit() }
  }
}
