"""Tests for PolicyForge simulation engine, event semantics, and conflict resolution."""

import json
from pathlib import Path
import pytest

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    RuleSource,
    Rule,
    State,
    Event,
    FindingType,
    FindingSeverity,
)
from policyforge.engine import PolicyEngine


def _make_rule(
    rule_id: str,
    decision: DecisionType,
    trigger: EventType,
    effect: EffectType,
    when_dict: dict,
    priority: int = 0,
    overrides: list[str] | None = None,
    state_updates: dict | None = None,
) -> Rule:
    return Rule(
        id=rule_id,
        name=f"Rule {rule_id}",
        decision=decision,
        trigger=trigger,
        effect=effect,
        when=when_dict,
        priority=priority,
        overrides=overrides or [],
        state_updates=state_updates,
        source=RuleSource(doc_name="Doc", verbatim_sentence="Sentence"),
    )


# ---------------------------------------------------------------------------
# 1. Table-Driven Tests for Each Event Type Semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "event_type,payload,expected_state_attrs",
    [
        (
            EventType.ORDER_PLACED,
            {"is_final_sale": True},
            {"order_placed": True, "order_day": 2, "is_final_sale": True},
        ),
        (
            EventType.ITEM_DELIVERED,
            {},
            {"item_delivered": True, "delivery_day": 2, "days_since_delivery": 0},
        ),
        (
            EventType.ITEM_DAMAGED_REPORTED,
            {},
            {"item_damaged": True},
        ),
        (
            EventType.REPLACEMENT_CANCELLED,
            {},
            {"replacement_cancelled": True, "replacement_cancel_day": 2},
        ),
        (
            EventType.ORDER_CANCELLED,
            {},
            {"order_placed": False},
        ),
        (
            EventType.RETURN_RECEIVED,
            {},
            {"return_received": True},
        ),
    ],
)
def test_non_decision_event_semantics(event_type, payload, expected_state_attrs):
    engine = PolicyEngine(rules=[])
    event = Event(event_type=event_type, day=2, payload=payload)
    result = engine.run([event])

    assert result.outcomes[0].outcome == EffectType.ALLOW
    assert result.outcomes[0].resolution_type == "NON_DECISION"
    assert result.outcomes[0].action_applied is True

    for attr, val in expected_state_attrs.items():
        assert getattr(result.final_state, attr) == val


# ---------------------------------------------------------------------------
# 2. Decision Event Denial Semantics
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "decision_event,decision_type,state_attr",
    [
        (EventType.REFUND_REQUESTED, DecisionType.REFUND, "refund_requested"),
        (EventType.REPLACEMENT_REQUESTED, DecisionType.REPLACEMENT, "replacement_requested"),
    ],
)
def test_decision_event_denial_semantics(decision_event, decision_type, state_attr):
    # Rule that always denies
    deny_rule = _make_rule(
        "deny_always",
        decision_type,
        decision_event,
        EffectType.DENY,
        {"field": "item_delivered", "op": "IS_FALSE", "value": False},
        priority=0,
    )
    engine = PolicyEngine(rules=[deny_rule])
    event = Event(event_type=decision_event, day=5)

    result = engine.run([event])

    assert result.outcomes[0].outcome == EffectType.DENY
    assert result.outcomes[0].action_applied is False
    assert getattr(result.final_state, state_attr) is False
    assert result.final_state.action_denied is True


# ---------------------------------------------------------------------------
# 3. Table-Driven Tests for Each Resolution Branch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rules,expected_outcome,expected_res_type,expected_finding_type",
    [
        # Branch 1: DEFAULT_DENY (No rules fire -> GAP)
        (
            [],
            EffectType.DENY,
            "DEFAULT_DENY",
            FindingType.GAP,
        ),
        # Branch 2: UNANIMOUS_ALLOW
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                ),
            ],
            EffectType.ALLOW,
            "UNANIMOUS_ALLOW",
            None,
        ),
        # Branch 3: UNANIMOUS_DENY
        (
            [
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                ),
            ],
            EffectType.DENY,
            "UNANIMOUS_DENY",
            None,
        ),
        # Branch 4: OVERRIDE_ALLOW (ALLOW overrides DENY)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    overrides=["r_deny"],
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                ),
            ],
            EffectType.ALLOW,
            "OVERRIDE_ALLOW",
            None,
        ),
        # Branch 5: OVERRIDE_DENY (DENY overrides ALLOW)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    overrides=["r_allow"],
                ),
            ],
            EffectType.DENY,
            "OVERRIDE_DENY",
            None,
        ),
        # Branch 6: PRIORITY_ALLOW (ALLOW priority > DENY priority)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=5,
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=2,
                ),
            ],
            EffectType.ALLOW,
            "PRIORITY_ALLOW",
            None,
        ),
        # Branch 7: PRIORITY_DENY (DENY priority > ALLOW priority)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=3,
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=8,
                ),
            ],
            EffectType.DENY,
            "PRIORITY_DENY",
            None,
        ),
        # Branch 8: CONTRADICTION (Equal priority at 0, no overrides)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=0,
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=0,
                ),
            ],
            EffectType.DENY,
            "CONTRADICTION",
            FindingType.CONTRADICTION,
        ),
        # Branch 9: AMBIGUOUS (Equal non-zero priority tie)
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=4,
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    priority=4,
                ),
            ],
            EffectType.DENY,
            "AMBIGUOUS",
            FindingType.AMBIGUITY,
        ),
        # Branch 10: Mutual override cycle contradiction
        (
            [
                _make_rule(
                    "r_allow",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.ALLOW,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    overrides=["r_deny"],
                ),
                _make_rule(
                    "r_deny",
                    DecisionType.REFUND,
                    EventType.REFUND_REQUESTED,
                    EffectType.DENY,
                    {"field": "order_placed", "op": "IS_TRUE", "value": True},
                    overrides=["r_allow"],
                ),
            ],
            EffectType.DENY,
            "CONTRADICTION",
            FindingType.CONTRADICTION,
        ),
    ],
)
def test_conflict_resolution_branches(
    rules,
    expected_outcome,
    expected_res_type,
    expected_finding_type,
):
    engine = PolicyEngine(rules=rules)
    journey = [
        Event(event_type=EventType.ORDER_PLACED, day=1),
        Event(event_type=EventType.REFUND_REQUESTED, day=2),
    ]
    result = engine.run(journey)

    outcome = result.outcomes[1]
    assert outcome.outcome == expected_outcome
    assert outcome.resolution_type == expected_res_type

    if expected_finding_type is not None:
        assert len(result.findings) >= 1
        assert any(f.type == expected_finding_type for f in result.findings)
    else:
        assert len(result.findings) == 0


