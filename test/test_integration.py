"""End to end against a real herdr: a throwaway session (zz-hr-test-<pid>) is started
headless, agents are faked in it with herdr's own pane.report_agent, and the relay and
`herdr-ready list` must report them. The session is stopped and deleted afterwards.
Skipped when herdr isn't installed. Reads, but never changes, any other session."""

import json
import os
import shutil
import socket
import subprocess
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "bin", "herdr-ready")
RELAY = os.path.join(HERE, "..", "bin", "herdr_ready_relay.py")
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "herdr")
NAME = "zz-hr-test-%d" % os.getpid()
SOCK = os.path.join(CONFIG, "sessions", NAME, "herdr.sock")
ENV = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")}


def call(method, params=None):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(5)
    sock.connect(SOCK)
    sock.sendall((json.dumps({"id": "t", "method": method, "params": params or {}}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        buf += sock.recv(65536)
    sock.close()
    reply = json.loads(buf)
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply["result"]


def report(pane, state):
    call("pane.report_agent", {"pane_id": pane, "source": "herdr-ready-test", "agent": "claude", "state": state})


def statuses():
    return {a["pane_id"]: a["agent_status"] for a in call("agent.list")["agents"]}


def listing():
    out = subprocess.run([HELPER, "list", "--json", "--wait", "6"], capture_output=True, text=True,
                         timeout=30, env=ENV).stdout
    state = json.loads(out)
    for group in state["groups"]:
        if group["session"] == NAME and group["hostLabel"] == "":
            return {a["pane"]: a["status"] for a in group["agents"]}
    return {}


@unittest.skipUnless(shutil.which("herdr"), "herdr is not installed")
class AgainstHerdr(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = subprocess.Popen(["herdr", "--session", NAME, "server"], env=ENV,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True)
        for _ in range(50):
            if os.path.exists(SOCK):
                break
            time.sleep(0.1)
        cls.shown = call("workspace.create", {"label": "shown", "focus": True})["root_pane"]["pane_id"]
        cls.hidden = call("workspace.create", {"label": "hidden", "focus": False})["root_pane"]["pane_id"]

    @classmethod
    def tearDownClass(cls):
        try:
            call("server.stop")
        except (OSError, RuntimeError, ValueError):
            pass
        try:
            cls.server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.server.kill()
        subprocess.run(["herdr", "session", "delete", NAME], env=ENV, capture_output=True, timeout=10)
        shutil.rmtree(os.path.join(CONFIG, "sessions", NAME), ignore_errors=True)

    def test_1_finished_agents_count_even_where_herdr_says_seen(self):
        # One agent finishes in the workspace herdr is showing (herdr: idle), one in a
        # hidden workspace (herdr: done). Both are waiting for you; nobody looked.
        report(self.shown, "working")
        report(self.hidden, "working")
        before = listing()
        self.assertEqual(before, {})
        report(self.shown, "idle")
        report(self.hidden, "idle")
        self.assertEqual(statuses(), {self.shown: "idle", self.hidden: "done"})

    def test_2_relay_reports_and_focuses(self):
        relay = subprocess.Popen(["python3", "-u", RELAY], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True, env=ENV)
        try:
            seen = None
            deadline = time.time() + 10
            while time.time() < deadline:
                message = json.loads(relay.stdout.readline())
                if message.get("type") == "session" and message["session"] == NAME:
                    seen = {a["pane"]: a["status"] for a in message["agents"]}
                    break
            self.assertEqual(seen, {self.shown: "idle", self.hidden: "done"})

            report(self.shown, "blocked")
            deadline = time.time() + 5
            while time.time() < deadline:
                message = json.loads(relay.stdout.readline())
                if message.get("type") == "session" and message["session"] == NAME:
                    if {a["pane"]: a["status"] for a in message["agents"]}.get(self.shown) == "blocked":
                        break
            else:
                self.fail("relay did not report the question")

            relay.stdin.write(json.dumps({"op": "focus", "session": NAME, "pane": self.hidden, "id": "1"}) + "\n")
            relay.stdin.flush()
            deadline = time.time() + 5
            while time.time() < deadline:
                message = json.loads(relay.stdout.readline())
                if message.get("type") == "result" and message.get("id") == "1":
                    self.assertTrue(message["ok"], message)
                    break
            self.assertEqual(statuses()[self.hidden], "idle", "focusing marks it seen in herdr")
        finally:
            relay.stdin.close()
            relay.wait(timeout=5)

    def test_3_question_listed(self):
        report(self.shown, "working")
        report(self.shown, "blocked")
        self.assertEqual(listing().get(self.shown), "blocked")

    def test_4_watch_counts_a_finish_herdr_calls_seen(self):
        call("pane.focus", {"pane_id": self.shown})  # herdr shows this agent's workspace again
        report(self.shown, "working")
        watch = subprocess.Popen([HELPER, "watch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 text=True, env=ENV)
        try:
            def mine():
                line = watch.stdout.readline()
                for group in json.loads(line)["groups"]:
                    if group["session"] == NAME and group["hostLabel"] == "":
                        return {a["pane"]: a["status"] for a in group["agents"]}
                return {}
            deadline = time.time() + 10
            current = None
            while time.time() < deadline and self.hidden not in (current or {}):
                current = mine()  # the hidden agent is done from earlier tests: listed at once
            report(self.shown, "idle")
            self.assertEqual(statuses()[self.shown], "idle", "herdr calls it seen")
            deadline = time.time() + 10
            while time.time() < deadline and current.get(self.shown) != "finished":
                current = mine()
            self.assertEqual(current.get(self.shown), "finished")
        finally:
            watch.stdin.close()
            watch.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
