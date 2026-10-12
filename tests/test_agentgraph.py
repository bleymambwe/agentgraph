import json
import tempfile
import unittest
from pathlib import Path

from agentgraph import Recorder
from agentgraph.adapters.claude_code import handle_hook, hook_config, import_transcript
from agentgraph.demo import write_demo
from agentgraph.redact import redact
from agentgraph.report import build_report
from agentgraph.schema import build_run, read_lines, run_stats, verify_lines


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ChainTests(Base):
    def make(self):
        t = [1000]
        rec = Recorder(self.tmp, agent="a", task="t", run_id="r1", clock=lambda: t[0])
        a = rec.node("tool", "search", data={"input": "q"})
        t[0] += 50
        rec.update(a, dur_ms=50, data={"output": "found"})
        rec.node("answer", "done", cites=[a])
        rec.end("success", "ok")
        return rec.path

    def test_clean_chain_verifies(self):
        errors, head = verify_lines(read_lines(self.make()))
        self.assertEqual(errors, [])
        self.assertEqual(len(head), 64)

    def test_edit_is_detected(self):
        p = self.make()
        lines = read_lines(p)
        lines[2] = lines[2].replace('"found"', '"forged"')
        errors, _ = verify_lines(lines)
        self.assertTrue(any("content altered" in why for _, why in errors))

    def test_deleted_line_is_detected(self):
        lines = read_lines(self.make())
        del lines[2]
        errors, _ = verify_lines(lines)
        self.assertTrue(errors)

    def test_reordered_lines_are_detected(self):
        lines = read_lines(self.make())
        lines[1], lines[2] = lines[2], lines[1]
        self.assertTrue(verify_lines(lines)[0])

    def test_rehashed_edit_breaks_next_link(self):
        from agentgraph.schema import GENESIS, seal, split_line
        lines = read_lines(self.make())
        body = json.loads(split_line(lines[1])[0])
        body["label"] = "forged"
        lines[1], _ = seal(body, split_line(lines[1])[1])  # attacker recomputes this line's hash
        errors, _ = verify_lines(lines)
        self.assertTrue(any(i == 2 for i, _ in errors))

    def test_build_run_folds_updates(self):
        built = build_run(read_lines(self.make()))
        n = built["nodes"]["n1"]
        self.assertEqual(n["data"], {"input": "q", "output": "found"})
        self.assertEqual(n["dur_ms"], 50)
        self.assertEqual(built["end"]["outcome"], "success")
        stats = run_stats(built)
        self.assertEqual((stats["steps"], stats["tools"], stats["cited"]), (2, 1, 1))

    def test_resume_continues_chain(self):
        p = self.make()
        rec = Recorder(p, agent="a", task="t")
        rec.node("think", "later")
        errors, _ = verify_lines(read_lines(p))
        self.assertEqual(errors, [])
        self.assertIn("n3", build_run(read_lines(p))["nodes"])


class RecorderTests(Base):
    def test_span_marks_error_and_reraises(self):
        rec = Recorder(self.tmp, agent="a", task="t", run_id="r")
        with self.assertRaises(RuntimeError):
            with rec.span("tool", "boom"):
                raise RuntimeError("bad")
        n = build_run(read_lines(rec.path))["nodes"]["n1"]
        self.assertEqual(n["status"], "error")
        self.assertIn("RuntimeError: bad", n["data"]["error"])

    def test_span_parents_children(self):
        rec = Recorder(self.tmp, agent="a", task="t", run_id="r")
        with rec.span("agent", "sub") as s:
            rec.node("tool", "inner")
        nodes = build_run(read_lines(rec.path))["nodes"]
        self.assertEqual(nodes["n2"]["parent"], s)
        self.assertEqual(nodes[s]["status"], "ok")

    def test_unknown_kind_rejected(self):
        rec = Recorder(self.tmp, agent="a", task="t", run_id="r")
        with self.assertRaises(ValueError):
            rec.node("banana", "x")

    def test_secrets_redacted_and_truncated(self):
        rec = Recorder(self.tmp, agent="a", task="t", run_id="r", max_chars=50)
        rec.node("tool", "x", data={"input": "key sk-abcdefghijklmnopqrstuvwxyz123456 " + "z" * 200})
        text = rec.path.read_text()
        self.assertNotIn("sk-abcdefgh", text)
        self.assertIn("truncated", text)

    def test_redact_assignments(self):
        self.assertEqual(redact("password = hunter22222"), "password = [REDACTED]")
        self.assertEqual(redact("nothing secret here"), "nothing secret here")


