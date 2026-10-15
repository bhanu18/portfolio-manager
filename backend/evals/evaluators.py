"""Research evaluators. Pure functions, usable with `langsmith.aevaluate` or the local runner.

Each takes `outputs` (what the target returned) and `reference_outputs` (the dataset label)
and returns `{"key", "score", "comment"}`. A `None` score means "not applicable here" and
is left out of averages.
"""

import json
import re
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from service.research.orchestrator import KIND_RANK
from service.research.providers import safe_url

Result = dict[str, Any]
Evaluator = Callable[..., Result | Awaitable[Result]]


def result(key: str, score: float | None, comment: str = "") -> Result:
    return {"key": key, "score": score, "comment": comment}


def profile(outputs: dict[str, Any]) -> dict[str, Any] | None:
    value = outputs.get("profile")
    return value if isinstance(value, dict) else None


# ---------------------------------------------------------------- routing


def kind_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> Result:
    got = profile(outputs)
    if got is None:
        return result("kind_match", None, "no routing decision (explicit provider or error)")
    expected = reference_outputs["kind"]
    return result("kind_match", float(got["kind"] == expected), f"{got['kind']} vs {expected}")


def routing_safe(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> Result:
    """Under-routing (a cheaper writer than the task needs) hurts quality; over-routing only costs."""
    got = profile(outputs)
    if got is None:
        return result("routing_safe", None, "no routing decision")
    ok = KIND_RANK[got["kind"]] >= KIND_RANK[reference_outputs["kind"]]
    return result("routing_safe", float(ok), "" if ok else f"under-routed to {got['kind']}")


def needs_web_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> Result:
    got = profile(outputs)
    if got is None:
        return result("needs_web_match", None, "no routing decision")
    expected = reference_outputs["needs_web"]
    return result("needs_web_match", float(got["needs_web"] == expected), f"expected {expected}")


def symbols_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> Result:
    got = profile(outputs)
    if got is None:
        return result("symbols_match", None, "no routing decision")
    found, expected = set(got["symbols"]), set(reference_outputs["symbols"])
    comment = ""
    if found != expected:
        comment = f"missing {sorted(expected - found)}, extra {sorted(found - expected)}"
    return result("symbols_match", float(found == expected), comment)


def treasury_match(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> Result:
    got = profile(outputs)
    if got is None:
        return result("treasury_match", None, "no routing decision")
    expected = reference_outputs["treasury"]
    return result("treasury_match", float(got["treasury"] == expected), f"expected {expected}")


ROUTING: list[Evaluator] = [
    kind_match,
    routing_safe,
    needs_web_match,
    symbols_match,
    treasury_match,
]

# ---------------------------------------------------------------- reports

# Numbers worth checking: decimals, percentages or dollar amounts (not "3 backtests", "MA50").
NUMBER = re.compile(r"(\$)?(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+\.\d+|-?\d+)(%)?")
YEAR = re.compile(r"^(19|20)\d\d$")


def report_numbers(report: str, prompt: str = "") -> list[tuple[float, int, str]]:
    """(value, decimals, text) for figures a report states, skipping ones the user wrote."""
    asked = {match.group(0) for match in NUMBER.finditer(prompt)}
    found: list[tuple[float, int, str]] = []
    for match in NUMBER.finditer(report):
        dollar, digits, percent = match.groups()
        text = match.group(0)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        start = match.start()
        # Part of a date (2026-10-14), a ticker/indicator (MA50) or a word (10-K): not a figure.
        if start and (report[start - 1].isalpha() or report[start - 1] in "-/"):
            continue
        if report[match.end() : match.end() + 1] in ("-", "/") or text in asked:
            continue
        if not (dollar or percent or decimals) or YEAR.match(digits):
            continue
        found.append((float(digits.replace(",", "")), decimals, text))
    return found


def numeric_leaves(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from numeric_leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from numeric_leaves(item)


def grounded(value: float, decimals: int, evidence: list[float]) -> bool:
    """True if some evidence value, as-is or as a percent, rounds to the stated figure."""
    tolerance = 10**-decimals
    for source in evidence:
        for candidate in (source, source * 100, source / 1e9, source / 1e12):
            if abs(abs(value) - abs(round(candidate, decimals))) <= tolerance:
                return True
    return False


def numbers_grounded(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> Result:
    """Share of stated figures traceable to fetched market data. Web-sourced answers are skipped
    because their numbers come from pages, not snapshots."""
    report = outputs.get("report") or ""
    if not report or reference_outputs.get("needs_web"):
        return result("numbers_grounded", None, "skipped: no report or web-sourced answer")
    snapshots = [item["snapshot"] for item in outputs.get("evidence", []) if item.get("snapshot")]
    if not snapshots:
        return result("numbers_grounded", None, "no market data evidence")
    evidence = list(numeric_leaves(snapshots))
    figures = report_numbers(report, inputs.get("prompt", ""))
    if not figures:
        return result("numbers_grounded", None, "report states no figures")
    missing = [text for value, decimals, text in figures if not grounded(value, decimals, evidence)]
    score = 1 - len(missing) / len(figures)
    return result(
        "numbers_grounded", round(score, 3), f"ungrounded: {missing[:10]}" if missing else ""
    )


def citations_valid(outputs: dict[str, Any]) -> Result:
    report = outputs.get("report") or ""
    citations = outputs.get("citations") or []
    if not citations:
        return result("citations_valid", None, "no citations")
    bad = []
    for citation in citations:
        start, end = citation.get("start_index"), citation.get("end_index")
        span_ok = (start is None and end is None) or (
            isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(report)
        )
        if not (safe_url(citation.get("url", "")) and span_ok):
            bad.append(citation.get("url", "?"))
    return result(
        "citations_valid", 1 - len(bad) / len(citations), f"invalid: {bad[:5]}" if bad else ""
    )


def completed(outputs: dict[str, Any]) -> Result:
    error = outputs.get("error")
    ok = bool((outputs.get("report") or "").strip()) and not error
    return result("completed", float(ok), error or "")


def total_tokens(outputs: dict[str, Any]) -> Result:
    """A metric, not pass/fail: lower is cheaper for the same scores."""
    steps = outputs.get("steps") or []
    tokens = sum(int(s.get("input_tokens") or 0) + int(s.get("output_tokens") or 0) for s in steps)
    return result("total_tokens", float(tokens), json.dumps(outputs.get("writer") or {}))


REPORT: list[Evaluator] = [completed, numbers_grounded, citations_valid, total_tokens]
