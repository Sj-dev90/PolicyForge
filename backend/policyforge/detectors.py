"""PolicyForge Detectors: Contradiction, Policy Gap, Ambiguity, Invariants, and Dead Rules.

Static Analysis Scope & Limits:
- Scope: Interval arithmetic over numeric fields (e.g. days_since_delivery in [0, inf)),
  and discrete equality/inequality over boolean and enum fields.
- Limits:
  1. Relational arithmetic across multiple fields (e.g. field_a + field_b > 10) is not modeled.
  2. Multi-step temporal reachability (whether an event sequence can reach a state) is not
     solved statically; it is verified dynamically via simulation and invariant checking.
  3. Approximates complex nested disjunctions conservatively to avoid false positives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
    ConditionTree,
    LeafCondition,
    AllCondition,
    AnyCondition,
    Rule,
    State,
    Finding,
    FindingType,
    FindingSeverity,
    Event,
    SimulationResult,
)
from policyforge.engine import PolicyEngine


# ---------------------------------------------------------------------------
# 1. Invariant Registry & Core Invariant Definitions
# ---------------------------------------------------------------------------

InvariantFn = Callable[[State, Event | None, int], Finding | None]


@dataclass
class InvariantDefinition:
    id: str
    name: str
    description: str
    check_fn: InvariantFn


class InvariantRegistry:
    """Registry for business policy invariants implemented as pure functions."""

    def __init__(self) -> None:
        self._registry: dict[str, InvariantDefinition] = {}

    def register(
        self,
        invariant_id: str,
        name: str,
        description: str,
    ) -> Callable[[InvariantFn], InvariantFn]:
        """Decorator to register a pure invariant check function."""
        def decorator(fn: InvariantFn) -> InvariantFn:
            self.add(invariant_id, name, description, fn)
            return fn
        return decorator

    def add(
        self,
        invariant_id: str,
        name: str,
        description: str,
        fn: InvariantFn,
    ) -> None:
        """Register an invariant check function."""
        self._registry[invariant_id] = InvariantDefinition(
            id=invariant_id,
            name=name,
            description=description,
            check_fn=fn,
        )

    def check_all(
        self,
        state: State,
        event: Event | None = None,
        event_index: int = 0,
    ) -> list[Finding]:
        """Evaluate all registered invariants against state, returning any findings."""
        findings: list[Finding] = []
        for inv in self._registry.values():
            finding = inv.check_fn(state, event, event_index)
            if finding is not None:
                findings.append(finding)
        return findings

    def get_registered_ids(self) -> list[str]:
        return list(self._registry.keys())


def create_default_invariant_registry() -> InvariantRegistry:
    """Instantiate a registry populated with the five standard business invariants."""
    registry = InvariantRegistry()

    # Invariant 1: Full refund + completed replacement
    @registry.register(
        "no_duplicate_restitution",
        "No Duplicate Restitution",
        "An order cannot have both a completed refund and a completed replacement.",
    )
    def check_no_duplicate_restitution(
        state: State, event: Event | None, event_index: int
    ) -> Finding | None:
        if state.refund_completed and state.replacement_completed:
            day_str = f" (day {event.day})" if event else ""
            return Finding(
                type=FindingType.INVARIANT_VIOLATION,
                severity=FindingSeverity.CRITICAL,
                rule_ids=[],
                event_indices=[event_index],
                trace=(
                    f"Invariant violation [no_duplicate_restitution] at event {event_index}{day_str}: "
                    f"Customer received both a completed refund and a completed replacement. "
                    f"Dual restitution violates merchant policy."
                ),
                details={
                    "invariant_id": "no_duplicate_restitution",
                    "refund_completed": state.refund_completed,
                    "replacement_completed": state.replacement_completed,
                },
            )
        return None

    # Invariant 2: Refund amount > amount paid
    @registry.register(
        "refund_le_amount_paid",
        "Refund Cannot Exceed Amount Paid",
        "Total refund amount cannot exceed the original amount paid for the order.",
    )
    def check_refund_le_amount_paid(
        state: State, event: Event | None, event_index: int
    ) -> Finding | None:
        if state.amount_paid > 0.0 and state.refund_amount > state.amount_paid:
            day_str = f" (day {event.day})" if event else ""
            return Finding(
                type=FindingType.INVARIANT_VIOLATION,
                severity=FindingSeverity.CRITICAL,
                rule_ids=[],
                event_indices=[event_index],
                trace=(
                    f"Invariant violation [refund_le_amount_paid] at event {event_index}{day_str}: "
                    f"Refund amount (${state.refund_amount:.2f}) exceeds total amount paid "
                    f"(${state.amount_paid:.2f})."
                ),
                details={
                    "invariant_id": "refund_le_amount_paid",
                    "amount_paid": state.amount_paid,
                    "refund_amount": state.refund_amount,
                },
            )
        return None

    # Invariant 3: Replacement both active and cancelled
    @registry.register(
        "replacement_consistent_status",
        "Replacement Cannot Be Active and Cancelled",
        "A replacement cannot be concurrently active and cancelled.",
    )
    def check_replacement_consistent_status(
        state: State, event: Event | None, event_index: int
    ) -> Finding | None:
        if state.replacement_active and state.replacement_cancelled:
            day_str = f" (day {event.day})" if event else ""
            return Finding(
                type=FindingType.INVARIANT_VIOLATION,
                severity=FindingSeverity.HIGH,
                rule_ids=[],
                event_indices=[event_index],
                trace=(
                    f"Invariant violation [replacement_consistent_status] at event {event_index}{day_str}: "
                    f"Replacement is marked active while also marked cancelled."
                ),
                details={
                    "invariant_id": "replacement_consistent_status",
                    "replacement_active": state.replacement_active,
                    "replacement_cancelled": state.replacement_cancelled,
                },
            )
        return None

    # Invariant 4: Completion before request
    @registry.register(
        "completion_requires_prior_request",
        "Action Completion Requires Prior Request",
        "A refund or replacement cannot complete before or without being requested.",
    )
    def check_completion_requires_prior_request(
        state: State, event: Event | None, event_index: int
    ) -> Finding | None:
        day_str = f" (day {event.day})" if event else ""
        # Check refund completion
        if state.refund_completed:
            if not state.refund_requested:
                return Finding(
                    type=FindingType.INVARIANT_VIOLATION,
                    severity=FindingSeverity.CRITICAL,
                    rule_ids=[],
                    event_indices=[event_index],
                    trace=(
                        f"Invariant violation [completion_requires_prior_request] at event {event_index}{day_str}: "
                        f"Refund completed without any recorded refund request."
                    ),
                    details={"action": "REFUND", "reason": "no_request"},
                )
            if (
                state.refund_request_day is not None
                and state.refund_completed_day is not None
                and state.refund_completed_day < state.refund_request_day
            ):
                return Finding(
                    type=FindingType.INVARIANT_VIOLATION,
                    severity=FindingSeverity.CRITICAL,
                    rule_ids=[],
                    event_indices=[event_index],
                    trace=(
                        f"Invariant violation [completion_requires_prior_request] at event {event_index}{day_str}: "
                        f"Refund completed on day {state.refund_completed_day} prior to request on day {state.refund_request_day}."
                    ),
                    details={
                        "action": "REFUND",
                        "request_day": state.refund_request_day,
                        "completion_day": state.refund_completed_day,
                    },
                )

        # Check replacement completion
        if state.replacement_completed:
            if not state.replacement_requested:
                return Finding(
                    type=FindingType.INVARIANT_VIOLATION,
                    severity=FindingSeverity.CRITICAL,
                    rule_ids=[],
                    event_indices=[event_index],
                    trace=(
                        f"Invariant violation [completion_requires_prior_request] at event {event_index}{day_str}: "
                        f"Replacement completed without any recorded replacement request."
                    ),
                    details={"action": "REPLACEMENT", "reason": "no_request"},
                )
            if (
                state.replacement_request_day is not None
                and state.replacement_completed_day is not None
                and state.replacement_completed_day < state.replacement_request_day
            ):
                return Finding(
                    type=FindingType.INVARIANT_VIOLATION,
                    severity=FindingSeverity.CRITICAL,
                    rule_ids=[],
                    event_indices=[event_index],
                    trace=(
                        f"Invariant violation [completion_requires_prior_request] at event {event_index}{day_str}: "
                        f"Replacement completed on day {state.replacement_completed_day} prior to request on day {state.replacement_request_day}."
                    ),
                    details={
                        "action": "REPLACEMENT",
                        "request_day": state.replacement_request_day,
                        "completion_day": state.replacement_completed_day,
                    },
                )
        return None

    # Invariant 5: Chargeback active while refund completed
    @registry.register(
        "no_chargeback_after_refund",
        "Chargeback Active While Refund Completed",
        "A chargeback dispute cannot be active after a merchant refund has already completed.",
    )
    def check_no_chargeback_after_refund(
        state: State, event: Event | None, event_index: int
    ) -> Finding | None:
        if state.chargeback_active and state.refund_completed:
            day_str = f" (day {event.day})" if event else ""
            return Finding(
                type=FindingType.INVARIANT_VIOLATION,
                severity=FindingSeverity.HIGH,
                rule_ids=[],
                event_indices=[event_index],
                trace=(
                    f"Invariant violation [no_chargeback_after_refund] at event {event_index}{day_str}: "
                    f"Chargeback dispute remains active after a full refund was already processed."
                ),
                details={
                    "invariant_id": "no_chargeback_after_refund",
                    "chargeback_active": state.chargeback_active,
                    "refund_completed": state.refund_completed,
                },
            )
        return None

    return registry


# ---------------------------------------------------------------------------
# 2. Static Analysis: Interval & Equality Reasoning (Dead Rules)
# ---------------------------------------------------------------------------

@dataclass
class NumericInterval:
    """Interval representing valid values for a numeric field [min_val, max_val]."""
    min_val: float = 0.0
    max_val: float = float("inf")

    def intersect_op(self, op: Operator, val: float) -> bool:
        """Intersect current interval with a new condition. Returns False if empty."""
        if op == Operator.EQ:
            self.min_val = max(self.min_val, val)
            self.max_val = min(self.max_val, val)
        elif op == Operator.GT:
            self.min_val = max(self.min_val, val + 1)
        elif op == Operator.GTE:
            self.min_val = max(self.min_val, val)
        elif op == Operator.LT:
            self.max_val = min(self.max_val, val - 1)
        elif op == Operator.LTE:
            self.max_val = min(self.max_val, val)
        return not self.is_empty()

    def is_empty(self) -> bool:
        return self.min_val > self.max_val

    def contains(self, other: NumericInterval) -> bool:
        """Check if this interval completely contains (subsumes) another interval."""
        return self.min_val <= other.min_val and self.max_val >= other.max_val


def _flatten_all_leafs(cond: ConditionTree) -> list[LeafCondition] | None:
    """Extract leaves that must simultaneously hold (under AllCondition or single Leaf).

    Returns None if condition tree has unsupported nested disjunctions for static analysis.
    """
    if isinstance(cond, LeafCondition):
        return [cond]
    if isinstance(cond, AllCondition):
        leaves: list[LeafCondition] = []
        for child in cond.all:
            sub = _flatten_all_leafs(child)
            if sub is None:
                return None
            leaves.extend(sub)
        return leaves
    return None


def is_condition_satisfiable(cond: ConditionTree) -> tuple[bool, str]:
    """Check if a condition tree is satisfiable using interval and equality reasoning."""
    if isinstance(cond, LeafCondition):
        if cond.field == StateField.DAYS_SINCE_DELIVERY:
            if cond.op in (Operator.LT, Operator.LTE):
                bound = 0 if cond.op == Operator.LT else -1
                if isinstance(cond.value, (int, float)) and cond.value <= bound:
                    return False, f"days_since_delivery cannot be {cond.op.value} {cond.value}"
        return True, ""

    if isinstance(cond, AnyCondition):
        # AnyCondition is unsatisfiable only if EVERY branch is unsatisfiable
        all_unsat = True
        reasons = []
        for branch in cond.any:
            sat, reason = is_condition_satisfiable(branch)
            if sat:
                all_unsat = False
                break
            reasons.append(reason)
        if all_unsat:
            return False, f"All branches of AnyCondition are unsatisfiable: {'; '.join(reasons)}"
        return True, ""

    if isinstance(cond, AllCondition):
        leaves = _flatten_all_leafs(cond)
        if leaves is None:
            # Conservative fallback: cannot prove unsatisfiability
            return True, ""

        # Analyze numeric intervals
        intervals: dict[StateField, NumericInterval] = {
            StateField.DAYS_SINCE_DELIVERY: NumericInterval(min_val=0.0, max_val=float("inf")),
        }

        # Analyze boolean / enum requirements
        equalities: dict[StateField, Any] = {}

        for leaf in leaves:
            val = leaf.value.value if isinstance(leaf.value, Enum) else leaf.value

            if leaf.field in (
                StateField.DAYS_SINCE_DELIVERY,
                StateField.ORDER_DAY,
                StateField.DELIVERY_DAY,
            ):
                if leaf.field not in intervals:
                    intervals[leaf.field] = NumericInterval(min_val=0.0, max_val=float("inf"))

                if leaf.op in (
                    Operator.EQ,
                    Operator.GT,
                    Operator.GTE,
                    Operator.LT,
                    Operator.LTE,
                ) and isinstance(val, (int, float)):
                    sat = intervals[leaf.field].intersect_op(leaf.op, float(val))
                    if not sat:
                        return (
                            False,
                            f"Contradictory bounds on {leaf.field.value}: "
                            f"min={intervals[leaf.field].min_val} > max={intervals[leaf.field].max_val}",
                        )

            # Equality / boolean checks
            if leaf.op in (Operator.EQ, Operator.IS_TRUE, Operator.IS_FALSE):
                expected = True if leaf.op == Operator.IS_TRUE else (False if leaf.op == Operator.IS_FALSE else val)
                if leaf.field in equalities and equalities[leaf.field] != expected:
                    return (
                        False,
                        f"Contradictory equality on {leaf.field.value}: "
                        f"requires {equalities[leaf.field]} and {expected}",
                    )
                equalities[leaf.field] = expected

        return True, ""

    return True, ""


def _rule_subsumes(r_broad: Rule, r_narrow: Rule) -> bool:
    """Check if r_broad's condition subsumes r_narrow (r_narrow entails r_broad).

    Meaning: whenever r_narrow fires, r_broad is guaranteed to fire as well.
    """
    broad_leaves = _flatten_all_leafs(r_broad.when)
    narrow_leaves = _flatten_all_leafs(r_narrow.when)

    if broad_leaves is None or narrow_leaves is None:
        return False

    # If broad rule has no conditions, it always fires whenever narrow rule fires
    if not broad_leaves:
        return True

    # Build constraints required by narrow rule
    narrow_equalities: dict[StateField, Any] = {}
    narrow_intervals: dict[StateField, NumericInterval] = {}

    for l in narrow_leaves:
        val = l.value.value if isinstance(l.value, Enum) else l.value
        if l.op in (Operator.EQ, Operator.IS_TRUE, Operator.IS_FALSE):
            expected = True if l.op == Operator.IS_TRUE else (False if l.op == Operator.IS_FALSE else val)
            narrow_equalities[l.field] = expected
        elif l.op in (Operator.GT, Operator.GTE, Operator.LT, Operator.LTE) and isinstance(val, (int, float)):
            if l.field not in narrow_intervals:
                narrow_intervals[l.field] = NumericInterval(min_val=0.0, max_val=float("inf"))
            narrow_intervals[l.field].intersect_op(l.op, float(val))

    # Every leaf requirement in broad rule must be guaranteed by narrow rule
    for b_leaf in broad_leaves:
        b_val = b_leaf.value.value if isinstance(b_leaf.value, Enum) else b_leaf.value

        if b_leaf.op in (Operator.EQ, Operator.IS_TRUE, Operator.IS_FALSE):
            b_expected = True if b_leaf.op == Operator.IS_TRUE else (False if b_leaf.op == Operator.IS_FALSE else b_val)
            # Narrow rule MUST require the exact same equality
            if b_leaf.field not in narrow_equalities or narrow_equalities[b_leaf.field] != b_expected:
                return False
        elif b_leaf.op in (Operator.GT, Operator.GTE, Operator.LT, Operator.LTE) and isinstance(b_val, (int, float)):
            # Narrow rule must constrain this field within b_leaf's bound
            if b_leaf.field not in narrow_intervals:
                return False
            b_interval = NumericInterval(min_val=0.0, max_val=float("inf"))
            b_interval.intersect_op(b_leaf.op, float(b_val))
            if not b_interval.contains(narrow_intervals[b_leaf.field]):
                return False
        else:
            return False

    return True


def detect_dead_rules(rules: list[Rule]) -> list[Finding]:
    """Perform static analysis on rule definitions to identify dead or shadowed rules.

    A rule is considered DEAD if:
    1. Its conditions are unsatisfiable (interval/boolean contradiction).
    2. It is always overridden by another rule whose conditions subsume it.
    """
    findings: list[Finding] = []

    for r in rules:
        # Check 1: Unsatisfiable condition
        sat, reason = is_condition_satisfiable(r.when)
        if not sat:
            findings.append(
                Finding(
                    type=FindingType.DEAD_RULE,
                    severity=FindingSeverity.MEDIUM,
                    rule_ids=[r.id],
                    event_indices=[],
                    trace=(
                        f"Dead rule detected [unsatisfiable_condition]: Rule '{r.id}' ({r.name}) "
                        f"can never fire because its conditions are unsatisfiable: {reason}."
                    ),
                    details={"rule_id": r.id, "reason": reason, "category": "unsatisfiable"},
                )
            )

    # Check 2: Always overridden
    for r1 in rules:
        for r2 in rules:
            if r1.id == r2.id:
                continue
            if r1.trigger == r2.trigger and r1.decision == r2.decision:
                if r1.id in r2.overrides and _rule_subsumes(r2, r1):
                    findings.append(
                        Finding(
                            type=FindingType.DEAD_RULE,
                            severity=FindingSeverity.MEDIUM,
                            rule_ids=[r1.id, r2.id],
                            event_indices=[],
                            trace=(
                                f"Dead rule detected [always_overridden]: Rule '{r1.id}' is permanently "
                                f"shadowed by '{r2.id}'. Whenever '{r1.id}' conditions are met, "
                                f"'{r2.id}' also fires and explicitly overrides it."
                            ),
                            details={
                                "rule_id": r1.id,
                                "overriding_rule_id": r2.id,
                                "category": "always_overridden",
                            },
                        )
                    )

    return findings


# ---------------------------------------------------------------------------
# 3. Comprehensive Policy Detector Runner
# ---------------------------------------------------------------------------

class PolicyDetector:
    """Coordinates static analysis and simulation-based verification."""

    def __init__(
        self,
        rules: list[Rule],
        invariant_registry: InvariantRegistry | None = None,
        default_decision_outcome: EffectType = EffectType.DENY,
    ) -> None:
        self.rules = rules
        self.invariant_registry = invariant_registry or create_default_invariant_registry()
        self.engine = PolicyEngine(
            rules=rules,
            default_decision_outcome=default_decision_outcome,
            invariant_registry=self.invariant_registry,
        )

    def run_static_analysis(self) -> list[Finding]:
        """Run all static checks across the rule set."""
        return detect_dead_rules(self.rules)

    def verify_journey(
        self,
        journey: list[Event],
        initial_state: State | None = None,
    ) -> SimulationResult:
        """Run simulation with full invariant checking and trace diagnostics."""
        return self.engine.run(journey, initial_state=initial_state)
