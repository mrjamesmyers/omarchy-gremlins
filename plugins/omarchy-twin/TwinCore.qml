// Twin - daemon owner and scan state.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property bool ready: false
  property bool scanning: false
  property var  groups: []
  property int  truncated: 0
  property int  scanned: 0
  property int  groupCount: 0
  property real reclaimable: 0
  property int  hardlinked: 0
  property string stage: ""
  property int  done: 0
  property int  total: 0
  property string home: ""
  property string lastError: ""
  property var  lastDelete: null

  readonly property string helperPath:
    Qt.resolvedUrl("helper/twind.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try { daemon.write(JSON.stringify(msg) + "\n") }
    catch (e) { console.warn("twin: could not reach the helper:", e) }
  }

  function scan(roots, skipHidden, minSize) {
    core.groups = []
    core.lastDelete = null
    post({ cmd: "scan", roots: roots, skipHidden: skipHidden, minSize: minSize })
  }
  function cancel() { post({ cmd: "cancel" }) }
  function remove(paths, keep) { post({ cmd: "delete", paths: paths, keep: keep }) }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.home = ev.home || ""
      break
    case "scanning":
      core.scanning = ev.active === true
      if (core.scanning) { core.stage = "counting"; core.done = 0; core.total = 0 }
      break
    case "progress":
      core.stage = ev.stage || ""
      core.done = ev.done || 0
      core.total = ev.total || 0
      break
    case "results":
      core.groups = ev.groups || []
      core.truncated = ev.truncated || 0
      core.scanned = ev.scanned || 0
      core.groupCount = ev.groups_count !== undefined ? ev.groups_count : (ev.groups || []).length
      core.reclaimable = ev.reclaimable || 0
      core.hardlinked = ev.hardlinked || 0
      core.lastError = ""
      break
    case "deleted":
      core.lastDelete = { removed: (ev.removed || []).length,
                          refused: (ev.refused || []).length,
                          freed: ev.freed || 0 }
      // Drop what is gone, so the list matches the disk without a rescan.
      var gone = {}
      for (var i = 0; i < (ev.removed || []).length; i++) gone[ev.removed[i]] = true
      var next = []
      for (var g = 0; g < core.groups.length; g++) {
        var kept = []
        for (var p = 0; p < core.groups[g].paths.length; p++)
          if (!gone[core.groups[g].paths[p]]) kept.push(core.groups[g].paths[p])
        if (kept.length > 1)
          next.push({ size: core.groups[g].size, paths: kept,
                      waste: core.groups[g].size * (kept.length - 1) })
      }
      core.groups = next
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
        try { core.handle(JSON.parse(text)) }
        catch (e) { console.warn("twin: unreadable event:", text) }
      }
    }
    onExited: function (code) {
      core.ready = false
      core.scanning = false
      if (code !== 0)
        core.lastError = "The Twin helper stopped (exit " + code + ")."
    }
  }

  Timer {
    interval: 5000
    running: !daemon.running
    repeat: true
    onTriggered: if (!daemon.running) daemon.running = true
  }
}
