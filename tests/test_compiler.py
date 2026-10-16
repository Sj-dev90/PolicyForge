"""Tests for policy compiler: clause splitting, source grounding, self-repair, linting, and coverage."""

import json
from pathlib import Path
import pytest

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
)
from policyforge.llm import LLMClient
from policyforge.compiler import (
    Clause,
    PolicyCompiler,
    split_document_into_clauses,
    check_source_grounding,
)


DOC_SAMPLE = """# NovaCart Returns Policy Sample

[RP-1] Customers may request a refund within 30 days of delivery for non-final sale items.
[RP-2] Refund requests submitted more than 30 days after delivery are strictly denied.
[RP-3] Promotional and marketing items are not eligible for compensation.
"""


def test_split_document_into_clauses():
    clauses = split_document_into_clauses(DOC_SAMPLE, "refund_policy.md")
    assert len(clauses) == 3
    assert clauses[0].id == "RP-1"
    assert "within 30 days of delivery" in clauses[0].text
    assert clauses[1].id == "RP-2"
    assert clauses[2].id == "RP-3"


def test_grounding_check():
    doc = "Customers may request a refund within 30 days of delivery."
    # Exact match
    assert check_source_grounding("Customers may request a refund within 30 days of delivery.", doc) is True
    # Normalized whitespace and casing
    assert check_source_grounding("customers   may request a refund   within 30 days of delivery.", doc) is True
    # Hallucinated clause
    assert check_source_grounding("Customers have 90 days to return everything for free.", doc) is False


def test_compiler_extracts_and_grounds_valid_rule():
    client = LLMClient(api_key="mock-key")

    valid_response = json.dumps({
        "rules": [
            {
                "id": "rule_refund_30d",
                "name": "Standard 30-day refund window",
                "decision": "REFUND",
                "trigger": "REFUND_REQUESTED",
                "when": {
                    "all": [
                        {"field": "days_since_delivery", "op": "LTE", "value": 30},
                        {"field": "is_final_sale", "op": "IS_FALSE", "value": False},
                    ]
                },
                "effect": "ALLOW",
                "priority": 0,
                "overrides": [],
                "state_updates": None,
                "source": {
                    "doc_name": "refund_policy.md",
                    "verbatim_sentence": "Customers may request a refund within 30 days of delivery for non-final sale items.",
                },
            }
        ]
    })

    empty_response = json.dumps({"rules": []})

    def _mock(msgs: list) -> str:
        # Only return the rule for the clause that contains it (RP-1).
        user_content = next((m["content"] for m in msgs if m["role"] == "user"), "")
        if "[RP-1]" in user_content:
            return valid_response
        return empty_response

    client.set_mock_responder(_mock)
    compiler = PolicyCompiler(llm_client=client)

    report = compiler.compile_document(DOC_SAMPLE, "refund_policy.md")

    assert len(report.compiled_rules) >= 1
    rule = report.compiled_rules[0]
    assert rule.id == "rule_refund_30d"
    assert report.rule_confidence[rule.id].grounded is True
    assert report.rule_confidence[rule.id].confidence == "HIGH"


def test_compiler_rejects_hallucinated_grounding():
    client = LLMClient(api_key="mock-key")

    # LLM hallucinates a sentence not in DOC_SAMPLE
    hallucinated_response = json.dumps({
        "rules": [
            {
                "id": "rule_hallucinated",
                "name": "Hallucinated 90-day window",
                "decision": "REFUND",
                "trigger": "REFUND_REQUESTED",
                "when": {"field": "days_since_delivery", "op": "LTE", "value": 90},
                "effect": "ALLOW",
                "priority": 0,
                "overrides": [],
                "state_updates": None,
                "source": {
                    "doc_name": "refund_policy.md",
                    "verbatim_sentence": "Customers are entitled to 90 days of unconditional returns.",
                },
            }
        ]
    })

    client.set_mock_responder(lambda msgs: hallucinated_response)
    compiler = PolicyCompiler(llm_client=client)

    report = compiler.compile_document(DOC_SAMPLE, "refund_policy.md")

    assert len(report.compiled_rules) == 0
    assert len(report.rejected_rules) >= 1
    assert "Grounding check failed" in report.rejected_rules[0]["reason"]


