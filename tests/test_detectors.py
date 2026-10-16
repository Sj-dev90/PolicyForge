"""Tests for PolicyForge detectors: contradiction, policy gap, ambiguity, invariants, dead rules, and Hypothesis property tests."""

import json
from pathlib import Path
import pytest
from hypothesis import given, strategies as st, settings

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
    CustomerTier,
    RuleSource,
    Rule,
    State,
    Event,
    FindingType,
    FindingSeverity,
    Finding,
)
from policyforge.engine import PolicyEngine
from policyforge.detectors import (
    InvariantRegistry,
    create_default_invariant_registry,
    detect_dead_rules,
    PolicyDetector,
)


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
# 1. Contradiction Detection Tests
# ---------------------------------------------------------------------------

def test_contradiction_detection():
    # Two rules with opposing effects, equal default priority 0, no overrides
    r_allow = _make_rule(
        "r_allow",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.ALLOW,
        {"field": "order_placed", "op": "IS_TRUE", "value": True},
        priority=0,
    )
    r_deny = _make_rule(
        "r_deny",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.DENY,
        {"field": "order_placed", "op": "IS_TRUE", "value": True},
        priority=0,
    )

    detector = PolicyDetector(rules=[r_allow, r_deny])
    journey = [
        Event(event_type=EventType.ORDER_PLACED, day=1),
        Event(event_type=EventType.REFUND_REQUESTED, day=2),
    ]
    res = detector.verify_journey(journey)

    contra_findings = [f for f in res.findings if f.type == FindingType.CONTRADICTION]
    assert len(contra_findings) == 1
    f = contra_findings[0]
    assert f.severity == FindingSeverity.HIGH
    assert set(f.rule_ids) == {"r_allow", "r_deny"}
    assert f.event_indices == [1]
    assert "Contradiction detected" in f.trace


# ---------------------------------------------------------------------------
# 2. Policy Gap Tests (Configurable Default Outcome)
# ---------------------------------------------------------------------------

def test_policy_gap_default_deny():
    # No rules registered -> decision event has no matching rule
    detector = PolicyDetector(rules=[], default_decision_outcome=EffectType.DENY)
    journey = [Event(event_type=EventType.REFUND_REQUESTED, day=5)]
    res = detector.verify_journey(journey)

    assert res.outcomes[0].outcome == EffectType.DENY
    assert res.outcomes[0].resolution_type == "DEFAULT_DENY"
    gap_findings = [f for f in res.findings if f.type == FindingType.POLICY_GAP]
    assert len(gap_findings) == 1
    assert "Policy gap detected" in gap_findings[0].trace
    assert gap_findings[0].event_indices == [0]


def test_policy_gap_configurable_default_allow():
    # Configured to default to ALLOW when policy has a gap
    detector = PolicyDetector(rules=[], default_decision_outcome=EffectType.ALLOW)
    journey = [Event(event_type=EventType.REFUND_REQUESTED, day=5)]
    res = detector.verify_journey(journey)

    assert res.outcomes[0].outcome == EffectType.ALLOW
    assert res.outcomes[0].resolution_type == "DEFAULT_ALLOW"
    gap_findings = [f for f in res.findings if f.type == FindingType.POLICY_GAP]
    assert len(gap_findings) == 1
    assert gap_findings[0].details["default_outcome"] == "ALLOW"


# ---------------------------------------------------------------------------
# 3. Ambiguity Detection Tests
# ---------------------------------------------------------------------------

def test_ambiguity_detection():
    # Two rules with opposing effects tied at priority 5
    r_allow = _make_rule(
        "r_allow",
        DecisionType.REPLACEMENT,
        EventType.REPLACEMENT_REQUESTED,
        EffectType.ALLOW,
        {"field": "order_placed", "op": "IS_TRUE", "value": True},
        priority=5,
    )
    r_deny = _make_rule(
        "r_deny",
        DecisionType.REPLACEMENT,
        EventType.REPLACEMENT_REQUESTED,
        EffectType.DENY,
        {"field": "order_placed", "op": "IS_TRUE", "value": True},
        priority=5,
    )

    detector = PolicyDetector(rules=[r_allow, r_deny])
    journey = [
        Event(event_type=EventType.ORDER_PLACED, day=1),
        Event(event_type=EventType.REPLACEMENT_REQUESTED, day=2),
    ]
    res = detector.verify_journey(journey)

    ambig_findings = [f for f in res.findings if f.type == FindingType.AMBIGUITY]
    assert len(ambig_findings) == 1
    f = ambig_findings[0]
    assert f.severity == FindingSeverity.HIGH
    assert set(f.rule_ids) == {"r_allow", "r_deny"}
    assert "Ambiguity detected" in f.trace


