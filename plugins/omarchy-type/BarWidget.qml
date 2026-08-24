// Type - the bar cell. Drop a font file on it to install.

import QtQuick
import Quickshell
import QtQuick.Window
import qs.Commons

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
  readonly property var core: coreLoader.item

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("TypeCore.qml")
  }

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
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.type", "toggle"])
  }

  implicitWidth: cell.implicitWidth
  implicitHeight: root.sz

  Text {
    id: cell
    anchors.centerIn: parent
    text: ""
    color: root.foreground
    font.family: root.fontFamily
    font.pixelSize: Math.round(root.sz * 0.46)
  }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: root.toggle()
  }

  DropArea {
    anchors.fill: parent
    onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
    onDropped: function (drop) {
      if (!drop.hasUrls || !root.core) return
      for (var i = 0; i < drop.urls.length; i++)
        root.core.install(decodeURIComponent(String(drop.urls[i]).replace(/^file:\/\//, "")))
      drop.accept(Qt.CopyAction)
    }
  }
}
