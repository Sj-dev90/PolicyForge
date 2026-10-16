"""Domain schemas and models for PolicyForge.

All schemas are strictly typed with closed vocabularies (Enums).
Any attribute or enum value outside these vocabularies is rejected.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventType(str, Enum):
    """Closed vocabulary of journey events."""
    ORDER_PLACED = "ORDER_PLACED"
    ITEM_DELIVERED = "ITEM_DELIVERED"
    REPLACEMENT_REQUESTED = "REPLACEMENT_REQUESTED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    RETURN_RECEIVED = "RETURN_RECEIVED"
    REPLACEMENT_CANCELLED = "REPLACEMENT_CANCELLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ITEM_DAMAGED_REPORTED = "ITEM_DAMAGED_REPORTED"
    REFUND_COMPLETED = "REFUND_COMPLETED"
    REPLACEMENT_DELIVERED = "REPLACEMENT_DELIVERED"
    CHARGEBACK_FILED = "CHARGEBACK_FILED"
    CHARGEBACK_RESOLVED = "CHARGEBACK_RESOLVED"


class DecisionType(str, Enum):
    """Decision domain categories."""
    REFUND = "REFUND"
    REPLACEMENT = "REPLACEMENT"


class EffectType(str, Enum):
    """Rule outcomes."""
    ALLOW = "ALLOW"
    DENY = "DENY"


class Operator(str, Enum):
    """Supported comparator operators for conditions (no eval/exec)."""
    EQ = "EQ"
    NEQ = "NEQ"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    IN = "IN"
    NIN = "NIN"
    IS_TRUE = "IS_TRUE"
    IS_FALSE = "IS_FALSE"
    IS_NULL = "IS_NULL"
    IS_NOT_NULL = "IS_NOT_NULL"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        # Support common mathematical symbols
        mapping = {
            "==": cls.EQ,
            "!=": cls.NEQ,
            "<": cls.LT,
            "<=": cls.LTE,
            ">": cls.GT,
            ">=": cls.GTE,
        }
        if isinstance(value, str) and value in mapping:
            return mapping[value]
        return super()._missing_(value)


class CustomerTier(str, Enum):
    """Customer loyalty tier."""
    STANDARD = "STANDARD"
    VIP = "VIP"


class StateField(str, Enum):
    """Closed vocabulary of tracked and derived state fields."""
    ORDER_PLACED = "order_placed"
    ORDER_DAY = "order_day"
    ITEM_DELIVERED = "item_delivered"
    DELIVERY_DAY = "delivery_day"
    DAYS_SINCE_DELIVERY = "days_since_delivery"
    REPLACEMENT_REQUESTED = "replacement_requested"
    REPLACEMENT_REQUEST_DAY = "replacement_request_day"
    REPLACEMENT_CANCELLED = "replacement_cancelled"
    REPLACEMENT_CANCEL_DAY = "replacement_cancel_day"
    REPLACEMENT_ACTIVE = "replacement_active"
    REPLACEMENT_COMPLETED = "replacement_completed"
    REPLACEMENT_COMPLETED_DAY = "replacement_completed_day"
    REFUND_REQUESTED = "refund_requested"
    REFUND_REQUEST_DAY = "refund_request_day"
    REFUND_COMPLETED = "refund_completed"
    REFUND_COMPLETED_DAY = "refund_completed_day"
    RETURN_RECEIVED = "return_received"
    ITEM_DAMAGED = "item_damaged"
    IS_FINAL_SALE = "is_final_sale"
    ITEM_OPENED = "item_opened"
    CUSTOMER_TIER = "customer_tier"
    REFUND_ELIGIBILITY_RESTORED = "refund_eligibility_restored"
    ACTION_DENIED = "action_denied"
    AMOUNT_PAID = "amount_paid"
    REFUND_AMOUNT = "refund_amount"
    CHARGEBACK_ACTIVE = "chargeback_active"


class State(BaseModel):
    """Tracks current state of an order journey."""
    order_placed: bool = False
    order_day: int | None = None
    item_delivered: bool = False
    delivery_day: int | None = None
    days_since_delivery: int | None = None
    replacement_requested: bool = False
    replacement_request_day: int | None = None
    replacement_cancelled: bool = False
    replacement_cancel_day: int | None = None
    replacement_active: bool = False
    replacement_completed: bool = False
    replacement_completed_day: int | None = None
    refund_requested: bool = False
    refund_request_day: int | None = None
    refund_completed: bool = False
    refund_completed_day: int | None = None
    return_received: bool = False
    item_damaged: bool = False
    is_final_sale: bool = False
    item_opened: bool = False
    customer_tier: CustomerTier = CustomerTier.STANDARD
    refund_eligibility_restored: bool = False
    action_denied: bool = False
    amount_paid: float = 0.0
    refund_amount: float = 0.0
    chargeback_active: bool = False

    model_config = ConfigDict(extra="forbid")

    def update_derived_day(self, current_day: int) -> None:
        """Derive days_since_delivery given the current event day."""
        if self.item_delivered and self.delivery_day is not None:
            self.days_since_delivery = max(0, current_day - self.delivery_day)
        else:
            self.days_since_delivery = None


# --- Condition Tree Models ---

class LeafCondition(BaseModel):
    """Atomic condition leaf comparing a state field against a literal value."""
    field: StateField
    op: Operator
    value: Any = None

    model_config = ConfigDict(extra="forbid")


class AllCondition(BaseModel):
    """Logical AND of nested conditions."""
    all: list[ConditionTree]

    model_config = ConfigDict(extra="forbid")


class AnyCondition(BaseModel):
    """Logical OR of nested conditions."""
    any: list[ConditionTree]

    model_config = ConfigDict(extra="forbid")


# Type alias for condition tree
ConditionTree = Union[AllCondition, AnyCondition, LeafCondition]

# Rebuild models to handle recursive type definitions in Pydantic v2
AllCondition.model_rebuild()
AnyCondition.model_rebuild()


def parse_condition_tree(data: Any) -> ConditionTree:
    """Helper to parse raw dicts into typed ConditionTree nodes."""
    if isinstance(data, (LeafCondition, AllCondition, AnyCondition)):
        return data
    if not isinstance(data, dict):
        raise ValueError(f"Condition must be a dictionary, got {type(data)}")
    if "all" in data:
        return AllCondition(all=[parse_condition_tree(c) for c in data["all"]])
    if "any" in data:
        return AnyCondition(any=[parse_condition_tree(c) for c in data["any"]])
    if "field" in data and "op" in data:
        return LeafCondition(**data)
    raise ValueError(f"Unrecognized condition format: {data}")


class RuleSource(BaseModel):
    """Origin documentation grounding for a rule."""
    doc_name: str
    verbatim_sentence: str

    model_config = ConfigDict(extra="forbid")


class Rule(BaseModel):
    """Executable business rule specification."""
    id: str
    name: str
    decision: DecisionType
    trigger: EventType
    when: ConditionTree
    effect: EffectType
    priority: int = 0
    overrides: list[str] = Field(default_factory=list)
    state_updates: dict[StateField, Any] | None = None
    source: RuleSource

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def parse_when_tree(cls, values: Any) -> Any:
        if isinstance(values, dict) and "when" in values:
            values["when"] = parse_condition_tree(values["when"])
        return values


class FindingType(str, Enum):
    """Categories of detected policy issues."""
    CONTRADICTION = "CONTRADICTION"
    POLICY_GAP = "POLICY_GAP"
    AMBIGUITY = "AMBIGUITY"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    DEAD_RULE = "DEAD_RULE"

    # Alias for backwards compatibility
    GAP = "POLICY_GAP"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        if value == "GAP":
            return cls.POLICY_GAP
        return super()._missing_(value)


class FindingSeverity(str, Enum):
    """Severity ratings for findings."""
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Finding(BaseModel):
    """Deterministic policy finding generated by the engine or detectors."""
    type: FindingType
    severity: FindingSeverity
    rule_ids: list[str] = Field(default_factory=list)
    event_indices: list[int] = Field(default_factory=list)
    trace: str
    details: dict[str, Any] | None = None

    model_config = ConfigDict(extra="forbid")


class LeafEvaluation(BaseModel):
    """Detailed boolean outcome for an individual leaf condition."""
    field: StateField
    op: Operator
    expected_value: Any
    actual_value: Any
    passed: bool
    description: str

    model_config = ConfigDict(extra="forbid")


class RuleEvaluationTrace(BaseModel):
    """Trace of evaluating an individual rule during a decision event."""
    rule_id: str
    rule_name: str
    effect: EffectType
    priority: int
    fired: bool
    leaf_evaluations: list[LeafEvaluation] = Field(default_factory=list)
    reason: str

    model_config = ConfigDict(extra="forbid")


class EventTrace(BaseModel):
    """Complete trace of an event step during simulation."""
    event_index: int
    day: int
    event_type: EventType
    is_decision_event: bool
    rules_evaluated: list[str] = Field(default_factory=list)
    rules_fired: list[str] = Field(default_factory=list)
    evaluations: list[RuleEvaluationTrace] = Field(default_factory=list)
    resolution_type: str
    outcome: EffectType
    active_rules: list[str] = Field(default_factory=list)
    suppressed_rules: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    state_before: State
    state_after: State
    explanation: str

    model_config = ConfigDict(extra="forbid")


class Trace(BaseModel):
    """Full journey trace."""
    event_traces: list[EventTrace] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class Event(BaseModel):
    """An event occurring along the customer journey."""
    event_type: EventType
    day: int
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class EventOutcome(BaseModel):
    """Per-event summary outcome."""
    event_index: int
    day: int
    event_type: EventType
    outcome: EffectType
    action_applied: bool
    resolution_type: str
    findings: list[Finding] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class SimulationResult(BaseModel):
    """Result of running a simulation on a journey."""
    outcomes: list[EventOutcome]
    final_state: State
    trace: Trace
    findings: list[Finding]

    model_config = ConfigDict(extra="forbid")
