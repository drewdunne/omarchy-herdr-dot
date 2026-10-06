import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Herdr Ready: a dot in the bar with the number of herdr agents waiting for you, across
// every session on this computer and on the remote hosts in settings. Click it (or the
// hotkey, Super + H by default) for the list, grouped by session; Enter or a click goes
// to the agent. bin/herdr-ready does the watching and the going; this file draws.
Panel {
  id: root
  moduleName: "gg.arkship.herdr-ready"
  ipcTarget: "gg.arkship.herdr-ready"
  manageIpc: false

  // ---------------------------------------------------------------- settings
  readonly property string remotes: String(setting("remotes", ""))
  readonly property string helperPath: Qt.resolvedUrl("bin/herdr-ready").toString().replace(/^file:\/\//, "")

  // ---------------------------------------------------------------- state from the helper
  property var snap: ({ count: 0, blocked: 0, groups: [], hosts: [] })
  readonly property int count: snap.count || 0
  readonly property int blockedCount: snap.blocked || 0
  readonly property var groups: snap.groups || []
  readonly property var hosts: snap.hosts || []
  readonly property var downHosts: hosts.filter(function(h) { return !h.ok })
  property double nowMs: Date.now()
  property int cursor: 0

  // Flattened rows for the list: a thin label per session, then its agents.
  readonly property var rows: {
    var out = []
    var index = 0
    for (var g = 0; g < groups.length; g++) {
      var group = groups[g]
      out.push({ kind: "group", group: group })
      for (var a = 0; a < group.agents.length; a++)
        out.push({ kind: "agent", agent: group.agents[a], index: index++ })
    }
    return out
  }
  readonly property var agentKeys: {
    var keys = []
    for (var g = 0; g < groups.length; g++)
      for (var a = 0; a < groups[g].agents.length; a++) keys.push(groups[g].agents[a].key)
    return keys
  }
  onAgentKeysChanged: if (cursor >= agentKeys.length) cursor = Math.max(0, agentKeys.length - 1)

  // ---------------------------------------------------------------- theme
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.rgba(fg.r, fg.g, fg.b, 0.5)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.3)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  property var themeColors: ({})
  readonly property color red: themeColors.bright_red || themeColors.red || Color.urgent
  readonly property color green: themeColors.bright_green || themeColors.green || Color.accent
  readonly property color dotColor: count === 0 ? faint : (blockedCount > 0 ? red : green)

  FileView {
    path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.parsePalette(text())
  }
  function parsePalette(content) {
    var out = {}
    var lines = String(content || "").split("\n")
    for (var i = 0; i < lines.length; i++) {
      var match = lines[i].match(/^\s*([a-z_]+)\s*=\s*"(#[0-9a-fA-F]{6})"/)
      if (match) out[match[1]] = match[2]
    }
    themeColors = out
  }

  // ---------------------------------------------------------------- the helper
  Process {
    id: helper
    // Omarchy can load a bar widget more than once; only the copy in a bar runs the helper.
    running: root.bar !== null
    command: [root.helperPath, "watch"].concat(root.remotes.trim() === "" ? [] : ["--remote", root.remotes])
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(data) {
        try {
          var parsed = JSON.parse(String(data || ""))
          if (parsed && typeof parsed === "object" && parsed.groups) root.snap = parsed
        } catch (e) {
          console.warn("herdr-ready", "bad line from helper", e)
        }
      }
    }
    stderr: SplitParser {
      onRead: function(data) { if (String(data).trim() !== "") console.warn("herdr-ready", String(data).trim()) }
    }
    onExited: function(code, status) {
      if (root.bar !== null) restartTimer.start()
    }
  }
  Timer {
    id: restartTimer
    interval: 5000
    onTriggered: helper.running = root.bar !== null
  }
  onRemotesChanged: if (helper.running) { helper.running = false; restartTimer.start() }

  function send(line) {
    if (helper.running) helper.write(line + "\n")
  }
  function go(key) {
    if (!key) return
    send("go " + key)
    root.close()
  }
  function goFirst() {
    send("first")
    root.close()
  }

  IpcHandler {
    enabled: root.bar !== null
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function first(): void { root.goFirst() }
    function refresh(): void { root.send("refresh") }
    function count(): string { return String(root.count) }
  }

  onOpenedChanged: if (opened) {
    nowMs = Date.now()
    cursor = 0
    send("refresh")
  }
  Timer {
    interval: 30000
    running: root.opened
    repeat: true
    onTriggered: root.nowMs = Date.now()
  }

  function age(since) {
    var seconds = Math.max(0, Math.round(nowMs / 1000 - since))
    if (seconds < 60) return "now"
    if (seconds < 3600) return Math.floor(seconds / 60) + "m"
    if (seconds < 86400) return Math.floor(seconds / 3600) + "h"
    return Math.floor(seconds / 86400) + "d"
  }
  function groupLabel(group) {
    return group.hostLabel ? group.session + " · " + group.hostLabel : group.session
  }
  function groupWhere(group) {
    if (!group.workspaces || group.workspaces.length === 0) return "no window"
    return "workspace " + group.workspaces.map(function(w) { return w === 10 ? 0 : w }).join(", ")
  }
  readonly property string tooltip: {
    var text = count === 0 ? "No herdr agents waiting"
      : count + " waiting" + (blockedCount > 0 ? " · " + blockedCount + " need" + (blockedCount === 1 ? "s" : "") + " you" : "")
    for (var i = 0; i < downHosts.length; i++) text += "\n" + downHosts[i].label + ": can't connect"
    return text
  }

  // ---------------------------------------------------------------- bar
  implicitWidth: barItem.implicitWidth
  implicitHeight: bar ? bar.barSize : Style.bar.sizeHorizontal

  Item {
    id: barItem
    anchors.centerIn: parent
    implicitWidth: barRow.implicitWidth + Style.space(12)
    height: parent.height

    Row {
      id: barRow
      anchors.centerIn: parent
      spacing: Style.space(5)

      Rectangle {
        id: dot
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(8)
        height: width
        radius: width / 2
        color: root.dotColor
        Behavior on color { ColorAnimation { duration: 200 } }
      }
      Rectangle {
        visible: root.downHosts.length > 0
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(4)
        height: width
        radius: width / 2
        color: root.red
      }
      Text {
        visible: root.count > 0
        anchors.verticalCenter: parent.verticalCenter
        text: String(root.count)
        color: root.bar ? root.bar.barForeground : root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      acceptedButtons: Qt.LeftButton | Qt.RightButton
      onClicked: function(mouse) {
        if (mouse.button === Qt.RightButton) root.goFirst()
        else root.toggle()
      }
      onEntered: if (root.bar) root.bar.showTooltip(barItem, root.tooltip)
      onExited: if (root.bar) root.bar.hideTooltip(barItem)
    }
  }

  // ---------------------------------------------------------------- the list
  KeyboardPanel {
    id: panel
    anchorItem: barItem
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(listColumn.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (dy !== 0 && root.agentKeys.length > 0)
          root.cursor = Math.max(0, Math.min(root.agentKeys.length - 1, root.cursor + dy))
      }
      onActivateRequested: root.go(root.agentKeys[root.cursor])
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) { if (t === "r") root.send("refresh") }

      Flickable {
        anchors.fill: parent
        contentWidth: width
        contentHeight: listColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: listColumn
          width: parent.width
          spacing: Style.space(2)

          Item {
            width: parent.width
            height: header.implicitHeight + Style.space(6)
            Text {
              id: header
              text: "Waiting for you"
              color: root.fg
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
            }
            Text {
              anchors.right: parent.right
              anchors.baseline: header.baseline
              text: root.count === 0 ? "" : (root.blockedCount > 0 ? root.blockedCount + " need you · " : "")
                + (root.count - root.blockedCount) + " finished"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Repeater {
            model: root.downHosts
            Text {
              required property var modelData
              width: listColumn.width
              text: modelData.label + ": can't connect" + (modelData.error ? " (" + modelData.error + ")" : "")
              color: root.red
              wrapMode: Text.Wrap
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          Text {
            visible: root.count === 0
            topPadding: Style.space(6)
            bottomPadding: Style.space(6)
            text: "Nothing is waiting."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }

          Repeater {
            model: root.rows

            Item {
              id: rowItem
              required property var modelData
              readonly property bool isGroup: modelData.kind === "group"
              readonly property bool selected: !isGroup && modelData.index === root.cursor
              width: listColumn.width
              height: isGroup ? groupText.implicitHeight + Style.space(10) : Style.space(26)

              // Thin label: the herdr session (and host for a remote one), not the workspace.
              Text {
                id: groupText
                visible: rowItem.isGroup
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Style.space(2)
                text: rowItem.isGroup ? root.groupLabel(rowItem.modelData.group) : ""
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.letterSpacing: 0.5
              }
              Text {
                visible: rowItem.isGroup
                anchors.right: parent.right
                anchors.baseline: groupText.baseline
                text: rowItem.isGroup ? root.groupWhere(rowItem.modelData.group) : ""
                color: root.faint
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Rectangle {
                visible: !rowItem.isGroup
                anchors.fill: parent
                radius: Style.cornerRadius
                color: rowItem.selected ? Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.10) : "transparent"

                Rectangle {
                  id: stateDot
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(7)
                  height: width
                  radius: width / 2
                  color: !rowItem.isGroup && rowItem.modelData.agent.status === "blocked" ? root.red : root.green
                }
                Text {
                  id: ageText
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  text: rowItem.isGroup ? "" : root.age(rowItem.modelData.agent.since)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Text {
                  id: kindText
                  anchors.right: ageText.left
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  text: rowItem.isGroup ? "" : (rowItem.modelData.agent.status === "blocked" ? "needs you" : rowItem.modelData.agent.agent)
                  color: !rowItem.isGroup && rowItem.modelData.agent.status === "blocked" ? root.red : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Text {
                  anchors.left: stateDot.right
                  anchors.leftMargin: Style.space(8)
                  anchors.right: kindText.left
                  anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  text: rowItem.isGroup ? "" : (rowItem.modelData.agent.name || rowItem.modelData.agent.title || rowItem.modelData.agent.pane)
                  elide: Text.ElideRight
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
              }

              MouseArea {
                visible: !rowItem.isGroup
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onEntered: root.cursor = rowItem.modelData.index
                onClicked: root.go(rowItem.modelData.agent.key)
              }
            }
          }

          Text {
            width: listColumn.width
            topPadding: Style.space(8)
            text: root.count > 0 ? "Enter or click: go to it · j k move · Esc close" : "Esc close"
            color: root.faint
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }
}
