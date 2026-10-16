"""Tests for FastAPI endpoints in policyforge.api.

Covers:
  - GET /api/health
  - GET /api/default-data
  - POST /api/compile
  - POST /api/simulate
  - POST /api/run-suite
  - POST /api/shrink
  - POST /api/diff
"""

from __future__ import annotations

import json
from pathlib import Path
from starlette.testclient import TestClient

from policyforge.api import app
from policyforge.models import Rule, Event, EventType, EffectType, DecisionType

client = TestClient(app)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "novacart"


def _get_v1_rules() -> list[dict]:
    p = DATA_DIR / "rules_v1.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _get_v2_rules() -> list[dict]:
    p = DATA_DIR / "rules_v2.json"
    return json.loads(p.read_text(encoding="utf-8"))


def test_api_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_api_default_data():
    resp = client.get("/api/default-data")
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert "rules_v1" in data
    assert "rules_v2" in data
    assert "sample_journeys" in data
    assert len(data["rules_v1"]) == 12
    assert len(data["rules_v2"]) == 13
    assert len(data["sample_journeys"]) >= 4


def test_api_simulate_canonical_journey():
    rules = _get_v1_rules()
    journey = [
        {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {}},
        {"event_type": "REPLACEMENT_REQUESTED", "day": 25, "payload": {}},
        {"event_type": "REPLACEMENT_CANCELLED", "day": 35, "payload": {}},
        {"event_type": "REFUND_REQUESTED", "day": 36, "payload": {}},
    ]

    resp = client.post(
        "/api/simulate",
        json={"rules": rules, "journey": journey},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["outcomes"]) == 4
    # Event 3 is the contradiction
    e3 = data["outcomes"][3]
    assert e3["event_type"] == "REFUND_REQUESTED"
    assert e3["outcome"] == "DENY"
    assert e3["resolution_type"] == "CONTRADICTION"
    assert len(data["findings"]) >= 1
    assert any(f["type"] == "CONTRADICTION" for f in data["findings"])


def test_api_run_suite_boundary():
    rules = _get_v1_rules()
    resp = client.post(
        "/api/run-suite",
        json={"rules": rules, "suite_type": "boundary", "limit": 10},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_scenarios"] == 10
    assert "findings" in data
    assert "summary_table" in data


def test_api_shrink():
    rules = _get_v1_rules()
    # Padded journey with contradiction on day 36
    journey = [
        {"event_type": "ORDER_PLACED", "day": 0, "payload": {}},
        {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {}},
        {"event_type": "ITEM_DAMAGED_REPORTED", "day": 10, "payload": {}},
        {"event_type": "REPLACEMENT_REQUESTED", "day": 25, "payload": {}},
        {"event_type": "REPLACEMENT_CANCELLED", "day": 35, "payload": {}},
        {"event_type": "REFUND_REQUESTED", "day": 36, "payload": {}},
    ]

    resp = client.post(
        "/api/shrink",
        json={
            "rules": rules,
            "journey": journey,
            "target_finding_type": "CONTRADICTION",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["original_length"] == 6
    assert data["minimal_length"] < 6
    assert data["reduction_pct"] > 0
    assert data["engine_runs"] >= 1


def test_api_diff():
    rules_v1 = _get_v1_rules()
    rules_v2 = _get_v2_rules()

    resp = client.post(
        "/api/diff",
        json={
            "rules_v1": rules_v1,
            "rules_v2": rules_v2,
            "suite_type": "boundary",
            "limit": 15,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_scenarios"] == 15
    assert "health_v1" in data
    assert "health_v2" in data
    assert "rule_text_diffs" in data
    assert "outcome_changes" in data
    assert "rule_refund_standard_window" in data["changed_rule_ids"]


def test_api_compile_with_mock():
    doc_text = """# NovaCart Returns Policy
[RP-1] Customers may request a refund within 30 days of delivery for non-final sale items.
[RP-2] Refund requests submitted more than 30 days after delivery are strictly denied.
"""
    resp = client.post(
        "/api/compile",
        json={
            "document_text": doc_text,
            "doc_name": "refund_policy.md",
            "use_mock": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_clauses"] >= 2
    assert "compiled_rules" in data
    assert "unmapped_clauses" in data
    assert "summary" in data
