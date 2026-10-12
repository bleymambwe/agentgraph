"""Five scripted agents solving five different tasks.

These are SIMULATED. No model or network is involved and the numbers inside the
tasks are invented. They exist to exercise every node kind and every outcome so
the viewer can be tested and demonstrated without API keys. Each run is marked
``meta.simulated = true``.
"""
from __future__ import annotations

import random
from pathlib import Path

from .recorder import Recorder


class _Clock:
    def __init__(self, seed: int, start: int):
        self.t = start
        self.rng = random.Random(seed)

    def __call__(self) -> int:
        return self.t

    def tick(self, lo: int = 200, hi: int = 1800) -> int:
        d = self.rng.randint(lo, hi)
        self.t += d
        return d


def _rec(out, agent, task, seed, start, model="simulated-model"):
    clock = _Clock(seed, start)
    return Recorder(out, agent=agent, task=task, model=model, run_id=agent, clock=clock,
                    meta={"simulated": True, "strategy": agent}), clock


def react_analyst(out):
    r, c = _rec(out, "react-analyst", "Why did EMEA revenue drop in Q3?", 1, 1_790_000_000_000)
    t = r.node("task", "Why did EMEA revenue drop in Q3?")
    c.tick(); a = r.node("think", "Need revenue by region and quarter first", parent=t)
    c.tick(); q1 = r.node("query", "sql: revenue by region, Q2 vs Q3", parent=a, status="running",
                          data={"input": "SELECT region, quarter, SUM(amount) FROM sales GROUP BY 1,2"})
    r.update(q1, status="ok", dur_ms=c.tick(), data={"output": "EMEA Q2 4.1M, Q3 3.2M (-22%). Other regions flat."})
    c.tick(); b = r.node("think", "EMEA fell 22%. Split by product line", parent=q1)
    c.tick(); q2 = r.node("query", "sql: EMEA by product line", parent=b, status="running",
                          data={"input": "SELECT product, SUM(amount) FROM sales WHERE region='EMEA' ..."})
    r.update(q2, status="error", dur_ms=c.tick(8000, 9000), data={"error": "TimeoutError: warehouse query exceeded 8s"})
    c.tick(); q3 = r.node("query", "sql: EMEA by product line (retry, last 2 quarters)", parent=q2, status="running",
                          data={"input": "same query, filtered to Q2-Q3"})
    r.update(q3, status="ok", dur_ms=c.tick(), data={"output": "Analytics suite -1.4M. Support add-on flat."})
    c.tick(); e1 = r.node("evidence", "Analytics suite down 1.4M of 0.9M total drop", parent=q3, cites=[q1, q3])
    c.tick(); w = r.node("tool", "search: Analytics suite EMEA Q3 pricing change", parent=e1, status="running",
                         data={"input": "Analytics suite EMEA Q3 pricing change"})
    r.update(w, status="ok", dur_ms=c.tick(), data={"output": "Price list v7 raised EMEA Analytics tier 18% on 1 Jul."})
    c.tick(); e2 = r.node("evidence", "Price rise of 18% on 1 Jul matches the drop", parent=w, cites=[w])
    c.tick(); ans = r.node("answer", "Q3 EMEA drop is driven by the Analytics price rise", parent=e2, cites=[e1, e2],
                           data={"text": "EMEA revenue fell 22% in Q3. The Analytics suite explains it; an 18% list-price rise on 1 July coincides."})
    r.end("success", "Answered with 2 evidence items after 1 retry.", answer=ans)


def planner_executor(out):
    r, c = _rec(out, "planner-executor", "Compare three vector databases for a 10M-document corpus", 2, 1_790_000_100_000)
    t = r.node("task", "Compare three vector databases for a 10M-document corpus")
    c.tick(); p = r.node("plan", "Plan: research A, B, C in parallel, then merge", parent=t,
                         data={"steps": ["research A", "research B", "research C", "merge", "recommend"]})
    branches = []
    for name, fail in (("Qdrant", False), ("Milvus", True), ("pgvector", False)):
        c.tick()
        with r.span("agent", "researcher: " + name, parent=p) as sp:
            c.tick(); s = r.node("tool", "search: %s benchmark 10M vectors" % name, parent=sp, status="running",
                                 data={"input": "%s benchmark 10M vectors" % name})
            r.update(s, status="ok", dur_ms=c.tick(), data={"output": "3 benchmark posts found"})
            c.tick(); f = r.node("tool", "fetch: %s docs, scaling page" % name, parent=sp, status="running",
                                 data={"input": "https://example.invalid/%s/scaling" % name.lower()})
            if fail:
                r.update(f, status="error", dur_ms=c.tick(3000, 4000), data={"error": "HTTP 503 from docs host"})
                c.tick(); f2 = r.node("tool", "fallback: cached copy of %s docs" % name, parent=sp)
                c.tick(); ev = r.node("evidence", "%s: older figures (v2.3), flagged stale" % name, parent=f2, cites=[s, f2])
            else:
                r.update(f, status="ok", dur_ms=c.tick(), data={"output": "Scaling notes retrieved"})
                c.tick(); ev = r.node("evidence", "%s: p95 latency and RAM per 10M vectors" % name, parent=f, cites=[s, f])
        branches.append(ev)
    c.tick(); m = r.node("model", "Merge findings into a comparison table", parent=p, cites=branches,
                         data={"input_tokens": 5200, "output_tokens": 640})
    c.tick(); d = r.node("decision", "Recommend pgvector if already on Postgres, else Qdrant", parent=m, cites=branches)
    c.tick(); ans = r.node("answer", "Recommendation with caveat on stale Milvus figures", parent=d, cites=branches)
    r.end("partial", "Milvus data was stale, so the comparison is incomplete.", answer=ans)