def test_compiler_self_repair_loop():
    client = LLMClient(api_key="mock-key")
    attempts = 0

    def repair_responder(msgs: list[dict[str, str]]) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            # First attempt: invalid trigger outside closed vocabulary
            return json.dumps({
                "rules": [
                    {
                        "id": "rule_broken",
                        "name": "Broken Rule",
                        "decision": "REFUND",
                        "trigger": "CUSTOMER_COMPLAINED",  # INVALID TRIGGER
                        "when": {"field": "days_since_delivery", "op": "LTE", "value": 30},
                        "effect": "ALLOW",
                        "source": {
                            "doc_name": "refund_policy.md",
                            "verbatim_sentence": "Customers may request a refund within 30 days of delivery for non-final sale items.",
                        },
                    }
                ]
            })
        else:
            # Repaired attempt: valid trigger
            return json.dumps({
                "rules": [
                    {
                        "id": "rule_repaired",
                        "name": "Repaired Rule",
                        "decision": "REFUND",
                        "trigger": "REFUND_REQUESTED",  # VALID TRIGGER
                        "when": {"field": "days_since_delivery", "op": "LTE", "value": 30},
                        "effect": "ALLOW",
                        "source": {
                            "doc_name": "refund_policy.md",
                            "verbatim_sentence": "Customers may request a refund within 30 days of delivery for non-final sale items.",
                        },
                    }
                ]
            })

    client.set_mock_responder(repair_responder)
    compiler = PolicyCompiler(llm_client=client, max_repairs=2)

    report = compiler.compile_document(DOC_SAMPLE, "refund_policy.md")

    # Should have recovered via self-repair
    assert len(report.compiled_rules) >= 1
    assert report.compiled_rules[0].id == "rule_repaired"
    assert attempts >= 2


def test_compiler_linting_and_coverage():
    client = LLMClient(api_key="mock-key")

    # Return an unsatisfiable condition rule and an unmapped clause response
    def mock_lint_responder(msgs: list[dict[str, str]]) -> str:
        user_content = msgs[-1]["content"]
        if "RP-1" in user_content:
            # Unsatisfiable numeric condition: > 30 and < 10
            return json.dumps({
                "rules": [
                    {
                        "id": "rule_unsat",
                        "name": "Unsatisfiable bounds",
                        "decision": "REFUND",
                        "trigger": "REFUND_REQUESTED",
                        "when": {
                            "all": [
                                {"field": "days_since_delivery", "op": "GT", "value": 30},
                                {"field": "days_since_delivery", "op": "LT", "value": 10},
                            ]
                        },
                        "effect": "ALLOW",
                        "source": {
                            "doc_name": "refund_policy.md",
                            "verbatim_sentence": "Customers may request a refund within 30 days of delivery for non-final sale items.",
                        },
                    }
                ]
            })
        # Other clauses return empty rules (unmapped)
        return json.dumps({"rules": []})

    client.set_mock_responder(mock_lint_responder)
    compiler = PolicyCompiler(llm_client=client)

    report = compiler.compile_document(DOC_SAMPLE, "refund_policy.md")

    assert len(report.compiled_rules) == 1
    assert len(report.lint_warnings) >= 1
    assert "unsatisfiable" in report.lint_warnings[0]
    assert report.rule_confidence["rule_unsat"].lint_clean is False
    assert report.rule_confidence["rule_unsat"].confidence == "MEDIUM"

    # Clauses RP-2 and RP-3 produced no rules, so they must be in unmapped_clauses
    unmapped_ids = {c.id for c in report.unmapped_clauses}
    assert "RP-2" in unmapped_ids
    assert "RP-3" in unmapped_ids
    assert report.mapped_clauses == 1
    assert report.total_clauses == 3


def test_compile_novacart_documents():
    data_dir = Path(__file__).resolve().parent.parent / "data" / "novacart"
    docs = {
        "refund_policy.md": (data_dir / "refund_policy.md").read_text(encoding="utf-8"),
        "replacement_policy.md": (data_dir / "replacement_policy.md").read_text(encoding="utf-8"),
        "support_sop.md": (data_dir / "support_sop.md").read_text(encoding="utf-8"),
    }

    # Verify document files exist and have clauses
    for doc_name, text in docs.items():
        clauses = split_document_into_clauses(text, doc_name)
        assert len(clauses) >= 7

    client = LLMClient(api_key="mock-key")

    # Dynamic responder that produces valid grounded rules for key clauses
    def dynamic_responder(msgs: list[dict[str, str]]) -> str:
        prompt = msgs[-1]["content"]
        if "within 30 days of delivery" in prompt:
            return json.dumps({
                "rules": [{
                    "id": "rule_sample_30d",
                    "name": "30-day window",
                    "decision": "REFUND",
                    "trigger": "REFUND_REQUESTED",
                    "when": {"field": "days_since_delivery", "op": "LTE", "value": 30},
                    "effect": "ALLOW",
                    "source": {
                        "doc_name": "refund_policy.md",
                        "verbatim_sentence": "Customers may request a refund within 30 days of delivery for non-final sale items.",
                    },
                }]
            })
        return json.dumps({"rules": []})

    client.set_mock_responder(dynamic_responder)
    compiler = PolicyCompiler(llm_client=client)

    report = compiler.compile_documents(docs)
    assert report.total_clauses >= 20
    assert report.mapped_clauses >= 1
    assert len(report.compiled_rules) >= 1
    assert "clause coverage" in report.summary()
