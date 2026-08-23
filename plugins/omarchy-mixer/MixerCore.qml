// Mixer - daemon owner and plugin state.
//
// helper/mixerd.py talks to PipeWire through pactl. It is event-driven rather
// than polled: `pactl subscribe` emits a line whenever anything in the audio
// graph changes, so the helper re-reads on change instead of asking sixty
// times a minute what a slider is set to.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property bool moveStreamsOnSwitch: true

  // ---- state ----
  property bool ready: false
  property bool available: false
  property var  streams: []          // [{id,name,detail,volume,mute,corked,sink,sinkName}]
  property var  outputs: []          // [{index,name,label,volume,mute,isDefault}]
  property string defaultSink: ""
  property string lastError: ""

  readonly property int playing: {
    var n = 0
    for (var i = 0; i < streams.length; i++) if (!streams[i].corked) n++
    return n
  }

  readonly property var currentOutput: {
    for (var i = 0; i < outputs.length; i++) if (outputs[i].isDefault) return outputs[i]
    return null
  }

  readonly property string helperPath:
    Qt.resolvedUrl("helper/mixerd.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("mixer: could not reach the helper:", e)
    }
  }

  function setVolume(id, level)  { post({ cmd: "volume", id: id, value: level }) }
  function setMute(id, mute)     { post({ cmd: "mute", id: id, value: mute }) }
  function move(id, sinkName)    { post({ cmd: "move", id: id, sink: sinkName }) }
  function setSinkVolume(s, v)   { post({ cmd: "sinkVolume", sink: s, value: v }) }
  function setSinkMute(s, m)     { post({ cmd: "sinkMute", sink: s, value: m }) }
  function refresh()             { post({ cmd: "refresh" }) }
  function chooseOutput(name) {
    post({ cmd: "defaultSink", sink: name, moveStreams: core.moveStreamsOnSwitch })
  }

  // Optimistic local update. The helper round-trip is a few milliseconds, but
  // a slider that waits for it feels like it is fighting the mouse.
  function nudgeLocally(id, level) {
    var next = []
    for (var i = 0; i < core.streams.length; i++) {
      var s = core.streams[i]
      next.push(s.id === id ? Object.assign({}, s, { volume: level }) : s)
    }
    core.streams = next
  }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.available = ev.available === true
      break

    case "snapshot":
      core.streams = ev.streams || []
      core.outputs = ev.outputs || []
      core.defaultSink = ev.defaultSink || ""
      core.lastError = ""
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
          console.warn("mixer: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      core.streams = []
      core.outputs = []
      if (code !== 0)
        core.lastError = "The Mixer helper stopped (exit " + code + "). " +
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
