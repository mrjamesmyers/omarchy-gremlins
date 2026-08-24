// UniFi - daemon owner and plugin state.
//
// helper/unifid.py does the talking. It exists rather than using QML's
// XMLHttpRequest for one reason that matters: UniFi consoles present a
// self-signed certificate, QML's XHR has no way to make an exception for one,
// and "turn off verification globally" is not an exception. The helper pins
// the console's certificate on first contact instead.
//
// The API key never passes through this file, is never written to shell.json,
// and never appears in a process argument list. The helper reads it from a
// 0600 file or the environment.

import QtQuick
import Quickshell.Io

Item {
  id: core

  property string host: ""
  property int    port: 443
  property string site: ""
  property string keyFile: ""
  property int    pollSeconds: 20

  // ---- state ----
  property bool ready: false
  property bool configured: false
  property bool keyPresent: false
  property bool pinned: false
  property string lastError: ""
  property string authError: ""
  property string defaultKeyFile: ""

  property var siteInfo: null          // {id, name}
  property var devices: []             // [{id,name,model,state,online,ip}]
  property int deviceCount: 0
  property int devicesOnline: 0
  property int clientCount: 0
  property int wired: 0
  property int wireless: 0
  property var gateway: null
  property var uplink: ({})
  property double updatedAt: 0

  readonly property bool healthy:
    core.deviceCount > 0 && core.devicesOnline === core.deviceCount
  readonly property bool degraded:
    core.deviceCount > 0 && core.devicesOnline < core.deviceCount
  readonly property bool problem:
    core.lastError.length > 0 || core.authError.length > 0

  readonly property string helperPath:
    Qt.resolvedUrl("helper/unifid.py").toString().replace("file://", "")

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("unifi: could not reach the helper:", e)
    }
  }

  function pushConfig() {
    core.configured = core.host.length > 0
    post({
      cmd: "config", host: core.host, port: core.port, site: core.site,
      keyFile: core.keyFile, pollSeconds: core.pollSeconds
    })
  }

  function refresh() { post({ cmd: "refresh" }) }
  function unpin()   { post({ cmd: "unpin" }) }

  onHostChanged: pushConfig()
  onPortChanged: pushConfig()
  onSiteChanged: pushConfig()
  onKeyFileChanged: pushConfig()
  onPollSecondsChanged: pushConfig()

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.defaultKeyFile = ev.keyFile || ""
      pushConfig()
      break

    case "config":
      core.keyPresent = ev.keyPresent === true
      core.pinned = ev.pinned === true
      break

    case "snapshot":
      core.siteInfo = ev.site || null
      core.devices = ev.devices || []
      core.deviceCount = ev.deviceCount || 0
      core.devicesOnline = ev.devicesOnline || 0
      core.clientCount = ev.clientCount || 0
      core.wired = ev.wired || 0
      core.wireless = ev.wireless || 0
      core.gateway = ev.gateway || null
      core.uplink = ev.uplink || ({})
      core.updatedAt = ev.at || 0
      core.lastError = ""
      core.authError = ""
      break

    case "pinned":
      core.pinned = true
      break

    case "unauthorised":
      core.authError = ev.message || "The console rejected the API key."
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
          console.warn("unifi: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      if (code !== 0)
        core.lastError = "The UniFi helper stopped (exit " + code + "). " +
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
