"use client";

import React, { useState, useEffect } from "react";
import {
  GitCompare,
  ArrowRight,
  TrendingDown,
  TrendingUp,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Sliders,
  ShieldCheck,
  FileDiff,
  Eye,
} from "lucide-react";
import { api, DefaultData, DiffResponse } from "@/lib/api";

interface PolicyDiffProps {
  defaultData: DefaultData | null;
}

export function PolicyDiff({ defaultData }: PolicyDiffProps) {
  const [suiteType, setSuiteType] = useState<"boundary" | "pairwise">("boundary");
  const [limit, setLimit] = useState<number>(20);
  const [diffData, setDiffData] = useState<DiffResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [filterReviewOnly, setFilterReviewOnly] = useState<boolean>(false);

  // Auto-run diff when defaultData is loaded
  useEffect(() => {
    if (defaultData?.rules_v1 && defaultData?.rules_v2 && !diffData) {
      handleRunDiff();
    }
  }, [defaultData]);

  const handleRunDiff = async () => {
    if (!defaultData?.rules_v1 || !defaultData?.rules_v2) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.diff({
        rules_v1: defaultData.rules_v1,
        rules_v2: defaultData.rules_v2,
        suite_type: suiteType,
        limit: limit,
      });
      setDiffData(res);
    } catch (err: any) {
      setError(err.message || "Failed to execute policy behavioral diff.");
    } finally {
      setLoading(false);
    }
  };

  const displayedChanges = diffData?.outcome_changes.filter((c) =>
    filterReviewOnly ? c.needs_review : true
  ) || [];

  return (
    <div className="space-y-6">
      {/* Header & Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-2xl bg-slate-900/90 border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <GitCompare className="w-5 h-5 text-indigo-400" />
            Behavioral Policy Diff
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Replaying scenario suite across NovaCart v1 (30d window) vs NovaCart v2 (14d window) to detect outcome shifts and regressions.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            <button
              onClick={() => setSuiteType("boundary")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                suiteType === "boundary" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
              }`}
            >
              Boundary Suite
            </button>
            <button
              onClick={() => setSuiteType("pairwise")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                suiteType === "pairwise" ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
              }`}
            >
              Pairwise Suite
            </button>
          </div>

          <button
            onClick={handleRunDiff}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-xs flex items-center gap-2 shadow-lg shadow-indigo-600/20 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Diffing..." : "Recompute Diff"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Top Behavioral Shifts Cards */}
      {diffData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">ALLOW → DENY</span>
            <div className="text-2xl font-bold text-rose-400 mt-1 flex items-baseline gap-1.5">
              <span>{diffData.outcomes_allow_to_deny}</span>
              <span className="text-xs text-slate-500 font-normal">scenarios narrowed</span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">DENY → ALLOW</span>
            <div className="text-2xl font-bold text-emerald-400 mt-1 flex items-baseline gap-1.5">
              <span>{diffData.outcomes_deny_to_allow}</span>
              <span className="text-xs text-slate-500 font-normal">scenarios widened</span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Health Score (v1 → v2)</span>
            <div className="text-2xl font-bold text-white mt-1 flex items-baseline gap-2">
              <span className="text-slate-400">{diffData.health_v1.score}</span>
              <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-indigo-400">{diffData.health_v2.score}</span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Manual Review Required</span>
            <div className="text-2xl font-bold text-amber-400 mt-1 flex items-baseline gap-1.5">
              <span>{diffData.scenarios_needing_review.length}</span>
              <span className="text-xs text-slate-500 font-normal">potential gaps/ambiguities</span>
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="p-24 rounded-2xl bg-slate-900/60 border border-slate-800 flex flex-col items-center justify-center text-slate-400">
          <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-3" />
          <p className="text-xs">Replaying scenarios on both v1 and v2 engines to compute behavioral diff...</p>
        </div>
      ) : diffData ? (
        <div className="space-y-6">
          {/* Changed Journeys Table */}
          <div className="rounded-2xl bg-slate-900/90 border border-slate-800 p-5 space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-800">
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-rose-500" />
                  Outcome Changes Across Scenarios ({displayedChanges.length})
                </h3>
                <p className="text-[11px] text-slate-400">
                  Every behavioral shift is attributed to changed rules via execution traces.
                </p>
              </div>

              <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                <input
                  type="checkbox"
                  checked={filterReviewOnly}
                  onChange={(e) => setFilterReviewOnly(e.target.checked)}
                  className="rounded border-slate-700 text-indigo-600 focus:ring-0"
                />
                <span>Only show &ldquo;Needs Review&rdquo;</span>
              </label>
            </div>

            {displayedChanges.length === 0 ? (
              <div className="p-8 text-center text-xs text-slate-500">
                No outcome changes matching current filter.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-slate-800 text-[10px] text-slate-500 uppercase tracking-wider">
                      <th className="pb-2.5 font-semibold">Scenario</th>
                      <th className="pb-2.5 font-semibold">Event @ Day</th>
                      <th className="pb-2.5 font-semibold">v1 Outcome</th>
                      <th className="pb-2.5 font-semibold">v2 Outcome</th>
                      <th className="pb-2.5 font-semibold">Attributed Rule(s)</th>
                      <th className="pb-2.5 font-semibold">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60 font-mono">
                    {displayedChanges.map((c, i) => (
                      <tr key={i} className="hover:bg-slate-800/30 transition-colors">
                        <td className="py-3 pr-3 font-semibold text-slate-200">
                          {c.scenario_id}
                        </td>
                        <td className="py-3 pr-3 text-slate-400">
                          {c.event_type} @ d{c.day}
                        </td>
                        <td className="py-3 pr-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              c.outcome_v1 === "ALLOW"
                                ? "bg-emerald-500/20 text-emerald-300"
                                : "bg-rose-500/20 text-rose-300"
                            }`}
                          >
                            {c.outcome_v1}
                          </span>
                        </td>
                        <td className="py-3 pr-3">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              c.outcome_v2 === "ALLOW"
                                ? "bg-emerald-500/20 text-emerald-300"
                                : "bg-rose-500/20 text-rose-300"
                            }`}
                          >
                            {c.outcome_v2}
                          </span>
                        </td>
                        <td className="py-3 pr-3 text-indigo-300 text-[11px]">
                          {c.attributed_rule_ids.join(", ") || "threshold shift"}
                        </td>
                        <td className="py-3 pr-3">
                          {c.needs_review ? (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                              ⚠ Needs Review
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-400">
                              Expected Shift
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Rule-Level Textual Diff */}
          <div className="rounded-2xl bg-slate-900/90 border border-slate-800 p-5 space-y-4">
            <h3 className="text-sm font-bold text-white flex items-center gap-2 pb-3 border-b border-slate-800">
              <FileDiff className="w-4 h-4 text-cyan-400" />
              Rule-Level Specification Diff ({diffData.rule_text_diffs.length} rules)
            </h3>

            <div className="space-y-3">
              {diffData.rule_text_diffs.map((d) => {
                const badgeColor =
                  d.status === "MODIFIED"
                    ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
                    : d.status === "ADDED"
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/30"
                    : d.status === "REMOVED"
                    ? "bg-rose-500/20 text-rose-300 border-rose-500/30"
                    : "bg-slate-800 text-slate-400 border-slate-700";

                return (
                  <div key={d.rule_id} className="p-4 rounded-xl bg-slate-950 border border-slate-800/80 space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold border ${badgeColor}`}>
                          {d.status}
                        </span>
                        <span className="font-mono text-xs text-white font-semibold">{d.rule_id}</span>
                      </div>
                    </div>

                    {d.changes.length > 0 && (
                      <div className="space-y-1 pt-1 text-xs font-mono text-amber-300/90">
                        {d.changes.map((change, cIdx) => (
                          <div key={cIdx} className="flex items-start gap-1.5">
                            <span className="text-amber-400">Δ</span>
                            <span>{change}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px] font-mono text-slate-400 pt-1">
                      {d.v1_summary && (
                        <div className="p-2 rounded bg-slate-900/60 border border-slate-800/60">
                          <span className="text-slate-500 uppercase text-[9px] block">v1 spec:</span>
                          <span className="line-clamp-2">{d.v1_summary}</span>
                        </div>
                      )}
                      {d.v2_summary && (
                        <div className="p-2 rounded bg-slate-900/60 border border-slate-800/60">
                          <span className="text-slate-500 uppercase text-[9px] block">v2 spec:</span>
                          <span className="line-clamp-2 text-indigo-300">{d.v2_summary}</span>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
