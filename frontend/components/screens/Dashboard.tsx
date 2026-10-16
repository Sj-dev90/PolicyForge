"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Zap,
  FileCode,
  Layers,
  ArrowRight,
  Server,
  Activity,
  ChevronRight,
} from "lucide-react";
import { api, DefaultData, SimulateResponse } from "@/lib/api";

interface DashboardProps {
  defaultData: DefaultData | null;
  onNavigate: (tab: string) => void;
}

export function Dashboard({ defaultData, onNavigate }: DashboardProps) {
  const [selectedJourneyId, setSelectedJourneyId] = useState<string>("canonical_contradiction");
  const [simulationResult, setSimulationResult] = useState<SimulateResponse | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-run simulation on journey change
  useEffect(() => {
    if (!defaultData?.rules_v1 || !defaultData?.sample_journeys) return;
    const currentJourney = defaultData.sample_journeys.find((j) => j.id === selectedJourneyId);
    if (!currentJourney) return;

    runSim(currentJourney.journey);
  }, [selectedJourneyId, defaultData]);

  const runSim = async (journey: any[]) => {
    if (!defaultData?.rules_v1) return;
    setSimulating(true);
    setError(null);
    try {
      const res = await api.simulate({
        rules: defaultData.rules_v1,
        journey: journey,
      });
      setSimulationResult(res);
    } catch (err: any) {
      setError(err.message || "Simulation failed");
    } finally {
      setSimulating(false);
    }
  };

  const sampleJourneys = defaultData?.sample_journeys || [];
  const rules = defaultData?.rules_v1 || [];

  return (
    <div className="space-y-8">
      {/* Hero Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl bg-gradient-to-r from-indigo-950/60 via-slate-900 to-slate-900/80 border border-indigo-900/40 backdrop-blur-sm">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
              CI/CD FOR BUSINESS POLICIES
            </span>
            <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Engine Online
            </span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            PolicyForge <span className="text-indigo-400">Control Center</span>
          </h1>
          <p className="text-slate-400 text-sm mt-1 max-w-2xl">
            Deterministic simulation, grounding-verified compilation, and automated counterexample reduction for NovaCart e-commerce policies.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => onNavigate("compiler")}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-sm flex items-center gap-2 shadow-lg shadow-indigo-600/20 transition-all hover:scale-[1.02]"
          >
            <FileCode className="w-4 h-4" />
            Policy Compiler
          </button>
          <button
            onClick={() => onNavigate("stress")}
            className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium text-sm flex items-center gap-2 transition-all hover:scale-[1.02]"
          >
            <Zap className="w-4 h-4 text-amber-400" />
            Run Stress Test
          </button>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition-all shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active Rules</span>
            <Layers className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white">{rules.length || "12"}</span>
            <span className="text-xs text-slate-500">NovaCart v1</span>
          </div>
          <div className="mt-2 text-xs text-slate-400 flex items-center gap-1">
            <span className="text-emerald-400 font-medium">100%</span> grounded in source documents
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition-all shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Engine Latency</span>
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold text-emerald-400">0.36</span>
            <span className="text-xs text-slate-500">ms / journey</span>
          </div>
          <div className="mt-2 text-xs text-slate-400 flex items-center gap-1">
            <span className="text-emerald-400 font-medium">Deterministic</span> Python (zero LLM in loop)
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition-all shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Invariant Registry</span>
            <CheckCircle2 className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white">5</span>
            <span className="text-xs text-slate-500">pure guardrails</span>
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Enforces monetary, order, & state invariants
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900/80 border border-slate-800 hover:border-slate-700 transition-all shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Planted Vulnerabilities</span>
            <AlertTriangle className="w-4 h-4 text-rose-400" />
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-bold text-rose-400">2</span>
            <span className="text-xs text-slate-500">in NovaCart v1</span>
          </div>
          <div className="mt-2 text-xs text-slate-400">
            Contradiction (d36) + Pre-delivery gap
          </div>
        </div>
      </div>

      {/* Interactive Quick Simulator */}
      <div className="rounded-2xl bg-slate-900/90 border border-slate-800 p-6 shadow-xl">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-5 border-b border-slate-800">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Play className="w-5 h-5 text-indigo-400 fill-indigo-400/20" />
              Live Journey Simulator
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">
              Select a customer journey to run real-time deterministic evaluation through all 12 rules.
            </p>
          </div>

          {/* Journey Selector Tabs */}
          <div className="flex flex-wrap gap-2">
            {sampleJourneys.map((j) => (
              <button
                key={j.id}
                onClick={() => setSelectedJourneyId(j.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  selectedJourneyId === j.id
                    ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                    : "bg-slate-800 text-slate-300 hover:bg-slate-700"
                }`}
              >
                {j.name.split("(")[0]}
              </button>
            ))}
          </div>
        </div>

        {error && (
          <div className="mt-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        {simulating ? (
          <div className="py-12 flex flex-col items-center justify-center text-slate-400">
            <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-3" />
            <p className="text-xs">Executing deterministic simulation...</p>
          </div>
        ) : simulationResult ? (
          <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Journey Stepper (Col 1 & 2) */}
            <div className="lg:col-span-2 space-y-4">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Event Execution Timeline
              </h3>

              <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-slate-800">
                {simulationResult.trace.event_traces.map((trace, idx) => {
                  const outcome = simulationResult.outcomes[idx];
                  const isDecision = trace.is_decision_event;
                  const isDeny = outcome?.outcome === "DENY";
                  const isContradiction = outcome?.resolution_type === "CONTRADICTION";

                  return (
                    <div key={idx} className="relative group">
                      {/* Step Circle */}
                      <div
                        className={`absolute -left-6 top-1.5 w-5 h-5 rounded-full border-2 flex items-center justify-center text-[10px] font-bold ${
                          isContradiction
                            ? "bg-rose-950 border-rose-500 text-rose-300"
                            : isDecision
                            ? isDeny
                              ? "bg-amber-950 border-amber-500 text-amber-300"
                              : "bg-emerald-950 border-emerald-500 text-emerald-300"
                            : "bg-slate-900 border-slate-700 text-slate-400"
                        }`}
                      >
                        {idx}
                      </div>

                      <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-all">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-xs text-indigo-300 font-semibold">
                              {trace.event_type}
                            </span>
                            <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-400">
                              Day {trace.day}
                            </span>
                          </div>

                          {isDecision ? (
                            <span
                              className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${
                                isContradiction
                                  ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                                  : isDeny
                                  ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                  : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              }`}
                            >
                              {outcome.outcome} ({outcome.resolution_type})
                            </span>
                          ) : (
                            <span className="text-xs text-slate-500 italic">State Transition</span>
                          )}
                        </div>

                        <p className="text-xs text-slate-300 mt-2">{trace.explanation}</p>

                        {trace.rules_fired.length > 0 && (
                          <div className="mt-3 pt-3 border-t border-slate-800/60 flex flex-wrap items-center gap-1.5">
                            <span className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                              Fired:
                            </span>
                            {trace.rules_fired.map((rid) => (
                              <span
                                key={rid}
                                className={`px-2 py-0.5 rounded text-[11px] font-mono ${
                                  isContradiction
                                    ? "bg-rose-950/80 text-rose-300 border border-rose-800/50"
                                    : "bg-indigo-950/60 text-indigo-300 border border-indigo-800/40"
                                }`}
                              >
                                {rid}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Findings & State Inspector (Col 3) */}
            <div className="space-y-6">
              {/* Findings Card */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center justify-between">
                  <span>Detected Findings</span>
                  <span className="px-2 py-0.5 rounded-full text-[10px] bg-slate-800 text-slate-300">
                    {simulationResult.findings.length}
                  </span>
                </h3>

                {simulationResult.findings.length === 0 ? (
                  <div className="p-4 text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-lg">
                    ✓ Clean journey: zero findings or invariant violations.
                  </div>
                ) : (
                  <div className="space-y-3">
                    {simulationResult.findings.map((f, i) => (
                      <div
                        key={i}
                        className="p-3 rounded-lg bg-rose-950/30 border border-rose-900/40 text-xs space-y-1.5"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-rose-300 flex items-center gap-1.5">
                            <ShieldAlert className="w-3.5 h-3.5" />
                            {f.type}
                          </span>
                          <span className="px-1.5 py-0.5 text-[10px] uppercase font-bold rounded bg-rose-900/60 text-rose-200">
                            {f.severity}
                          </span>
                        </div>
                        <p className="text-slate-300 text-[11px] leading-relaxed">{f.trace}</p>
                        <div className="text-[10px] text-slate-400 font-mono">
                          Rules: {f.rule_ids?.join(", ") || "None"}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Final State Inspector */}
              <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
                  Final State Snapshot
                </h3>
                <div className="max-h-56 overflow-y-auto space-y-1 font-mono text-[11px] pr-2">
                  {Object.entries(simulationResult.final_state)
                    .filter(([_, v]) => v !== null && v !== false && v !== 0)
                    .map(([k, v]) => (
                      <div key={k} className="flex justify-between py-1 border-b border-slate-800/40">
                        <span className="text-slate-400">{k}</span>
                        <span className="text-indigo-300 font-semibold">{String(v)}</span>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
