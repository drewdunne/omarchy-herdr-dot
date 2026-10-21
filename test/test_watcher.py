"""Unit tests for bin/herdr-dot: command lines, and when an agent counts as waiting."""

import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp(prefix="herdr-dot-test-")
_loader = importlib.machinery.SourceFileLoader("herdr_dot", os.path.join(HERE, "..", "bin", "herdr-dot"))
_spec = importlib.util.spec_from_loader("herdr_dot", _loader)
hr = importlib.util.module_from_spec(_spec)
_loader.exec_module(hr)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def agent(pane, status, tab="w1:t1", name=None, title="task", watched_by=None, role=None):
    return {"pane": pane, "tab": tab, "workspace": tab.split(":")[0], "agent": "claude",
            "name": name, "status": status, "title": title, "terminal": "t-" + pane,
            "watched_by": watched_by, "role": role}


class ParseClient(unittest.TestCase):
    def test_default_session(self):
        self.assertEqual(hr.parse_client([]), (None, "default"))

    def test_named_session(self):
        self.assertEqual(hr.parse_client(["--session", "myproject"]), (None, "myproject"))
        self.assertEqual(hr.parse_client(["--session=myproject"]), (None, "myproject"))
        self.assertEqual(hr.parse_client(["session", "attach", "myproject"]), (None, "myproject"))

    def test_environment_session(self):
        self.assertEqual(hr.parse_client([], "work"), (None, "work"))
        self.assertEqual(hr.parse_client(["--session", "x"], "work"), (None, "x"))

    def test_remote(self):
        self.assertEqual(hr.parse_client(["--remote", "me@server", "--session", "myproject"]),
                         ("me@server", "myproject"))
        self.assertEqual(hr.parse_client(["--remote", "server"]), ("server", "default"))
        self.assertEqual(hr.parse_client(["--remote", "server", "--remote-keybindings", "server"]),
                         ("server", "default"))

    def test_not_a_client(self):
        for args in (["server"], ["client"], ["--session", "x", "server"], ["agent", "list"], ["api", "snapshot"]):
            self.assertIsNone(hr.parse_client(args), args)

    def test_short_label(self):
        self.assertEqual(hr.short_label("me@server"), "server")
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

    def session(self, name, agents, focus_tab=None, terminals=None, host=hr.LOCAL):
        if terminals is None:
            terminals = [a["terminal"] for a in agents]
        self.w.on_relay(host, {"type": "session", "session": name, "agents": agents, "agent_terminals": terminals,
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

    def test_an_agent_watched_by_another_is_left_to_it_while_the_watcher_is_open(self):
        # An agent another agent watches for you (its pane carries watched_by=<terminal>) isn't
        # shown while a pane with that terminal is open on the same host, in any session. The
        # watcher shows instead when it needs you, and the agent shows again once it's gone.
        self.session("work", [agent("w1:p1", "working", watched_by="t-w9:p1"), agent("w1:p2", "working")])
        self.session("watch", [agent("w9:p1", "working")])
        self.session("work", [agent("w1:p1", "done", watched_by="t-w9:p1"), agent("w1:p2", "done")])
        self.assertEqual(self.keys(), ["local|work|w1:p2"])
        self.session("work", [agent("w1:p1", "blocked", watched_by="t-w9:p1"), agent("w1:p2", "done")])
        self.assertEqual(self.w.state()["blocked"], 0, "its question goes to the watcher, not to you")
        self.session("watch", [agent("w9:p1", "done")])
        self.assertEqual(sorted(self.keys()), ["local|watch|w9:p1", "local|work|w1:p2"])
        self.session("watch", [], terminals=[])  # the watcher's agent quit, or its pane closed
        self.assertEqual(sorted(self.keys()), ["local|work|w1:p1", "local|work|w1:p2"])
        self.assertEqual(self.w.state()["blocked"], 1)

    def test_a_watcher_that_isnt_open_or_is_on_another_host_hides_nothing(self):
        self.w.hosts["far"] = hr.Host("far", "far", "far", self.w.events)
        self.w.hosts["far"].ok = True
        self.session("s", [agent("w1:p1", "done", watched_by="t-gone"), agent("w1:p2", "done", watched_by="t-w9:p1"),
                           agent("w1:p3", "done", watched_by="t-w1:p3")])
        self.session("s", [agent("w9:p1", "working")], host="far")
        self.assertEqual(sorted(self.keys()), ["local|s|w1:p1", "local|s|w1:p2", "local|s|w1:p3"])

    def test_helpers_are_never_listed_or_counted(self):
        # A helper (role=helper: a reviewer or tester another agent started) is left to the agent
        # that started it, finished or asking. Labeled later, it leaves the list as if it closed.
        self.session("s", [agent("w1:p1", "done", role="helper"), agent("w1:p2", "blocked", role="helper"),
                           agent("w1:p3", "done")])
        self.assertEqual(self.keys(), ["local|s|w1:p3"])
        self.assertEqual((self.w.state()["count"], self.w.state()["blocked"]), (1, 0))
        self.session("s", [agent("w1:p1", "working", role="helper"), agent("w1:p2", "blocked", role="helper"),
                           agent("w1:p3", "done", role="helper")])
        self.session("s", [agent("w1:p1", "idle", role="helper"), agent("w1:p2", "blocked", role="helper"),
                           agent("w1:p3", "done", role="helper")])
        self.assertEqual(self.keys(), [])
        self.assertEqual(self.w.waiting, {}, "a helper is never kept, so never saved")
        self.session("s", [agent("w1:p2", "blocked", role="reviewer")])  # another role, or none, shows
        self.assertEqual(self.keys(), ["local|s|w1:p2"])

    def test_scratch_sessions_are_never_listed_or_counted(self):
        # A temporary session (its name starts with zz-: an agent's probe or test) is never listed,
        # counted or saved, even while its agents ask, here or on an SSH host. One seen late (its
        # agents remembered from before a restart) or renamed to zz- drops out as if it closed.
        self.w.hosts["far"] = hr.Host("far", "far", "far", self.w.events)
        self.w.hosts["far"].ok = True
        self.w.restored = {"local|zz-probe|w1:p1": 900.0, "local|s|w1:p1": 900.0}
        self.session("zz-probe", [agent("w1:p1", "idle"), agent("w1:p2", "blocked"), agent("w1:p3", "done")])
        self.session("zz-probe", [agent("w1:p1", "working"), agent("w2:p1", "working")], host="far")
        self.session("zz-probe", [agent("w1:p1", "blocked"), agent("w2:p1", "done")], host="far")
        self.session("s", [agent("w1:p1", "idle")])
        self.assertEqual(self.keys(), ["local|s|w1:p1"])
        self.assertEqual((self.w.state()["count"], self.w.state()["blocked"]), (1, 0))
        self.assertEqual(sorted(self.w.waiting), ["local|s|w1:p1"], "a temporary session's agent is never saved")
        self.assertEqual(self.w.restored, {"local|s|w1:p1": 900.0}, "what it remembered from before is dropped")
        self.assertEqual(list(self.w.sessions), [(hr.LOCAL, "s")], "nor is the session itself kept, on either host")
        self.session("probe", [agent("w1:p1", "blocked")])
        self.assertIn("local|probe|w1:p1", self.keys())
        self.w.on_relay(hr.LOCAL, {"type": "gone", "session": "probe"})  # renamed: the old name goes,
        self.session("zz-probe2", [agent("w1:p1", "blocked")])             # and the new one is never read
        self.assertEqual(self.keys(), ["local|s|w1:p1"])
        self.session("zz", [agent("w1:p1", "done")])  # only a name that starts with zz- is temporary
        self.session("my-zz-probe", [agent("w1:p1", "done")])
        self.assertEqual(sorted(self.keys()), ["local|my-zz-probe|w1:p1", "local|s|w1:p1", "local|zz|w1:p1"])

    def test_scratch_sessions_are_listed_for_the_plugins_own_tests(self):
        # The end-to-end test fakes agents in its own zz-hr-test-<pid> session, which the bar must
        # never show; it reads them with --list-temporary.
        self.w.list_temporary = True
        self.session("zz-hr-test-1", [agent("w1:p1", "blocked")])
        self.assertEqual(self.keys(), ["local|zz-hr-test-1|w1:p1"])

    def test_sessions_that_no_longer_exist_are_forgotten(self):
        # The relay lists every session with a socket; what the state file remembered for any
        # other session of that host is dropped, as is what was counted before a reconnect.
        self.w.restored = {"local|s|w1:p1": 900.0, "local|deleted|w1:p1": 800.0, "far|deleted|w1:p1": 700.0}
        self.w.on_relay(hr.LOCAL, {"type": "sessions", "sessions": ["s", "kept"]})
        self.assertEqual(self.w.restored, {"local|s|w1:p1": 900.0, "far|deleted|w1:p1": 700.0})
        self.session("kept", [agent("w1:p1", "done")])
        self.w.on_relay(hr.LOCAL, {"type": "hello", "host": "x"})  # reconnected; "kept" went meanwhile
        self.w.on_relay(hr.LOCAL, {"type": "sessions", "sessions": ["s"]})
        self.assertEqual(self.w.waiting, {})
        self.assertNotIn((hr.LOCAL, "kept"), self.w.stash)

    def test_a_stopped_session_forgets_what_it_remembered(self):
        # A socket left behind by a session that isn't running reports "gone" without ever being read.
        self.w.restored = {"local|stale|w1:p1": 900.0, "local|s|w1:p1": 900.0}
        self.w.on_relay(hr.LOCAL, {"type": "gone", "session": "stale"})
        self.assertEqual(self.w.restored, {"local|s|w1:p1": 900.0})

    def test_groups_name_session_and_host(self):
        self.session("myproject", [agent("w1:p1", "done")])
        group = self.w.state()["groups"][0]
        self.assertEqual((group["session"], group["hostLabel"]), ("myproject", ""))


class Settings(unittest.TestCase):
    def test_remotes_from_shell_json(self):
        path = os.path.join(tempfile.mkdtemp(), "shell.json")
        with open(path, "w") as handle:
            handle.write('{"bar": {"layout": {"left": [{"id": "omarchy.workspaces"},'
                         '{"id": "gg.arkship.herdr-dot", "remotes": "a@one, two  three"}]}}}')
        self.assertEqual(hr.configured_remotes(path), ["a@one", "two", "three"])
        with open(path, "w") as handle:
            handle.write('{"bar": {"layout": {"left": [{"id": "gg.arkship.herdr-dot"}]}}}')
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

    def test_save_drops_sessions_that_no_longer_exist(self):
        w = hr.Watcher([], persist=True)
        w.restored = {"local|s|w1:p1": 900.0, "local|zz-old|w1:p1": 800.0}
        w.on_relay(hr.LOCAL, {"type": "sessions", "sessions": ["s"]})
        w.save()
        with open(hr.STATE_FILE) as handle:
            self.assertEqual(json.load(handle)["waiting"], {"local|s|w1:p1": 900.0})


class NewWindowWorkspace(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "workspaces.json")
        self.ident = lambda target: "id:" + target.split("@")[-1]

    def write(self, workspaces):
        with open(self.path, "w") as handle:
            json.dump({"version": 1, "workspaces": workspaces}, handle)

    def test_the_sessions_own_workspace(self):
        self.write({"3": {"session": "myproject", "remote": "me@server"},
                    "7": {"remote": "server"}, "1": {"session": "ark"}})
        self.assertEqual(hr.workspace_for("id:server", "myproject", self.ident, {1, 2, 3}, self.path), 3)
        self.assertEqual(hr.workspace_for("id:server", "default", self.ident, set(), self.path), 7)
        self.assertEqual(hr.workspace_for(hr.LOCAL, "ark", self.ident, {1}, self.path), 1)

    def test_first_empty_not_assigned_elsewhere(self):
        self.write({"6": {"session": "other"}, "8": {}})
        # 1-5 in use, 6 belongs to another session, 7 is free; an entry with nothing set is free
        self.assertEqual(hr.workspace_for(hr.LOCAL, "s", self.ident, {1, 2, 3, 4, 5}, self.path), 7)
        self.assertEqual(hr.workspace_for(hr.LOCAL, "s", self.ident, {1, 2, 3, 4, 5, 7}, self.path), 8)

    def test_without_settings_first_empty(self):
        missing = self.path + ".missing"
        self.assertEqual(hr.workspace_for(hr.LOCAL, "s", self.ident, {1, 2, 3, 4, 5, 10}, missing), 6)
        self.assertIsNone(hr.workspace_for(hr.LOCAL, "s", self.ident, set(range(1, 11)), missing))


if __name__ == "__main__":
    unittest.main()
