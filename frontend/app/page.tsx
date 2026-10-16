"use client";

import React, { useState, useEffect } from "react";
import {
  LayoutDashboard,
  FileCode,
  Zap,
  GitCompare,
  Workflow,
  Server,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
} from "lucide-react";
import { api, DefaultData } from "@/lib/api";
import { Dashboard } from "@/components/screens/Dashboard";
import { Compiler } from "@/components/screens/Compiler";
import { StressTest } from "@/components/screens/StressTest";
import { PolicyDiff } from "@/components/screens/PolicyDiff";
import { ProcessGraph } from "@/components/screens/ProcessGraph";

type TabType = "dashboard" | "compiler" | "stress" | "diff" | "graph";

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>("dashboard");
  const [defaultData, setDefaultData] = useState<DefaultData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDefaultData();
      setDefaultData(data);
    } catch (err: any) {
      setError(
        err.message ||
          "Could not connect to PolicyForge backend on http://localhost:8000. Ensure the FastAPI server is running."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const navItems: Array<{ id: TabType; label: string; icon: React.ComponentType<{ className?: string }> }> = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "compiler", label: "Policy Compiler", icon: FileCode },
    { id: "stress", label: "Stress Test", icon: Zap },
    { id: "diff", label: "Policy Diff", icon: GitCompare },
    { id: "graph", label: "Process Graph", icon: Workflow },
  ];

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="sticky top-0 z-50 bg-[#090d16]/80 backdrop-blur-md border-b border-slate-800/80 px-6 py-3.5">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          {/* Logo & Subtitle */}
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-extrabold text-base tracking-tight text-white">PolicyForge</span>
                <span className="px-1.5 py-0.2 rounded text-[10px] font-mono font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  v1.0.0
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-medium">
                CI/CD for Business Policies • NovaCart
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <nav className="flex items-center gap-1.5 bg-slate-900/90 p-1 rounded-xl border border-slate-800 overflow-x-auto">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = activeTab === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveTab(item.id)}
                  className={`flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all whitespace-nowrap ${
                    isActive
                      ? "bg-indigo-600 text-white shadow-md shadow-indigo-600/30"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                  }`}
                >
                  <Icon className={`w-3.5 h-3.5 ${isActive ? "text-white" : "text-slate-400"}`} />
                  {item.label}
                </button>
              );
            })}
          </nav>

          {/* Backend Connection Indicator */}
          <div className="hidden lg:flex items-center gap-2 text-xs">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300">
              <Server className="w-3.5 h-3.5 text-slate-400" />
              <span className="font-mono text-[11px]">localhost:8000</span>
              <span
                className={`w-2 h-2 rounded-full ${
                  error ? "bg-rose-500" : defaultData ? "bg-emerald-500 animate-pulse" : "bg-amber-500"
                }`}
              />
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-8">
        {loading ? (
          <div className="min-h-[60vh] flex flex-col items-center justify-center text-slate-400 space-y-4">
            <div className="w-10 h-10 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
            <div className="text-center">
              <h3 className="text-sm font-semibold text-slate-200">Connecting to PolicyForge Engine...</h3>
              <p className="text-xs text-slate-500 mt-1">Loading NovaCart policy documents and rule sets.</p>
            </div>
          </div>
        ) : error ? (
          <div className="min-h-[50vh] flex flex-col items-center justify-center text-center p-8 max-w-md mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 mb-4">
              <AlertCircle className="w-6 h-6" />
            </div>
            <h2 className="text-lg font-bold text-white">Backend Connection Error</h2>
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">{error}</p>
            <div className="mt-4 p-3 bg-slate-900 rounded-xl border border-slate-800 text-left font-mono text-[11px] text-slate-300 space-y-1">
              <div className="text-slate-500">To start the backend, run:</div>
              <div className="text-indigo-300">uvicorn backend.policyforge.api:app --reload</div>
            </div>
            <button
              onClick={fetchData}
              className="mt-6 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-medium text-xs flex items-center gap-2 shadow-lg shadow-indigo-600/20"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry Connection
            </button>
          </div>
        ) : (
          <div>
            {activeTab === "dashboard" && (
              <Dashboard
                defaultData={defaultData}
                onNavigate={(tab) => setActiveTab(tab as TabType)}
              />
            )}
            {activeTab === "compiler" && <Compiler defaultData={defaultData} />}
            {activeTab === "stress" && <StressTest defaultData={defaultData} />}
            {activeTab === "diff" && <PolicyDiff defaultData={defaultData} />}
            {activeTab === "graph" && <ProcessGraph defaultData={defaultData} />}
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-900 bg-slate-950/40 py-4 px-6 text-center text-xs text-slate-500">
        PolicyForge Business Policy Verifier • Deterministic Simulation • Grounding Verified • Zero LLM in findings loop
      </footer>
    </div>
  );
}
