// Mixer - the panel.
//
// Applications first, because that is what people came for; the output picker
// underneath. Each application row is a slider you can drag, a mute button,
// and - if there is more than one output - the name of the device it is
// playing to, which you can click to send it somewhere else.

import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.mixer"
  ipcTarget: "omarchy.mixer"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property bool overdrive: setting("allowOverdrive", false) === true
  readonly property real ceiling: root.overdrive ? 1.5 : 1.0

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

  // Cycle a stream to the next output. With two devices - which is the common
  // case, speakers and headphones - this is a single click, and a dropdown
  // would be three.
  function cycleOutput(stream) {
    if (!root.core || root.core.outputs.length < 2) return
    var outs = root.core.outputs
    var at = 0
    for (var i = 0; i < outs.length; i++)
      if (outs[i].name === stream.sinkName) { at = i; break }
    root.core.move(stream.id, outs[(at + 1) % outs.length].name)
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.mixer"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function refresh(): void { if (root.core) root.core.refresh() }
  }

  // A slider that reports while you drag it rather than only on release.
  component VolumeSlider: Item {
    id: slider
    property real value: 0
    property real ceiling: 1.0
    property color fill: Color.accent
    property color track: Qt.rgba(0, 0, 0, 0.18)
    signal moved(real value)

    implicitHeight: Math.max(6, Style.space(6))

    Rectangle {
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width
      height: Math.max(4, Style.space(4))
      radius: height / 2
      color: slider.track

      Rectangle {
        width: parent.width * Math.max(0, Math.min(1, slider.value / slider.ceiling))
        height: parent.height
        radius: parent.radius
        color: slider.fill
      }

      // The 100% mark, so overdrive is visible rather than a surprise.
      Rectangle {
        visible: slider.ceiling > 1.0
        x: parent.width * (1.0 / slider.ceiling) - width / 2
        width: 2
        height: parent.height + 4
        anchors.verticalCenter: parent.verticalCenter
        color: Qt.rgba(1, 1, 1, 0.35)
      }
    }

    MouseArea {
      anchors.fill: parent
      anchors.margins: -6
      cursorShape: Qt.PointingHandCursor
      preventStealing: true

      function report(mouseX) {
        var fraction = Math.max(0, Math.min(1, mouseX / slider.width))
        slider.moved(fraction * slider.ceiling)
      }
      onPressed: function (mouse) { report(mouse.x) }
      onPositionChanged: function (mouse) { if (pressed) report(mouse.x) }
      onWheel: function (wheel) {
        var step = (wheel.angleDelta.y > 0 ? 0.05 : -0.05) * slider.ceiling
        slider.moved(Math.max(0, Math.min(slider.ceiling, slider.value + step)))
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
          title: "Mixer"
          meta: root.core && root.core.playing > 0
                ? root.core.playing + (root.core.playing === 1 ? " APP PLAYING" : " APPS PLAYING")
                : "NOTHING PLAYING"
          foreground: root.barForeground
          fontFamily: root.fontFamily
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

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: "APPLICATIONS"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !root.core || root.core.streams.length === 0
          text: "Nothing is playing. Applications appear here as soon as they open an audio stream."
          color: root.barForeground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Repeater {
          model: root.core ? root.core.streams : []

          Column {
            width: column.width
            spacing: Style.space(3)
            opacity: modelData.corked ? 0.55 : 1.0

            Item {
              width: parent.width
              height: muteButton.implicitHeight

              Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: Style.space(6)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.name
                  color: root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  visible: modelData.detail.length > 0
                  text: modelData.detail
                  color: root.barForeground
                  opacity: 0.5
                  elide: Text.ElideRight
                  width: Math.min(implicitWidth, Style.space(150))
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 2)
                }
              }

              Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: Style.space(6)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: Math.round(modelData.volume * 100) + "%"
                  color: root.barForeground
                  opacity: 0.6
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 2)
                }

                PanelActionButton {
                  id: muteButton
                  iconText: modelData.mute ? "" : ""
                  tooltipText: modelData.mute ? "Unmute" : "Mute"
                  foreground: modelData.mute
                              ? (bar ? bar.urgent : root.barForeground)
                              : root.barForeground
                  fontFamily: root.fontFamily
                  onClicked: root.core.setMute(modelData.id, !modelData.mute)
                }
              }
            }

            VolumeSlider {
              width: parent.width
              value: modelData.volume
              ceiling: root.ceiling
              fill: modelData.mute
                    ? Qt.rgba(root.barForeground.r, root.barForeground.g,
                              root.barForeground.b, 0.3)
                    : Color.accent
              track: Qt.rgba(root.barForeground.r, root.barForeground.g,
                             root.barForeground.b, 0.16)
              onMoved: function (v) {
                root.core.nudgeLocally(modelData.id, v)
                root.core.setVolume(modelData.id, v)
              }
            }

            // Where this application is playing. Only worth showing when
            // there is somewhere else it could go.
            Text {
              visible: root.core && root.core.outputs.length > 1
              text: "→ " + (function () {
                for (var i = 0; i < root.core.outputs.length; i++)
                  if (root.core.outputs[i].name === modelData.sinkName)
                    return root.core.outputs[i].label
                return modelData.sinkName
              })()
              color: Color.accent
              opacity: 0.85
              font.family: root.fontFamily
              font.pixelSize: Math.max(9, Style.font.caption - 2)

              MouseArea {
                anchors.fill: parent
                anchors.margins: -4
                cursorShape: Qt.PointingHandCursor
                onClicked: root.cycleOutput(modelData)
              }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        PanelSectionHeader {
          text: "OUTPUT"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Repeater {
          model: root.core ? root.core.outputs : []

          Column {
            width: column.width
            spacing: Style.space(3)

            Item {
              width: parent.width
              height: Math.round(Style.space(20))

              Row {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                spacing: Style.space(6)

                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: 7; height: 7; radius: 3.5
                  color: modelData.isDefault ? Color.accent
                         : Qt.rgba(root.barForeground.r, root.barForeground.g,
                                   root.barForeground.b, 0.3)
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.label
                  color: root.barForeground
                  opacity: modelData.isDefault ? 1.0 : 0.75
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Text {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                text: Math.round(modelData.volume * 100) + "%"
                color: root.barForeground
                opacity: 0.6
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 2)
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: modelData.isDefault ? Qt.ArrowCursor : Qt.PointingHandCursor
                onClicked: if (!modelData.isDefault) root.core.chooseOutput(modelData.name)
              }
            }

            VolumeSlider {
              width: parent.width
              visible: modelData.isDefault
              value: modelData.volume
              ceiling: root.ceiling
              fill: modelData.mute
                    ? Qt.rgba(root.barForeground.r, root.barForeground.g,
                              root.barForeground.b, 0.3)
                    : Color.accent
              track: Qt.rgba(root.barForeground.r, root.barForeground.g,
                             root.barForeground.b, 0.16)
              onMoved: function (v) { root.core.setSinkVolume(modelData.index, v) }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Toggle {
          width: parent.width
          label: "Allow above 100%"
          description: "Useful for quiet recordings. Unkind to speakers."
          checked: root.overdrive
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ allowOverdrive: !root.overdrive })
        }
      }
    }
  }
}
