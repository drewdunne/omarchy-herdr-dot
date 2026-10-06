"""Unit tests for bin/herdr-ready: command lines, and when an agent counts as waiting."""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="herdr-ready-test-")
_loader = importlib.machinery.SourceFileLoader("herdr_ready", os.path.join(HERE, "..", "bin", "herdr-ready"))
_spec = importlib.util.spec_from_loader("herdr_ready", _loader)
hr = importlib.util.module_from_spec(_spec)
_loader.exec_module(hr)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def agent(pane, status, tab="w1:t1", name=None, title="task"):
    return {"pane": pane, "tab": tab, "workspace": tab.split(":")[0], "agent": "claude",
            "name": name, "status": status, "title": title, "terminal": "t-" + pane}


class ParseClient(unittest.TestCase):
    def test_default_session(self):
        self.assertEqual(hr.parse_client([]), (None, "default"))

    def test_named_session(self):
        self.assertEqual(hr.parse_client(["--session", "tinyhost"]), (None, "tinyhost"))
        self.assertEqual(hr.parse_client(["--session=tinyhost"]), (None, "tinyhost"))
        self.assertEqual(hr.parse_client(["session", "attach", "tinyhost"]), (None, "tinyhost"))

    def test_environment_session(self):
        self.assertEqual(hr.parse_client([], "work"), (None, "work"))
        self.assertEqual(hr.parse_client(["--session", "x"], "work"), (None, "x"))

    def test_remote(self):
        self.assertEqual(hr.parse_client(["--remote", "drewdunne@server", "--session", "tinyhost"]),
                         ("drewdunne@server", "tinyhost"))
        self.assertEqual(hr.parse_client(["--remote", "server"]), ("server", "default"))
        self.assertEqual(hr.parse_client(["--remote", "server", "--remote-keybindings", "server"]),
                         ("server", "default"))

    def test_not_a_client(self):
        for args in (["server"], ["client"], ["--session", "x", "server"], ["agent", "list"], ["api", "snapshot"]):
            self.assertIsNone(hr.parse_client(args), args)

    def test_short_label(self):
        self.assertEqual(hr.short_label("drewdunne@server"), "server")
        self.assertEqual(hr.short_label("me@box.example.ts.net"), "box")
        self.assertEqual(hr.short_label("box:2222"), "box")


