// Cast - daemon owner and plugin state.
//
// One instance, on the primary screen only: discovery binds a multicast
// socket and there is no sense in three of them asking the same question.
//
// helper/castd.py does the protocol work - mDNS and SSDP to find receivers,
// CASTV2 over TLS to drive Chromecasts, SOAP to drive DLNA televisions, and a
// range-capable HTTP server so a local file becomes a URL the television can
// actually fetch. None of that is expressible in QML.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property int rescanSeconds: 300

  // ---- state ----
  property bool ready: false
  property bool scanning: false
  property var  targets: []           // [{id, name, model, kind, address}]
  property var  current: null         // {target, title} while casting
  property string state: ""           // PLAYING | PAUSED | BUFFERING | IDLE
  property real position: 0
  property real duration: 0
  property string title: ""
  property real volume: -1
  property string lastError: ""

  readonly property bool casting: current !== null
  readonly property string helperPath:
    Qt.resolvedUrl("helper/castd.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("cast: could not reach the helper:", e)
    }
  }

  function scan()                { post({ cmd: "scan" }) }
  function castTo(id, source, t) { post({ cmd: "cast", target: id, source: source, title: t }) }
  function pause()               { post({ cmd: "pause" }) }
  function play()                { post({ cmd: "play" }) }
  function stop()                { post({ cmd: "stop" }) }
  function seek(seconds)         { post({ cmd: "seek", value: seconds }) }
  function setVolume(level)      { post({ cmd: "volume", value: level }) }

  function toggle() {
    if (core.state === "PLAYING") pause(); else play()
  }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.lastError = ""
      break

    case "scanning":
      core.scanning = ev.active === true
      break

    case "targets":
      core.targets = ev.targets || []
      break

    case "casting":
      core.current = { target: ev.target, title: ev.title || "" }
      core.title = ev.title || ""
      core.state = "BUFFERING"
      core.position = 0
      core.duration = 0
      core.lastError = ""
      break

    case "status":
      if (ev.state) core.state = ev.state
      if (ev.position !== undefined && ev.position !== null) core.position = ev.position
      if (ev.duration !== undefined && ev.duration !== null) core.duration = ev.duration
      if (ev.title) core.title = ev.title
      // A receiver that goes idle has finished or been taken over by
      // something else. Either way this plugin is no longer driving it.
      if (ev.state === "IDLE") { core.current = null; core.state = "" }
      break

    case "receiver":
      if (ev.volume !== undefined && ev.volume !== null) core.volume = ev.volume
      break

    case "stopped":
      core.current = null
      core.state = ""
      core.position = 0
      core.duration = 0
      core.title = ""
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
          console.warn("cast: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      core.targets = []
      core.current = null
      core.state = ""
      if (code !== 0)
        core.lastError = "The Cast helper stopped (exit " + code + "). " +
                         "Check that python3 is installed."
    }
  }

  Timer {
    interval: 5000
    running: !daemon.running
    repeat: true
    onTriggered: if (!daemon.running) daemon.running = true
  }

  // Devices come and go - a television is off most of the day. Re-asking on a
  // slow cycle keeps the list honest without making the network noisy.
  Timer {
    interval: Math.max(60, core.rescanSeconds) * 1000
    running: core.ready
    repeat: true
    onTriggered: if (!core.casting) core.scan()
  }

  // While something is playing on a DLNA renderer nothing pushes progress at
  // us, so the position is advanced locally and corrected whenever the
  // receiver does say something.
  Timer {
    interval: 1000
    running: core.casting && core.state === "PLAYING"
    repeat: true
    onTriggered: if (core.duration > 0) core.position = Math.min(core.duration, core.position + 1)
  }
}