def orchestrator(out):
    r, c = _rec(out, "orchestrator", "Find why nightly CI build #4812 fails", 3, 1_790_000_200_000)
    t = r.node("task", "Find why nightly CI build #4812 fails")
    c.tick(); p = r.node("plan", "Delegate: logs, diff, flaky history", parent=t)
    finds = []
    work = (
        ("log-reader", [("tool", "read: build-4812.log (last 400 lines)", "NullPointerException in PaymentSerializer line 88")]),
        ("diff-inspector", [("tool", "git diff 4811..4812 --stat", "PaymentSerializer.java changed"),
                            ("tool", "git show a91c3f -- PaymentSerializer.java", "null guard removed in refactor")]),
        ("flaky-checker", [("query", "ci-db: failures of PaymentSerializerTest last 30 days", "0 failures before build 4812")]),
    )
    for name, steps in work:
        c.tick()
        with r.span("agent", "sub-agent: " + name, parent=p) as sp:
            last = sp
            for kind, label, out_text in steps:
                c.tick(); last = r.node(kind, label, parent=last, data={"output": out_text})
            c.tick(); finds.append(r.node("evidence", "%s: %s" % (name, steps[-1][2]), parent=last, cites=[last]))
    c.tick(); d = r.node("decision", "Three independent findings agree: commit a91c3f", parent=p, cites=finds)
    c.tick(); ans = r.node("answer", "Build fails because commit a91c3f removed a null guard", parent=d, cites=finds)
    r.end("success", "Root cause found by 3 sub-agents.", answer=ans)


def rag_explainer(out):
    r, c = _rec(out, "rag-explainer", "Does clause 14 of the supplier contract allow early termination?", 4, 1_790_000_300_000)
    t = r.node("task", "Does clause 14 of the supplier contract allow early termination?")
    c.tick(); q = r.node("model", "Rewrite question into 3 retrieval queries", parent=t, data={"input_tokens": 310, "output_tokens": 54})
    hits = []
    for i, (label, text) in enumerate((
        ("clause 14.2 termination for convenience", "Either party may terminate on 90 days written notice."),
        ("clause 14.5 termination fees", "Early termination within the first 24 months incurs a fee of 15% of remaining value."),
        ("schedule C amendments", "Amendment 2 replaced clause 14.2 notice period with 60 days."),
    )):
        c.tick(); hits.append(r.node("query", "retrieve: " + label, parent=q, data={"output": text}))
    c.tick(); weak = r.node("decision", "Reject hit 3 as ambiguous? Checking amendment date", parent=q, cites=[hits[2]],
                            data={"reasoning": "Amendment 2 is dated after the contract; it applies."})
    ev = []
    for h, label in zip(hits, ("14.2: 90 days notice (original)", "14.5: 15% fee if inside 24 months", "Amendment 2: notice is now 60 days")):
        c.tick(); ev.append(r.node("evidence", label, parent=weak, cites=[h]))
    c.tick(); m = r.node("model", "Draft answer with citations", parent=weak, cites=ev, data={"input_tokens": 1900, "output_tokens": 310})
    c.tick(); ans = r.node("answer", "Yes: 60 days notice, plus a 15% fee in the first 24 months", parent=m, cites=ev)
    r.end("success", "3 clauses cited, 1 ambiguity resolved.", answer=ans)


def single_shot(out):
    r, c = _rec(out, "single-shot", "Summarise the attached 300-page PDF", 5, 1_790_000_400_000)
    t = r.node("task", "Summarise the attached 300-page PDF")
    c.tick(); m = r.node("model", "Summarise entire document in one call", parent=t, status="running",
                         data={"input_tokens": 410_000})
    r.update(m, status="error", dur_ms=c.tick(), data={"error": "ContextLengthExceeded: 410000 tokens > 200000"})
    c.tick(); e = r.node("error", "No fallback configured, giving up", parent=m)
    r.end("failure", "Context overflow with no chunking strategy.")


ALL = (react_analyst, planner_executor, orchestrator, rag_explainer, single_shot)


def write_demo(out_dir) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.jsonl"):
        old.unlink()
    for fn in ALL:
        fn(out)
    return sorted(out.glob("*.jsonl"))
