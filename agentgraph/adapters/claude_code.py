"""Claude Code adapter: import finished sessions, or record live through hooks."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from ..recorder import Recorder

AGENT_TOOLS = {"Task", "Agent"}


def _ms(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _brief(name: str, inp) -> str:
    if not isinstance(inp, dict):
        return name
    for key in ("description", "command", "file_path", "pattern", "url", "query", "prompt", "path"):
        if inp.get(key):
            return "%s: %s" % (name, str(inp[key]).replace("\n", " ")[:90])
    return name


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def import_transcript(path, out_dir, redact: bool = True, max_chars: int = 4000) -> Path:
    """Convert a Claude Code session transcript (.jsonl) into an AgentGraph trace."""
    path = Path(path)
    records = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(ln))
        except ValueError:
            continue
    convo = [r for r in records if r.get("type") in ("user", "assistant") and isinstance(r.get("message"), dict)]
    if not convo:
        raise ValueError("no user/assistant messages found in %s" % path)

    first_prompt = next((_text_of(r["message"].get("content")) for r in convo
                         if r["type"] == "user" and not r.get("isMeta")
                         and _text_of(r["message"].get("content")).strip()
                         and not _text_of(r["message"].get("content")).lstrip().startswith("<")), "")
    session = next((r.get("sessionId") for r in convo if r.get("sessionId")), path.stem)
    model = next((r["message"].get("model") for r in convo if r["type"] == "assistant" and r["message"].get("model")), None)
    t0 = _ms(convo[0].get("timestamp")) or int(time.time() * 1000)
    clock_box = [t0]
    rec = Recorder(Path(out_dir) / ("claude-code-%s.jsonl" % session[:8]), agent="claude-code",
                   task=first_prompt.strip()[:300] or "Claude Code session", model=model,
                   run_id="claude-code-%s" % session[:8], redact=redact, max_chars=max_chars,
                   meta={"source": "claude-code-transcript", "session": session,
                         "cwd": next((r.get("cwd") for r in convo if r.get("cwd")), None)},
                   clock=lambda: clock_box[0])
    if rec._seq > 1:  # refuse to append to an earlier import
        raise FileExistsError("%s already exists; delete it to re-import" % rec.path)

    anc: dict[str, str | None] = {}   # record uuid -> nearest node id
    started: dict[str, tuple[str, int]] = {}  # tool_use_id -> (node id, start ms)
    last_node: str | None = None
    for r in convo:
        ts = _ms(r.get("timestamp")) or clock_box[0]
        clock_box[0] = max(clock_box[0], ts)
        inherit = anc.get(r.get("parentUuid")) or last_node
        content = r["message"].get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
        made = None
        if r["type"] == "user":
            for b in blocks:
                if b.get("type") == "tool_result" and b.get("tool_use_id") in started:
                    nid, start = started.pop(b["tool_use_id"])
                    rec.update(nid, status="error" if b.get("is_error") else "ok", ts=ts,
                               dur_ms=max(0, ts - start), data={"output": _text_of(b.get("content")) or str(b.get("content"))[:max_chars]})
            texts = [b.get("text", "") for b in blocks if b.get("type") == "text" and b.get("text", "").strip()]
            text = "\n".join(texts)
            injected = text.lstrip().startswith(("<local-command-", "<system-reminder"))
            if texts and not injected and not r.get("isMeta") and not any(b.get("type") == "tool_result" for b in blocks):
                made = rec.node("task", text.strip().replace("\n", " ")[:80], parent=inherit, ts=ts,
                                data={"prompt": text})
        else:
            usage = r["message"].get("usage") or {}
            prev = inherit
            for b in blocks:
                bt = b.get("type")
                if bt == "thinking":
                    made = rec.node("think", "reasoning", parent=prev, ts=ts,
                                    data={"thinking": b.get("thinking") or "(not recorded)"})
                elif bt == "text" and b.get("text", "").strip():
                    made = rec.node("model", b["text"].strip().replace("\n", " ")[:80], parent=prev, ts=ts,
                                    data={"text": b["text"], "model": r["message"].get("model"),
                                          "input_tokens": usage.get("input_tokens"),
                                          "output_tokens": usage.get("output_tokens")})
                elif bt == "tool_use":
                    kind = "agent" if b.get("name") in AGENT_TOOLS else "tool"
                    made = rec.node(kind, _brief(b.get("name", "tool"), b.get("input")), parent=prev, ts=ts,
                                    status="running", data={"tool": b.get("name"), "input": b.get("input")})
                    started[b["id"]] = (made, ts)
                else:
                    continue
                prev = made
        anc[r.get("uuid")] = made or inherit
        if made:
            last_node = made
    for nid, _ in started.values():
        rec.update(nid, status="error", data={"error": "no result recorded in transcript"})
    rec.end("unknown", "Imported from a Claude Code transcript. The outcome is not judged automatically.")
    return rec.path


# --------------------------------------------------------------------- hooks
def _state_path(base: Path, session: str) -> Path:
    return base / ".state" / (re.sub(r"[^A-Za-z0-9_-]", "_", session) + ".json")


def handle_hook(payload: dict, base: str | Path) -> None:
    """Record one Claude Code hook event. Never raises into the host agent."""
    base = Path(base)
    try:
        _handle(payload, base)
    except Exception as exc:  # a recorder must never break the agent it watches
        try:
            base.mkdir(parents=True, exist_ok=True)
            with (base / "hook-errors.log").open("a", encoding="utf-8") as fh:
                fh.write("%s %r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), exc))
        except OSError:
            pass


def _handle(p: dict, base: Path) -> None:
    session = p.get("session_id") or "session"
    event = p.get("hook_event_name") or ""
    sp = _state_path(base, session)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {"pending": {}}
    run_id = "claude-code-live-%s" % session[:8]
    rec = Recorder(base / "traces" / (run_id + ".jsonl"), agent="claude-code",
                   task=(p.get("prompt") or "Claude Code session (live)")[:300], run_id=run_id,
                   meta={"source": "claude-code-hooks", "session": session, "cwd": p.get("cwd")})
    if event == "UserPromptSubmit":
        nid = rec.node("task", (p.get("prompt") or "")[:80].replace("\n", " "), parent=rec._last,
                       data={"prompt": p.get("prompt")})
        state["anchor"] = nid
    elif event == "PreToolUse":
        name = p.get("tool_name") or "tool"
        nid = rec.node("agent" if name in AGENT_TOOLS else "tool", _brief(name, p.get("tool_input")),
                       parent=state.get("anchor"), status="running",
                       data={"tool": name, "input": p.get("tool_input")})
        key = p.get("tool_use_id") or "stack:" + name
        state["pending"].setdefault(key, []).append([nid, int(time.time() * 1000)])
    elif event == "PostToolUse":
        name = p.get("tool_name") or "tool"
        key = p.get("tool_use_id") if p.get("tool_use_id") in state["pending"] else "stack:" + name
        queue = state["pending"].get(key) or []
        if queue:
            nid, start = queue.pop(0)
            resp = p.get("tool_response")
            failed = isinstance(resp, dict) and bool(resp.get("is_error") or resp.get("error"))
            rec.update(nid, status="error" if failed else "ok", dur_ms=int(time.time() * 1000) - start,
                       data={"output": resp})
            state["anchor"] = nid
    elif event in ("Stop", "SessionEnd", "SubagentStop"):
        rec.end("unknown", "%s hook fired" % event)
    sp.write_text(json.dumps(state), encoding="utf-8")


def hook_main(base: str | Path | None = None) -> int:
    base = Path(base or os.environ.get("AGENTGRAPH_DIR") or Path.cwd() / ".agentgraph")
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    handle_hook(payload, base)
    return 0


def hook_config(python: str | None = None) -> dict:
    cmd = '"%s" -m agentgraph hook' % (python or sys.executable)
    entry = [{"matcher": "*", "hooks": [{"type": "command", "command": cmd}]}]
    plain = [{"hooks": [{"type": "command", "command": cmd}]}]
    return {"hooks": {"UserPromptSubmit": plain, "PreToolUse": entry, "PostToolUse": entry,
                      "Stop": plain, "SessionEnd": plain}}
