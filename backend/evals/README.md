# Research evals

Scores the research service's routing (Auto mode) and reports against a labelled dataset.
Results go to LangSmith as experiments when `LANGSMITH_API_KEY` is set, otherwise they print
locally and are saved to `evals/results/` (gitignored).

## Run

From `backend/`:

| Command | Cost | What it checks |
|---|---|---|
| `venv/bin/python -m evals.run_research routing --rules-only` | free | the regex router alone |
| `venv/bin/python -m evals.run_research routing` | free (local model) | rules + the `LOCAL_LLM_MODEL` classifier |
| `venv/bin/python -m evals.run_research full --market offline --limit 5` | paid | real models on fixed market data |
| `venv/bin/python -m evals.run_research full --market live --provider anthropic` | paid | one provider end to end on live data |

Useful flags: `--only id1,id2`, `--limit N`, `--concurrency N` (default 1), `--local` (skip
upload), `--judge-model qwen3:8b` (add the local LLM judge to `full`), `--quiet`.

`full` calls cloud providers. Start with `--limit`, and prefer `--market offline` when comparing
changes: the fixtures in `fixtures.py` return the same synthetic prices, backtests and Treasury
rates every run, so a score change comes from the models or the orchestration, not the market.

## Files

- `datasets/research.jsonl`: one example per line: `id`, `inputs` (`prompt`, `history`),
  `outputs` (the ideal `kind`, `needs_web`, `symbols`, `treasury`). The `id` is the sync key:
  editing a line updates that LangSmith example; new lines are added. Removed lines are only
  reported, never deleted remotely.
- `evaluators.py`: plain functions, also unit-tested in `tests/test_evals.py`.
  - Routing: `kind_match`, `routing_safe` (no under-routing to a cheaper writer),
    `needs_web_match`, `symbols_match`, `treasury_match`.
  - Reports (`full` only): `completed`, `numbers_grounded` (figures in the report must round
    from a market-data value; skipped for web answers), `citations_valid`, `total_tokens`.
  - `judge.py`: optional LLM judge on a local model. A small judge is noisy; read it as a trend.
- `run_research.py`: CLI; `fixtures.py`: offline market data.
- `record_fixture.py`: records one real Anthropic run (raw API responses, encrypted fields
  redacted) to `tests/fixtures/langchain/anthropic_web.json` for the replay test. Costs a few
  cents; review the file before committing.

## LangSmith

Set `LANGSMITH_API_KEY` (and `LANGSMITH_TRACING=true` to also trace the worker) in
`backend/.env`. The dataset is `portfolio-research`; experiments are named
`<mode>-<label>-…` and carry git SHA, tiers and local model as metadata, so you can compare
runs in the LangSmith UI. Cloud sessions need `api.smith.langchain.com` on the network
allowlist.

## Baseline (2026-10-15, rules only, 40 examples)

| kind_match | routing_safe | needs_web_match | symbols_match | treasury_match |
|---|---|---|---|---|
| 0.925 | 0.975 | 0.95 | 0.85 | 0.975 |

Known misses: `P/E` yields tickers `E`/`P`; `T-bill` yields `T` (AT&T); lowercase tickers
and company names ("Apple") are not recognized, so the question falls back to news or clarify;
"today" forces web search on a T-bill lookup; a "10-year" follow-up loses the Treasury flag.
Re-run with a local classifier and with `full` before changing the orchestrator.
