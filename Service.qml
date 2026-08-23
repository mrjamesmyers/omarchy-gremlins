// Gremlins — startup service.
//
// Headless singleton, loaded at shell startup. Its only job is to summon the
// bumper once per session and then stay out of the way.
//
// VERIFY ON BOX: confirm how a service reaches the shell's summon IPC, and
// what the correct startup delay is so the bumper doesn't race shell init.
// If auto-play proves unreliable, ship replay-only and say so in the README —
// a bumper that sometimes fights the shell is worse than one you trigger.

import QtQuick

QtObject {
  id: root

  property var settings
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"
  readonly property bool playOnLogin: !(settings && settings.playOnLogin === false)

  property Timer startup: Timer {
    interval: 1200          // let the shell finish coming up first
    running: root.playOnLogin
    repeat: false
    onTriggered: root.summon()
  }

  function summon() {
    // TODO(box): replace with the verified in-process summon call if one is
    // exposed to services; shelling out is the fallback, not the goal.
    console.log("gremlins: summoning bumper")
  }
}
