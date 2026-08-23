// Gremlins - startup service.
//
// Headless singleton, loaded at shell startup. Summons the bumper once per
// session, then stays out of the way. Looping is NOT its business: DHH's
// stated design is one-off on boot by default, and anything that runs forever
// is something the user opts into themselves.

import Quickshell
import Quickshell.Io
import QtQuick

Item {
  id: root

  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"
  property bool playOnLogin: true

  Process { id: summonProc }

  Timer {
    // Let the shell finish coming up before stealing the screen. Summoning
    // into a half-built shell races the bar and the background plugin.
    interval: 1500
    running: root.playOnLogin
    repeat: false
    onTriggered: {
      summonProc.command = ["omarchy-shell", "-q", "shell", "summon", root.pluginId]
      summonProc.running = true
    }
  }
}
