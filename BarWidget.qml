// Gremlins - bar widget.
//
// Three styles, selected by settings.style. EXACTLY ONE is ever constructed:
// each lives behind a Loader with `active:`, because `visible: false` is not
// the same as "not built". AnimatedSprite carries a QQuickSpriteEngine with its
// own frame timer that ticks whether or not anything is drawn - instantiating
// all three cost ~4% shell CPU at idle before this was fixed.
//
//   "hang"    (default) big, on its own layer surface below the bar, hanging
//             over your wallpaper. Reserves no space, click-through except on
//             the creature itself.
//   "descend" the same animation, small, inside the bar cell.
//   "peek"    hooks its head over the bar's edge from below.
//
// Assets are chroma-keyed cut-outs with real 8-bit alpha, never tiles with
// baked-in darkness: a dark tile is invisible on an opaque bar and shows as a
// floating rectangle the moment the bar goes transparent.

import Quickshell
import Quickshell.Wayland
import QtQuick
import QtQuick.Window

Item {
  id: root

  // Injected by the bar host. See shell/plugins/bar/README.md.
  property var    bar
  property string moduleName
  property var    settings

  readonly property int    sz: bar ? bar.barSize : 26
  readonly property string pluginId: "io.github.mrjamesmyers.gremlins"
  readonly property string style: (settings && settings.style) || "hang"

  readonly property int minGap: (settings && settings.peekMinSeconds) || 45
  readonly property int maxGap: (settings && settings.peekMaxSeconds) || 120

  readonly property int  hangHeight: (settings && settings.hangHeight) || 190
  readonly property real hangX: (settings && settings.hangX) !== undefined ? settings.hangX : 0.74
  readonly property int  barPixels: (settings && settings.barPixels) || 43
  // How far the creature reaches up over the bar, so its fingers grip the bar
  // itself rather than dangling below it.
  // Screen y of sprite row 0. Measured from the sheet: rows 0-30 are forearm,
  // 32 the wrist, 34-60 fingers, 62+ the head. -31 puts row 62 (the head's
  // crown) exactly at the bar's lower edge, so the creature hangs flush with
  // the bar and everything above - hands and arms - is simply never drawn.
  // Extra pixels below the bar, so the whole grin clears it. Separate from
  // spriteTopY on purpose: spriteTopY decides WHICH rows get drawn, this
  // decides WHERE they land, so nudging it down can't re-introduce the hands.
  readonly property int  hangDrop: (settings && settings.hangDrop) !== undefined ? settings.hangDrop : 18
  readonly property int  spriteTopY: (settings && settings.spriteTopY) !== undefined ? settings.spriteTopY : -4

  // The bar is instantiated once per monitor, so without this every instance
  // spawns its own hanging window and they stack invisibly.
  readonly property bool ownsHang:
    Quickshell.screens.length > 0 && Screen.name === Quickshell.screens[0].name

  readonly property int spriteFrames: 92

  // A sprite sheet played by translating one clipped Image.
  //
  // NOT AnimatedSprite: its QQuickSpriteEngine keeps a frame timer alive even
  // with running:false and paused:true, which measured 3.25% shell CPU at idle
  // versus 0.08% for a static image. In a process that lives for weeks that is
  // not acceptable for a thing you see for ten seconds a minute. This is one
  // texture, no animation driver, and a stopped timer costs nothing.
  component Sprite: Item {
    id: sp
    property string sheet
    property int    cols: 7
    property int    frameW: 236
    property int    frameH: 180
    property int    frames: 42
    property int    fps: 12
    // Render only rows [srcTop, srcTop+srcRows) of each frame. Lets one sheet
    // and one frame counter drive two views on different layers, so the bar can
    // sit between the creature's body and its hands.
    property int    srcTop: 0
    property int    srcRows: 0          // 0 = whole frame
    property int    frame: 0
    property bool   reverse: false
    signal finished()

    clip: true
    readonly property int rows: srcRows > 0 ? srcRows : frameH
    // k is set by the owner from the FULL frame height, not this slice, so two
    // slices of the same sheet scale identically and stay aligned.
    property real k: height > 0 ? height / frameH : 1

    // Fade the tail. Even with a clean exit in the source, cutting straight to
    // nothing on the last frame reads as the animation breaking rather than
    // finishing.
    property int fadeFrames: 6
    opacity: (ticker.running && sp.frame > sp.frames - sp.fadeFrames)
             ? Math.max(0, (sp.frames - sp.frame) / sp.fadeFrames) : 1
    implicitWidth: Math.round(frameW * k)
    implicitHeight: Math.round(rows * k)

    Image {
      source: sp.sheet
      width:  Math.round(sp.cols * sp.frameW * sp.k)
      height: Math.round(Math.ceil(sp.frames / sp.cols) * sp.frameH * sp.k)
      x: -Math.round((sp.frame % sp.cols) * sp.frameW * sp.k)
      y: -Math.round((Math.floor(sp.frame / sp.cols) * sp.frameH + sp.srcTop) * sp.k)
      smooth: true
      cache: true
    }

    Timer {
      id: ticker
      interval: Math.max(16, Math.round(1000 / sp.fps))
      repeat: true
      running: false
      onTriggered: sp.step()
    }

    function play(rev) {
      sp.reverse = !!rev
      sp.frame = rev ? sp.frames - 1 : 0
      ticker.start()
    }
    function halt() { ticker.stop() }
    function step() {
      var n = sp.frame + (sp.reverse ? -1 : 1)
      if (n < 0 || n >= sp.frames) { ticker.stop(); sp.finished(); return }
      sp.frame = n
    }
    readonly property bool playing: ticker.running
  }

  implicitWidth: root.style === "hang"     ? 6
               : root.style === "descend" ? Math.round(sz * 94 / 72)
               :                            Math.round(sz * 1.75)
  implicitHeight: sz
  clip: root.style !== "hang"

  property bool watching: false
  property bool away: false
  // Gates construction of the hang window. A hidden-but-built PanelWindow with
  // a 1652x1080 sheet still cost 1.27% shell CPU at idle; not building it costs
  // nothing, and QQuickPixmap caches the decode so re-showing is cheap.
  property bool hangLive: false
  property bool hangPending: false

  readonly property var actor:
      root.style === "hang"    ? hangL.item
    : root.style === "descend" ? descendL.item
    :                            peekL.item

  Loader {
    id: hangL
    active: root.style === "hang" && root.ownsHang && root.hangLive
    sourceComponent: hangComp
    onLoaded: if (root.hangPending) { root.hangPending = false; item.arrive() }
  }
  Loader { id: descendL; active: root.style === "descend"; anchors.fill: parent; sourceComponent: descendComp }
  Loader { id: peekL;    active: root.style === "peek";    anchors.fill: parent; sourceComponent: peekComp }

  // ---------------- hang ----------------
  //
  // One layer surface, on the bottom layer so the bar draws over it. The
  // creature hangs flush with the bar's lower edge and its arms are never
  // rendered at all - an earlier version drew them on a second overlay surface
  // above the bar, and dark fur on a dark bar simply never read.
  Component {
    id: hangComp
    Item {
      id: hangRoot
      property alias sprite: bodySprite

      function arrive() { hangRoot.frameIdx = 0; hangRoot.held = false; grinHold.stop(); hangRoot.playing = true; clock.restart() }
      function leave()  { }        // the sheet ends with it already gone
      function reset()  { clock.stop(); grinHold.stop(); hangRoot.held = false; hangRoot.playing = false; hangRoot.frameIdx = 0 }

      // The parent Item owns the frame counter. Binding one window's sprite to
      // an id inside ANOTHER PanelWindow does not track - each window is its own
      // top-level scene graph, so the binding evaluates once and then freezes,
      // silently, with no warning. Both slices read from here instead.
      property int  frameIdx: 0
      property bool playing: false
      // No fade. The sheet now carries the full retreat - the creature climbs
      // back up and out of frame under its own power, and the hands-only tail
      // frames draw nothing because only rows below the bar are ever rendered.
      // A fade was only ever compensating for cutting the animation short.

      // The grin lands at sheet frames 71-79. Without a deliberate pause it
      // flashes past in three quarters of a second and nobody sees it.
      readonly property int holdFrame: (root.settings && root.settings.holdFrame) || 74
      readonly property int holdMs:    (root.settings && root.settings.holdMs)    || 1800
      property bool held: false

      Timer {
        id: clock
        interval: 83
        repeat: true
        running: false
        onTriggered: {
          if (hangRoot.frameIdx + 1 >= root.spriteFrames) { clock.stop(); hangRoot.playing = false; return }
          hangRoot.frameIdx += 1
          if (!hangRoot.held && hangRoot.frameIdx === hangRoot.holdFrame) {
            hangRoot.held = true
            clock.stop()
            grinHold.start()
          }
        }
      }
      Timer { id: grinHold; repeat: false; interval: hangRoot.holdMs; onTriggered: clock.start() }

      readonly property real k: root.hangHeight / 160
      readonly property int  spriteW: Math.round(247 * k)
      // Where the drawn slice starts, derived from screen geometry: everything
      // above the bar's lower edge is simply never rendered.
      readonly property int  bodyTopRow:  Math.max(0, Math.round((root.barPixels - root.spriteTopY) / k))

      // body - beneath the bar
      PanelWindow {
        id: bodyWin
        visible: !root.away && (root.watching || hangRoot.playing)
        anchors { top: true; left: true; right: true }
        implicitHeight: root.barPixels + root.hangHeight
        color: "transparent"
        WlrLayershell.namespace: "omarchy-gremlins-body"
        WlrLayershell.layer: WlrLayer.Bottom
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        mask: Region { item: bodySprite }

        Sprite {
          id: bodySprite
          sheet: Qt.resolvedUrl("assets/descend-big.png")
          cols: 10; frameW: 247; frameH: 160; frames: root.spriteFrames; fps: 12
          k: hangRoot.k
          frame: hangRoot.frameIdx
          srcTop: hangRoot.bodyTopRow
          srcRows: 160 - hangRoot.bodyTopRow
          width: hangRoot.spriteW
          height: Math.round((160 - hangRoot.bodyTopRow) * hangRoot.k)
          x: Math.round((bodyWin.width - hangRoot.spriteW) * root.hangX)
          y: root.barPixels + root.hangDrop
          MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.trigger() }
        }
      }

    }
  }

  // ---------------- descend (in-bar) ----------------
  Component {
    id: descendComp
    Sprite {
      id: small
      sheet: Qt.resolvedUrl("assets/descend.png")
      cols: 10; frameW: 74; frameH: 48; frames: root.spriteFrames; fps: 12
      height: root.height
      width: root.width
      opacity: root.away ? 0 : 1
      Behavior on opacity { NumberAnimation { duration: 200 } }
      function arrive() { play(false) }
      function leave()  { }        // the sheet ends with it already gone
      function reset()  { halt(); frame = 0 }
    }
  }

  // ---------------- peek (in-bar) ----------------
  Component {
    id: peekComp
    Item {
      id: pk
      readonly property real hiddenY: root.height + 2
      readonly property real shownY:  Math.round(root.height * 0.06)

      function arrive() { img.y = shownY; duck.restart(); glance.restart() }
      function leave()  { img.y = hiddenY; img.anchors.horizontalCenterOffset = 0 }
      function reset()  { img.y = hiddenY }

      Image {
        id: img
        source: Qt.resolvedUrl("assets/peek.png")
        height: root.height
        fillMode: Image.PreserveAspectFit
        anchors.horizontalCenter: parent.horizontalCenter
        y: pk.hiddenY
        opacity: root.away ? 0 : 1
        Behavior on y { NumberAnimation { duration: root.watching ? 900 : 520
                        easing.type: root.watching ? Easing.OutCubic : Easing.InCubic } }
        Behavior on anchors.horizontalCenterOffset { NumberAnimation { duration: 420; easing.type: Easing.InOutQuad } }
        Behavior on opacity { NumberAnimation { duration: 200 } }
      }
      // A photographic face can't blink by squashing - it looks broken. It ducks
      // below the edge instead, which is what a real thing peeking would do.
      Timer { id: duck; interval: 1800 + Math.random()*1500; repeat: true; running: root.watching; onTriggered: duckAnim.restart() }
      SequentialAnimation {
        id: duckAnim
        NumberAnimation { target: img; property: "y"; to: pk.shownY + root.height*0.42; duration: 130; easing.type: Easing.InQuad }
        PauseAnimation { duration: 90 }
        NumberAnimation { target: img; property: "y"; to: pk.shownY; duration: 160; easing.type: Easing.OutQuad }
      }
      Timer { id: glance; interval: 2200 + Math.random()*1800; repeat: true; running: root.watching
              onTriggered: img.anchors.horizontalCenterOffset = (Math.random()<0.5?-1:1) * Math.max(1, Math.round(root.width*0.05)) }
    }
  }

  // ---------------- cycle ----------------
  Timer {
    id: nextPeek
    running: !root.away && (root.style !== "hang" || root.ownsHang)
    repeat: false
    interval: (root.minGap + Math.random()*(root.maxGap-root.minGap)) * 1000
    onTriggered: root.arrive()
  }
  Timer { id: stayFor; repeat: false; onTriggered: root.leave() }
  Timer {
    id: hangTeardown
    repeat: false
    interval: 400
    onTriggered: { root.hangLive = false; root.hangPending = false }
  }

  function arrive() {
    if (root.away) return
    root.watching = true
    if (root.style === "hang") {
      if (!root.ownsHang) return
      if (hangL.item) hangL.item.arrive()
      else { root.hangPending = true; root.hangLive = true }   // built, then arrives onLoaded
    } else if (root.actor) {
      root.actor.arrive()
    }
    stayFor.interval = Math.round(root.spriteFrames / 12 * 1000) + 2400
    stayFor.restart()
  }

  function leave() {
    root.watching = false
    if (root.actor) root.actor.leave()
    // Tear the hang window down once the climb-out has had time to finish.
    // A signal-driven teardown proved unreliable here, and a window that
    // survives is the difference between 0.1% and 1.5% idle CPU forever - so
    // this is a deadline, not an optimisation.
    if (root.style === "hang") hangTeardown.restart()
    nextPeek.interval = (root.minGap + Math.random()*(root.maxGap-root.minGap)) * 1000
    nextPeek.restart()
  }

  function trigger() {
    if (!bar) return
    bar.run("omarchy-shell shell toggle " + root.pluginId)
    root.away = true          // it isn't here now - it's on your screen
    root.watching = false
    stayFor.stop()
    comeBack.restart()
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onEntered: {
      if (bar) bar.showTooltip(root, "Gremlins - click to replay the bumper")
      if (!root.away && !root.watching) root.arrive()
    }
    onExited: {
      if (bar) bar.hideTooltip(root)

    }
    onClicked: root.trigger()
  }

  Timer {
    id: comeBack
    interval: 3600
    onTriggered: { root.away = false; root.hangLive = false; root.hangPending = false; hangTeardown.stop(); nextPeek.restart() }
  }

  Component.onCompleted: { nextPeek.interval = 7000; nextPeek.restart() }
}