# ---------------------------------------------------------------------------
# 4. Canonical NovaCart Journey Test (with rules_v1.json)
# ---------------------------------------------------------------------------

def test_canonical_novacart_journey():
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules_data = json.load(f)

    rules = [Rule.model_validate(r) for r in rules_data]
    assert len(rules) == 12

    engine = PolicyEngine(rules=rules)

    # Canonical journey:
    # Day 0: ITEM_DELIVERED
    # Day 25: REPLACEMENT_REQUESTED
    # Day 35: REPLACEMENT_CANCELLED
    # Day 36: REFUND_REQUESTED
    journey = [
        Event(event_type=EventType.ITEM_DELIVERED, day=0),
        Event(event_type=EventType.REPLACEMENT_REQUESTED, day=25),
        Event(event_type=EventType.REPLACEMENT_CANCELLED, day=35),
        Event(event_type=EventType.REFUND_REQUESTED, day=36),
    ]

    result = engine.run(journey)

    # 4 events processed
    assert len(result.outcomes) == 4
    assert len(result.trace.event_traces) == 4

    # Event 0: ITEM_DELIVERED (day 0)
    e0_trace = result.trace.event_traces[0]
    assert e0_trace.event_type == EventType.ITEM_DELIVERED
    assert e0_trace.state_after.item_delivered is True
    assert e0_trace.state_after.delivery_day == 0
    assert e0_trace.state_after.days_since_delivery == 0

    # Event 1: REPLACEMENT_REQUESTED (day 25)
    e1_trace = result.trace.event_traces[1]
    assert e1_trace.event_type == EventType.REPLACEMENT_REQUESTED
    assert e1_trace.outcome == EffectType.ALLOW
    assert e1_trace.resolution_type == "UNANIMOUS_ALLOW"
    assert "rule_replacement_standard_window" in e1_trace.rules_fired
    assert e1_trace.state_after.replacement_requested is True
    assert e1_trace.state_after.replacement_request_day == 25
    assert e1_trace.state_after.days_since_delivery == 25

    # Event 2: REPLACEMENT_CANCELLED (day 35)
    e2_trace = result.trace.event_traces[2]
    assert e2_trace.event_type == EventType.REPLACEMENT_CANCELLED
    assert e2_trace.state_after.replacement_cancelled is True
    assert e2_trace.state_after.replacement_cancel_day == 35

    # Event 3: REFUND_REQUESTED (day 36) -> THE CONFLICT!
    e3_trace = result.trace.event_traces[3]
    assert e3_trace.event_type == EventType.REFUND_REQUESTED
    # Fired both: rule_refund_past_deadline (DENY, p=0) and rule_refund_after_replacement_cancelled (ALLOW, p=0)
    assert set(e3_trace.rules_fired) == {
        "rule_refund_past_deadline",
        "rule_refund_after_replacement_cancelled",
    }
    assert e3_trace.resolution_type == "CONTRADICTION"
    assert e3_trace.outcome == EffectType.DENY
    # Action does not take effect
    assert e3_trace.state_after.refund_requested is False
    assert e3_trace.state_after.action_denied is True

    # Findings should contain the contradiction on event index 3
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.type == FindingType.CONTRADICTION
    assert finding.severity == FindingSeverity.HIGH
    assert set(finding.rule_ids) == {
        "rule_refund_past_deadline",
        "rule_refund_after_replacement_cancelled",
    }
    assert finding.event_indices == [3]
    assert "Contradiction" in finding.trace

    # Trace must contain leaf evaluations showing why conditions evaluated as they did
    fired_traces = {t.rule_id: t for t in e3_trace.evaluations if t.fired}
    assert "rule_refund_past_deadline" in fired_traces
    assert fired_traces["rule_refund_past_deadline"].leaf_evaluations[0].actual_value == 36
    assert fired_traces["rule_refund_past_deadline"].leaf_evaluations[0].passed is True


# ---------------------------------------------------------------------------
# 5. Hypothesis Property-Based Invariant: Determinism
# ---------------------------------------------------------------------------

from hypothesis import given, strategies as st


@given(
    st.lists(
        st.tuples(
            st.sampled_from(list(EventType)),
            st.integers(min_value=0, max_value=100),
        ),
        min_size=1,
        max_size=10,
    )
)
def test_simulation_determinism_property(event_specs):
    """Determinism invariant: same rules + same journey = same result, always."""
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = [Rule.model_validate(r) for r in json.load(f)]

    engine = PolicyEngine(rules=rules)
    journey = [Event(event_type=et, day=d) for et, d in event_specs]

    result1 = engine.run(journey)
    result2 = engine.run(journey)

    assert result1.model_dump() == result2.model_dump()
