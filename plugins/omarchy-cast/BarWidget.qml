// Cast - the bar cell.
//
// Idle it is a cast glyph and nothing else. Casting, it shows what is playing
// and turns into a transport control: click toggles play/pause, right-click
// opens the panel. Files dropped on it are staged for the next device you pick.

import QtQuick
import Quickshell
import Quickshell.Io
import QtQuick.Window
import qs.Commons
import qs.Ui

Item {
  id: root

  property var    bar
  property string moduleName
  property var    settings

  readonly property string pluginId: "io.github.mrjamesmyers.cast"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property bool hideWhenIdle: !!(settings && settings.hideWhenIdle)
  readonly property int  rescanSeconds: (settings && settings.rescanSeconds) || 300

  readonly property var core: coreLoader.item
  readonly property bool casting: core ? core.casting : false
  readonly property string state: core ? core.state : ""

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("CastCore.qml")
    onLoaded: item.rescanSeconds = root.rescanSeconds
  }
  onRescanSecondsChanged: if (coreLoader.item) coreLoader.item.rescanSeconds = root.rescanSeconds

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
  onSettingsChanged: injectPanel()

  function openSettings() { openPanel() }
  function openPanel() {
    if (panelLoader.item) panelLoader.item.toggle()
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.cast", "toggle"])
  }

  // The cell can disappear entirely when idle, but only if the user asked -
  // a widget that vanishes without being told to is a widget people think
  // crashed.
  visible: !root.hideWhenIdle || root.casting

  readonly property string glyph: {
    if (!root.casting) return ""
    if (root.state === "PLAYING") return ""
    if (root.state === "PAUSED") return ""
    return ""
  }

  readonly property string label: {
    if (!root.casting || !root.core) return ""
    var name = root.core.current ? root.core.current.target.name : ""
    return name.length > 18 ? name.substring(0, 17) + "…" : name
  }

  implicitWidth: visible ? cell.implicitWidth : 0
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: root.label.length > 0 ? Style.space(4) : 0

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.glyph
      color: root.casting ? Color.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.label.length > 0
      text: root.label
      color: Color.accent
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
    cursorShape: Qt.PointingHandCursor
    onClicked: function (mouse) {
      if (mouse.button === Qt.LeftButton && root.casting && root.core) root.core.toggle()
      else if (mouse.button === Qt.MiddleButton && root.core) root.core.stop()
      else root.openPanel()
    }
    onWheel: function (wheel) {
      if (!root.casting || !root.core || root.core.volume < 0) return
      var step = wheel.angleDelta.y > 0 ? 0.05 : -0.05
      root.core.setVolume(Math.max(0, Math.min(1, root.core.volume + step)))
    }
  }

  DropArea {
    anchors.fill: parent
    onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
    onDropped: function (drop) {
      if (!drop.hasUrls || !panelLoader.item) return
      panelLoader.item.stage(drop.urls)
      drop.accept(Qt.CopyAction)
    }
  }
}
