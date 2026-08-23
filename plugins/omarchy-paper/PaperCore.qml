// Paper - daemon owner and plugin state.
//
// One instance, on the primary screen: discovery binds a multicast socket and
// there is no sense in three of them asking the network the same question.
//
// helper/paperd.py does two things QML cannot. It speaks DNS-SD to find
// printers that CUPS has never heard of, and it speaks IPP directly to each
// one to ask what it is actually doing - idle, printing, out of paper, how much
// toner is left - which is information CUPS does not have for a printer it has
// not been told about.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property int pollSeconds: 20

  // ---- state ----
  property bool ready: false
  property bool scanning: false
  property bool cupsPresent: false
  property bool canPrint: false
  property var printers: []          // [{id,name,queue,state,markers,setupCommand,…}]
  property var jobs: []
  property string defaultQueue: ""
  property string lastError: ""
  property string lastSubmitted: ""

  readonly property int busy: {
    var n = 0
    for (var i = 0; i < printers.length; i++)
      if (printers[i].state === "printing") n++
    return n
  }

  readonly property bool attention: {
    for (var i = 0; i < printers.length; i++) {
      var p = printers[i]
      if (p.queue && (p.state === "stopped" || p.state === "disabled")) return true
      if (p.reasons && p.reasons.length > 0) return true
    }
    return false
  }

  readonly property string helperPath:
    Qt.resolvedUrl("helper/paperd.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("paper: could not reach the helper:", e)
    }
  }

  function rescan()  { post({ cmd: "rescan" }) }
  function refresh() { post({ cmd: "refresh" }) }
  function cancel(job) { post({ cmd: "cancel", job: job }) }
  function printFile(path, queue, duplex) {
    post({ cmd: "print", path: path, queue: queue || null, duplex: !!duplex })
  }

  onPollSecondsChanged: post({ cmd: "config", pollSeconds: core.pollSeconds })

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.cupsPresent = ev.cups === true
      core.canPrint = ev.canPrint === true
      post({ cmd: "config", pollSeconds: core.pollSeconds })
      break

    case "scanning":
      core.scanning = ev.active === true
      break

    case "snapshot":
      core.printers = ev.printers || []
      core.jobs = ev.jobs || []
      core.defaultQueue = ev.default || ""
      core.cupsPresent = ev.cups === true
      core.lastError = ""
      break

    case "submitted":
      core.lastSubmitted = ev.file || ""
      Quickshell.execDetached(["notify-send", "-a", "Paper", "-i", "printer",
                               "Printing", (ev.file || "Document") + " → " + (ev.queue || "printer")])
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
          console.warn("paper: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      core.printers = []
      core.jobs = []
      if (code !== 0)
        core.lastError = "The Paper helper stopped (exit " + code + "). " +
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
