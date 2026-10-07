#!/usr/bin/env python3
"""herdr-dot relay: follows every herdr session on one machine.

Runs on the machine whose sessions it reads: directly on this computer, and on a
remote host through `ssh <host> python3 -c ...` (the watcher sends this file's
source with the command, so nothing is installed there). Standard library only.

stdout, one JSON object per line:
  {"type":"hello","host":"<hostname>"}
  {"type":"session","session":"<name>","focus":{"pane":..,"tab":..},"agents":[...]}
  {"type":"gone","session":"<name>"}                 the session stopped
  {"type":"result","id":"<n>","ok":true|false,"error":"..."}
stdin, one JSON object per line:
  {"op":"focus","session":"<name>","pane":"<pane id>","id":"<n>"}
  {"op":"refresh"}
End of stdin ends the relay, so it never outlives the watcher or its SSH link.

A session is re-read whenever herdr reports an event for it, and once a minute
regardless. herdr only reports agent state changes per pane, so each session's
subscription names every agent pane, plus the events that change that set.
"""

import json
import os
import select
import socket
import sys
import threading
import time

CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "herdr")
RESCAN_SECONDS = 5.0
RESYNC_SECONDS = 60.0
DEBOUNCE_SECONDS = 0.15
GLOBAL_EVENTS = [
    "pane.created", "pane.closed", "pane.exited", "pane.focused", "pane.moved",
    "pane.agent_detected", "tab.focused", "tab.closed", "tab.moved",
    "workspace.focused", "workspace.closed", "workspace.moved",
]

_out_lock = threading.Lock()


def emit(message):
    line = json.dumps(message, separators=(",", ":"))
    with _out_lock:
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, ValueError):
            os._exit(0)


class HerdrError(Exception):
    pass


def session_sockets():
    """{session name: socket path} for every session socket on this machine."""
    found = {}
    default = os.path.join(CONFIG, "herdr.sock")
    if _is_socket(default):
        found["default"] = default
    sessions = os.path.join(CONFIG, "sessions")
    try:
        names = sorted(os.listdir(sessions))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(sessions, name, "herdr.sock")
        if _is_socket(path):
            found[name] = path
    return found


def _is_socket(path):
    try:
        import stat
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except OSError:
        return False


