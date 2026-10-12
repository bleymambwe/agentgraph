"""Command line: ``python -m agentgraph <command>``."""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .report import build_report, collect
from .schema import build_run, read_lines, run_stats, verify_lines


def _fmt_ms(ms: int) -> str:
    return "%.1fs" % (ms / 1000)


def cmd_demo(a) -> int:
    from .demo import write_demo
    out = Path(a.out)
    files = write_demo(out / "traces")
    info = build_report(files, out / "report.html", title="Five agents, five tasks (simulated)")
    print("Wrote %d simulated traces and %s" % (len(files), info["out"]))
    if a.open:
        webbrowser.open(Path(info["out"]).resolve().as_uri())
    return 0


def cmd_report(a) -> int:
    info = build_report(a.traces, a.out, title=a.title)
    print("Wrote %s (%d runs, chains %s)" % (info["out"], info["runs"], "intact" if info["all_chains_ok"] else "BROKEN"))
    print("Report digest:", info["digest"])
    if a.open:
        webbrowser.open(Path(info["out"]).resolve().as_uri())
    return 0 if info["all_chains_ok"] else 1


def cmd_verify(a) -> int:
    bad = 0
    for f in collect(a.traces):
        errors, head = verify_lines(read_lines(f))
        if errors:
            bad += 1
            print("FAIL %s" % f)
            for line_no, why in errors:
                print("     line %d: %s" % (line_no + 1, why))
        else:
            print("ok   %s  head=%s" % (f, head[:16]))
    return 1 if bad else 0


def cmd_summary(a) -> int:
    rows = []
    for f in collect(a.traces):
        built = build_run(read_lines(f))
        s = run_stats(built)
        rows.append((built["run"]["agent"], s["outcome"], s["steps"], s["tools"], s["errors"],
                     s["agents"], s["depth"], _fmt_ms(s["duration_ms"]), built["run"]["task"][:48]))
    head = ("agent", "outcome", "steps", "tools", "errs", "subagents", "depth", "time", "task")
    widths = [max(len(str(r[i])) for r in rows + [head]) for i in range(len(head))]
    for r in [head] + rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return 0


def cmd_import(a) -> int:
    from .adapters.claude_code import import_transcript
    src = Path(a.session)
    if src.is_dir():
        src = max(src.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    out = import_transcript(src, a.out, redact=not a.no_redact)
    print("Imported %s -> %s" % (src.name, out))
    return 0


def cmd_hook(a) -> int:
    from .adapters.claude_code import hook_main
    return hook_main()


def cmd_hook_config(a) -> int:
    from .adapters.claude_code import hook_config
    print(json.dumps(hook_config(), indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agentgraph", description="Record, replay and audit agent runs as a graph.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("demo", help="write five simulated agent runs and a report")
    s.add_argument("--out", default="out"); s.add_argument("--open", action="store_true"); s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("report", help="bundle .jsonl traces (files or folders) into one HTML file")
    s.add_argument("traces", nargs="+"); s.add_argument("-o", "--out", default="report.html")
    s.add_argument("--title", default="Agent run audit"); s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("verify", help="check the hash chain of trace files")
    s.add_argument("traces", nargs="+"); s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("summary", help="print a comparison table")
    s.add_argument("traces", nargs="+"); s.set_defaults(fn=cmd_summary)

    s = sub.add_parser("import-claude", help="convert a Claude Code transcript (file, or folder = newest) to a trace")
    s.add_argument("session"); s.add_argument("--out", default=".agentgraph/traces")
    s.add_argument("--no-redact", action="store_true"); s.set_defaults(fn=cmd_import)

    s = sub.add_parser("hook", help="Claude Code hook entry point (reads JSON on stdin)")
    s.set_defaults(fn=cmd_hook)

    s = sub.add_parser("hook-config", help="print the settings.json hooks block")
    s.set_defaults(fn=cmd_hook_config)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
