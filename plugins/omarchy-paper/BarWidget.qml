// Paper - the bar cell.
//
// Silent when every printer is idle and nothing is queued, which is almost
// always. It appears when a job is in flight or a printer wants attention -
// out of paper, paused, low toner - because those are the only two moments
// anybody wants to be told about a printer.

import QtQuick
import Quickshell
import QtQuick.Window
import qs.Commons

Item {
  id: root

  property var    bar
  property string moduleName
  property var    settings

  readonly property string pluginId: "io.github.mrjamesmyers.paper"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property bool   hideWhenIdle: !(settings && settings.hideWhenIdle === false)
  readonly property int    pollSeconds: (settings && settings.pollSeconds) || 20
  readonly property string defaultQueue: (settings && settings.defaultQueue) || ""
  readonly property bool   duplex: !!(settings && settings.duplex)

  readonly property var core: coreLoader.item
  readonly property int jobCount: core ? core.jobs.length : 0
  readonly property bool attention: core ? core.attention : false
  readonly property bool printing: core ? core.busy > 0 : false

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("PaperCore.qml")
    onLoaded: item.pollSeconds = root.pollSeconds
  }
  onPollSecondsChanged: if (coreLoader.item) coreLoader.item.pollSeconds = root.pollSeconds

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
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.paper", "toggle"])
  }

  visible: !root.hideWhenIdle || root.jobCount > 0 || root.attention || root.printing

  readonly property color tint: {
    if (root.attention) return bar && bar.urgent ? bar.urgent : "#e0a352"
    if (root.printing || root.jobCount > 0) return Color.accent
    return root.foreground
  }

  readonly property string label: {
    if (root.jobCount > 0) return String(root.jobCount)
    if (root.attention) return "!"
    return ""
  }

  implicitWidth: visible ? cell.implicitWidth : 0
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: root.label.length > 0 ? Style.space(4) : 0

    Text {
      id: glyph
      anchors.verticalCenter: parent.verticalCenter
      text: ""
      color: root.tint
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.44)

      SequentialAnimation on opacity {
        running: root.printing
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { to: 0.5; duration: 800; easing.type: Easing.InOutQuad }
        NumberAnimation { to: 1.0; duration: 800; easing.type: Easing.InOutQuad }
        onRunningChanged: if (!running) glyph.opacity = 1.0
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

  // Drop a document on the bar and it prints. This is the shortest path from a
  // file manager to paper that exists on any desktop.
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
}
