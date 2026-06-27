# Deep Research Agent — Implementation Plan

## Goal
Build a single-file Python CLI tool with 3 subsystems: Core Agent, Evaluation Harness, GEPA Self-Improvement Loop. The script must dogfood itself on execution.

## Architecture (Single File: `research_agent.py`)

### Modules within the file (organized as classes/functions with type hints):
1. **Planner** — `TaskPlanner` class: decomposes ambiguous queries into sub-questions, search queries, and a research plan.
2. **Crawler** — `WebCrawler` class: fetches URLs, strips HTML boilerplate, extracts clean text with citations.
3. **ContradictionEngine** — `ContradictionEngine` class: flags conflicting statistics, sources, and divergent claims.
4. **Synthesizer** — `ReportSynthesizer` class: generates structured Markdown reports from gathered evidence.
5. **SessionManager** — `SessionManager` class: saves/loads state to `research_state.json`.
6. **EvalHarness** — `EvaluationHarness` class: task bank, execution runs, transcript capture, hybrid graders.
7. **GEPALoop** — `GEPALoop` class: candidate pool, reflector, mutation, Pareto selection.
8. **CLI** — `main()` / `if __name__ == '__main__':` — argument parsing + autonomic execution block.

## Implementation Phases

### Phase 1: Project Setup + Core Agent Shell
- [ ] Create `pyproject.toml` with minimal deps (requests, beautifulsoup4, httpx, rich)
- [ ] Create `research_agent.py` with the 5 core modules (non-placeholder, fully typed)
- [ ] Each module must be self-contained with proper error handling
- [ ] Create `tasks/lessons.md`

### Phase 2: Evaluation Harness
- [ ] Add 3 pre-seeded ambiguous research tasks to task bank
- [ ] Implement execution runner with full transcript capture (tool calls, tokens, errors, reasoning)
- [ ] Implement code-based graders (deterministic assertions)
- [ ] Implement model-based grader (LLM-as-a-judge rubric) — can use regex/heuristic fallback since no API key
- [ ] Wire up pass@k metrics

### Phase 3: GEPA Self-Improvement Loop
- [ ] Candidate pool management (prompt variants stored as dicts)
- [ ] Reflector routine — reads transcripts, diagnoses failures via pattern matching
- [ ] Mutation engine — generates prompt variants from reflections
- [ ] Pareto selection — rank by accuracy, token efficiency, speed
- [ ] Self-revision output (writes improved version of self)

### Phase 4: Integration + Dogfooding
- [ ] Wire `if __name__ == '__main__':` block
- [ ] Add argparse CLI
- [ ] Test full pipeline: evals → GEPA → self-revision
- [ ] Run lint + typecheck
- [ ] Verify dogfooding loop works

## Key Design Decisions
- Use **httpx** for async HTTP (avoids sync bottlenecks)
- Use **BeautifulSoup** for HTML parsing
- Use **rich** for terminal UI (progress bars, panels)
- Simulated LLM calls (local regex/text manipulation) since no API key — model-based grader uses heuristic rubric
- Single file for self-rewriting simplicity
- Stateful via JSON for crash recovery

## Constraints
- No external LLM API dependency (local-dev Ollama for real runs, but code must work standalone)
- Must be self-contained, testable with `python research_agent.py`
- Type hints everywhere, no `Any` unless unavoidable
- Error logging with Python `logging` module
