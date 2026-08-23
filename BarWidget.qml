// Gremlins - bar widget.
//
// Something lives behind your bar. Most of the time you don't see it. Every
// minute or so a pair of eyes rises into the gap, watches for a few seconds,
// blinks, and drops away again.
//
// An earlier version drew a walking cartoon gremlin from primitives. It read as
// a small boxy robot: 26px is too few pixels for a body, and it contradicted the
// bumper, which is photoreal. Eyes work at this size, and they suit the tone.
//
// The asset keeps its own darkness rather than being keyed transparent - the
// dark surround IS the slit. Its edges are alpha-vignetted so it composites onto
// any theme: on a dark bar it disappears into the background, on a light one it
// reads as a gap with something in it.

import QtQuick

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"

  // How often it shows up, in seconds. Rare is the whole point - a thing that
  // stares at you constantly is a decoration, not a scare.
  readonly property int minGap: (settings && settings.peekMinSeconds) || 45
  readonly property int maxGap: (settings && settings.peekMaxSeconds) || 120

  implicitWidth:  Math.round(sz * 2.2)
  implicitHeight: sz
  clip: true                       // this is the slit

  property bool watching: false
  property bool away: false        // true while the bumper owns the screen

  readonly property real hiddenY:  root.height + 2
  readonly property real peekY:    Math.round(root.height * 0.16)

  Image {
    id: eyes
    source: Qt.resolvedUrl("assets/eyes.png")
    width: root.width
    fillMode: Image.PreserveAspectFit
    smooth: true
    mipmap: true
    x: 0
    y: root.hiddenY
    opacity: root.away ? 0 : 1

    Behavior on y {
      NumberAnimation { duration: root.watching ? 900 : 520
                        easing.type: root.watching ? Easing.OutCubic : Easing.InCubic }
    }
    Behavior on x { NumberAnimation { duration: 420; easing.type: Easing.InOutQuad } }
    Behavior on opacity { NumberAnimation { duration: 200 } }

    // blink: squash vertically about the eyeline
    transform: Scale {
      id: lid
      origin.x: eyes.width / 2
      origin.y: eyes.height * 0.45
      yScale: 1.0
    }
  }

  // ---- appearance cycle ----
  Timer {
    id: nextPeek
    running: !root.away
    repeat: false
    interval: (root.minGap + Math.random() * (root.maxGap - root.minGap)) * 1000
    onTriggered: root.startWatching()
  }

  Timer {
    id: watchFor
    repeat: false
    onTriggered: root.stopWatching()
  }

  function startWatching() {
    if (root.away) return
    root.watching = true
    eyes.y = root.peekY
    watchFor.interval = 4000 + Math.random() * 4000
    watchFor.restart()
    blinkIn.restart()
    glance.restart()
  }

  function stopWatching() {
    root.watching = false
    eyes.y = root.hiddenY
    eyes.x = 0
    nextPeek.interval = (root.minGap + Math.random() * (root.maxGap - root.minGap)) * 1000
    nextPeek.restart()
  }

  // a blink or two while it's up
  Timer {
    id: blinkIn
    interval: 1400 + Math.random() * 1200
    repeat: true
    running: root.watching
    onTriggered: blinkAnim.restart()
  }
  SequentialAnimation {
    id: blinkAnim
    NumberAnimation { target: lid; property: "yScale"; to: 0.06; duration: 70 }
    NumberAnimation { target: lid; property: "yScale"; to: 1.0;  duration: 110 }
  }

  // and a slow glance sideways, so it isn't a static stare
  Timer {
    id: glance
    interval: 2200 + Math.random() * 1800
    repeat: true
    running: root.watching
    onTriggered: eyes.x = (Math.random() < 0.5 ? -1 : 1) * Math.round(root.width * 0.06)
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor

    // lean in and it notices you
    onEntered: {
      if (bar) bar.showTooltip(root, "Gremlins - click to replay the bumper")
      if (!root.away) { root.watching = true; eyes.y = root.peekY; watchFor.stop() }
    }
    onExited: {
      if (bar) bar.hideTooltip(root)
      if (!root.away && !watchFor.running) { watchFor.interval = 1200; watchFor.restart() }
    }

    // Verified against /usr/bin/omarchy-shell: usage is
    //   omarchy-shell [-q] <target> <method> [args...]
    // so the "shell" target is required.
    onClicked: {
      if (!bar) return
      bar.run("omarchy-shell shell toggle " + root.pluginId)
      // it isn't behind the bar any more - it's on your screen
      root.away = true
      root.watching = false
      eyes.y = root.hiddenY
      comeBack.restart()
    }
  }

  Timer { id: comeBack; interval: 3600; onTriggered: { root.away = false; nextPeek.restart() } }

  // show up shortly after login too, once the bumper has finished
  Component.onCompleted: { nextPeek.interval = 6000; nextPeek.restart() }
}
