# Research: LangChain migration (Phase 3)

Status: planned 2026-10-15, not started. Phase 4 (Auto as a LangGraph graph) comes after.

**Goal:** replace the three hand-written provider loops (`agent.py`, `anthropic_agent.py`,
`local_agent.py`) with LangChain chat models, `@tool` functions and `create_agent`. The
orchestrator, failover, cooldowns, the `steps` shape and the frontend stay as they are.

**Done when:** the evals score at least as well as the pre-migration baseline (step 0) and the
code is smaller.

Versions checked 2026-10-15 (install cleanly with the current pins): `langchain==1.4.6`,
`langchain-core==1.6.10`, `langchain-openai==1.7.2`, `langchain-anthropic==1.7.6`,
`langgraph==1.2.15` (comes with `langchain`).

## Adjusted plan (2026-10-15): Anthropic key only, no local model yet

Only Anthropic can be evaluated, so the plan changes:
- **Step 0:** run the baseline for `--provider anthropic` and `--provider auto` only. With just
  Anthropic, Auto routes with the regex rules and every tier falls back to Anthropic. To keep
  Auto's cheap/strong split meaningful, set `RESEARCH_TIER_CHEAP=anthropic:claude-haiku-5-5`
  before the baseline and keep it identical for the parity run. The routing baseline is the
  rules-only run already recorded.