# ---------------------------------------------------------------------------
# 4. Invariant Registry & Violation Tests
# ---------------------------------------------------------------------------

def test_invariant_full_refund_and_completed_replacement():
    registry = create_default_invariant_registry()
    state = State(refund_completed=True, replacement_completed=True)
    findings = registry.check_all(state, event_index=2)

    assert any(
        f.type == FindingType.INVARIANT_VIOLATION
        and f.details.get("invariant_id") == "no_duplicate_restitution"
        for f in findings
    )


def test_invariant_refund_exceeds_amount_paid():
    registry = create_default_invariant_registry()
    state = State(amount_paid=100.0, refund_amount=150.0)
    findings = registry.check_all(state, event_index=1)

    assert any(
        f.type == FindingType.INVARIANT_VIOLATION
        and f.details.get("invariant_id") == "refund_le_amount_paid"
        for f in findings
    )


def test_invariant_replacement_active_and_cancelled():
    registry = create_default_invariant_registry()
    state = State(replacement_active=True, replacement_cancelled=True)
    findings = registry.check_all(state, event_index=3)

    assert any(
        f.type == FindingType.INVARIANT_VIOLATION
        and f.details.get("invariant_id") == "replacement_consistent_status"
        for f in findings
    )


def test_invariant_completion_before_request():
    registry = create_default_invariant_registry()
    # Refund completed with no prior request
    state_no_req = State(refund_completed=True, refund_requested=False)
    findings1 = registry.check_all(state_no_req, event_index=1)
    assert any("without any recorded refund request" in f.trace for f in findings1)

    # Replacement completed before request day
    state_early = State(
        replacement_requested=True,
        replacement_request_day=10,
        replacement_completed=True,
        replacement_completed_day=5,
    )
    findings2 = registry.check_all(state_early, event_index=2)
    assert any("prior to request" in f.trace for f in findings2)


def test_invariant_chargeback_active_with_completed_refund():
    registry = create_default_invariant_registry()
    state = State(chargeback_active=True, refund_completed=True)
    findings = registry.check_all(state, event_index=4)

    assert any(
        f.type == FindingType.INVARIANT_VIOLATION
        and f.details.get("invariant_id") == "no_chargeback_after_refund"
        for f in findings
    )


def test_custom_invariant_registration():
    registry = InvariantRegistry()

    @registry.register("custom_tier_check", "VIP No Return Received", "VIP test invariant")
    def custom_check(state: State, event: Event | None, event_index: int) -> Finding | None:
        if state.customer_tier == CustomerTier.VIP and state.return_received:
            return Finding(
                type=FindingType.INVARIANT_VIOLATION,
                severity=FindingSeverity.LOW,
                rule_ids=[],
                event_indices=[event_index],
                trace="Custom invariant triggered",
            )
        return None

    state_vip = State(customer_tier=CustomerTier.VIP, return_received=True)
    findings = registry.check_all(state_vip, event_index=0)
    assert len(findings) == 1
    assert findings[0].trace == "Custom invariant triggered"


# ---------------------------------------------------------------------------
# 5. Dead Rule Static Analysis Tests
# ---------------------------------------------------------------------------

def test_dead_rule_unsatisfiable_numeric_bounds():
    # days_since_delivery > 30 and days_since_delivery < 10
    dead_rule = _make_rule(
        "dead_numeric",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.ALLOW,
        {
            "all": [
                {"field": "days_since_delivery", "op": "GT", "value": 30},
                {"field": "days_since_delivery", "op": "LT", "value": 10},
            ]
        },
    )
    findings = detect_dead_rules([dead_rule])
    assert len(findings) == 1
    assert findings[0].type == FindingType.DEAD_RULE
    assert findings[0].details["category"] == "unsatisfiable"
    assert "Contradictory bounds" in findings[0].trace


def test_dead_rule_unsatisfiable_negative_days():
    # days_since_delivery < 0 is impossible
    dead_rule = _make_rule(
        "dead_neg_days",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.ALLOW,
        {"field": "days_since_delivery", "op": "LT", "value": 0},
    )
    findings = detect_dead_rules([dead_rule])
    assert len(findings) == 1
    assert findings[0].type == FindingType.DEAD_RULE


