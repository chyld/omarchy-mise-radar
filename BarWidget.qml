import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "chyld.mise-radar"

  readonly property var miseService: bar && bar.shell
    ? bar.shell.serviceFor("chyld.mise-radar") : null
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool loading: miseService ? miseService.loading : true
  readonly property int outdatedCount: miseService ? miseService.outdatedCount : 0
  readonly property bool hasError: miseService ? miseService.errorMessage !== "" : false
  readonly property bool popoutSwitchClosing: panelLoader.item
    ? panelLoader.item.popoutSwitchClosing === true : false

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
    text: "󰏗"
    dimmed: root.loading || root.hasError
    tooltipText: {
      if (!root.miseService) return "mise"
      if (root.hasError) return "mise · error"
      if (root.loading) return "mise · loading…"
      if (root.outdatedCount > 0) return "mise · " + root.outdatedCount + " update" + (root.outdatedCount === 1 ? "" : "s")
      return "mise · up to date"
    }

    iconComponent: Component {
      Item {
        OpticalGlyph {
          id: miseGlyph
          anchors.fill: parent
          text: button.text
          color: button.foreground
          fontFamily: button.fontFamily
          fontSize: button.fontSize
        }

        Text {
          textFormat: Text.PlainText
          visible: root.outdatedCount > 0 && !root.loading && !root.hasError
          anchors.right: miseGlyph.right
          anchors.bottom: miseGlyph.bottom
          anchors.rightMargin: -Style.space(1)
          anchors.bottomMargin: -Style.space(1)
          text: root.outdatedCount > 9 ? "9+" : String(root.outdatedCount)
          color: Color.accent
          font.family: button.fontFamily
          font.pixelSize: Math.max(7, Math.round(button.fontSize * 0.45))
          font.bold: true
        }
      }
    }

    onPressed: function(mouseButton) {
      if (mouseButton === Qt.LeftButton) root.togglePanel()
    }
  }
}
