"use client";

import React, { useState, useEffect, useMemo } from "react";
import {
  AlertTriangle,
  HelpCircle,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Layers,
  FlaskConical,
  ArrowRight,
  Sparkles,
  Info,
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api, DefaultData, SimulateResponse, SuiteResponse } from "@/lib/api";
import {
  translateResolution,
  translateFindingType,
  translateEventType,
  getFindingOneLineSummary,
  getWhatWentWrong,
} from "@/lib/translate";
import {
  staggerListContainerVariants,
  staggerItemVariants,
  timelineContainerVariants,
  timelineItemVariants,
  panelCrossFadeVariants,
  useCountUp,
} from "@/lib/motion";

interface DashboardProps {
  defaultData: DefaultData | null;
  onNavigate: (tab: string) => void;
}

export function Dashboard({ defaultData, onNavigate }: DashboardProps) {
  const [suiteResult, setSuiteResult] = useState<SuiteResponse | null>(null);
  const [engineTimeMs, setEngineTimeMs] = useState<number | null>(null);
  const [loadingSuite, setLoadingSuite] = useState<boolean>(true);
  const [selectedFindingIndex, setSelectedFindingIndex] = useState<number>(0);
  const [selectedJourneyId, setSelectedJourneyId] = useState<string>("canonical_contradiction");
  const [simResult, setSimResult] = useState<SimulateResponse | null>(null);
  const [simLoading, setSimLoading] = useState<boolean>(false);
  const [traceOpen, setTraceOpen] = useState<boolean>(false);

  // Index rules by ID for instant O(1) lookup
  const rulesMap = useMemo(() => {
    const map: Record<string, any> = {};
    if (defaultData?.rules_v1) {
      for (const r of defaultData.rules_v1) {
        map[r.id] = r;
      }
    }
    return map;
  }, [defaultData]);

  // Execute suite verification against sample scenarios to compute verdict header & stats from real data
  useEffect(() => {
    if (!defaultData?.rules_v1 || !defaultData?.sample_journeys) return;

    let isMounted = true;
    const runSuiteTest = async () => {
      setLoadingSuite(true);
      const start = performance.now();
      try {
        const res = await api.runSuite({
          rules: defaultData.rules_v1,
          suite_type: "custom",
          custom_scenarios: defaultData.sample_journeys,
        });
        const elapsed = Math.max(0.2, Number((performance.now() - start).toFixed(2)));
        if (isMounted) {
          setSuiteResult(res);
          setEngineTimeMs(elapsed);
        }
      } catch (err) {
        console.error("Suite verification error:", err);
      } finally {
        if (isMounted) setLoadingSuite(false);
      }
    };

    runSuiteTest();
    return () => {
      isMounted = false;
    };
  }, [defaultData]);

  // Execute single simulation when a journey is picked via "Try a journey"
  useEffect(() => {
    if (!defaultData?.rules_v1 || !defaultData?.sample_journeys) return;
    const currentJourney = defaultData.sample_journeys.find((j) => j.id === selectedJourneyId);
    if (!currentJourney) return;

    let isMounted = true;
    const runSingle = async () => {
      setSimLoading(true);
      try {
        const res = await api.simulate({
          rules: defaultData.rules_v1,
          journey: currentJourney.journey,
        });
        if (isMounted) setSimResult(res);
      } catch (err) {
        console.error("Simulation error:", err);
      } finally {
        if (isMounted) setSimLoading(false);
      }
    };

    runSingle();
    return () => {
      isMounted = false;
    };
  }, [selectedJourneyId, defaultData]);

  const findingsList = useMemo(() => suiteResult?.findings || [], [suiteResult]);
  const selectedFindingWrapper = findingsList[selectedFindingIndex] || null;
  const selectedFinding = selectedFindingWrapper?.finding || null;
  const selectedShrink = selectedFindingWrapper?.shrink || null;

  // Breakdown counts by finding type computed dynamically from real API data
  const countsByType = useMemo(() => {
    const counts = {
      contradictions: 0,
      gaps: 0,
      invariants: 0,
      ambiguities: 0,
    };
    for (const f of findingsList) {
      const type = f.finding.type;
      if (type === "CONTRADICTION") counts.contradictions++;
      else if (type === "POLICY_GAP") counts.gaps++;
      else if (type === "INVARIANT_VIOLATION") counts.invariants++;
      else if (type === "AMBIGUITY") counts.ambiguities++;
    }
    return counts;
  }, [findingsList]);

  // Animated Count-Up values for stats (max 500ms)
  const animatedIssues = useCountUp(findingsList.length);
  const animatedContradictions = useCountUp(countsByType.contradictions);
  const animatedGaps = useCountUp(countsByType.gaps);
  const animatedInvariants = useCountUp(countsByType.invariants);
  const animatedAmbiguities = useCountUp(countsByType.ambiguities);
  const animatedRulesCount = useCountUp(defaultData?.rules_v1?.length || 0);
  const animatedScenariosCount = useCountUp(suiteResult?.total_scenarios || 0);

  // If a user selects a sample scenario, check if it maps to any finding
  const handleJourneyChange = (journeyId: string) => {
    setSelectedJourneyId(journeyId);
    if (journeyId === "canonical_contradiction") {
      const idx = findingsList.findIndex((f) => f.finding.type === "CONTRADICTION");
      if (idx !== -1) setSelectedFindingIndex(idx);
    } else if (journeyId === "policy_gap_pre_delivery") {
      const idx = findingsList.findIndex((f) => f.finding.type === "POLICY_GAP");
      if (idx !== -1) setSelectedFindingIndex(idx);
    }
  };

  return (
    <div className="space-y-6">
      {/* 2. Verdict Header */}
      <section className="bg-surface rounded-xl border border-border p-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight text-text">
                {findingsList.length === 0 ? (
                  <span className="flex items-center gap-2 text-success">
                    <ShieldCheck className="w-5 h-5 text-success" />
                    No issues found in NovaCart v1
                  </span>
                ) : (
                  <span>
                    <span className="text-danger font-bold">{animatedIssues}</span>{" "}
                    {findingsList.length === 1 ? "issue" : "issues"} found in NovaCart v1
                  </span>
                )}
              </h1>
            </div>

            {/* Chips for counts by type */}
            <div className="flex flex-wrap items-center gap-2 mt-2.5">
              {countsByType.contradictions > 0 && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-danger/10 text-danger border border-danger/30">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  <span>{animatedContradictions} contradiction{countsByType.contradictions > 1 ? "s" : ""}</span>
                </span>
              )}

              {countsByType.gaps > 0 && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-warning/10 text-warning border border-warning/30">
                  <HelpCircle className="w-3.5 h-3.5" />
                  <span>{animatedGaps} gap{countsByType.gaps > 1 ? "s" : ""}</span>
                </span>
              )}

              {countsByType.invariants > 0 && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-danger/10 text-danger border border-danger/30">
                  <ShieldAlert className="w-3.5 h-3.5" />
                  <span>{animatedInvariants} invariant violation{countsByType.invariants > 1 ? "s" : ""}</span>
                </span>
              )}

              {countsByType.ambiguities > 0 && (
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-md text-xs font-medium bg-info/10 text-info border border-info/30">
                  <Info className="w-3.5 h-3.5" />
                  <span>{animatedAmbiguities} ambiguit{countsByType.ambiguities > 1 ? "ies" : "y"}</span>
                </span>
              )}

              {findingsList.length === 0 && (
                <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-md text-xs font-medium bg-success/10 text-success border border-success/30">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  All policy journeys fully covered and consistent
                </span>
              )}
            </div>
          </div>

          {/* Quiet Stats: Rules, Scenarios tested, Engine time (All from real API) */}
          <div className="flex items-center gap-6 border-t md:border-t-0 md:border-l border-border pt-3 md:pt-0 md:pl-6 text-xs text-muted">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted font-medium flex items-center gap-1">
                <Layers className="w-3 h-3 text-primary" />
                Rules
              </div>
              <div className="text-base font-semibold text-text mt-0.5">
                {animatedRulesCount}
              </div>
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted font-medium flex items-center gap-1">
                <FlaskConical className="w-3 h-3 text-info" />
                Scenarios
              </div>
              <div className="text-base font-semibold text-text mt-0.5">
                {animatedScenariosCount}
              </div>
            </div>

            <div>
              <div className="text-[11px] uppercase tracking-wider text-muted font-medium flex items-center gap-1">
                <Clock className="w-3 h-3 text-success" />
                Engine time
              </div>
              <div className="text-base font-semibold text-success mt-0.5 font-mono">
                {engineTimeMs !== null ? `${engineTimeMs} ms` : "..."}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 3. Main Area: Two columns (Narrow Left, Wide Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT COLUMN: List of findings as compact cards */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs uppercase tracking-wider font-semibold text-muted">
              Detected Findings ({findingsList.length})
            </span>
            <span className="text-[11px] text-muted">Click to inspect</span>
          </div>

          {loadingSuite ? (
            <div className="space-y-2">
              <div className="h-20 bg-surface rounded-xl border border-border animate-pulse" />
              <div className="h-20 bg-surface rounded-xl border border-border animate-pulse" />
            </div>
          ) : findingsList.length === 0 ? (
            <div className="p-6 rounded-xl bg-surface border border-border text-center space-y-2">
              <CheckCircle2 className="w-8 h-8 text-success mx-auto" />
              <h3 className="text-sm font-semibold text-text">No issues found</h3>
              <p className="text-xs text-muted">
                NovaCart v1 policy rules evaluated clean across all journeys.
              </p>
            </div>
          ) : (
            <motion.div
              variants={staggerListContainerVariants}
              initial="initial"
              animate="animate"
              className="space-y-2"
            >
              {findingsList.map((item, idx) => {
                const finding = item.finding;
                const isSelected = selectedFindingIndex === idx;
                const isContradiction = finding.type === "CONTRADICTION";
                const isGap = finding.type === "POLICY_GAP";
                const isInvariant = finding.type === "INVARIANT_VIOLATION";

                const summaryText = getFindingOneLineSummary(finding);

                return (
                  <motion.button
                    key={idx}
                    variants={staggerItemVariants}
                    onClick={() => setSelectedFindingIndex(idx)}
                    className={`w-full text-left p-3.5 rounded-xl border transition-all duration-150 relative focus-visible:ring-1 focus-visible:ring-primary ${
                      isSelected
                        ? "bg-raised border-primary shadow-subtle -translate-y-0.5"
                        : "bg-surface border-border hover:bg-raised/70 hover:border-border hover:-translate-y-0.5"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        {isContradiction ? (
                          <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0" />
                        ) : isGap ? (
                          <HelpCircle className="w-4 h-4 text-warning flex-shrink-0" />
                        ) : (
                          <ShieldAlert className="w-4 h-4 text-danger flex-shrink-0" />
                        )}
                        <span className="text-xs font-semibold text-text">
                          {translateFindingType(finding.type)}
                        </span>
                      </div>

                      <span
                        className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${
                          finding.severity === "HIGH" || finding.severity === "CRITICAL"
                            ? "bg-danger/10 text-danger border border-danger/30"
                            : "bg-warning/10 text-warning border border-warning/30"
                        }`}
                      >
                        {finding.severity}
                      </span>
                    </div>

                    <p className="text-xs text-muted mt-2 line-clamp-2 leading-relaxed">
                      {summaryText}
                    </p>

                    {finding.rule_ids && finding.rule_ids.length > 0 && (
                      <div className="mt-2.5 flex flex-wrap gap-1">
                        {finding.rule_ids.map((rid) => (
                          <span
                            key={rid}
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg text-muted border border-border"
                          >
                            {rid}
                          </span>
                        ))}
                      </div>
                    )}
                  </motion.button>
                );
              })}
            </motion.div>
          )}
        </div>

        {/* RIGHT COLUMN: Detail Panel for selected finding */}
        <div className="lg:col-span-8 space-y-4">
          {/* 4. "Try a journey" dropdown control above the right panel */}
          <div className="bg-surface rounded-xl border border-border p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-text">Try a journey:</span>
              <span className="text-[11px] text-muted hidden sm:inline">
                Evaluate against sample scenarios
              </span>
            </div>

            <div className="relative">
              <select
                value={selectedJourneyId}
                onChange={(e) => handleJourneyChange(e.target.value)}
                className="w-full sm:w-auto bg-raised border border-border rounded-lg text-xs font-medium text-text px-3 py-1.5 pr-8 focus-visible:ring-1 focus-visible:ring-primary appearance-none cursor-pointer"
              >
                {(defaultData?.sample_journeys || []).map((j) => (
                  <option key={j.id} value={j.id} className="bg-raised text-text">
                    {j.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3.5 h-3.5 text-muted absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
            </div>
          </div>

          {/* Finding Detail Panel */}
          {selectedFinding ? (
            <AnimatePresence mode="wait">
              <motion.div
                key={selectedFindingIndex}
                variants={panelCrossFadeVariants}
                initial="initial"
                animate="animate"
                exit="exit"
                className="space-y-4"
              >
                {/* a) "What went wrong" (plain language, 2 sentences max) */}
                <div className="bg-surface rounded-xl border border-border p-5">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                      What went wrong
                    </span>
                  </div>
                  <p className="text-sm text-text leading-relaxed font-normal">
                    {getWhatWentWrong(selectedFinding, rulesMap)}
                  </p>
                </div>

                {/* b) Conflicting rules side by side (Allow = success, Deny = danger) */}
                <div className="bg-surface rounded-xl border border-border p-5 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-muted">
                      {selectedFinding.type === "CONTRADICTION"
                        ? "Conflicting Rules"
                        : "Trigger & Fallback"}
                    </span>
                    <span className="text-[11px] text-muted">
                      {selectedFinding.type === "CONTRADICTION"
                        ? "Equal priority without declared override"
                        : "No matching rule"}
                    </span>
                  </div>

                  {selectedFinding.type === "CONTRADICTION" &&
                  selectedFinding.rule_ids &&
                  selectedFinding.rule_ids.length >= 2 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Rule 1 (Allow -> success #7BC48F) */}
                      {(() => {
                        const r1 = rulesMap[selectedFinding.rule_ids[0]];
                        const isAllow = r1?.effect === "ALLOW";
                        return (
                          <div
                            className={`p-4 rounded-xl border flex flex-col justify-between ${
                              isAllow
                                ? "bg-success/5 border-success/30"
                                : "bg-danger/5 border-danger/30"
                            }`}
                          >
                            <div>
                              <div className="flex items-center justify-between gap-2 mb-2">
                                <span
                                  className={`text-xs font-bold px-2 py-0.5 rounded ${
                                    isAllow
                                      ? "bg-success/20 text-success"
                                      : "bg-danger/20 text-danger"
                                  }`}
                                >
                                  {isAllow ? "ALLOW" : "DENY"}
                                </span>
                                <span className="font-mono text-[11px] text-muted px-1.5 py-0.5 rounded bg-bg border border-border">
                                  {r1?.id || selectedFinding.rule_ids[0]}
                                </span>
                              </div>
                              <h4 className="text-sm font-semibold text-text">
                                {r1?.name || selectedFinding.rule_ids[0]}
                              </h4>
                              <p className="text-xs text-muted mt-2 italic border-l-2 pl-2.5 border-border">
                                &ldquo;{r1?.source?.verbatim_sentence || "Source sentence not found"}&rdquo;
                              </p>
                            </div>
                            <div className="mt-3 pt-2.5 border-t border-border/50 text-[11px] text-muted">
                              Doc: {r1?.source?.doc_name || "NovaCart Policy"}
                            </div>
                          </div>
                        );
                      })()}

                      {/* Rule 2 (Deny -> danger #E5786D) */}
                      {(() => {
                        const r2 = rulesMap[selectedFinding.rule_ids[1]];
                        const isDeny = r2?.effect === "DENY";
                        return (
                          <div
                            className={`p-4 rounded-xl border flex flex-col justify-between ${
                              isDeny
                                ? "bg-danger/5 border-danger/30"
                                : "bg-success/5 border-success/30"
                            }`}
                          >
                            <div>
                              <div className="flex items-center justify-between gap-2 mb-2">
                                <span
                                  className={`text-xs font-bold px-2 py-0.5 rounded ${
                                    isDeny
                                      ? "bg-danger/20 text-danger"
                                      : "bg-success/20 text-success"
                                  }`}
                                >
                                  {isDeny ? "DENY" : "ALLOW"}
                                </span>
                                <span className="font-mono text-[11px] text-muted px-1.5 py-0.5 rounded bg-bg border border-border">
                                  {r2?.id || selectedFinding.rule_ids[1]}
                                </span>
                              </div>
                              <h4 className="text-sm font-semibold text-text">
                                {r2?.name || selectedFinding.rule_ids[1]}
                              </h4>
                              <p className="text-xs text-muted mt-2 italic border-l-2 pl-2.5 border-border">
                                &ldquo;{r2?.source?.verbatim_sentence || "Source sentence not found"}&rdquo;
                              </p>
                            </div>
                            <div className="mt-3 pt-2.5 border-t border-border/50 text-[11px] text-muted">
                              Doc: {r2?.source?.doc_name || "NovaCart Policy"}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  ) : (
                    /* Policy Gap or Non-contradiction fallback */
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="p-4 rounded-xl border bg-warning/5 border-warning/30">
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <span className="text-xs font-bold px-2 py-0.5 rounded bg-warning/20 text-warning">
                            REQUEST EVENT
                          </span>
                          <span className="font-mono text-[11px] text-muted px-1.5 py-0.5 rounded bg-bg border border-border">
                            {selectedFinding.details?.event_type || "EVENT"}
                          </span>
                        </div>
                        <h4 className="text-sm font-semibold text-text">
                          {translateEventType(selectedFinding.details?.event_type)}
                        </h4>
                        <p className="text-xs text-muted mt-2">
                          Customer submitted this event before order reached delivered state, but no clause authorizes or denies this transition.
                        </p>
                      </div>

                      <div className="p-4 rounded-xl border bg-danger/5 border-danger/30">
                        <div className="flex items-center justify-between gap-2 mb-2">
                          <span className="text-xs font-bold px-2 py-0.5 rounded bg-danger/20 text-danger">
                            FALLBACK DENY
                          </span>
                          <span className="font-mono text-[11px] text-muted px-1.5 py-0.5 rounded bg-bg border border-border">
                            default_deny
                          </span>
                        </div>
                        <h4 className="text-sm font-semibold text-text">Default Safety Denial</h4>
                        <p className="text-xs text-muted mt-2 italic border-l-2 pl-2.5 border-border">
                          &ldquo;Engine fallback rule: Uncovered transitions default to DENY to prevent unauthorized financial operations.&rdquo;
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                {/* c) "Shortest journey that triggers it" (compact horizontal timeline) */}
                <div className="bg-surface rounded-xl border border-border p-5 space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <div>
                      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
                        Shortest journey that triggers it
                      </h3>
                      <p className="text-xs text-muted mt-0.5">
                        Minimal counterexample isolated via delta debugging
                      </p>
                    </div>

                    {selectedShrink && (
                      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-raised border border-border text-xs">
                        <span className="text-muted">
                          original <strong className="text-text">{selectedShrink.original_length}</strong> events
                        </span>
                        <ArrowRight className="w-3 h-3 text-muted" />
                        <span className="text-primary font-medium">
                          minimal <strong className="text-primary">{selectedShrink.minimal_length}</strong> events
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Horizontal Timeline */}
                  {selectedShrink?.minimal_journey && selectedShrink.minimal_journey.length > 0 ? (
                    <div className="pt-2 overflow-x-auto pb-2">
                      <motion.div
                        variants={timelineContainerVariants}
                        initial="initial"
                        animate="animate"
                        className="flex items-center gap-2 min-w-max"
                      >
                        {selectedShrink.minimal_journey.map((event, idx) => {
                          const isLast = idx === selectedShrink.minimal_journey.length - 1;
                          return (
                            <React.Fragment key={idx}>
                              <motion.div
                                variants={timelineItemVariants}
                                className={`p-3 rounded-xl border transition-all duration-150 min-w-[170px] max-w-[210px] ${
                                  isLast
                                    ? "bg-danger/10 border-danger/60 pulse-danger-ring"
                                    : "bg-raised border-border"
                                }`}
                              >
                                <div className="flex items-center justify-between gap-1 mb-1.5">
                                  <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-bg text-muted border border-border">
                                    Day {event.day}
                                  </span>
                                  {isLast ? (
                                    <span className="text-[10px] font-bold text-danger">
                                      Conflict
                                    </span>
                                  ) : (
                                    <span className="text-[10px] text-muted">
                                      Step {idx + 1}
                                    </span>
                                  )}
                                </div>
                                <div className="text-xs font-medium text-text truncate">
                                  {translateEventType(event.event_type)}
                                </div>
                                <div className="font-mono text-[10px] text-muted truncate mt-0.5">
                                  {event.event_type}
                                </div>
                              </motion.div>

                              {!isLast && (
                                <ArrowRight className="w-3.5 h-3.5 text-muted flex-shrink-0" />
                              )}
                            </React.Fragment>
                          );
                        })}
                      </motion.div>
                    </div>
                  ) : (
                    <div className="p-4 rounded-lg bg-raised border border-border text-xs text-muted text-center">
                      No minimal journey available for this finding.
                    </div>
                  )}
                </div>

                {/* d) Collapsed "Show engine trace" accordion */}
                <div className="bg-surface rounded-xl border border-border overflow-hidden">
                  <button
                    onClick={() => setTraceOpen(!traceOpen)}
                    className="w-full px-5 py-3.5 flex items-center justify-between text-xs font-semibold text-text hover:bg-raised/50 transition-colors duration-150 focus-visible:ring-1 focus-visible:ring-primary"
                  >
                    <span className="uppercase tracking-wider text-muted">
                      Show engine trace & state snapshot
                    </span>
                    {traceOpen ? (
                      <ChevronUp className="w-4 h-4 text-muted" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-muted" />
                    )}
                  </button>

                  {traceOpen && (
                    <div className="p-5 border-t border-border bg-bg/40 space-y-4">
                      {/* Raw trace text */}
                      <div>
                        <div className="text-[11px] font-medium text-muted uppercase tracking-wider mb-1.5">
                          Raw Engine Finding Trace
                        </div>
                        <pre className="p-3 rounded-lg bg-bg border border-border text-xs font-mono text-muted whitespace-pre-wrap leading-relaxed">
                          {selectedFinding.trace}
                        </pre>
                      </div>

                      {/* Fired rules */}
                      {selectedFinding.rule_ids && selectedFinding.rule_ids.length > 0 && (
                        <div>
                          <div className="text-[11px] font-medium text-muted uppercase tracking-wider mb-1.5">
                            Fired Rule Identifiers
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {selectedFinding.rule_ids.map((rid) => (
                              <span
                                key={rid}
                                className="font-mono text-xs px-2 py-1 rounded bg-raised border border-border text-primary"
                              >
                                {rid}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Final state snapshot if single simulation was run */}
                      {simResult?.final_state && (
                        <div>
                          <div className="text-[11px] font-medium text-muted uppercase tracking-wider mb-1.5">
                            Final State Snapshot ({selectedJourneyId})
                          </div>
                          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 font-mono text-xs">
                            {Object.entries(simResult.final_state)
                              .filter(([_, v]) => v !== null && v !== false && v !== 0)
                              .map(([k, v]) => (
                                <div
                                  key={k}
                                  className="p-2 rounded bg-raised border border-border flex flex-col justify-between"
                                >
                                  <span className="text-[10px] text-muted truncate">{k}</span>
                                  <span className="text-text font-semibold">{String(v)}</span>
                                </div>
                              ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </motion.div>
            </AnimatePresence>
          ) : (
            /* Empty state when no finding is selected */
            <div className="bg-surface rounded-xl border border-border p-12 text-center space-y-3">
              <CheckCircle2 className="w-8 h-8 text-success mx-auto" />
              <h3 className="text-base font-semibold text-text">No issues selected</h3>
              <p className="text-xs text-muted max-w-sm mx-auto">
                Select a finding from the left panel to inspect its conflicting rules and minimal counterexample journey.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
