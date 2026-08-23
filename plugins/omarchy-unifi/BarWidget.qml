// UniFi - the bar cell.
//
// A health dot and a client count. The dot is the whole point: green when
// every adopted device is online, amber when something is not, red when the
// console cannot be reached or will not take the key.

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

  readonly property string pluginId: "io.github.mrjamesmyers.unifi"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property string host:    (settings && settings.host) || ""
  readonly property int    port:    (settings && settings.port) || 443
  readonly property string site:    (settings && settings.site) || ""
  readonly property string keyFile: (settings && settings.keyFile) || ""
  readonly property int    pollSeconds: (settings && settings.pollSeconds) || 20
  readonly property bool   showClientCount: !(settings && settings.showClientCount === false)

  readonly property var core: coreLoader.item

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("UnifiCore.qml")
    onLoaded: root.pushSettings()
  }

  function pushSettings() {
    var c = coreLoader.item
    if (!c) return
    c.host = root.host
    c.port = root.port
    c.site = root.site
    c.keyFile = root.keyFile
    c.pollSeconds = root.pollSeconds
  }
  onSettingsChanged: { pushSettings(); injectPanel() }

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
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.unifi", "toggle"])
  }

  readonly property color dot: {
    if (!core || !core.configured) return Qt.rgba(root.foreground.r, root.foreground.g,
                                                  root.foreground.b, 0.35)
    if (core.problem) return bar && bar.urgent ? bar.urgent : "#e05252"
    if (core.degraded) return "#e0a352"
    if (core.healthy) return "#5fd18a"
    return Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.35)
  }

  readonly property string label: {
    if (!core || !core.configured) return "set up"
    if (core.authError.length > 0) return "key"
    if (core.lastError.length > 0) return "offline"
    if (!root.showClientCount) return ""
    return core.clientCount > 0 ? String(core.clientCount) : ""
  }

  implicitWidth: cell.implicitWidth
  implicitHeight: root.sz

  Row {
    id: cell
    anchors.centerIn: parent
    spacing: Style.space(5)

    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: ""
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Math.round(root.sz * 0.42)
    }

    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: Math.max(6, Math.round(root.sz * 0.18))
      height: width
      radius: width / 2
      color: root.dot

      // Amber and red pulse; green does not. Steady state should be silent.
      SequentialAnimation on opacity {
        running: !!(root.core && (root.core.problem || root.core.degraded))
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { to: 0.35; duration: 900; easing.type: Easing.InOutQuad }
        NumberAnimation { to: 1.0;  duration: 900; easing.type: Easing.InOutQuad }
      }
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.label.length > 0
      text: root.label
      color: root.foreground
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
}