def test_dead_rule_unsatisfiable_contradictory_boolean():
    # item_delivered == True and item_delivered == False
    dead_rule = _make_rule(
        "dead_bool",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.ALLOW,
        {
            "all": [
                {"field": "item_delivered", "op": "IS_TRUE", "value": True},
                {"field": "item_delivered", "op": "IS_FALSE", "value": False},
            ]
        },
    )
    findings = detect_dead_rules([dead_rule])
    assert len(findings) == 1
    assert findings[0].type == FindingType.DEAD_RULE
    assert "Contradictory equality" in findings[0].trace


def test_dead_rule_always_overridden():
    # rule 1: refund allowed <= 15 days
    r1 = _make_rule(
        "r1_narrow",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.ALLOW,
        {"field": "days_since_delivery", "op": "LTE", "value": 15},
    )
    # rule 2: refund denied <= 30 days, overrides r1_narrow
    r2 = _make_rule(
        "r2_broad",
        DecisionType.REFUND,
        EventType.REFUND_REQUESTED,
        EffectType.DENY,
        {"field": "days_since_delivery", "op": "LTE", "value": 30},
        overrides=["r1_narrow"],
    )

    findings = detect_dead_rules([r1, r2])
    assert len(findings) == 1
    assert findings[0].type == FindingType.DEAD_RULE
    assert findings[0].details["category"] == "always_overridden"
    assert "r1_narrow" in findings[0].rule_ids
    assert "r2_broad" in findings[0].rule_ids


def test_satisfiable_rules_not_flagged_dead():
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = [Rule.model_validate(r) for r in json.load(f)]

    # None of the active 12 NovaCart rules should be flagged as dead
    findings = detect_dead_rules(rules)
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# 6. Hypothesis Property-Based Tests
# ---------------------------------------------------------------------------

payload_strategy = st.fixed_dictionaries(
    {},
    optional={
        "amount_paid": st.floats(min_value=0.0, max_value=500.0, allow_nan=False),
        "refund_amount": st.floats(min_value=0.0, max_value=500.0, allow_nan=False),
        "item_damaged": st.booleans(),
        "is_final_sale": st.booleans(),
    },
)

valid_event_strategy = st.tuples(
    st.sampled_from(list(EventType)),
    st.integers(min_value=0, max_value=60),
    payload_strategy,
)


@settings(max_examples=50)
@given(st.lists(valid_event_strategy, min_size=1, max_size=8))
def test_random_valid_journeys_never_crash(event_tuples):
    """Property 1: Random valid journeys never crash the engine."""
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = [Rule.model_validate(r) for r in json.load(f)]

    detector = PolicyDetector(rules=rules)
    journey = [
        Event(event_type=et, day=d, payload=p)
        for et, d, p in event_tuples
    ]

    result = detector.verify_journey(journey)
    assert len(result.outcomes) == len(journey)
    assert result.final_state is not None
    assert isinstance(result.findings, list)


@settings(max_examples=50)
@given(st.lists(valid_event_strategy, min_size=1, max_size=8))
def test_engine_determinism_property(event_tuples):
    """Property 2: Results are strictly deterministic across runs."""
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = [Rule.model_validate(r) for r in json.load(f)]

    detector = PolicyDetector(rules=rules)
    journey = [
        Event(event_type=et, day=d, payload=p)
        for et, d, p in event_tuples
    ]

    res1 = detector.verify_journey(journey)
    res2 = detector.verify_journey(journey)

    assert res1.model_dump() == res2.model_dump()


def test_invariants_hold_when_no_findings():
    """Property 3: Invariants hold on journeys that produce no findings."""
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        rules = [Rule.model_validate(r) for r in json.load(f)]

    detector = PolicyDetector(rules=rules)

    # Standard clean compliant journey:
    # 1. Order placed with $100 paid
    # 2. Delivered day 0
    # 3. Refund requested day 10 (well within 30 days) -> approved
    # 4. Refund completed day 12 with $100 refund
    journey = [
        Event(event_type=EventType.ORDER_PLACED, day=0, payload={"amount_paid": 100.0}),
        Event(event_type=EventType.ITEM_DELIVERED, day=0),
        Event(event_type=EventType.REFUND_REQUESTED, day=10),
        Event(event_type=EventType.REFUND_COMPLETED, day=12, payload={"refund_amount": 100.0}),
    ]

    result = detector.verify_journey(journey)

    # There should be 0 findings
    invariant_findings = [
        f for f in result.findings if f.type == FindingType.INVARIANT_VIOLATION
    ]
    assert len(invariant_findings) == 0
    assert len(result.findings) == 0

    # Explicitly run registry on final state
    reg_findings = detector.invariant_registry.check_all(result.final_state)
    assert len(reg_findings) == 0
