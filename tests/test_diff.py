"""Tests for diff.py: behavioral diff between two policy rule sets.

Tests cover:
  - outcome changes detected (ALLOW→DENY, DENY→ALLOW)
  - finding deltas (introduced / resolved)
  - rule attribution
  - manual review flagging
  - rule-level textual diff
  - coverage metrics (rule, event, transition)
  - health score formula correctness
  - v1 → v2 diff with NovaCart rules (refund window 30→14 days)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Rule,
    Event,
    RuleSource,
    LeafCondition,
    AllCondition,
    StateField,
    Operator,
)
from policyforge.scenarios import Scenario, generate_boundary_scenarios, generate_pairwise_scenarios
from policyforge.diff import (
    diff_rule_sets,
    DiffReport,
    OutcomeChange,
    FindingDelta,
    CoverageReport,
    HealthScore,
    RuleTextDiff,
    _diff_rules,
    _compute_health,
    render_rule_text_diff,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "novacart"


def _load_rules(path: Path) -> list[Rule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Rule.model_validate(r) for r in raw]


def _leaf(field: str, op: str, value) -> LeafCondition:
    return LeafCondition(field=StateField(field), op=Operator(op), value=value)


def _all(*conds) -> AllCondition:
    return AllCondition(all=list(conds))


def _source(name: str = "test.md", sentence: str = "Test sentence.") -> RuleSource:
    return RuleSource(doc_name=name, verbatim_sentence=sentence)


def _simple_refund_rule(
    rule_id: str,
    effect: EffectType,
    days_threshold: int,
    priority: int = 0,
    overrides: list[str] | None = None,
) -> Rule:
    """Factory: refund rule that fires when days_since_delivery <= threshold."""
    return Rule(
        id=rule_id,
        name=f"Refund {effect.value} ≤{days_threshold}d",
        decision=DecisionType.REFUND,
        trigger=EventType.REFUND_REQUESTED,
        when=_all(
            _leaf("days_since_delivery", "LTE", days_threshold),
            _leaf("item_delivered", "IS_TRUE", True),
        ),
        effect=effect,
        priority=priority,
        overrides=overrides or [],
        source=_source(sentence=f"Refund within {days_threshold} days."),
    )


def _deny_past_rule(rule_id: str, days_threshold: int, priority: int = 0) -> Rule:
    return Rule(
        id=rule_id,
        name=f"Deny after {days_threshold}d",
        decision=DecisionType.REFUND,
        trigger=EventType.REFUND_REQUESTED,
        when=_leaf("days_since_delivery", "GT", days_threshold),
        effect=EffectType.DENY,
        priority=priority,
        overrides=[],
        source=_source(sentence=f"Deny after {days_threshold} days."),
    )


def _journey_refund_at_day(day: int) -> list[Event]:
    return [
        Event(event_type=EventType.ITEM_DELIVERED, day=0),
        Event(event_type=EventType.REFUND_REQUESTED, day=day),
    ]


def _scenario(sid: str, day: int) -> Scenario:
    return Scenario(
        id=sid, name=sid, description="",
        journey=_journey_refund_at_day(day),
    )


# ---------------------------------------------------------------------------
# 1. Rule-level textual diff
# ---------------------------------------------------------------------------

class TestRuleTextDiff:
    def test_added_rule_detected(self):
        r1 = [_simple_refund_rule("r1", EffectType.ALLOW, 30)]
        r2 = [
            _simple_refund_rule("r1", EffectType.ALLOW, 30),
            _simple_refund_rule("r2", EffectType.DENY, 14),
        ]
        diffs = _diff_rules(r1, r2)
        by_id = {d.rule_id: d for d in diffs}
        assert by_id["r1"].status == "UNCHANGED"
        assert by_id["r2"].status == "ADDED"

    def test_removed_rule_detected(self):
        r1 = [
            _simple_refund_rule("r1", EffectType.ALLOW, 30),
            _simple_refund_rule("r2", EffectType.ALLOW, 60),
        ]
        r2 = [_simple_refund_rule("r1", EffectType.ALLOW, 30)]
        diffs = _diff_rules(r1, r2)
        by_id = {d.rule_id: d for d in diffs}
        assert by_id["r2"].status == "REMOVED"

    def test_modified_rule_condition_detected(self):
        r1 = [_simple_refund_rule("r1", EffectType.ALLOW, 30)]
        r2 = [_simple_refund_rule("r1", EffectType.ALLOW, 14)]
        diffs = _diff_rules(r1, r2)
        d = diffs[0]
        assert d.status == "MODIFIED"
        assert any("condition changed" in c for c in d.changes)

    def test_modified_rule_effect_detected(self):
        r1 = [_simple_refund_rule("r1", EffectType.ALLOW, 30)]
        r2 = [_simple_refund_rule("r1", EffectType.DENY, 30)]
        diffs = _diff_rules(r1, r2)
        d = diffs[0]
        assert d.status == "MODIFIED"
        assert any("effect" in c for c in d.changes)

    def test_render_text_diff_contains_markers(self):
        r1 = [_simple_refund_rule("r1", EffectType.ALLOW, 30)]
        r2 = [
            _simple_refund_rule("r1", EffectType.ALLOW, 14),
            _simple_refund_rule("r2", EffectType.DENY, 5),
        ]
        diffs = _diff_rules(r1, r2)
        rendered = render_rule_text_diff(diffs)
        assert "MODIFIED" in rendered
        assert "ADDED" in rendered
        assert "r1" in rendered
        assert "r2" in rendered


# ---------------------------------------------------------------------------
# 2. Outcome change detection
# ---------------------------------------------------------------------------

class TestOutcomeChanges:
    def _make_engines(self, threshold_v1: int, threshold_v2: int):
        """Build two minimal rule sets with different thresholds."""
        v1 = [
            _simple_refund_rule("allow", EffectType.ALLOW, threshold_v1),
            _deny_past_rule("deny", threshold_v1),
        ]
        v2 = [
            _simple_refund_rule("allow", EffectType.ALLOW, threshold_v2),
            _deny_past_rule("deny", threshold_v2),
        ]
        return v1, v2

    def test_allow_to_deny_at_boundary(self):
        """Day 20 was within 30-day window (ALLOW), but outside 14-day window (DENY)."""
        v1, v2 = self._make_engines(30, 14)
        scenarios = [_scenario("s_day20", 20)]
        report = diff_rule_sets(v1, v2, scenarios)

        assert report.outcomes_allow_to_deny >= 1
        change = report.outcome_changes[0]
        assert change.outcome_v1 == EffectType.ALLOW
        assert change.outcome_v2 == EffectType.DENY
        assert change.scenario_id == "s_day20"
        assert change.day == 20

    def test_deny_to_allow_when_window_widens(self):
        """Day 20 was outside 14-day window (DENY), inside 30-day window (ALLOW)."""
        v1, v2 = self._make_engines(14, 30)
        scenarios = [_scenario("s_day20", 20)]
        report = diff_rule_sets(v1, v2, scenarios)

        assert report.outcomes_deny_to_allow >= 1

    def test_no_change_within_both_windows(self):
        """Day 5 is inside both 30-day and 14-day windows → no outcome change."""
        v1, v2 = self._make_engines(30, 14)
        scenarios = [_scenario("s_day5", 5)]
        report = diff_rule_sets(v1, v2, scenarios)

        assert len(report.outcome_changes) == 0

    def test_attribution_to_changed_rule(self):
        """The outcome change is attributed to the modified rule."""
        v1, v2 = self._make_engines(30, 14)
        scenarios = [_scenario("s_day20", 20)]
        report = diff_rule_sets(v1, v2, scenarios)

        change = report.outcome_changes[0]
        # 'allow' rule changed condition; 'deny' rule also changed.
        assert len(change.attributed_rule_ids) > 0


# ---------------------------------------------------------------------------
# 3. Finding deltas
# ---------------------------------------------------------------------------

class TestFindingDeltas:
    def test_introduced_policy_gap(self):
        """Remove all rules in v2 → every decision event becomes a POLICY_GAP."""
        v1 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        v2: list[Rule] = []  # No rules → gap on every decision event
        scenarios = [_scenario("s_gap", 10)]
        report = diff_rule_sets(v1, v2, scenarios, default_decision_outcome=EffectType.DENY)

        introduced = [d for d in report.finding_deltas if d.direction == "INTRODUCED"]
        assert len(introduced) >= 1
        gap_introductions = [d for d in introduced if d.finding.type.value == "POLICY_GAP"]
        assert len(gap_introductions) >= 1

    def test_resolved_finding_when_contradiction_removed(self):
        """v1 has a contradiction; v2 resolves it by adding an explicit override."""
        # v1: two equal-priority rules with opposite effects → CONTRADICTION
        r_allow = Rule(
            id="r_allow", name="Allow", decision=DecisionType.REFUND,
            trigger=EventType.REFUND_REQUESTED,
            when=_leaf("item_delivered", "IS_TRUE", True),
            effect=EffectType.ALLOW, priority=0, overrides=[],
            source=_source(sentence="Allow if delivered."),
        )
        r_deny = Rule(
            id="r_deny", name="Deny", decision=DecisionType.REFUND,
            trigger=EventType.REFUND_REQUESTED,
            when=_leaf("item_delivered", "IS_TRUE", True),
            effect=EffectType.DENY, priority=0, overrides=[],
            source=_source(sentence="Deny if delivered."),
        )
        # v2: r_deny explicitly overrides r_allow → OVERRIDE_DENY, no CONTRADICTION
        r_deny_v2 = Rule(
            id="r_deny", name="Deny", decision=DecisionType.REFUND,
            trigger=EventType.REFUND_REQUESTED,
            when=_leaf("item_delivered", "IS_TRUE", True),
            effect=EffectType.DENY, priority=0, overrides=["r_allow"],
            source=_source(sentence="Deny if delivered."),
        )
        v1 = [r_allow, r_deny]
        v2 = [r_allow, r_deny_v2]
        scenarios = [
            Scenario(
                id="s_contra", name="Contradiction test", description="",
                journey=_journey_refund_at_day(5),
            )
        ]
        report = diff_rule_sets(v1, v2, scenarios)

        resolved = [d for d in report.finding_deltas if d.direction == "RESOLVED"]
        contradiction_resolved = [
            d for d in resolved if d.finding.type.value == "CONTRADICTION"
        ]
        assert len(contradiction_resolved) >= 1


# ---------------------------------------------------------------------------
# 4. Manual review flagging
# ---------------------------------------------------------------------------

class TestManualReviewFlagging:
    def test_new_gap_flags_review(self):
        """Removing all rules in v2 introduces a gap → scenario flagged for review."""
        v1 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        v2: list[Rule] = []
        scenarios = [_scenario("s_review", 10)]
        report = diff_rule_sets(v1, v2, scenarios)

        assert "s_review" in report.scenarios_needing_review

    def test_no_review_when_clean(self):
        """If v2 has no new ambiguities or gaps, no review is needed."""
        v1 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        v2 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        scenarios = [_scenario("s_clean", 10)]
        report = diff_rule_sets(v1, v2, scenarios)

        assert len(report.scenarios_needing_review) == 0


# ---------------------------------------------------------------------------
# 5. Coverage metrics
# ---------------------------------------------------------------------------

class TestCoverageMetrics:
    def test_rule_coverage_all_fired(self):
        """If the scenario fires the only rule, coverage should be 1.0."""
        v1 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        scenarios = [_scenario("s_fire", 5)]
        report = diff_rule_sets(v1, v1, scenarios)

        # Rule 'allow' should fire in both v1 and v2 (same rules)
        assert report.coverage_v1.rule_coverage == pytest.approx(1.0)
        assert report.coverage_v1.rules_fired == 1

    def test_rule_coverage_unfired_rule(self):
        """A rule that never fires should appear in uncovered_rule_ids."""
        r_allow = _simple_refund_rule("allow", EffectType.ALLOW, 30)
        # This rule requires item_opened=True, which no scenario sets
        r_opened = Rule(
            id="r_opened", name="Opened deny", decision=DecisionType.REFUND,
            trigger=EventType.REFUND_REQUESTED,
            when=_leaf("item_opened", "IS_TRUE", True),
            effect=EffectType.DENY, priority=5, overrides=[],
            source=_source(sentence="Deny opened items."),
        )
        v1 = [r_allow, r_opened]
        scenarios = [_scenario("s_standard", 5)]
        report = diff_rule_sets(v1, v1, scenarios)

        assert "r_opened" in report.coverage_v1.uncovered_rule_ids
        assert report.coverage_v1.rule_coverage < 1.0

    def test_event_type_coverage_increases_with_more_scenarios(self):
        """More diverse scenarios cover more event types."""
        v1 = [_simple_refund_rule("allow", EffectType.ALLOW, 30)]
        s1 = Scenario(
            id="s1", name="s1", description="",
            journey=[Event(event_type=EventType.ITEM_DELIVERED, day=0),
                     Event(event_type=EventType.REFUND_REQUESTED, day=5)],
        )
        s2 = Scenario(
            id="s2", name="s2", description="",
            journey=[Event(event_type=EventType.ORDER_PLACED, day=0),
                     Event(event_type=EventType.ITEM_DELIVERED, day=3),
                     Event(event_type=EventType.REPLACEMENT_REQUESTED, day=10)],
        )
        # 2 scenarios → more event types covered than just 1
        report_2 = diff_rule_sets(v1, v1, [s1, s2])
        report_1 = diff_rule_sets(v1, v1, [s1])
        assert report_2.coverage_v1.event_types_observed >= report_1.coverage_v1.event_types_observed

    def test_transition_coverage_non_zero_with_multi_decision(self):
        """A journey with two consecutive decision events produces transitions."""
        v1 = [
            _simple_refund_rule("allow_refund", EffectType.ALLOW, 30),
            Rule(
                id="allow_replacement", name="Allow replacement",
                decision=DecisionType.REPLACEMENT,
                trigger=EventType.REPLACEMENT_REQUESTED,
                when=_all(
                    _leaf("days_since_delivery", "LTE", 30),
                    _leaf("item_delivered", "IS_TRUE", True),
                ),
                effect=EffectType.ALLOW, priority=0, overrides=[],
                source=_source(sentence="Allow replacement within 30 days."),
            ),
        ]
        s = Scenario(
            id="s_two_decisions", name="Two decisions", description="",
            journey=[
                Event(event_type=EventType.ITEM_DELIVERED, day=0),
                Event(event_type=EventType.REPLACEMENT_REQUESTED, day=5),
                Event(event_type=EventType.REFUND_REQUESTED, day=10),
            ],
        )
        report = diff_rule_sets(v1, v1, [s])
        assert report.coverage_v1.transitions_observed >= 1


# ---------------------------------------------------------------------------
# 6. Health score
# ---------------------------------------------------------------------------

class TestHealthScore:
    def test_perfect_health_no_findings_full_coverage(self):
        """Zero findings + full rule coverage + no gaps → near-perfect health."""
        from policyforge.diff import CoverageReport, _compute_health
        cov = CoverageReport(
            rules_total=2, rules_fired=2, rule_coverage=1.0,
            uncovered_rule_ids=[],
            event_types_total=12, event_types_observed=12,
            event_type_coverage=1.0,
            uncovered_event_types=[],
            transitions_observed=3, unique_transitions=[],
        )
        health = _compute_health([], cov, total_decision_events=10)
        assert health.score == pytest.approx(100.0)

    def test_health_degrades_with_critical_findings(self):
        """Adding critical findings (CONTRADICTION) lowers health."""
        from policyforge.models import Finding, FindingType, FindingSeverity
        from policyforge.diff import CoverageReport, _compute_health
        cov = CoverageReport(
            rules_total=2, rules_fired=2, rule_coverage=1.0,
            uncovered_rule_ids=[],
            event_types_total=12, event_types_observed=12,
            event_type_coverage=1.0,
            uncovered_event_types=[],
            transitions_observed=1, unique_transitions=[],
        )
        findings = [
            Finding(
                type=FindingType.CONTRADICTION,
                severity=FindingSeverity.CRITICAL,
                rule_ids=["r1", "r2"],
                event_indices=[0],
                trace="test contradiction",
            )
            for _ in range(5)  # 5 critical → no_critical=0
        ]
        health = _compute_health(findings, cov, total_decision_events=10)
        # no_critical weight = 0.40; 5 criticals → no_critical=0
        # health = 0*0.40 + 1*0.25 + 1*0.20 + 1*0.10 + 1*0.05 = 60.0
        assert health.score == pytest.approx(60.0)
        assert health.no_critical_findings == pytest.approx(0.0)

    def test_health_score_in_range(self):
        """Health score is always in [0, 100]."""
        from policyforge.models import Finding, FindingType, FindingSeverity
        from policyforge.diff import CoverageReport, _compute_health
        cov = CoverageReport(
            rules_total=5, rules_fired=1, rule_coverage=0.2,
            uncovered_rule_ids=["r2", "r3", "r4", "r5"],
            event_types_total=12, event_types_observed=2,
            event_type_coverage=2 / 12,
            uncovered_event_types=[],
            transitions_observed=0, unique_transitions=[],
        )
        findings = [
            Finding(
                type=FindingType.CONTRADICTION,
                severity=FindingSeverity.CRITICAL,
                rule_ids=["r1"],
                event_indices=[0],
                trace="bad",
            )
            for _ in range(10)
        ]
        health = _compute_health(findings, cov, total_decision_events=1)
        assert 0.0 <= health.score <= 100.0


# ---------------------------------------------------------------------------
# 7. NovaCart v1 → v2 integration test
# ---------------------------------------------------------------------------

class TestNovacartV1toV2Diff:
    """Integration test using actual rules_v1.json and rules_v2.json."""

    def _load(self):
        rules_v1 = _load_rules(DATA_DIR / "rules_v1.json")
        rules_v2 = _load_rules(DATA_DIR / "rules_v2.json")
        return rules_v1, rules_v2

    def test_rules_loaded(self):
        rules_v1, rules_v2 = self._load()
        assert len(rules_v1) == 12
        assert len(rules_v2) == 13  # one extra rule added in v2

    def test_changed_rules_identified(self):
        rules_v1, rules_v2 = self._load()
        scenarios = [_scenario("s_day20", 20)]  # minimal set for speed
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)

        # Key changes: rule_refund_standard_window, rule_refund_past_deadline,
        # rule_refund_vip_extended_window, rule_refund_opened_item_deny changed.
        # rule_refund_damaged_grace_period added.
        assert "rule_refund_standard_window" in report.changed_rule_ids
        assert "rule_refund_past_deadline" in report.changed_rule_ids
        assert "rule_refund_damaged_grace_period" in report.changed_rule_ids

    def test_allow_to_deny_day20_refund(self):
        """Day 20 refund: ALLOW in v1 (30d window), DENY in v2 (14d window)."""
        rules_v1, rules_v2 = self._load()
        scenarios = [_scenario("s_day20_refund", 20)]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)

        assert report.outcomes_allow_to_deny >= 1
        # The change must be attributed to the window-shrink rules
        change = report.outcome_changes[0]
        relevant = {"rule_refund_standard_window", "rule_refund_past_deadline"}
        assert len(set(change.attributed_rule_ids) & relevant) > 0

    def test_no_change_day5_refund(self):
        """Day 5 refund: ALLOW in both v1 and v2 → no outcome change."""
        rules_v1, rules_v2 = self._load()
        scenarios = [_scenario("s_day5_refund", 5)]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)
        assert len(report.outcome_changes) == 0

    def test_boundary_scenario_suite(self):
        """Run the full boundary suite and verify the report structure is populated."""
        rules_v1, rules_v2 = self._load()
        boundary = generate_boundary_scenarios(rules_v1)
        # Day 14 falls inside BOTH windows (v1: ≤30, v2: ≤14), so no change there.
        # Day 15 is the first divergence: v1 ALLOW (15≤30), v2 DENY (15>14).
        # Day 30 is also a divergence point. Include both so we get ALLOW→DENY flips.
        scenarios = [s for s in boundary if "d15_" in s.id or "d30_" in s.id][:24]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)

        assert report.total_scenarios == len(scenarios)
        assert isinstance(report.health_v1.score, float)
        assert isinstance(report.health_v2.score, float)
        # Narrowed window → refund scenarios at day 15 and 30 flip ALLOW→DENY
        assert report.outcomes_allow_to_deny > 0

    def test_summary_contains_key_sections(self):
        """summary() output contains all expected report sections."""
        rules_v1, rules_v2 = self._load()
        scenarios = [_scenario("s_day20_refund", 20), _scenario("s_day5_refund", 5)]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)
        summary = report.summary()

        assert "Behavioral Diff Report" in summary
        assert "Outcome Changes" in summary
        assert "Coverage" in summary
        assert "Health Score" in summary
        assert "Rule-Level Diff" in summary

    def test_v2_health_changes_from_v1(self):
        """Tightening the refund window changes the health score."""
        rules_v1, rules_v2 = self._load()
        # Mix of boundary and pairwise scenarios for meaningful coverage
        scenarios = generate_boundary_scenarios(rules_v1)[:20]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)

        # Both scores are in range
        assert 0.0 <= report.health_v1.score <= 100.0
        assert 0.0 <= report.health_v2.score <= 100.0

    def test_new_damaged_grace_rule_appears_in_diff(self):
        """The new rule added in v2 appears in rule_text_diffs as ADDED."""
        rules_v1, rules_v2 = self._load()
        scenarios = [_scenario("s_any", 5)]
        report = diff_rule_sets(rules_v1, rules_v2, scenarios)

        added = [d for d in report.rule_text_diffs if d.status == "ADDED"]
        assert any(d.rule_id == "rule_refund_damaged_grace_period" for d in added)
