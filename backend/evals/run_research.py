"""Evaluate research routing and reports.

    cd backend
    venv/bin/python -m evals.run_research routing --rules-only   # free: regex router only
    venv/bin/python -m evals.run_research routing                # + local classifier, if set
    venv/bin/python -m evals.run_research full --market offline  # real models, fixed data
    venv/bin/python -m evals.run_research full --market live --provider auto --limit 5

With LANGSMITH_API_KEY set, the dataset is synced to LangSmith and each run is an experiment
there (compare runs side by side). Without it, or with --local, results print here and are
saved to evals/results/. `full` calls paid providers: start with --limit.
"""

import argparse
import asyncio
import inspect
import json
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from langsmith import Client, aevaluate

from core.config import settings
from evals.evaluators import REPORT, ROUTING, Evaluator
from evals.fixtures import offline_market_data
from evals.judge import make_judge
from service.research.agent import ResearchFailure
from service.research.configuration import model_for_provider, provider_enabled
from service.research.orchestrator import (
    FailoverResearchAgent,
    ResearchOrchestrator,
    heuristic_profile,
)
from service.research.tracing import configure_tracing, flush_traces, langsmith_client

HERE = Path(__file__).parent
DATASET_FILE = HERE / "datasets" / "research.jsonl"
DATASET_NAME = "portfolio-research"
RESULTS = HERE / "results"
Target = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def load_rows(only: set[str] | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in DATASET_FILE.read_text().splitlines() if line.strip()]
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit(f"Duplicate ids in {DATASET_FILE.name}")
    if only:
        rows = [row for row in rows if row["id"] in only]
    return rows[:limit] if limit else rows


async def no_progress(**_: Any) -> None:
    """Evals have no database run to save progress to."""


def previous_question(history: list[dict[str, str]]) -> str:
    return next((item["content"] for item in reversed(history) if item["role"] == "user"), "")


def routing_target(rules_only: bool) -> Target:
    async def route(inputs: dict[str, Any]) -> dict[str, Any]:
        if rules_only:
            profile = heuristic_profile(inputs["prompt"], previous_question(inputs["history"]))
            return {"profile": profile.model_dump(), "steps": []}
        orchestrator = ResearchOrchestrator(no_progress)
        profile = await orchestrator.classify(inputs["prompt"], inputs["history"])
        return {"profile": profile.model_dump(), "steps": orchestrator.steps}

    return route


def full_target(provider: str) -> Target:
    async def research(inputs: dict[str, Any]) -> dict[str, Any]:
        agent = (
            ResearchOrchestrator(no_progress)
            if provider == "auto"
            else FailoverResearchAgent(
                no_progress, provider=provider, model=model_for_provider(provider)
            )
        )
        report, error = None, None
        try:
            async with asyncio.timeout(settings.RESEARCH_TIMEOUT_SECONDS):
                report = await agent.run(inputs["prompt"], inputs["history"])
        except TimeoutError:
            error = "timeout"
        except ResearchFailure as failure:
            error = str(failure)
        writers = [step for step in agent.steps if step["role"] == "writer"]
        return {
            "report": report,
            "error": error,
            "profile": agent.profile.model_dump() if agent.profile else None,
            "model": agent.model,
            "writer": {k: writers[-1][k] for k in ("provider", "model")} if writers else None,
            "steps": agent.steps,
            "evidence": agent.evidence,
            "citations": agent.citations,
        }

    return research


async def score(evaluator: Evaluator, row: dict[str, Any], outputs: dict[str, Any]) -> Any:
    """Call an evaluator with the arguments it names, like LangSmith does."""
    available = {"inputs": row["inputs"], "outputs": outputs, "reference_outputs": row["outputs"]}
    wanted = inspect.signature(evaluator).parameters
    value = evaluator(**{name: available[name] for name in wanted})
    return await value if inspect.isawaitable(value) else value


async def run_local(
    rows: list[dict[str, Any]], target: Target, evaluators: list[Evaluator], concurrency: int
) -> list[dict[str, Any]]:
    limit = asyncio.Semaphore(concurrency)

    async def one(row: dict[str, Any]) -> dict[str, Any]:
        async with limit:
            started = time.monotonic()
            outputs = await target(row["inputs"])
            seconds = round(time.monotonic() - started, 2)
            results = [await score(evaluator, row, outputs) for evaluator in evaluators]
            return {"id": row["id"], "seconds": seconds, "outputs": outputs, "results": results}

    return list(await asyncio.gather(*(one(row) for row in rows)))