class Waiting(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.real_time = hr.time.time
        hr.time.time = self.clock
        self.w = hr.Watcher([])  # no remotes, and not following shell.json
        self.w.restored = {}
        self.w.hosts[hr.LOCAL].ok = True

    def tearDown(self):
        hr.time.time = self.real_time

    def session(self, name, agents, focus_tab=None):
        self.w.on_relay(hr.LOCAL, {"type": "session", "session": name, "agents": agents,
                                   "focus": {"pane": None, "tab": focus_tab, "workspace": None}})

    def keys(self):
        return [a["key"] for g in self.w.state()["groups"] for a in g["agents"]]

    def look_at(self, session, seconds=None):
        """The desktop's focused window shows `session` (None: nothing in front)."""
        self.w.windows = {"a1": {"address": "a1", "workspace": 1, "focus_rank": 0,
                                 "clients": [(hr.LOCAL, session)] if session else []}}
        self.w.active = "a1"
        self.w.update_view()
        if seconds:
            self.clock.now += seconds
            self.w.update_view()

    def test_first_read_counts_blocked_and_done_not_idle(self):
        self.session("s", [agent("w1:p1", "blocked"), agent("w1:p2", "done"), agent("w1:p3", "idle"),
                           agent("w1:p4", "working")])
        self.assertEqual(sorted(self.keys()), ["local|s|w1:p1", "local|s|w1:p2"])

    def test_finishing_counts_even_when_herdr_says_idle(self):
        # herdr marks an agent seen (idle, not done) when any window shows its tab,
        # even a window on a desktop workspace you aren't looking at.
        self.session("s", [agent("w1:p1", "working")])
        self.assertEqual(self.keys(), [])
        self.session("s", [agent("w1:p1", "idle")])
        self.assertEqual(self.keys(), ["local|s|w1:p1"])

    def test_done_turning_idle_is_not_a_new_finish(self):
        self.session("s", [agent("w1:p1", "idle")])
        self.session("s", [agent("w1:p1", "done")], focus_tab="w1:t1")  # only a real change starts waiting
        self.assertEqual(self.keys(), ["local|s|w1:p1"])
        self.look_at("s", 2)
        self.assertEqual(self.keys(), [])
        self.session("s", [agent("w1:p1", "idle")])
        self.assertEqual(self.keys(), [])

    def test_seen_after_a_second_in_front_of_you(self):
        self.session("s", [agent("w1:p1", "working")], focus_tab="w1:t1")
        self.session("s", [agent("w1:p1", "idle")], focus_tab="w1:t1")
        self.look_at("s", 0.4)
        self.assertEqual(len(self.keys()), 1, "a glance is not enough")
        self.look_at(None)
        self.look_at("s", 1.2)
        self.assertEqual(self.keys(), [])

    def test_other_tab_is_not_in_front_of_you(self):
        self.session("s", [agent("w1:p1", "working", tab="w1:t2")], focus_tab="w1:t1")
        self.session("s", [agent("w1:p1", "idle", tab="w1:t2")], focus_tab="w1:t1")
        self.look_at("s", 5)
        self.assertEqual(len(self.keys()), 1)

    def test_other_session_is_not_in_front_of_you(self):
        self.session("s", [agent("w1:p1", "working")], focus_tab="w1:t1")
        self.session("s", [agent("w1:p1", "idle")], focus_tab="w1:t1")
        self.session("other", [], focus_tab="w1:t1")
        self.look_at("other", 5)
        self.assertEqual(len(self.keys()), 1)

    def test_question_stays_until_answered_but_hides_while_in_front(self):
        self.session("s", [agent("w1:p1", "working")], focus_tab="w1:t1")
        self.session("s", [agent("w1:p1", "blocked")], focus_tab="w1:t1")
        self.look_at("s", 5)
        self.assertEqual(self.keys(), [], "hidden while you look at it")
        self.look_at(None)
        self.assertEqual(self.keys(), ["local|s|w1:p1"], "back when you look away")
        self.session("s", [agent("w1:p1", "working")], focus_tab="w1:t1")
        self.assertEqual(self.keys(), [])

    def test_working_again_clears(self):
        self.session("s", [agent("w1:p1", "done")])
        self.session("s", [agent("w1:p1", "working")])
        self.assertEqual(self.keys(), [])

    def test_pane_or_session_gone_clears(self):
        self.session("s", [agent("w1:p1", "done"), agent("w1:p2", "done")])
        self.session("s", [agent("w1:p1", "done")])
        self.assertEqual(self.keys(), ["local|s|w1:p1"])
        self.w.on_relay(hr.LOCAL, {"type": "gone", "session": "s"})
        self.assertEqual(self.keys(), [])

    def test_unreachable_host_hides_its_agents_until_back(self):
        self.session("s", [agent("w1:p1", "done")])
        self.w.hosts[hr.LOCAL].ok = False
        self.assertEqual(self.keys(), [])
        self.w.hosts[hr.LOCAL].ok = True
        self.w.on_relay(hr.LOCAL, {"type": "hello", "host": "x"})
        self.session("s", [agent("w1:p1", "idle")])  # seen elsewhere meanwhile? still waiting for you
        self.assertEqual(self.keys(), ["local|s|w1:p1"])

    def test_restored_waiting_survives_a_restart(self):
        self.w.restored = {"local|s|w1:p1": 900.0}
        self.session("s", [agent("w1:p1", "idle"), agent("w1:p2", "idle")])
        self.assertEqual(self.keys(), ["local|s|w1:p1"])
        self.assertEqual(self.w.state()["groups"][0]["agents"][0]["since"], 900)

    def test_order_questions_first_then_longest_waiting(self):
        self.session("a", [agent("w1:p1", "working"), agent("w1:p2", "working")])
        self.session("b", [agent("w1:p1", "working")])
        self.session("a", [agent("w1:p1", "idle"), agent("w1:p2", "working")])
        self.clock.now += 10
        self.session("b", [agent("w1:p1", "idle")])
        self.clock.now += 10
        self.session("a", [agent("w1:p1", "idle"), agent("w1:p2", "blocked")])
        state = self.w.state()
        self.assertEqual([g["session"] for g in state["groups"]], ["a", "b"])
        self.assertEqual([a["pane"] for a in state["groups"][0]["agents"]], ["w1:p2", "w1:p1"])
        self.assertEqual((state["count"], state["blocked"]), (3, 1))

    def test_groups_name_session_and_host(self):
        self.session("tinyhost", [agent("w1:p1", "done")])
        group = self.w.state()["groups"][0]
        self.assertEqual((group["session"], group["hostLabel"]), ("tinyhost", ""))


class Settings(unittest.TestCase):
    def test_remotes_from_shell_json(self):
        path = os.path.join(tempfile.mkdtemp(), "shell.json")
        with open(path, "w") as handle:
            handle.write('{"bar": {"layout": {"left": [{"id": "omarchy.workspaces"},'
                         '{"id": "gg.arkship.herdr-ready", "remotes": "a@one, two  three"}]}}}')
        self.assertEqual(hr.configured_remotes(path), ["a@one", "two", "three"])
        with open(path, "w") as handle:
            handle.write('{"bar": {"layout": {"left": [{"id": "gg.arkship.herdr-ready"}]}}}')
        self.assertEqual(hr.configured_remotes(path), [])
        self.assertIsNone(hr.configured_remotes(path + ".missing"))

    def test_hosts_follow_the_setting(self):
        real = hr.ssh_identity
        hr.ssh_identity = lambda target: "id:" + target.split("@")[-1]
        try:
            w = hr.Watcher(["me@box"])
            self.assertEqual(w.host_order, [hr.LOCAL, "id:box"])
            w.set_remotes(["box", "other"])  # same machine under another name: kept as is
            self.assertEqual(w.host_order, [hr.LOCAL, "id:box", "id:other"])
            w.set_remotes([])
            self.assertEqual(w.host_order, [hr.LOCAL])
        finally:
            hr.ssh_identity = real

    def test_save_keeps_remembered_agents_not_read_yet(self):
        w = hr.Watcher([], persist=True)
        w.restored = {"local|s|w1:p1": 900.0, "gone-host|s|w1:p1": 800.0}
        w.save()
        with open(hr.STATE_FILE) as handle:
            self.assertEqual(json.load(handle)["waiting"], {"local|s|w1:p1": 900.0})


if __name__ == "__main__":
    unittest.main()
