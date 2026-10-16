# PolicyForge Execution & Conflict Resolution Semantics

This document formalizes the runtime semantics of the PolicyForge deterministic rule engine, state transitions, event types, condition evaluation, and conflict resolution rules.

---

## 1. Event Types & State Semantics

The vocabulary of events and state fields is **strictly closed** (represented by Enums).
Any event or field outside this specification is rejected at validation time.

### Closed Vocabularies

#### `EventType`
1. `ORDER_PLACED`: Initial placement of an e-commerce order.
2. `ITEM_DELIVERED`: Delivery of the purchased item to the customer. Marks the baseline for delivery-relative time limits.
3. `REPLACEMENT_REQUESTED`: Customer request to replace an item (Decision Event).
4. `REFUND_REQUESTED`: Customer request to refund an item (Decision Event).
5. `RETURN_RECEIVED`: Physical item received back at the warehouse/merchant.
6. `REPLACEMENT_CANCELLED`: Customer or system cancellation of a pending replacement.
7. `ORDER_CANCELLED`: Cancellation of the initial order before delivery.
8. `ITEM_DAMAGED_REPORTED`: Formal customer notification reporting transit or manufacturing defect.

#### `State` Fields
- `order_placed` (`bool`): Whether the order has been placed.
- `order_day` (`int | None`): Day index of order placement.
- `item_delivered` (`bool`): Whether the item has been delivered.
- `delivery_day` (`int | None`): Day index of delivery.
- `days_since_delivery` (`int | None`): Derived day delta (`current_event.day - delivery_day`). If not delivered, `None`.
- `replacement_requested` (`bool`): Whether a replacement has been successfully requested.
- `replacement_request_day` (`int | None`): Day of active replacement request.
- `replacement_cancelled` (`bool`): Whether an active replacement was cancelled.
- `replacement_cancel_day` (`int | None`): Day replacement was cancelled.
- `refund_requested` (`bool`): Whether a refund has been successfully requested.
- `refund_request_day` (`int | None`): Day of refund request.
- `return_received` (`bool`): Whether the returned item was physically received.
- `item_damaged` (`bool`): Whether the item was reported damaged/defective.
- `is_final_sale` (`bool`): Flag denoting non-returnable / clearance merchandise.
- `item_opened` (`bool`): Flag denoting whether packaging/seals have been opened.
- `customer_tier` (`CustomerTier`: `STANDARD`, `VIP`): Customer loyalty tier.
- `refund_eligibility_restored` (`bool`): Special state flag, e.g. restored after replacement cancellation or support override.
- `action_denied` (`bool`): Tracks whether the most recent decision was denied.

### Event Processing Lifecycle & State Updates

When an event at day `t` is processed:
1. `current_day` moves forward to `t`. If `item_delivered` is true (or becomes true in this event), `days_since_delivery` is derived as `t - delivery_day`.
2. **Decision vs Non-Decision Events**:
   - **Non-Decision Events** (`ORDER_PLACED`, `ITEM_DELIVERED`, `ORDER_CANCELLED`, `RETURN_RECEIVED`, `REPLACEMENT_CANCELLED`, `ITEM_DAMAGED_REPORTED`):
     - State transitions apply deterministically according to event semantics.
     - No policy rules are evaluated (or default outcome ALLOW with no decision conflict).
   - **Decision Events** (`REFUND_REQUESTED`, `REPLACEMENT_REQUESTED`):
     - Triggered rules matching `trigger == event.event_type` and `decision == expected_decision` are evaluated against current state and event payload.
     - Conflict resolution resolves to an `Outcome` (`ALLOW` or `DENY`).
     - **Denial Semantics**: If the resolved outcome is `DENY`, the requested action **does NOT take effect**. Specifically:
       - For `REFUND_REQUESTED`: `refund_requested` remains `False`, `refund_request_day` remains `None`.
       - For `REPLACEMENT_REQUESTED`: `replacement_requested` remains `False`, `replacement_request_day` remains `None`.
       - `action_denied` is set to `True`.
     - **Approval Semantics**: If the resolved outcome is `ALLOW`:
       - The state fields for the action are set (`refund_requested = True`, etc.).
       - Any `state_updates` specified by winning firing rules are applied to state.
       - `action_denied` is set to `False`.

