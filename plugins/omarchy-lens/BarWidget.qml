// Lens - the bar cell.
//
// Scroll to magnify, middle-click to find the pointer, click for everything
// else. The cell stays visible by default even when nothing is active: an
// accessibility control that hides itself until you already know how to turn
// it on is not a control anyone will find.

import QtQuick
import Quickshell
import Quickshell.Wayland
import QtQuick.Window
import qs.Commons

Item {
  id: root

  property var    bar
  property string moduleName
  property var    settings

  readonly property string pluginId: "io.github.mrjamesmyers.lens"

  readonly property bool ownsDaemon:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property color  foreground: bar ? bar.foreground : Color.accent

  readonly property real zoomStep: (settings && settings.zoomStep) || 0.5
  readonly property bool showWhenInactive: !(settings && settings.showWhenInactive === false)
  readonly property bool locateOnClick: !(settings && settings.locateOnClick === false)
  readonly property bool rigidZoom: !!(settings && settings.rigidZoom)

  readonly property var core: coreLoader.item
  readonly property bool active: core ? core.active : false

  Loader {
    id: coreLoader
    active: root.ownsDaemon
    source: Qt.resolvedUrl("LensCore.qml")
    onLoaded: item.setRigid(root.rigidZoom)
  }
  onRigidZoomChanged: if (coreLoader.item) coreLoader.item.setRigid(root.rigidZoom)

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
    else Quickshell.execDetached(["omarchy-shell", "-q", "omarchy.lens", "toggle"])
  }

  visible: root.showWhenInactive || root.active

  readonly property string glyph: {
    if (!core) return ""
    if (core.zoom > 1.0) return ""
    if (core.filter.length > 0) return ""
    return ""
  }

  readonly property string label: {
    if (!core) return ""
    if (core.zoom > 1.0) return core.zoom.toFixed(1) + "×"
    return ""
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
      color: root.active ? Color.accent : root.foreground
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
      if (mouse.button === Qt.MiddleButton && root.locateOnClick && root.core)
        root.core.locate()
      else
        root.toggle()
    }

    onWheel: function (wheel) {
      if (!root.core || !root.core.canMagnify) return
      root.core.zoomBy(wheel.angleDelta.y > 0 ? root.zoomStep : -root.zoomStep)
    }
  }

  // ---- find the pointer -------------------------------------------------
  //
  // A ring that pulses once where the cursor is. Built only while it is
  // playing: a layer surface that exists all session costs a surface all
  // session, and this is on screen for well under a second.

  property bool locating: false

  Connections {
    target: coreLoader.item
    function onCursorLocated() {
      if (!root.ownsDaemon) return
      root.locating = true
      hideLocator.restart()
    }
  }

  Timer {
    id: hideLocator
    interval: 900
    onTriggered: root.locating = false
  }

  Loader {
    active: root.locating
    sourceComponent: PanelWindow {
      anchors { top: true; bottom: true; left: true; right: true }
      color: "transparent"
      WlrLayershell.namespace: "omarchy-lens-locator"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
      exclusionMode: ExclusionMode.Ignore
      mask: Region {}          // never takes a click

      Item {
        anchors.fill: parent

        Repeater {
          model: 3
          Rectangle {
            readonly property int ringSize: 40 + index * 46
            width: ringSize
            height: ringSize
            radius: ringSize / 2
            x: (root.core ? root.core.cursorX : 0) - ringSize / 2
            y: (root.core ? root.core.cursorY : 0) - ringSize / 2
            color: "transparent"
            border.width: 3
            border.color: Color.accent
            opacity: 0

            SequentialAnimation on opacity {
              running: true
              PauseAnimation { duration: index * 110 }
              NumberAnimation { to: 0.85; duration: 120 }
              NumberAnimation { to: 0.0; duration: 480; easing.type: Easing.OutQuad }
            }
            SequentialAnimation on scale {
              running: true
              PauseAnimation { duration: index * 110 }
              NumberAnimation { from: 0.4; to: 1.0; duration: 600; easing.type: Easing.OutQuad }
            }
          }
        }
      }
    }
  }
}
