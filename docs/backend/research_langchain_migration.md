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

## PR 1 in detail: building blocks only, no behaviour change

**Status: built 2026-10-15.** Differences from the plan below:
- `thinking()` stays in `local_agent.py`, and `models.py` imports it. Moving it would load
  LangChain through the worker.
- `chat_model` raises `ProviderUnavailable` (1800 s) when a cloud key is missing, because the
  OpenAI client refuses to build without one.
- Local models also use `output_version="v1"`.
- The guard test also covers `main` (the API) and `langgraph`.

Nothing in the running app imports the new modules, so the worker, API and evals behave
exactly as before. Only new unit tests exercise them.

### 1. Dependencies
- In `backend/`: `uv pip install --python venv/bin/python langchain==1.4.6 langchain-openai==1.7.2 langchain-anthropic==1.7.6`.
- Then `uv pip freeze --python venv/bin/python` and add every new package to `requirements.txt`
  at its installed version, keeping the file sorted. Expect `langgraph*`, `openai`,
  `anthropic`, `tiktoken`, `jiter` and friends.
- Check it resolves from scratch: a fresh 3.12 venv plus `uv pip install --dry-run -r requirements-dev.txt`.
- Note the larger Docker image in the PR description.

### 2. `service/research/errors.py`: one failure table
- Move `ResearchFailure`, `ProviderUnavailable` and `CREDIT_HINTS` out of `agent.py`.
- Add `classify_failure(status: int | None, body: str, name, rejected=None) -> ResearchFailure`.
  It holds today's rules, unchanged:
  - `None` (unreachable): 60 s;
  - 402 or a credit hint: 1800 s;
  - 401/403: 1800 s;
  - 429: 60 s;
  - 5xx: 60 s;
  - anything else: a plain `ResearchFailure`.
- Rewrite `http_failure` as a thin wrapper around it. The old loops keep using it.
- Add `provider_failure(error: Exception, name) -> ResearchFailure` for the SDKs:
  - `openai.APIConnectionError` / `anthropic.APIConnectionError` (timeouts are subclasses):
    `classify_failure(None, ...)`;
  - `openai.APIStatusError` / `anthropic.APIStatusError`:
    `classify_failure(e.status_code, e.response.text[:2000].lower(), ...)`;
  - anything else is re-raised. Never hide a bug as a provider error.
- In `agent.py`, keep `from service.research.errors import ProviderUnavailable, ResearchFailure, http_failure`
  so the existing imports in the worker, orchestrator, tests and evals keep working.

### 3. `service/research/models.py`: model factory
`chat_model(provider: str, model: str, *, max_tokens: int) -> BaseChatModel`.

Shared settings: `max_retries=0` and `max_tokens`. Then per provider:

- **anthropic:** `ChatAnthropic(model=..., api_key=settings.ANTHROPIC_API_KEY, output_version="v1", default_request_timeout=90)`
- **openai:** `ChatOpenAI(model=..., api_key=settings.OPENAI_API_KEY, use_responses_api=True, output_version="v1", store=False, include=["web_search_call.action.sources", "reasoning.encrypted_content"], request_timeout=90)`.
  It's built but stays unused until there's a key.
- **local:** `ChatOpenAI(model=..., base_url=settings.LOCAL_LLM_BASE_URL, api_key=settings.LOCAL_LLM_API_KEY.strip() or "unused", use_responses_api=False, request_timeout=120, extra_body=thinking(settings.LOCAL_LLM_THINKING))`.
  - The `"unused"` placeholder is needed because the OpenAI client insists on a key; local
    servers ignore the header.
  - Move `thinking()` into this module and import it back into `local_agent.py`.
- Any other provider: `ValueError`.
- Take a `thinking` override argument so `local_json` can force it off in PR 3.

### 4. `service/research/tools.py`: market tools as LangChain tools
- **Refactor first** (behaviour-neutral): split `ResearchAgent.run_tool` into
  - JSON parsing of the arguments, which stays in `run_tool`;
  - `async def market_tool(self, name: str, args: dict[str, Any]) -> str`, which holds the
    checkpoint, the snapshot calls, `record_snapshot` and the exact error-JSON strings.

  The old loops keep calling `execute_tool`, so their tests must still pass untouched.
- `make_tools(agent: ResearchAgent) -> list[BaseTool]` defines three async `@tool` closures that
  each `return await agent.market_tool(name, {...})`:
  - `stock_snapshot(symbol: str)`
  - `investment_analysis(symbol: str)`
  - `treasury_snapshot(kind: Literal["curve", "bills"])`

  The description of each must be its `TOOLS` description verbatim; set it with
  `@tool(description=...)` or as the docstring. Return only those that `agent.tool_allowed(name)`
  permits.
