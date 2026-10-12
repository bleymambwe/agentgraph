"""Trace format: JSONL, one event per line, sealed into a sha256 hash chain.

Every line is the canonical JSON of the event body followed by ``"prev"`` and
``"hash"`` fields. ``hash = sha256(prev + body)`` where ``body`` is the exact text
of the line before those two fields, so a verifier (Python here, JavaScript in the
report) never has to re-serialise anything. Changing, removing or reordering any
line breaks the chain from that point on.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SCHEMA_VERSION = 1
GENESIS = "0" * 64

KINDS = (
    "task", "plan", "think", "tool", "query", "model",
    "agent", "evidence", "decision", "answer", "error",
)
STATUSES = ("ok", "error", "running")
OUTCOMES = ("success", "partial", "failure", "unknown")

_TAIL = re.compile(r',"prev":"([0-9a-f]{64})","hash":"([0-9a-f]{64})"\}$')


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def seal(body: dict, prev: str) -> tuple[str, str]:
    """Return (line, hash) for an event body chained after ``prev``."""
    text = canonical(body)
    digest = hashlib.sha256((prev + text).encode("ascii")).hexdigest()
    return text[:-1] + ',"prev":"%s","hash":"%s"}' % (prev, digest), digest


def split_line(line: str) -> tuple[str, str, str]:
    m = _TAIL.search(line)
    if not m:
        raise ValueError("not a sealed event line")
    return line[: m.start()] + "}", m.group(1), m.group(2)


def read_lines(path) -> list[str]:
    text = Path(path).read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.strip()]


def verify_lines(lines) -> tuple[list[tuple[int, str]], str]:
    """Check the hash chain. Returns (errors, head_hash); errors is [(line_no, why)]."""
    errors: list[tuple[int, str]] = []
    prev = GENESIS
    for i, line in enumerate(lines):
        try:
            body, p, h = split_line(line)
        except ValueError:
            errors.append((i, "line is not sealed"))
            break
        if p != prev:
            errors.append((i, "chain broken: previous hash does not match"))
        if hashlib.sha256((p + body).encode("ascii")).hexdigest() != h:
            errors.append((i, "content altered: hash does not match"))
        try:
            seq = json.loads(body).get("seq")
        except ValueError:
            errors.append((i, "line is not valid JSON"))
            break
        if seq != i:
            errors.append((i, "sequence gap: expected %d, found %s" % (i, seq)))
        prev = h
    return errors, prev


def build_run(lines) -> dict:
    """Fold events into {run, nodes, end, events}. Mirrors the viewer's logic."""
    events = [json.loads(split_line(ln)[0]) for ln in lines]
    if not events or events[0].get("type") != "run":
        raise ValueError("trace must start with a run event")
    run = {k: events[0].get(k) for k in ("run", "agent", "task", "model", "meta", "ts")}
    nodes: dict[str, dict] = {}
    end = None
    for ev in events[1:]:
        t = ev.get("type")
        if t == "node":
            nodes[ev["id"]] = {
                "id": ev["id"], "kind": ev["kind"], "label": ev.get("label", ""),
                "parent": ev.get("parent"), "cites": list(ev.get("cites") or []),
                "status": ev.get("status", "ok"), "data": dict(ev.get("data") or {}),
                "dur_ms": ev.get("dur_ms"), "ts": ev["ts"],
            }
        elif t == "update" and ev["id"] in nodes:
            n = nodes[ev["id"]]
            for k in ("status", "label", "dur_ms"):
                if k in ev:
                    n[k] = ev[k]
            if "cites" in ev:
                n["cites"] = list(ev["cites"])
            n["data"].update(ev.get("data") or {})
        elif t == "end":
            end = ev
    return {"run": run, "nodes": nodes, "end": end, "events": events}


def run_stats(built: dict) -> dict:
    nodes = built["nodes"]
    events = built["events"]
    depth: dict[str, int] = {}
    for nid, n in nodes.items():  # parents are created before children
        depth[nid] = depth[n["parent"]] + 1 if n["parent"] in depth else 0

    kids: dict[str, int] = {}
    for n in nodes.values():
        if n["parent"]:
            kids[n["parent"]] = kids.get(n["parent"], 0) + 1
    ts = [e["ts"] for e in events if "ts" in e]
    answers = [n for n in nodes.values() if n["kind"] == "answer"]
    return {
        "events": len(events),
        "steps": len(nodes),
        "tools": sum(1 for n in nodes.values() if n["kind"] in ("tool", "query")),
        "errors": sum(1 for n in nodes.values() if n["status"] == "error"),
        "agents": sum(1 for n in nodes.values() if n["kind"] == "agent"),
        "depth": max(depth.values(), default=0),
        "fanout": max(kids.values(), default=0),
        "duration_ms": (max(ts) - min(ts)) if ts else 0,
        "cited": len({c for n in answers for c in n["cites"]}),
        "outcome": (built["end"] or {}).get("outcome", "running"),
    }
