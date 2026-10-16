"""Baseline runner: policy text + scenario description -> Nemotron answers directly.

For each labeled scenario the baseline:
  1. Concatenates all NovaCart policy documents into a single context.
  2. Describes the customer journey in plain English.
  3. Asks the model: "Should this refund/replacement request be ALLOWED or DENIED?"
  4. Runs the prompt N_RUNS times (default 3) to measure variance / consistency.
  5. Records latency and token cost per call.

The baseline NEVER runs the deterministic engine.  Outcome is parsed from the
model's response by looking for the first occurrence of "ALLOW" or "DENY"
(case-insensitive); if neither appears the run is recorded as "UNKNOWN".

All results are returned as BaselineResult objects and optionally serialised
to JSON by the caller.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sys
# Allow imports from backend/policyforge when running from repo root
_BACKEND = Path(__file__).parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from policyforge.llm import LLMClient, LLMCallRecord
from benchmark.schema import LabeledScenario

# ---------------------------------------------------------------------------
# Policy context (loaded once)
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data" / "novacart"

POLICY_CONTEXT: str = "\n\n".join(
    (_DATA_DIR / fn).read_text(encoding="utf-8")
    for fn in ("refund_policy.md", "replacement_policy.md", "support_sop.md")
    if (_DATA_DIR / fn).exists()
)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _journey_to_prose(scenario: LabeledScenario) -> str:
    """Convert a structured journey into plain-English prose for the baseline prompt."""
    lines: list[str] = [f"Customer journey for scenario '{scenario.id}':"]
    for ev in scenario.journey:
        payload_parts = [f"{k}={v}" for k, v in ev.payload.items() if v]
        payload_str = f" ({', '.join(payload_parts)})" if payload_parts else ""
        lines.append(f"  - Day {ev.day}: {ev.event_type}{payload_str}")
    lines.append("")
    lines.append(f"Context: {scenario.description}")
    return "\n".join(lines)


def _build_messages(scenario: LabeledScenario) -> list[dict[str, str]]:
    """Build the chat messages for a single baseline call."""
    system_prompt = (
        "You are a NovaCart customer support AI. "
        "You are given the complete NovaCart policy documents and a customer journey. "
        "Your job is to determine whether the LAST refund or replacement request in the journey "
        "should be ALLOWED or DENIED based strictly on the policies. "
        "Reply with exactly one word: either ALLOW or DENY, followed by a one-sentence reason."
    )
    user_content = (
        f"=== NovaCart Policy Documents ===\n\n{POLICY_CONTEXT}\n\n"
        f"=== Customer Journey ===\n\n{_journey_to_prose(scenario)}\n\n"
        "Decision (ALLOW or DENY):"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Outcome parsing
# ---------------------------------------------------------------------------

_OUTCOME_RE = re.compile(r"\b(ALLOW|DENY)\b", re.IGNORECASE)


def _parse_outcome(response: str) -> str:
    """Extract ALLOW or DENY from model response; return 'UNKNOWN' if absent."""
    m = _OUTCOME_RE.search(response)
    if m:
        return m.group(1).upper()
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BaselineRun:
    """A single run of the baseline for one scenario."""
    run_index: int
    response: str
    parsed_outcome: str
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    success: bool
    error_message: str | None = None


@dataclass
class BaselineResult:
    """Aggregated baseline results for one scenario across N runs."""
    scenario_id: str
    expected_outcome: str | None
    runs: list[BaselineRun] = field(default_factory=list)

    @property
    def outcomes(self) -> list[str]:
        return [r.parsed_outcome for r in self.runs]

    @property
    def majority_outcome(self) -> str:
        """Most common parsed outcome across runs."""
        counts: dict[str, int] = {}
        for o in self.outcomes:
            counts[o] = counts.get(o, 0) + 1
        return max(counts, key=lambda k: counts[k]) if counts else "UNKNOWN"

    @property
    def is_consistent(self) -> bool:
        """True if all successful runs returned the same outcome."""
        valid = [o for o in self.outcomes if o != "UNKNOWN"]
        return len(set(valid)) <= 1 if valid else False

    @property
    def correct(self) -> bool | None:
        """None if expected_outcome is unset; else True/False."""
        if self.expected_outcome is None:
            return None
        return self.majority_outcome == self.expected_outcome

    @property
    def avg_latency_ms(self) -> float:
        successful = [r for r in self.runs if r.success]
        return sum(r.latency_ms for r in successful) / len(successful) if successful else 0.0

    @property
    def total_cost_tokens(self) -> int:
        return sum(r.total_tokens for r in self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "expected_outcome": self.expected_outcome,
            "majority_outcome": self.majority_outcome,
            "is_consistent": self.is_consistent,
            "correct": self.correct,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "total_cost_tokens": self.total_cost_tokens,
            "runs": [
                {
                    "run_index": r.run_index,
                    "parsed_outcome": r.parsed_outcome,
                    "latency_ms": round(r.latency_ms, 1),
                    "prompt_tokens": r.prompt_tokens,
                    "completion_tokens": r.completion_tokens,
                    "total_tokens": r.total_tokens,
                    "success": r.success,
                    "response_snippet": r.response[:120],
                }
                for r in self.runs
            ],
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class BaselineRunner:
    """Runs the naive LLM baseline for a list of labeled scenarios."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        n_runs: int = 3,
        temperature: float = 0.0,
    ) -> None:
        self.client = llm_client or LLMClient()
        self.n_runs = n_runs
        self.temperature = temperature

    def run_scenario(self, scenario: LabeledScenario) -> BaselineResult:
        """Run the baseline N times for a single scenario."""
        messages = _build_messages(scenario)
        result = BaselineResult(
            scenario_id=scenario.id,
            expected_outcome=scenario.expected_outcome,
        )
        for i in range(self.n_runs):
            t0 = time.perf_counter()
            try:
                response = self.client.chat_complete(
                    messages=messages,
                    temperature=self.temperature,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000
                # Grab telemetry from the last call record
                last_rec = self.client.call_history[-1] if self.client.call_history else None
                run = BaselineRun(
                    run_index=i,
                    response=response,
                    parsed_outcome=_parse_outcome(response),
                    latency_ms=last_rec.latency_ms if last_rec else elapsed_ms,
                    prompt_tokens=last_rec.prompt_tokens if last_rec else 0,
                    completion_tokens=last_rec.completion_tokens if last_rec else 0,
                    total_tokens=last_rec.total_tokens if last_rec else 0,
                    success=True,
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - t0) * 1000
                run = BaselineRun(
                    run_index=i,
                    response="",
                    parsed_outcome="UNKNOWN",
                    latency_ms=elapsed_ms,
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    success=False,
                    error_message=str(exc),
                )
            result.runs.append(run)
        return result

    def run_all(self, scenarios: list[LabeledScenario]) -> list[BaselineResult]:
        """Run the baseline for every scenario and return all results."""
        results: list[BaselineResult] = []
        for scenario in scenarios:
            result = self.run_scenario(scenario)
            results.append(result)
        return results
