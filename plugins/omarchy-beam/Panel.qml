// Beam - the panel.
//
// Built from the same qs.Ui primitives the first-party Omarchy panels use, so
// it inherits the active theme rather than approximating it.
//
// The flow is deliberately one-directional: stage files (drop them on the bar,
// drop them here, or `omarchy-shell omarchy.beam send <path>`), then pick a
// device. Picking a device with nothing staged does nothing, which is why the
// device rows say so rather than pretending to be buttons.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.beam"
  ipcTarget: "omarchy.beam"
  // One monitor's copy claims the IPC target; a second registration collides.
  manageIpc: false

  // ---- injected by BarWidget ----
  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool   autoAccept: setting("autoAccept", false) === true
  readonly property bool   quiet:      setting("quiet", false) === true
  readonly property bool   notifyOnReceive: setting("notifyOnReceive", true) !== false

  // ---- files waiting for a destination ----
  property var staged: []

  function stageForSending(urls) {
    var next = staged.slice()
    for (var i = 0; i < urls.length; i++) {
      var path = String(urls[i]).replace(/^file:\/\//, "")
      path = decodeURIComponent(path)
      if (next.indexOf(path) === -1) next.push(path)
    }
    root.staged = next
    root.open()
  }

  function clearStaged() { root.staged = [] }

  function sendTo(fingerprint) {
    if (!root.core || root.staged.length === 0) return
    root.core.send([fingerprint], root.staged)
    root.clearStaged()
  }

  function baseName(path) {
    var parts = String(path).split("/")
    return parts[parts.length - 1] || path
  }

  function humanSize(bytes) {
    var b = Number(bytes) || 0
    if (b < 1024) return b + " B"
    var units = ["KB", "MB", "GB", "TB"]
    var i = -1
    do { b /= 1024; i++ } while (b >= 1024 && i < units.length - 1)
    return (b < 10 ? b.toFixed(1) : Math.round(b)) + " " + units[i]
  }

  function deviceGlyph(type) {
    if (type === "mobile") return ""
    if (type === "web") return ""
    if (type === "server" || type === "headless") return ""
    return ""
  }

  // ---- persistence ----
  // updateEntryInline REPLACES the entry, so every existing key has to be
  // carried across or it is silently dropped from the user's config.
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

  readonly property bool canPersist:
    !!(bar && bar.shell && typeof bar.shell.updateEntryInline === "function")

  IpcHandler {
    enabled: root.primary
    target: "omarchy.beam"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    // `omarchy-shell omarchy.beam send ~/report.pdf` - the terminal route,
    // and the thing to bind a Hyprland key to.
    function send(path: string): void {
      if (path && path.length > 0) root.stageForSending([path])
    }
    function refresh(): void { if (root.core) root.core.refresh() }
  }

  KeyboardPanel {
    id: panel

    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      // Dropping onto the open panel is the same gesture as dropping onto
      // the bar cell, and people will try both.
      DropArea {
        anchors.fill: parent
        onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
        onDropped: function (drop) {
          if (!drop.hasUrls) return
          root.stageForSending(drop.urls)
          drop.accept(Qt.CopyAction)
        }
      }

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: "Beam"
          meta: root.core && root.core.ready
                ? (root.core.identity + "  ·  " + (root.core.protocol === "https"
                                                   ? "ENCRYPTED" : "PLAINTEXT"))
                : "STARTING"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        // ---------------- the helper is not running ----------------
        Text {
          width: parent.width
          visible: !!(root.core && !root.core.ready && root.core.lastError.length > 0)
          text: root.core ? root.core.lastError : ""
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // ---------------- someone is sending us something ----------------
        Loader {
          width: parent.width
          active: !!(root.core && root.core.pending)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(6)
            readonly property var req: root.core.pending

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            PanelSectionHeader {
              text: "INCOMING"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Text {
              width: parent.width
              text: req.from + " wants to send " +
                    (req.files.length === 1
                     ? root.baseName(req.files[0].fileName)
                     : req.files.length + " files") +
                    "  ·  " + root.humanSize(req.totalSize)
              color: root.barForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
            }

            ButtonGroup {
              width: parent.width
              spacing: Style.space(6)
              value: ""
              foreground: root.barForeground
              accent: Color.accent
              fontFamily: root.fontFamily
              options: [
                { value: "accept",  label: "Accept",  tooltip: "Save to " + (root.core.saveDir || "~/Downloads") },
                { value: "decline", label: "Decline", tooltip: "Refuse this transfer" }
              ]
              onChanged: function (v) {
                if (v === "accept") root.core.accept(req.sessionId)
                else root.core.reject(req.sessionId)
              }
            }
          }
        }

        // ---------------- something is moving ----------------
        Loader {
          width: parent.width
          active: !!(root.core && root.core.transfer)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(4)
            readonly property var t: root.core.transfer
            readonly property real fraction:
              t.total > 0 ? Math.max(0, Math.min(1, t.bytes / t.total)) : 0

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            Text {
              width: parent.width
              elide: Text.ElideMiddle
              text: (t.direction === "in" ? "Receiving " : "Sending ") +
                    (t.fileName || "") +
                    (t.count > 1 ? "  (" + (t.done + 1) + " of " + t.count + ")" : "")
              color: root.barForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Rectangle {
              width: parent.width
              height: Math.max(3, Style.space(3))
              radius: height / 2
              color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                             root.barForeground.b, 0.18)

              Rectangle {
                width: parent.width * fraction
                height: parent.height
                radius: parent.radius
                color: Color.accent
                Behavior on width { NumberAnimation { duration: 120 } }
              }
            }

            Text {
              text: root.humanSize(t.bytes) + " of " + root.humanSize(t.total)
              color: root.barForeground
              opacity: 0.7
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        // ---------------- files staged to send ----------------
        Loader {
          width: parent.width
          active: root.staged.length > 0
          visible: active
          sourceComponent: Column {
            spacing: Style.space(4)

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            PanelSectionHeader {
              text: "READY TO SEND — PICK A DEVICE"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.staged
              Text {
                width: column.width
                elide: Text.ElideMiddle
                text: "  " + root.baseName(modelData)
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Item {
              width: column.width
              height: clearButton.implicitHeight
              PanelActionButton {
                id: clearButton
                anchors.right: parent.right
                iconText: ""
                tooltipText: "Forget these files"
                foreground: root.barForeground
                fontFamily: root.fontFamily
                onClicked: root.clearStaged()
              }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        // ---------------- devices ----------------
        PanelSectionHeader {
          text: root.quiet ? "DEVICES — YOU ARE INVISIBLE" : "DEVICES"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !root.core || root.core.peers.length === 0
          text: root.core && root.core.ready
                ? "Nothing found yet. Open LocalSend on a phone or laptop on this network and it will appear here."
                : "Starting the Beam helper…"
          color: root.barForeground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.core ? root.core.peers : []

          Rectangle {
            width: column.width
            height: Math.round(Style.space(34))
            radius: Style.cornerRadius
            color: peerMouse.containsMouse && root.staged.length > 0
                   ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.18)
                   : "transparent"

            Row {
              anchors { left: parent.left; right: parent.right
                        verticalCenter: parent.verticalCenter
                        leftMargin: Style.space(6); rightMargin: Style.space(6) }
              spacing: Style.space(8)

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.deviceGlyph(modelData.deviceType)
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Column {
                anchors.verticalCenter: parent.verticalCenter
                Text {
                  text: modelData.alias
                  color: root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Text {
                  text: (modelData.deviceModel || modelData.deviceType || "") +
                        "  ·  " + modelData.address
                  color: root.barForeground
                  opacity: 0.6
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 2)
                }
              }
            }

            Text {
              anchors { right: parent.right; rightMargin: Style.space(8)
                        verticalCenter: parent.verticalCenter }
              visible: root.staged.length > 0
              text: "Send "
              color: Color.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            MouseArea {
              id: peerMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: root.staged.length > 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: root.sendTo(modelData.fingerprint)
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        // ---------------- settings ----------------
        Toggle {
          width: parent.width
          label: "Accept without asking"
          description: "Fine at home. Not on a network you do not own."
          checked: root.autoAccept
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ autoAccept: !root.autoAccept })
        }

        Toggle {
          width: parent.width
          label: "Invisible"
          description: "Stop announcing. You can still send; nobody can send to you."
          checked: root.quiet
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ quiet: !root.quiet })
        }

        Toggle {
          width: parent.width
          label: "Notify on arrival"
          description: "Raise a notification when files finish landing."
          checked: root.notifyOnReceive
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ notifyOnReceive: !root.notifyOnReceive })
        }

        Text {
          width: parent.width
          visible: !!(root.core && root.core.ready)
          text: "Saving to " + (root.core ? (root.core.saveDir || "~/Downloads") : "") +
                (root.core && root.core.addresses.length > 0
                 ? "   ·   " + root.core.addresses[0] : "")
          color: root.barForeground
          opacity: 0.55
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: !root.canPersist
          text: "Add Beam to the bar to save these settings."
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
