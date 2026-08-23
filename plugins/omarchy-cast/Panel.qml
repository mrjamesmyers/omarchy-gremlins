// Cast - the panel.
//
// Two states. Nothing casting: pick something to play and pick a screen.
// Casting: what is playing, where, and the controls for it.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.cast"
  ipcTarget: "omarchy.cast"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // What will be sent to whichever device is picked next.
  property string pendingSource: ""
  property string pendingTitle: ""

  function stage(urls) {
    if (!urls || urls.length === 0) return
    var path = decodeURIComponent(String(urls[0]).replace(/^file:\/\//, ""))
    root.pendingSource = path
    root.pendingTitle = root.baseName(path)
    root.open()
  }

  function stagePath(path) {
    if (!path || path.length === 0) return
    root.pendingSource = path
    root.pendingTitle = /^https?:\/\//.test(path) ? path : root.baseName(path)
    root.open()
  }

  function baseName(path) {
    var parts = String(path).split("/")
    return parts[parts.length - 1] || path
  }

  function clock(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0))
    var h = Math.floor(s / 3600)
    var m = Math.floor((s % 3600) / 60)
    var r = s % 60
    function pad(n) { return n < 10 ? "0" + n : String(n) }
    return h > 0 ? h + ":" + pad(m) + ":" + pad(r) : m + ":" + pad(r)
  }

  function kindLabel(kind) {
    if (kind === "cast") return "Chromecast"
    if (kind === "dlna") return "DLNA"
    if (kind === "airplay") return "AirPlay"
    return kind
  }

  function pick(target) {
    if (!root.core) return
    if (root.pendingSource.length === 0) return
    root.core.castTo(target.id, root.pendingSource, root.pendingTitle)
    root.persistSettings({ lastTarget: target.id })
    root.pendingSource = ""
    root.pendingTitle = ""
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
    target: "omarchy.cast"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    // `omarchy-shell omarchy.cast play ~/film.mkv` - stage a file or URL and
    // open the picker. The obvious thing to bind a key to.
    function play(source: string): void { root.stagePath(source) }
    function stop(): void { if (root.core) root.core.stop() }
    function rescan(): void { if (root.core) root.core.scan() }
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

      DropArea {
        anchors.fill: parent
        onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
        onDropped: function (drop) {
          if (!drop.hasUrls) return
          root.stage(drop.urls)
          drop.accept(Qt.CopyAction)
        }
      }

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: "Cast"
          meta: root.core && root.core.casting
                ? "ON " + root.core.current.target.name.toUpperCase()
                : (root.core && root.core.scanning ? "LOOKING…" : "READY")
          foreground: root.barForeground
          fontFamily: root.fontFamily
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

        // ---------------- now playing ----------------
        Loader {
          width: parent.width
          active: !!(root.core && root.core.casting)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(6)
            readonly property real fraction:
              root.core.duration > 0
              ? Math.max(0, Math.min(1, root.core.position / root.core.duration)) : 0

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            Text {
              width: parent.width
              elide: Text.ElideMiddle
              text: root.core.title || root.core.current.title
              color: root.barForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Rectangle {
              width: parent.width
              height: Math.max(3, Style.space(3))
              radius: height / 2
              visible: root.core.duration > 0
              color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                             root.barForeground.b, 0.18)

              Rectangle {
                width: parent.width * fraction
                height: parent.height
                radius: parent.radius
                color: Color.accent
                Behavior on width { NumberAnimation { duration: 250 } }
              }

              MouseArea {
                anchors.fill: parent
                anchors.margins: -6
                cursorShape: Qt.PointingHandCursor
                onClicked: function (mouse) {
                  if (root.core.duration <= 0) return
                  root.core.seek(root.core.duration * (mouse.x / width))
                }
              }
            }

            Text {
              visible: root.core.duration > 0
              text: root.clock(root.core.position) + " / " + root.clock(root.core.duration)
              color: root.barForeground
              opacity: 0.7
              font.family: root.fontFamily
              font.pixelSize: Math.max(9, Style.font.caption - 2)
            }

            ButtonGroup {
              width: parent.width
              spacing: Style.space(6)
              value: ""
              foreground: root.barForeground
              accent: Color.accent
              fontFamily: root.fontFamily
              options: [
                { value: "back",   label: "−30s",  tooltip: "Back thirty seconds" },
                { value: "toggle", label: root.core.state === "PLAYING" ? "Pause" : "Play",
                  tooltip: "Play or pause on the television" },
                { value: "fwd",    label: "+30s",  tooltip: "Forward thirty seconds" },
                { value: "stop",   label: "Stop",  tooltip: "Stop and release the television" }
              ]
              onChanged: function (v) {
                if (v === "toggle") root.core.toggle()
                else if (v === "stop") root.core.stop()
                else if (v === "back") root.core.seek(Math.max(0, root.core.position - 30))
                else if (v === "fwd") root.core.seek(root.core.position + 30)
              }
            }
          }
        }

        // ---------------- staged media ----------------
        Loader {
          width: parent.width
          active: root.pendingSource.length > 0
          visible: active
          sourceComponent: Column {
            spacing: Style.space(4)

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            PanelSectionHeader {
              text: "READY TO PLAY — PICK A SCREEN"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Text {
              width: column.width
              elide: Text.ElideMiddle
              text: root.pendingTitle
              color: Color.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: "SCREENS"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !root.core || root.core.targets.length === 0
          text: root.core && root.core.scanning
                ? "Looking for televisions…"
                : "Nothing found. Chromecasts and smart TVs only answer when they are awake and on the same network."
          color: root.barForeground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.core ? root.core.targets : []

          Rectangle {
            width: column.width
            height: Math.round(Style.space(34))
            radius: Style.cornerRadius
            readonly property bool selectable:
              root.pendingSource.length > 0 && modelData.kind !== "airplay"
            color: targetMouse.containsMouse && selectable
                   ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.18)
                   : "transparent"
            opacity: modelData.kind === "airplay" ? 0.5 : 1.0

            Row {
              anchors { left: parent.left; verticalCenter: parent.verticalCenter
                        leftMargin: Style.space(6) }
              spacing: Style.space(8)

              Text {
                anchors.verticalCenter: parent.verticalCenter
                text: ""
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Column {
                anchors.verticalCenter: parent.verticalCenter
                Text {
                  text: modelData.name
                  color: root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Text {
                  text: root.kindLabel(modelData.kind) + "  ·  " + modelData.address
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
              visible: parent.selectable
              text: "Play "
              color: Color.accent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            MouseArea {
              id: targetMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: parent.selectable ? Qt.PointingHandCursor : Qt.ArrowCursor
              onClicked: {
                if (modelData.kind === "airplay") {
                  root.core.lastError =
                    modelData.name + " is an AirPlay receiver. Apple has never " +
                    "published the handshake its video path needs, so Omarchy " +
                    "can see it but cannot drive it."
                  return
                }
                root.pick(modelData)
              }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Item {
          width: parent.width
          height: rescan.implicitHeight

          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: "Drop a file here, or: omarchy-shell omarchy.cast play <file>"
            color: root.barForeground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 2)
          }

          PanelActionButton {
            id: rescan
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Look for devices again"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: if (root.core) root.core.scan()
          }
        }
      }
    }
  }
}
