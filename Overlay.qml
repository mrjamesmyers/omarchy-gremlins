// Gremlins - the bumper.
//
// Plays once on summon, on EVERY screen, then gets out of the way.
// Per DHH's stated design (omarchy thread, 2026-08-19): one-off on boot by
// default; looping is opt-in.
//
// Contract, read out of shell/shell.qml rather than guessed:
//   summon -> deliverIfLoaded() calls open(payloadJson) on this item
//   hide   -> invokeIfLoaded() calls close()
//   isPluginOpen() reads the `opened` property
//
// One PanelWindow per output via Variants on Quickshell.screens - the same
// pattern the first-party background and notification plugins use. A single
// MediaPlayer can only drive one VideoOutput, so each screen gets its own
// decoder. That costs ~5% CPU per output for three seconds, which is the right
// trade at realistic monitor counts; mirroring one decode across outputs is a
// lot of machinery to save very little.
//
// QtMultimedia rather than AnimatedImage: Omarchy's Qt ships no webp image
// plugin (imageformats is gif/ico/jpeg/pdf/svg), but does ship
// qt6-multimedia-ffmpeg. mp4 also carries its own audio track.

import Quickshell
import Quickshell.Wayland
import QtQuick
import QtMultimedia

Item {
  id: root

  property bool opened: false
  property string source: Qt.resolvedUrl("assets/bumper.mp4")
  property bool loopForever: false
  property bool soundOn: true

  // Sound belongs to exactly one output. Without this every screen decodes its
  // own audio track and you hear the scream N times, slightly out of phase.
  property string audioScreen: ""

  function open(payload) {
    try {
      if (payload && payload.length > 2) {
        var p = JSON.parse(payload)
        if (p.source) root.source = p.source
        if (p.loop !== undefined) root.loopForever = !!p.loop
        if (p.sound !== undefined) root.soundOn = !!p.sound
      }
    } catch (e) { console.warn("gremlins: bad payload", e) }

    var screens = Quickshell.screens
    root.audioScreen = (screens && screens.length > 0) ? screens[0].name : ""

    root.opened = true
    // The stall guard stops a failed decode leaving a black screen up. In loop
    // mode long playback is the point, so arming it there would strangle the
    // feature it exists to protect.
    if (root.loopForever) guard.stop(); else guard.restart()
  }

  function close() {
    guard.stop()
    root.opened = false   // destroys the delegates, which tears down every decoder
  }

  Timer {
    id: guard
    interval: 9000
    running: false
    onTriggered: root.close()
  }

  Variants {
    // Empty model when closed => all windows and players are destroyed.
    model: root.opened ? Quickshell.screens : []

    delegate: Component {
      PanelWindow {
        id: panel
        required property var modelData

        screen: modelData
        anchors { top: true; bottom: true; left: true; right: true }
        color: "black"
        WlrLayershell.namespace: "omarchy-gremlins"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
        exclusionMode: ExclusionMode.Ignore

        VideoOutput {
          id: vout
          anchors.fill: parent
          fillMode: VideoOutput.PreserveAspectCrop
        }

        MediaPlayer {
          id: player
          source: root.source
          videoOutput: vout
          loops: root.loopForever ? MediaPlayer.Infinite : 1
          audioOutput: AudioOutput {
            volume: (root.soundOn && panel.modelData.name === root.audioScreen) ? 1.0 : 0.0
          }
          Component.onCompleted: play()
          onMediaStatusChanged: {
            if (mediaStatus === MediaPlayer.EndOfMedia && !root.loopForever) root.close()
            if (mediaStatus === MediaPlayer.InvalidMedia) {
              console.warn("gremlins: cannot play", root.source, errorString)
              root.close()
            }
          }
        }

        MouseArea { anchors.fill: parent; onClicked: root.close() }
        Keys.onEscapePressed: root.close()
        Component.onCompleted: forceActiveFocus()
      }
    }
  }
}