def _transcript(path):
    rows = [
        {"type": "user", "uuid": "u1", "parentUuid": None, "sessionId": "abcd1234ef", "timestamp": "2026-10-12T08:00:00Z",
         "cwd": "/w", "message": {"role": "user", "content": "Fix the failing test"}},
        {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "sessionId": "abcd1234ef", "timestamp": "2026-10-12T08:00:02Z",
         "message": {"role": "assistant", "model": "m", "content": [{"type": "thinking", "thinking": "look at the test"}]}},
        {"type": "assistant", "uuid": "a2", "parentUuid": "a1", "sessionId": "abcd1234ef", "timestamp": "2026-10-12T08:00:03Z",
         "message": {"role": "assistant", "model": "m", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -x"}}]}},
        {"type": "user", "uuid": "u2", "parentUuid": "a2", "sessionId": "abcd1234ef", "timestamp": "2026-10-12T08:00:08Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "1 failed, token=abc123456789"}]}},
        {"type": "assistant", "uuid": "a3", "parentUuid": "u2", "sessionId": "abcd1234ef", "timestamp": "2026-10-12T08:00:09Z",
         "message": {"role": "assistant", "model": "m", "content": [{"type": "text", "text": "The test fails on line 4."},
                                                                      {"type": "tool_use", "id": "t2", "name": "Task", "input": {"description": "dig deeper"}}]}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


class AdapterTests(Base):
    def test_import_transcript(self):
        src = self.tmp / "s.jsonl"
        _transcript(src)
        out = import_transcript(src, self.tmp / "out")
        lines = read_lines(out)
        self.assertEqual(verify_lines(lines)[0], [])
        built = build_run(lines)
        nodes = built["nodes"]
        kinds = [n["kind"] for n in nodes.values()]
        self.assertEqual(kinds, ["task", "think", "tool", "model", "agent"])
        bash = [n for n in nodes.values() if n["data"].get("tool") == "Bash"][0]
        self.assertEqual(bash["status"], "error")
        self.assertEqual(bash["dur_ms"], 5000)
        self.assertNotIn("abc123456789", json.dumps(bash["data"]))
        self.assertEqual(nodes["n3"]["parent"], "n2")
        self.assertEqual(nodes["n4"]["parent"], "n3")  # reply follows the tool result
        self.assertEqual(nodes["n5"]["parent"], "n4")
        self.assertEqual(nodes["n5"]["status"], "error")  # never got a result
        self.assertEqual(built["end"]["outcome"], "unknown")

    def test_reimport_refused(self):
        src = self.tmp / "s.jsonl"
        _transcript(src)
        import_transcript(src, self.tmp / "out")
        with self.assertRaises(FileExistsError):
            import_transcript(src, self.tmp / "out")

    def test_hooks_roundtrip(self):
        base = self.tmp / "ag"
        sid = "sess-1234567890"
        handle_hook({"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": "do it"}, base)
        handle_hook({"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Read", "tool_input": {"file_path": "a.py"}, "tool_use_id": "x1"}, base)
        handle_hook({"hook_event_name": "PreToolUse", "session_id": sid, "tool_name": "Bash", "tool_input": {"command": "ls"}}, base)
        handle_hook({"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Read", "tool_response": {"content": "ok"}, "tool_use_id": "x1"}, base)
        handle_hook({"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Bash", "tool_response": {"is_error": True}}, base)
        handle_hook({"hook_event_name": "Stop", "session_id": sid}, base)
        files = list((base / "traces").glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = read_lines(files[0])
        self.assertEqual(verify_lines(lines)[0], [])
        nodes = build_run(lines)["nodes"]
        self.assertEqual([n["status"] for n in nodes.values()], ["ok", "ok", "error"])
        self.assertFalse((base / "hook-errors.log").exists())

    def test_hook_never_raises(self):
        base = self.tmp / "ag"
        handle_hook({"hook_event_name": "PostToolUse", "session_id": "s", "tool_name": "X"}, base)  # no matching Pre
        handle_hook({"hook_event_name": "Whatever"}, self.tmp / "file.txt" / "nope")  # unwritable on purpose is fine

    def test_hook_config_shape(self):
        cfg = hook_config("python")
        self.assertIn("PreToolUse", cfg["hooks"])
        self.assertIn("agentgraph hook", cfg["hooks"]["PreToolUse"][0]["hooks"][0]["command"])


class DemoAndReportTests(Base):
    def test_demo_covers_every_outcome_and_verifies(self):
        files = write_demo(self.tmp / "t")
        self.assertEqual(len(files), 5)
        outcomes = set()
        for f in files:
            lines = read_lines(f)
            self.assertEqual(verify_lines(lines)[0], [], f.name)
            outcomes.add(run_stats(build_run(lines))["outcome"])
        self.assertEqual(outcomes, {"success", "partial", "failure"})

    def test_report_is_self_contained(self):
        files = write_demo(self.tmp / "t")
        info = build_report(files, self.tmp / "r.html", title="T <x>")
        html = (self.tmp / "r.html").read_text(encoding="utf-8")
        self.assertTrue(info["all_chains_ok"])
        self.assertNotIn("__AGENTGRAPH_DATA__", html)
        viewer = (Path(__file__).parents[1] / "agentgraph" / "viewer.html").read_text(encoding="utf-8")
        self.assertNotIn("http://", viewer)
        self.assertNotIn("https://", viewer)  # the viewer code loads nothing from the network
        self.assertNotRegex(viewer, r"<(script|link|img)[^>]+(src|href)=")
        self.assertIn("&lt;x&gt;", html)
        self.assertNotIn("</script><", html.split("<script>")[1].split("</script>")[0])


if __name__ == "__main__":
    unittest.main()
