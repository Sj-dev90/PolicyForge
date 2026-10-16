"""Behavioral diff between two policy rule sets.

Given rules_v1, rules_v2, and a scenario suite, this module:
  - Replays every scenario on both rule sets
  - Reports outcome changes (ALLOW↔DENY, gap↔decision)
  - Reports findings introduced / resolved
  - Attributes each outcome change to the changed rule(s) via trace comparison
  - Flags scenarios that need manual review (new ambiguity or gap)
  - Produces a human-readable rule-level textual diff
  - Computes coverage metrics (rule, event, transition)
  - Emits a health score with a transparent, documented formula
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from policyforge.models import (
    EffectType,
    EventType,
    FindingType,
    Rule,
    Event,
    Finding,
    SimulationResult,
)
from policyforge.engine import PolicyEngine
from policyforge.scenarios import Scenario
from policyforge.detectors import create_default_invariant_registry, InvariantRegistry


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class OutcomeChange:
    """A single scenario outcome that changed between v1 and v2."""
    scenario_id: str
    scenario_name: str
    event_index: int
    day: int
    event_type: EventType
    outcome_v1: EffectType
    outcome_v2: EffectType
    resolution_v1: str
    resolution_v2: str
    # Rule IDs that fired in v2 but not v1 (or vice-versa) at this event
    attributed_rule_ids: list[str]
    # Human-readable explanation derived from traces
    explanation: str
    needs_review: bool  # True when new ambiguity or gap introduced


@dataclass
class FindingDelta:
    """A finding that was introduced or resolved between v1 and v2."""
    scenario_id: str
    finding: Finding
    direction: str  # "INTRODUCED" or "RESOLVED"


@dataclass
class ScenarioDiffResult:
    """Full diff for a single scenario."""
    scenario_id: str
    scenario_name: str
    outcome_changes: list[OutcomeChange]
    findings_introduced: list[Finding]
    findings_resolved: list[Finding]
    needs_manual_review: bool


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    """Coverage metrics computed from simulation traces.

    - rule_coverage: fraction of rules that fired at least once across all scenarios
    - event_type_coverage: fraction of EventType values observed as decision events
    - transition_coverage: fraction of observed (from_resolution, to_resolution)
      transitions vs. all that were seen (open-world; we cannot enumerate all
      possible transitions in advance).
    """
    # Rule coverage
    rules_total: int
    rules_fired: int
    rule_coverage: float  # rules_fired / rules_total  (0.0–1.0)
    uncovered_rule_ids: list[str]

    # Event type coverage (decision events)
    event_types_total: int
    event_types_observed: int
    event_type_coverage: float
    uncovered_event_types: list[str]

    # Transition coverage (resolution_type pairs across consecutive decision events per scenario)
    transitions_observed: int
    unique_transitions: list[tuple[str, str]]

    def summary(self) -> str:
        lines = [
            f"Rule coverage   : {self.rules_fired}/{self.rules_total} "
            f"({self.rule_coverage * 100:.1f}%)",
            f"  Uncovered     : {self.uncovered_rule_ids or 'none'}",
            f"Event coverage  : {self.event_types_observed}/{self.event_types_total} "
            f"({self.event_type_coverage * 100:.1f}%)",
            f"  Uncovered     : {self.uncovered_event_types or 'none'}",
            f"Transitions seen: {self.transitions_observed} unique "
            f"({', '.join(f'{a}→{b}' for a, b in self.unique_transitions[:8])}"
            f"{'…' if len(self.unique_transitions) > 8 else ''})",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------

@dataclass
class HealthScore:
    """Policy health score for a rule set evaluated over a scenario suite.

    Formula (all components in [0, 1]):
        health = 0.40 * no_critical_findings
                + 0.25 * rule_coverage
                + 0.20 * no_gaps
                + 0.10 * no_ambiguities
                + 0.05 * event_coverage

    Components:
        no_critical_findings: 1 - clamp(critical_count / 5, 0, 1)
            Penalises CONTRADICTION + INVARIANT_VIOLATION findings,
            scaled so ≥5 critical findings → 0.
        rule_coverage: fraction of rules fired at least once.
        no_gaps: 1 - clamp(gap_count / total_decision_events, 0, 1)
            Penalises POLICY_GAP findings relative to total decision events.
        no_ambiguities: 1 - clamp(ambiguity_count / 10, 0, 1)
            Penalises AMBIGUITY findings.
        event_coverage: fraction of EventType values observed.

    Score is multiplied by 100 and rounded to one decimal place.
    """
    score: float  # 0.0–100.0
    no_critical_findings: float
    rule_coverage: float
    no_gaps: float
    no_ambiguities: float
    event_coverage: float

    def summary(self) -> str:
        return (
            f"Health score    : {self.score:.1f}/100\n"
            f"  No critical   : {self.no_critical_findings:.3f} (×0.40)\n"
            f"  Rule coverage : {self.rule_coverage:.3f} (×0.25)\n"
            f"  No gaps       : {self.no_gaps:.3f} (×0.20)\n"
            f"  No ambiguities: {self.no_ambiguities:.3f} (×0.10)\n"
            f"  Event coverage: {self.event_coverage:.3f} (×0.05)"
        )


# ---------------------------------------------------------------------------
# Rule-level textual diff
# ---------------------------------------------------------------------------

@dataclass
class RuleTextDiff:
    """Human-readable diff for a single rule across v1 and v2."""
    rule_id: str
    status: str  # ADDED | REMOVED | MODIFIED | UNCHANGED
    v1_summary: str | None
    v2_summary: str | None
    changes: list[str]  # Field-level change descriptions


def _rule_summary(r: Rule) -> str:
    """One-line human-readable rule summary."""
    cond_json = json.dumps(
        r.when.model_dump(by_alias=False), separators=(",", ":"), sort_keys=True
    )
    return (
        f"[{r.effect.value}] trigger={r.trigger.value} "
        f"decision={r.decision.value} priority={r.priority} "
        f"when={cond_json}"
    )


def _diff_rules(v1: list[Rule], v2: list[Rule]) -> list[RuleTextDiff]:
    """Produce per-rule textual diffs between two rule sets."""
    v1_by_id: dict[str, Rule] = {r.id: r for r in v1}
    v2_by_id: dict[str, Rule] = {r.id: r for r in v2}

    all_ids = sorted(set(v1_by_id) | set(v2_by_id))
    diffs: list[RuleTextDiff] = []

    for rid in all_ids:
        r1 = v1_by_id.get(rid)
        r2 = v2_by_id.get(rid)

        if r1 is None and r2 is not None:
            diffs.append(RuleTextDiff(
                rule_id=rid,
                status="ADDED",
                v1_summary=None,
                v2_summary=_rule_summary(r2),
                changes=[f"Rule '{rid}' added in v2."],
            ))
        elif r1 is not None and r2 is None:
            diffs.append(RuleTextDiff(
                rule_id=rid,
                status="REMOVED",
                v1_summary=_rule_summary(r1),
                v2_summary=None,
                changes=[f"Rule '{rid}' removed in v2."],
            ))
        else:
            assert r1 is not None and r2 is not None
            changes: list[str] = []

            if r1.effect != r2.effect:
                changes.append(f"effect: {r1.effect.value} → {r2.effect.value}")
            if r1.priority != r2.priority:
                changes.append(f"priority: {r1.priority} → {r2.priority}")
            if r1.overrides != r2.overrides:
                changes.append(f"overrides: {r1.overrides} → {r2.overrides}")
            if r1.trigger != r2.trigger:
                changes.append(f"trigger: {r1.trigger.value} → {r2.trigger.value}")
            if r1.decision != r2.decision:
                changes.append(f"decision: {r1.decision.value} → {r2.decision.value}")
            # Condition diff: compare serialised representation
            cond_v1 = json.dumps(r1.when.model_dump(by_alias=False), sort_keys=True)
            cond_v2 = json.dumps(r2.when.model_dump(by_alias=False), sort_keys=True)
            if cond_v1 != cond_v2:
                changes.append(f"condition changed: {cond_v1} → {cond_v2}")
            if r1.state_updates != r2.state_updates:
                changes.append(
                    f"state_updates: {r1.state_updates} → {r2.state_updates}"
                )
            if r1.name != r2.name:
                changes.append(f"name: '{r1.name}' → '{r2.name}'")

            status = "MODIFIED" if changes else "UNCHANGED"
            diffs.append(RuleTextDiff(
                rule_id=rid,
                status=status,
                v1_summary=_rule_summary(r1),
                v2_summary=_rule_summary(r2),
                changes=changes,
            ))

    return diffs


def render_rule_text_diff(diffs: list[RuleTextDiff]) -> str:
    """Render rule diffs as a human-readable markdown block."""
    lines: list[str] = ["## Rule-Level Diff\n"]
    for d in diffs:
        marker = {"ADDED": "++", "REMOVED": "--", "MODIFIED": "~~", "UNCHANGED": "  "}.get(d.status, "  ")
        lines.append(f"{marker} [{d.status}] {d.rule_id}")
        if d.v1_summary and d.status not in ("ADDED",):
            lines.append(f"   v1: {d.v1_summary}")
        if d.v2_summary and d.status not in ("REMOVED",):
            lines.append(f"   v2: {d.v2_summary}")
        for c in d.changes:
            lines.append(f"      Δ {c}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Attribution helper
# ---------------------------------------------------------------------------

def _attribute_change(
    result_v1: SimulationResult,
    result_v2: SimulationResult,
    event_index: int,
    changed_rule_ids: set[str],
) -> list[str]:
    """Identify which changed rules caused a specific outcome change at event_index.

    Compares the sets of fired rules at that event between v1 and v2.
    Returns the intersection with changed_rule_ids (rules that differ between versions).
    """
    def fired_at(result: SimulationResult, idx: int) -> set[str]:
        for et in result.trace.event_traces:
            if et.event_index == idx:
                return set(et.rules_fired)
        return set()

    fired_v1 = fired_at(result_v1, event_index)
    fired_v2 = fired_at(result_v2, event_index)
    newly_fired = fired_v2 - fired_v1
    no_longer_fired = fired_v1 - fired_v2
    all_changed_at_event = (newly_fired | no_longer_fired) & changed_rule_ids
    # Fall back to any fired difference if no explicit changed rule matched
    if not all_changed_at_event:
        all_changed_at_event = newly_fired | no_longer_fired
    return sorted(all_changed_at_event)


# ---------------------------------------------------------------------------
# Coverage computation
# ---------------------------------------------------------------------------

def _compute_coverage(
    rules: list[Rule],
    scenarios: list[Scenario],
    results: list[SimulationResult],
) -> CoverageReport:
    """Compute rule, event-type, and transition coverage from simulation traces."""
    all_rule_ids = {r.id for r in rules}
    fired_rule_ids: set[str] = set()

    decision_event_types: set[EventType] = {
        EventType.REFUND_REQUESTED,
        EventType.REPLACEMENT_REQUESTED,
    }
    observed_event_types: set[EventType] = set()

    transitions: list[tuple[str, str]] = []
    transition_set: set[tuple[str, str]] = set()

    for result in results:
        prev_resolution: str | None = None
        for et in result.trace.event_traces:
            # Rule coverage
            fired_rule_ids.update(et.rules_fired)
            # Event type coverage (track all event types observed)
            observed_event_types.add(et.event_type)
            # Transition coverage (consecutive resolutions within a journey)
            if et.is_decision_event:
                if prev_resolution is not None:
                    pair = (prev_resolution, et.resolution_type)
                    if pair not in transition_set:
                        transition_set.add(pair)
                        transitions.append(pair)
                prev_resolution = et.resolution_type

    # Event coverage over *all* event types, not just decision types
    all_event_types = {e for e in EventType}
    uncovered_event_types = sorted(
        e.value for e in all_event_types if e not in observed_event_types
    )
    uncovered_rule_ids = sorted(all_rule_ids - fired_rule_ids)

    rule_cov = len(fired_rule_ids & all_rule_ids) / len(all_rule_ids) if all_rule_ids else 1.0
    event_cov = len(observed_event_types) / len(all_event_types) if all_event_types else 1.0

    return CoverageReport(
        rules_total=len(all_rule_ids),
        rules_fired=len(fired_rule_ids & all_rule_ids),
        rule_coverage=rule_cov,
        uncovered_rule_ids=uncovered_rule_ids,
        event_types_total=len(all_event_types),
        event_types_observed=len(observed_event_types),
        event_type_coverage=event_cov,
        uncovered_event_types=uncovered_event_types,
        transitions_observed=len(transition_set),
        unique_transitions=sorted(transition_set),
    )


def _compute_health(
    all_findings: list[Finding],
    coverage: CoverageReport,
    total_decision_events: int,
) -> HealthScore:
    """Compute health score per documented formula in HealthScore docstring."""
    critical_types = {FindingType.CONTRADICTION, FindingType.INVARIANT_VIOLATION}
    critical_count = sum(1 for f in all_findings if f.type in critical_types)
    gap_count = sum(1 for f in all_findings if f.type == FindingType.POLICY_GAP)
    ambiguity_count = sum(1 for f in all_findings if f.type == FindingType.AMBIGUITY)

    no_critical = 1.0 - min(critical_count / 5.0, 1.0)
    rule_cov = coverage.rule_coverage
    no_gaps = 1.0 - min(
        gap_count / max(total_decision_events, 1), 1.0
    )
    no_ambiguities = 1.0 - min(ambiguity_count / 10.0, 1.0)
    event_cov = coverage.event_type_coverage

    raw = (
        0.40 * no_critical
        + 0.25 * rule_cov
        + 0.20 * no_gaps
        + 0.10 * no_ambiguities
        + 0.05 * event_cov
    )
    return HealthScore(
        score=round(raw * 100, 1),
        no_critical_findings=no_critical,
        rule_coverage=rule_cov,
        no_gaps=no_gaps,
        no_ambiguities=no_ambiguities,
        event_coverage=event_cov,
    )


# ---------------------------------------------------------------------------
# Main DiffReport
# ---------------------------------------------------------------------------

@dataclass
class DiffReport:
    """Full behavioral diff report between two policy rule sets.

    Attributes:
        scenario_diffs: Per-scenario diff results.
        outcome_changes: All outcome changes across scenarios (flattened).
        finding_deltas: All introduced / resolved findings (flattened).
        scenarios_needing_review: Scenario IDs flagged for manual review.
        rule_text_diffs: Textual diff of individual rules.
        coverage_v1: Coverage metrics for rules_v1 over the scenario suite.
        coverage_v2: Coverage metrics for rules_v2 over the scenario suite.
        health_v1: Health score for rules_v1.
        health_v2: Health score for rules_v2.
        total_scenarios: Number of scenarios evaluated.
        changed_rule_ids: Rule IDs that differ between v1 and v2.
    """
    scenario_diffs: list[ScenarioDiffResult]
    outcome_changes: list[OutcomeChange]
    finding_deltas: list[FindingDelta]
    scenarios_needing_review: list[str]
    rule_text_diffs: list[RuleTextDiff]
    coverage_v1: CoverageReport
    coverage_v2: CoverageReport
    health_v1: HealthScore
    health_v2: HealthScore
    total_scenarios: int
    changed_rule_ids: set[str]

    # Counts for quick access
    @property
    def outcomes_allow_to_deny(self) -> int:
        return sum(
            1 for c in self.outcome_changes
            if c.outcome_v1 == EffectType.ALLOW and c.outcome_v2 == EffectType.DENY
        )

    @property
    def outcomes_deny_to_allow(self) -> int:
        return sum(
            1 for c in self.outcome_changes
            if c.outcome_v1 == EffectType.DENY and c.outcome_v2 == EffectType.ALLOW
        )

    @property
    def findings_introduced_count(self) -> int:
        return sum(1 for d in self.finding_deltas if d.direction == "INTRODUCED")

    @property
    def findings_resolved_count(self) -> int:
        return sum(1 for d in self.finding_deltas if d.direction == "RESOLVED")

    def summary(self) -> str:
        """Produce a full markdown summary of the diff report."""
        lines = [
            "# PolicyForge Behavioral Diff Report",
            "",
            f"**Total scenarios evaluated** : {self.total_scenarios}",
            f"**Changed rules (v1→v2)**     : {sorted(self.changed_rule_ids) or 'none'}",
            "",
            "## Outcome Changes",
            f"- ALLOW → DENY : **{self.outcomes_allow_to_deny}**",
            f"- DENY → ALLOW : **{self.outcomes_deny_to_allow}**",
            f"- Other changes: **{len(self.outcome_changes) - self.outcomes_allow_to_deny - self.outcomes_deny_to_allow}**",
            "",
            "## Finding Deltas",
            f"- Introduced : **{self.findings_introduced_count}**",
            f"- Resolved   : **{self.findings_resolved_count}**",
            "",
            "## Manual Review Required",
            f"Scenarios needing review: **{len(self.scenarios_needing_review)}**",
        ]
        if self.scenarios_needing_review:
            for sid in self.scenarios_needing_review:
                lines.append(f"  - `{sid}`")
        lines.append("")

        # Outcome change table
        if self.outcome_changes:
            lines += [
                "## Changed Outcomes",
                "| Scenario | Event | Day | v1 | v2 | Attributed Rule(s) | Notes |",
                "| :--- | :--- | ---: | :---: | :---: | :--- | :--- |",
            ]
            for c in self.outcome_changes:
                rule_str = ", ".join(c.attributed_rule_ids) or "unknown"
                review = "⚠ review" if c.needs_review else ""
                lines.append(
                    f"| `{c.scenario_id}` | `{c.event_type.value}` | {c.day}"
                    f" | `{c.outcome_v1.value}` | `{c.outcome_v2.value}`"
                    f" | `{rule_str}` | {review} |"
                )
            lines.append("")

        # Coverage
        lines += [
            "## Coverage (v1 → v2)",
            "```",
            "--- v1 ---",
            self.coverage_v1.summary(),
            "",
            "--- v2 ---",
            self.coverage_v2.summary(),
            "```",
            "",
        ]

        # Health
        lines += [
            "## Health Score",
            "```",
            "--- v1 ---",
            self.health_v1.summary(),
            "",
            "--- v2 ---",
            self.health_v2.summary(),
            "```",
            "",
        ]

        # Rule text diff
        lines.append(render_rule_text_diff(self.rule_text_diffs))

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def diff_rule_sets(
    rules_v1: list[Rule],
    rules_v2: list[Rule],
    scenarios: list[Scenario],
    default_decision_outcome: EffectType = EffectType.DENY,
    invariant_registry: InvariantRegistry | None = None,
) -> DiffReport:
    """Run a behavioral diff between two rule sets over a scenario suite.

    Args:
        rules_v1: Original rule set.
        rules_v2: Updated rule set.
        scenarios: Scenario suite to replay on both rule sets.
        default_decision_outcome: Default outcome when no rule fires.
        invariant_registry: Optional custom invariant registry.

    Returns:
        DiffReport with all outcome changes, finding deltas, coverage, and health.
    """
    registry = invariant_registry or create_default_invariant_registry()

    engine_v1 = PolicyEngine(
        rules=rules_v1,
        default_decision_outcome=default_decision_outcome,
        invariant_registry=registry,
    )
    engine_v2 = PolicyEngine(
        rules=rules_v2,
        default_decision_outcome=default_decision_outcome,
        invariant_registry=registry,
    )

    # Identify which rules changed between v1 and v2
    rule_text_diffs = _diff_rules(rules_v1, rules_v2)
    changed_rule_ids: set[str] = {
        d.rule_id for d in rule_text_diffs if d.status != "UNCHANGED"
    }

    # Replay all scenarios
    all_results_v1: list[SimulationResult] = []
    all_results_v2: list[SimulationResult] = []
    scenario_diffs: list[ScenarioDiffResult] = []
    all_outcome_changes: list[OutcomeChange] = []
    all_finding_deltas: list[FindingDelta] = []
    review_ids: list[str] = []

    # Track findings per version for global health
    all_findings_v1: list[Finding] = []
    all_findings_v2: list[Finding] = []
    total_decision_events: int = 0

    _NEEDS_REVIEW_TYPES = {FindingType.AMBIGUITY, FindingType.POLICY_GAP}

    for scenario in scenarios:
        journey = scenario.journey
        result_v1 = engine_v1.run(journey)
        result_v2 = engine_v2.run(journey)
        all_results_v1.append(result_v1)
        all_results_v2.append(result_v2)
        all_findings_v1.extend(result_v1.findings)
        all_findings_v2.extend(result_v2.findings)

        # Build outcome index keyed by event_index
        outcomes_v1 = {o.event_index: o for o in result_v1.outcomes}
        outcomes_v2 = {o.event_index: o for o in result_v2.outcomes}

        # Count decision events for health score denominator
        for o in result_v1.outcomes:
            if o.event_type in (EventType.REFUND_REQUESTED, EventType.REPLACEMENT_REQUESTED):
                total_decision_events += 1

        # Detect outcome changes
        outcome_changes: list[OutcomeChange] = []
        all_event_indices = sorted(set(outcomes_v1) | set(outcomes_v2))
        for idx in all_event_indices:
            o1 = outcomes_v1.get(idx)
            o2 = outcomes_v2.get(idx)
            if o1 is None or o2 is None:
                continue
            if o1.outcome != o2.outcome or o1.resolution_type != o2.resolution_type:
                # Attribute to changed rules
                attributed = _attribute_change(result_v1, result_v2, idx, changed_rule_ids)

                # Needs review if v2 introduces ambiguity or gap at this event
                new_review_findings = [
                    f for f in result_v2.findings
                    if f.type in _NEEDS_REVIEW_TYPES and idx in f.event_indices
                ]
                needs_review = len(new_review_findings) > 0

                change = OutcomeChange(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    event_index=idx,
                    day=o1.day,
                    event_type=o1.event_type,
                    outcome_v1=o1.outcome,
                    outcome_v2=o2.outcome,
                    resolution_v1=o1.resolution_type,
                    resolution_v2=o2.resolution_type,
                    attributed_rule_ids=attributed,
                    explanation=(
                        f"Scenario '{scenario.id}' event[{idx}] "
                        f"({o1.event_type.value}@day {o1.day}): "
                        f"v1={o1.outcome.value}({o1.resolution_type}), "
                        f"v2={o2.outcome.value}({o2.resolution_type}). "
                        f"Attributed to: {attributed or 'unknown rule change'}."
                    ),
                    needs_review=needs_review,
                )
                outcome_changes.append(change)
                all_outcome_changes.append(change)

        # Finding delta: introduced and resolved
        def finding_sig(f: Finding) -> tuple:
            return (f.type, tuple(sorted(f.rule_ids)))

        sigs_v1 = {finding_sig(f) for f in result_v1.findings}
        sigs_v2 = {finding_sig(f) for f in result_v2.findings}

        findings_introduced: list[Finding] = [
            f for f in result_v2.findings if finding_sig(f) not in sigs_v1
        ]
        findings_resolved: list[Finding] = [
            f for f in result_v1.findings if finding_sig(f) not in sigs_v2
        ]

        for f in findings_introduced:
            all_finding_deltas.append(FindingDelta(
                scenario_id=scenario.id, finding=f, direction="INTRODUCED"
            ))
        for f in findings_resolved:
            all_finding_deltas.append(FindingDelta(
                scenario_id=scenario.id, finding=f, direction="RESOLVED"
            ))

        # Check if scenario needs manual review
        new_review_scenario = any(
            f.type in _NEEDS_REVIEW_TYPES for f in findings_introduced
        ) or any(c.needs_review for c in outcome_changes)

        if new_review_scenario:
            review_ids.append(scenario.id)

        scenario_diffs.append(ScenarioDiffResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            outcome_changes=outcome_changes,
            findings_introduced=findings_introduced,
            findings_resolved=findings_resolved,
            needs_manual_review=new_review_scenario,
        ))

    # Coverage (v1 and v2 independently)
    coverage_v1 = _compute_coverage(rules_v1, scenarios, all_results_v1)
    coverage_v2 = _compute_coverage(rules_v2, scenarios, all_results_v2)

    # Health (v1 and v2 independently)
    health_v1 = _compute_health(all_findings_v1, coverage_v1, total_decision_events)
    health_v2 = _compute_health(all_findings_v2, coverage_v2, total_decision_events)

    return DiffReport(
        scenario_diffs=scenario_diffs,
        outcome_changes=all_outcome_changes,
        finding_deltas=all_finding_deltas,
        scenarios_needing_review=sorted(set(review_ids)),
        rule_text_diffs=rule_text_diffs,
        coverage_v1=coverage_v1,
        coverage_v2=coverage_v2,
        health_v1=health_v1,
        health_v2=health_v2,
        total_scenarios=len(scenarios),
        changed_rule_ids=changed_rule_ids,
    )