def request(path, method, params=None, timeout=5.0):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(path)
        sock.sendall((json.dumps({"id": "r", "method": method, "params": params or {}}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    finally:
        sock.close()
    reply = json.loads(buf.split(b"\n", 1)[0].decode("utf-8", "replace"))
    if "error" in reply:
        error = reply["error"] or {}
        raise HerdrError("%s: %s" % (error.get("code", "error"), error.get("message", "")))
    return reply.get("result") or {}


def read_session(path):
    """The session's agents and which pane and tab are focused."""
    panes = request(path, "pane.list").get("panes") or []
    names = {}
    try:
        for agent in request(path, "agent.list").get("agents") or []:
            if agent.get("name"):
                names[agent.get("pane_id")] = agent["name"]
    except (OSError, ValueError, HerdrError):
        pass
    focus = {"pane": None, "tab": None, "workspace": None}
    agents = []
    for pane in panes:
        if pane.get("focused"):
            focus = {"pane": pane.get("pane_id"), "tab": pane.get("tab_id"), "workspace": pane.get("workspace_id")}
        if not pane.get("agent"):
            continue
        agents.append({
            "pane": pane.get("pane_id"),
            "tab": pane.get("tab_id"),
            "workspace": pane.get("workspace_id"),
            "agent": pane.get("agent"),
            "name": names.get(pane.get("pane_id")),
            "status": pane.get("agent_status") or "unknown",
            "title": pane.get("terminal_title_stripped") or pane.get("terminal_title") or "",
            "terminal": pane.get("terminal_id"),
        })
    return focus, agents


class Session(threading.Thread):
    def __init__(self, name, path):
        threading.Thread.__init__(self, daemon=True)
        self.name = name
        self.path = path
        self.stopped = threading.Event()
        self.dirty = threading.Event()
        self.last = None
        self.alive = True

    def stop(self):
        self.stopped.set()

    def snapshot(self):
        focus, agents = read_session(self.path)
        message = {"type": "session", "session": self.name, "focus": focus, "agents": agents}
        if message != self.last:
            self.last = message
            emit(message)
        return [a["pane"] for a in agents]

    def subscribe(self, panes):
        subs = [{"type": t} for t in GLOBAL_EVENTS]
        subs += [{"type": "pane.agent_status_changed", "pane_id": p} for p in panes]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect(self.path)
        sock.sendall((json.dumps({"id": "s", "method": "events.subscribe",
                                  "params": {"subscriptions": subs}}) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(1 << 16)
            if not chunk:
                raise HerdrError("subscription closed")
            buf += chunk
        first, rest = buf.split(b"\n", 1)
        reply = json.loads(first.decode("utf-8", "replace"))
        if "error" in reply:
            sock.close()
            raise HerdrError((reply["error"] or {}).get("message", "subscribe failed"))
        sock.setblocking(False)
        return sock, rest

    def run(self):
        backoff = 1.0
        while not self.stopped.is_set():
            sock = None
            try:
                panes = [a["pane"] for a in read_session(self.path)[1]]
                sock, buf = self.subscribe(panes)
                current = self.snapshot()
                backoff = 1.0
                if not self.alive:
                    self.alive = True
                next_resync = time.time() + RESYNC_SECONDS
                while not self.stopped.is_set():
                    if sorted(current) != sorted(panes):
                        break  # the set of agent panes changed: subscribe again
                    timeout = DEBOUNCE_SECONDS if (buf or self.dirty.is_set()) else 1.0
                    readable, _, _ = select.select([sock], [], [], timeout)
                    if readable:
                        chunk = sock.recv(1 << 16)
                        if not chunk:
                            raise HerdrError("subscription closed")
                        buf += chunk
                        if b"\n" in buf:
                            buf = buf.rsplit(b"\n", 1)[1]
                            self.dirty.set()
                        continue
                    if self.dirty.is_set() or time.time() >= next_resync:
                        self.dirty.clear()
                        next_resync = time.time() + RESYNC_SECONDS
                        current = self.snapshot()
            except (OSError, ValueError, HerdrError) as error:
                if isinstance(error, (ConnectionRefusedError, FileNotFoundError)):
                    # Socket left behind by a session that is no longer running.
                    if self.alive:
                        self.alive = False
                        self.last = None
                        emit({"type": "gone", "session": self.name})
                    self.stopped.wait(RESCAN_SECONDS)
                    continue
                self.stopped.wait(backoff)
                backoff = min(backoff * 2, 30.0)
            finally:
                if sock is not None:
                    sock.close()


def focus(sessions, command):
    session = sessions.get(command.get("session"))
    reply = {"type": "result", "id": command.get("id"), "ok": False}
    if session is None:
        reply["error"] = "no such session"
        emit(reply)
        return
    pane = command.get("pane")
    try:
        try:
            request(session.path, "agent.focus", {"target": pane})
        except HerdrError:
            request(session.path, "pane.focus", {"pane_id": pane})
        reply["ok"] = True
    except (OSError, ValueError, HerdrError) as error:
        reply["error"] = str(error)
    emit(reply)
    session.dirty.set()


def scanner(sessions, lock, stop):
    while not stop.is_set():
        found = session_sockets()
        with lock:
            for name, path in found.items():
                if name not in sessions:
                    sessions[name] = Session(name, path)
                    sessions[name].start()
            for name in list(sessions):
                if name not in found:
                    sessions.pop(name).stop()
                    emit({"type": "gone", "session": name})
        stop.wait(RESCAN_SECONDS)


def main():
    emit({"type": "hello", "host": socket.gethostname()})
    sessions = {}
    lock = threading.Lock()
    stop = threading.Event()
    threading.Thread(target=scanner, args=(sessions, lock, stop), daemon=True).start()
    for line in sys.stdin:
        try:
            command = json.loads(line)
        except ValueError:
            continue
        op = command.get("op")
        if op == "focus":
            with lock:
                snapshot = dict(sessions)
            threading.Thread(target=focus, args=(snapshot, command), daemon=True).start()
        elif op == "refresh":
            with lock:
                for session in sessions.values():
                    session.dirty.set()
    stop.set()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
