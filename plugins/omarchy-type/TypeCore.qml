// Type - daemon owner and font state.
//
// helper/typed.py reads fontconfig, which is already installed because the
// desktop cannot draw text without it. Nothing here needs a package manager
// and nothing needs a password.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  property bool ready: false
  property bool available: false
  property var  families: []          // [{family, styles, count, user, disabled, preview}]
  property int  total: 0
  property var  disabled: []
  property string userDir: ""
  property string lastError: ""

  readonly property int familyCount: families.length
  readonly property int mineCount: {
    var n = 0
    for (var i = 0; i < families.length; i++) if (families[i].user) n++
    return n
  }

  readonly property string helperPath:
    Qt.resolvedUrl("helper/typed.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try { daemon.write(JSON.stringify(msg) + "\n") }
    catch (e) { console.warn("type: could not reach the helper:", e) }
  }

  function refresh()          { post({ cmd: "refresh" }) }
  function install(path)      { post({ cmd: "install", path: path }) }
  function uninstall(family)  { post({ cmd: "uninstall", family: family }) }
  function setEnabled(family, on) {
    post({ cmd: on ? "enable" : "disable", family: family })
  }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.available = ev.fontconfig === true
      core.userDir = ev.userDir || ""
      break
    case "fonts":
      core.families = ev.families || []
      core.total = ev.total || 0
      core.available = ev.available !== false
      core.disabled = ev.disabled || []
      if (ev.userDir) core.userDir = ev.userDir
      core.lastError = ""
      break
    case "installed":
      Quickshell.execDetached(["notify-send", "-a", "Type", "-i", "font",
                               "Font installed", ev.name || ""])
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
        catch (e) { console.warn("type: unreadable event:", text) }
      }
    }
    onExited: function (code) {
      core.ready = false
      if (code !== 0)
        core.lastError = "The Type helper stopped (exit " + code + "). " +
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
