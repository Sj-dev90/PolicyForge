"""Scenario generation, LLM scenario validation, and test suite execution with minimal counterexamples."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
    CustomerTier,
    LeafCondition,
    AllCondition,
    AnyCondition,
    Rule,
    Event,
    Finding,
    FindingType,
)
from policyforge.engine import PolicyEngine
from policyforge.detectors import create_default_invariant_registry, InvariantRegistry
from policyforge.shrink import shrink_journey, ShrinkResult, get_finding_signature


@dataclass
class Scenario:
    """A test scenario comprising an ID, description, and event journey."""
    id: str
    name: str
    description: str
    journey: list[Event]
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Boundary Scenario Generator
# ---------------------------------------------------------------------------

def _extract_thresholds(cond: Any) -> set[int]:
    """Recursively extract integer boundary thresholds from condition trees."""
    thresholds: set[int] = set()
    if isinstance(cond, LeafCondition):
        if cond.field == StateField.DAYS_SINCE_DELIVERY and isinstance(cond.value, (int, float)):
            thresholds.add(int(cond.value))
    elif isinstance(cond, AllCondition):
        for child in cond.all:
            thresholds.update(_extract_thresholds(child))
    elif isinstance(cond, AnyCondition):
        for child in cond.any:
            thresholds.update(_extract_thresholds(child))
    return thresholds


def generate_boundary_scenarios(rules: list[Rule]) -> list[Scenario]:
    """Generate boundary scenarios at threshold-1, threshold, and threshold+1.

    Extracts numeric thresholds from rule conditions and combines them with
    orthogonal boolean flags (damaged, VIP, clearance/final sale, chargeback).
    """
    thresholds: set[int] = set()
    for r in rules:
        thresholds.update(_extract_thresholds(r.when))

    # Fallback to standard e-commerce windows if no thresholds discovered
    if not thresholds:
        thresholds = {14, 30, 45, 60}

    # Generate boundary days
    boundary_days: set[int] = set()
    for t in sorted(thresholds):
        for delta in (-1, 0, 1):
            day = t + delta
            if day >= 0:
                boundary_days.add(day)

    # Flag combinations
    flag_combos = [
        {"desc": "standard", "payload": {}},
        {"desc": "damaged", "payload": {"item_damaged": True}},
        {"desc": "vip", "payload": {"customer_tier": "VIP"}},
        {"desc": "clearance", "payload": {"is_final_sale": True}},
        {"desc": "chargeback", "payload": {"chargeback_active": True}},
        {"desc": "vip_damaged", "payload": {"customer_tier": "VIP", "item_damaged": True}},
    ]

    scenarios: list[Scenario] = []
    scenario_idx = 1

    for day in sorted(boundary_days):
        for combo in flag_combos:
            for decision_event in (EventType.REFUND_REQUESTED, EventType.REPLACEMENT_REQUESTED):
                action_name = "refund" if decision_event == EventType.REFUND_REQUESTED else "replacement"
                s_id = f"boundary_{action_name}_d{day}_{combo['desc']}_{scenario_idx}"
                desc = (
                    f"Boundary test for {action_name} at day {day} "
                    f"with flags {combo['desc']}."
                )
                journey = [
                    Event(event_type=EventType.ITEM_DELIVERED, day=0),
                    Event(
                        event_type=decision_event,
                        day=day,
                        payload=combo["payload"],
                    ),
                ]
                scenarios.append(
                    Scenario(
                        id=s_id,
                        name=f"Boundary Day {day} ({combo['desc']})",
                        description=desc,
                        journey=journey,
                        tags=["boundary", action_name, combo["desc"]],
                    )
                )
                scenario_idx += 1

    return scenarios


# ---------------------------------------------------------------------------
# 2. Pairwise Scenario Generator
# ---------------------------------------------------------------------------

def generate_pairwise_scenarios() -> list[Scenario]:
    """Generate combinatorial pairwise journeys covering combinations of events and flags."""
    # Key event progression patterns
    patterns = [
        # Pattern 1: Standard delivery -> request
        [
            (EventType.ORDER_PLACED, 0),
            (EventType.ITEM_DELIVERED, 3),
            (EventType.REFUND_REQUESTED, 15),
        ],
        # Pattern 2: Delivery -> replacement -> cancel -> refund
        [
            (EventType.ITEM_DELIVERED, 0),
            (EventType.REPLACEMENT_REQUESTED, 25),
            (EventType.REPLACEMENT_CANCELLED, 35),
            (EventType.REFUND_REQUESTED, 36),
        ],
        # Pattern 3: Damaged report -> replacement -> completed
        [
            (EventType.ITEM_DELIVERED, 0),
            (EventType.ITEM_DAMAGED_REPORTED, 5),
            (EventType.REPLACEMENT_REQUESTED, 10),
            (EventType.REPLACEMENT_DELIVERED, 20),
        ],
        # Pattern 4: Order placed -> cancel before delivery -> refund request
        [
            (EventType.ORDER_PLACED, 0),
            (EventType.ORDER_CANCELLED, 2),
            (EventType.REFUND_REQUESTED, 3),
        ],
        # Pattern 5: Delivery -> return received -> refund request -> refund completed
        [
            (EventType.ITEM_DELIVERED, 0),
            (EventType.RETURN_RECEIVED, 12),
            (EventType.REFUND_REQUESTED, 14),
            (EventType.REFUND_COMPLETED, 18),
        ],
        # Pattern 6: Delivery -> replacement -> duplicate replacement request
        [
            (EventType.ITEM_DELIVERED, 0),
            (EventType.REPLACEMENT_REQUESTED, 10),
            (EventType.REPLACEMENT_REQUESTED, 12),
        ],
    ]

    # Orthogonal flag combinations
    flag_sets = [
        {"customer_tier": "STANDARD", "is_final_sale": False, "item_damaged": False},
        {"customer_tier": "VIP", "is_final_sale": False, "item_damaged": False},
        {"customer_tier": "STANDARD", "is_final_sale": True, "item_damaged": False},
        {"customer_tier": "STANDARD", "is_final_sale": False, "item_damaged": True},
        {"customer_tier": "VIP", "is_final_sale": False, "item_damaged": True},
    ]

    scenarios: list[Scenario] = []
    idx = 1
    for p_idx, pattern in enumerate(patterns, start=1):
        for f_idx, flags in enumerate(flag_sets, start=1):
            s_id = f"pairwise_p{p_idx}_f{f_idx}_{idx}"
            journey: list[Event] = []
            for et, d in pattern:
                payload = dict(flags) if et in (EventType.ORDER_PLACED, EventType.REFUND_REQUESTED, EventType.REPLACEMENT_REQUESTED) else {}
                journey.append(Event(event_type=et, day=d, payload=payload))

            scenarios.append(
                Scenario(
                    id=s_id,
                    name=f"Pairwise Pattern {p_idx} Flags {f_idx}",
                    description=f"Pairwise combination of event flow {p_idx} with flags {flags}.",
                    journey=journey,
                    tags=["pairwise", f"pattern_{p_idx}"],
                )
            )
            idx += 1

    return scenarios


# ---------------------------------------------------------------------------
# 3. LLM Scenario Validator
# ---------------------------------------------------------------------------

def validate_scenario(journey_data: Any) -> tuple[bool, str | None]:
    """Validate raw journey data produced by an LLM against closed vocabularies and domain rules.

    Rejects:
    - Unknown event types
    - Unknown state fields in payloads
    - Non-monotonic / decreasing day ordering
    - Negative day or monetary values
    - Invalid customer tier or non-enum string values
    - Empty or non-list data structures
    """
    if not isinstance(journey_data, list):
        return False, f"Journey must be a list of event objects, got {type(journey_data).__name__}."

    if not journey_data:
        return False, "Journey cannot be empty."

    valid_event_types = {e.value for e in EventType}
    valid_state_fields = {f.value for f in StateField}
    valid_customer_tiers = {t.value for t in CustomerTier}

    last_day = -1

    for idx, raw_event in enumerate(journey_data):
        if not isinstance(raw_event, dict):
            return False, f"Event at index {idx} must be a dictionary, got {type(raw_event).__name__}."

        # Check event_type
        event_type = raw_event.get("event_type")
        if not event_type:
            return False, f"Event at index {idx} missing required field 'event_type'."
        if event_type not in valid_event_types:
            return False, (
                f"Unknown event type '{event_type}' at index {idx}. "
                f"Must be one of closed vocabulary: {sorted(valid_event_types)}."
            )

        # Check day
        day = raw_event.get("day")
        if day is None or not isinstance(day, int):
            return False, f"Event at index {idx} must have an integer 'day', got {day}."
        if day < 0:
            return False, f"Event at index {idx} has negative day {day}. Days must be non-negative."
        if day < last_day:
            return False, (
                f"Impossible ordering at index {idx}: day {day} is earlier than previous event day {last_day}. "
                f"Journeys must be chronologically ordered."
            )
        last_day = day

        # Check payload fields
        payload = raw_event.get("payload", {})
        if not isinstance(payload, dict):
            return False, f"Event at index {idx} payload must be a dict."

        for key, val in payload.items():
            if key not in valid_state_fields:
                return False, (
                    f"Unknown payload field '{key}' at index {idx}. "
                    f"Must be one of closed vocabulary: {sorted(valid_state_fields)}."
                )

            # Check value constraints
            if key in ("amount_paid", "refund_amount"):
                if not isinstance(val, (int, float)) or val < 0:
                    return False, f"Field '{key}' at index {idx} must be a non-negative number, got {val}."
            elif key == "customer_tier":
                if val not in valid_customer_tiers:
                    return False, (
                        f"Invalid customer_tier '{val}' at index {idx}. "
                        f"Must be one of {sorted(valid_customer_tiers)}."
                    )
            elif key in ("is_final_sale", "item_damaged", "item_opened", "chargeback_active"):
                if not isinstance(val, bool):
                    return False, f"Field '{key}' at index {idx} must be a boolean, got {type(val).__name__}."

    return True, None


# ---------------------------------------------------------------------------
# 4. Suite Runner with Minimal Counterexample Shrinking
# ---------------------------------------------------------------------------

@dataclass
class SuiteResult:
    """Aggregated results from running a scenario test suite."""
    total_scenarios: int
    passed_scenarios: int
    failed_scenarios: int
    total_findings: int
    deduplicated_findings: dict[tuple[FindingType, tuple[str, ...]], Finding]
    minimal_counterexamples: dict[tuple[FindingType, tuple[str, ...]], ShrinkResult]

    def summary_table(self) -> str:
        """Format a clear markdown summary table of unique failures and minimal counterexamples."""
        lines = [
            f"# PolicyForge Scenario Suite Execution Summary",
            f"",
            f"- **Total Scenarios Evaluated**: {self.total_scenarios}",
            f"- **Passed Scenarios**: {self.passed_scenarios}",
            f"- **Failed Scenarios (with Findings)**: {self.failed_scenarios}",
            f"- **Total Diagnostic Findings**: {self.total_findings}",
            f"- **Unique Finding Signatures**: {len(self.deduplicated_findings)}",
            f"",
            f"| Finding Type | Severity | Rule IDs | Original Steps | Minimal Steps | Minimal Journey |",
            f"| :--- | :--- | :--- | :---: | :---: | :--- |",
        ]

        for sig, finding in self.deduplicated_findings.items():
            shrink_res = self.minimal_counterexamples.get(sig)
            rule_str = ", ".join(finding.rule_ids) if finding.rule_ids else "None"
            orig_len = len(shrink_res.original_journey) if shrink_res else "N/A"
            min_len = len(shrink_res.minimal_journey) if shrink_res else "N/A"
            min_journey_str = (
                " -> ".join(f"{e.event_type.value}@d{e.day}" for e in shrink_res.minimal_journey)
                if shrink_res
                else "N/A"
            )
            lines.append(
                f"| `{finding.type.value}` | `{finding.severity.value}` | `{rule_str}` | {orig_len} | **{min_len}** | `{min_journey_str}` |"
            )

        return "\n".join(lines)


def run_suite(
    rules: list[Rule],
    scenarios: list[Scenario | list[Event]],
    default_decision_outcome: EffectType = EffectType.DENY,
    invariant_registry: InvariantRegistry | None = None,
) -> SuiteResult:
    """Execute scenario suite, aggregate and deduplicate findings, and shrink each failure."""
    registry = invariant_registry or create_default_invariant_registry()
    engine = PolicyEngine(
        rules=rules,
        default_decision_outcome=default_decision_outcome,
        invariant_registry=registry,
    )

    total_scenarios = len(scenarios)
    passed_scenarios = 0
    failed_scenarios = 0
    total_findings_count = 0

    # Map signature -> first finding
    dedup_findings: dict[tuple[FindingType, tuple[str, ...]], Finding] = {}
    # Map signature -> journey where it was observed
    failing_journeys: dict[tuple[FindingType, tuple[str, ...]], list[Event]] = {}

    for item in scenarios:
        journey = item.journey if isinstance(item, Scenario) else item
        res = engine.run(journey)
        if res.findings:
            failed_scenarios += 1
            total_findings_count += len(res.findings)
            for f in res.findings:
                sig = get_finding_signature(f)
                if sig not in dedup_findings:
                    dedup_findings[sig] = f
                    failing_journeys[sig] = journey
        else:
            passed_scenarios += 1

    # Shrink each unique finding to its minimal counterexample
    minimal_counterexamples: dict[tuple[FindingType, tuple[str, ...]], ShrinkResult] = {}
    for sig, raw_journey in failing_journeys.items():
        try:
            shrink_res = shrink_journey(engine, raw_journey, target_signature=sig)
            minimal_counterexamples[sig] = shrink_res
        except Exception:
            # Fallback if shrink fails on edge cases
            pass

    return SuiteResult(
        total_scenarios=total_scenarios,
        passed_scenarios=passed_scenarios,
        failed_scenarios=failed_scenarios,
        total_findings=total_findings_count,
        deduplicated_findings=dedup_findings,
        minimal_counterexamples=minimal_counterexamples,
    )
