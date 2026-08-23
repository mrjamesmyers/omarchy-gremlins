// Lens - daemon owner and plugin state.
//
// helper/lensd.py drives everything through hyprctl. It probes for option
// names at startup rather than assuming them, because the zoom factor has
// moved between Hyprland releases and a plugin that hard-codes one spelling
// works on the author's machine and silently does nothing on everybody else's.
//
// The capability flags below are load-bearing: a control for something this
// Hyprland cannot do is disabled and labelled, never shown as if it works.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  // ---- capabilities, discovered ----
  property bool ready: false
  property bool hasHyprctl: false
  property bool canMagnify: false
  property bool canFilter: false
  property bool canReduceMotion: false

  // ---- state ----
  property real zoom: 1.0
  property string filter: ""
  property bool animations: true
  property int cursorSize: 0
  property var filters: []
  property string lastError: ""

  // ---- contrast checker ----
  property var contrast: null

  // ---- cursor locator ----
  property int cursorX: 0
  property int cursorY: 0
  signal cursorLocated()

  readonly property bool active: zoom > 1.0 || filter.length > 0 || !animations

  readonly property string helperPath:
    Qt.resolvedUrl("helper/lensd.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("lens: could not reach the helper:", e)
    }
  }

  function setFilter(name)      { post({ cmd: "filter", name: name }) }
  function setZoom(v)           { post({ cmd: "zoom", value: v }) }
  function zoomBy(delta)        { post({ cmd: "zoomBy", value: delta }) }
  function setRigid(on)         { post({ cmd: "rigid", value: on }) }
  function setAnimations(on)    { post({ cmd: "animations", value: on }) }
  function setCursorSize(n)     { post({ cmd: "cursorSize", value: n }) }
  function locate()             { post({ cmd: "locate" }) }
  function reset()              { post({ cmd: "reset" }) }
  function checkContrast(fg, bg, large) {
    post({ cmd: "contrast", foreground: fg, background: bg, large: !!large })
  }

  // A human label for each shader, kept here rather than in the helper because
  // it is presentation, not behaviour.
  function filterLabel(name) {
    switch (name) {
    case "protanopia-correct":    return "Protanopia — correct"
    case "deuteranopia-correct":  return "Deuteranopia — correct"
    case "tritanopia-correct":    return "Tritanopia — correct"
    case "protanopia-simulate":   return "Protanopia — simulate"
    case "deuteranopia-simulate": return "Deuteranopia — simulate"
    case "tritanopia-simulate":   return "Tritanopia — simulate"
    case "high-contrast":         return "High contrast"
    case "invert":                return "Invert lightness"
    case "greyscale":             return "Greyscale"
    case "dim":                   return "Dim"
    default:                      return name
    }
  }

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.hasHyprctl = ev.hyprctl === true
      core.canMagnify = ev.magnifier === true
      core.canFilter = ev.filters === true
      core.canReduceMotion = ev.reduceMotion === true
      break

    case "state":
      core.zoom = ev.zoom !== undefined ? ev.zoom : core.zoom
      core.filter = ev.filter !== undefined ? ev.filter : core.filter
      core.animations = ev.animations !== undefined ? ev.animations : core.animations
      core.cursorSize = ev.cursorSize || core.cursorSize
      if (ev.filters) core.filters = ev.filters
      core.lastError = ""
      break

    case "cursor":
      core.cursorX = ev.x || 0
      core.cursorY = ev.y || 0
      core.cursorLocated()
      break

    case "contrast":
      core.contrast = {
        ratio: ev.ratio, verdict: ev.verdict,
        foreground: ev.foreground, background: ev.background, large: ev.large
      }
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
          console.warn("lens: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      if (code !== 0)
        core.lastError = "The Lens helper stopped (exit " + code + "). " +
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
