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

import Quickshell
import Quickshell.Wayland
import QtQuick
import QtQuick.Window

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"
  // "hang"    - big, below the bar, over your wallpaper (default)
  // "descend" - the same animation, small, inside the bar cell
  // "peek"    - hooks its head over the bar's edge from below
  readonly property string style: (settings && settings.style) || "hang"

  // hang-mode geometry
  readonly property int  hangHeight: (settings && settings.hangHeight) || 190
  readonly property real hangX:      (settings && settings.hangX) !== undefined ? settings.hangX : 0.74
  readonly property int  barPixels:  (settings && settings.barPixels) || 43

  // The bar is instantiated once per monitor, so every instance of this widget
  // would spawn its own hanging window and they would stack invisibly on top of
  // each other. Only the instance living on the first screen owns it.
  readonly property bool ownsHangWindow:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  // How often it shows up, in seconds. Rare is the point - a thing that stares
  // at you constantly is a decoration, not a scare.
  readonly property int minGap: (settings && settings.peekMinSeconds) || 45
  readonly property int maxGap: (settings && settings.peekMaxSeconds) || 120

  // sprite sheet geometry
  readonly property int spriteFrames: 42
  readonly property int spriteW: 94
  readonly property int spriteH: 72

  implicitWidth: root.style === "hang"     ? 6
               : root.style === "descend" ? Math.round(sz * root.spriteW / root.spriteH)
               :                            Math.round(sz * 1.75)
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

  // ---------------- hang: its own layer surface, outside the bar ----------------
  //
  // exclusionMode Ignore is mandatory - a layer-shell surface that reserves
  // space would push every window on the screen down to make room for a
  // gremlin. And the mask means only the creature takes clicks; everything
  // around it behaves as though the window isn't there.
  Loader {
    id: hangLoader
    active: root.style === "hang" && root.ownsHangWindow
    sourceComponent: PanelWindow {
    id: hangWin
    property alias sprite: bigSprite
    visible: !root.away && (root.watching || bigSprite.running)
    anchors { top: true; left: true; right: true }
    implicitHeight: root.barPixels + root.hangHeight
    color: "transparent"
    WlrLayershell.namespace: "omarchy-gremlins-hang"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    mask: Region { item: bigSprite }

    AnimatedSprite {
      id: bigSprite
      source: Qt.resolvedUrl("assets/descend-big.png")
      frameCount: root.spriteFrames
      frameWidth: 236
      frameHeight: 180
      frameRate: 12
      loops: 1
      running: false
      interpolate: false
      height: root.hangHeight
      width: Math.round(root.hangHeight * 236 / 180)
      y: root.barPixels
      x: Math.round((hangWin.width - width) * root.hangX)

      onRunningChanged: {
        if (!running && !bigSprite.reverse) { bigSprite.currentFrame = root.spriteFrames - 1; bigSprite.paused = true }
        if (!running && bigSprite.reverse)  { bigSprite.currentFrame = 0; bigSprite.paused = true }
      }

      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: root.trigger()
      }
    }
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
    running: !root.away && (root.style !== "hang" || root.ownsHangWindow)
    repeat: false
    interval: (root.minGap + Math.random() * (root.maxGap - root.minGap)) * 1000
    onTriggered: root.arrive()
  }

  Timer { id: stayFor; repeat: false; onTriggered: root.leave() }

  function arrive() {
    if (root.away) return
    root.watching = true
    if (root.style === "hang") {
      if (!root.ownsHangWindow) return
      var sp = hangLoader.item ? hangLoader.item.sprite : null
      if (sp) { sp.paused = false; sp.reverse = false; sp.currentFrame = 0; sp.running = true }
    } else if (root.style === "descend") {
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
    if (root.style === "hang") {
      if (!root.ownsHangWindow) return
      var sp2 = hangLoader.item ? hangLoader.item.sprite : null
      if (sp2) { sp2.paused = false; sp2.reverse = true; sp2.running = true }
    } else if (root.style === "descend") {
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
    onClicked: root.trigger()
  }

  function trigger() {
    if (!bar) return
    bar.run("omarchy-shell shell toggle " + root.pluginId)
    root.away = true                 // it isn't here now - it's on your screen
    root.watching = false
    stayFor.stop()
    comeBack.restart()
  }

  Timer {
    id: comeBack
    interval: 3600
    onTriggered: {
      root.away = false
      if (root.style === "hang") {
        var sp3 = hangLoader.item ? hangLoader.item.sprite : null
        if (sp3) { sp3.currentFrame = 0; sp3.paused = true }
      }
      else if (root.style === "descend") { climber.currentFrame = 0; climber.paused = true }
      else                                peeker.y = root.hiddenY
      nextPeek.restart()
    }
  }

  Component.onCompleted: { nextPeek.interval = 7000; nextPeek.restart() }
}