---

## 2. Condition Evaluation

Rule conditions are structured nested boolean trees:
- **Leaf condition**: `{ "field": <StateField>, "op": <Op>, "value": <Any> }`
- **All composite**: `{ "all": [ <Condition>, ... ] }`
- **Any composite**: `{ "any": [ <Condition>, ... ] }`

### Supported Operators (`Op`)
- `EQ` (`==`), `NEQ` (`!=`)
- `LT` (`<`), `LTE` (`<=`)
- `GT` (`>`), `GTE` (`>=`)
- `IN` (`in`), `NIN` (`not in`)
- `IS_TRUE`, `IS_FALSE`, `IS_NULL`, `IS_NOT_NULL`

No `eval()` or `exec()` is ever used. Each leaf evaluates against the current state and payload through strongly typed comparator functions.

---

## 3. Conflict Resolution Formal Definition

When evaluating decision events, all triggered rules whose condition evaluates to `True` are collected into `firing_rules`.

1. **No rules fire**:
   - Default outcome is `DENY` (closed policy model) or flagged as a coverage GAP if unexplained. Default resolution status: `DEFAULT_DENY`.

2. **Only ALLOW or only DENY rules fire**:
   - If all firing rules have `effect == ALLOW`, outcome is `ALLOW` (`RESOLUTION: UNANIMOUS_ALLOW`).
   - If all firing rules have `effect == DENY`, outcome is `DENY` (`RESOLUTION: UNANIMOUS_DENY`).

3. **Both ALLOW and DENY rules fire (Conflict)**:
   - **Step 3.1: Explicit Overrides**:
     - Check if any firing `ALLOW` rule lists a firing `DENY` rule's `id` in its `overrides`.
     - Check if any firing `DENY` rule lists a firing `ALLOW` rule's `id` in its `overrides`.
     - If rule A overrides rule B and rule B does not override rule A:
       - The overridden rule is suppressed.
       - If all opposing rules are overridden, the overriding effect wins (`RESOLUTION: OVERRIDE`).
     - If mutual override exists (A overrides B and B overrides A), it is treated as a `CONTRADICTION`.
   - **Step 3.2: Priority Resolution**:
     - If conflicts remain after explicit overrides, compare `max_allow_priority = max(r.priority for r in active_allow_rules)` and `max_deny_priority = max(r.priority for r in active_deny_rules)`.
     - If `max_allow_priority > max_deny_priority`:
       - Outcome is `ALLOW` (`RESOLUTION: PRIORITY_ALLOW`).
     - If `max_deny_priority > max_allow_priority`:
       - Outcome is `DENY` (`RESOLUTION: PRIORITY_DENY`).
   - **Step 3.3: Equal Priority / Precedence Ties**:
     - If `max_allow_priority == max_deny_priority`:
       - If neither side declared precedence/override, it is flagged as `CONTRADICTION`.
       - If multiple rules on both sides have conflicting claims with equal priority, the result is flagged as `AMBIGUOUS`.
       - For safety in production, ties default to `DENY` with finding `Finding(type=CONTRADICTION | AMBIGUOUS, severity=HIGH, ...)`.

---

## 4. Trace & Finding Artifacts

Every simulation returns a full execution trace:
- `event_index`: Sequence position of event in journey.
- `event`: Event payload and timestamp.
- `rules_evaluated`: List of rule IDs evaluated.
- `rules_fired`: List of rule IDs whose condition passed.
- `leaf_evaluations`: Detailed boolean breakdown for each leaf condition (field, op, expected value, actual state value, result).
- `resolution`: How the outcome was determined (`UNANIMOUS`, `OVERRIDE`, `PRIORITY`, `CONTRADICTION`, `AMBIGUOUS`, `DEFAULT_DENY`).
- `outcome`: `ALLOW` or `DENY`.
- `findings`: Any diagnostic findings generated during this step.
