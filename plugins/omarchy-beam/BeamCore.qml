// Beam - the daemon owner and the single source of truth for plugin state.
//
// Exactly one of these exists, no matter how many monitors are attached: the
// bar instantiates a widget per screen, and three copies of a network daemon
// all binding UDP 53317 is three copies of a bug. BarWidget.qml guards this
// behind `active: ownsDaemon`, the same way the Gremlins widget guards its
// hanging window.
//
// Everything network-shaped lives in helper/beamd.py. QML cannot join a
// multicast group, cannot listen on a TCP port, and cannot stream a 4 GB file
// off disk without reading it into the shell's heap first, so it does none of
// those things - it starts a process, reads newline-delimited JSON events out
// of it, and writes newline-delimited JSON commands back in.

import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: core

  // ---- configuration, pushed down from the widget's settings ----
  property string alias_: ""
  property string downloadDir: ""
  property bool   autoAccept: false
  property string pin: ""
  property bool   quiet: false
  property bool   notifyOnReceive: true

  // ---- state, read by the widget and the panel ----
  property bool   ready: false
  property string identity: ""          // our own alias, as peers see it
  property string fingerprint: ""
  property string protocol: ""
  property var    addresses: []
  property string saveDir: ""
  property string lastError: ""

  // Peers are held in a plain array of plain objects rather than a
  // ListModel so the panel can rebind the whole list at once; the list is
  // never long enough for incremental updates to be worth the machinery.
  property var peers: []

  // The one incoming request currently waiting on the user. null when there
  // is nothing to answer.
  property var pending: null

  // A transfer in flight, either direction. null when idle.
  property var transfer: null

  signal finished(bool ok, string message, var saved)

  readonly property bool running: daemon.running
  readonly property string helperPath:
    Qt.resolvedUrl("helper/beamd.py").toString().replace("file://", "")

  // ---- talking to the daemon ------------------------------------------

  function post(msg) {
    if (!daemon.running) return
    try {
      daemon.write(JSON.stringify(msg) + "\n")
    } catch (e) {
      console.warn("beam: could not reach the helper:", e)
    }
  }

  function pushConfig() {
    post({
      cmd: "config",
      alias: core.alias_,
      downloadDir: core.downloadDir,
      autoAccept: core.autoAccept,
      pin: core.pin,
      quiet: core.quiet
    })
  }

  function refresh()                 { post({ cmd: "scan" }) }
  function send(fingerprints, paths) { post({ cmd: "send", targets: fingerprints, paths: paths }) }
  function accept(sessionId)         { post({ cmd: "accept", sessionId: sessionId }); core.pending = null }
  function reject(sessionId)         { post({ cmd: "reject", sessionId: sessionId }); core.pending = null }
  function cancel(sessionId)         { post({ cmd: "cancel", sessionId: sessionId }) }

  onAlias_Changed: pushConfig()
  onDownloadDirChanged: pushConfig()
  onAutoAcceptChanged: pushConfig()
  onPinChanged: pushConfig()
  onQuietChanged: pushConfig()

  // ---- peer bookkeeping ------------------------------------------------

  function upsertPeer(device) {
    var next = []
    var replaced = false
    for (var i = 0; i < core.peers.length; i++) {
      if (core.peers[i].fingerprint === device.fingerprint) {
        next.push(device)
        replaced = true
      } else {
        next.push(core.peers[i])
      }
    }
    if (!replaced) next.push(device)
    next.sort(function (a, b) { return (a.alias || "").localeCompare(b.alias || "") })
    core.peers = next
  }

  function dropPeer(fingerprint) {
    var next = []
    for (var i = 0; i < core.peers.length; i++)
      if (core.peers[i].fingerprint !== fingerprint) next.push(core.peers[i])
    core.peers = next
  }

  function notify(summary, body) {
    if (!core.notifyOnReceive) return
    Quickshell.execDetached(["notify-send", "-a", "Beam", "-i", "folder-download",
                             summary, body])
  }

  // ---- the event stream ------------------------------------------------

  function handle(ev) {
    switch (ev.ev) {
    case "ready":
      core.ready = true
      core.identity = ev.alias || ""
      core.fingerprint = ev.fingerprint || ""
      core.protocol = ev.protocol || ""
      core.addresses = ev.addresses || []
      core.saveDir = ev.downloadDir || ""
      core.lastError = ""
      // Settings the user changed while the helper was down are only real
      // once it is up, so replay them rather than assuming they took.
      pushConfig()
      break

    case "config":
      core.identity = ev.alias || core.identity
      core.saveDir = ev.downloadDir || core.saveDir
      break

    case "peer":
      if (ev.device) upsertPeer(ev.device)
      break

    case "peer-gone":
      dropPeer(ev.fingerprint)
      break

    case "incoming":
      core.pending = {
        sessionId: ev.sessionId,
        from: ev.sender ? (ev.sender.alias || "Unknown device") : "Unknown device",
        deviceType: ev.sender ? ev.sender.deviceType : "desktop",
        files: ev.files || [],
        totalSize: ev.totalSize || 0
      }
      // An auto-accepted transfer needs no dialog, but the user should still
      // be told a stranger just wrote to their disk.
      if (ev.autoAccepted) core.pending = null
      break

    case "outgoing":
      core.transfer = {
        sessionId: ev.sessionId, direction: "out", peer: ev.to || "",
        fileName: "", bytes: 0, total: ev.totalSize || 0, done: 0, count: ev.count || 1
      }
      break

    case "progress":
      core.transfer = {
        sessionId: ev.sessionId, direction: ev.direction,
        peer: core.transfer ? core.transfer.peer : "",
        fileName: ev.fileName || "", bytes: ev.bytes || 0, total: ev.total || 0,
        done: ev.done || 0, count: ev.count || 1
      }
      break

    case "finished":
      core.transfer = null
      if (ev.direction === "in" && ev.ok) {
        var n = (ev.saved || []).length
        notify("Beam", n === 1 ? "1 file received" : n + " files received")
      }
      core.finished(ev.ok === true, ev.message || "", ev.saved || [])
      break

    case "error":
      core.lastError = ev.message || "Something went wrong."
      break
    }
  }

  // ---- the process -----------------------------------------------------

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
          console.warn("beam: unreadable event:", text)
        }
      }
    }

    onExited: function (code, status) {
      core.ready = false
      core.peers = []
      core.pending = null
      core.transfer = null
      if (code !== 0)
        core.lastError = "The Beam helper stopped (exit " + code + "). " +
                         "Check that python3 is installed."
    }
  }

  // The helper is cheap to run and expensive to be without - if it dies
  // because the machine suspended mid-transfer, the plugin should come back
  // by itself rather than waiting for a shell restart.
  Timer {
    interval: 5000
    running: !daemon.running
    repeat: true
    onTriggered: if (!daemon.running) daemon.running = true
  }

  // A nudge on a slow cycle. The helper announces itself every 25 seconds on
  // its own; this only re-asks for the peer list, which costs one line of
  // JSON and keeps a panel that has been open for an hour honest.
  Timer {
    interval: 30000
    running: core.ready
    repeat: true
    onTriggered: core.refresh()
  }
}
