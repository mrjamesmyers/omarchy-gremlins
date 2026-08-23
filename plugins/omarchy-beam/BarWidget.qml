// Beam - the bar cell.
//
// Shows one of three things, in order of how much the user needs to know:
// a transfer in flight, a request waiting to be answered, or how many devices
// are within reach. Clicking opens the panel; that is the whole interaction.
//
// The bar instantiates one of these per monitor. Only the copy on the first
// screen owns the helper process, because a network daemon that binds a port
// does not want three of itself. The others are display-only and hand their
// clicks to the owner over IPC.

import QtQuick
import Quickshell
import Quickshell.Io
import QtQuick.Window
import qs.Commons
import qs.Ui

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property string pluginId: "io.github.mrjamesmyers.beam"

  // One monitor owns the daemon. Everything else mirrors nothing and simply
  // opens the panel where the daemon lives.
  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  // ---- settings ----
  readonly property string aliasSetting:  (settings && settings.alias) || ""
  readonly property string dirSetting:    (settings && settings.downloadDir) || ""
  readonly property bool   autoAccept:    !!(settings && settings.autoAccept)
  readonly property string pinSetting:    (settings && settings.pin) || ""
  readonly property bool   quiet:         !!(settings && settings.quiet)
  readonly property bool   notifyOnReceive: !(settings && settings.notifyOnReceive === false)

  // ---- live state ----
  readonly property var core: coreLoader.item
  readonly property int peerCount: core ? core.peers.length : 0
  readonly property var transfer: core ? core.transfer : null
  readonly property var pending: core ? core.pending : null

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("BeamCore.qml")
    onLoaded: root.pushSettings()
  }

  function pushSettings() {
    var c = coreLoader.item
    if (!c) return
    c.alias_ = root.aliasSetting
    c.downloadDir = root.dirSetting
    c.autoAccept = root.autoAccept
    c.pin = root.pinSetting
    c.quiet = root.quiet
    c.notifyOnReceive = root.notifyOnReceive
  }
  onSettingsChanged: pushSettings()

  Loader {
    id: panelLoader
    active: root.ownsDaemon
    visible: false
    source: Qt.resolvedUrl("Panel.qml")
    onLoaded: { root.injectPanel(); Qt.callLater(root.injectPanel) }
  }

  function injectPanel() {
    var t = panelLoader.item
    if (!t) return
    if ("bar"        in t) t.bar        = root.bar
    if ("settings"   in t) t.settings   = root.settings
    if ("anchorItem" in t) t.anchorItem = cell
    if ("hostWidget" in t) t.hostWidget = root
    if ("core"       in t) t.core       = coreLoader.item
    if ("primary"    in t) t.primary    = root.ownsDaemon
  }
  onBarChanged: injectPanel()

  function openSettings() { toggle() }
  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.beam", "toggle"])
  }

  // ---- what the cell says ---------------------------------------------

  readonly property real progress: {
    if (!transfer || !transfer.total || transfer.total <= 0) return 0
    return Math.max(0, Math.min(1, transfer.bytes / transfer.total))
  }

  readonly property string glyph: {
    if (transfer) return transfer.direction === "in" ? "" : ""
    if (pending) return ""
    return ""
  }

  readonly property string label: {
    if (transfer) return Math.round(root.progress * 100) + "%"
    if (pending) return "?"
    if (peerCount > 0) return String(peerCount)
    return ""
  }

  readonly property color tint: {
    if (pending) return bar && bar.urgent ? bar.urgent : Color.accent
    if (transfer) return Color.accent
    if (core && core.lastError.length > 0 && !core.ready)
      return bar && bar.urgent ? bar.urgent : root.foreground
    return root.foreground
  }

  implicitWidth: cell.implicitWidth
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: root.label.length > 0 ? Style.space(4) : 0

    Text {
      id: icon
      anchors.verticalCenter: parent.verticalCenter
      text: root.glyph
      color: root.tint
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)

      // A quiet pulse while something is moving. Cheap: one opacity
      // animation on one text item, and it stops dead when idle rather than
      // idling a timer for the life of the shell.
      SequentialAnimation on opacity {
        running: root.transfer !== null || root.pending !== null
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { to: 0.45; duration: 700; easing.type: Easing.InOutQuad }
        NumberAnimation { to: 1.0;  duration: 700; easing.type: Easing.InOutQuad }
        onRunningChanged: if (!running) icon.opacity = 1.0
      }
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.label.length > 0
      text: root.label
      color: root.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.PointingHandCursor
    onClicked: root.toggle()
  }

  // Files can be dropped straight onto the bar cell, which is the shortest
  // path there is from a file manager to another device: drag, hover, drop,
  // pick a name.
  DropArea {
    anchors.fill: parent
    onEntered: function (drag) {
      if (drag.hasUrls) drag.accept(Qt.CopyAction)
    }
    onDropped: function (drop) {
      if (!drop.hasUrls || !panelLoader.item) return
      panelLoader.item.stageForSending(drop.urls)
      drop.accept(Qt.CopyAction)
    }
  }
}
