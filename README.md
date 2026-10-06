# Herdr Ready

A dot in the Omarchy bar with the number of [herdr](https://herdr.dev) agents waiting for
you, across every herdr session on this computer and on your SSH hosts. Click the dot, or
press **Super + H**, and a small list opens, grouped by herdr session. Pick an agent and you
land on it: the terminal window showing that session comes to the front (switching desktop
workspace if needed) and herdr focuses the agent's pane.

herdr itself is not changed: no herdr plugin, no herdr settings, no saved machines. The
plugin only reads herdr's state, and asks herdr to focus an agent when you pick one. It never
shows a desktop notification.

## What you see

- **A faint dot, no number**: nothing is waiting.
- **Green dot and a number**: that many agents have finished and you haven't looked at them.
- **Red dot**: at least one of them is asking you a question or waiting for approval.
- **A small red mark beside the dot**: a remote host can't be reached. Hover for which one.

The list shows each session as a thin label (`tinyhost`, or `default · server` for a session
on a remote host), with that session's waiting agents under it, questions first, then the one
that has waited longest. On the right of each label: the desktop workspace where a window
shows that session, or "no window".

Keys in the list: **j / k** or the arrows move, **Enter** or a click goes to the agent,
**r** refreshes, **Esc** closes. Right-clicking the dot goes straight to the top agent.

## When does an agent count as waiting?

herdr's own "done" state isn't enough. herdr marks an agent seen as soon as *any* herdr
window shows its tab, even a window on a desktop workspace you aren't looking at. So Herdr
Ready keeps its own record:

- An agent **starts waiting** when it stops working: it finishes, or asks a question.
- It **stops waiting** when it has been in front of you for one second: its tab is showing in
  the herdr window that has keyboard focus on your desktop. Also when you pick it from the
  list, when it starts working again, or when its pane closes.
- An agent **asking a question** stays on the list until it's answered. It's hidden only
  while it's in front of you.
- When the plugin starts (login, shell restart), agents herdr reports as asking or finished
  and unseen count, plus any it was already counting before the restart
  (`~/.local/state/herdr-ready/waiting.json`).

## Install

```bash
git clone https://github.com/drewdunne/omarchy-herdr-ready.git ~/.config/omarchy/plugins/gg.arkship.herdr-ready
~/.config/omarchy/plugins/gg.arkship.herdr-ready/setup install --remote drewdunne@server
```

`setup install` adds the dot after the workspace numbers, loads the hotkey from
`~/.config/hypr/hyprland.lua` (a marked block; the file is backed up first), and sets which
remote hosts to watch. Leave out `--remote` to watch only this computer. Remote hosts need
`ssh <host>` to work without a password prompt, and `python3` there. Nothing is installed on
them: the small program that reads their sessions is sent with the SSH command each time it
connects.

Other commands:

```bash
setup hotkey "SUPER + J"     # use another key (refuses one that's already taken)
setup status                 # what's installed, and the list as the helper sees it
omarchy bar set gg.arkship.herdr-ready remotes "drewdunne@server other@box"
```

## Remove

```bash
~/.config/omarchy/plugins/gg.arkship.herdr-ready/setup uninstall
```

One step: it takes the hotkey out of `hyprland.lua` (backing it up first), deletes the
plugin's settings and state, and removes the plugin from the bar and from disk.

## How it works

```
 the dot and list (HerdrReady.qml, in the Omarchy shell)
        │ runs, reads one JSON line per change; sends "go <agent>"
        ▼
 bin/herdr-ready watch ──── Hyprland: which window is in front, which window shows which
        │                   session (from each terminal's herdr command line)
        ├── relay on this computer ──────────────► every herdr session socket here
        └── relay on each remote host, over SSH ─► every herdr session socket there
```

- **The relay** (`bin/herdr_ready_relay.py`, Python standard library only) finds every
  session's socket under `~/.config/herdr/` (checked every 5 seconds for sessions that start or
  stop), subscribes to herdr's events, and re-reads a session whenever one arrives (and once a
  minute regardless). herdr reports agent state changes one pane at a time, so it subscribes to
  each agent pane.
- **Finding the window**: for each window on the desktop, the helper looks for a herdr client
  among the programs running in it and reads which session it's attached to: `herdr`,
  `herdr --session NAME`, `herdr session attach NAME`, or `herdr --remote TARGET [--session
  NAME]`. Remote names are compared after SSH resolves them, so `server` and `drewdunne@server`
  match.
- **Going to an agent**: if a window shows that session, Hyprland focuses it; the terminal
  tells herdr it has focus, and herdr's "focus agent" then moves *that* window to the agent. If
  no window shows the session, the helper focuses the agent first (no window is attached, so
  nothing else moves) and opens a terminal attached to the session, which starts on it.

`bin/herdr-ready list`, `windows` and `plan local tinyhost` print what the helper sees, for
checking things by hand.

## Limits

- Windows are matched by their own process, so terminals that run every window from one
  process (`foot --server`, Ghostty) can't be told apart. Plain `foot`, Omarchy's default, works.
- herdr run inside a plain `ssh` terminal (rather than `herdr --remote`) is watched, but the
  plugin can't tell that window is showing it: picking one of its agents opens a new
  `herdr --remote` window.
- If you walk away with a herdr window focused, an agent that finishes in the tab it's showing
  counts as seen after a second.

## Tests

```bash
test/run
```

Unit tests for the waiting rules and command lines, a round trip of the `hyprland.lua` block on
a copy, `omarchy plugin validate`, and (when herdr is installed) an end-to-end test that starts a
throwaway herdr session named `zz-hr-test-<pid>`, fakes agents in it, and deletes it afterwards.
