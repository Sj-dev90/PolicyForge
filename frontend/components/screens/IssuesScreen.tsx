"use client";

/**
 * IssuesScreen — Stage A
 *
 * Left column: list of problems found by run-suite.
 * Right panel: plain-English description → journey timeline → Rule YES/NO →
 *              "Try it" live simulator → Technical details.
 */

import React, {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
} from "react";
import {
  AlertTriangle,
  HelpCircle,
  Info,
  ShieldAlert,
  CheckCircle2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  ShoppingCart,
  Package,
  RotateCcw,
  XCircle,
  PackageCheck,
  CreditCard,
  Minus,
  Plus,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api, DefaultData, SuiteResponse, SimulateResponse } from "@/lib/api";
import {
  eventLabel,
  findingTitle,
  findingOneLiner,
  findingScenarioSentence,
  resolutionBadge,
  stateChips,
  shrinkSummary,
} from "@/lib/translate";
import {
  listContainer,
  listItem,
  panelVariants,
  timelineContainer,
  timelineStep,
  badgeVariants,
} from "@/lib/motion";

interface IssuesScreenProps {
  defaultData: DefaultData | null;
}

// ─── Event icons (Lucide) ─────────────────────────────────────────────────
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  ShoppingCart, Package, RotateCcw, RefreshCw, XCircle,
  PackageCheck, CreditCard, AlertTriangle, CheckCircle2,
};

function EventIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICON_MAP[name] ?? Package;
  return <Icon className={className} />;
}

// ─── Finding icon ─────────────────────────────────────────────────────────
function FindingIcon({ type, className }: { type: string; className?: string }) {
  const icons: Record<string, React.ComponentType<{ className?: string }>> = {
    CONTRADICTION: AlertTriangle,
    POLICY_GAP: HelpCircle,
    AMBIGUITY: Info,
    INVARIANT_VIOLATION: ShieldAlert,
  };
  const Icon = icons[type] ?? AlertTriangle;
  return <Icon className={className} />;
}

