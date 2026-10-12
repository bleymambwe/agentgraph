"""Bundle traces into one self-contained HTML file (no network, no build step)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import __version__
from .schema import read_lines, verify_lines

_TEMPLATE = Path(__file__).with_name("viewer.html")


def collect(paths) -> list[Path]:
    found: list[Path] = []
    for p in map(Path, paths):
        found.extend(sorted(p.glob("*.jsonl")) if p.is_dir() else [p])
    if not found:
        raise FileNotFoundError("no .jsonl traces found")
    return found


def build_report(paths, out, title: str = "Agent run audit") -> dict:
    runs = []
    for f in collect(paths):
        lines = read_lines(f)
        errors, head = verify_lines(lines)
        runs.append({"file": f.name, "lines": lines, "head": head, "chain_ok": not errors})
    digest = hashlib.sha256("".join(r["head"] for r in runs).encode()).hexdigest()
    data = {"title": title, "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "version": __version__, "digest": digest, "runs": runs}
    blob = json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("</", "<\\/")
    html = _TEMPLATE.read_text(encoding="utf-8").replace("__TITLE__", _esc(title)).replace(
        "/*__AGENTGRAPH_DATA__*/null", blob)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    return {"out": out, "runs": len(runs), "digest": digest,
            "all_chains_ok": all(r["chain_ok"] for r in runs)}


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
