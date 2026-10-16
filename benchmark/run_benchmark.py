"""Main benchmark runner: orchestrates baseline and engine evaluation.

Usage:
    # With API key configured (runs both baseline and engine):
    python benchmark/run_benchmark.py

    # Engine-only (no API key needed):
    python benchmark/run_benchmark.py --engine-only

    # Limit scenarios for a quick smoke test:
    python benchmark/run_benchmark.py --engine-only --limit 5

Output:
    benchmark/results.json   - Full structured results
    benchmark/report.md      - README-ready markdown table

All numbers come from real simulation/LLM runs. Nothing is fabricated.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure backend is on sys.path
_ROOT = Path(__file__).parent.parent
_BACKEND = _ROOT / "backend"
for p in (_BACKEND, _ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from benchmark.schema import load_labeled_scenarios, LabeledScenario
from benchmark.engine_runner import EngineRunner, EngineResult
from benchmark.metrics import (
    compute_engine_metrics,
    compute_baseline_metrics,
    MetricsReport,
    FindingMetrics,
)

_BENCHMARK_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Markdown report renderer
# ---------------------------------------------------------------------------

def _fmt(v: Any, pct: bool = False, decimals: int = 1) -> str:
    """Format a metric value for the markdown table."""
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float):
        if pct:
            return f"{v * 100:.{decimals}f}%"
        return f"{v:.{decimals}f}"
    return str(v)


def render_markdown_report(
    engine_metrics: MetricsReport,
    baseline_metrics: MetricsReport | None,
    engine_results: list[EngineResult],
    labeled_scenarios: list[LabeledScenario],
    run_timestamp: str,
) -> str:
    """Render a README-ready markdown report from real metrics."""

    lines: list[str] = [
        "# PolicyForge Benchmark Report",
        "",
        f"*Generated: {run_timestamp}*",
        "",
        "> All numbers are computed from real simulation runs and (when available) "
        "> live LLM API calls. Nothing is fabricated or hardcoded.",
        "",
        "## Scenario Suite",
        "",
        f"| Metric | Value |",
        f"| :--- | ---: |",
        f"| Total labeled scenarios | {engine_metrics.total_scenarios} |",
        f"| Scenarios with ALLOW expectation | "
        + f"{sum(1 for s in labeled_scenarios if s.expected_outcome == 'ALLOW')} |",
        f"| Scenarios with DENY expectation | "
        + f"{sum(1 for s in labeled_scenarios if s.expected_outcome == 'DENY')} |",
        f"| Scenarios expecting POLICY_GAP finding | "
        + f"{sum(1 for s in labeled_scenarios if 'POLICY_GAP' in s.expected_finding_types)} |",
        f"| Scenarios expecting CONTRADICTION finding | "
        + f"{sum(1 for s in labeled_scenarios if 'CONTRADICTION' in s.expected_finding_types)} |",
        "",
    ]

    # --- Outcome accuracy table ---
    lines += [
        "## Outcome Accuracy",
        "",
        "| Metric | PolicyForge Engine |"
        + (" Baseline (Nemotron Direct) |" if baseline_metrics else ""),
        "| :--- | ---: |" + (" ---: |" if baseline_metrics else ""),
    ]

    def _row(label: str, eng_val: Any, base_val: Any = None, pct: bool = False) -> str:
        row = f"| {label} | {_fmt(eng_val, pct=pct)} |"
        if baseline_metrics is not None:
            row += f" {_fmt(base_val, pct=pct)} |"
        return row

    lines += [
        _row("Scenarios evaluated",
             engine_metrics.total_scenarios,
             baseline_metrics.total_scenarios if baseline_metrics else None),
        _row("Correct outcomes",
             engine_metrics.outcome_correct,
             baseline_metrics.outcome_correct if baseline_metrics else None),
        _row("Outcome accuracy",
             engine_metrics.outcome_accuracy,
             baseline_metrics.outcome_accuracy if baseline_metrics else None,
             pct=True),
        _row("Precision (ALLOW)",
             engine_metrics.outcome_precision_allow,
             baseline_metrics.outcome_precision_allow if baseline_metrics else None,
             pct=True),
        _row("Recall (ALLOW)",
             engine_metrics.outcome_recall_allow,
             baseline_metrics.outcome_recall_allow if baseline_metrics else None,
             pct=True),
        _row("F1 (ALLOW)",
             engine_metrics.outcome_f1_allow,
             baseline_metrics.outcome_f1_allow if baseline_metrics else None,
             pct=True),
        _row("Precision (DENY)",
             engine_metrics.outcome_precision_deny,
             baseline_metrics.outcome_precision_deny if baseline_metrics else None,
             pct=True),
        _row("Recall (DENY)",
             engine_metrics.outcome_recall_deny,
             baseline_metrics.outcome_recall_deny if baseline_metrics else None,
             pct=True),
        _row("F1 (DENY)",
             engine_metrics.outcome_f1_deny,
             baseline_metrics.outcome_f1_deny if baseline_metrics else None,
             pct=True),
        _row("Consistency rate",
             engine_metrics.consistency_rate,
             baseline_metrics.consistency_rate if baseline_metrics else None,
             pct=True),
        "",
    ]

    # --- Finding detection table ---
    lines += [
        "## Finding Detection (PolicyForge Engine)",
        "",
        "The baseline cannot emit structured findings; all finding metrics are "
        "engine-only.",
        "",
        "| Finding Type | TP | FP | FN | Precision | Recall | F1 |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fm in engine_metrics.finding_metrics:
        lines.append(
            f"| `{fm.finding_type}` | {fm.true_positives} | {fm.false_positives}"
            f" | {fm.false_negatives} | {_fmt(fm.precision, pct=True)}"
            f" | {_fmt(fm.recall, pct=True)} | {_fmt(fm.f1, pct=True)} |"
        )
    lines.append("")

    # --- Performance table ---
    lines += [
        "## Performance",
        "",
        "| Metric | PolicyForge Engine |"
        + (" Baseline (Nemotron Direct) |" if baseline_metrics else ""),
        "| :--- | ---: |" + (" ---: |" if baseline_metrics else ""),
        _row("Avg latency (ms)",
             engine_metrics.avg_latency_ms,
             baseline_metrics.avg_latency_ms if baseline_metrics else None),
        _row("p95 latency (ms)",
             engine_metrics.p95_latency_ms,
             baseline_metrics.p95_latency_ms if baseline_metrics else None),
        _row("Total LLM tokens",
             engine_metrics.total_tokens,
             baseline_metrics.total_tokens if baseline_metrics else None),
        _row("Avg tokens / scenario",
             engine_metrics.avg_tokens_per_scenario,
             baseline_metrics.avg_tokens_per_scenario if baseline_metrics else None),
        "",
    ]

    # --- Per-scenario detail table (engine) ---
    lines += [
        "## Per-Scenario Engine Results",
        "",
        "| ID | Expected | Engine | Correct | Findings | Latency (ms) |",
        "| :--- | :---: | :---: | :---: | :--- | ---: |",
    ]
    id_to_scenario = {s.id: s for s in labeled_scenarios}
    for r in engine_results:
        correct_str = "✓" if r.correct is True else ("✗" if r.correct is False else "—")
        findings_str = ", ".join(r.finding_types) if r.finding_types else "none"
        lines.append(
            f"| `{r.scenario_id}` | `{r.expected_outcome or '—'}` "
            f"| `{r.engine_outcome or '—'}` | {correct_str} "
            f"| {findings_str} | {r.latency_ms:.2f} |"
        )
    lines.append("")

    # --- Mislabeled / unexpected engine outcomes ---
    wrong = [r for r in engine_results if r.correct is False]
    if wrong:
        lines += [
            "## ⚠ Engine Disagreements with Labels",
            "",
            "These scenarios have a label mismatch. "
            "Either the label is wrong or the rule set needs updating.",
            "",
            "| ID | Expected | Engine | Notes |",
            "| :--- | :---: | :---: | :--- |",
        ]
        for r in wrong:
            scenario = id_to_scenario.get(r.scenario_id)
            notes = scenario.notes if scenario else ""
            lines.append(
                f"| `{r.scenario_id}` | `{r.expected_outcome}` "
                f"| `{r.engine_outcome}` | {notes} |"
            )
        lines.append("")
    else:
        lines += [
            "## ✓ No Engine Disagreements",
            "",
            "All labeled scenarios matched the engine's deterministic outcome.",
            "",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Results JSON builder
# ---------------------------------------------------------------------------

def build_results_json(
    engine_results: list[EngineResult],
    engine_metrics: MetricsReport,
    baseline_results: list[Any] | None,
    baseline_metrics: MetricsReport | None,
    run_timestamp: str,
) -> dict[str, Any]:
    return {
        "benchmark_version": "1.0",
        "run_timestamp": run_timestamp,
        "engine": {
            "metrics": engine_metrics.to_dict(),
            "results": [r.to_dict() for r in engine_results],
        },
        "baseline": (
            {
                "metrics": baseline_metrics.to_dict(),
                "results": [r.to_dict() for r in baseline_results],
            }
            if baseline_results is not None and baseline_metrics is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the PolicyForge benchmark.")
    parser.add_argument(
        "--scenarios",
        default=str(_BENCHMARK_DIR / "labeled_scenarios.json"),
        help="Path to labeled_scenarios.json",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help="Path to rules JSON (default: data/novacart/rules_v1.json)",
    )
    parser.add_argument(
        "--engine-only",
        action="store_true",
        help="Skip the LLM baseline (no API key required).",
    )
    parser.add_argument(
        "--n-runs",
        type=int,
        default=3,
        help="Number of baseline runs per scenario (default 3).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit to first N scenarios (for smoke testing).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_BENCHMARK_DIR),
        help="Directory to write results.json and report.md.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load scenarios
    print(f"Loading scenarios from {args.scenarios} …")
    scenarios = load_labeled_scenarios(args.scenarios)
    if args.limit:
        scenarios = scenarios[: args.limit]
        print(f"  Limiting to {len(scenarios)} scenarios.")
    print(f"  {len(scenarios)} scenarios loaded.")

    run_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # --- Engine ---
    print("\nRunning PolicyForge engine …")
    rules_path = Path(args.rules) if args.rules else None
    engine_runner = EngineRunner(rules_path=rules_path)
    engine_results = engine_runner.run_all(scenarios)
    engine_metrics = compute_engine_metrics(engine_results, scenarios)

    correct_count = sum(1 for r in engine_results if r.correct is True)
    total_with_label = sum(1 for r in engine_results if r.correct is not None)
    print(f"  Engine accuracy: {correct_count}/{total_with_label}")

    # --- Baseline ---
    baseline_results: list[Any] | None = None
    baseline_metrics: MetricsReport | None = None

    if not args.engine_only:
        api_key = os.getenv("NEBIUS_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            print(
                "\n[WARN] No NEBIUS_API_KEY found — skipping baseline. "
                "Set NEBIUS_API_KEY in .env or use --engine-only."
            )
        else:
            from benchmark.baseline import BaselineRunner
            from policyforge.llm import LLMClient

            print(f"\nRunning LLM baseline ({args.n_runs} runs per scenario) …")
            client = LLMClient()
            baseline_runner = BaselineRunner(llm_client=client, n_runs=args.n_runs)
            baseline_results = baseline_runner.run_all(scenarios)
            baseline_metrics = compute_baseline_metrics(baseline_results, scenarios)

            base_correct = sum(1 for r in baseline_results if r.correct is True)
            base_total = sum(1 for r in baseline_results if r.correct is not None)
            print(f"  Baseline accuracy: {base_correct}/{base_total}")
            print(f"  Baseline consistency: {baseline_metrics.consistency_rate * 100:.1f}%")
    else:
        print("\n[INFO] Baseline skipped (--engine-only).")

    # --- Write results.json ---
    results_path = output_dir / "results.json"
    results_data = build_results_json(
        engine_results, engine_metrics,
        baseline_results, baseline_metrics,
        run_timestamp,
    )
    results_path.write_text(
        json.dumps(results_data, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nResults written to {results_path}")

    # --- Write report.md ---
    report_path = output_dir / "report.md"
    report_md = render_markdown_report(
        engine_metrics=engine_metrics,
        baseline_metrics=baseline_metrics,
        engine_results=engine_results,
        labeled_scenarios=scenarios,
        run_timestamp=run_timestamp,
    )
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Report written to    {report_path}")

    # --- Print summary to stdout ---
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    print(f"Engine accuracy   : {engine_metrics.outcome_accuracy * 100:.1f}%")
    print(f"Engine consistency: 100.0% (deterministic)")
    print(f"Engine avg latency: {engine_metrics.avg_latency_ms:.2f} ms")
    if baseline_metrics:
        print(f"Baseline accuracy : {baseline_metrics.outcome_accuracy * 100:.1f}%")
        print(f"Baseline consist. : {baseline_metrics.consistency_rate * 100:.1f}%")
        print(f"Baseline avg lat. : {baseline_metrics.avg_latency_ms:.1f} ms")
        print(f"Baseline tokens   : {baseline_metrics.total_tokens:,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
