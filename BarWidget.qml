// Gremlins — bar widget.
//
// The gremlin that lives in your bar. Click it to replay the bumper.
// Drawn as a silhouette in the live theme foreground colour, so it follows
// every Omarchy theme, including ones that don't exist yet.

import QtQuick

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property color fg: bar ? bar.foreground : "#e6e6e6"
  readonly property int   sz: bar ? bar.barSize : 26
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"

  implicitWidth:  Math.round(sz * 1.1)
  implicitHeight: sz

  // Theme changes are live — repaint rather than restart.
  onFgChanged: gremlin.requestPaint()

  Canvas {
    id: gremlin
    anchors.centerIn: parent
    width:  Math.round(root.sz * 0.78)
    height: Math.round(root.sz * 0.78)

    onPaint: {
      const ctx = getContext("2d")
      const w = width, h = height
      ctx.reset()
      ctx.fillStyle = root.fg

      // ears
      ctx.beginPath()
      ctx.moveTo(w * 0.20, h * 0.52)
      ctx.lineTo(w * 0.02, h * 0.02)
      ctx.lineTo(w * 0.46, h * 0.30)
      ctx.closePath()
      ctx.fill()

      ctx.beginPath()
      ctx.moveTo(w * 0.80, h * 0.52)
      ctx.lineTo(w * 0.98, h * 0.02)
      ctx.lineTo(w * 0.54, h * 0.30)
      ctx.closePath()
      ctx.fill()

      // head
      ctx.beginPath()
      ctx.ellipse(w * 0.18, h * 0.32, w * 0.64, h * 0.62)
      ctx.fill()

      // eyes, punched out so the silhouette reads at 26px
      ctx.globalCompositeOperation = "destination-out"
      ctx.beginPath()
      ctx.ellipse(w * 0.33, h * 0.52, w * 0.13, h * 0.17)
      ctx.fill()
      ctx.beginPath()
      ctx.ellipse(w * 0.55, h * 0.52, w * 0.13, h * 0.17)
      ctx.fill()
      ctx.globalCompositeOperation = "source-over"
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor

    onEntered: if (bar) bar.showTooltip(root, "Gremlins — click to replay the bumper")
    onExited:  if (bar) bar.hideTooltip(root)

    // VERIFY ON BOX: confirm the CLI verb for summoning a plugin overlay.
    // The manual documents `summon <id>` / `toggle <id>` over the shell's IPC socket.
    onClicked: if (bar) bar.run("omarchy-shell toggle " + root.pluginId)
  }
}