def sync_dataset(client: Client, rows: list[dict[str, Any]]) -> None:
    """Make the LangSmith dataset match the JSONL file (create/update by example id)."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        dataset = client.create_dataset(
            DATASET_NAME,
            description=f"Research routing labels; source: backend/evals/{DATASET_FILE.name}",
        )
    existing = {
        (example.metadata or {}).get("id"): example
        for example in client.list_examples(dataset_id=dataset.id)
    }
    new = []
    for row in rows:
        example = existing.get(row["id"])
        if example is None:
            new.append(
                {"inputs": row["inputs"], "outputs": row["outputs"], "metadata": {"id": row["id"]}}
            )
        elif example.inputs != row["inputs"] or example.outputs != row["outputs"]:
            client.update_example(example.id, inputs=row["inputs"], outputs=row["outputs"])
    if new:
        client.create_examples(dataset_id=dataset.id, examples=new)
    stale = set(existing) - {row["id"] for row in load_rows()}
    if stale:
        print(
            f"Note: LangSmith examples not in the JSONL file (left as is): {sorted(map(str, stale))}"
        )


async def run_langsmith(
    rows: list[dict[str, Any]],
    target: Target,
    evaluators: list[Evaluator],
    concurrency: int,
    prefix: str,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    client = langsmith_client()
    sync_dataset(client, load_rows())
    wanted = {row["id"] for row in rows}
    examples = [
        example
        for example in client.list_examples(dataset_name=DATASET_NAME)
        if (example.metadata or {}).get("id") in wanted
    ]
    experiment = await aevaluate(
        target,
        data=examples,
        # LangSmith accepts async evaluators at runtime; its stubs only list sync ones.
        evaluators=evaluators,  # type: ignore[arg-type]
        experiment_prefix=prefix,
        metadata=metadata,
        max_concurrency=concurrency,
        client=client,
    )
    collected = []
    async for item in experiment:
        run, example = item["run"], item["example"]
        collected.append(
            {
                "id": (example.metadata or {}).get("id"),
                "seconds": round((run.end_time - run.start_time).total_seconds(), 2)
                if run.end_time
                else None,
                "outputs": run.outputs or {},
                "results": [
                    {"key": r.key, "score": r.score, "comment": r.comment}
                    for r in item["evaluation_results"]["results"]
                ],
            }
        )
    print(f"LangSmith experiment: {experiment.experiment_name}")
    return collected


def summarize(collected: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for item in collected:
        for result in item["results"]:
            entry = summary.setdefault(result["key"], {"scores": [], "failures": []})
            if result["score"] is None:
                continue
            entry["scores"].append(result["score"])
            if result["key"] != "total_tokens" and result["score"] < 1:
                entry["failures"].append(f"{item['id']}: {result['comment']}")
    for entry in summary.values():
        scores = entry.pop("scores")
        entry["n"] = len(scores)
        entry["mean"] = round(sum(scores) / len(scores), 3) if scores else None
    return summary


def print_summary(summary: dict[str, dict[str, Any]], show_failures: bool) -> None:
    width = max(map(len, summary), default=10)
    for key, entry in summary.items():
        mean = "n/a" if entry["mean"] is None else entry["mean"]
        print(f"{key:<{width}}  mean={mean}  n={entry['n']}")
        if show_failures:
            for failure in entry["failures"]:
                print(f"    {failure}")


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=["routing", "full"])
    parser.add_argument(
        "--rules-only", action="store_true", help="routing: skip the local classifier"
    )
    parser.add_argument(
        "--provider", default="auto", choices=["auto", "openai", "anthropic", "local"]
    )
    parser.add_argument("--market", default="offline", choices=["offline", "live"])
    parser.add_argument("--judge-model", help="full: grade reports with this local model")
    parser.add_argument("--only", help="comma-separated example ids")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--local", action="store_true", help="do not upload to LangSmith")
    parser.add_argument("--quiet", action="store_true", help="hide per-example failures")
    return parser.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = parse_args(argv)
    rows = load_rows(set(args.only.split(",")) if args.only else None, args.limit)
    if not rows:
        raise SystemExit("No examples selected.")
    configure_tracing()
    if args.mode == "routing":
        target, evaluators = routing_target(args.rules_only), list(ROUTING)
        label = (
            "rules"
            if args.rules_only or not settings.LOCAL_LLM_MODEL.strip()
            else settings.LOCAL_LLM_MODEL
        )
    else:
        if not provider_enabled(args.provider):
            raise SystemExit(
                f"Provider {args.provider!r} is not configured (API key or LOCAL_LLM_MODEL)."
            )
        target, evaluators = full_target(args.provider), [*ROUTING, *REPORT]
        if args.judge_model:
            evaluators.append(make_judge(args.judge_model))
        label = f"{args.provider}-{args.market}"
    metadata = {
        "mode": args.mode,
        "label": label,
        "git_sha": git_sha(),
        "local_model": settings.LOCAL_LLM_MODEL,
        "tier_cheap": settings.RESEARCH_TIER_CHEAP,
        "tier_strong": settings.RESEARCH_TIER_STRONG,
        "market": args.market if args.mode == "full" else None,
    }
    upload = bool(settings.LANGSMITH_API_KEY.strip()) and not args.local
    market = (
        offline_market_data() if args.mode == "full" and args.market == "offline" else nullcontext()
    )
    with market:
        if upload:
            collected = await run_langsmith(
                rows, target, evaluators, args.concurrency, f"{args.mode}-{label}", metadata
            )
        else:
            collected = await run_local(rows, target, evaluators, args.concurrency)
    flush_traces()
    summary = summarize(collected)
    print(f"{args.mode} · {label} · {len(rows)} examples")
    print_summary(summary, not args.quiet)
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.mode}-{label.replace(':', '_')}.json"
    path.write_text(
        json.dumps(
            {"metadata": metadata, "summary": summary, "examples": collected}, indent=2, default=str
        )
    )
    print(f"Saved {path.relative_to(HERE.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
