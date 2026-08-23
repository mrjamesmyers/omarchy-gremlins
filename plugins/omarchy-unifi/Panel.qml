// UniFi - the panel.
//
// Unconfigured it is setup instructions, because the alternative is an empty
// box and a user who does not know an API key is missing. Configured it is
// the gateway, the adopted devices, and who is on the network.

import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root

  moduleName: "io.github.mrjamesmyers.unifi"
  ipcTarget: "omarchy.unifi"
  manageIpc: false

  property Item anchorItem: null
  property var  hostWidget: null
  property var  core: null
  property bool primary: false

  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property string host: setting("host", "")
  readonly property bool configured: host.length > 0

  function rate(bps) {
    var n = Number(bps) || 0
    if (n <= 0) return "—"
    var units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s"]
    var i = 0
    while (n >= 1000 && i < units.length - 1) { n /= 1000; i++ }
    return (n < 10 ? n.toFixed(1) : Math.round(n)) + " " + units[i]
  }

  function uptime(seconds) {
    var s = Number(seconds) || 0
    if (s <= 0) return "—"
    var d = Math.floor(s / 86400)
    var h = Math.floor((s % 86400) / 3600)
    if (d > 0) return d + "d " + h + "h"
    var m = Math.floor((s % 3600) / 60)
    return h > 0 ? h + "h " + m + "m" : m + "m"
  }

  function percent(value) {
    return (value === undefined || value === null) ? "—" : Math.round(value) + "%"
  }

  IpcHandler {
    enabled: root.primary
    target: "omarchy.unifi"
    function toggle(): void { root.toggle() }
    function open(): void { root.open() }
    function close(): void { root.close() }
    function refresh(): void { if (root.core) root.core.refresh() }
  }

  KeyboardPanel {
    id: panel

    anchorItem: root.anchorItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: column
        anchors { left: parent.left; right: parent.right; top: parent.top }
        spacing: Style.space(10)

        PanelHero {
          width: parent.width
          title: "UniFi"
          meta: root.core && root.core.siteInfo
                ? root.core.siteInfo.name.toUpperCase()
                : (root.configured ? "CONNECTING…" : "NOT CONFIGURED")
          foreground: root.barForeground
          fontFamily: root.fontFamily
        }

        // ---------------- setup ----------------
        Loader {
          width: parent.width
          active: !root.configured || !!(root.core && root.core.authError.length > 0)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(6)

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            Text {
              width: column.width
              wrapMode: Text.WordWrap
              color: root.barForeground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              text: root.core && root.core.authError.length > 0
                    ? root.core.authError
                    : "Two things to set. In the UniFi console, Settings → Control " +
                      "Plane → Integrations → Create API Key. Then:"
            }

            Text {
              width: column.width
              wrapMode: Text.WrapAnywhere
              color: Color.accent
              font.family: root.fontFamily
              font.pixelSize: Math.max(9, Style.font.caption - 1)
              text: "install -m600 /dev/null " +
                    (root.core && root.core.defaultKeyFile.length > 0
                     ? root.core.defaultKeyFile : "~/.config/omarchy/unifi.key") +
                    "\nprintf %s 'YOUR_KEY' > " +
                    (root.core && root.core.defaultKeyFile.length > 0
                     ? root.core.defaultKeyFile : "~/.config/omarchy/unifi.key")
            }

            Text {
              width: column.width
              wrapMode: Text.WordWrap
              color: root.barForeground
              opacity: 0.7
              font.family: root.fontFamily
              font.pixelSize: Math.max(9, Style.font.caption - 1)
              text: "Then set the console address in this widget's settings in " +
                    "~/.config/omarchy/shell.json. The key is kept out of that " +
                    "file on purpose — dotfiles end up in public repositories."
            }
          }
        }

        // ---------------- errors ----------------
        Text {
          width: parent.width
          visible: !!(root.core && root.core.lastError.length > 0)
          text: root.core ? root.core.lastError : ""
          color: bar ? bar.urgent : root.barForeground
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // ---------------- the network ----------------
        Loader {
          width: parent.width
          active: !!(root.core && root.core.siteInfo)
          visible: active
          sourceComponent: Column {
            spacing: Style.space(8)

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            Row {
              width: column.width
              spacing: Style.space(14)

              Repeater {
                model: [
                  { k: "DEVICES", v: root.core.devicesOnline + " / " + root.core.deviceCount },
                  { k: "CLIENTS", v: String(root.core.clientCount) },
                  { k: "WIRELESS", v: String(root.core.wireless) },
                  { k: "WIRED", v: String(root.core.wired) }
                ]
                Column {
                  spacing: 1
                  Text {
                    text: modelData.k
                    color: root.barForeground
                    opacity: 0.55
                    font.family: root.fontFamily
                    font.pixelSize: Math.max(8, Style.font.caption - 3)
                  }
                  Text {
                    text: modelData.v
                    color: root.barForeground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }
            }

            // ---- gateway ----
            Column {
              width: column.width
              spacing: Style.space(3)
              visible: !!root.core.gateway

              PanelSectionHeader {
                text: "GATEWAY"
                foreground: root.barForeground
                fontFamily: root.fontFamily
              }

              Text {
                text: root.core.gateway
                      ? (root.core.gateway.name || root.core.gateway.model || "") : ""
                color: root.barForeground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Text {
                width: parent.width
                wrapMode: Text.WordWrap
                color: root.barForeground
                opacity: 0.7
                font.family: root.fontFamily
                font.pixelSize: Math.max(9, Style.font.caption - 2)
                text: "↓ " + root.rate(root.core.uplink.rxRate) +
                      "   ↑ " + root.rate(root.core.uplink.txRate) +
                      "   cpu " + root.percent(root.core.uplink.cpu) +
                      "   mem " + root.percent(root.core.uplink.memory) +
                      "   up " + root.uptime(root.core.uplink.uptime)
              }
            }

            PanelSeparator { width: parent.width; foreground: root.barForeground }

            PanelSectionHeader {
              text: "DEVICES"
              foreground: root.barForeground
              fontFamily: root.fontFamily
            }

            Repeater {
              model: root.core.devices

              Item {
                width: column.width
                height: Math.round(Style.space(24))

                Row {
                  anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                  spacing: Style.space(8)

                  Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 6; height: 6; radius: 3
                    color: modelData.online ? "#5fd18a"
                                            : (bar ? bar.urgent : "#e05252")
                  }

                  Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.name
                    color: root.barForeground
                    opacity: modelData.online ? 1.0 : 0.6
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Text {
                  anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                  text: modelData.ip || modelData.model
                  color: root.barForeground
                  opacity: 0.5
                  font.family: root.fontFamily
                  font.pixelSize: Math.max(9, Style.font.caption - 2)
                }
              }
            }
          }
        }

        PanelSeparator { width: parent.width; foreground: root.barForeground }

        Item {
          width: parent.width
          height: refreshButton.implicitHeight

          Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - refreshButton.width - Style.space(8)
            elide: Text.ElideRight
            color: root.barForeground
            opacity: 0.55
            font.family: root.fontFamily
            font.pixelSize: Math.max(9, Style.font.caption - 2)
            text: !root.core ? ""
                  : (root.core.pinned
                     ? "Certificate pinned — read-only"
                     : "Certificate not yet pinned — read-only")
          }

          PanelActionButton {
            id: refreshButton
            anchors.right: parent.right
            iconText: ""
            tooltipText: "Ask the console again"
            foreground: root.barForeground
            fontFamily: root.fontFamily
            onClicked: if (root.core) root.core.refresh()
          }
        }
      }
    }
  }
}
