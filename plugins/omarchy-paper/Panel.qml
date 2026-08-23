// Paper - the panel.
//
// Printers first, jobs second. A printer CUPS already knows is a button you
// can print to; a printer only the network knows about shows the one command
// that would set it up, which the user runs themselves. This plugin does not
// run lpadmin and does not ask for a password.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.paper"
  ipcTarget: "omarchy.paper"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string defaultQueue: setting("defaultQueue", "")
  readonly property bool   duplex: setting("duplex", false) === true

  function stateColour(p) {
    if (!p.queue) return Qt.rgba(root.barForeground.r, root.barForeground.g,
                                 root.barForeground.b, 0.35)
    if (p.state === "printing") return Color.accent
    if (p.state === "stopped" || p.state === "disabled") return bar ? bar.urgent : "#e05252"
    if (p.reasons && p.reasons.length > 0) return "#e0a352"
    return "#5fd18a"
  }

  function stateWords(p) {
    var bits = []
    if (!p.queue) bits.push("not set up")
    else bits.push(p.state)
    if (p.reasons && p.reasons.length > 0)
      bits.push(p.reasons.join(", ").replace(/-/g, " "))
    else if (p.stateMessage) bits.push(p.stateMessage)
    return bits.join(" · ")
  }

  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var k in root.settings)
      if (k !== "id") entry[k] = root.settings[k]
    for (var v in values) entry[v] = values[v]
    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget)
      root.hostWidget.settings = entry
    if (root.bar && root.bar.shell
        && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.paper"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    // `omarchy-shell omarchy.paper print ~/invoice.pdf`
    function print(path: string): void {
      if (root.core && path) root.core.printFile(path, root.defaultQueue, root.duplex)
    }
    function rescan(): void { if (root.core) root.core.rescan() }
  }

  KeyboardPanel {
    id: panel

    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      DropArea {
        anchors.fill: parent
        onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
        onDropped: function (drop) {
          if (!drop.hasUrls || !root.core) return
          var path = decodeURIComponent(String(drop.urls[0]).replace(/^file:\/\//, ""))
          root.core.printFile(path, root.defaultQueue, root.duplex)
          drop.accept(Qt.CopyAction)
        }
      }

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: "Paper"
          meta: root.core && root.core.scanning ? "LOOKING…"
                : (root.core && root.core.jobs.length > 0
                   ? root.core.jobs.length + " IN THE QUEUE" : "READY")
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !!(root.core && !root.core.cupsPresent)
          text: "CUPS is not installed, so nothing can be printed yet. Discovered " +
                "printers are still listed below.  sudo pacman -S cups && " +
                "sudo systemctl enable --now cups"
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: !!(root.core && root.core.lastError.length > 0)
          text: root.core ? root.core.lastError : ""
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: "PRINTERS"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !root.core || root.core.printers.length === 0
          text: root.core && root.core.scanning
                ? "Asking the network…"
                : "No printers found. Most network printers advertise themselves; " +
                  "a USB printer needs CUPS to know about it first."
          color: root.barForeground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.core ? root.core.printers : []

          Column {
            width: column.width
            spacing: Style.space(2)

            Item {
              width: parent.width
              height: Math.round(Style.space(30))

              Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: Style.space(8)

                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: 7; height: 7; radius: 3.5
                  color: root.stateColour(modelData)
                }

                Column {
                  anchors.verticalCenter: parent.verticalCenter
                  Text {
                    text: modelData.name + (modelData.isDefault ? "  ·  default" : "")
                    color: root.barForeground
                    opacity: modelData.queue ? 1.0 : 0.65
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                  Text {
                    text: root.stateWords(modelData)
                    color: root.barForeground
                    opacity: 0.6
                    font.family: root.fontFamily
                    font.pixelSize: Math.max(9, Style.font.caption - 2)
                  }
                }
              }

              // Ink and toner, where the printer told us.
              Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: Style.space(3)
                visible: (modelData.markers || []).length > 0

                Repeater {
                  model: modelData.markers || []
                  Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Style.space(4); height: Style.space(16)
                    radius: 1
                    color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                                   root.barForeground.b, 0.16)

                    Rectangle {
                      anchors.bottom: parent.bottom
                      width: parent.width
                      height: parent.height * Math.max(0, Math.min(1, modelData.level / 100))
                      radius: 1
                      color: modelData.level < 15 ? (bar ? bar.urgent : "#e05252")
                             : (modelData.level < 30 ? "#e0a352" : Color.accent)
                    }
                  }
                }
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: modelData.queue ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (modelData.queue)
                  root.persistSettings({ defaultQueue: modelData.queue })
              }
            }

            // A printer the network advertises but CUPS has never been told
            // about. We show the command; we do not run it. lpadmin needs
            // privileges a bar widget has no business holding.
            Column {
              width: parent.width
              visible: !!modelData.setupCommand
              spacing: Style.space(2)

              Text {
                width: parent.width
                text: "Set it up yourself — this plugin will not ask for your password:"
                color: root.barForeground
                opacity: 0.55
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 2)
                wrapMode: Text.WordWrap
              }

              Rectangle {
                width: parent.width
                height: setupText.implicitHeight + Style.space(10)
                radius: Style.cornerRadius
                color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                               root.barForeground.b, 0.07)

                Text {
                  id: setupText
                  anchors { left: parent.left; right: parent.right
                            verticalCenter: parent.verticalCenter
                            leftMargin: Style.space(6); rightMargin: Style.space(6) }
                  text: "sudo " + modelData.setupCommand
                  color: Color.accent
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 1)
                  wrapMode: Text.WrapAnywhere
                }
              }
            }
          }
        }

        // ---------------- queue ----------------
        Loader {
          width: parent.width
          active: !!(root.core && root.core.jobs.length > 0)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(4)

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            PanelSectionHeader {
              text: "QUEUE"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.core.jobs
              Item {
                width: column.width
                height: Math.round(Style.space(22))

                Text {
                  anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                  width: parent.width - cancelButton.width - Style.space(10)
                  elide: Text.ElideRight
                  text: modelData.id + "   " + modelData.user
                  color: root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                PanelActionButton {
                  id: cancelButton
                  anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                  iconText: ""
                  tooltipText: "Cancel this job"
                  foreground: root.barForeground
                  fontFamily: root.fontFamily
                  onClicked: root.core.cancel(modelData.id)
                }
              }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Toggle {
          width: parent.width
          label: "Double-sided"
          description: "Send jobs two-sided when the printer supports it."
          checked: root.duplex
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ duplex: !root.duplex })
        }

        Item {
          width: parent.width
          height: rescanButton.implicitHeight

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: parent.width - rescanButton.width - Style.space(8)
            elide: Text.ElideRight
            text: "Drop a document here to print it" +
                  (root.defaultQueue.length > 0 ? "  ·  " + root.defaultQueue : "")
            color: root.barForeground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 2)
          }

          PanelActionButton {
            id: rescanButton
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Look for printers again"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: if (root.core) root.core.rescan()
          }
        }
      }
    }
  }
}
