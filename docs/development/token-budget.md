# Token Budget And Context Hygiene

This repo has long-running release work, model experiments, Docker logs, and hardware diagnostics.
That makes token discipline part of the engineering workflow.

## Defaults For Agents

- Prefer the smallest relevant test category before broad sweeps.
- Use `--dry-run` before running unfamiliar categories.
- Use the quiet category-runner default so full logs land in `artifacts/test-categories/`.
- Summarize pass/fail status and artifact paths instead of pasting complete JSON reports or logs into
  chat.
- Store large generated evidence under `artifacts/` and reference paths.
- Use targeted `rg`, `Select-String`, or JSON projections instead of dumping whole files.
- Keep README edits concise; put matrices, runbooks, and decision logs under `docs/`.

## Category Runner

Recommended low-token commands:

```bash
python3 scripts/run_test_category.py quick
python3 scripts/run_test_category.py contracts
python3 scripts/run_test_category.py all --continue-on-failure
```

Windows:

```powershell
pwsh -NoProfile -File scripts/dev_container.ps1 test-category quick
pwsh -NoProfile -File scripts/dev_container.ps1 test-category all --continue-on-failure
```

The runner prints command summaries and writes logs under:

```text
artifacts/test-categories/<category>/
```

Use `--tail-lines N` only when the default failure tail is not enough. Use `--verbose` only when live
logs are more important than preserving thread context.

## OpenAI API Controls

When Language uses OpenAI APIs directly, token control should be explicit:

- Count input tokens before large requests with the Responses input-token count endpoint.
- Set output limits such as `max_output_tokens` on generation calls.
- Use truncation deliberately; automatic truncation can drop older conversation items.
- Use Responses compaction for long-running stateful conversations where compaction is appropriate.
- Prefer structured outputs and concise schemas over free-form verbose traces.

These controls reduce provider spend and prevent context-window failures, but they do not replace
local artifact discipline. Large logs should still be stored as files and summarized.

## Headroom Evaluation

`chopratejas/headroom` is a promising optional tool to evaluate because its README describes local
compression for tool outputs, logs, files, RAG chunks, conversation history, Codex wrapping,
OpenAI-compatible proxy mode, MCP tools, and reversible retrieval.

Do not add it to the release path without a pinned dependency and a small eval. Suggested evaluation:

1. Run a noisy category with `--quiet` and keep the raw log artifacts.
2. Run Headroom against the same logs or through its wrapper/proxy mode in a disposable environment.
3. Compare token savings, retrieval fidelity, failure diagnosis quality, runtime overhead, and
   whether sensitive local evidence leaves the machine.
4. Record the decision under `docs/research/decisions/` before adopting it.

Until that eval exists, the supported repo-level token control is the category runner plus concise
artifact handoffs.
