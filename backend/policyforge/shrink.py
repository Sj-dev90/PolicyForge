"""Delta debugging (ddmin) and day shrinking for minimal counterexamples."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from policyforge.models import (
    EventType,
    Finding,
    FindingType,
    Event,
    State,
)
from policyforge.engine import PolicyEngine


@dataclass
class ShrinkResult:
    """Outcome of shrinking a failing journey."""
    original_journey: list[Event]
    minimal_journey: list[Event]
    engine_runs: int
    target_signature: tuple[FindingType, tuple[str, ...]]
    final_finding: Finding


def get_finding_signature(finding: Finding) -> tuple[FindingType, tuple[str, ...]]:
    """Compute a canonical signature for a finding based on type and sorted rule IDs."""
    return (finding.type, tuple(sorted(finding.rule_ids)))


def is_valid_journey(events: list[Event]) -> bool:
    """Check domain validity constraints on a candidate journey."""
    if not events:
        return False

    # Days must be non-decreasing and non-negative
    for i in range(len(events)):
        if events[i].day < 0:
            return False
        if i > 0 and events[i].day < events[i - 1].day:
            return False

    # Domain constraints:
    has_replacement_req = False
    has_delivery = False
    delivery_day = None

    for e in events:
        if e.event_type == EventType.ITEM_DELIVERED:
            has_delivery = True
            delivery_day = e.day
        elif e.event_type == EventType.REPLACEMENT_REQUESTED:
            has_replacement_req = True
        elif e.event_type == EventType.REPLACEMENT_CANCELLED:
            # Cancellation requires a prior replacement request
            if not has_replacement_req:
                return False
        elif e.event_type == EventType.REFUND_REQUESTED:
            # Standard refunds in our domain evaluate delivery
            pass

    return True


def _split_into_chunks(seq: list[Event], k: int) -> list[list[Event]]:
    """Partition a sequence into k roughly equal non-empty chunks."""
    n = len(seq)
    chunks: list[list[Event]] = []
    chunk_size = n / k
    for i in range(k):
        start = int(round(i * chunk_size))
        end = int(round((i + 1) * chunk_size))
        sub = seq[start:end]
        if sub:
            chunks.append(sub)
    return chunks


def shrink_journey(
    engine: PolicyEngine,
    journey: list[Event],
    target_signature: tuple[FindingType, tuple[str, ...]] | None = None,
    initial_state: State | None = None,
) -> ShrinkResult:
    """Reduce a failing journey to its 1-minimal counterexample using ddmin and day shrinking."""
    # Ensure chronological order
    working_journey = sorted([copy.deepcopy(e) for e in journey], key=lambda e: e.day)
    engine_runs = 0

    def test_candidate(candidate: list[Event]) -> Finding | None:
        nonlocal engine_runs
        if not is_valid_journey(candidate):
            return None
        engine_runs += 1
        res = engine.run(candidate, initial_state=initial_state)
        for f in res.findings:
            sig = get_finding_signature(f)
            if target_sig is None or sig == target_sig:
                return f
        return None

    # Step 0: Establish baseline failure
    baseline_res = engine.run(working_journey, initial_state=initial_state)
    engine_runs += 1

    target_finding: Finding | None = None
    if target_signature is None:
        if not baseline_res.findings:
            raise ValueError("Cannot shrink a journey that produces no findings.")
        target_finding = baseline_res.findings[0]
        target_sig = get_finding_signature(target_finding)
    else:
        target_sig = target_signature
        for f in baseline_res.findings:
            if get_finding_signature(f) == target_sig:
                target_finding = f
                break
        if target_finding is None:
            raise ValueError(f"Target signature {target_sig} not found in baseline journey.")

    # Step 1: Classical Delta Debugging (ddmin) to remove unneeded events
    seq = working_journey
    n = len(seq)
    k = 2

    while len(seq) >= 2:
        n = len(seq)
        chunks = _split_into_chunks(seq, k)
        reduced = False

        # Try complements (S \ chunk)
        for chunk in chunks:
            chunk_ids = {id(e) for e in chunk}
            complement = [e for e in seq if id(e) not in chunk_ids]
            f = test_candidate(complement)
            if f is not None:
                seq = complement
                target_finding = f
                k = max(k - 1, 2)
                reduced = True
                break

        if reduced:
            continue

        # Try subsets (chunk)
        if k > 2:
            for chunk in chunks:
                f = test_candidate(chunk)
                if f is not None:
                    seq = chunk
                    target_finding = f
                    k = 2
                    reduced = True
                    break

        if reduced:
            continue

        # Increase granularity
        if k < n:
            k = min(2 * k, n)
        else:
            break

    # Step 2: Day Shrinking (Binary search for minimum day preserving the failure)
    minimal_events = [copy.deepcopy(e) for e in seq]
    for i in range(len(minimal_events)):
        min_bound = 0 if i == 0 else minimal_events[i - 1].day
        orig_day = minimal_events[i].day

        if orig_day <= min_bound:
            continue

        # Binary search for smallest valid day in [min_bound, orig_day]
        best_day = orig_day
        low = min_bound
        high = orig_day - 1

        while low <= high:
            mid = (low + high) // 2
            candidate = [copy.deepcopy(e) for e in minimal_events]
            candidate[i].day = mid

            f = test_candidate(candidate)
            if f is not None:
                best_day = mid
                target_finding = f
                high = mid - 1  # Try smaller
            else:
                low = mid + 1  # Too small, try larger

        minimal_events[i].day = best_day

    return ShrinkResult(
        original_journey=journey,
        minimal_journey=minimal_events,
        engine_runs=engine_runs,
        target_signature=target_sig,
        final_finding=target_finding or baseline_res.findings[0],
    )