- `web_search_tool(provider, remaining_uses) -> dict | None`:
  - openai: `{"type": "web_search"}`
  - anthropic: `{"type": "web_search_20250305", "name": "web_search", "max_uses": remaining_uses}`
  - local: `None`

  Callers check `tool_allowed("web_search")`.
- Note for PR 2: a `Literal` argument rejects bad values before our code runs. Inside
  `create_agent`, configure the tool node so a validation error returns our safe "Unsupported
  read-only tool or arguments" JSON, not LangChain's default message.

### 5. Tests (new files; nothing existing changes)
- **`tests/test_research_errors.py`.** Parametrize today's `test_http_failure_classification`
  table over three error sources:
  - `httpx.HTTPStatusError`;
  - `openai.APIStatusError(message, response=httpx2.Response(status, request=httpx2.Request("POST", "https://x"), text=body), body=None)`;
  - the same for `anthropic`.

  Add connection errors (expect a 60 s cooldown) and a plain `ValueError` (re-raised).
  **Gotcha:** the SDKs here use `httpx2`, not `httpx`, so build their responses with `httpx2`.
- **`tests/test_research_models.py`.** No network:
  - check the class, `max_retries == 0` and `output_version == "v1"` per provider;
  - check the local `base_url`, the `extra_body` thinking flag and the `"unused"` key fallback;
  - an unknown provider raises.
- **`tests/test_research_tools.py`.** Use a plain `ResearchAgent` with `stock_snapshot` and the
  others monkeypatched:
  - tool names and descriptions equal `TOOLS`;
  - `treasury_snapshot`'s schema has the `curve`/`bills` enum;
  - `allowed_tools={"stock_snapshot"}` yields one tool;
  - a call records evidence and returns exactly what `execute_tool` returns for the same input;
  - an upstream failure returns the same error JSON;
  - `web_search_tool` returns the right shape per provider.
- **Guard test:** `import service.research.worker` must not import `langchain`. Check that
  `"langchain_core"` is not in `sys.modules` after importing the worker in a subprocess. This
  proves PR 1 is inert.

### 6. Checks before pushing
- Run in `backend/`: `ruff check .`, `ruff format --check .`, `mypy`, `pytest` (expect
  196 + new tests passing).
- If mypy fails on LangChain types, add a narrow `[[tool.mypy.overrides]]` for that module only.
- Run `python -m evals.run_research routing --rules-only --local`. It must match the
  baseline exactly (kind 0.925, symbols 0.85…).
- Update CLAUDE.md (research section: new modules, the `httpx2` gotcha) and `context.md`'s
  source map.

PR title: `feat(research): LangChain building blocks (models, errors, tools)`. Description: no
behaviour change; nothing imports the new modules yet; Anthropic migration follows in PR 2.

## PR 2 in detail: Anthropic on LangChain

**Goal:** `AGENTS["anthropic"]` runs on LangChain, and so does Auto whenever it routes to
Anthropic. OpenAI and local stay on their httpx loops. Behaviour must match
`anthropic_agent.py` exactly, including errors, budgets, progress stages, citation markers and
the `steps` data.

**Before merging:** the step-0 Anthropic baseline exists (`full --market offline --provider anthropic`
and `--provider auto`, with `RESEARCH_TIER_CHEAP=anthropic:claude-haiku-5-5`).

### Verified facts this design relies on (langchain 1.4.6, langchain-anthropic 1.7.6, anthropic 1.14)

**Where things appear on the model's response (`AIMessage`):**
- `response_metadata["stop_reason"]` carries Anthropic's stop reason (`end_turn`, `tool_use`,
  `pause_turn`, `max_tokens`, `refusal`).
- `usage_metadata["input_tokens"]` already includes cache reads and writes, matching today's
  sum.

**How `content_blocks` look with `output_version="v1"`:**
- web search call: `{"type": "server_tool_call", "name": "web_search", "id": …}`
- web search results: `{"type": "server_tool_result", "status": "success", "output": [{"url", "title", …}]}`
- web search error (e.g. `max_uses_exceeded`): `status: "error"` and `output` holding a dict
- text: `{"type": "text", "text": …, "annotations": [{"type": "citation", "url", "title", "cited_text"}]}`.
  Anthropic citations have **no character spans**.
- our tools: `{"type": "tool_call", …}`, also listed in `message.tool_calls`

