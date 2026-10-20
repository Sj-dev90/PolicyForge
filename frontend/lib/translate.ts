/**
 * lib/translate.ts
 *
 * ALL plain-English mappings live here. Nothing from this file
 * should ever expose raw enum names, JSON, or technical jargon in the UI.
 * Raw values are only surfaced inside a "Technical details" section.
 */

// ─── Event types → friendly names ────────────────────────────────────────
export const EVENT_LABELS: Record<string, { label: string; icon: string }> = {
  ORDER_PLACED:            { label: "Order placed",             icon: "ShoppingCart" },
  ITEM_DELIVERED:          { label: "Item delivered",           icon: "Package" },
  REFUND_REQUESTED:        { label: "Refund requested",         icon: "RotateCcw" },
  REFUND_COMPLETED:        { label: "Refund completed",         icon: "CheckCircle" },
  REPLACEMENT_REQUESTED:   { label: "Replacement requested",    icon: "RefreshCw" },
  REPLACEMENT_CANCELLED:   { label: "Replacement cancelled",    icon: "XCircle" },
  REPLACEMENT_DELIVERED:   { label: "Replacement delivered",    icon: "Package" },
  ITEM_DAMAGED_REPORTED:   { label: "Damage reported",          icon: "AlertTriangle" },
  RETURN_RECEIVED:         { label: "Return received",          icon: "PackageCheck" },
  CHARGEBACK_FILED:        { label: "Chargeback filed",         icon: "CreditCard" },
  CHARGEBACK_RESOLVED:     { label: "Chargeback resolved",      icon: "CheckCircle" },
  ORDER_CANCELLED:         { label: "Order cancelled",          icon: "XCircle" },
};

export function eventLabel(raw: string): string {
  return EVENT_LABELS[raw]?.label ?? raw.replace(/_/g, " ").toLowerCase();
}

// ─── Finding types → friendly titles + one-line explanations ─────────────
export type FindingKind = "CONTRADICTION" | "POLICY_GAP" | "AMBIGUITY" | "INVARIANT_VIOLATION";

export const FINDING_TITLES: Record<string, string> = {
  CONTRADICTION:       "Rules disagree",
  POLICY_GAP:          "Missing rule",
  AMBIGUITY:           "Unclear priority",
  INVARIANT_VIOLATION: "Business rule broken",
};

export const FINDING_ICONS: Record<string, string> = {
  CONTRADICTION:       "AlertTriangle",
  POLICY_GAP:          "HelpCircle",
  AMBIGUITY:           "Info",
  INVARIANT_VIOLATION: "ShieldAlert",
};

export function findingTitle(raw: string): string {
  return FINDING_TITLES[raw] ?? raw.replace(/_/g, " ").toLowerCase();
}

// ─── One-line card explanations ───────────────────────────────────────────
export function findingOneLiner(finding: {
  type: string;
  rule_ids?: string[];
  details?: Record<string, any>;
  trace?: string;
}, rules?: Record<string, any>): string {
  switch (finding.type) {
    case "CONTRADICTION": {
      const r1 = rules?.[finding.rule_ids?.[0] ?? ""]?.name ?? "one rule";
      const r2 = rules?.[finding.rule_ids?.[1] ?? ""]?.name ?? "another rule";
      return `"${r1}" approves the request while "${r2}" rejects it — with no tiebreaker.`;
    }
    case "POLICY_GAP": {
      const ev = eventLabel(finding.details?.event_type ?? "");
      return `No policy clause covers "${ev}" in this situation, so the system silently denies it.`;
    }
    case "AMBIGUITY":
      return "Multiple rules match but none has higher priority, so the outcome is unpredictable.";
    case "INVARIANT_VIOLATION":
      return "The customer journey violated a hard business constraint.";
    default:
      return finding.trace?.split(".")[0] ?? "A policy anomaly was detected.";
  }
}

