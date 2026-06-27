# Lessons Learned

## Session 2026-06-26

### 7. GEPA prompt overrides must clear state between evaluations
- **Failure:** GEPA candidates were evaluated using cached state files from previous runs. Speed showed as 128ms (cached) vs 6000ms (real). Accuracy was meaningless.
- **Fix:** Added `clear_state=True` flag to `EvaluationRunner.run_all()` that deletes `research_state_*.json` before each candidate eval.
- **Detection:** GEPA report showed "accuracy=100%, speed=128ms" — impossible for a real web crawl.

### 8. Self-rewriting patch must match source code quoting exactly
- **Failure:** `_generate_self_patch` used single quotes (`'planner': "`) but source code uses double quotes (`"planner": "`). The patch executed without error but made no changes.
- **Fix:** Use `re.sub()` with raw strings to handle any quoting, or match the exact source format.
- **Prevention:** Test `_self_patch.py` by checking the output file has actually changed after running it.

### 9. Wikipedia API rate limits persist even with Semaphore(1)
- **Failure:** Sequential Wikipedia requests still get 429 errors because the semaphore is per-instance, not global across parallel fetch_batch workers.
- **Fix:** Used `Semaphore(1)` with jittered delays (`random.uniform(0.3, 0.8)`). Works most of the time but still hits 429 under heavy load.
- **Alternative:** Use a class-level semaphore shared across all instances, or use exponential backoff with retry.

### 10. Ollama model name matters — auto-detect available models
- **Failure:** Hardcoded "llama3.2" model doesn't exist. `/api/generate` returned 404, not a model-not-found error.
- **Fix:** Query `/api/tags` at startup, select best available model by priority list (lfm2.5:latest > gemma4:e2b > qwen3.5).
- **Detection:** `is_available()` returned True, but both `/api/chat` and `/api/generate` returned 404.

## Session 2026-06-22

### 1. Self-modifying code must avoid marker collisions
- **Failure:** `_write_dogfood_footer` used a marker string (`# === DF_SELF_ASSESS ===`) that also appeared in its own source code. The function split on its own source code, truncating the rest of the file.
- **Detection:** File became uncompilable with `unterminated triple-quoted string literal` or `unterminated string literal` error.
- **Prevention:** Construct marker strings dynamically by concatenating parts (`pfx + sfx`) so the literal never appears contiguously in source code.

### 2. Asyncio event loop management
- **Constraint:** `asyncio.run()` cannot be called when an event loop is already running.
- **Fix:** All async calls from synchronous context use `asyncio.run()`. The synchronous CLI flow calls `asyncio.run()` from `main()` and worker functions. This works because `main()` is synchronous.

### 3. State file collisions in eval runner
- **Failure:** Multiple eval tasks using the same `research_state.json` caused each subsequent task to find a "completed" state and skip.
- **Fix:** Use unique state paths per task/run: `research_state_{task.id}_{run_id}.json`.

### 4. Search queries vs URLs
- **Failure:** TaskPlanner produced plain text queries but WebCrawler expects HTTP URLs.
- **Fix:** TaskPlanner produces URL-encoded query strings; `search_url()` wraps them in DuckDuckGo HTML search URLs.

### 5. Re.finditer is not subscriptable on Python 3.11+
- **Failure:** `matches_b[:2]` on `re.finditer()` output throws `'callable_iterator' object is not subscriptable`.
- **Fix:** Wrap in `list()`: `list(pattern["trigger"].finditer(text))[:2]`.

### 6. Subagent tool execution gap
- **Observation:** The `local-dev` subagent repeatedly reported completing tasks without actually modifying files. Commands appeared in output as planned but were not executed.
- **Action:** Manually write/verify all file changes rather than relying on subagent execution.