**How the agent loop behaves:**
- `create_agent` ends the loop when a message has no `tool_calls`. A `pause_turn` response with
  only a server-side web search would therefore end the run early.
- `ToolCallLimitMiddleware` counts only our tools, not web searches. Today's budget counts both,
  so don't use it.
- When a tool's arguments fail validation, `ToolNode` returns LangChain's own error text by
  default.
- `ModelRequest.override(tools=..., model_settings=...)` changes the tools and settings for a
  single model call. `model_settings` is passed to `bind()`, so
  `{"max_tokens": n}` works per call.

### 1. `service/research/langchain_agent.py` (new): `LangChainResearchAgent(ResearchAgent)`
- Constructor `(progress, *, provider, model=None, **options)`. The default model comes from
  `model_for_provider(provider)`.
- `run(prompt, history)` steps:
  1. Trim the history exactly as `anthropic_agent.py` does.
  2. Convert it to `HumanMessage` / `AIMessage`.
  3. Build `create_agent(model=chat_model(provider, self.model, max_tokens=4000), tools=make_tools(self), system_prompt=self.instructions(), middleware=[BudgetMiddleware(self, provider), ModelCallLimitMiddleware(run_limit=settings.RESEARCH_MAX_MODEL_TURNS, exit_behavior="error")])`.
     Web search is not in `tools`; the middleware adds it per call (see 2).
  4. Run `await agent.ainvoke({"messages": messages})`, and translate errors:
     - `openai.*` / `anthropic.*` errors → `provider_failure(e, "Anthropic", rejected="Anthropic rejected the request. Check the model and web-search access in your Anthropic account.")`.
       Keep today's exact wording.
     - `ModelCallLimitExceededError` → today's "research turn limit was reached" `ResearchFailure`.
  5. Read the final `AIMessage`; this is step 4 below.

### 2. `BudgetMiddleware(AgentMiddleware)`: reproduces today's loop rules
**`awrap_model_call(request, handler)`, before each call:**
- Compute the remaining tool calls and the remaining output tokens.
- Fewer than 500 output tokens left: raise the "response token budget" `ResearchFailure`.
- Rebuild the tools for this call:
  - our allowed tools, plus `web_search_tool("anthropic", remaining)` if `tool_allowed("web_search")`;
  - no tools at all when `remaining <= 0`.
- Byte-bound the input exactly as today (messages + system + tools as JSON). If
  `input_tokens + bound` exceeds the limit, raise the "context budget" failure.
- `model_turns += 1`, then `await agent.checkpoint("Searching sources and drafting analysis")`.
- `response = await handler(request.override(tools=tools, model_settings={"max_tokens": min(4000, remaining_output)}))`.

**After each call:**
- Add `usage_metadata` to the counters. If usage is missing, fall back to the byte bound and
  4000, as today.
- Count each new `server_tool_call` id and `tool_call` id once (keep a `seen` set) into
  `tool_calls`.
- Call `add_source` for every `server_tool_result` output item.
- `await agent.checkpoint("Verifying sources")`.
- If `tool_calls > RESEARCH_MAX_TOOL_CALLS`: raise the "tool-call budget" failure.
- If any `server_tool_result` has `status == "error"`: raise the "web search failed or reached
  its search limit" failure.
- If `stop_reason` is not one of `end_turn`, `tool_use`, `pause_turn`: raise the "incomplete or
  could not answer" failure. This covers `max_tokens` and `refusal`.

**`aafter_model(state, runtime)` with `@hook_config(can_jump_to=["model"])`:**
- When the last message's `stop_reason == "pause_turn"`:
  - if the tool budget is exhausted, raise the "tool-call budget was reached before Anthropic
    finished" failure;
  - otherwise return `{"jump_to": "model"}` to continue. The paused assistant message stays in
    state, which is exactly what Anthropic expects for `pause_turn`.

**`awrap_tool_call(request, handler)`:**
- Unknown tool or failed argument validation (the result is a `ToolMessage` with
  `status == "error"`): replace its content with today's
  `{"error": "Unsupported read-only tool or arguments"}` JSON and keep the `tool_call_id`.
- Valid calls already go through `market_tool`, which does the progress stage and evidence.

### 3. Final message → report and citations (keep today's output exactly)
- Use the **last** `AIMessage` only. Earlier turns are tool-planning narration; today's code
  resets `report` and `citations` on every `tool_use` turn.
- Reject it if it still has `tool_calls`, its stop reason isn't `end_turn`, or it has no text:
  raise the "Anthropic returned no complete report" failure.
