# PolicyForge: project contract

## Mission
CI/CD for business policies. Natural-language policy -> structured rules ->
deterministic simulation -> verified failures -> minimal counterexamples ->
behavioral diff between policy versions. Domain: e-commerce refunds and
replacements for a fictional company, NovaCart.

## Core principle
The LLM (Nemotron via Nebius Token Factory) extracts rules, generates
scenarios, and explains findings. It NEVER decides whether a failure exists.
Only deterministic Python code produces findings.

## Non-negotiables
- Python 3.11, Pydantic v2, pytest, Hypothesis. Fully typed.
- No eval/exec. Rule conditions are structured data (nested all/any trees).
- Closed vocabularies: event types and state fields are enums. Anything the
  LLM outputs outside them is rejected, not guessed.
- Every finding carries: type, severity, rule_ids, event_indices, and a
  human-readable trace of how the engine reached it.
- Determinism: same rules + same journey = same result, always.
- Secrets only via .env; never commit them.
- Every module ships with tests; a stage is done only when pytest is green.
- Small commits, one per stage, with clear messages.

## Architecture
backend/
  policyforge/models.py       schemas (Rule, Event, State, Finding, Trace)
  policyforge/engine.py       simulator + rule evaluation + conflict resolution
  policyforge/detectors.py    contradiction, gap, ambiguity, invariants
  policyforge/shrink.py       minimal counterexample (delta debugging)
  policyforge/scenarios.py    boundary generator + LLM scenario validator
  policyforge/compiler.py     text -> rules with source grounding
  policyforge/diff.py         behavioral diff between rule sets
  policyforge/llm.py          Token Factory client (OpenAI-compatible)
  policyforge/api.py          FastAPI
  benchmark/                  labeled scenarios + runner
  data/novacart/              policy documents + rules + scenarios
frontend/                     Next.js + TypeScript + Tailwind + shadcn/ui
