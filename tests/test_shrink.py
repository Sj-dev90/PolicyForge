"""Tests for shrink.py delta debugging (ddmin) and day shrinking."""

import json
from pathlib import Path
import pytest

from policyforge.models import (
    EventType,
    FindingType,
    Rule,
    Event,
)
from policyforge.engine import PolicyEngine
from policyforge.shrink import shrink_journey


def _load_rules_v1() -> list[Rule]:
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        return [Rule.model_validate(r) for r in json.load(f)]


def test_shrink_canonical_journey():
    rules = _load_rules_v1()
    engine = PolicyEngine(rules=rules)

    # Canonical journey (4 events)
    canonical_journey = [
        Event(event_type=EventType.ITEM_DELIVERED, day=0),
        Event(event_type=EventType.REPLACEMENT_REQUESTED, day=25),
        Event(event_type=EventType.REPLACEMENT_CANCELLED, day=35),
        Event(event_type=EventType.REFUND_REQUESTED, day=36),
    ]

    target_sig = (
        FindingType.CONTRADICTION,
        ("rule_refund_after_replacement_cancelled", "rule_refund_past_deadline"),
    )

    result = shrink_journey(engine, canonical_journey, target_signature=target_sig)

    assert result.original_journey == canonical_journey
    assert result.engine_runs > 0
    assert result.target_signature == target_sig
    assert result.final_finding.type == FindingType.CONTRADICTION
    assert set(result.final_finding.rule_ids) == {
        "rule_refund_after_replacement_cancelled",
        "rule_refund_past_deadline",
    }

    # Day shrinking: Day 36 should shrink to day 31 (smallest integer > 30)
    refund_event = [e for e in result.minimal_journey if e.event_type == EventType.REFUND_REQUESTED][0]
    assert refund_event.day == 31

    # Earlier events should be shrunk down towards 0
    assert result.minimal_journey[0].day == 0


def test_shrink_padded_12_event_journey():
    rules = _load_rules_v1()
    engine = PolicyEngine(rules=rules)

    # 12-event journey padded with extraneous noise events
    padded_journey = [
        Event(event_type=EventType.ORDER_PLACED, day=0),
        Event(event_type=EventType.ITEM_DELIVERED, day=0),
        Event(event_type=EventType.ITEM_DAMAGED_REPORTED, day=2),
        Event(event_type=EventType.ITEM_DAMAGED_REPORTED, day=4),
        Event(event_type=EventType.REPLACEMENT_REQUESTED, day=10),
        Event(event_type=EventType.ITEM_DAMAGED_REPORTED, day=12),
        Event(event_type=EventType.RETURN_RECEIVED, day=15),
        Event(event_type=EventType.REPLACEMENT_CANCELLED, day=20),
        Event(event_type=EventType.ORDER_PLACED, day=22),
        Event(event_type=EventType.RETURN_RECEIVED, day=28),
        Event(event_type=EventType.REFUND_REQUESTED, day=40),
        Event(event_type=EventType.RETURN_RECEIVED, day=42),
    ]

    assert len(padded_journey) == 12

    target_sig = (
        FindingType.CONTRADICTION,
        ("rule_refund_after_replacement_cancelled", "rule_refund_past_deadline"),
    )

    result = shrink_journey(engine, padded_journey, target_signature=target_sig)

    # Original has 12 events
    assert len(result.original_journey) == 12
    # Minimal journey should have removed noise events (only delivery, replacement req, cancel, and refund req needed)
    assert len(result.minimal_journey) <= 4

    # The minimal journey reproduces the exact same failure
    final_res = engine.run(result.minimal_journey)
    contra_findings = [
        f for f in final_res.findings
        if f.type == FindingType.CONTRADICTION and set(f.rule_ids) == {
            "rule_refund_after_replacement_cancelled",
            "rule_refund_past_deadline",
        }
    ]
    assert len(contra_findings) == 1

    # Verify that refund event day shrank from 40 down to 31
    refund_event = [e for e in result.minimal_journey if e.event_type == EventType.REFUND_REQUESTED][0]
    assert refund_event.day == 31
