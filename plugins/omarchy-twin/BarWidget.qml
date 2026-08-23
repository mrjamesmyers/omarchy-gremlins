// Twin - the bar cell. Quiet unless there is something to reclaim.

import QtQuick
import Quickshell
import QtQuick.Window
import qs.Commons
import qs.Ui

Item {
  id: root
  property var    bar
  property string moduleName
  property var    settings

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name
  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent
  readonly property bool hideWhenIdle: !(settings && settings.hideWhenIdle === false)
  readonly property var core: coreLoader.item

  Loader { id: coreLoader; active: root.ownsDaemon
           source: Qt.resolvedUrl("TwinCore.qml") }

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

  function openSettings() { toggle() }
  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.twin", "toggle"])
  }

  readonly property bool busy: core ? core.scanning : false
  readonly property bool found: core ? core.groups.length > 0 : false
  visible: !root.hideWhenIdle || root.busy || root.found

  implicitWidth: visible ? cell.implicitWidth : 0
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: root.found || root.busy ? Style.space(4) : 0

    Text {
      id: glyph
      anchors.verticalCenter: parent.verticalCenter
      text: ""
      color: root.found ? Color.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)
      SequentialAnimation on opacity {
        running: root.busy
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { to: 0.45; duration: 700 }
        NumberAnimation { to: 1.0;  duration: 700 }
        onRunningChanged: if (!running) glyph.opacity = 1.0
      }
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.found && !root.busy
      text: String(root.core ? root.core.groups.length : 0)
      color: Color.accent
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.toggle()
  }
}
