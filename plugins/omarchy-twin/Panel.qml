// Twin - the panel.
//
// Groups ordered by how much space they waste, because that is the reason
// anybody opened this. Every group keeps its first copy: the delete button
// removes the others, and the helper refuses to remove the kept one even if
// asked, so there is no sequence of clicks that leaves you with nothing.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.twin"
  ipcTarget: "omarchy.twin"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string rootsSetting: setting("roots", "")
  readonly property bool skipHidden: setting("skipHidden", true) !== false
  readonly property int  minSizeKb: setting("minSizeKb", 4)

  readonly property var scanRoots: {
    if (rootsSetting.length === 0) return root.core ? [root.core.home] : []
    return rootsSetting.split(":").filter(function (s) { return s.length > 0 })
  }

  function human(bytes) {
    var b = Number(bytes) || 0
    if (b < 1024) return b + " B"
    var units = ["KB", "MB", "GB", "TB"]
    var i = -1
    do { b /= 1024; i++ } while (b >= 1024 && i < units.length - 1)
    return (b < 10 ? b.toFixed(1) : Math.round(b)) + " " + units[i]
  }

  function shortPath(path) {
    var home = root.core ? root.core.home : ""
    return home.length > 0 && path.indexOf(home) === 0 ? "~" + path.substring(home.length) : path
  }

  function persistSettings(values) {
    var entry = { id: root.moduleName }
    for (var k in root.settings) if (k !== "id") entry[k] = root.settings[k]
    for (var v in values) entry[v] = values[v]
    root.settings = entry
    if (root.hostWidget && "settings" in root.hostWidget) root.hostWidget.settings = entry
    if (root.bar && root.bar.shell
        && typeof root.bar.shell.updateEntryInline === "function")
      root.bar.shell.updateEntryInline(root.moduleName, entry)
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.twin"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function scan(): void { root.startScan() }
    function cancel(): void { if (root.core) root.core.cancel() }
  }

  function startScan() {
    if (!root.core) return
    root.core.scan(root.scanRoots, root.skipHidden, root.minSizeKb * 1024)
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(9)

        PanelHero {
          width: parent.width
          title: "Twin"
          meta: {
            if (!root.core) return "STARTING"
            if (root.core.scanning) return "SCANNING"
            if (root.core.groups.length > 0)
              return root.human(root.core.reclaimable).toUpperCase() + " RECLAIMABLE"
            return "NO DUPLICATES"
          }
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        Text {
          width: parent.width
          visible: !!(root.core && root.core.lastError.length > 0)
          text: root.core ? root.core.lastError : ""
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        // ---------------- scanning ----------------
        Item {
          width: parent.width
          height: scanButton.implicitHeight

          Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            width: parent.width - scanButton.width - Style.space(10)
            elide: Text.ElideMiddle
            color: root.barForeground
            opacity: 0.7
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 1)
            text: {
              if (root.core && root.core.scanning) {
                if (root.core.stage === "counting")
                  return "Counting files… " + root.core.scanned
                return "Hashing " + root.core.done + " of " + root.core.total
              }
              if (root.core && root.core.scanned > 0)
                return root.core.scanned + " files checked" +
                       (root.core.hardlinked > 0
                        ? "  ·  " + root.core.hardlinked + " hard-linked, left alone" : "")
              return root.scanRoots.map(root.shortPath).join(", ")
            }
          }

          PanelActionButton {
            id: scanButton
            anchors.right: parent.right
            iconText: root.core && root.core.scanning ? "" : ""
            tooltipText: root.core && root.core.scanning ? "Stop" : "Scan for duplicates"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: {
              if (root.core && root.core.scanning) root.core.cancel()
              else root.startScan()
            }
          }
        }

        Rectangle {
          width: parent.width
          height: Math.max(3, Style.space(3))
          radius: height / 2
          visible: !!(root.core && root.core.scanning && root.core.total > 0)
          color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                         root.barForeground.b, 0.16)
          Rectangle {
            width: parent.width * (root.core && root.core.total > 0
                                   ? Math.min(1, root.core.done / root.core.total) : 0)
            height: parent.height
            radius: parent.radius
            color: Color.accent
            Behavior on width { NumberAnimation { duration: 150 } }
          }
        }

        Text {
          width: parent.width
          visible: !!(root.core && root.core.lastDelete)
          text: root.core && root.core.lastDelete
                ? ("Removed " + root.core.lastDelete.removed + ", freed " +
                   root.human(root.core.lastDelete.freed) +
                   (root.core.lastDelete.refused > 0
                    ? "  ·  " + root.core.lastDelete.refused + " refused" : ""))
                : ""
          color: Color.accent
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 1)
          wrapMode: Text.WordWrap
        }

        PanelSeparator
          { width: parent.width; foreground: root.barForeground
            visible: !!(root.core && root.core.groups.length > 0) }

        // ---------------- results ----------------
        Repeater {
          model: root.core ? root.core.groups.slice(0, 40) : []

          Column {
            width: column.width
            spacing: Style.space(2)

            Item {
              width: parent.width
              height: Math.round(Style.space(20))

              Text {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                text: modelData.paths.length + " copies  ·  " +
                      root.human(modelData.size) + " each  ·  " +
                      root.human(modelData.waste) + " wasted"
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 1)
              }

              Text {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                text: "Keep the first "
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 2)
                MouseArea {
                  anchors.fill: parent
                  anchors.margins: -5
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.core.remove(modelData.paths.slice(1), modelData.paths[0])
                }
              }
            }

            Repeater {
              model: modelData.paths
              Text {
                width: column.width
                elide: Text.ElideMiddle
                text: (index === 0 ? "  keep   " : "  delete ") + root.shortPath(modelData)
                color: root.barForeground
                opacity: index === 0 ? 0.85 : 0.55
                font.family: root.fontFamily
                font.pixelSize: Math.max(8, Style.font.caption - 2)
              }
            }

            Item { width: 1; height: Style.space(5) }
          }
        }

        Text {
          width: parent.width
          visible: !!(root.core && (root.core.groups.length > 40 || root.core.truncated > 0))
          text: root.core
                ? ("Showing 40 of " + (root.core.groups.length + root.core.truncated) +
                   " groups.") : ""
          color: root.barForeground
          opacity: 0.55
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Toggle {
          width: parent.width
          label: "Skip hidden files"
          description: "Dotfiles and caches are duplicated by design."
          checked: root.skipHidden
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ skipHidden: !root.skipHidden })
        }

        Text {
          width: parent.width
          text: "Only files over " + root.minSizeKb + " KB are considered. " +
                "Hard links are never offered for deletion — they already share their storage."
          color: root.barForeground
          opacity: 0.55
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
