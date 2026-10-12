"""Append-only recorder. Any Python agent can emit a trace with a few calls."""
from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .redact import redact as _redact
from .schema import GENESIS, KINDS, OUTCOMES, SCHEMA_VERSION, seal, split_line

AUTO = object()  # "parent = innermost open span, else the previous node"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "agent"


class Recorder:
    """Write one run to ``<dir>/<run_id>.jsonl``.

    >>> rec = Recorder("traces", agent="my-agent", task="Summarise the report")
    >>> a = rec.node("tool", "search: q3 revenue", data={"input": "q3 revenue"})
    >>> rec.node("answer", "Revenue fell 12%", cites=[a])
    >>> rec.end("success")
    """

    def __init__(self, path, agent: str, task: str, model: str | None = None,
                 run_id: str | None = None, meta: dict | None = None, clock=None,
                 redact: bool = True, max_chars: int = 4000):
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._redact = redact
        self._max = max_chars
        self._lock = threading.Lock()
        self._stack: list[str] = []
        self._last: str | None = None
        self._n = 0
        self._seq = 0
        self._prev = GENESIS
        self.agent = agent
        path = Path(path)
        if path.suffix != ".jsonl":
            run_id = run_id or "%s-%s" % (_slug(agent), time.strftime("%Y%m%d-%H%M%S"))
            path.mkdir(parents=True, exist_ok=True)
            path = path / (run_id + ".jsonl")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        if path.exists() and path.stat().st_size > 0:
            self._resume()
        else:
            self.run_id = run_id or path.stem
            self._emit({"type": "run", "run": self.run_id, "agent": agent,
                        "task": self._clean(task), "model": model, "meta": self._clean(meta or {})})

    # -- internals ---------------------------------------------------------
    def _resume(self) -> None:
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        body, _, digest = split_line(lines[-1])
        first = json.loads(split_line(lines[0])[0])
        self.run_id = first["run"]
        self._seq = len(lines)
        self._prev = digest
        for ln in lines:
            ev = json.loads(split_line(ln)[0])
            if ev.get("type") == "node":
                self._n = max(self._n, int(ev["id"][1:]))
                self._last = ev["id"]

    def _clean(self, v, depth: int = 0):
        if isinstance(v, str):
            if self._redact:
                v = _redact(v)
            if len(v) > self._max:
                v = v[: self._max] + "... [+%d chars truncated]" % (len(v) - self._max)
            return v
        if isinstance(v, dict):
            return {str(k): self._clean(x, depth + 1) for k, x in v.items()} if depth < 6 else str(v)[: self._max]
        if isinstance(v, (list, tuple)):
            return [self._clean(x, depth + 1) for x in list(v)[:200]] if depth < 6 else str(v)[: self._max]
        if v is None or isinstance(v, (bool, int, float)):
            return v
        return self._clean(str(v), depth + 1)

    def _emit(self, body: dict) -> None:
        with self._lock:
            body = dict(body, v=SCHEMA_VERSION, seq=self._seq)
            body.setdefault("ts", self._clock())
            line, digest = seal(body, self._prev)
            with self.path.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            self._prev = digest
            self._seq += 1

    # -- public API --------------------------------------------------------
    def node(self, kind: str, label: str, *, parent=AUTO, cites=(), data: dict | None = None,
             status: str = "ok", dur_ms: int | None = None, ts: int | None = None) -> str:
        if kind not in KINDS:
            raise ValueError("unknown kind %r; use one of %s" % (kind, ", ".join(KINDS)))
        if parent is AUTO:
            parent = self._stack[-1] if self._stack else self._last
        with self._lock:
            self._n += 1
            nid = "n%d" % self._n
        body = {"type": "node", "id": nid, "kind": kind, "label": self._clean(label)[:200],
                "parent": parent, "cites": list(cites), "status": status,
                "data": self._clean(data or {})}
        if dur_ms is not None:
            body["dur_ms"] = int(dur_ms)
        if ts is not None:
            body["ts"] = int(ts)
        self._emit(body)
        self._last = nid
        return nid

    def update(self, node_id: str, *, status: str | None = None, label: str | None = None,
               data: dict | None = None, dur_ms: int | None = None, cites=None,
               ts: int | None = None) -> None:
        body: dict = {"type": "update", "id": node_id}
        if status:
            body["status"] = status
        if label:
            body["label"] = self._clean(label)[:200]
        if data:
            body["data"] = self._clean(data)
        if dur_ms is not None:
            body["dur_ms"] = int(dur_ms)
        if cites is not None:
            body["cites"] = list(cites)
        if ts is not None:
            body["ts"] = int(ts)
        self._emit(body)

    @contextmanager
    def span(self, kind: str, label: str, **kw):
        """Open a node, make it the parent of nodes created inside, time it, and
        mark it ``error`` if the block raises."""
        kw.setdefault("status", "running")
        nid = self.node(kind, label, **kw)
        start = self._clock()
        self._stack.append(nid)
        try:
            yield nid
        except BaseException as exc:
            self._stack.pop()
            self.update(nid, status="error", dur_ms=self._clock() - start,
                        data={"error": "%s: %s" % (type(exc).__name__, exc)})
            raise
        else:
            self._stack.pop()
            self.update(nid, status="ok", dur_ms=self._clock() - start)
        finally:
            self._last = nid

    def end(self, outcome: str = "success", summary: str = "", answer: str | None = None) -> None:
        if outcome not in OUTCOMES:
            raise ValueError("outcome must be one of %s" % ", ".join(OUTCOMES))
        self._emit({"type": "end", "outcome": outcome, "summary": self._clean(summary),
                    "answer": answer})
