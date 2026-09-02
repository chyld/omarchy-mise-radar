import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "chyld.mise-radar"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null

  function open() {
    root.controller.show()
    if (root.service) root.service.requestRefresh()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.hostWidget || root, direction)
    return false
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.hostWidget || root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: content
        width: parent.width
        spacing: Style.space(6)

        Row {
          width: parent.width
          spacing: Style.space(6)

          Text {
            textFormat: Text.PlainText
            text: "mise radar"
            color: root.barForeground
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.body
            font.bold: true
          }

          Text {
            textFormat: Text.PlainText
            visible: root.service && root.service.lastChecked !== ""
            text: root.service ? "last updated " + root.service.lastChecked : ""
            color: root.barForeground
            opacity: 0.45
            font.family: root.bar ? root.bar.fontFamily : Style.font.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        Text {
          visible: root.service && root.service.errorMessage !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: root.service ? root.service.errorMessage : ""
          color: Color.urgent
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
        }

        Text {
          visible: root.service && !root.service.loading && root.service.toolRows.length === 0 && root.service.errorMessage === ""
          textFormat: Text.PlainText
          text: "No tools configured"
          color: root.barForeground
          opacity: 0.6
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        Text {
          visible: root.service && root.service.loading
          textFormat: Text.PlainText
          text: "Loading…"
          color: root.barForeground
          opacity: 0.6
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.bodySmall
        }

        Column {
          visible: root.service && !root.service.loading && root.service.toolRows.length > 0
          width: parent.width
          spacing: 0

          Row {
            width: parent.width
            height: Style.font.bodySmall + Style.space(4)
            spacing: 0

            Text {
              width: parent.width * 0.40
              textFormat: Text.PlainText
              text: "tool"
              color: root.barForeground
              opacity: 0.45
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              width: parent.width * 0.20
              textFormat: Text.PlainText
              text: "requested"
              color: root.barForeground
              opacity: 0.45
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              width: parent.width * 0.20
              textFormat: Text.PlainText
              text: "installed"
              color: root.barForeground
              opacity: 0.45
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
            Text {
              width: parent.width * 0.20
              textFormat: Text.PlainText
              text: "latest"
              color: root.barForeground
              opacity: 0.45
              font.family: root.bar ? root.bar.fontFamily : Style.font.family
              font.pixelSize: Style.font.bodySmall
            }
          }

          Repeater {
            model: root.service ? root.service.toolRows : []

            Rectangle {
              width: parent.width
              height: rowTexts.implicitHeight + Style.space(4)
              color: modelData.outdated ? Util.alpha(Color.accent, 0.12) : "transparent"
              radius: Style.cornerRadius

              Row {
                id: rowTexts
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width
                spacing: 0

                Text {
                  width: parent.width * 0.40
                  textFormat: Text.PlainText
                  text: modelData.name
                  elide: Text.ElideRight
                  color: root.barForeground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                }
                Text {
                  width: parent.width * 0.20
                  textFormat: Text.PlainText
                  text: modelData.requested
                  elide: Text.ElideRight
                  color: root.barForeground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }
                Text {
                  width: parent.width * 0.20
                  textFormat: Text.PlainText
                  text: modelData.current
                  elide: Text.ElideRight
                  color: root.barForeground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }
                Text {
                  width: parent.width * 0.20
                  textFormat: Text.PlainText
                  text: modelData.latest !== "" ? modelData.latest : modelData.current
                  elide: Text.ElideRight
                  color: modelData.outdated ? Color.accent : root.barForeground
                  font.family: root.bar ? root.bar.fontFamily : Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  font.bold: modelData.outdated
                }
              }
            }
          }
        }
      }
    }
  }
}
