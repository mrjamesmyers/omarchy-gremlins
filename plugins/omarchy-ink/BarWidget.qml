// Ink - the bar cell.
//
// Drop a PDF on it and the editor opens. That is the whole entry point: the
// thing people want is "sign this and give it back", not a document manager.

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

  readonly property string pluginId: "io.github.mrjamesmyers.ink"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property string inkColour: (settings && settings.inkColour) || "#1a1a1a"
  readonly property real   inkWidth:  (settings && settings.inkWidth) || 2.5
  readonly property int    textSize:  (settings && settings.textSize) || 12
  readonly property bool   saveBeside: !(settings && settings.saveBeside === false)

  readonly property var core: coreLoader.item
  readonly property bool open: core ? core.open : false

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("InkCore.qml")
  }

  Loader {
    id: editorLoader
    active: root.ownsDaemon
    visible: false
    source: Qt.resolvedUrl("Editor.qml")
    onLoaded: { root.injectEditor(); Qt.callLater(root.injectEditor) }
  }

  function injectEditor() {
    var t = editorLoader.item
    if (!t) return
    if ("bar"        in t) t.bar        = root.bar
    if ("core"       in t) t.core       = coreLoader.item
    if ("hostWidget" in t) t.hostWidget = root
    if ("primary"    in t) t.primary    = root.ownsDaemon
    if ("inkColour"  in t) t.inkColour  = root.inkColour
    if ("inkWidth"   in t) t.inkWidth   = root.inkWidth
    if ("textSize"   in t) t.textSize   = root.textSize
    if ("saveBeside" in t) t.saveBeside = root.saveBeside
  }
  onBarChanged: injectEditor()
  onSettingsChanged: injectEditor()

  function openFile(path) {
    if (!root.core) return
    root.core.openDocument(path)
    if (editorLoader.item) editorLoader.item.show()
  }

  function openSettings() { toggle() }
  function toggle() {
    if (editorLoader.item && root.open) editorLoader.item.toggle()
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.ink", "toggle"])
  }

  implicitWidth: cell.implicitWidth
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: root.open ? Style.space(4) : 0

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: ""
      color: root.open ? Color.accent : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.open
      text: root.core && root.core.dirty ? "•" : ""
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

  DropArea {
    anchors.fill: parent
    onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
    onDropped: function (drop) {
      if (!drop.hasUrls) return
      var path = decodeURIComponent(String(drop.urls[0]).replace(/^file:\/\//, ""))
      if (path.toLowerCase().indexOf(".pdf") < 0) {
        if (root.core) root.core.lastError = "Ink only opens PDFs."
        return
      }
      root.openFile(path)
      drop.accept(Qt.CopyAction)
    }
  }
}
