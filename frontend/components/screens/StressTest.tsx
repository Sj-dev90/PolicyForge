"use client";

import React, { useState, useEffect } from "react";
import {
  Zap,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Minimize2,
  Clock,
  ArrowRight,
  RefreshCw,
  Layers,
  ChevronRight,
  Code,
  Flame,
} from "lucide-react";
import { api, DefaultData, SuiteResponse } from "@/lib/api";

interface StressTestProps {
  defaultData: DefaultData | null;
}

export function StressTest({ defaultData }: StressTestProps) {
  const [suiteType, setSuiteType] = useState<"boundary" | "pairwise">("boundary");
  const [limit, setLimit] = useState<number>(30);
  const [suiteData, setSuiteData] = useState<SuiteResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFindingIndex, setSelectedFindingIndex] = useState<number>(0);

  // Auto-run stress test on initial mount
  useEffect(() => {
    if (defaultData?.rules_v1 && !suiteData) {
      handleRunSuite();
    }
  }, [defaultData]);

  const handleRunSuite = async () => {
    if (!defaultData?.rules_v1) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.runSuite({
        rules: defaultData.rules_v1,
        suite_type: suiteType,
        limit: limit,
      });
      setSuiteData(res);
      setSelectedFindingIndex(0);
    } catch (err: any) {
      setError(err.message || "Failed to execute stress test suite.");
    } finally {
      setLoading(false);
    }
  };

  const selectedFindingItem = suiteData?.findings?.[selectedFindingIndex];
  const finding = selectedFindingItem?.finding;
  const shrink = selectedFindingItem?.shrink;

  // Find rule objects for conflicting rule IDs
  const conflictingRules = defaultData?.rules_v1?.filter((r) =>
    finding?.rule_ids?.includes(r.id)
  ) || [];

  return (
    <div className="space-y-6">
      {/* Top Header & Suite Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-2xl bg-slate-900/90 border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Flame className="w-5 h-5 text-amber-400" />
            Automated Stress Testing & Delta Debugging
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Combinatorial journeys replay across policy space with automated minimal counterexample generation (ddmin).
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Suite Type Selector */}
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            <button
              onClick={() => setSuiteType("boundary")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                suiteType === "boundary" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
              }`}
            >
              Boundary Analysis (±1d)
            </button>
            <button
              onClick={() => setSuiteType("pairwise")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                suiteType === "pairwise" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
              }`}
            >
              Pairwise Combinatorial
            </button>
          </div>

          {/* Scenario Limit */}
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="bg-slate-950 text-slate-300 text-xs px-3 py-1.5 rounded-xl border border-slate-800 focus:outline-none"
          >
            <option value={15}>15 scenarios</option>
            <option value={30}>30 scenarios</option>
            <option value={50}>50 scenarios</option>
          </select>

          {/* Run Button */}
          <button
            onClick={handleRunSuite}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white font-medium text-xs flex items-center gap-2 shadow-lg shadow-amber-600/20 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Testing..." : "Execute Suite"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* KPI Cards */}
      {suiteData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Scenarios Replayed</span>
            <div className="text-2xl font-bold text-white mt-1">{suiteData.total_scenarios}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Passing Scenarios</span>
            <div className="text-2xl font-bold text-emerald-400 mt-1">{suiteData.passed_scenarios}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Failing Scenarios</span>
            <div className="text-2xl font-bold text-rose-400 mt-1">{suiteData.failed_scenarios}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Unique Failure Signatures</span>
            <div className="text-2xl font-bold text-amber-400 mt-1">{suiteData.findings_count}</div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="p-24 rounded-2xl bg-slate-900/60 border border-slate-800 flex flex-col items-center justify-center text-slate-400">
          <div className="w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-xs">Simulating journeys and computing minimal counterexamples via ddmin...</p>
        </div>
      ) : suiteData ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Column: Unique Findings List */}
          <div className="space-y-3">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider px-1">
              Discovered Findings ({suiteData.findings_count})
            </h3>

            {suiteData.findings.length === 0 ? (
              <div className="p-6 rounded-xl bg-slate-900/40 border border-slate-800 text-center text-xs text-slate-400">
                ✓ No findings detected in this scenario suite.
              </div>
            ) : (
              <div className="space-y-2.5">
                {suiteData.findings.map((item, idx) => {
                  const f = item.finding;
                  const isSelected = selectedFindingIndex === idx;

                  return (
                    <div
                      key={idx}
                      onClick={() => setSelectedFindingIndex(idx)}
                      className={`p-4 rounded-xl border text-xs cursor-pointer transition-all ${
                        isSelected
                          ? "bg-slate-900 border-indigo-500 shadow-md shadow-indigo-600/10"
                          : "bg-slate-950/60 border-slate-800/80 hover:border-slate-700 text-slate-300"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-bold text-rose-400 flex items-center gap-1.5 font-mono">
                          <ShieldAlert className="w-3.5 h-3.5" />
                          {f.type}
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-rose-500/20 text-rose-300 border border-rose-500/30">
                          {f.severity}
                        </span>
                      </div>

                      <p className="text-slate-300 text-[11px] line-clamp-2 leading-relaxed">{f.trace}</p>

                      <div className="mt-2.5 pt-2.5 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-500">
                        <span>Rules: {f.rule_ids?.length || 0}</span>
                        {item.shrink && (
                          <span className="text-emerald-400 font-semibold flex items-center gap-1">
                            <Minimize2 className="w-3 h-3" />
                            -{item.shrink.reduction_pct}% shrunk
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Right Column: Selected Finding Detail & Minimal Counterexample */}
          <div className="lg:col-span-2 space-y-5">
            {finding ? (
              <>
                {/* Finding Header Card */}
                <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="px-2.5 py-1 rounded-md text-xs font-mono font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                        {finding.type}
                      </span>
                      <span className="text-xs text-slate-400">Severity: {finding.severity}</span>
                    </div>

                    {shrink && (
                      <span className="px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 flex items-center gap-1.5">
                        <Minimize2 className="w-3.5 h-3.5" />
                        Reduced by {shrink.reduction_pct}% ({shrink.original_length} → {shrink.minimal_length} steps)
                      </span>
                    )}
                  </div>

                  <p className="text-sm text-slate-200 leading-relaxed font-medium bg-slate-950 p-3 rounded-xl border border-slate-800">
                    {finding.trace}
                  </p>
                </div>

                {/* Minimal Counterexample Timeline Comparison */}
                {shrink && (
                  <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-4">
                    <div className="flex items-center justify-between">
                      <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                        <Minimize2 className="w-4 h-4 text-emerald-400" />
                        Minimal Counterexample Timeline (Delta Debugging)
                      </h3>
                      <span className="text-[11px] text-slate-500 font-mono">
                        {shrink.engine_runs} engine iterations
                      </span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {/* Original Journey */}
                      <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800">
                        <div className="text-[11px] font-semibold text-slate-400 mb-2 flex items-center justify-between">
                          <span>Original Journey ({shrink.original_length} steps)</span>
                          <span className="text-slate-500 font-mono">Unreduced</span>
                        </div>
                        <div className="space-y-1.5">
                          {shrink.original_journey.map((ev, i) => (
                            <div
                              key={i}
                              className="px-2.5 py-1.5 rounded bg-slate-900/70 border border-slate-800/60 text-xs font-mono flex items-center justify-between"
                            >
                              <span className="text-slate-300">{ev.event_type}</span>
                              <span className="text-slate-500 text-[10px]">d{ev.day}</span>
                            </div>
                          ))}
                        </div>
                      </div>

                      {/* Minimal Journey */}
                      <div className="p-3.5 rounded-xl bg-emerald-950/20 border border-emerald-900/40">
                        <div className="text-[11px] font-semibold text-emerald-400 mb-2 flex items-center justify-between">
                          <span>Minimal Counterexample ({shrink.minimal_length} steps)</span>
                          <span className="text-emerald-400 font-mono">Verified Minimal</span>
                        </div>
                        <div className="space-y-1.5">
                          {shrink.minimal_journey.map((ev, i) => (
                            <div
                              key={i}
                              className="px-2.5 py-1.5 rounded bg-emerald-950/40 border border-emerald-800/40 text-xs font-mono flex items-center justify-between text-emerald-200"
                            >
                              <span>{ev.event_type}</span>
                              <span className="text-emerald-400 text-[10px]">d{ev.day}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Conflicting Rules Highlighted */}
                <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-3">
                  <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider flex items-center gap-1.5">
                    <ShieldAlert className="w-4 h-4 text-rose-400" />
                    Conflicting Rules Highlighted
                  </h3>

                  {conflictingRules.length === 0 ? (
                    <div className="text-xs text-slate-500 italic p-3 bg-slate-950 rounded-lg">
                      No explicit rule IDs tied to this finding (e.g. general policy gap or invariant violation).
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {conflictingRules.map((rule) => (
                        <div
                          key={rule.id}
                          className="p-4 rounded-xl bg-slate-950 border border-rose-900/40 space-y-2.5"
                        >
                          <div className="flex items-center justify-between">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
                                rule.effect === "ALLOW"
                                  ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                  : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                              }`}
                            >
                              {rule.effect}
                            </span>
                            <span className="text-[10px] text-slate-500 font-mono">
                              Priority: {rule.priority}
                            </span>
                          </div>

                          <div className="font-mono text-xs text-white font-semibold">{rule.id}</div>
                          <p className="text-xs text-slate-300">{rule.name}</p>

                          <div className="p-2 rounded bg-slate-900 font-mono text-[10px] text-slate-400">
                            {JSON.stringify(rule.when)}
                          </div>

                          {rule.source?.verbatim_sentence && (
                            <p className="text-[11px] text-slate-400 italic">
                              &ldquo;{rule.source.verbatim_sentence}&rdquo;
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="p-12 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-2xl">
                Select a finding from the left to inspect its minimal counterexample.
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