- **Order:** migrate **Anthropic first** (the only provider that can be eval-gated), then local.
- **Local:** migrate it and cover it with fake-model unit tests. Run the parity eval once Ollama
  is set up (it's free).
- **OpenAI: keep the old httpx adapter** (`agent.py` loop) in `AGENTS` until a key exists to
  record a real fixture and run parity. Don't ship an unverified citation parser. Step 10
  cleanup then skips OpenAI's loop.
- Run evals on your machine (where the key lives), not in the cloud session.

## Step 0: paid baseline (before touching code)

Needs API keys and a local model. Run from `backend/`, ideally with `LANGSMITH_API_KEY` set so
each run is saved as an experiment:

```
venv/bin/python -m evals.run_research routing                      # with LOCAL_LLM_MODEL set
venv/bin/python -m evals.run_research full --market offline --provider local
venv/bin/python -m evals.run_research full --market offline --provider openai
venv/bin/python -m evals.run_research full --market offline --provider anthropic
venv/bin/python -m evals.run_research full --market offline --provider auto
```

Write the experiment names into `evals/README.md`. Every later step compares against them.
To check the plumbing cheaply first, add `--limit 5`.

## Step 1: dependencies

- Add the three packages above to `requirements.txt`, install, then pin every new transitive
  package at the version that was installed (same pattern as `langsmith`).
- Do not add `langchain-ollama`. Local models keep using the OpenAI-compatible endpoint through
  `ChatOpenAI(base_url=...)`, so LM Studio, vLLM and mlx keep working.
- Run `mypy`. If LangChain's types cause errors, add a narrow `[[tool.mypy.overrides]]` in
  `pyproject.toml`; never a blanket `ignore_errors`.

## Step 2: model factory: `service/research/models.py` (new)

`chat_model(provider, model, *, max_tokens) -> BaseChatModel`:

| provider | class and key settings |
|---|---|
| openai | `ChatOpenAI(model, api_key=OPENAI_API_KEY, use_responses_api=True, output_version="v1", store=False, include=["web_search_call.action.sources", "reasoning.encrypted_content"], max_tokens=…, max_retries=0, request_timeout=90)` |
| anthropic | `ChatAnthropic(model, api_key=ANTHROPIC_API_KEY, output_version="v1", max_tokens=…, max_retries=0, default_request_timeout=90)` |
| local | `ChatOpenAI(model, base_url=LOCAL_LLM_BASE_URL, api_key=LOCAL_LLM_API_KEY, use_responses_api=False, max_tokens=…, max_retries=0, request_timeout=120)`, with the thinking flag from `thinking()` passed in the request body |

Two settings matter:
- **`max_retries=0` everywhere.** Our failover and cooldowns decide what happens after an
  error. The SDKs' default retries would bill twice and hide 429s from the cooldown logic.
- **`output_version="v1"`.** Text, citations and web-search results then come back in the same
  standard shape (`message.content_blocks`) for both providers. Citation extraction is built on
  this (step 5).

## Step 3: errors: `service/research/errors.py` (new)

- Move `ResearchFailure`, `ProviderUnavailable` and `CREDIT_HINTS` here.
- Add `provider_failure(error, name) -> ResearchFailure` that applies today's `http_failure`
  rules to the SDK exceptions:
  - `openai.APIConnectionError` / `APITimeoutError` and the matching `anthropic.*` errors:
    unreachable, 60 s cooldown.
  - `openai.APIStatusError` / `anthropic.APIStatusError`: read `status_code` and the response
    body:
    - 402, or any credit hint in the body: 1800 s;
    - 401/403: 1800 s;
    - 429: 60 s, but `insufficient_quota` is a credit error;
    - 5xx: 60 s;
    - anything else: a plain `ResearchFailure`.
- Re-export the two exception classes from `agent.py` for now so imports don't break.
- Port `test_http_failure_classification` to the new function, building the SDK exceptions
  with fake `httpx.Response` objects. Same table of cases, same expected cooldowns.

## Step 4: tools: `service/research/tools.py` (new)

`make_tools(agent) -> list[BaseTool]` builds three async `@tool` functions (`stock_snapshot`,
`investment_analysis`, `treasury_snapshot`). They are closures over the agent, so each call can:
- run `await agent.checkpoint(stage)` with the same stage labels as today;
- call `agent.record_snapshot(snapshot)` and return its bounded JSON;
- on failure, return the existing error JSON strings unchanged. Those strings tell the model
  "do not invent results", which the `numbers_grounded` eval checks.

Rules:
- Keep the descriptions word for word from `TOOLS` in `agent.py`.
- Restrict `treasury_snapshot.kind` to `Literal["curve", "bills"]` so the schema keeps the enum.
- Web search stays provider-native and is passed as a plain dict next to the `@tool`s:
  - OpenAI: `{"type": "web_search"}`
  - Anthropic: `{"type": "web_search_20250305", "name": "web_search", "max_uses": n}`
  - Local: none (`NO_WEB` instructions stay)
- Filter all of them through `agent.tool_allowed(name)`, because the orchestrator narrows tools
  per step.

## Step 5: one agent class replaces three

`LangChainResearchAgent(ResearchAgent)`, with `provider` as a constructor argument. It keeps the
`run(prompt, history) -> str` signature and all the counters (`input_tokens`, `output_tokens`,
`tool_calls`, `model_turns`, `evidence`, `citations`). Inside `run`:

1. **History.** Trim it exactly as today (whole turns, byte bound) and convert it to LangChain
   messages.
2. **Agent.** `create_agent(model, tools, system_prompt=self.instructions(), middleware=[...])`:
   - `ModelCallLimitMiddleware(run_limit=RESEARCH_MAX_MODEL_TURNS, exit_behavior="error")`,
     with its error mapped to today's "turn limit" `ResearchFailure` message.
   - `ToolCallLimitMiddleware(run_limit=RESEARCH_MAX_TOOL_CALLS)` for our own tools.
   - `BudgetMiddleware(agent)` (ours), using `awrap_model_call` and `awrap_tool_call`.
3. **`BudgetMiddleware`, before each model call:**
   - raise the "output budget" failure if fewer than 500 output tokens remain;
   - raise the "context budget" failure if the input bound would be exceeded;
   - `checkpoint("Searching sources and drafting analysis")`.
4. **`BudgetMiddleware`, after each model call:**
   - add `usage_metadata` to the counters;
   - add 1 to `model_turns`;
   - count server-side web searches into `tool_calls`; the limit middleware only sees our own
     tools;
   - raise on a refusal or an incomplete response;
   - `checkpoint("Verifying sources")`.
5. **`BudgetMiddleware`, around each tool call:** add to `tool_calls` and enforce the remaining
   budget.
6. **Invoke.** Call `await agent.ainvoke({"messages": ...})` inside `try`, and turn
   `openai.*` / `anthropic.*` errors into `provider_failure(...)`.
7. **Final message.**
   - The report is the last `AIMessage`'s `.text`. For local models, apply `strip_thinking`.
   - Citations come from its `content_blocks`: text blocks carry `annotations` of type
     `citation` (`url`, `title`, `start_index`, `end_index`). Offset the spans by the length of
     the earlier text blocks plus 2, as today.
   - Web-search result blocks feed `add_source`.
   - Keep the "No external evidence…" prefix and its span shift.

Then in `orchestrator.py`, set
`AGENTS = {p: partial(LangChainResearchAgent, provider=p) for p in ("openai", "anthropic", "local")}`.
That's the only orchestrator change; `test_orchestrator.py` keeps working because it swaps
`AGENTS`.

**Biggest risk: citations.** Before writing the extraction code, call each provider once with
a web-search question and save the raw `AIMessage` to `tests/fixtures/langchain/openai_web.json`
and `anthropic_web.json`, trimmed of anything sensitive. Build and test the extraction against
those files. Don't assume the two providers' blocks match.

## Step 6: `local_json` on LangChain

- Reimplement it with `chat_model("local", ...)` and `.bind(response_format={"type": "json_object"})`,
  `temperature=0`, thinking off.
- Keep the signature, the `(data, input_tokens, output_tokens)` return and "never raises".
  Trade imports (`service/imports/mapping.py`) also call it.
- Keep the fallback that cuts the JSON object out of prose or code fences.

## Step 7: tracing adjustments (Phase 1 code)

LangChain traces its own model and tool calls into the current LangSmith trace, so:
- In `run_agent`, change the span from `run_type="llm"` to `"chain"`. Keep the name, metadata
  and outputs. If it stays `llm`, the real LLM runs nest inside it and LangSmith counts tokens
  and cost twice.
- Remove the `traceable` wrapper from `execute_tool`; LangChain traces tools.
- Remove `@traceable` from `local_json`.
- Update `test_auto_run_is_traced_as_one_tree`: the writer step's run type becomes `"chain"`.

## Step 8: tests

- **Delete** the httpx-payload tests together with the code they cover:
  - `test_research_agent.py` (loop parts);
  - `test_anthropic_research.py`;
  - `test_local_agent.py` (loop parts).
- **New `tests/test_langchain_agent.py`**, using a scripted fake model. `GenericFakeChatModel`
  doesn't implement `bind_tools`, so subclass it and return `self` from `bind_tools`. Cover:
  - a tool call followed by a final answer: evidence recorded, counters right, progress events
    sent;
  - each budget failure: output, context, turns, tool calls;
  - an unknown tool and bad arguments return the safe error JSON;
  - a refusal or an incomplete response raises `ResearchFailure`;
  - citation offsets across several text blocks;
  - the no-evidence prefix shifts the spans;
  - citation extraction against the two recorded fixture files.
- **Keep** `test_orchestrator.py` and `test_evals.py` as they are (only the trace test changes).
- **Keep** the `local_json` tests, rewritten for the fake model: JSON parse, fenced JSON,
  never raises.
- Full suite on MariaDB: `ruff check .`, `ruff format --check .`, `mypy`, `pytest`.

## Step 9: parity gate

Re-run every command from step 0 and compare in LangSmith or `evals/results/`:

| metric | rule |
|---|---|
| routing (all five) | identical to the baseline (classify only changed in step 6) |
| `completed` | at least the baseline |
| `numbers_grounded` | at least baseline − 0.02 |
| `citations_valid` | 1.0 wherever citations exist |
| `total_tokens` | within +10% per provider |

Then one manual check per provider: run the worker and the frontend, ask one lookup and one
news question, and confirm the steps panel, sources list and citation highlights look as they
did before.

## Step 10: cleanup and docs

- Delete `anthropic_agent.py` and the HTTP loop parts of `agent.py` and `local_agent.py`.
  Keep `ResearchAgent`'s shared state and helpers, plus `NO_WEB`, `thinking()` and
  `strip_thinking()`.
- Update CLAUDE.md (research section), `context.md` and `evals/README.md` (new baseline).

## Suggested PRs

1. **Steps 1–4:** dependencies, factory, errors, tools. Nothing calls them yet, so no behaviour
   changes.
2. **Steps 5–8, local provider only:** switch `AGENTS["local"]` first. It's free to eval.
3. **Switch OpenAI, then Anthropic**, each with its recorded fixture and a parity run.
4. **Step 10:** cleanup.