// ─── Right-panel "What happened?" sentence ────────────────────────────────
export function findingScenarioSentence(finding: {
  type: string;
  rule_ids?: string[];
  details?: Record<string, any>;
  trace?: string;
}, rules?: Record<string, any>): string {
  switch (finding.type) {
    case "CONTRADICTION": {
      const r1 = rules?.[finding.rule_ids?.[0] ?? ""]?.name ?? "one rule";
      const r2 = rules?.[finding.rule_ids?.[1] ?? ""]?.name ?? "another rule";
      return `A customer requested a refund after cancelling a replacement. The policy has two rules that disagree: "${r1}" says the refund should be approved, but "${r2}" says it should be rejected — and neither rule overrides the other, leaving the customer in limbo.`;
    }
    case "POLICY_GAP": {
      const ev = eventLabel(finding.details?.event_type ?? "");
      return `A customer submitted a "${ev}" but the policy doesn't have any rule that covers this case. The system falls back to a silent denial because nothing explicitly allows it.`;
    }
    case "AMBIGUITY":
      return "Multiple rules in the policy match the customer's situation and all have equal priority, so the system cannot reliably decide the outcome.";
    case "INVARIANT_VIOLATION":
      return "The customer's journey put the system into an invalid state that violates a core business constraint.";
    default:
      return finding.trace ?? "An unexpected policy conflict occurred.";
  }
}

// ─── Resolution type → result badge label ────────────────────────────────
export function resolutionBadge(resolution: string, outcome: string): {
  label: string;
  kind: "allow" | "deny" | "conflict" | "neutral";
} {
  if (resolution === "CONTRADICTION") return { label: "Conflict — no decision", kind: "conflict" };
  if (outcome === "ALLOW") {
    if (resolution === "UNANIMOUS_ALLOW" || resolution === "DEFAULT_ALLOW") return { label: "Refund approved", kind: "allow" };
    if (resolution === "OVERRIDE_ALLOW") return { label: "Override: refund approved", kind: "allow" };
    if (resolution === "PRIORITY_ALLOW") return { label: "Higher-priority rule: approved", kind: "allow" };
    return { label: "Approved", kind: "allow" };
  }
  if (outcome === "DENY") {
    if (resolution === "UNANIMOUS_DENY" || resolution === "DEFAULT_DENY") return { label: "Refund denied", kind: "deny" };
    if (resolution === "OVERRIDE_DENY") return { label: "Override: refund denied", kind: "deny" };
    if (resolution === "PRIORITY_DENY") return { label: "Higher-priority rule: denied", kind: "deny" };
    if (resolution === "NO_RULES_FIRED") return { label: "No rule — denied by default", kind: "deny" };
    return { label: "Denied", kind: "deny" };
  }
  return { label: resolution.replace(/_/g, " ").toLowerCase(), kind: "neutral" };
}

// ─── State field → friendly chip label ───────────────────────────────────
export const STATE_CHIPS: Array<{ key: string; label: string }> = [
  { key: "item_delivered",         label: "Item delivered" },
  { key: "replacement_requested",  label: "Replacement requested" },
  { key: "replacement_cancelled",  label: "Replacement cancelled" },
  { key: "replacement_active",     label: "Replacement active" },
  { key: "replacement_completed",  label: "Replacement completed" },
  { key: "refund_requested",       label: "Refund requested" },
  { key: "refund_completed",       label: "Refund completed" },
  { key: "return_received",        label: "Return received" },
  { key: "item_damaged",           label: "Item damaged" },
  { key: "is_final_sale",          label: "Final sale item" },
  { key: "item_opened",            label: "Item opened" },
  { key: "chargeback_active",      label: "Chargeback active" },
  { key: "action_denied",          label: "Last action denied" },
  { key: "order_placed",           label: "Order placed" },
  { key: "refund_eligibility_restored", label: "Refund eligibility restored" },
];

export function stateChips(state: Record<string, any>): string[] {
  const chips: string[] = [];
  for (const { key, label } of STATE_CHIPS) {
    if (state[key] === true) chips.push(label);
  }
  if (state.customer_tier && state.customer_tier !== "STANDARD") {
    chips.push(`${state.customer_tier} customer`);
  }
  if (state.days_since_delivery != null && state.item_delivered) {
    chips.push(`Day ${state.days_since_delivery} since delivery`);
  }
  return chips;
}

// ─── Shrink summary sentence ──────────────────────────────────────────────
export function shrinkSummary(shrink: {
  original_length: number;
  minimal_length: number;
  minimal_journey: Array<{ day: number }>;
}): string {
  const { original_length, minimal_length, minimal_journey } = shrink;
  if (original_length === minimal_length) return "Already the minimal failing journey.";
  const failDay = minimal_journey.at(-1)?.day;
  const reduced = `Reduced from ${original_length} steps to ${minimal_length} steps.`;
  if (failDay != null && failDay > 0) {
    return `${reduced} Fails from day ${failDay} onward.`;
  }
  return reduced;
}
