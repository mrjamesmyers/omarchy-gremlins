// Gremlins - the bumper.
//
// Plays once on summon, then gets out of the way. Per DHH's stated design
// (omarchy thread, 2026-08-19): one-off on boot by default; looping is opt-in.
//
// Contract, read out of shell.qml rather than guessed:
//   summon -> deliverIfLoaded() calls open(payloadJson) on this item
//   hide   -> invokeIfLoaded() calls close()
//   isPluginOpen() reads the `opened` property
// An overlay must also create its OWN PanelWindow with layershell properties;
// a bare Item has no surface and renders nothing. Pattern matches the
// first-party image-picker at shell/plugins/image-picker/ImagePicker.qml.
//
// QtMultimedia rather than AnimatedImage: this box has no webp image plugin
// (/usr/lib/qt6/plugins/imageformats is gif/ico/jpeg/pdf/svg only), but does
// ship qt6-multimedia-ffmpeg. mp4 also carries its own audio.

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

  function open(payload) {
    try {
      if (payload && payload.length > 2) {
        var p = JSON.parse(payload)
        if (p.source) root.source = p.source
        if (p.loop !== undefined) root.loopForever = !!p.loop
        if (p.sound !== undefined) root.soundOn = !!p.sound
      }
    } catch (e) { console.warn("gremlins: bad payload", e) }

    root.opened = true
    player.stop()
    player.play()
    guard.restart()
  }

  function close() {
    player.stop()
    guard.stop()
    root.opened = false
  }

  MediaPlayer {
    id: player
    source: root.source
    videoOutput: vout
    audioOutput: AudioOutput { volume: root.soundOn ? 1.0 : 0.0 }
    loops: root.loopForever ? MediaPlayer.Infinite : 1
    onMediaStatusChanged: {
      if (mediaStatus === MediaPlayer.EndOfMedia && !root.loopForever) root.close()
      if (mediaStatus === MediaPlayer.InvalidMedia) {
        console.warn("gremlins: cannot play", root.source, errorString)
        root.close()
      }
    }
  }

  // Never leave a black surface on screen if a decode stalls.
  Timer {
    id: guard
    interval: 9000
    onTriggered: root.close()
  }

  PanelWindow {
    id: panel
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "black"
    WlrLayershell.namespace: "omarchy-gremlins"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore

    VideoOutput {
      id: vout
      anchors.fill: parent
      fillMode: VideoOutput.PreserveAspectCrop
    }

    MouseArea { anchors.fill: parent; onClicked: root.close() }
    Keys.onEscapePressed: root.close()
    Component.onCompleted: forceActiveFocus()
  }
}
