"""PolicyForge engine runner for benchmark evaluation.

For each labeled scenario:
  1. Loads rules from rules_v1.json (compiled, deterministic).
  2. Simulates the journey with PolicyEngine.
  3. Extracts the last decision-event outcome.
  4. Records all findings.
  5. Times the simulation.

Since the engine is deterministic, a single run per scenario suffices.
Consistency is 100% by design.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sys

_BACKEND = Path(__file__).parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from policyforge.models import (
    Rule,
    Event,
    EventType,
    EffectType,
    FindingType,
    SimulationResult,
)
from policyforge.engine import PolicyEngine
from policyforge.detectors import create_default_invariant_registry
from benchmark.schema import LabeledScenario


# ---------------------------------------------------------------------------
# Decision event types
# ---------------------------------------------------------------------------

_DECISION_EVENT_TYPES = {
    EventType.REFUND_REQUESTED,
    EventType.REPLACEMENT_REQUESTED,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EngineResult:
    """Result of running the PolicyForge engine on one labeled scenario."""
    scenario_id: str
    expected_outcome: str | None
    # The outcome of the LAST decision event, or None if no decision event
    engine_outcome: str | None
    finding_types: list[str]
    latency_ms: float
    # True if engine_outcome matches expected_outcome (None when no expectation set)
    correct: bool | None

    @property
    def is_consistent(self) -> bool:
        """Always True; the engine is deterministic."""
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "expected_outcome": self.expected_outcome,
            "engine_outcome": self.engine_outcome,
            "finding_types": self.finding_types,
            "latency_ms": round(self.latency_ms, 3),
            "correct": self.correct,
            "is_consistent": True,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).parent.parent / "data" / "novacart"


def _load_rules(path: Path | None = None) -> list[Rule]:
    p = path or (_DATA_DIR / "rules_v1.json")
    raw = json.loads(p.read_text(encoding="utf-8"))
    return [Rule.model_validate(r) for r in raw]


class EngineRunner:
    """Runs the deterministic PolicyForge engine on labeled scenarios."""

    def __init__(
        self,
        rules: list[Rule] | None = None,
        rules_path: Path | None = None,
        default_decision_outcome: EffectType = EffectType.DENY,
    ) -> None:
        loaded_rules = rules if rules is not None else _load_rules(rules_path)
        self.engine = PolicyEngine(
            rules=loaded_rules,
            default_decision_outcome=default_decision_outcome,
            invariant_registry=create_default_invariant_registry(),
        )

    def run_scenario(self, scenario: LabeledScenario) -> EngineResult:
        """Simulate a single labeled scenario and return EngineResult."""
        journey = [
            Event(
                event_type=EventType(ev.event_type),
                day=ev.day,
                payload=ev.payload,
            )
            for ev in scenario.journey
        ]

        t0 = time.perf_counter()
        sim: SimulationResult = self.engine.run(journey)
        latency_ms = (time.perf_counter() - t0) * 1000

        # Extract last decision-event outcome from EventOutcomes
        last_decision_outcome: str | None = None
        for outcome in reversed(sim.outcomes):
            if outcome.event_type in _DECISION_EVENT_TYPES:
                last_decision_outcome = outcome.outcome.value
                break

        finding_types = [f.type.value for f in sim.findings]

        correct: bool | None = None
        if scenario.expected_outcome is not None and last_decision_outcome is not None:
            correct = last_decision_outcome == scenario.expected_outcome
        elif scenario.expected_outcome is None:
            correct = None  # no expectation set

        return EngineResult(
            scenario_id=scenario.id,
            expected_outcome=scenario.expected_outcome,
            engine_outcome=last_decision_outcome,
            finding_types=finding_types,
            latency_ms=latency_ms,
            correct=correct,
        )

    def run_all(self, scenarios: list[LabeledScenario]) -> list[EngineResult]:
        """Simulate all labeled scenarios."""
        return [self.run_scenario(s) for s in scenarios]
