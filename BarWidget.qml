import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "." as Backend

BarWidget {
  id: root
  moduleName: "chyld.mise-radar"

  // Share one backend across monitors without depending on the bar's shell
  // facade, which cannot expose plugin services under replacement bars.
  readonly property var miseService: Backend.MiseService
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool loading: miseService ? miseService.loading : true
  readonly property int outdatedCount: miseService ? miseService.outdatedCount : 0
  readonly property bool hasError: miseService ? miseService.errorMessage !== "" : false
  readonly property bool stale: root.outdatedCount > 0
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false

  property string serviceSubscription: ""
  Component.onCompleted: serviceSubscription = miseService.acquire()
  Component.onDestruction: miseService.release(serviceSubscription)

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("service" in target) target.service = root.miseService
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
    else if (panelLoader.item) panelLoader.item.open()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()
  onMiseServiceChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "radar"
    dimmed: root.loading || root.hasError
    tooltipText: {
      if (!root.miseService) return "mise radar"
      if (root.hasError) return "mise radar · error"
      if (root.loading) return "mise radar · loading…"
      if (root.outdatedCount > 0) return "mise radar · " + root.outdatedCount + " update" + (root.outdatedCount === 1 ? "" : "s")
      return "mise radar · up to date"
    }

    iconComponent: Component {
      Item {
        id: radar
        readonly property color ink: root.stale ? Color.urgent : button.foreground

        Rectangle {
          anchors.centerIn: parent
          width: Math.min(parent.width, parent.height) - 1
          height: width
          radius: width / 2
          color: "transparent"
          border.color: radar.ink
          border.width: 1.25
          antialiasing: true
        }

        Rectangle {
          width: 1.25
          height: parent.height * 0.39
          radius: width / 2
          color: radar.ink
          x: parent.width / 2 - width / 2
          y: parent.height / 2 - height
          transformOrigin: Item.Bottom
          rotation: 42
          antialiasing: true
        }

        Rectangle {
          width: 2.5
          height: width
          radius: width / 2
          color: radar.ink
          x: parent.width * 0.30 - width / 2
          y: parent.height * 0.65 - height / 2
          antialiasing: true
        }

      }
    }

    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) root.togglePanel()
    }
  }
}
