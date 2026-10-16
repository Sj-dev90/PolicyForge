"""FastAPI application exposing PolicyForge endpoints:
  - POST /api/compile    : Natural-language policy documents -> compiled rules + grounding & linting
  - POST /api/simulate   : Deterministic journey simulation + full trace & findings
  - POST /api/run-suite  : Stress testing with boundary/pairwise suites & minimal counterexamples
  - POST /api/shrink     : Delta debugging (ddmin) to reduce a failing journey to minimal counterexample
  - POST /api/diff       : Behavioral diff between two rule sets (outcomes, findings, health, coverage)
  - GET  /api/default-data : Pre-loaded NovaCart documents, rules v1/v2, and scenarios for rapid UI testing
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from policyforge.models import (
    Rule,
    Event,
    EventType,
    DecisionType,
    EffectType,
    FindingType,
    State,
    SimulationResult,
)
from policyforge.engine import PolicyEngine
from policyforge.compiler import (
    PolicyCompiler,
    CompileReport,
    split_document_into_clauses,
    check_source_grounding,
)
from policyforge.llm import LLMClient
from policyforge.shrink import shrink_journey, ShrinkResult
from policyforge.scenarios import (
    Scenario,
    generate_boundary_scenarios,
    generate_pairwise_scenarios,
    run_suite,
    SuiteResult,
)
from policyforge.diff import (
    diff_rule_sets,
    DiffReport,
    render_rule_text_diff,
)
from policyforge.detectors import create_default_invariant_registry

# ---------------------------------------------------------------------------
# App Initialization & CORS
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PolicyForge API",
    description="CI/CD for business policies: compile, simulate, stress test, shrink, and diff.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "novacart"
BENCHMARK_DIR = Path(__file__).resolve().parent.parent.parent / "benchmark"


# ---------------------------------------------------------------------------
# Request & Response Schemas
# ---------------------------------------------------------------------------

class CompileRequest(BaseModel):
    documents: dict[str, str] | None = None
    document_text: str | None = None
    doc_name: str | None = "policy.md"
    max_repairs: int = 2
    use_mock: bool = False


class SimulateRequest(BaseModel):
    rules: list[Rule]
    journey: list[Event]
    default_decision_outcome: EffectType = EffectType.DENY


class RunSuiteRequest(BaseModel):
    rules: list[Rule]
    suite_type: Literal["boundary", "pairwise", "novacart", "custom"] = "boundary"
    custom_scenarios: list[dict[str, Any]] | None = None
    default_decision_outcome: EffectType = EffectType.DENY
    limit: int | None = 30


class ShrinkRequest(BaseModel):
    rules: list[Rule]
    journey: list[Event]
    target_finding_type: FindingType | None = None
    target_rule_ids: list[str] | None = None
    default_decision_outcome: EffectType = EffectType.DENY


class DiffRequest(BaseModel):
    rules_v1: list[Rule]
    rules_v2: list[Rule]
    suite_type: Literal["boundary", "pairwise", "custom"] = "boundary"
    custom_scenarios: list[dict[str, Any]] | None = None
    default_decision_outcome: EffectType = EffectType.DENY
    limit: int | None = 30


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "PolicyForge Engine API"}


@app.get("/api/default-data")
def get_default_data():
    """Provides NovaCart policy markdown, rules v1, rules v2, and sample journeys for instant frontend testing."""
    docs: dict[str, str] = {}
    for filename in ("refund_policy.md", "replacement_policy.md", "support_sop.md"):
        p = DATA_DIR / filename
        if p.exists():
            docs[filename] = p.read_text(encoding="utf-8")

    rules_v1: list[dict[str, Any]] = []
    p_v1 = DATA_DIR / "rules_v1.json"
    if p_v1.exists():
        rules_v1 = json.loads(p_v1.read_text(encoding="utf-8"))

    rules_v2: list[dict[str, Any]] = []
    p_v2 = DATA_DIR / "rules_v2.json"
    if p_v2.exists():
        rules_v2 = json.loads(p_v2.read_text(encoding="utf-8"))

    sample_journeys = [
        {
            "id": "canonical_contradiction",
            "name": "Canonical Contradiction (Replacement Cancelled vs 30d Window)",
            "description": "Item delivered day 0, replacement requested day 25, cancelled day 35, refund requested day 36.",
            "journey": [
                {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {}},
                {"event_type": "REPLACEMENT_REQUESTED", "day": 25, "payload": {}},
                {"event_type": "REPLACEMENT_CANCELLED", "day": 35, "payload": {}},
                {"event_type": "REFUND_REQUESTED", "day": 36, "payload": {}},
            ],
        },
        {
            "id": "standard_refund_allowed",
            "name": "Standard Refund Allowed (Day 15)",
            "description": "Standard non-final sale item requested on day 15 after delivery.",
            "journey": [
                {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {}},
                {"event_type": "REFUND_REQUESTED", "day": 15, "payload": {}},
            ],
        },
        {
            "id": "vip_60d_refund",
            "name": "VIP Extended Refund Window (Day 50)",
            "description": "VIP customer requesting refund at day 50 (standard 30d passed, VIP 60d valid).",
            "journey": [
                {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {"customer_tier": "VIP"}},
                {"event_type": "REFUND_REQUESTED", "day": 50, "payload": {"customer_tier": "VIP"}},
            ],
        },
        {
            "id": "final_sale_denial",
            "name": "Final Sale Refund Denied",
            "description": "Final sale item requested on day 5 after delivery.",
            "journey": [
                {"event_type": "ITEM_DELIVERED", "day": 0, "payload": {}},
                {"event_type": "REFUND_REQUESTED", "day": 5, "payload": {"is_final_sale": True}},
            ],
        },
        {
            "id": "policy_gap_pre_delivery",
            "name": "Planted Policy Gap (Replacement Pre-Delivery)",
            "description": "Replacement requested before delivery with no covering rule.",
            "journey": [
                {"event_type": "ORDER_PLACED", "day": 0, "payload": {}},
                {"event_type": "REPLACEMENT_REQUESTED", "day": 2, "payload": {}},
            ],
        },
    ]

    return {
        "documents": docs,
        "rules_v1": rules_v1,
        "rules_v2": rules_v2,
        "sample_journeys": sample_journeys,
    }


@app.post("/api/compile")
def compile_policy(req: CompileRequest):
    """Compile policy documents into structured rules with grounding checks, linting, and coverage."""
    client = LLMClient()
    if req.use_mock or not client.api_key:
        # If no API key or mock requested, use pre-compiled rules or rule extractor mock
        # to ensure the UI operates smoothly and demonstrates the compilation pipeline.
        p_v1 = DATA_DIR / "rules_v1.json"
        cached_rules = []
        if p_v1.exists():
            cached_rules = [Rule.model_validate(r) for r in json.loads(p_v1.read_text(encoding="utf-8"))]

        def _mock_responder(msgs: list[dict[str, str]]) -> str:
            user_msg = next((m["content"] for m in msgs if m["role"] == "user"), "")
            # Return matching rule from cached rules based on document text mention
            matching = []
            for r in cached_rules:
                if r.source.verbatim_sentence.lower() in user_msg.lower():
                    matching.append(r.model_dump(mode="json"))
            return json.dumps({"rules": matching})

        client.set_mock_responder(_mock_responder)

    compiler = PolicyCompiler(llm_client=client, max_repairs=req.max_repairs)

    try:
        if req.documents:
            report = compiler.compile_documents(req.documents)
        elif req.document_text:
            report = compiler.compile_document(req.document_text, req.doc_name or "policy.md")
        else:
            raise HTTPException(status_code=400, detail="Must provide either 'documents' or 'document_text'.")

        return {
            "total_clauses": report.total_clauses,
            "mapped_clauses": report.mapped_clauses,
            "unmapped_clauses": [
                {
                    "id": c.id,
                    "text": c.text,
                    "doc_name": c.doc_name,
                    "line_number": c.line_number,
                }
                for c in report.unmapped_clauses
            ],
            "compiled_rules": [r.model_dump(mode="json") for r in report.compiled_rules],
            "rule_confidence": {
                k: {
                    "rule_id": v.rule_id,
                    "grounded": v.grounded,
                    "lint_clean": v.lint_clean,
                    "confidence": v.confidence,
                    "notes": v.notes,
                }
                for k, v in report.rule_confidence.items()
            },
            "rejected_rules": report.rejected_rules,
            "lint_warnings": report.lint_warnings,
            "token_usage": report.token_usage,
            "latency_ms": round(report.latency_ms, 2),
            "summary": report.summary(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Compilation error: {exc}")


@app.post("/api/simulate")
def simulate_journey(req: SimulateRequest):
    """Run deterministic journey simulation on a rule set."""
    try:
        engine = PolicyEngine(
            rules=req.rules,
            default_decision_outcome=req.default_decision_outcome,
            invariant_registry=create_default_invariant_registry(),
        )
        result: SimulationResult = engine.run(req.journey)

        return {
            "outcomes": [o.model_dump(mode="json") for o in result.outcomes],
            "final_state": result.final_state.model_dump(mode="json"),
            "trace": result.trace.model_dump(mode="json"),
            "findings": [f.model_dump(mode="json") for f in result.findings],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Simulation error: {exc}")


@app.post("/api/run-suite")
def run_test_suite(req: RunSuiteRequest):
    """Run stress testing scenario suite with automatic deduplication and minimal counterexample shrinking."""
    try:
        scenarios: list[Scenario] = []
        if req.suite_type == "boundary":
            scenarios = generate_boundary_scenarios(req.rules)
        elif req.suite_type == "pairwise":
            scenarios = generate_pairwise_scenarios()
        elif req.suite_type == "custom" and req.custom_scenarios:
            for s_dict in req.custom_scenarios:
                journey = [Event.model_validate(e) for e in s_dict.get("journey", [])]
                scenarios.append(
                    Scenario(
                        id=s_dict.get("id", "custom_s"),
                        name=s_dict.get("name", "Custom Scenario"),
                        description=s_dict.get("description", ""),
                        journey=journey,
                        tags=s_dict.get("tags", []),
                    )
                )
        else:
            scenarios = generate_boundary_scenarios(req.rules)

        if req.limit and len(scenarios) > req.limit:
            scenarios = scenarios[: req.limit]

        suite_res: SuiteResult = run_suite(
            rules=req.rules,
            scenarios=scenarios,
            default_decision_outcome=req.default_decision_outcome,
        )

        dedup_findings_list = []
        for sig, finding in suite_res.deduplicated_findings.items():
            shrink_res = suite_res.minimal_counterexamples.get(sig)
            dedup_findings_list.append({
                "signature": [sig[0].value, list(sig[1])],
                "finding": finding.model_dump(mode="json"),
                "shrink": (
                    {
                        "original_journey": [e.model_dump(mode="json") for e in shrink_res.original_journey],
                        "minimal_journey": [e.model_dump(mode="json") for e in shrink_res.minimal_journey],
                        "original_length": len(shrink_res.original_journey),
                        "minimal_length": len(shrink_res.minimal_journey),
                        "engine_runs": shrink_res.engine_runs,
                        "reduction_pct": round(
                            ((len(shrink_res.original_journey) - len(shrink_res.minimal_journey)) / max(len(shrink_res.original_journey), 1)) * 100,
                            1,
                        ),
                    }
                    if shrink_res
                    else None
                ),
            })

        return {
            "total_scenarios": suite_res.total_scenarios,
            "passed_scenarios": suite_res.passed_scenarios,
            "failed_scenarios": suite_res.failed_scenarios,
            "total_findings": suite_res.total_findings,
            "findings_count": len(dedup_findings_list),
            "findings": dedup_findings_list,
            "summary_table": suite_res.summary_table(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Suite execution error: {exc}")


@app.post("/api/shrink")
def shrink_counterexample(req: ShrinkRequest):
    """Perform delta debugging on a failing journey to extract minimal counterexample."""
    try:
        engine = PolicyEngine(
            rules=req.rules,
            default_decision_outcome=req.default_decision_outcome,
            invariant_registry=create_default_invariant_registry(),
        )

        initial_result = engine.run(req.journey)
        if not initial_result.findings:
            raise HTTPException(status_code=400, detail="Journey produced no findings; nothing to shrink.")

        target_sig = None
        from policyforge.shrink import get_finding_signature
        if req.target_finding_type:
            if req.target_rule_ids is not None:
                rule_ids = tuple(sorted(req.target_rule_ids))
                target_sig = (req.target_finding_type, rule_ids)
            else:
                match = next((f for f in initial_result.findings if f.type == req.target_finding_type), None)
                if match:
                    target_sig = get_finding_signature(match)
        if not target_sig:
            target_sig = get_finding_signature(initial_result.findings[0])

        shrink_res = shrink_journey(engine, req.journey, target_signature=target_sig)

        orig_len = len(shrink_res.original_journey)
        min_len = len(shrink_res.minimal_journey)
        reduction_pct = ((orig_len - min_len) / max(orig_len, 1)) * 100

        return {
            "original_journey": [e.model_dump(mode="json") for e in shrink_res.original_journey],
            "minimal_journey": [e.model_dump(mode="json") for e in shrink_res.minimal_journey],
            "original_length": orig_len,
            "minimal_length": min_len,
            "engine_runs": shrink_res.engine_runs,
            "reduction_pct": round(reduction_pct, 1),
            "finding": shrink_res.final_finding.model_dump(mode="json"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Shrink error: {exc}")


@app.post("/api/diff")
def diff_policies(req: DiffRequest):
    """Run behavioral diff between rules_v1 and rules_v2 over a scenario suite."""
    try:
        scenarios: list[Scenario] = []
        if req.suite_type == "boundary":
            scenarios = generate_boundary_scenarios(req.rules_v1)
        elif req.suite_type == "pairwise":
            scenarios = generate_pairwise_scenarios()
        elif req.suite_type == "custom" and req.custom_scenarios:
            for s_dict in req.custom_scenarios:
                journey = [Event.model_validate(e) for e in s_dict.get("journey", [])]
                scenarios.append(
                    Scenario(
                        id=s_dict.get("id", "custom_s"),
                        name=s_dict.get("name", "Custom Scenario"),
                        description=s_dict.get("description", ""),
                        journey=journey,
                        tags=s_dict.get("tags", []),
                    )
                )
        else:
            scenarios = generate_boundary_scenarios(req.rules_v1)

        if req.limit and len(scenarios) > req.limit:
            scenarios = scenarios[: req.limit]

        report: DiffReport = diff_rule_sets(
            rules_v1=req.rules_v1,
            rules_v2=req.rules_v2,
            scenarios=scenarios,
            default_decision_outcome=req.default_decision_outcome,
        )

        return {
            "total_scenarios": report.total_scenarios,
            "changed_rule_ids": sorted(report.changed_rule_ids),
            "outcomes_allow_to_deny": report.outcomes_allow_to_deny,
            "outcomes_deny_to_allow": report.outcomes_deny_to_allow,
            "outcome_changes": [
                {
                    "scenario_id": c.scenario_id,
                    "scenario_name": c.scenario_name,
                    "event_index": c.event_index,
                    "day": c.day,
                    "event_type": c.event_type.value,
                    "outcome_v1": c.outcome_v1.value,
                    "outcome_v2": c.outcome_v2.value,
                    "resolution_v1": c.resolution_v1,
                    "resolution_v2": c.resolution_v2,
                    "attributed_rule_ids": c.attributed_rule_ids,
                    "explanation": c.explanation,
                    "needs_review": c.needs_review,
                }
                for c in report.outcome_changes
            ],
            "finding_deltas": [
                {
                    "scenario_id": d.scenario_id,
                    "direction": d.direction,
                    "finding": d.finding.model_dump(mode="json"),
                }
                for d in report.finding_deltas
            ],
            "scenarios_needing_review": report.scenarios_needing_review,
            "rule_text_diffs": [
                {
                    "rule_id": d.rule_id,
                    "status": d.status,
                    "v1_summary": d.v1_summary,
                    "v2_summary": d.v2_summary,
                    "changes": d.changes,
                }
                for d in report.rule_text_diffs
            ],
            "coverage_v1": {
                "rule_coverage": round(report.coverage_v1.rule_coverage, 4),
                "rules_fired": report.coverage_v1.rules_fired,
                "rules_total": report.coverage_v1.rules_total,
                "uncovered_rule_ids": report.coverage_v1.uncovered_rule_ids,
                "event_type_coverage": round(report.coverage_v1.event_type_coverage, 4),
                "transitions_observed": report.coverage_v1.transitions_observed,
            },
            "coverage_v2": {
                "rule_coverage": round(report.coverage_v2.rule_coverage, 4),
                "rules_fired": report.coverage_v2.rules_fired,
                "rules_total": report.coverage_v2.rules_total,
                "uncovered_rule_ids": report.coverage_v2.uncovered_rule_ids,
                "event_type_coverage": round(report.coverage_v2.event_type_coverage, 4),
                "transitions_observed": report.coverage_v2.transitions_observed,
            },
            "health_v1": {
                "score": report.health_v1.score,
                "no_critical_findings": report.health_v1.no_critical_findings,
                "rule_coverage": report.health_v1.rule_coverage,
                "no_gaps": report.health_v1.no_gaps,
                "no_ambiguities": report.health_v1.no_ambiguities,
                "event_coverage": report.health_v1.event_coverage,
            },
            "health_v2": {
                "score": report.health_v2.score,
                "no_critical_findings": report.health_v2.no_critical_findings,
                "rule_coverage": report.health_v2.rule_coverage,
                "no_gaps": report.health_v2.no_gaps,
                "no_ambiguities": report.health_v2.no_ambiguities,
                "event_coverage": report.health_v2.event_coverage,
            },
            "summary": report.summary(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diff execution error: {exc}")
