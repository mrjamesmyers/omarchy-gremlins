// Gremlins — the bumper.
//
// Plays once, then gets out of the way. Never traps input, never persists.
// Esc dismisses. Per DHH's stated design (omarchy thread, 2026-08-19):
// one-off on boot by default; looping is something you opt into.

import QtQuick

Item {
  id: root
  anchors.fill: parent
  focus: true

  property var settings

  readonly property string src:
    (settings && settings.source && settings.source.length > 0)
      ? settings.source
      : Qt.resolvedUrl("assets/bumper.webp")

  // Opt-in loop mode. Default false — a disconnected laptop should pay nothing.
  readonly property bool loopForever: !!(settings && settings.loop)

  signal finished()

  opacity: 0
  Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutQuad } }
  Component.onCompleted: opacity = 1

  Rectangle { anchors.fill: parent; color: "black" }

  AnimatedImage {
    id: bumper
    anchors.fill: parent
    fillMode: Image.PreserveAspectCrop
    source: root.src
    playing: true
    cache: false
    asynchronous: true

    // Play exactly once unless the user opted into looping.
    onCurrentFrameChanged: {
      if (!root.loopForever && frameCount > 1 && currentFrame >= frameCount - 1) {
        playing = false
        root.dismiss()
      }
    }

    onStatusChanged: if (status === Image.Error) root.dismiss()
  }

  // Safety net: never let a decode stall leave a black surface on screen.
  Timer {
    interval: 8000
    running: !root.loopForever
    onTriggered: root.dismiss()
  }

  function dismiss() {
    opacity = 0
    hideTimer.start()
  }

  Timer {
    id: hideTimer
    interval: 240
    onTriggered: root.finished()
  }

  Keys.onEscapePressed: root.dismiss()

  MouseArea {
    anchors.fill: parent
    onClicked: root.dismiss()
  }
}
