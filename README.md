# research-agent

> Self-improving deep research agent for the terminal. Built-in eval suite. GEPA self-improvement loop. Single file.

[![CI](https://github.com/bigknoxy/research-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/bigknoxy/research-agent/actions/workflows/ci.yml)
[![Release](https://github.com/bigknoxy/research-agent/actions/workflows/release.yml/badge.svg)](https://github.com/bigknoxy/research-agent/actions/workflows/release.yml)
[![Pages](https://github.com/bigknoxy/research-agent/actions/workflows/pages.yml/badge.svg)](https://bigknoxy.github.io/research-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

## Install

```bash
pip install git+https://github.com/bigknoxy/research-agent.git
```

*Requires Python 3.10+*

## Quick Start

```bash
# Run a research query
research-agent "What are the latest developments in RAG?"

# Run the eval suite
research-agent --eval --eval-runs 1

# Self-improvement loop (evolves prompt strategies automatically)
research-agent --gepa --gepa-generations 3

# Full dogfood pipeline (eval + GEPA + self-patch)
research-agent --dogfood
```

## CLI

| Flag | Description |
|------|-------------|
| `query` | Research query (positional) |
| `--eval` | Run evaluation suite |
| `--gepa` | Run GEPA self-improvement loop |
| `--dogfood` | Full pipeline: eval → GEPA → self-patch |
| `--searx-instance URL` | Use custom SearXNG instance |
| `--self-update` | Update to latest version from GitHub |
| `--report` | View last generated report |
| `--clear` | Clear saved state |
| `--state PATH` | Custom state file path |

## Update & Uninstall

```bash
# Update to latest version
pip install --upgrade git+https://github.com/bigknoxy/research-agent.git

# Or use the built-in updater
research-agent --self-update

# Uninstall
pip uninstall research-agent
```

## How It Works

```
Query → TaskPlanner → WebCrawler → ContradictionEngine → ReportSynthesizer → Report
         ↑              ↑            ↑                     ↑
         └─── Prompt strategies evolved by GEPA loop ──────┘
```

Each run decomposes your query into sub-questions, crawls multiple web sources (DuckDuckGo, Wikipedia, optional SearXNG), detects cross-source contradictions, and synthesizes a structured markdown report.

The **GEPA** (Generative Evolutionary Prompt Adaptation) loop evaluates prompt strategy variants, selects winners by accuracy, and mutates them to discover better strategies across generations. Improvements self-patch into the script.

## Eval Suite

Built-in regression testing. Run with `--eval`:

```
╭────────────────────────────┬────────┬───────────┬──────────╮
│ Task                       │ Status │ Pass Rate │ Duration │
├────────────────────────────┼────────┼───────────┼──────────┤
│ Ambiguous Health Claim     │ ✓      │ 4/4       │ 8003ms   │
│ Emerging Technology Impact │ ✓      │ 4/4       │ 6643ms   │
│ Historical Revisionism     │ ✓      │ 4/4       │ 8962ms   │
╰────────────────────────────┴────────┴───────────┴──────────╯
```

Tasks test report quality across different domains. 4 deterministic checks per task (executive summary, findings with sources, contradictions, citations). New runs must maintain 100% pass rate.

## Grading

Two-tier quality scoring:

- **Heuristic grader** (default): keyword-based, deterministic, instant — checks report structure and coverage
- **Ollama grader** (auto-detected): local LLM via Ollama for richer quality analysis when GPU available

## Self-Patching

After a GEPA run, the best prompt strategy is written to `_self_patch.py`:

```bash
research-agent --gepa --gepa-generations 3
python _self_patch.py
```

This bakes the learned improvements into the script and bumps the version.

## Docs & Design

- [Landing page](https://bigknoxy.github.io/research-agent/)
- [Design doc](https://bigknoxy.github.io/research-agent/design.html)
- [API reference](https://bigknoxy.github.io/research-agent/api.html)

## License

MIT
