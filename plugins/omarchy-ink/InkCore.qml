// Ink - daemon owner and document state.
//
// helper/inkd.py holds the open document and does the coordinate maths;
// helper/pdfcore.py does the PDF reading and writing, standard library only,
// because Omarchy plugins are cloned rather than installed and asking somebody
// to run pip before they can sign a form is the same as not shipping it.
//
// Annotations live here in interface coordinates - top-left origin, display
// pixels - and are converted on the way out. Nothing in QML needs to know
// which way up a PDF is.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property bool ready: false
  property string path: ""
  property string name: ""
  property var pages: []              // [{index, width, height, rotate}]
  property bool encrypted: false
  property string lastError: ""
  property string lastSaved: ""

  // pageIndex -> [op, ...]. Ops are in interface coordinates at scale 1.
  property var strokes: ({})
  property int revision: 0            // bumped so bindings see nested changes

  readonly property bool open: core.path.length > 0
  readonly property int pageCount: core.pages.length

  readonly property bool dirty: {
    core.revision                     // depend on it
    for (var k in core.strokes)
      if (core.strokes[k] && core.strokes[k].length > 0) return true
    return false
  }

  readonly property string helperPath:
    Qt.resolvedUrl("helper/inkd.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("ink: could not reach the helper:", e)
    }
  }

  function openDocument(p) {
    core.strokes = ({})
    core.revision++
    core.lastSaved = ""
    post({ cmd: "open", path: p })
  }

  function closeDocument() {
    core.path = ""
    core.name = ""
    core.pages = []
    core.strokes = ({})
    core.revision++
    post({ cmd: "close" })
  }

  function addOp(pageIndex, op) {
    var all = core.strokes
    if (!all[pageIndex]) all[pageIndex] = []
    all[pageIndex].push(op)
    core.strokes = all
    core.revision++
  }

  function undo(pageIndex) {
    var all = core.strokes
    if (all[pageIndex] && all[pageIndex].length > 0) {
      all[pageIndex].pop()
      core.strokes = all
      core.revision++
    }
  }

  function clearPage(pageIndex) {
    var all = core.strokes
    all[pageIndex] = []
    core.strokes = all
    core.revision++
  }

  function opsFor(pageIndex) {
    core.revision
    return core.strokes[pageIndex] || []
  }

  function save(target) {
    post({ cmd: "save", target: target || "", annotations: core.strokes, scale: 1.0 })
  }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      break

    case "opened":
      core.path = ev.path || ""
      core.name = ev.name || ""
      core.pages = ev.pages || []
      core.encrypted = ev.encrypted === true
      core.lastError = ""
      break

    case "closed":
      core.path = ""
      core.pages = []
      break

    case "saved":
      core.lastSaved = ev.path || ""
      Quickshell.execDetached(["notify-send", "-a", "Ink", "-i", "document-save",
                               "Saved", ev.name || "Document"])
      break

    case "error":
      core.lastError = ev.message || "Something went wrong."
      break
    }
  }

  Process {
    id: daemon
    command: ["python3", "-u", core.helperPath]
    running: true
    stdinEnabled: true

    stdout: SplitParser {
      splitMarker: "\n"
      onRead: function (line) {
        var text = (line || "").trim()
        if (text.length === 0) return
        try {
          core.handle(JSON.parse(text))
        } catch (e) {
          console.warn("ink: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      if (code !== 0)
        core.lastError = "The Ink helper stopped (exit " + code + "). " +
                         "Check that python3 is installed."
    }
  }

  Timer {
    interval: 5000
    running: !daemon.running
    repeat: true
    onTriggered: if (!daemon.running) daemon.running = true
  }
}
