// Type - the panel.
//
// Every family, each drawn in itself. That is the only presentation that
// answers the question people actually have, which is "what does it look
// like", and it is why a list of names is not a font manager.

import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.type"
  ipcTarget: "omarchy.type"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property int  previewSize: setting("previewSize", 22)
  readonly property bool onlyMine: setting("onlyMine", false) === true
  readonly property string sampleSetting: setting("sample", "")
  readonly property string sample:
    sampleSetting.length > 0 ? sampleSetting
                             : "Sphinx of black quartz, judge my vow"

  property string filter: ""

  readonly property var shown: {
    if (!root.core) return []
    var out = []
    var needle = root.filter.toLowerCase()
    for (var i = 0; i < root.core.families.length; i++) {
      var f = root.core.families[i]
      if (root.onlyMine && !f.user) continue
      if (needle.length > 0 && f.family.toLowerCase().indexOf(needle) < 0) continue
      out.push(f)
    }
    return out
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
    target: "omarchy.type"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function install(path: string): void { if (root.core && path) root.core.install(path) }
    function refresh(): void { if (root.core) root.core.refresh() }
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

      DropArea {
        anchors.fill: parent
        onEntered: function (drag) { if (drag.hasUrls) drag.accept(Qt.CopyAction) }
        onDropped: function (drop) {
          if (!drop.hasUrls || !root.core) return
          for (var i = 0; i < drop.urls.length; i++)
            root.core.install(decodeURIComponent(String(drop.urls[i]).replace(/^file:\/\//, "")))
          drop.accept(Qt.CopyAction)
        }
      }

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(9)

        PanelHero {
          width: parent.width
          title: "Type"
          meta: root.core && root.core.available
                ? (root.core.familyCount + " FAMILIES  ·  " + root.core.mineCount + " YOURS")
                : "FONTCONFIG MISSING"
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

        // ---------------- filter ----------------
        Rectangle {
          width: parent.width
          height: Math.round(Style.space(26))
          radius: Style.cornerRadius
          color: Qt.rgba(root.barForeground.r, root.barForeground.g,
                         root.barForeground.b, 0.08)

          TextInput {
            id: search
            anchors { fill: parent; leftMargin: Style.space(8); rightMargin: Style.space(8) }
            verticalAlignment: TextInput.AlignVCenter
            color: root.barForeground
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            clip: true
            onTextChanged: root.filter = text

            Text {
              anchors.fill: parent
              verticalAlignment: Text.AlignVCenter
              visible: search.text.length === 0
              text: "Search families"
              color: root.barForeground
              opacity: 0.45
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }

        Toggle {
          width: parent.width
          label: "Only fonts I installed"
          description: "Hides the ones that came with the system, which is most of them."
          checked: root.onlyMine
          foreground: root.barForeground
          accent: Color.accent
          fontFamily: root.fontFamily
          onClicked: root.persistSettings({ onlyMine: !root.onlyMine })
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Text {
          width: parent.width
          visible: root.shown.length === 0
          text: root.core && !root.core.available
                ? "fontconfig is not installed, so there is nothing to list."
                : (root.filter.length > 0 ? "Nothing matches that."
                                          : "No fonts found.")
          color: root.barForeground
          opacity: 0.7
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // ---------------- the families ----------------
        Repeater {
          model: root.shown.slice(0, 60)

          Column {
            width: column.width
            spacing: Style.space(2)
            opacity: modelData.disabled ? 0.45 : 1.0

            // Load the actual file so the sample is drawn in the real face,
            // including families Qt would not otherwise resolve by name.
            FontLoader {
              id: face
              source: "file://" + modelData.preview
            }

            Item {
              width: parent.width
              height: Math.round(Style.space(20))

              Text {
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                text: modelData.family
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 1)
              }

              Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: Style.space(6)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.count + (modelData.count === 1 ? " style" : " styles")
                  color: root.barForeground
                  opacity: 0.5
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(8, Style.font.caption - 3)
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.disabled ? "off" : "on"
                  color: modelData.disabled ? root.barForeground : Color.accent
                  opacity: modelData.disabled ? 0.6 : 1.0
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(8, Style.font.caption - 3)
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -5
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.core.setEnabled(modelData.family, modelData.disabled)
                  }
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  visible: modelData.user
                  text: ""
                  color: bar ? bar.urgent : root.barForeground
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(8, Style.font.caption - 3)
                  MouseArea {
                    anchors.fill: parent
                    anchors.margins: -5
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.core.uninstall(modelData.family)
                  }
                }
              }
            }

            Text {
              width: parent.width
              text: root.sample
              elide: Text.ElideRight
              color: root.barForeground
              font.family: face.status === FontLoader.Ready ? face.name : modelData.family
              font.pixelSize: root.previewSize
            }

            Item { width: 1; height: Style.space(4) }
          }
        }

        Text {
          width: parent.width
          visible: root.shown.length > 60
          text: "…and " + (root.shown.length - 60) + " more. Search to narrow it down."
          color: root.barForeground
          opacity: 0.55
          font.family: root.fontFamily
          font.pixelSize: Math.max(9, Style.font.caption - 2)
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Text {
          width: parent.width
          text: "Drop a font file here to install it into " +
                (root.core ? root.core.userDir : "~/.local/share/fonts")
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
