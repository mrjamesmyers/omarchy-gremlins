// Gremlins - bar widget.
//
// Two styles, selectable via settings.style:
//   "descend" (default) - it climbs down into the bar from above, upside down:
//                         one hand grips, then the other, then it lowers its
//                         body and hangs there looking at you.
//   "peek"              - it hooks its head over the bar's edge from below.
//
// Both assets are chroma-keyed cut-outs with real 8-bit alpha, NOT tiles with
// baked-in darkness. An earlier version baked its own dark vignette in, which
// was invisible on an opaque bar and showed as a floating dark rectangle the
// moment the bar went transparent. A silhouette has nothing to blend.
//
// The descent is a sprite sheet rather than video: mp4 carries no alpha, GIF has
// only 1-bit alpha (jagged edges over a wallpaper), and Omarchy's Qt ships no
// webp plugin. A sheet gives full alpha, one texture upload and GPU playback.

import QtQuick

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"
  readonly property string style: (settings && settings.style) || "descend"

  // How often it shows up, in seconds. Rare is the point - a thing that stares
  // at you constantly is a decoration, not a scare.
  readonly property int minGap: (settings && settings.peekMinSeconds) || 45
  readonly property int maxGap: (settings && settings.peekMaxSeconds) || 120

  // sprite sheet geometry
  readonly property int spriteFrames: 42
  readonly property int spriteW: 94
  readonly property int spriteH: 72

  implicitWidth: root.style === "descend"
    ? Math.round(sz * root.spriteW / root.spriteH)
    : Math.round(sz * 1.75)
  implicitHeight: sz
  clip: true

  property bool watching: false
  property bool away: false        // true while the bumper owns the screen

  // ---------------- descend ----------------
  AnimatedSprite {
    id: climber
    visible: root.style === "descend"
    anchors.fill: parent
    source: Qt.resolvedUrl("assets/descend.png")
    frameCount: root.spriteFrames
    frameWidth: root.spriteW
    frameHeight: root.spriteH
    frameRate: 12
    loops: 1
    running: false
    interpolate: false
    opacity: root.away ? 0 : 1
    Behavior on opacity { NumberAnimation { duration: 200 } }

    // hold on the last frame instead of snapping back to an empty one
    onRunningChanged: {
      if (!running && !climber.reverse) { climber.currentFrame = root.spriteFrames - 1; climber.paused = true }
      if (!running && climber.reverse)  { climber.currentFrame = 0; climber.paused = true }
    }
  }

  // ---------------- peek ----------------
  Image {
    id: peeker
    visible: root.style === "peek"
    source: Qt.resolvedUrl("assets/peek.png")
    height: root.height
    fillMode: Image.PreserveAspectFit
    anchors.horizontalCenter: parent.horizontalCenter
    y: root.hiddenY
    opacity: root.away ? 0 : 1
    Behavior on y { NumberAnimation { duration: root.watching ? 900 : 520
                    easing.type: root.watching ? Easing.OutCubic : Easing.InCubic } }
    Behavior on anchors.horizontalCenterOffset { NumberAnimation { duration: 420; easing.type: Easing.InOutQuad } }
    Behavior on opacity { NumberAnimation { duration: 200 } }
  }

  readonly property real hiddenY: root.height + 2
  readonly property real peekY:   Math.round(root.height * 0.06)

  // ---------------- appearance cycle ----------------
  Timer {
    id: nextPeek
    running: !root.away
    repeat: false
    interval: (root.minGap + Math.random() * (root.maxGap - root.minGap)) * 1000
    onTriggered: root.arrive()
  }

  Timer { id: stayFor; repeat: false; onTriggered: root.leave() }

  function arrive() {
    if (root.away) return
    root.watching = true
    if (root.style === "descend") {
      climber.paused = false
      climber.reverse = false
      climber.currentFrame = 0
      climber.running = true
    } else {
      peeker.y = root.peekY
      glance.restart()
      duck.restart()
    }
    stayFor.interval = 5000 + Math.random() * 5000
    stayFor.restart()
  }

  function leave() {
    root.watching = false
    if (root.style === "descend") {
      climber.paused = false
      climber.reverse = true          // climb back up the way it came
      climber.running = true
    } else {
      peeker.y = root.hiddenY
      peeker.anchors.horizontalCenterOffset = 0
    }
    nextPeek.interval = (root.minGap + Math.random() * (root.maxGap - root.minGap)) * 1000
    nextPeek.restart()
  }

  // peek-style idle motion
  Timer {
    id: duck
    interval: 1800 + Math.random() * 1500
    repeat: true
    running: root.watching && root.style === "peek"
    onTriggered: duckAnim.restart()
  }
  SequentialAnimation {
    id: duckAnim
    NumberAnimation { target: peeker; property: "y"; to: root.peekY + root.height * 0.42; duration: 130; easing.type: Easing.InQuad }
    PauseAnimation { duration: 90 }
    NumberAnimation { target: peeker; property: "y"; to: root.peekY; duration: 160; easing.type: Easing.OutQuad }
  }
  Timer {
    id: glance
    interval: 2200 + Math.random() * 1800
    repeat: true
    running: root.watching && root.style === "peek"
    onTriggered: peeker.anchors.horizontalCenterOffset =
      (Math.random() < 0.5 ? -1 : 1) * Math.max(1, Math.round(root.width * 0.05))
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor

    onEntered: {
      if (bar) bar.showTooltip(root, "Gremlins - click to replay the bumper")
      if (!root.away && !root.watching) root.arrive()
      else stayFor.stop()
    }
    onExited: {
      if (bar) bar.hideTooltip(root)
      if (!root.away && root.watching && !stayFor.running) { stayFor.interval = 1500; stayFor.restart() }
    }

    // Verified against /usr/bin/omarchy-shell: usage is
    //   omarchy-shell [-q] <target> <method> [args...]
    // so the "shell" target is required.
    onClicked: {
      if (!bar) return
      bar.run("omarchy-shell shell toggle " + root.pluginId)
      root.away = true               // it isn't in the bar now - it's on your screen
      root.watching = false
      stayFor.stop()
      comeBack.restart()
    }
  }

  Timer {
    id: comeBack
    interval: 3600
    onTriggered: {
      root.away = false
      if (root.style === "descend") { climber.currentFrame = 0; climber.paused = true }
      else peeker.y = root.hiddenY
      nextPeek.restart()
    }
  }

  Component.onCompleted: { nextPeek.interval = 7000; nextPeek.restart() }
}
