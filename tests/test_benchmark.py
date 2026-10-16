"""Unit tests for benchmark/ package.

Covers:
  - schema.py: loading, validation, rejection of invalid entries
  - engine_runner.py: running deterministic engine on labeled scenarios
  - baseline.py: running mock baseline, variance/consistency across runs, token/latency logging
  - metrics.py: accuracy, precision/recall, finding metrics, consistency, latency
  - run_benchmark.py: report rendering, results.json structure
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from benchmark.schema import (
    LabeledScenario,
    LabeledEvent,
    load_labeled_scenarios,
)
from benchmark.engine_runner import EngineRunner, EngineResult
from benchmark.baseline import (
    BaselineRunner,
    BaselineResult,
    _parse_outcome,
    _journey_to_prose,
)
from benchmark.metrics import (
    compute_engine_metrics,
    compute_baseline_metrics,
    MetricsReport,
)
from benchmark.run_benchmark import (
    render_markdown_report,
    build_results_json,
)
from policyforge.llm import LLMClient
from policyforge.models import EventType, EffectType


# ---------------------------------------------------------------------------
# 1. Schema & Validation Tests
# ---------------------------------------------------------------------------

class TestBenchmarkSchema:
    def test_load_real_labeled_scenarios(self):
        path = Path(__file__).resolve().parent.parent / "benchmark" / "labeled_scenarios.json"
        scenarios = load_labeled_scenarios(path)
        assert len(scenarios) == 50
        ids = [s.id for s in scenarios]
        assert len(set(ids)) == 50  # all unique
        assert ids[0] == "ls_001"
        assert ids[-1] == "ls_050"

    def test_valid_scenario_model(self):
        s = LabeledScenario(
            id="s_test",
            description="Test scenario",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0, payload={}),
                LabeledEvent(event_type="REFUND_REQUESTED", day=10, payload={}),
            ],
            expected_outcome="ALLOW",
            expected_finding_types=["CONTRADICTION"],
            notes="A note",
        )
        assert s.id == "s_test"
        assert s.expected_outcome == "ALLOW"
        assert s.expected_finding_types == ["CONTRADICTION"]

    def test_reject_unknown_event_type(self):
        with pytest.raises(ValidationError):
            LabeledScenario(
                id="s_bad_event",
                description="Bad event",
                journey=[LabeledEvent(event_type="PACKAGE_EXPLODED", day=0)],
                expected_outcome="DENY",
            )

    def test_reject_negative_day(self):
        with pytest.raises(ValidationError):
            LabeledScenario(
                id="s_neg_day",
                description="Negative day",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=-1)],
                expected_outcome="ALLOW",
            )

    def test_reject_non_monotonic_days(self):
        with pytest.raises(ValidationError, match="must be non-decreasing"):
            LabeledScenario(
                id="s_decreasing_day",
                description="Decreasing day",
                journey=[
                    LabeledEvent(event_type="ITEM_DELIVERED", day=10),
                    LabeledEvent(event_type="REFUND_REQUESTED", day=5),
                ],
                expected_outcome="ALLOW",
            )

    def test_reject_invalid_expected_outcome(self):
        with pytest.raises(ValidationError, match="expected_outcome must be one of"):
            LabeledScenario(
                id="s_bad_outcome",
                description="Bad outcome",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="MAYBE",
            )

    def test_reject_invalid_finding_type(self):
        with pytest.raises(ValidationError, match="Unknown finding type"):
            LabeledScenario(
                id="s_bad_finding",
                description="Bad finding",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="DENY",
                expected_finding_types=["RANDOM_BUG"],
            )

    def test_reject_duplicate_ids_in_loader(self, tmp_path):
        bad_json = tmp_path / "dup.json"
        dup_content = [
            {
                "id": "dup_1",
                "description": "First",
                "journey": [{"event_type": "ITEM_DELIVERED", "day": 0}],
                "expected_outcome": "ALLOW",
            },
            {
                "id": "dup_1",
                "description": "Second duplicate",
                "journey": [{"event_type": "ITEM_DELIVERED", "day": 1}],
                "expected_outcome": "DENY",
            },
        ]
        bad_json.write_text(json.dumps(dup_content), encoding="utf-8")
        # Loader with wrapped format catches duplicates
        with pytest.raises(ValueError):
            from benchmark.schema import LabeledScenarioFile
            LabeledScenarioFile.model_validate({"scenarios": dup_content})


# ---------------------------------------------------------------------------
# 2. Engine Runner Tests
# ---------------------------------------------------------------------------

class TestBenchmarkEngineRunner:
    def test_run_single_scenario(self):
        runner = EngineRunner()
        scenario = LabeledScenario(
            id="s_allow",
            description="30-day refund",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                LabeledEvent(event_type="REFUND_REQUESTED", day=15),
            ],
            expected_outcome="ALLOW",
        )
        res = runner.run_scenario(scenario)
        assert res.scenario_id == "s_allow"
        assert res.engine_outcome == "ALLOW"
        assert res.correct is True
        assert res.is_consistent is True
        assert res.latency_ms > 0

    def test_run_contradiction_scenario(self):
        runner = EngineRunner()
        scenario = LabeledScenario(
            id="s_contra",
            description="Canonical contradiction",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                LabeledEvent(event_type="REPLACEMENT_REQUESTED", day=25),
                LabeledEvent(event_type="REPLACEMENT_CANCELLED", day=35),
                LabeledEvent(event_type="REFUND_REQUESTED", day=36),
            ],
            expected_outcome="DENY",
            expected_finding_types=["CONTRADICTION"],
        )
        res = runner.run_scenario(scenario)
        assert res.engine_outcome == "DENY"
        assert res.correct is True
        assert "CONTRADICTION" in res.finding_types

    def test_run_all_on_subset(self):
        runner = EngineRunner()
        scenarios = [
            LabeledScenario(
                id="s1",
                description="s1",
                journey=[
                    LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                    LabeledEvent(event_type="REFUND_REQUESTED", day=5),
                ],
                expected_outcome="ALLOW",
            ),
            LabeledScenario(
                id="s2",
                description="s2",
                journey=[
                    LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                    LabeledEvent(event_type="REFUND_REQUESTED", day=35),
                ],
                expected_outcome="DENY",
            ),
        ]
        results = runner.run_all(scenarios)
        assert len(results) == 2
        assert all(r.correct for r in results)


# ---------------------------------------------------------------------------
# 3. Baseline Runner Tests (with Mock LLM)
# ---------------------------------------------------------------------------

class TestBenchmarkBaselineRunner:
    def test_parse_outcome(self):
        assert _parse_outcome("ALLOW - per section 1.1") == "ALLOW"
        assert _parse_outcome("DENY because of 30-day window") == "DENY"
        assert _parse_outcome("I cannot decide") == "UNKNOWN"

    def test_journey_to_prose(self):
        scenario = LabeledScenario(
            id="s_prose",
            description="Prose test",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                LabeledEvent(event_type="REFUND_REQUESTED", day=10, payload={"item_damaged": True}),
            ],
            expected_outcome="ALLOW",
        )
        prose = _journey_to_prose(scenario)
        assert "ITEM_DELIVERED" in prose
        assert "REFUND_REQUESTED" in prose
        assert "item_damaged=True" in prose

    def test_mock_baseline_consistent_runs(self):
        client = LLMClient(api_key="mock-key")
        client.set_mock_responder(lambda msgs: "ALLOW. Within the 30-day window.")

        runner = BaselineRunner(llm_client=client, n_runs=3)
        scenario = LabeledScenario(
            id="s_base_allow",
            description="Baseline allow test",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                LabeledEvent(event_type="REFUND_REQUESTED", day=10),
            ],
            expected_outcome="ALLOW",
        )
        res = runner.run_scenario(scenario)
        assert len(res.runs) == 3
        assert res.majority_outcome == "ALLOW"
        assert res.is_consistent is True
        assert res.correct is True
        assert res.total_cost_tokens > 0

    def test_mock_baseline_inconsistent_runs(self):
        client = LLMClient(api_key="mock-key")
        # Flip outcome across runs
        call_count = 0
        def _alternating(msgs):
            nonlocal call_count
            call_count += 1
            return "ALLOW" if call_count % 2 == 1 else "DENY"

        client.set_mock_responder(_alternating)
        runner = BaselineRunner(llm_client=client, n_runs=3)
        scenario = LabeledScenario(
            id="s_inconsistent",
            description="Inconsistent test",
            journey=[
                LabeledEvent(event_type="ITEM_DELIVERED", day=0),
                LabeledEvent(event_type="REFUND_REQUESTED", day=10),
            ],
            expected_outcome="ALLOW",
        )
        res = runner.run_scenario(scenario)
        assert len(res.runs) == 3
        # With 2 ALLOWs and 1 DENY, majority is ALLOW, but is_consistent is False
        assert res.is_consistent is False


# ---------------------------------------------------------------------------
# 4. Metrics Computation Tests
# ---------------------------------------------------------------------------

class TestBenchmarkMetrics:
    def test_engine_metrics_calculation(self):
        labeled = [
            LabeledScenario(
                id="s1", description="",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="ALLOW",
            ),
            LabeledScenario(
                id="s2", description="",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="DENY",
                expected_finding_types=["CONTRADICTION"],
            ),
        ]
        results = [
            EngineResult(
                scenario_id="s1", expected_outcome="ALLOW", engine_outcome="ALLOW",
                finding_types=[], latency_ms=0.5, correct=True,
            ),
            EngineResult(
                scenario_id="s2", expected_outcome="DENY", engine_outcome="DENY",
                finding_types=["CONTRADICTION"], latency_ms=0.6, correct=True,
            ),
        ]
        metrics = compute_engine_metrics(results, labeled)
        assert metrics.total_scenarios == 2
        assert metrics.outcome_accuracy == pytest.approx(1.0)
        assert metrics.outcome_precision_allow == pytest.approx(1.0)
        assert metrics.outcome_recall_allow == pytest.approx(1.0)
        assert metrics.consistency_rate == pytest.approx(1.0)

        contra_m = next(fm for fm in metrics.finding_metrics if fm.finding_type == "CONTRADICTION")
        assert contra_m.true_positives == 1
        assert contra_m.precision == pytest.approx(1.0)
        assert contra_m.recall == pytest.approx(1.0)

    def test_baseline_metrics_calculation(self):
        from benchmark.baseline import BaselineRun

        labeled = [
            LabeledScenario(
                id="s1", description="",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="ALLOW",
            ),
        ]
        runs = [
            BaselineRun(
                run_index=0, response="ALLOW", parsed_outcome="ALLOW",
                latency_ms=100.0, prompt_tokens=50, completion_tokens=10,
                total_tokens=60, success=True,
            ),
            BaselineRun(
                run_index=1, response="ALLOW", parsed_outcome="ALLOW",
                latency_ms=105.0, prompt_tokens=50, completion_tokens=10,
                total_tokens=60, success=True,
            ),
        ]
        b_res = [
            BaselineResult(
                scenario_id="s1", expected_outcome="ALLOW", runs=runs,
            )
        ]
        metrics = compute_baseline_metrics(b_res, labeled)
        assert metrics.total_scenarios == 1
        assert metrics.outcome_accuracy == pytest.approx(1.0)
        assert metrics.consistency_rate == pytest.approx(1.0)
        assert metrics.total_tokens == 120
        assert metrics.avg_latency_ms == pytest.approx(102.5)


# ---------------------------------------------------------------------------
# 5. Report & Output Generation Tests
# ---------------------------------------------------------------------------

class TestBenchmarkReportGeneration:
    def test_markdown_and_json_generation(self):
        labeled = [
            LabeledScenario(
                id="s1", description="",
                journey=[LabeledEvent(event_type="ITEM_DELIVERED", day=0)],
                expected_outcome="ALLOW",
            ),
        ]
        results = [
            EngineResult(
                scenario_id="s1", expected_outcome="ALLOW", engine_outcome="ALLOW",
                finding_types=[], latency_ms=0.35, correct=True,
            ),
        ]
        engine_metrics = compute_engine_metrics(results, labeled)

        md = render_markdown_report(
            engine_metrics=engine_metrics,
            baseline_metrics=None,
            engine_results=results,
            labeled_scenarios=labeled,
            run_timestamp="2026-10-16T12:00:00Z",
        )
        assert "# PolicyForge Benchmark Report" in md
        assert "## Outcome Accuracy" in md
        assert "## Finding Detection (PolicyForge Engine)" in md
        assert "## Performance" in md

        res_json = build_results_json(
            engine_results=results,
            engine_metrics=engine_metrics,
            baseline_results=None,
            baseline_metrics=None,
            run_timestamp="2026-10-16T12:00:00Z",
        )
        assert res_json["benchmark_version"] == "1.0"
        assert res_json["engine"]["metrics"]["outcome_accuracy"] == 1.0
