# AgentGraph

Record what an agent did, replay it as a graph, and audit it later. One command produces a single self-contained HTML file. No server, no network, no dependencies beyond Python 3.9+.

Built for the Open Agent Hackathon 2026 (see `dashboard.html` for the event brief).

## Install

Requires Python 3.9 or newer. There are no other dependencies.

**From GitHub (any OS):**

```bash
pip install git+https://github.com/bleymambwe/agentgraph.git
```

**Isolated command-line tool with pipx:**

```bash
pipx install git+https://github.com/bleymambwe/agentgraph.git
```

**From a clone, for development:**

```bash
git clone https://github.com/bleymambwe/agentgraph.git
cd agentgraph
pip install -e .
python -m unittest discover -s tests
```

**No install at all:** clone the repo and run `python -m agentgraph ...` from its root folder.

Check it worked:

```bash
agentgraph --version
```

On Windows, if `agentgraph` is not found after `pip install`, use `python -m agentgraph` instead, which behaves identically.

## Try it in 30 seconds

```bash
agentgraph demo --open
```

This writes `out/report.html` and opens it in your browser. The commands below also work as `python -m agentgraph <command>`.

This writes five **simulated** agents solving five different tasks to `out/report.html` and opens it. The agents are scripted, with no model or network behind them, so you can see every node type and outcome without API keys.

## What the report gives you

| View | Use |
| --- | --- |
| **Compare** | Every run as a minimal flow graph on its own card. One slider replays them in lockstep, so you can see which strategy reaches an answer in fewer steps. |
| **Hub** | The agent at the centre, the tools and data sources it reached for around it. Line weight is the number of calls, dashed red is failures, and the line goes green when that source is the current step. Quickest way to see how two agents differ in approach. |
| **Run** | One run's full flow graph with labelled nodes. Play, pause, step back and forward, scrub, 0.5x to 5x. Keys: Space, Left, Right, Home, End. |
| **Summary** | Table of outcome, steps, calls, errors, sub-agents, depth, fan-out, evidence cited, duration, integrity. |
| **Node tab** | Click any node for its input, output, timing, parent and cited evidence. "Highlight path" lights up everything an answer depends on. |
| **Event log** | Every event in order. Click a row to jump the replay there. |
| **Audit tab** | Hash-chain status, head hash per run, a report digest, and export of the original `.jsonl`. |

The address bar tracks the view, run, replay position and selected node (`#v=run&r=react-analyst&p=7&n=n4`). Send someone that link and they land on the exact step you meant.

## Reading the graphs

Hollow circles are steps, joined by a thin track. The dashed green line is the path the agent has actually taken so far. Dotted blue lines are evidence: an answer or decision pointing back at the calls it relied on. Green outline is a tool or data call, blue is reasoning, a ringed dot is a sub-agent, a solid green dot is evidence, a ringed dark dot is the answer, and red is a failure. Select any node and tick "highlight path" to light up everything it depends on.

The visual style follows two references: the minimal vein-to-vein flow diagram on the Terumo BCT Africa Hackathon site (hollow nodes on a track, mono micro-labels, a green live path, dotted loops for the AI layer) and the hub-and-spoke "eve" slide in the AgriChat deck (agent in the middle, data sources around it). It uses IBM Plex when installed and falls back to system fonts so the file stays fully offline.

## Record your own agent

```python
from agentgraph import Recorder

rec = Recorder("traces", agent="my-agent", task="Why did revenue drop?")
q = rec.node("query", "sql: revenue by region", data={"input": "SELECT ...", "output": "EMEA -22%"})
with rec.span("agent", "sub-agent: pricing") as sp:      # children created inside get this parent
    hit = rec.node("tool", "search: price changes", data={"output": "+18% on 1 Jul"})
rec.node("answer", "Price rise explains it", cites=[q, hit])
rec.end("success", "2 pieces of evidence")
```

Node kinds: `task plan think tool query model agent evidence decision answer error`. `cites` draws dashed evidence edges, which is what powers "why did the agent answer this". An exception inside `span()` marks the node `error` and is re-raised.

```bash
agentgraph report traces -o report.html --open
```

## Claude Code

**Import a finished session (recommended, most faithful structure):**

```bash
agentgraph import-claude ~/.claude/projects/<project-folder>      # newest session
agentgraph import-claude path/to/session.jsonl --out traces
agentgraph report .agentgraph/traces -o report.html --open
```

Each tool call becomes a node, parented by the transcript's own `parentUuid` chain. Tool results fill in output, status and duration. Sub-agent (`Task`) calls get their own kind. Imported runs have outcome `unknown`: the importer does not judge success.

**Record live with hooks:** run `python -m agentgraph hook-config` and merge the printed `hooks` block into your Claude Code `settings.json`. Hooks write to `.agentgraph/traces/` in the project (override with `AGENTGRAPH_DIR`). The hook never raises into Claude Code; failures are logged to `hook-errors.log`. Live hooks chain tool calls in the order they start, so parallel calls look sequential. Use the import for exact structure.

## Open models and other agents

Any runtime that can call the Python `Recorder` works today (LangGraph, plain loops, a wrapper around an Ollama or OpenAI-compatible client). Writing a trace from another language only needs the format below.

## Audit properties

- Each line is the canonical JSON of an event plus `"prev"` and `"hash"`, where `hash = sha256(prev + body)`. Edit, delete or reorder a line and every following link breaks.
- The report **re-verifies every chain in the viewer's browser** from the embedded raw lines, so a recipient does not have to trust the generator. `python -m agentgraph verify traces/` does the same on the command line and exits 1 on failure.
- Secrets matching common key, token and password patterns are redacted at record time. Long values are truncated at 4,000 characters. This is best effort. Read a report before sharing it.

What it does **not** prove: a chain made by someone who controls the whole file can be rebuilt from scratch, and deleting the last events leaves a valid shorter chain. Record the report digest (or each head hash) somewhere independent when you create it, such as a ticket or a signed commit, and compare later.

## Trace format (v1)

JSONL. First event `run` (agent, task, model, meta). Then `node` (id, kind, label, parent, cites, status, data), `update` (id plus changed fields, applied in order, which is how replay shows a call going from running to ok or error), and optional `end` (outcome, summary). Every event has `v`, `seq` (0, 1, 2, ...), `ts` (epoch ms), `prev`, `hash`.

## Tests

```bash
python -m unittest discover -s tests
```

19 tests cover the hash chain (clean, edited, deleted, reordered, re-hashed edit), the recorder, redaction, the transcript importer, the hook handler, and report generation. The viewer was checked by hand in Chromium: all chains verified, replay, deep links, tamper detection, and a 804-event real session (about 110 ms per replay step).

## Known limits

- The hook adapter has been tested against simulated hook payloads, not a live Claude Code session. Check the field names against your Claude Code version.
- Replay re-folds events from the start on each step. A few thousand events is fine; tens of thousands will feel slow.
- Sessions deeper than 45 levels are folded into side-by-side columns so the graph stays navigable.
- No adapters yet for MCP traffic or OpenAI-compatible HTTP proxies. The schema is ready for them.

MIT licence.
