from pathlib import Path

from agentgraph import Recorder


OUT = Path(__file__).parent / "out" / "research-trace"


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rec = Recorder(
        OUT,
        agent="codex-research-explainer",
        task="Explain Seeing Is Not Steering and prepare a visual site experience",
        model="Codex",
        run_id="seeing-is-not-steering",
        meta={"simulated": False, "scope": "local project + Opera debugging"},
    )

    task = rec.node("task", "Explain the READ/WRITE gap from genesis to applications")
    inspect = rec.node(
        "plan",
        "Inventory theory, experiment, results, two-clock extension, site, and audio paths",
        parent=task,
    )
    source = rec.node(
        "query",
        "inspect: README, pilot_results, research_audit, experiment_protocol, two_clock",
        parent=inspect,
        data={"output": "Auditable scaffold found; natural-model headline claims are explicitly limited."},
    )
    theory = rec.node(
        "evidence",
        "READ is decodability; WRITE is behavioral sensitivity under intervention",
        parent=source,
        cites=[source],
        data={"source": "theory.md", "claim": "Probe AUC does not imply causal steering."},
    )
    pilot = rec.node(
        "evidence",
        "Pythia-70M middle/final sites show low probe RMS efficiency and strong dark directions",
        parent=source,
        cites=[source],
        data={"source": "seeing_is_not_steering/pilot_results.md", "status": "small-model pilot; not generation-level toxicity."},
    )
    limits = rec.node(
        "decision",
        "Keep claims bounded: lexical proxy, synthetic/toy evidence, scale and human gates remain open",
        parent=inspect,
        cites=[theory, pilot],
    )
    site = rec.node(
        "tool",
        "debug: blessingsmambwe.web.app/seeingisnotsteering in Opera",
        parent=limits,
        data={"output": "Route currently returns 404; root is an unrelated IAM Opportunity Atlas."},
    )
    github = rec.node(
        "tool",
        "install: github.com/bleymambwe/agentgraph",
        parent=site,
        data={"output": "Cloned locally, installed editable, and 19 tests passed."},
    )
    report = rec.node(
        "tool",
        "visualize: generate AgentGraph replay report and serve it to Opera",
        parent=github,
        data={"output": "out/report.html generated and opened through localhost:8000."},
    )
    answer = rec.node(
        "answer",
        "Deliver a visual, audio-ready research explainer with explicit evidence boundaries",
        parent=report,
        cites=[theory, pilot, site, github, report],
        data={"next": "Publish the explainer once the site source/deployment target is identified."},
    )
    rec.end("partial", "Research is mapped and the workflow is visible; the requested Firebase route still needs its deploy source.", answer=answer)


if __name__ == "__main__":
    build()
