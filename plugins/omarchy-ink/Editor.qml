// Ink - the editor.
//
// A fullscreen overlay: the page, and the smallest set of tools that gets a
// form signed. Draw, type, undo, save.
//
// Page rendering goes through QtQuick.Pdf where it is available, which is the
// only way to reach page two and beyond. Where it is not, Qt's PDF image
// plugin still renders the first page through a plain Image, and the editor
// says so rather than showing an empty rectangle - a one-page fallback is
// enough for the majority of things people actually sign.

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root

  property var  bar
  property var  core: null
  property var  hostWidget: null
  property bool primary: false

  property string inkColour: "#1a1a1a"
  property real   inkWidth: 2.5
  property int    textSize: 12
  property bool   saveBeside: true

  property bool shown: false
  property int  page: 0
  property string tool: "pen"          // pen | text | erase
  property string pendingText: ""

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property var pageInfo: core && core.pages.length > page ? core.pages[page] : null

  function show()   { root.shown = true }
  function hide()   { root.shown = false }
  function toggle() { root.shown = !root.shown }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.ink"
    function toggle(): void { root.toggle() }
    function open(path: string): void {
      if (root.core && path) { root.core.openDocument(path); root.show() }
    }
    function close(): void { root.hide() }
    function save(): void { root.doSave() }
  }

  function doSave() {
    if (!root.core || !root.core.open) return
    root.core.save("")
  }

  Loader {
    active: root.shown && !!root.core && root.core.open
    sourceComponent: PanelWindow {
      anchors { top: true; bottom: true; left: true; right: true }
      color: Qt.rgba(0, 0, 0, 0.82)
      WlrLayershell.namespace: "omarchy-ink"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
      exclusionMode: ExclusionMode.Ignore

      Item {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: root.hide()
        Keys.onPressed: function (event) {
          if (event.key === Qt.Key_S && (event.modifiers & Qt.ControlModifier)) {
            root.doSave(); event.accepted = true
          } else if (event.key === Qt.Key_Z && (event.modifiers & Qt.ControlModifier)) {
            if (root.core) root.core.undo(root.page); event.accepted = true
          } else if (event.key === Qt.Key_Left) {
            root.page = Math.max(0, root.page - 1); event.accepted = true
          } else if (event.key === Qt.Key_Right) {
            root.page = Math.min((root.core ? root.core.pageCount : 1) - 1, root.page + 1)
            event.accepted = true
          }
        }

        // ---------------- toolbar ----------------
        Rectangle {
          id: toolbar
          anchors { top: parent.top; left: parent.left; right: parent.right }
          height: Math.round(Style.space(48))
          color: bar ? bar.background : "#111"

          Row {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter
                      leftMargin: Style.space(14) }
            spacing: Style.space(10)

            Text {
              anchors.verticalCenter: parent.verticalCenter
              text: root.core ? root.core.name : ""
              color: bar ? bar.foreground : "white"
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              anchors.verticalCenter: parent.verticalCenter
              visible: root.core && root.core.pageCount > 1
              text: "page " + (root.page + 1) + " of " + (root.core ? root.core.pageCount : 1)
              color: bar ? bar.foreground : "white"
              opacity: 0.6
              font.family: root.fontFamily
              font.pixelSize: Math.max(9, Style.font.caption - 2)
            }
          }

          Row {
            anchors { right: parent.right; verticalCenter: parent.verticalCenter
                      rightMargin: Style.space(14) }
            spacing: Style.space(6)

            Repeater {
              model: [
                { id: "pen",  label: "Sign" },
                { id: "text", label: "Type" }
              ]
              Rectangle {
                readonly property bool on: root.tool === modelData.id
                width: Math.round(Style.space(56)); height: Math.round(Style.space(28))
                radius: Style.cornerRadius
                color: on ? Color.accent : Qt.rgba(1, 1, 1, 0.10)
                Text {
                  anchors.centerIn: parent
                  text: modelData.label
                  color: parent.on ? (bar ? bar.background : "black") : "white"
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 1)
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.tool = modelData.id
                }
              }
            }

            Repeater {
              model: [
                { id: "undo",  label: "Undo" },
                { id: "clear", label: "Clear" },
                { id: "save",  label: "Save" },
                { id: "close", label: "Close" }
              ]
              Rectangle {
                width: Math.round(Style.space(56)); height: Math.round(Style.space(28))
                radius: Style.cornerRadius
                color: modelData.id === "save"
                       ? (root.core && root.core.dirty ? Color.accent : Qt.rgba(1, 1, 1, 0.10))
                       : Qt.rgba(1, 1, 1, 0.10)
                Text {
                  anchors.centerIn: parent
                  text: modelData.label
                  color: modelData.id === "save" && root.core && root.core.dirty
                         ? (bar ? bar.background : "black") : "white"
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 1)
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    if (modelData.id === "undo") root.core.undo(root.page)
                    else if (modelData.id === "clear") root.core.clearPage(root.page)
                    else if (modelData.id === "save") root.doSave()
                    else root.hide()
                  }
                }
              }
            }
          }
        }

        // ---------------- the page ----------------
        Item {
          id: stage
          anchors { top: toolbar.bottom; left: parent.left; right: parent.right
                    bottom: status.top; margins: Style.space(18) }

          readonly property real pw: root.pageInfo ? root.pageInfo.width : 612
          readonly property real ph: root.pageInfo ? root.pageInfo.height : 792
          readonly property real fit:
            Math.min(width / pw, height / ph)

          Rectangle {
            id: sheet
            width: stage.pw * stage.fit
            height: stage.ph * stage.fit
            anchors.centerIn: parent
            color: "white"

            // Qt's PDF image plugin renders the first page of a PDF through a
            // plain Image. Multi-page needs QtQuick.Pdf, which is loaded
            // opportunistically below.
            Image {
              id: flat
              anchors.fill: parent
              visible: pdfLoader.status !== Loader.Ready
              source: root.core && root.core.open && root.page === 0
                      ? "file://" + root.core.path : ""
              fillMode: Image.PreserveAspectFit
              asynchronous: true
              cache: false
            }

            Loader {
              id: pdfLoader
              anchors.fill: parent
              // Failing to load is an expected outcome, not an error: not every
              // Qt build ships the PDF QML module.
              source: root.core && root.core.open
                      ? Qt.resolvedUrl("PdfPage.qml") : ""
              onStatusChanged: if (status === Loader.Error)
                console.info("ink: QtQuick.Pdf unavailable, first page only")
              onLoaded: {
                if ("source" in item) item.source = "file://" + root.core.path
                if ("page" in item) item.page = root.page
              }
            }
            Connections {
              target: pdfLoader.item
              ignoreUnknownSignals: true
            }
            onVisibleChanged: if (pdfLoader.item && "page" in pdfLoader.item)
              pdfLoader.item.page = root.page

            // ---------------- what has been drawn ----------------
            Canvas {
              id: overlay
              anchors.fill: parent
              renderStrategy: Canvas.Cooperative

              property var live: []

              onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.lineCap = "round"
                ctx.lineJoin = "round"

                function stroke(points, colour, width) {
                  if (!points || points.length < 2) return
                  ctx.strokeStyle = colour
                  ctx.lineWidth = Math.max(0.5, width * stage.fit)
                  ctx.beginPath()
                  ctx.moveTo(points[0][0] * stage.fit, points[0][1] * stage.fit)
                  for (var i = 1; i < points.length; i++)
                    ctx.lineTo(points[i][0] * stage.fit, points[i][1] * stage.fit)
                  ctx.stroke()
                }

                var ops = root.core ? root.core.opsFor(root.page) : []
                for (var i = 0; i < ops.length; i++) {
                  var op = ops[i]
                  if (op.type === "ink") stroke(op.points, root.inkColour, op.width)
                  else if (op.type === "text") {
                    ctx.fillStyle = root.inkColour
                    ctx.font = Math.round(op.size * stage.fit) + "px sans-serif"
                    ctx.textBaseline = "top"
                    var lines = String(op.text).split("\n")
                    for (var l = 0; l < lines.length; l++)
                      ctx.fillText(lines[l], op.x * stage.fit,
                                   (op.y + l * op.size * 1.2) * stage.fit)
                  }
                }
                stroke(overlay.live, root.inkColour, root.inkWidth)
              }
            }

            Connections {
              target: root.core
              function onRevisionChanged() { overlay.requestPaint() }
            }

            MouseArea {
              anchors.fill: parent
              cursorShape: root.tool === "pen" ? Qt.CrossCursor : Qt.IBeamCursor
              acceptedButtons: Qt.LeftButton

              function toPage(mx, my) {
                return [mx / stage.fit, my / stage.fit]
              }

              onPressed: function (mouse) {
                if (root.tool === "pen") {
                  overlay.live = [toPage(mouse.x, mouse.y)]
                  overlay.requestPaint()
                } else if (root.tool === "text") {
                  var at = toPage(mouse.x, mouse.y)
                  textEntry.pageX = at[0]
                  textEntry.pageY = at[1]
                  textEntry.text = ""
                  textEntry.visible = true
                  textEntry.forceActiveFocus()
                }
              }
              onPositionChanged: function (mouse) {
                if (root.tool !== "pen" || !pressed) return
                var next = overlay.live.slice()
                next.push(toPage(mouse.x, mouse.y))
                overlay.live = next
                overlay.requestPaint()
              }
              onReleased: {
                if (root.tool !== "pen") return
                if (overlay.live.length > 1 && root.core) {
                  root.core.addOp(root.page, {
                    type: "ink", points: overlay.live,
                    width: root.inkWidth, colour: root.rgb(root.inkColour)
                  })
                }
                overlay.live = []
                overlay.requestPaint()
              }
            }

            TextField {
              id: textEntry
              property real pageX: 0
              property real pageY: 0
              visible: false
              x: pageX * stage.fit
              y: pageY * stage.fit
              width: Math.max(Style.space(120), stage.width * 0.3)
              font.family: root.fontFamily
              font.pixelSize: Math.round(root.textSize * stage.fit)
              color: root.inkColour
              background: Rectangle { color: Qt.rgba(1, 1, 0.6, 0.4) }
              onAccepted: {
                if (text.length > 0 && root.core) {
                  root.core.addOp(root.page, {
                    type: "text", text: text, x: pageX, y: pageY,
                    size: root.textSize, colour: root.rgb(root.inkColour)
                  })
                }
                visible = false
                text = ""
              }
              Keys.onEscapePressed: { visible = false; text = "" }
            }
          }
        }

        // ---------------- status ----------------
        Rectangle {
          id: status
          anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
          height: Math.round(Style.space(34))
          color: bar ? bar.background : "#111"

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter
                      leftMargin: Style.space(14) }
            width: parent.width - Style.space(28)
            elide: Text.ElideRight
            color: root.core && root.core.lastError.length > 0
                   ? (bar ? bar.urgent : "#e88") : (bar ? bar.foreground : "white")
            opacity: 0.85
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 1)
            text: {
              if (!root.core) return ""
              if (root.core.lastError.length > 0) return root.core.lastError
              if (root.core.lastSaved.length > 0) return "Saved to " + root.core.lastSaved
              if (root.core.encrypted) return "This PDF is encrypted — annotations will not stick."
              return root.tool === "pen"
                     ? "Drag to sign  ·  Ctrl+Z undo  ·  Ctrl+S save  ·  Esc close"
                     : "Click where the text goes, type, press Enter"
            }
          }
        }
      }
    }
  }

  // "#rrggbb" to the 0..1 triple the helper wants.
  function rgb(hex) {
    var c = String(hex).replace("#", "")
    if (c.length === 3) c = c[0] + c[0] + c[1] + c[1] + c[2] + c[2]
    if (c.length !== 6) return [0, 0, 0]
    return [parseInt(c.substr(0, 2), 16) / 255,
            parseInt(c.substr(2, 2), 16) / 255,
            parseInt(c.substr(4, 2), 16) / 255]
  }
}
