"""Deterministic simulation engine for business policy verification.

Executes customer journeys against a rule set, strictly enforcing closed
vocabularies, computing derived state fields, evaluating condition trees
without eval/exec, and resolving conflicts deterministically.
"""

from __future__ import annotations

import copy
from typing import Any
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
    LeafEvaluation,
    RuleEvaluationTrace,
    EventTrace,
    Trace,
    Event,
    EventOutcome,
    SimulationResult,
)


def _get_field_value(field: StateField, state: State) -> Any:
    """Retrieve raw value of a field from State, unwrapping Enums if needed."""
    val = getattr(state, field.value, None)
    if isinstance(val, Enum):
        return val.value
    return val


def _compare_values(actual: Any, op: Operator, expected: Any) -> bool:
    """Evaluate comparator without eval or exec."""
    # Normalize Enum values if present
    if isinstance(actual, Enum):
        actual = actual.value
    if isinstance(expected, Enum):
        expected = expected.value

    if op == Operator.EQ:
        return bool(actual == expected)
    if op == Operator.NEQ:
        return bool(actual != expected)
    if op == Operator.IS_TRUE:
        return bool(actual is True)
    if op == Operator.IS_FALSE:
        return bool(actual is False)
    if op == Operator.IS_NULL:
        return bool(actual is None)
    if op == Operator.IS_NOT_NULL:
        return bool(actual is not None)

    # For ordering operators, if either is None, return False safely
    if actual is None or expected is None:
        return False

    try:
        if op == Operator.LT:
            return bool(actual < expected)
        if op == Operator.LTE:
            return bool(actual <= expected)
        if op == Operator.GT:
            return bool(actual > expected)
        if op == Operator.GTE:
            return bool(actual >= expected)
        if op == Operator.IN:
            return bool(actual in expected)
        if op == Operator.NIN:
            return bool(actual not in expected)
    except TypeError:
        return False

    return False


def evaluate_condition_tree(
    cond: ConditionTree, state: State
) -> tuple[bool, list[LeafEvaluation]]:
    """Recursively evaluate a condition tree against the given state."""
    if isinstance(cond, LeafCondition):
        actual = _get_field_value(cond.field, state)
        expected = cond.value
        passed = _compare_values(actual, cond.op, expected)
        desc = f"{cond.field.value} ({actual}) {cond.op.value} {expected} -> {passed}"
        eval_leaf = LeafEvaluation(
            field=cond.field,
            op=cond.op,
            expected_value=expected,
            actual_value=actual,
            passed=passed,
            description=desc,
        )
        return passed, [eval_leaf]

    if isinstance(cond, AllCondition):
        all_passed = True
        leaf_evals: list[LeafEvaluation] = []
        for child in cond.all:
            child_passed, child_evals = evaluate_condition_tree(child, state)
            leaf_evals.extend(child_evals)
            if not child_passed:
                all_passed = False
        return all_passed, leaf_evals

    if isinstance(cond, AnyCondition):
        any_passed = False
        leaf_evals: list[LeafEvaluation] = []
        for child in cond.any:
            child_passed, child_evals = evaluate_condition_tree(child, state)
            leaf_evals.extend(child_evals)
            if child_passed:
                any_passed = True
        return any_passed, leaf_evals

    raise ValueError(f"Unsupported condition node type: {type(cond)}")


