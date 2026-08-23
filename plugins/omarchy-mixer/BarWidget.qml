// Mixer - the bar cell.
//
// Scroll on it to change the current output's volume, click for the panel,
// middle-click to mute. The number is how many applications are actually
// making noise right now, not how many have an audio stream open - a paused
// video is not something you need to be told about.

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

  readonly property string pluginId: "io.github.mrjamesmyers.mixer"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property bool showStreamCount: !(settings && settings.showStreamCount === false)
  readonly property bool moveStreams: !(settings && settings.moveStreamsOnSwitch === false)
  readonly property int  scrollStep: (settings && settings.scrollStep) || 5

  readonly property var core: coreLoader.item
  readonly property var output: core ? core.currentOutput : null
  readonly property int playing: core ? core.playing : 0

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("MixerCore.qml")
    onLoaded: item.moveStreamsOnSwitch = root.moveStreams
  }
  onMoveStreamsChanged: if (coreLoader.item) coreLoader.item.moveStreamsOnSwitch = root.moveStreams

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
  onSettingsChanged: { injectPanel(); if (coreLoader.item) coreLoader.item.moveStreamsOnSwitch = root.moveStreams }

  function openSettings() { toggle() }
  function toggle() {
    if (panelLoader.item) panelLoader.item.toggle()
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.mixer", "toggle"])
  }

  readonly property string glyph: {
    if (!output) return ""
    if (output.mute) return ""
    if (output.volume < 0.01) return ""
    if (output.volume < 0.5) return ""
    return ""
  }

  implicitWidth: cell.implicitWidth
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: Style.space(4)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.glyph
      color: root.output && root.output.mute
             ? (bar ? bar.urgent : root.foreground) : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.showStreamCount && root.playing > 0
      text: String(root.playing)
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
      if (mouse.button === Qt.MiddleButton && root.core && root.output)
        root.core.setSinkMute(root.output.index, !root.output.mute)
      else
        root.toggle()
    }

    onWheel: function (wheel) {
      if (!root.core || !root.output) return
      var step = (wheel.angleDelta.y > 0 ? 1 : -1) * (root.scrollStep / 100)
      root.core.setSinkVolume(root.output.index,
                              Math.max(0, Math.min(1, root.output.volume + step)))
    }
  }
}
