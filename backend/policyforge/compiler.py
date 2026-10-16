"""Policy compiler: natural-language policy documents -> validated, grounded Rule objects."""

from __future__ import annotations

import re
import json
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from policyforge.models import (
    EventType,
    DecisionType,
    EffectType,
    Operator,
    StateField,
    Rule,
    RuleSource,
)
from policyforge.detectors import is_condition_satisfiable
from policyforge.llm import LLMClient


@dataclass
class Clause:
    """A numbered section or clause extracted from a policy document."""
    id: str
    text: str
    doc_name: str
    line_number: int


@dataclass
class RuleConfidence:
    """Quality and confidence metrics for an individual compiled rule."""
    rule_id: str
    grounded: bool
    lint_clean: bool
    confidence: str  # HIGH, MEDIUM, LOW
    notes: list[str] = field(default_factory=list)


@dataclass
class CompileReport:
    """Compilation diagnostics, clause coverage, and rule confidence report."""
    total_clauses: int
    mapped_clauses: int
    unmapped_clauses: list[Clause]
    compiled_rules: list[Rule]
    rule_confidence: dict[str, RuleConfidence]
    rejected_rules: list[dict[str, Any]]
    lint_warnings: list[str]
    token_usage: dict[str, Any]
    latency_ms: float

    def summary(self) -> str:
        coverage_pct = (self.mapped_clauses / self.total_clauses * 100) if self.total_clauses else 0.0
        return (
            f"Compiled {len(self.compiled_rules)} rules from {self.total_clauses} clauses "
            f"({self.mapped_clauses} mapped, {len(self.unmapped_clauses)} unmapped, "
            f"{coverage_pct:.1f}% clause coverage). "
            f"Rejected: {len(self.rejected_rules)}, Lint warnings: {len(self.lint_warnings)}."
        )


def split_document_into_clauses(doc_text: str, doc_name: str) -> list[Clause]:
    """Split policy document text into discrete numbered clauses or paragraphs."""
    clauses: list[Clause] = []
    lines = doc_text.splitlines()

    # Regex for numbered patterns like [RP-1], [SOP-2], 1.2, Clause 3
    pattern = re.compile(r"^(\[[A-Z0-9_\-]+\]|\d+\.|\d+\.\d+|Clause\s+\d+:?)\s*(.+)$", re.IGNORECASE)

    current_id = ""
    current_text = []
    current_line = 1

    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        match = pattern.match(stripped)
        if match:
            if current_text:
                clauses.append(
                    Clause(
                        id=current_id or f"clause_{len(clauses)+1}",
                        text=" ".join(current_text),
                        doc_name=doc_name,
                        line_number=current_line,
                    )
                )
                current_text = []

            current_id = match.group(1).strip("[]: ")
            current_text.append(match.group(2).strip())
            current_line = line_idx
        else:
            if current_text:
                current_text.append(stripped)
            else:
                # Regular paragraph clause
                current_id = f"clause_{len(clauses)+1}"
                current_text.append(stripped)
                current_line = line_idx

    if current_text:
        clauses.append(
            Clause(
                id=current_id or f"clause_{len(clauses)+1}",
                text=" ".join(current_text),
                doc_name=doc_name,
                line_number=current_line,
            )
        )

    return clauses


def check_source_grounding(verbatim_sentence: str, document_text: str) -> bool:
    """Verify that verbatim_sentence appears in the document text under whitespace normalization."""
    norm_sentence = " ".join(verbatim_sentence.lower().split())
    norm_doc = " ".join(document_text.lower().split())
    return norm_sentence in norm_doc


def _build_system_prompt() -> str:
    event_types = [e.value for e in EventType]
    state_fields = [f.value for f in StateField]
    decisions = [d.value for d in DecisionType]
    effects = [e.value for e in EffectType]
    operators = [o.value for o in Operator]

    return f"""You are PolicyForge Compiler, an expert at compiling natural language business policy clauses into structured deterministic Rule schemas.

CRITICAL CONSTRAINTS:
1. Closed Vocabularies:
- trigger: must be one of {event_types}
- decision: must be one of {decisions}
- effect: must be one of {effects}
- condition field: must be one of {state_fields}
- condition op: must be one of {operators}

2. Condition Tree Format:
- Leaf condition: {{"field": "<Field>", "op": "<Op>", "value": <Literal>}}
- All condition: {{"all": [<Condition>, ...]}}
- Any condition: {{"any": [<Condition>, ...]}}

3. Source Grounding:
Every rule must include a "source" dict with "doc_name" and "verbatim_sentence".
The "verbatim_sentence" MUST BE COPIED EXACTLY word-for-word from the text.

Output MUST be a JSON object containing a "rules" array. If a clause contains no business rule, return {{"rules": []}}.
"""


