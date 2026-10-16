"""Tests for scenarios.py: boundary generation, pairwise generation, LLM scenario validator, and suite execution."""

import json
from pathlib import Path
import pytest

from policyforge.models import (
    EventType,
    Rule,
    Event,
)
from policyforge.scenarios import (
    generate_boundary_scenarios,
    generate_pairwise_scenarios,
    validate_scenario,
    run_suite,
)


def _load_rules_v1() -> list[Rule]:
    rules_path = Path(__file__).resolve().parent.parent / "data" / "novacart" / "rules_v1.json"
    with open(rules_path, "r", encoding="utf-8") as f:
        return [Rule.model_validate(r) for r in json.load(f)]


# ---------------------------------------------------------------------------
# 1. Boundary Scenario Generation Tests
# ---------------------------------------------------------------------------

def test_generate_boundary_scenarios():
    rules = _load_rules_v1()
    scenarios = generate_boundary_scenarios(rules)

    # Must produce a substantial set of boundary tests
    assert len(scenarios) > 50

    # Ensure days tested include threshold-1, threshold, and threshold+1 for 30 (e.g. 29, 30, 31)
    boundary_days = {s.journey[-1].day for s in scenarios}
    for expected_day in (13, 14, 15, 29, 30, 31, 44, 45, 46, 59, 60, 61):
        assert expected_day in boundary_days

    # Ensure flags are combined
    has_damaged = any(s.journey[-1].payload.get("item_damaged") is True for s in scenarios)
    has_vip = any(s.journey[-1].payload.get("customer_tier") == "VIP" for s in scenarios)
    has_final_sale = any(s.journey[-1].payload.get("is_final_sale") is True for s in scenarios)
    has_chargeback = any(s.journey[-1].payload.get("chargeback_active") is True for s in scenarios)

    assert has_damaged and has_vip and has_final_sale and has_chargeback


# ---------------------------------------------------------------------------
# 2. Pairwise Scenario Generation Tests
# ---------------------------------------------------------------------------

def test_generate_pairwise_scenarios():
    scenarios = generate_pairwise_scenarios()
    assert len(scenarios) >= 30

    # Check that diverse event types are present
    all_event_types = {e.event_type for s in scenarios for e in s.journey}
    assert EventType.ITEM_DELIVERED in all_event_types
    assert EventType.REPLACEMENT_REQUESTED in all_event_types
    assert EventType.REPLACEMENT_CANCELLED in all_event_types
    assert EventType.REFUND_REQUESTED in all_event_types


# ---------------------------------------------------------------------------
# 3. LLM Scenario Validator Tests
# ---------------------------------------------------------------------------

def test_validate_scenario_valid():
    valid_data = [
        {"event_type": "ORDER_PLACED", "day": 0, "payload": {"amount_paid": 50.0}},
        {"event_type": "ITEM_DELIVERED", "day": 2, "payload": {}},
        {"event_type": "REFUND_REQUESTED", "day": 10, "payload": {"customer_tier": "VIP"}},
    ]
    is_valid, reason = validate_scenario(valid_data)
    assert is_valid is True
    assert reason is None


def test_validate_scenario_rejects_unknown_event_type():
    invalid_data = [
        {"event_type": "USER_ANGRY_CALL", "day": 1, "payload": {}}
    ]
    is_valid, reason = validate_scenario(invalid_data)
    assert is_valid is False
    assert "Unknown event type 'USER_ANGRY_CALL'" in reason


def test_validate_scenario_rejects_impossible_ordering():
    invalid_data = [
        {"event_type": "ITEM_DELIVERED", "day": 10, "payload": {}},
        {"event_type": "REFUND_REQUESTED", "day": 5, "payload": {}},
    ]
    is_valid, reason = validate_scenario(invalid_data)
    assert is_valid is False
    assert "Impossible ordering" in reason


def test_validate_scenario_rejects_negative_day():
    invalid_data = [
        {"event_type": "ITEM_DELIVERED", "day": -3, "payload": {}}
    ]
    is_valid, reason = validate_scenario(invalid_data)
    assert is_valid is False
    assert "negative day" in reason


def test_validate_scenario_rejects_unknown_payload_field():
    invalid_data = [
        {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {"fictional_rating": 5}}
    ]
    is_valid, reason = validate_scenario(invalid_data)
    assert is_valid is False
    assert "Unknown payload field 'fictional_rating'" in reason


def test_validate_scenario_rejects_invalid_customer_tier():
    invalid_data = [
        {"event_type": "REFUND_REQUESTED", "day": 1, "payload": {"customer_tier": "SUPER_VIP"}}
    ]
    is_valid, reason = validate_scenario(invalid_data)
    assert is_valid is False
    assert "Invalid customer_tier 'SUPER_VIP'" in reason


# ---------------------------------------------------------------------------
# 4. Suite Runner Execution & Summary Table Test
# ---------------------------------------------------------------------------

def test_run_suite_and_summary_table():
    rules = _load_rules_v1()
    boundary_scenarios = generate_boundary_scenarios(rules)
    pairwise_scenarios = generate_pairwise_scenarios()
    suite = boundary_scenarios + pairwise_scenarios

    result = run_suite(rules, suite)

    assert result.total_scenarios == len(suite)
    assert result.passed_scenarios + result.failed_scenarios == result.total_scenarios
    assert len(result.deduplicated_findings) > 0

    # Ensure minimal counterexamples were generated for each unique finding
    for sig in result.deduplicated_findings:
        assert sig in result.minimal_counterexamples
        shrink_res = result.minimal_counterexamples[sig]
        assert len(shrink_res.minimal_journey) <= len(shrink_res.original_journey)

    # Generate and print the summary table for rules_v1.json
    table_str = result.summary_table()
    assert "# PolicyForge Scenario Suite Execution Summary" in table_str
    assert "| Finding Type |" in table_str
    print("\n" + table_str)
