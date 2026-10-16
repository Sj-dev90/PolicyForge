"""Tests for PolicyForge models and closed-vocabulary schemas."""

import pytest
from pydantic import ValidationError

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
    CustomerTier,
    State,
    LeafCondition,
    AllCondition,
    AnyCondition,
    RuleSource,
    Rule,
    Finding,
    FindingType,
    FindingSeverity,
    Event,
    parse_condition_tree,
)


def test_closed_vocabulary_event_types():
    assert EventType.ORDER_PLACED == "ORDER_PLACED"
    assert EventType.REFUND_REQUESTED == "REFUND_REQUESTED"

    with pytest.raises(ValidationError):
        Event(event_type="INVALID_EVENT", day=1)


def test_closed_vocabulary_state_fields():
    state = State(order_placed=True, customer_tier=CustomerTier.VIP)
    assert state.order_placed is True
    assert state.customer_tier == CustomerTier.VIP

    # Forbid extra fields
    with pytest.raises(ValidationError):
        State(unknown_field="not_allowed")


def test_state_derived_day():
    state = State()
    state.update_derived_day(10)
    assert state.days_since_delivery is None

    state.item_delivered = True
    state.delivery_day = 5
    state.update_derived_day(5)
    assert state.days_since_delivery == 0

    state.update_derived_day(25)
    assert state.days_since_delivery == 20


def test_condition_tree_parsing_and_forbid_extra():
    # Leaf condition
    leaf = parse_condition_tree({
        "field": StateField.DAYS_SINCE_DELIVERY,
        "op": Operator.LTE,
        "value": 30,
    })
    assert isinstance(leaf, LeafCondition)
    assert leaf.field == StateField.DAYS_SINCE_DELIVERY

    # Extra field forbidden on leaf
    with pytest.raises(ValidationError):
        LeafCondition(
            field=StateField.DAYS_SINCE_DELIVERY,
            op=Operator.LTE,
            value=30,
            bogus_key="invalid",
        )

    # All condition
    tree_all = parse_condition_tree({
        "all": [
            {"field": "item_delivered", "op": "IS_TRUE", "value": True},
            {"field": "days_since_delivery", "op": "<=", "value": 30},
        ]
    })
    assert isinstance(tree_all, AllCondition)
    assert len(tree_all.all) == 2

    # Any condition
    tree_any = parse_condition_tree({
        "any": [
            {"field": "customer_tier", "op": "EQ", "value": "VIP"},
            {"field": "item_damaged", "op": "IS_TRUE", "value": True},
        ]
    })
    assert isinstance(tree_any, AnyCondition)
    assert len(tree_any.any) == 2


def test_rule_creation_and_validation():
    rule = Rule(
        id="test_rule",
        name="Test Rule",
        decision=DecisionType.REFUND,
        trigger=EventType.REFUND_REQUESTED,
        when={
            "all": [
                {"field": "days_since_delivery", "op": "LTE", "value": 30},
                {"field": "item_delivered", "op": "IS_TRUE", "value": True},
            ]
        },
        effect=EffectType.ALLOW,
        priority=1,
        overrides=["other_rule"],
        source=RuleSource(
            doc_name="Test Policy",
            verbatim_sentence="Test sentence for rule source.",
        ),
    )
    assert rule.id == "test_rule"
    assert rule.decision == DecisionType.REFUND
    assert rule.priority == 1
    assert rule.overrides == ["other_rule"]
    assert isinstance(rule.when, AllCondition)

    # Forbid invalid trigger
    with pytest.raises(ValidationError):
        Rule(
            id="bad_rule",
            name="Bad Rule",
            decision=DecisionType.REFUND,
            trigger="NON_EXISTENT_TRIGGER",
            when={"field": "days_since_delivery", "op": "LTE", "value": 30},
            effect=EffectType.ALLOW,
            source=RuleSource(doc_name="Doc", verbatim_sentence="Text"),
        )


def test_finding_structure():
    finding = Finding(
        type=FindingType.CONTRADICTION,
        severity=FindingSeverity.HIGH,
        rule_ids=["rule_1", "rule_2"],
        event_indices=[3],
        trace="Conflict detected between rule_1 and rule_2.",
    )
    assert finding.type == FindingType.CONTRADICTION
    assert finding.severity == FindingSeverity.HIGH
    assert finding.rule_ids == ["rule_1", "rule_2"]
    assert finding.event_indices == [3]
