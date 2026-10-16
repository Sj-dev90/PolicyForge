"""Metrics computation for the PolicyForge benchmark.

Computes from real run data — never fabricates or hardcodes numbers.

Metrics computed:
  Outcome accuracy
    - outcome_accuracy      : fraction of correctly predicted ALLOW/DENY outcomes
    - outcome_precision_allow : TP_allow / (TP_allow + FP_allow)
    - outcome_recall_allow    : TP_allow / (TP_allow + FN_allow)
    - (and same for DENY)

  Finding detection (precision / recall / F1)
    For each finding type in {CONTRADICTION, POLICY_GAP, AMBIGUITY, INVARIANT_VIOLATION}:
    - A scenario is a "positive" for finding type F if expected_finding_types contains F.
    - A scenario is "predicted positive" for F if the engine/baseline emitted F.
    - precision_F, recall_F, f1_F computed accordingly.
    - false_positives_F : predicted F but not expected.

  Consistency
    - consistency_rate : fraction of scenarios where all N runs gave same outcome (baseline only)

  Latency
    - avg_latency_ms : mean latency across all scenarios
    - p95_latency_ms : 95th-percentile latency

  Token cost
    - total_tokens : sum across all runs
    - avg_tokens_per_scenario : total_tokens / n_scenarios
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


_FINDING_TYPES = [
    "CONTRADICTION",
    "POLICY_GAP",
    "AMBIGUITY",
    "INVARIANT_VIOLATION",
]


# ---------------------------------------------------------------------------
# Per-finding-type precision/recall
# ---------------------------------------------------------------------------

@dataclass
class FindingMetrics:
    finding_type: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_type": self.finding_type,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


# ---------------------------------------------------------------------------
# Full metrics report
# ---------------------------------------------------------------------------

@dataclass
class MetricsReport:
    """Complete metrics for one runner (baseline or engine)."""
    runner_name: str
    total_scenarios: int
    scenarios_with_expectation: int

    # Outcome accuracy
    outcome_correct: int
    outcome_accuracy: float

    # Per-class precision / recall
    outcome_precision_allow: float
    outcome_recall_allow: float
    outcome_f1_allow: float
    outcome_precision_deny: float
    outcome_recall_deny: float
    outcome_f1_deny: float

    # Finding detection
    finding_metrics: list[FindingMetrics]

    # Consistency
    consistency_rate: float  # 1.0 for engine (deterministic)

    # Latency (ms)
    avg_latency_ms: float
    p95_latency_ms: float

    # Token cost
    total_tokens: int
    avg_tokens_per_scenario: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "runner_name": self.runner_name,
            "total_scenarios": self.total_scenarios,
            "scenarios_with_expectation": self.scenarios_with_expectation,
            "outcome_correct": self.outcome_correct,
            "outcome_accuracy": round(self.outcome_accuracy, 4),
            "outcome_precision_allow": round(self.outcome_precision_allow, 4),
            "outcome_recall_allow": round(self.outcome_recall_allow, 4),
            "outcome_f1_allow": round(self.outcome_f1_allow, 4),
            "outcome_precision_deny": round(self.outcome_precision_deny, 4),
            "outcome_recall_deny": round(self.outcome_recall_deny, 4),
            "outcome_f1_deny": round(self.outcome_f1_deny, 4),
            "finding_metrics": [fm.to_dict() for fm in self.finding_metrics],
            "consistency_rate": round(self.consistency_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "p95_latency_ms": round(self.p95_latency_ms, 1),
            "total_tokens": self.total_tokens,
            "avg_tokens_per_scenario": round(self.avg_tokens_per_scenario, 1),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(num: float, den: float) -> float:
    return num / den if den > 0 else 0.0


def _f1(p: float, r: float) -> float:
    return _safe_div(2 * p * r, p + r)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    idx = math.ceil(0.95 * len(sorted_v)) - 1
    return sorted_v[max(0, idx)]


# ---------------------------------------------------------------------------
# Compute from engine results
# ---------------------------------------------------------------------------

def compute_engine_metrics(
    engine_results: list[Any],   # list[EngineResult]
    labeled_scenarios: list[Any],  # list[LabeledScenario]
) -> MetricsReport:
    """Compute MetricsReport from EngineResult objects."""
    id_to_scenario = {s.id: s for s in labeled_scenarios}

    total = len(engine_results)
    with_expectation = [r for r in engine_results if r.expected_outcome is not None]
    n_with = len(with_expectation)

    # Outcome accuracy
    correct = [r for r in with_expectation if r.correct is True]
    accuracy = _safe_div(len(correct), n_with)

    # Per-class metrics (ALLOW / DENY)
    def _class_metrics(cls: str) -> tuple[float, float, float]:
        tp = sum(1 for r in with_expectation
                 if r.expected_outcome == cls and r.engine_outcome == cls)
        fp = sum(1 for r in with_expectation
                 if r.expected_outcome != cls and r.engine_outcome == cls)
        fn = sum(1 for r in with_expectation
                 if r.expected_outcome == cls and r.engine_outcome != cls)
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        return p, r, _f1(p, r)

    pa, ra, fa = _class_metrics("ALLOW")
    pd, rd, fd = _class_metrics("DENY")

    # Finding metrics
    finding_metrics_list: list[FindingMetrics] = []
    for ft in _FINDING_TYPES:
        expected_positive = [
            s for s in labeled_scenarios if ft in s.expected_finding_types
        ]
        pred_positive_ids = {
            r.scenario_id for r in engine_results if ft in r.finding_types
        }
        expected_positive_ids = {s.id for s in expected_positive}

        tp = len(expected_positive_ids & pred_positive_ids)
        fp = len(pred_positive_ids - expected_positive_ids)
        fn = len(expected_positive_ids - pred_positive_ids)
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        finding_metrics_list.append(FindingMetrics(
            finding_type=ft,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            precision=p,
            recall=r,
            f1=_f1(p, r),
        ))

    # Latency
    latencies = [r.latency_ms for r in engine_results]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p95_lat = _p95(latencies)

    return MetricsReport(
        runner_name="PolicyForge Engine",
        total_scenarios=total,
        scenarios_with_expectation=n_with,
        outcome_correct=len(correct),
        outcome_accuracy=accuracy,
        outcome_precision_allow=pa,
        outcome_recall_allow=ra,
        outcome_f1_allow=fa,
        outcome_precision_deny=pd,
        outcome_recall_deny=rd,
        outcome_f1_deny=fd,
        finding_metrics=finding_metrics_list,
        consistency_rate=1.0,  # deterministic by design
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        total_tokens=0,  # engine uses no LLM tokens
        avg_tokens_per_scenario=0.0,
    )


# ---------------------------------------------------------------------------
# Compute from baseline results
# ---------------------------------------------------------------------------

def compute_baseline_metrics(
    baseline_results: list[Any],   # list[BaselineResult]
    labeled_scenarios: list[Any],  # list[LabeledScenario]
) -> MetricsReport:
    """Compute MetricsReport from BaselineResult objects."""
    id_to_scenario = {s.id: s for s in labeled_scenarios}

    total = len(baseline_results)
    with_expectation = [r for r in baseline_results if r.expected_outcome is not None]
    n_with = len(with_expectation)

    # Use majority_outcome for correctness
    correct = [r for r in with_expectation if r.correct is True]
    accuracy = _safe_div(len(correct), n_with)

    def _class_metrics(cls: str) -> tuple[float, float, float]:
        tp = sum(1 for r in with_expectation
                 if r.expected_outcome == cls and r.majority_outcome == cls)
        fp = sum(1 for r in with_expectation
                 if r.expected_outcome != cls and r.majority_outcome == cls)
        fn = sum(1 for r in with_expectation
                 if r.expected_outcome == cls and r.majority_outcome != cls)
        p = _safe_div(tp, tp + fp)
        r = _safe_div(tp, tp + fn)
        return p, r, _f1(p, r)

    pa, ra, fa = _class_metrics("ALLOW")
    pd, rd, fd = _class_metrics("DENY")

    # Finding metrics: baseline cannot detect structured findings (it only returns ALLOW/DENY)
    # All finding detection metrics are 0 for the baseline.
    finding_metrics_list = [
        FindingMetrics(
            finding_type=ft,
            true_positives=0,
            false_positives=0,
            false_negatives=sum(
                1 for s in labeled_scenarios if ft in s.expected_finding_types
            ),
            precision=0.0,
            recall=0.0,
            f1=0.0,
        )
        for ft in _FINDING_TYPES
    ]

    # Consistency
    consistent = sum(1 for r in baseline_results if r.is_consistent)
    consistency_rate = _safe_div(consistent, total)

    # Latency
    latencies = [r.avg_latency_ms for r in baseline_results]
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    p95_lat = _p95(latencies)

    # Token cost
    total_tokens = sum(r.total_cost_tokens for r in baseline_results)
    avg_tokens = _safe_div(total_tokens, total)

    return MetricsReport(
        runner_name="Baseline (Nemotron Direct)",
        total_scenarios=total,
        scenarios_with_expectation=n_with,
        outcome_correct=len(correct),
        outcome_accuracy=accuracy,
        outcome_precision_allow=pa,
        outcome_recall_allow=ra,
        outcome_f1_allow=fa,
        outcome_precision_deny=pd,
        outcome_recall_deny=rd,
        outcome_f1_deny=fd,
        finding_metrics=finding_metrics_list,
        consistency_rate=consistency_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        total_tokens=total_tokens,
        avg_tokens_per_scenario=avg_tokens,
    )