class PolicyEngine:
    """Deterministic simulation engine."""

    def __init__(
        self,
        rules: list[Rule],
        default_decision_outcome: EffectType = EffectType.DENY,
        invariant_registry: Any = None,
    ) -> None:
        self.rules = rules
        self.default_decision_outcome = default_decision_outcome
        self.invariant_registry = invariant_registry

    def _resolve_conflict(
        self,
        firing_rules: list[Rule],
        event_index: int,
        event: Event,
    ) -> tuple[EffectType, str, list[str], list[str], list[Finding]]:
        """Resolve conflict between firing rules according to docs/semantics.md.

        Returns:
            (outcome, resolution_type, active_rule_ids, suppressed_rule_ids, findings)
        """
        # 1. No rules fired -> POLICY_GAP (with configurable default outcome)
        if not firing_rules:
            outcome = self.default_decision_outcome
            res_type = "DEFAULT_ALLOW" if outcome == EffectType.ALLOW else "DEFAULT_DENY"
            finding = Finding(
                type=FindingType.POLICY_GAP,
                severity=FindingSeverity.MEDIUM,
                rule_ids=[],
                event_indices=[event_index],
                trace=(
                    f"Policy gap detected at event {event_index} (day {event.day}): "
                    f"No rules fired for decision event '{event.event_type.value}'. "
                    f"Default outcome '{outcome.value}' was applied."
                ),
                details={
                    "event_type": event.event_type.value,
                    "day": event.day,
                    "default_outcome": outcome.value,
                },
            )
            return outcome, res_type, [], [], [finding]

        allow_rules = [r for r in firing_rules if r.effect == EffectType.ALLOW]
        deny_rules = [r for r in firing_rules if r.effect == EffectType.DENY]

        # 2. Unanimous ALLOW
        if allow_rules and not deny_rules:
            return (
                EffectType.ALLOW,
                "UNANIMOUS_ALLOW",
                [r.id for r in allow_rules],
                [],
                [],
            )

        # 3. Unanimous DENY
        if deny_rules and not allow_rules:
            return (
                EffectType.DENY,
                "UNANIMOUS_DENY",
                [r.id for r in deny_rules],
                [],
                [],
            )

        # 4. Both ALLOW and DENY rules fired
        # Step 4.1: Check for mutual overrides (contradiction)
        for a in allow_rules:
            for d in deny_rules:
                if d.id in a.overrides and a.id in d.overrides:
                    finding = Finding(
                        type=FindingType.CONTRADICTION,
                        severity=FindingSeverity.HIGH,
                        rule_ids=[a.id, d.id],
                        event_indices=[event_index],
                        trace=(
                            f"Contradiction detected at event {event_index} (day {event.day}): "
                            f"Mutual override cycle between ALLOW rule '{a.id}' and "
                            f"DENY rule '{d.id}'."
                        ),
                        details={"rule_a": a.id, "rule_d": d.id},
                    )
                    return (
                        EffectType.DENY,
                        "CONTRADICTION",
                        [],
                        [r.id for r in firing_rules],
                        [finding],
                    )

        # Check explicit overrides
        allow_overridden_ids = {
            r.id for r in allow_rules if any(r.id in d.overrides for d in deny_rules)
        }
        deny_overridden_ids = {
            r.id for r in deny_rules if any(r.id in a.overrides for a in allow_rules)
        }

        active_allow = [r for r in allow_rules if r.id not in allow_overridden_ids]
        active_deny = [r for r in deny_rules if r.id not in deny_overridden_ids]

        if active_allow and not active_deny:
            return (
                EffectType.ALLOW,
                "OVERRIDE_ALLOW",
                [r.id for r in active_allow],
                list(deny_overridden_ids),
                [],
            )

        if active_deny and not active_allow:
            return (
                EffectType.DENY,
                "OVERRIDE_DENY",
                [r.id for r in active_deny],
                list(allow_overridden_ids),
                [],
            )

        # Step 4.2: Priority Resolution among remaining active rules
        max_allow_priority = max(r.priority for r in active_allow)
        max_deny_priority = max(r.priority for r in active_deny)

        if max_allow_priority > max_deny_priority:
            winning_rules = [r for r in active_allow if r.priority == max_allow_priority]
            suppressed = [r.id for r in firing_rules if r not in winning_rules]
            return (
                EffectType.ALLOW,
                "PRIORITY_ALLOW",
                [r.id for r in winning_rules],
                suppressed,
                [],
            )

        if max_deny_priority > max_allow_priority:
            winning_rules = [r for r in active_deny if r.priority == max_deny_priority]
            suppressed = [r.id for r in firing_rules if r not in winning_rules]
            return (
                EffectType.DENY,
                "PRIORITY_DENY",
                [r.id for r in winning_rules],
                suppressed,
                [],
            )

        # Step 4.3: Equal priority tie
        conflicting_ids = [r.id for r in active_allow + active_deny]
        if max_allow_priority == 0 and max_deny_priority == 0:
            # Neither rule declared precedence
            finding = Finding(
                type=FindingType.CONTRADICTION,
                severity=FindingSeverity.HIGH,
                rule_ids=conflicting_ids,
                event_indices=[event_index],
                trace=(
                    f"Contradiction detected at event {event_index} (day {event.day}): "
                    f"Conflicting outcomes with no declared precedence. "
                    f"ALLOW rules {[r.id for r in active_allow]} and DENY rules {[r.id for r in active_deny]} "
                    f"both fired with default priority 0 and no overrides."
                ),
                details={
                    "allow_rules": [r.id for r in active_allow],
                    "deny_rules": [r.id for r in active_deny],
                    "priority": 0,
                },
            )
            return (
                EffectType.DENY,
                "CONTRADICTION",
                [],
                [r.id for r in firing_rules],
                [finding],
            )

        # Equal non-zero priority tie -> AMBIGUOUS
        finding = Finding(
            type=FindingType.AMBIGUITY,
            severity=FindingSeverity.HIGH,
            rule_ids=conflicting_ids,
            event_indices=[event_index],
            trace=(
                f"Ambiguity detected at event {event_index} (day {event.day}): "
                f"ALLOW rules {[r.id for r in active_allow]} and DENY rules {[r.id for r in active_deny]} "
                f"tied at equal priority {max_allow_priority} with no overriding precedence."
            ),
            details={
                "allow_rules": [r.id for r in active_allow],
                "deny_rules": [r.id for r in active_deny],
                "priority": max_allow_priority,
            },
        )
        return (
            EffectType.DENY,
            "AMBIGUOUS",
            [],
            [r.id for r in firing_rules],
            [finding],
        )

    def _apply_payload_attributes(self, state: State, payload: dict[str, Any]) -> None:
        """Apply non-decision payload attributes to state (e.g. item_damaged)."""
        valid_fields = {f.value: f for f in StateField}
        bool_fields = {
            "order_placed",
            "item_delivered",
            "replacement_requested",
            "replacement_cancelled",
            "replacement_active",
            "replacement_completed",
            "refund_requested",
            "refund_completed",
            "return_received",
            "item_damaged",
            "is_final_sale",
            "item_opened",
            "refund_eligibility_restored",
            "action_denied",
            "chargeback_active",
        }
        float_fields = {"amount_paid", "refund_amount"}
        int_fields = {
            "order_day",
            "delivery_day",
            "days_since_delivery",
            "replacement_request_day",
            "replacement_cancel_day",
            "replacement_completed_day",
            "refund_request_day",
            "refund_completed_day",
        }

        for k, v in payload.items():
            if k in valid_fields:
                field_name = valid_fields[k].value
                if k in bool_fields and not isinstance(v, bool):
                    setattr(state, field_name, bool(v))
                elif k in float_fields and not isinstance(v, float):
                    try:
                        setattr(state, field_name, float(v))
                    except (ValueError, TypeError):
                        pass
                elif k in int_fields and not isinstance(v, int):
                    try:
                        setattr(state, field_name, int(v))
                    except (ValueError, TypeError):
                        pass
                else:
                    setattr(state, field_name, v)

    def run(
        self,
        journey: list[Event],
        initial_state: State | None = None,
        invariant_registry: Any = None,
    ) -> SimulationResult:
        """Simulate a customer journey deterministically."""
        events = sorted(journey, key=lambda e: e.day)
        state = copy.deepcopy(initial_state) if initial_state is not None else State()

        registry = invariant_registry or self.invariant_registry

        outcomes: list[EventOutcome] = []
        event_traces: list[EventTrace] = []
        all_findings: list[Finding] = []

        decision_events = {
            EventType.REFUND_REQUESTED: DecisionType.REFUND,
            EventType.REPLACEMENT_REQUESTED: DecisionType.REPLACEMENT,
        }

        for idx, event in enumerate(events):
            state_before = copy.deepcopy(state)
            state.update_derived_day(event.day)
            self._apply_payload_attributes(state, event.payload)

            step_findings: list[Finding] = []

            if event.event_type not in decision_events:
                # Non-decision event processing
                if event.event_type == EventType.ORDER_PLACED:
                    state.order_placed = True
                    state.order_day = event.day
                    if "amount_paid" in event.payload:
                        state.amount_paid = float(event.payload["amount_paid"])
                elif event.event_type == EventType.ITEM_DELIVERED:
                    state.item_delivered = True
                    state.delivery_day = event.day
                    state.update_derived_day(event.day)
                elif event.event_type == EventType.ITEM_DAMAGED_REPORTED:
                    state.item_damaged = True
                elif event.event_type == EventType.REPLACEMENT_CANCELLED:
                    state.replacement_cancelled = True
                    state.replacement_cancel_day = event.day
                    state.replacement_active = False
                elif event.event_type == EventType.ORDER_CANCELLED:
                    state.order_placed = False
                elif event.event_type == EventType.RETURN_RECEIVED:
                    state.return_received = True
                elif event.event_type == EventType.REFUND_COMPLETED:
                    state.refund_completed = True
                    state.refund_completed_day = event.day
                    if "refund_amount" in event.payload:
                        state.refund_amount = float(event.payload["refund_amount"])
                    elif state.refund_amount == 0.0 and state.amount_paid > 0.0:
                        state.refund_amount = state.amount_paid
                elif event.event_type == EventType.REPLACEMENT_DELIVERED:
                    state.replacement_completed = True
                    state.replacement_completed_day = event.day
                    state.replacement_active = False
                elif event.event_type == EventType.CHARGEBACK_FILED:
                    state.chargeback_active = True
                elif event.event_type == EventType.CHARGEBACK_RESOLVED:
                    state.chargeback_active = False

                # Run invariant checks if registry provided
                if registry:
                    step_findings.extend(registry.check_all(state, event, idx))

                all_findings.extend(step_findings)
                state_after = copy.deepcopy(state)
                trace = EventTrace(
                    event_index=idx,
                    day=event.day,
                    event_type=event.event_type,
                    is_decision_event=False,
                    rules_evaluated=[],
                    rules_fired=[],
                    evaluations=[],
                    resolution_type="NON_DECISION",
                    outcome=EffectType.ALLOW,
                    active_rules=[],
                    suppressed_rules=[],
                    findings=step_findings,
                    state_before=state_before,
                    state_after=state_after,
                    explanation=f"Processed non-decision event {event.event_type.value}.",
                )
                outcome = EventOutcome(
                    event_index=idx,
                    day=event.day,
                    event_type=event.event_type,
                    outcome=EffectType.ALLOW,
                    action_applied=True,
                    resolution_type="NON_DECISION",
                    findings=step_findings,
                )
                outcomes.append(outcome)
                event_traces.append(trace)
                continue

            # Decision event processing
            expected_decision = decision_events[event.event_type]
            triggered_rules = [
                r
                for r in self.rules
                if r.trigger == event.event_type and r.decision == expected_decision
            ]

            evaluated_rule_ids = [r.id for r in triggered_rules]
            fired_rules: list[Rule] = []
            rule_eval_traces: list[RuleEvaluationTrace] = []

            for r in triggered_rules:
                passed, leaf_evals = evaluate_condition_tree(r.when, state)
                reason = "All conditions passed" if passed else "Condition failed"
                rule_eval_traces.append(
                    RuleEvaluationTrace(
                        rule_id=r.id,
                        rule_name=r.name,
                        effect=r.effect,
                        priority=r.priority,
                        fired=passed,
                        leaf_evaluations=leaf_evals,
                        reason=reason,
                    )
                )
                if passed:
                    fired_rules.append(r)

            outcome_effect, res_type, active_ids, suppressed_ids, resolution_findings = (
                self._resolve_conflict(fired_rules, idx, event)
            )

            step_findings.extend(resolution_findings)

            # Apply action semantics if ALLOW
            action_applied = outcome_effect == EffectType.ALLOW
            if action_applied:
                state.action_denied = False
                if event.event_type == EventType.REFUND_REQUESTED:
                    state.refund_requested = True
                    state.refund_request_day = event.day
                elif event.event_type == EventType.REPLACEMENT_REQUESTED:
                    state.replacement_requested = True
                    state.replacement_request_day = event.day
                    state.replacement_active = True

                # Apply state_updates from winning active rules
                active_rule_objs = [r for r in fired_rules if r.id in active_ids]
                for r in active_rule_objs:
                    if r.state_updates:
                        for k, v in r.state_updates.items():
                            field_name = k.value if isinstance(k, StateField) else k
                            setattr(state, field_name, v)
            else:
                # DENIAL SEMANTICS: Action does NOT take effect
                state.action_denied = True
                if event.event_type == EventType.REFUND_REQUESTED:
                    state.refund_requested = False
                elif event.event_type == EventType.REPLACEMENT_REQUESTED:
                    state.replacement_requested = False

            # Run invariant checks if registry provided
            if registry:
                step_findings.extend(registry.check_all(state, event, idx))

            all_findings.extend(step_findings)
            state_after = copy.deepcopy(state)

            trace = EventTrace(
                event_index=idx,
                day=event.day,
                event_type=event.event_type,
                is_decision_event=True,
                rules_evaluated=evaluated_rule_ids,
                rules_fired=[r.id for r in fired_rules],
                evaluations=rule_eval_traces,
                resolution_type=res_type,
                outcome=outcome_effect,
                active_rules=active_ids,
                suppressed_rules=suppressed_ids,
                findings=step_findings,
                state_before=state_before,
                state_after=state_after,
                explanation=(
                    f"Decision event {event.event_type.value}: outcome={outcome_effect.value} "
                    f"via {res_type} (active={active_ids})."
                ),
            )
            outcome = EventOutcome(
                event_index=idx,
                day=event.day,
                event_type=event.event_type,
                outcome=outcome_effect,
                action_applied=action_applied,
                resolution_type=res_type,
                findings=step_findings,
            )
            outcomes.append(outcome)
            event_traces.append(trace)

        return SimulationResult(
            outcomes=outcomes,
            final_state=state,
            trace=Trace(event_traces=event_traces),
            findings=all_findings,
        )
