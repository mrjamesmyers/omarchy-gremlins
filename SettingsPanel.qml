// Settings for the Gremlins plugin.
//
// Quattro's manifest contract has a `barWidget.schema` field and shell.qml
// stores it, but nothing in 4.0.0.alpha renders it - BarWidgetRegistry's
// metadataFor() has no call sites, and the whole qs.Ui form-control set is
// used by no shipped panel. The renderer was removed, not never written. So
// this is hand-built out of the same primitives the first-party panels use,
// which is also the only way to get a live preview and preset chips rather
// than a generic spinner.
//
// Opened by right-clicking the bar widget, which calls toggle() on this object
// in-process. NOT by `omarchy-shell shell toggle <plugin-id>`: this plugin
// declares `overlay` in kinds, so isBarWidgetPanelPlugin() returns false and
// that route summons the login bumper instead. Service.qml depends on that
// behaviour, so it must not be "fixed".

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.gremlins"
  ipcTarget: "omarchy.gremlins"
  // We own the handler ourselves so exactly one monitor's copy claims the
  // target; a bar surface is instantiated per monitor and the second
  // registration would collide.
  manageIpc: false

  // ---- injected by BarWidget.injectPanel() ----
  property Item anchorItem: null
  property var hostWidget: null
  property bool primary: false

  // ---- current values ----
  readonly property string styleValue: setting("style", "hang")
  readonly property string wallpaper: setting("wallpaper", "")
  readonly property int everySec: setting("wallpaperEverySeconds", 60)
  readonly property bool wallpaperFill: setting("wallpaperFill", true) !== false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---- the wallpaper catalogue ----
  // Values must match the files in assets/wallpapers/ exactly: BarWidget builds
  // the URL by string concatenation, so an unknown value yields a broken image
  // rather than an error.
  readonly property var wallpaperOptions: [
    { value: "",            label: "Off" },
    { value: "tv",          label: "Gremlins — TV" },
    { value: "nineteen84",  label: "Gremlins — 1984" },
    { value: "runners",     label: "Gremlins — Runners" },
    { value: "viking",      label: "Scene — Viking" },
    { value: "highlands",   label: "Scene — Highlands" },
    { value: "ycombinator", label: "Scene — Y Combinator" },
    { value: "seventies",   label: "Scene — 1970s" },
    { value: "pumpkin",     label: "Scene — Pumpkin Spice" },
    { value: "raptor",      label: "Scene — Velociraptor" }
  ]

  readonly property var intervalOptions: [
    { value: "30",  label: "30s" },
    { value: "60",  label: "1m" },
    { value: "120", label: "2m" },
    { value: "300", label: "5m" }
  ]

  function labelFor(v) {
    for (var i = 0; i < wallpaperOptions.length; i++)
      if (wallpaperOptions[i].value === v) return wallpaperOptions[i].label
    return v
  }

  // ---- persistence ----
  // updateEntryInline REPLACES the entry with {id} + whatever you pass, so any
  // key omitted here is deleted from the user's config. The sprite calibration
  // keys (hangHeight, spriteTopY, holdFrame, ...) are JSON-only and would be
  // silently wiped the first time someone touched a dropdown. Merge first.
  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var k in root.settings)
      if (k !== "id") entry[k] = root.settings[k]
    for (var v in values) entry[v] = values[v]

    // Apply locally before writing: the value round-trips through
    // applyBarConfig -> inlineSettingsDelta, and skipping this shows a visible
    // lag between the click and the redraw.
    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget)
      root.hostWidget.settings = entry

    if (root.bar && root.bar.shell
        && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  // True when there is nowhere on disk to write to, in which case changes are
  // session-only and the user deserves to be told rather than confused later.
  readonly property bool canPersist:
    !!(bar && bar.shell && typeof bar.shell.updateEntryInline === "function")

  // ---- keyboard cursor ----
  property bool cursorActive: false
  property string focusSection: "style"
  property int selectedIndex: 0

  readonly property var visibleSections:
    root.wallpaper === "" ? ["style", "wallpaper"]
                          : ["style", "wallpaper", "every", "fill", "play"]

  function sectionIsHorizontal(s) { return s === "style" || s === "every" }

  function sectionLength(s) {
    if (s === "style") return 3
    if (s === "every") return root.intervalOptions.length
    return 1
  }

  function clampCursor() {
    var n = sectionLength(root.focusSection)
    if (root.selectedIndex >= n) root.selectedIndex = n - 1
    if (root.selectedIndex < 0) root.selectedIndex = 0
  }

  function moveCursor(dy) {
    var list = root.visibleSections
    var i = list.indexOf(root.focusSection)
    if (i < 0) i = 0
    i = (i + dy + list.length) % list.length
    root.focusSection = list[i]
    root.selectedIndex = 0
    clampCursor()
  }

  function moveCursorH(dx) {
    if (!sectionIsHorizontal(root.focusSection)) return
    var n = sectionLength(root.focusSection)
    root.selectedIndex = (root.selectedIndex + dx + n) % n
  }

  function activateCursor() {
    var s = root.focusSection
    if (s === "style") {
      var styles = ["hang", "descend", "peek"]
      root.persistSettings({ style: styles[root.selectedIndex] })
    } else if (s === "wallpaper") {
      wallpaperDropdown.toggle()
    } else if (s === "every") {
      root.persistSettings({
        wallpaperEverySeconds: parseInt(root.intervalOptions[root.selectedIndex].value)
      })
    } else if (s === "fill") {
      root.persistSettings({ wallpaperFill: !root.wallpaperFill })
    } else if (s === "play") {
      root.playNow()
    }
  }

  // Ask the bar widget to run its wallpaper event immediately, so choosing a
  // wallpaper can be confirmed without waiting out the interval.
  function playNow() {
    if (root.hostWidget && typeof root.hostWidget.playWallpaperNow === "function")
      root.hostWidget.playWallpaperNow()
  }

  onOpenedChanged: {
    if (opened) {
      cursorActive = false
      focusSection = "style"
      selectedIndex = 0
    }
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.gremlins"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function replay(): void {
      if (root.hostWidget && typeof root.hostWidget.trigger === "function")
        root.hostWidget.trigger()
    }
    // Scriptable wallpaper control. Handy for demos and for anyone who would
    // rather bind a scene to a key than open a panel.
    function setWallpaper(name: string): void { root.persistSettings({ wallpaper: name }) }
    function playScene(): void { root.playNow() }
    function currentWallpaper(): string { return root.wallpaper }
  }

  KeyboardPanel {
    id: panel

    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      // While the dropdown popup owns input the catcher must stand down, or
      // its BeforeItem priority eats the arrow keys the popup needs.
      blocked: wallpaperDropdown.popupOpen

      onMoveRequested: function (dx, dy) {
        // The first arrow press reveals the cursor rather than moving it, so
        // the highlight never appears somewhere the user did not look.
        if (!root.cursorActive) { root.cursorActive = true; return }
        if (dy !== 0) root.moveCursor(dy)
        else if (dx !== 0) root.moveCursorH(dx)
      }
      onActivateRequested: if (root.cursorActive) root.activateCursor()
      onCloseRequested: root.close()
      onTabRequested: function (direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(12)

        PanelHero {
          width: parent.width
          title: "Gremlins"
          meta: "PLUGIN SETTINGS"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        // ---------------- style ----------------
        PanelSectionHeader {
          text: "GREMLIN STYLE"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        ButtonGroup {
          id: styleGroup
          width: parent.width
          spacing: Style.space(6)
          value: root.styleValue
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          cursorIndex: root.focusSection === "style" && root.cursorActive
                       ? root.selectedIndex : -1
          options: [
            { value: "hang",    label: "Hang",    tooltip: "Hangs off the bar, over your wallpaper" },
            { value: "descend", label: "Descend", tooltip: "Climbs down inside the bar cell" },
            { value: "peek",    label: "Peek",    tooltip: "Eyes over the bar's lower edge" }
          ]
          onChanged: function (v) { root.persistSettings({ style: v }) }
          onHovered: function (i, on) {
            if (on) { root.cursorActive = true; root.focusSection = "style"; root.selectedIndex = i }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        // ---------------- wallpaper ----------------
        PanelSectionHeader {
          text: "ANIMATED WALLPAPER"
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Dropdown {
          id: wallpaperDropdown
          width: parent.width
          label: "Scene"
          value: root.wallpaper
          options: root.wallpaperOptions
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          hasCursor: root.focusSection === "wallpaper" && root.cursorActive
          onChanged: function (v) { root.persistSettings({ wallpaper: v }) }
          onHovered: function (on) {
            if (on) { root.cursorActive = true; root.focusSection = "wallpaper" }
          }
        }

        // A still preview, because the names alone say nothing. This is the
        // frame the desktop actually rests on between plays, so what is shown
        // here is literally what the user will be looking at.
        Item {
          width: parent.width
          height: root.wallpaper === "" ? 0 : Math.round(parent.width * 9 / 16)
          visible: root.wallpaper !== ""
          clip: true

          Image {
            id: preview
            anchors.fill: parent
            source: root.wallpaper === ""
                    ? ""
                    : Qt.resolvedUrl("assets/wallpapers/" + root.wallpaper + "-still.jpg")
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: true
          }

          Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                                  root.barForeground.b, 0.18)
            border.width: 1
            radius: Style.cornerRadius
          }

          Text {
            anchors { left: parent.left; bottom: parent.bottom; margins: Style.space(6) }
            text: preview.status === Image.Error ? "preview missing" : root.labelFor(root.wallpaper)
            color: "white"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.7)
          }
        }

        // ---------------- interval ----------------
        PanelSectionHeader {
          text: "HOW OFTEN"
          foreground: root.barForeground
          fontFamily: root.fontFamily
          visible: root.wallpaper !== ""
        }

        ButtonGroup {
          id: everyGroup
          width: parent.width
          spacing: Style.space(6)
          visible: root.wallpaper !== ""
          value: String(root.everySec)
          options: root.intervalOptions
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          cursorIndex: root.focusSection === "every" && root.cursorActive
                       ? root.selectedIndex : -1
          onChanged: function (v) {
            root.persistSettings({ wallpaperEverySeconds: parseInt(v) })
          }
          onHovered: function (i, on) {
            if (on) { root.cursorActive = true; root.focusSection = "every"; root.selectedIndex = i }
          }
        }

        Toggle {
          id: fillToggle
          width: parent.width
          visible: root.wallpaper !== ""
          label: "Fill the screen"
          description: "Crop to fill. Off letterboxes the scene instead."
          checked: root.wallpaperFill
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          hasCursor: root.focusSection === "fill" && root.cursorActive
          // Toggle is stateless - it reports the click and we flip the value.
          onClicked: root.persistSettings({ wallpaperFill: !root.wallpaperFill })
          onHovered: function (on) {
            if (on) { root.cursorActive = true; root.focusSection = "fill" }
          }
        }

        Item {
          width: parent.width
          height: playButton.implicitHeight
          visible: root.wallpaper !== ""

          PanelActionButton {
            id: playButton
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Play the scene now"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            hasCursor: root.focusSection === "play" && root.cursorActive
            onClicked: root.playNow()
            onHovered: function (on) {
              if (on) { root.cursorActive = true; root.focusSection = "play" }
            }
          }
        }

        // Settings only persist if this widget id exists in bar.layout or
        // plugins[]. Saying so beats letting the user wonder why a setting
        // reverted after a restart.
        Text {
          width: parent.width
          visible: !root.canPersist
          text: "Add Gremlins to the bar to save these settings."
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