class PolicyCompiler:
    """Compiles policy documents into structured rules with grounding checks and linting."""

    def __init__(self, llm_client: LLMClient | None = None, max_repairs: int = 2) -> None:
        self.llm_client = llm_client or LLMClient()
        self.max_repairs = max_repairs

    def _compile_clause_with_self_repair(
        self, clause: Clause, doc_name: str, full_doc_text: str
    ) -> tuple[list[Rule], list[dict[str, Any]]]:
        """Extract rules from a clause with automatic LLM self-repair on schema errors."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _build_system_prompt()},
            {
                "role": "user",
                "content": (
                    f"Document: {doc_name}\n"
                    f"Clause [{clause.id}]: {clause.text}\n\n"
                    f"Extract any business policy rules from this clause as a JSON object {{\"rules\": [...]}}."
                ),
            },
        ]

        rules: list[Rule] = []
        rejected: list[dict[str, Any]] = []

        for attempt in range(self.max_repairs + 1):
            raw_response = self.llm_client.chat_complete(
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            try:
                # Strip markdown code blocks if present
                clean_json = raw_response.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.startswith("```"):
                    clean_json = clean_json[3:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()

                parsed = json.loads(clean_json)
                raw_rules = parsed.get("rules", [])
                if not isinstance(raw_rules, list):
                    raise ValueError(f"Expected 'rules' list, got {type(raw_rules).__name__}")

                for r_dict in raw_rules:
                    # Grounding check in code
                    source = r_dict.get("source", {})
                    verbatim = source.get("verbatim_sentence", "")
                    if not verbatim or not check_source_grounding(verbatim, full_doc_text):
                        rejected.append({
                            "raw_rule": r_dict,
                            "reason": f"Grounding check failed: verbatim sentence '{verbatim}' not found in document.",
                            "clause_id": clause.id,
                        })
                        continue

                    # Validate with Pydantic
                    rule_obj = Rule.model_validate(r_dict)
                    rules.append(rule_obj)

                # Successfully parsed
                return rules, rejected

            except (json.JSONDecodeError, ValidationError, ValueError) as err:
                if attempt < self.max_repairs:
                    # Self-repair prompt back to LLM
                    messages.append({"role": "assistant", "content": raw_response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your output failed validation with error: {err}.\n"
                            f"Please repair the JSON so that every field strictly adheres to the schema "
                            f"and closed vocabularies, and return {{\"rules\": [...]}}."
                        ),
                    })
                else:
                    rejected.append({
                        "clause_id": clause.id,
                        "raw_response": raw_response,
                        "reason": f"Validation failed after {self.max_repairs} self-repairs: {err}",
                    })

        return rules, rejected

    def compile_document(self, doc_text: str, doc_name: str) -> CompileReport:
        """Compile a policy document into validated rules with coverage and lint analysis."""
        start_time = time.perf_counter()
        clauses = split_document_into_clauses(doc_text, doc_name)

        compiled_rules: list[Rule] = []
        all_rejected: list[dict[str, Any]] = []
        mapped_clause_ids: set[str] = set()

        for clause in clauses:
            rules, rejected = self._compile_clause_with_self_repair(
                clause, doc_name, doc_text
            )
            all_rejected.extend(rejected)
            if rules:
                compiled_rules.extend(rules)
                mapped_clause_ids.add(clause.id)

        # Unmapped clauses
        unmapped = [c for c in clauses if c.id not in mapped_clause_ids]

        # Linting after compiling
        lint_warnings: list[str] = []
        rule_confidence: dict[str, RuleConfidence] = {}

        seen_rule_sigs: dict[tuple, str] = {}
        for r in compiled_rules:
            notes: list[str] = []
            lint_clean = True

            # Lint 1: Unsatisfiable condition
            sat, reason = is_condition_satisfiable(r.when)
            if not sat:
                lint_clean = False
                msg = f"Rule '{r.id}' has unsatisfiable condition: {reason}."
                notes.append(msg)
                lint_warnings.append(msg)

            # Lint 2: Duplicate rule
            # Rule signature: trigger + decision + effect + priority + serialized condition
            cond_str = json.dumps(r.when.model_dump(), sort_keys=True)
            sig = (r.trigger, r.decision, r.effect, r.priority, cond_str)
            if sig in seen_rule_sigs:
                lint_clean = False
                msg = f"Rule '{r.id}' duplicates logic from '{seen_rule_sigs[sig]}'."
                notes.append(msg)
                lint_warnings.append(msg)
            else:
                seen_rule_sigs[sig] = r.id

            confidence = "HIGH" if lint_clean else "MEDIUM"
            rule_confidence[r.id] = RuleConfidence(
                rule_id=r.id,
                grounded=True,  # All compiled rules passed grounding check
                lint_clean=lint_clean,
                confidence=confidence,
                notes=notes,
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        token_usage = self.llm_client.get_total_usage()

        return CompileReport(
            total_clauses=len(clauses),
            mapped_clauses=len(mapped_clause_ids),
            unmapped_clauses=unmapped,
            compiled_rules=compiled_rules,
            rule_confidence=rule_confidence,
            rejected_rules=all_rejected,
            lint_warnings=lint_warnings,
            token_usage=token_usage,
            latency_ms=elapsed_ms,
        )

    def compile_documents(self, docs: dict[str, str]) -> CompileReport:
        """Compile a dictionary of {doc_name: doc_text} into a consolidated CompileReport."""
        start_time = time.perf_counter()
        all_rules: list[Rule] = []
        all_rejected: list[dict[str, Any]] = []
        all_unmapped: list[Clause] = []
        all_lint_warnings: list[str] = []
        all_confidence: dict[str, RuleConfidence] = {}
        total_clauses = 0
        mapped_clauses = 0

        for doc_name, doc_text in docs.items():
            report = self.compile_document(doc_text, doc_name)
            total_clauses += report.total_clauses
            mapped_clauses += report.mapped_clauses
            all_rules.extend(report.compiled_rules)
            all_rejected.extend(report.rejected_rules)
            all_unmapped.extend(report.unmapped_clauses)
            all_lint_warnings.extend(report.lint_warnings)
            all_confidence.update(report.rule_confidence)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        token_usage = self.llm_client.get_total_usage()

        return CompileReport(
            total_clauses=total_clauses,
            mapped_clauses=mapped_clauses,
            unmapped_clauses=all_unmapped,
            compiled_rules=all_rules,
            rule_confidence=all_confidence,
            rejected_rules=all_rejected,
            lint_warnings=all_lint_warnings,
            token_usage=token_usage,
            latency_ms=elapsed_ms,
        )