- Walk its `text` blocks in order:
  - join them with `"\n\n"`;
  - for each `citation` annotation with a `safe_url`, call `add_source(title, url)` and append
    `" [Source N]"` right after that block's text;
  - record `Citation(url, title, start_index, end_index)` covering the marker, exactly as today.

  Put this in a pure function `anthropic_report(message) -> (report, citations)` so it can be
  tested on its own.
- No evidence: prefix "No external evidence was retrieved for this response." Anthropic's spans
  sit on markers built after the prefix is known, so build the prefix first, or shift the spans
  the way `agent.py` does.

### 4. Wiring
- In `orchestrator.py`, set `AGENTS["anthropic"] = partial(LangChainResearchAgent, provider="anthropic")`.
  Leave `"openai"` and `"local"` as they are.
- Keep the class name visible to callers that check `type(...)`: there are none today, but
  grep first.
- Delete the guard test `test_running_app_does_not_load_langchain_yet`. It is now meant to fail.
- Leave `anthropic_agent.py` in place until PR 4 (cleanup). It is no longer referenced.

### 5. Tracing (Phase 1 code)
- In `run_agent`, change the span from `run_type="llm"` to `"chain"`. Keep the name, metadata and
  outputs. LangChain now logs the real LLM runs underneath, so leaving it as `llm` would count
  tokens and cost twice. Also remove `usage_metadata` from that span's outputs; put it in
  metadata instead if you still want it visible.
- The `execute_tool` `traceable` wrapper stays, because the httpx loops still use it.
  LangChain's tool runs don't go through `execute_tool`, so nothing is traced twice.
- Update `test_auto_run_is_traced_as_one_tree`: the writer is now `"chain"`.

### 6. Real response fixture (needs your key, about 2 cents)
- Add `evals/record_fixture.py`: `python -m evals.record_fixture anthropic "Latest NVDA earnings news and current price"`.
- It runs `LangChainResearchAgent` once, with the market tools on offline fixtures. It saves every
  `AIMessage` from the run (`message.model_dump()`, with `encrypted_content` / `encrypted_index`
  removed) to `tests/fixtures/langchain/anthropic_web.json`.
- Check the file before committing; it must contain no key and no account id.
- Until it exists, the tests use a hand-built fixture with the shapes verified above. Once
  recorded, the real file is added and the same tests must pass on it.

### 7. Tests: `tests/test_langchain_agent.py`
Use a scripted fake model: subclass `GenericFakeChatModel`, have `bind_tools` return `self`, and
record each call's tools and `max_tokens`. The `AIMessage`s it yields carry `content_blocks` and
`response_metadata["stop_reason"]`.

Cover:
- **Happy path:** tool call → final answer. Check the report text, the `[Source N]` markers and
  their spans, evidence, counters, and that the progress stage sequence equals today's.
- **`pause_turn`:** a server search, then `pause_turn`, then `end_turn` continues instead of
  ending.
- **Budgets:**
  - output tokens under 500;
  - the context bound;
  - the tool-call budget counting server and client calls together;
  - the turn limit;
  - web search `max_uses` shrinking as the budget is used.
- **Failures:** a web search `status == "error"`, `max_tokens` and `refusal`, and a final message
  without text each give the right `ResearchFailure`.
- **Bad tool calls:** an unknown tool name and bad arguments return the safe JSON, and the run
  continues.
- **Provider errors:** an SDK `APIStatusError` 400 with "credit balance" becomes
  `ProviderUnavailable` with an 1800 s cooldown. Build it with `httpx2`.
- **No-evidence prefix:** citation spans still point at their markers.
- **Recorded fixture:** replay the saved messages through the fake model and get the same
  report and citations. This is the citation parity check.

Also:
- Port `tests/test_anthropic_research.py` cases that still apply. Run them against the new
  class through the fake model, or delete them where the new tests cover them.
- `test_orchestrator.py` needs no change (it swaps `AGENTS`). `test_research_api.py` must
  still pass.

### 8. Checks and parity gate
- Run in `backend/`: `ruff check .`, `ruff format --check .`, `mypy`, `pytest`.
- `routing --rules-only --local`: identical to the baseline.
- With your key, run `full --market offline --provider anthropic` and then `--provider auto`.
  Compare against step 0 with the parity table in step 9 above.
- Manual check: run the worker and the frontend, ask one news question on Anthropic, and confirm
  the steps panel, the sources list and the `[Source N]` highlights.

PR title: `feat(research): run Anthropic research on LangChain`.