// ─── Result badge ─────────────────────────────────────────────────────────
function ResultBadge({ resolution, outcome }: { resolution: string; outcome: string }) {
  const badge = resolutionBadge(resolution, outcome);
  const cls =
    badge.kind === "allow"   ? "bg-allow-bg text-allow border-allow/30" :
    badge.kind === "deny"    ? "bg-deny-bg text-deny border-deny/30" :
    badge.kind === "conflict"? "bg-warning-bg text-warning border-warning/30" :
                               "bg-surface text-muted border-border";
  return (
    <motion.span
      key={badge.label}
      variants={badgeVariants}
      initial="initial"
      animate="animate"
      className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold border ${cls}`}
    >
      {badge.label}
    </motion.span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────
export function IssuesScreen({ defaultData }: IssuesScreenProps) {
  const [suite, setSuite] = useState<SuiteResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState(0);
  const [techOpen, setTechOpen] = useState(false);

  // rulesMap: rule id → rule object for O(1) lookups
  const rulesMap = useMemo(() => {
    const m: Record<string, any> = {};
    for (const r of defaultData?.rules_v1 ?? []) m[r.id] = r;
    return m;
  }, [defaultData]);

  // ── Run suite ────────────────────────────────────────────────────────────
  const runSuite = useCallback(async () => {
    if (!defaultData?.rules_v1 || !defaultData?.sample_journeys) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.runSuite({
        rules: defaultData.rules_v1,
        suite_type: "custom",
        custom_scenarios: defaultData.sample_journeys,
      });
      setSuite(res);
      setSelected(0);
      setTechOpen(false);
    } catch (e: any) {
      setError(e.message ?? "Test run failed.");
    } finally {
      setLoading(false);
    }
  }, [defaultData]);

  useEffect(() => { runSuite(); }, [runSuite]);

  const findings = useMemo(() => suite?.findings ?? [], [suite]);
  const item = findings[selected];
  const finding = item?.finding;
  const shrink = item?.shrink;

  // ── "Try it" state: editable journey + live simulation ──────────────────
  // Start from the minimal journey for the selected finding
  const baseJourney = useMemo(
    () => shrink?.minimal_journey ?? [],
    [shrink]
  );

  const [editJourney, setEditJourney] = useState<Array<{ event_type: string; day: number; payload: any }>>([]);
  const [simResult, setSimResult] = useState<SimulateResponse | null>(null);
  const [simLoading, setSimLoading] = useState(false);

  // Reset editable journey when selection changes
  useEffect(() => {
    setEditJourney(baseJourney.map(e => ({ ...e })));
    setSimResult(null);
  }, [baseJourney, selected]);

  // Debounced simulate on journey edit
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const simulate = useCallback(
    (journey: typeof editJourney) => {
      if (!defaultData?.rules_v1 || journey.length === 0) return;
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(async () => {
        setSimLoading(true);
        try {
          const res = await api.simulate({ rules: defaultData.rules_v1, journey });
          setSimResult(res);
        } catch {
          /* ignore transient errors in try-it */
        } finally {
          setSimLoading(false);
        }
      }, 300);
    },
    [defaultData]
  );

  const updateDay = (idx: number, newDay: number) => {
    const next = editJourney.map((e, i) => i === idx ? { ...e, day: Math.max(0, newDay) } : e);
    setEditJourney(next);
    simulate(next);
  };

  const removeStep = (idx: number) => {
    const next = editJourney.filter((_, i) => i !== idx);
    setEditJourney(next);
    simulate(next);
  };

  // Which event in the edit journey had the conflict/issue?
  const lastDecisionIdx = useMemo(() => {
    if (!simResult) return editJourney.length - 1;
    for (let i = simResult.outcomes.length - 1; i >= 0; i--) {
      if (simResult.outcomes[i].action_applied || simResult.outcomes[i].resolution_type !== "NON_DECISION") {
        return i;
      }
    }
    return editJourney.length - 1;
  }, [simResult, editJourney]);

  // State at a given step index
  const [activeStepIdx, setActiveStepIdx] = useState<number | null>(null);

  const stateAtStep = useMemo(() => {
    if (activeStepIdx == null || !simResult) return null;
    // final_state is the state after the whole run; for per-step, use final_state only for last
    // For non-last steps we parse chips from the trace explanation or just show final_state
    // (The API doesn't expose per-step state, so we show final_state with a note)
    return simResult.final_state;
  }, [activeStepIdx, simResult]);

  // Active step shown in timeline — the failing one by default
  useEffect(() => {
    setActiveStepIdx(null);
  }, [selected]);

  // Last decision in the BASE (shrink) timeline for highlight
  const failingStepInBase = useMemo(() => {
    if (!shrink) return -1;
    const j = shrink.minimal_journey;
    for (let i = j.length - 1; i >= 0; i--) {
      if (finding?.event_indices?.includes(i)) return i;
    }
    return j.length - 1;
  }, [shrink, finding]);

  // ── Rendering ────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">

      {/* ── Headline ──────────────────────────────────────────────────── */}
      <div className="bg-surface rounded-xl border border-border p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-card">
        <div>
          {loading ? (
            <div className="space-y-2 animate-pulse">
              <div className="h-7 w-72 bg-border rounded" />
              <div className="h-5 w-48 bg-border rounded" />
            </div>
          ) : error ? (
            <p className="text-deny text-base font-medium">{error}</p>
          ) : (
            <>
              <h1 className="text-2xl font-bold text-text leading-tight">
                {findings.length === 0
                  ? "No problems found in NovaCart's refund policy"
                  : `We found ${findings.length} problem${findings.length > 1 ? "s" : ""} in NovaCart's refund policy`}
              </h1>
              <p className="text-muted text-base mt-1">
                Tested on {suite?.total_scenarios ?? 0} customer journeys
              </p>
            </>
          )}
        </div>

        <button
          onClick={runSuite}
          disabled={loading}
          className="flex-shrink-0 flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Re-run test
        </button>
      </div>

      {/* ── Two-column layout ──────────────────────────────────────────── */}
      {!loading && !error && (
        <div className="flex gap-6 items-start">

          {/* ── Left: problem list (320px fixed) ──────────────────────── */}
          <div className="w-80 flex-shrink-0 space-y-2">
            {findings.length === 0 ? (
              <EmptyState />
            ) : (
              <motion.ul
                variants={listContainer}
                initial="initial"
                animate="animate"
                className="space-y-2"
                role="listbox"
                aria-label="Problems"
              >
                {findings.map((item, idx) => {
                  const f = item.finding;
                  const active = selected === idx;
                  return (
                    <motion.li
                      key={idx}
                      variants={listItem}
                      role="option"
                      aria-selected={active}
                    >
                      <button
                        onClick={() => { setSelected(idx); setTechOpen(false); }}
                        className={`
                          w-full text-left px-4 py-3 rounded-xl border transition-all duration-150
                          focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary
                          hover:-translate-y-px
                          ${active
                            ? "bg-surface border-primary shadow-card"
                            : "bg-surface border-border hover:border-primary/40"
                          }
                        `}
                      >
                        <div className="flex items-center gap-2.5 mb-1">
                          <FindingIcon
                            type={f.type}
                            className={`w-4 h-4 flex-shrink-0 ${
                              f.type === "CONTRADICTION" ? "text-deny" :
                              f.type === "POLICY_GAP"    ? "text-warning" :
                              "text-muted"
                            }`}
                          />
                          <span className="font-semibold text-sm text-text">
                            {findingTitle(f.type)}
                          </span>
                          <span className={`
                            ml-auto text-xs font-medium px-2 py-0.5 rounded-full border
                            ${f.severity === "HIGH" || f.severity === "CRITICAL"
                              ? "text-deny bg-deny-bg border-deny/30"
                              : "text-warning bg-warning-bg border-warning/30"
                            }
                          `}>
                            {f.severity === "HIGH" ? "High" : f.severity === "CRITICAL" ? "Critical" : "Medium"}
                          </span>
                        </div>
                        <p className="text-sm text-muted leading-snug line-clamp-2">
                          {findingOneLiner(f, rulesMap)}
                        </p>
                      </button>
                    </motion.li>
                  );
                })}
              </motion.ul>
            )}
          </div>

          {/* ── Right: detail panel ───────────────────────────────────── */}
          <div className="flex-1 min-w-0">
            <AnimatePresence mode="wait">
              {finding ? (
                <motion.div
                  key={selected}
                  variants={panelVariants}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="space-y-5"
                >
                  {/* a) Plain-English scenario sentence */}
                  <div className="bg-surface rounded-xl border border-border p-5 shadow-card">
                    <p className="text-base text-text leading-relaxed">
                      {findingScenarioSentence(finding, rulesMap)}
                    </p>
                    {shrink && (
                      <p className="text-sm text-muted mt-2">
                        {shrinkSummary(shrink)}
                      </p>
                    )}
                  </div>

                  {/* b) Journey timeline (uses minimal/shrunk journey) */}
                  {shrink && (
                    <div className="bg-surface rounded-xl border border-border p-5 shadow-card">
                      <h2 className="text-sm font-semibold text-muted mb-4 uppercase tracking-wide">
                        Customer journey
                      </h2>
                      <div className="overflow-x-auto pb-2">
                        <motion.div
                          variants={timelineContainer}
                          initial="initial"
                          animate="animate"
                          className="flex items-start gap-2 min-w-max"
                        >
                          {shrink.minimal_journey.map((ev, idx) => {
                            const isFailing = idx === failingStepInBase || idx === shrink.minimal_journey.length - 1;
                            const isActive = activeStepIdx === idx;
                            return (
                              <React.Fragment key={idx}>
                                <motion.button
                                  variants={timelineStep}
                                  onClick={() => setActiveStepIdx(isActive ? null : idx)}
                                  className={`
                                    flex flex-col items-center gap-1.5 px-3 py-2.5 rounded-xl border
                                    min-w-[100px] text-center transition-all duration-150
                                    focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary
                                    ${isFailing
                                      ? `bg-deny-bg border-deny/60 ${isActive ? "" : "step-fail-pulse"}`
                                      : isActive
                                        ? "bg-primary/10 border-primary"
                                        : "bg-bg border-border hover:border-primary/40"
                                    }
                                  `}
                                >
                                  <span className={`text-xs font-mono ${isFailing ? "text-deny" : "text-muted"}`}>
                                    Day {ev.day}
                                  </span>
                                  <span className={`text-xs font-medium leading-tight ${isFailing ? "text-deny" : "text-text"}`}>
                                    {eventLabel(ev.event_type)}
                                  </span>
                                </motion.button>
                                {idx < shrink.minimal_journey.length - 1 && (
                                  <ArrowRight className="w-4 h-4 text-muted self-center flex-shrink-0" />
                                )}
                              </React.Fragment>
                            );
                          })}
                        </motion.div>
                      </div>

                      {/* State chips on step click (shows final_state) */}
                      <AnimatePresence>
                        {activeStepIdx !== null && simResult && (
                          <motion.div
                            initial={{ opacity: 0, height: 0 }}
                            animate={{ opacity: 1, height: "auto" }}
                            exit={{ opacity: 0, height: 0 }}
                            transition={{ duration: 0.18 }}
                            className="mt-4 pt-4 border-t border-border"
                          >
                            <p className="text-xs text-muted mb-2">State at this point:</p>
                            <div className="flex flex-wrap gap-2">
                              {stateChips(simResult.final_state).length === 0 ? (
                                <span className="text-xs text-muted">No notable state changes.</span>
                              ) : (
                                stateChips(simResult.final_state).map(chip => (
                                  <span
                                    key={chip}
                                    className="text-xs px-2.5 py-1 rounded-full bg-bg border border-border text-text"
                                  >
                                    {chip}
                                  </span>
                                ))
                              )}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  )}

                  {/* c) Rule YES / Rule NO cards */}
                  {finding.type === "CONTRADICTION" && finding.rule_ids && finding.rule_ids.length >= 2 && (
                    <div>
                      <h2 className="text-sm font-semibold text-muted mb-3 uppercase tracking-wide px-1">
                        Why they disagree
                      </h2>
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        {/* ALLOW rule */}
                        {(() => {
                          const allowId = finding.details?.allow_rules?.[0] ?? finding.rule_ids[0];
                          const rule = rulesMap[allowId];
                          return (
                            <RuleCard
                              label="Rule says YES"
                              effect="allow"
                              name={rule?.name ?? allowId}
                              sentence={rule?.source?.verbatim_sentence}
                              ruleId={allowId}
                            />
                          );
                        })()}
                        {/* DENY rule */}
                        {(() => {
                          const denyId = finding.details?.deny_rules?.[0] ?? finding.rule_ids[1];
                          const rule = rulesMap[denyId];
                          return (
                            <RuleCard
                              label="Rule says NO"
                              effect="deny"
                              name={rule?.name ?? denyId}
                              sentence={rule?.source?.verbatim_sentence}
                              ruleId={denyId}
                            />
                          );
                        })()}
                      </div>
                    </div>
                  )}

                  {/* Policy gap: no rule at all */}
                  {finding.type === "POLICY_GAP" && (
                    <div>
                      <h2 className="text-sm font-semibold text-muted mb-3 uppercase tracking-wide px-1">
                        What's missing
                      </h2>
                      <div className="bg-warning-bg border border-warning/40 rounded-xl p-5">
                        <p className="text-base text-warning font-medium">
                          No policy clause covers this event
                        </p>
                        <p className="text-sm text-muted mt-2">
                          The policy needs a rule that explicitly says what should happen when a customer submits{" "}
                          <strong className="text-text">{eventLabel(finding.details?.event_type ?? "")}</strong>{" "}
                          in this order state.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* d) "Try it" controls */}
                  {editJourney.length > 0 && (
                    <TryItPanel
                      journey={editJourney}
                      simResult={simResult}
                      simLoading={simLoading}
                      lastDecisionIdx={lastDecisionIdx}
                      onUpdateDay={updateDay}
                      onRemoveStep={removeStep}
                    />
                  )}

                  {/* e) Technical details accordion */}
                  <div className="bg-surface rounded-xl border border-border overflow-hidden shadow-card">
                    <button
                      onClick={() => setTechOpen(o => !o)}
                      className="w-full flex items-center justify-between px-5 py-4 text-sm font-medium text-muted hover:text-text hover:bg-bg/50 transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                    >
                      Technical details
                      {techOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                    </button>
                    <AnimatePresence>
                      {techOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2 }}
                          className="overflow-hidden"
                        >
                          <div className="border-t border-border px-5 py-4 space-y-4">
                            <div>
                              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Finding type</p>
                              <code className="text-sm font-mono text-text">{finding.type}</code>
                            </div>
                            {finding.rule_ids && finding.rule_ids.length > 0 && (
                              <div>
                                <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Rule IDs</p>
                                <div className="flex flex-wrap gap-2">
                                  {finding.rule_ids.map(id => (
                                    <code key={id} className="text-xs font-mono px-2 py-1 bg-bg border border-border rounded text-primary">
                                      {id}
                                    </code>
                                  ))}
                                </div>
                              </div>
                            )}
                            <div>
                              <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Engine trace</p>
                              <pre className="text-xs font-mono text-muted bg-bg border border-border rounded-lg p-3 whitespace-pre-wrap leading-relaxed">
                                {finding.trace}
                              </pre>
                            </div>
                            {simResult?.final_state && (
                              <div>
                                <p className="text-xs font-semibold text-muted uppercase tracking-wide mb-2">Final state</p>
                                <pre className="text-xs font-mono text-muted bg-bg border border-border rounded-lg p-3 whitespace-pre-wrap leading-relaxed max-h-40 overflow-y-auto">
                                  {JSON.stringify(simResult.final_state, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>

                </motion.div>
              ) : (
                findings.length === 0 ? null : (
                  <div className="bg-surface rounded-xl border border-border p-12 text-center text-muted">
                    Select a problem on the left to inspect it.
                  </div>
                )
              )}
            </AnimatePresence>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Rule card (YES / NO) ─────────────────────────────────────────────────
function RuleCard({
  label, effect, name, sentence, ruleId,
}: {
  label: string;
  effect: "allow" | "deny";
  name: string;
  sentence?: string;
  ruleId: string;
}) {
  const bg   = effect === "allow" ? "bg-allow-bg border-allow/40" : "bg-deny-bg border-deny/40";
  const head = effect === "allow" ? "text-allow" : "text-deny";

  return (
    <div className={`rounded-xl border p-5 space-y-3 ${bg}`}>
      <div className="flex items-center justify-between">
        <span className={`text-sm font-bold uppercase tracking-wide ${head}`}>{label}</span>
      </div>
      <p className="text-base font-semibold text-text leading-snug">{name}</p>
      {sentence && (
        <blockquote className="border-l-2 border-current pl-3 text-sm text-muted italic leading-relaxed">
          &ldquo;{sentence}&rdquo;
        </blockquote>
      )}
    </div>
  );
}

// ─── "Try it" panel ───────────────────────────────────────────────────────
function TryItPanel({
  journey,
  simResult,
  simLoading,
  lastDecisionIdx,
  onUpdateDay,
  onRemoveStep,
}: {
  journey: Array<{ event_type: string; day: number; payload: any }>;
  simResult: SimulateResponse | null;
  simLoading: boolean;
  lastDecisionIdx: number;
  onUpdateDay: (idx: number, day: number) => void;
  onRemoveStep: (idx: number) => void;
}) {
  const lastOutcome = simResult?.outcomes?.[lastDecisionIdx] ?? simResult?.outcomes?.at(-1);

  return (
    <div className="bg-surface rounded-xl border border-border p-5 shadow-card space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-muted uppercase tracking-wide">Try it</h2>
        <p className="text-xs text-muted">Edit the journey — result updates instantly</p>
      </div>

      {/* Editable steps */}
      <div className="space-y-2">
        {journey.map((ev, idx) => {
          const isLast = idx === journey.length - 1;
          return (
            <div
              key={idx}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border ${
                isLast ? "bg-deny-bg border-deny/40" : "bg-bg border-border"
              }`}
            >
              <span className="text-sm text-text flex-1 min-w-0 truncate">
                {eventLabel(ev.event_type)}
              </span>

              {/* Day stepper */}
              <div className="flex items-center gap-1">
                <button
                  onClick={() => onUpdateDay(idx, ev.day - 1)}
                  className="w-7 h-7 flex items-center justify-center rounded border border-border bg-surface hover:bg-bg text-muted hover:text-text transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                  aria-label="Decrease day"
                >
                  <Minus className="w-3 h-3" />
                </button>
                <span className="text-sm font-mono text-text w-14 text-center">
                  Day {ev.day}
                </span>
                <button
                  onClick={() => onUpdateDay(idx, ev.day + 1)}
                  className="w-7 h-7 flex items-center justify-center rounded border border-border bg-surface hover:bg-bg text-muted hover:text-text transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
                  aria-label="Increase day"
                >
                  <Plus className="w-3 h-3" />
                </button>
              </div>

              {/* Remove */}
              {journey.length > 1 && (
                <button
                  onClick={() => onRemoveStep(idx)}
                  className="text-muted hover:text-deny transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary rounded"
                  aria-label={`Remove ${eventLabel(ev.event_type)}`}
                >
                  <XCircle className="w-4 h-4" />
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Live result badge */}
      <div className="flex items-center gap-3 pt-2 border-t border-border">
        <span className="text-sm text-muted">Result:</span>
        {simLoading ? (
          <span className="text-sm text-muted animate-pulse">Simulating…</span>
        ) : lastOutcome ? (
          <ResultBadge
            resolution={lastOutcome.resolution_type}
            outcome={lastOutcome.outcome}
          />
        ) : (
          <span className="text-sm text-muted">Run the simulation first</span>
        )}
      </div>
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────
function EmptyState() {
  return (
    <div className="bg-surface rounded-xl border border-border p-8 text-center space-y-3 shadow-card">
      <CheckCircle2 className="w-8 h-8 text-allow mx-auto" />
      <h3 className="text-base font-semibold text-text">No problems found</h3>
      <p className="text-sm text-muted leading-relaxed">
        NovaCart's refund policy is consistent across all tested journeys.
      </p>
    </div>
  );
}
