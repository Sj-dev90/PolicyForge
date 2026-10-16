"""Pydantic schema for labeled_scenarios.json and a file validator.

Run as a script:
    python benchmark/schema.py [path/to/labeled_scenarios.json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

VALID_FINDING_TYPES = {
    "CONTRADICTION",
    "POLICY_GAP",
    "AMBIGUITY",
    "INVARIANT_VIOLATION",
    "DEAD_RULE",
}

VALID_EVENT_TYPES = {
    "ORDER_PLACED",
    "ITEM_DELIVERED",
    "REPLACEMENT_REQUESTED",
    "REFUND_REQUESTED",
    "RETURN_RECEIVED",
    "REPLACEMENT_CANCELLED",
    "ORDER_CANCELLED",
    "ITEM_DAMAGED_REPORTED",
    "REFUND_COMPLETED",
    "REPLACEMENT_DELIVERED",
    "CHARGEBACK_FILED",
    "CHARGEBACK_RESOLVED",
}

VALID_OUTCOMES = {"ALLOW", "DENY"}


class LabeledEvent(BaseModel):
    """A single event inside a labeled journey."""

    event_type: str
    day: int
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_event_type(self) -> "LabeledEvent":
        if self.event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{self.event_type}'. "
                f"Valid values: {sorted(VALID_EVENT_TYPES)}"
            )
        if self.day < 0:
            raise ValueError(f"day must be non-negative, got {self.day}")
        return self


class LabeledScenario(BaseModel):
    """A single hand-labeled benchmark scenario."""

    id: str
    description: str
    journey: list[LabeledEvent]
    # The last decision-event outcome expected (ALLOW or DENY).
    # Set to null/None if the journey has no decision event.
    expected_outcome: str | None = None
    # Finding types expected to appear in the simulation result.
    expected_finding_types: list[str] = Field(default_factory=list)
    notes: str = ""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_fields(self) -> "LabeledScenario":
        if self.expected_outcome is not None and self.expected_outcome not in VALID_OUTCOMES:
            raise ValueError(
                f"expected_outcome must be one of {VALID_OUTCOMES}, "
                f"got '{self.expected_outcome}'"
            )
        for ft in self.expected_finding_types:
            if ft not in VALID_FINDING_TYPES:
                raise ValueError(
                    f"Unknown finding type '{ft}' in scenario '{self.id}'. "
                    f"Valid: {sorted(VALID_FINDING_TYPES)}"
                )
        if not self.journey:
            raise ValueError(f"Scenario '{self.id}' has an empty journey.")
        # Monotonic day check
        last_day = -1
        for i, ev in enumerate(self.journey):
            if ev.day < last_day:
                raise ValueError(
                    f"Scenario '{self.id}': event[{i}] day {ev.day} < "
                    f"previous day {last_day} (must be non-decreasing)."
                )
            last_day = ev.day
        return self


class LabeledScenarioFile(BaseModel):
    """Top-level wrapper for a labeled_scenarios.json file."""

    scenarios: list[LabeledScenario]

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "LabeledScenarioFile":
        seen: set[str] = set()
        for s in self.scenarios:
            if s.id in seen:
                raise ValueError(f"Duplicate scenario id '{s.id}'.")
            seen.add(s.id)
        return self


# ---------------------------------------------------------------------------
# Loader helper
# ---------------------------------------------------------------------------

def load_labeled_scenarios(path: Path | str) -> list[LabeledScenario]:
    """Load and validate a labeled_scenarios.json file.

    The file may be either:
      - A JSON array of scenario objects (legacy flat format), or
      - A JSON object with a "scenarios" key (wrapped format).

    Returns the list of validated LabeledScenario objects.
    Raises ValueError / pydantic.ValidationError on schema violations.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [LabeledScenario.model_validate(item) for item in data]
    elif isinstance(data, dict) and "scenarios" in data:
        wrapper = LabeledScenarioFile.model_validate(data)
        return wrapper.scenarios
    else:
        raise ValueError(
            "labeled_scenarios.json must be a JSON array or an object with a 'scenarios' key."
        )


# ---------------------------------------------------------------------------
# CLI validator
# ---------------------------------------------------------------------------

def _validate_cli(path: Path) -> None:
    try:
        scenarios = load_labeled_scenarios(path)
    except Exception as exc:
        print(f"[FAIL] Validation error in {path}:\n  {exc}", file=sys.stderr)
        sys.exit(1)

    # Summary
    print(f"[OK] {path}: {len(scenarios)} scenarios validated.")
    outcomes = [s.expected_outcome for s in scenarios if s.expected_outcome]
    finding_counts: dict[str, int] = {}
    for s in scenarios:
        for ft in s.expected_finding_types:
            finding_counts[ft] = finding_counts.get(ft, 0) + 1

    allow_count = outcomes.count("ALLOW")
    deny_count = outcomes.count("DENY")
    no_decision = sum(1 for s in scenarios if s.expected_outcome is None)

    print(f"  Expected outcomes : ALLOW={allow_count}  DENY={deny_count}  none={no_decision}")
    if finding_counts:
        print(f"  Expected findings : {finding_counts}")
    else:
        print("  Expected findings : (none — all clean scenarios)")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).parent / "labeled_scenarios.json"
    )
    _validate_cli(target)
