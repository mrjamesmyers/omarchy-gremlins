// Lens - the panel.
//
// Grouped by what a person is trying to fix, not by which hyprctl key it maps
// to. Anything this Hyprland cannot do is shown disabled with the reason,
// rather than hidden or - worse - shown as a control that quietly does nothing.

import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.lens"
  ipcTarget: "omarchy.lens"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool rigidZoom: setting("rigidZoom", false) === true

  readonly property var correctFilters: [
    "protanopia-correct", "deuteranopia-correct", "tritanopia-correct"
  ]
  readonly property var toneFilters: [
    "high-contrast", "invert", "greyscale", "dim"
  ]
  readonly property var simulateFilters: [
    "protanopia-simulate", "deuteranopia-simulate", "tritanopia-simulate"
  ]

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

  function toggleFilter(name) {
    if (!root.core) return
    root.core.setFilter(root.core.filter === name ? "" : name)
  }

  // Check the bar's own colours, which is the one pair we can read without
  // asking the user to type anything.
  function checkBarContrast() {
    if (!root.core || !bar) return
    root.core.checkContrast(String(bar.foreground), String(bar.background), false)
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.lens"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    // Worth binding to keys in hyprland.conf.
    function zoomIn(): void  { if (root.core) root.core.zoomBy(0.5) }
    function zoomOut(): void { if (root.core) root.core.zoomBy(-0.5) }
    function locate(): void  { if (root.core) root.core.locate() }
    function filter(name: string): void { if (root.core) root.core.setFilter(name) }
    function reset(): void   { if (root.core) root.core.reset() }
  }

  component FilterChips: Flow {
    id: chips
    property var names: []
    spacing: Style.space(5)

    Repeater {
      model: chips.names
      Rectangle {
        readonly property bool on: root.core && root.core.filter === modelData
        height: Math.round(Style.space(22))
        width: chipLabel.implicitWidth + Style.space(16)
        radius: Style.cornerRadius
        color: on ? Color.accent
                  : Qt.rgba(root.barForeground.r, root.barForeground.g,
                            root.barForeground.b, chipMouse.containsMouse ? 0.16 : 0.08)
        opacity: (root.core && root.core.canFilter) ? 1.0 : 0.4

        Text {
          id: chipLabel
          anchors.centerIn: parent
          text: root.core ? root.core.filterLabel(modelData) : modelData
          color: parent.on ? (bar ? bar.background : "black") : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 1)
        }

        MouseArea {
          id: chipMouse
          anchors.fill: parent
          hoverEnabled: true
          enabled: root.core && root.core.canFilter
          cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
          onClicked: root.toggleFilter(modelData)
        }
      }
    }
  }

  KeyboardPanel {
    id: panel

    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(400))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: "Lens"
          meta: root.core && root.core.active ? "ACTIVE" : "ACCESSIBILITY"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !!(root.core && !root.core.hasHyprctl)
          text: "hyprctl is not on PATH, so none of this can be applied."
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
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

        // ---------------- magnifier ----------------
        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: root.core && root.core.canMagnify ? "MAGNIFIER"
                                                  : "MAGNIFIER — NOT AVAILABLE"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Item {
          width: parent.width
          height: Math.round(Style.space(26))
          opacity: (root.core && root.core.canMagnify) ? 1.0 : 0.4

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: root.core && root.core.zoom > 1.0
                  ? root.core.zoom.toFixed(1) + "×" : "off"
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            spacing: Style.space(4)

            Repeater {
              model: [1.0, 1.5, 2.0, 3.0, 4.0]
              Rectangle {
                readonly property bool on:
                  root.core && Math.abs(root.core.zoom - modelData) < 0.01
                width: Math.round(Style.space(30))
                height: Math.round(Style.space(22))
                radius: Style.cornerRadius
                color: on ? Color.accent
                          : Qt.rgba(root.barForeground.r, root.barForeground.g,
                                    root.barForeground.b, 0.08)

                Text {
                  anchors.centerIn: parent
                  text: modelData === 1.0 ? "off" : modelData.toFixed(modelData % 1 ? 1 : 0) + "×"
                  color: parent.on ? (bar ? bar.background : "black") : root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 1)
                }

                MouseArea {
                  anchors.fill: parent
                  enabled: root.core && root.core.canMagnify
                  cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                  onClicked: root.core.setZoom(modelData)
                }
              }
            }
          }
        }

        Toggle {
          width: parent.width
          label: "Rigid magnifier"
          description: "Follows the pointer exactly instead of drifting toward it."
          checked: root.rigidZoom
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: {
            root.persistSettings({ rigidZoom: !root.rigidZoom })
            if (root.core) root.core.setRigid(!root.rigidZoom)
          }
        }

        // ---------------- colour vision ----------------
        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: root.core && root.core.canFilter ? "COLOUR VISION"
                                                 : "COLOUR VISION — NO SCREEN SHADER"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          text: "Redistributes the colours a dichromat cannot separate into ones they can."
          color: root.barForeground
          opacity: 0.6
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
          wrapMode: Text.WordWrap
        }

        FilterChips { width: parent.width; names: root.correctFilters }

        // ---------------- contrast and tone ----------------
        PanelSectionHeader {
          text: "CONTRAST AND TONE"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        FilterChips { width: parent.width; names: root.toneFilters }

        // ---------------- simulate ----------------
        PanelSectionHeader {
          text: "SIMULATE — FOR CHECKING A THEME"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          text: "Shows the desktop as a dichromat sees it. For designing, not for using."
          color: root.barForeground
          opacity: 0.6
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
          wrapMode: Text.WordWrap
        }

        FilterChips { width: parent.width; names: root.simulateFilters }

        // ---------------- motion and cursor ----------------
        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Toggle {
          width: parent.width
          label: "Reduce motion"
          description: "Turns off window animations. Helps vestibular sensitivity."
          checked: !!(root.core && !root.core.animations)
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: if (root.core) root.core.setAnimations(!root.core.animations)
        }

        Item {
          width: parent.width
          height: Math.round(Style.space(26))

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "Cursor size"
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Row {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
            spacing: Style.space(4)

            Repeater {
              model: [24, 32, 48, 64]
              Rectangle {
                readonly property bool on: root.core && root.core.cursorSize === modelData
                width: Math.round(Style.space(30))
                height: Math.round(Style.space(22))
                radius: Style.cornerRadius
                color: on ? Color.accent
                          : Qt.rgba(root.barForeground.r, root.barForeground.g,
                                    root.barForeground.b, 0.08)
                Text {
                  anchors.centerIn: parent
                  text: String(modelData)
                  color: parent.on ? (bar ? bar.background : "black") : root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 1)
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: if (root.core) root.core.setCursorSize(modelData)
                }
              }
            }
          }
        }

        // ---------------- contrast checker ----------------
        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Item {
          width: parent.width
          height: checkButton.implicitHeight

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: parent.width - checkButton.width - Style.space(8)
            wrapMode: Text.WordWrap
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 1)
            text: root.core && root.core.contrast
                  ? ("Bar text " + root.core.contrast.ratio + ":1 — "
                     + root.core.contrast.verdict
                     + (root.core.contrast.verdict === "fail"
                        ? "  (WCAG wants 4.5:1)" : ""))
                  : "Check this theme's bar text against WCAG"
          }

          PanelActionButton {
            id: checkButton
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Measure the bar's contrast ratio"
            foreground: root.core && root.core.contrast
                        && root.core.contrast.verdict === "fail"
                        ? (bar ? bar.urgent : root.barForeground)
                        : root.barForeground
            fontFamily: root.fontFamily
            onClicked: root.checkBarContrast()
          }
        }

        Item {
          width: parent.width
          height: resetButton.implicitHeight

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: "Settings persist and are re-applied on login"
            color: root.barForeground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 2)
          }

          PanelActionButton {
            id: resetButton
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Turn everything off"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: if (root.core) root.core.reset()
          }
        }
      }
    }
  }
}
