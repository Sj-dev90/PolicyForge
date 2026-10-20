"use client";

import React, { useState, useEffect } from "react";
import { AlertCircle, RefreshCw, Moon, Sun, ShieldCheck } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { api, DefaultData } from "@/lib/api";
import { IssuesScreen } from "@/components/screens/IssuesScreen";
import { PoliciesScreen } from "@/components/screens/PoliciesScreen";
import { WhatIfScreen } from "@/components/screens/WhatIfScreen";
import { pageVariants } from "@/lib/motion";

type Tab = "issues" | "policies" | "whatif";

const TABS: { id: Tab; label: string }[] = [
  { id: "issues",   label: "Issues" },
  { id: "policies", label: "Policies" },
  { id: "whatif",   label: "What-if" },
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<Tab>("issues");
  const [defaultData, setDefaultData] = useState<DefaultData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ── Theme: read from localStorage, fall back to prefers-color-scheme ──
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem("pf-theme");
    if (stored) {
      setDark(stored === "dark");
    } else {
      setDark(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }
  }, []);

  useEffect(() => {
    if (dark) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("pf-theme", dark ? "dark" : "light");
  }, [dark]);

  // ── Data fetch ──────────────────────────────────────────────────────────
  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDefaultData();
      setDefaultData(data);
    } catch (err: any) {
      setError(
        err.message ??
          "Cannot reach the PolicyForge backend at http://localhost:8000."
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="min-h-screen bg-bg text-text font-sans flex flex-col">

      {/* ── Navigation ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-surface border-b border-border">
        <div className="max-w-page mx-auto px-6 h-14 flex items-center justify-between">
          {/* Logo */}
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-primary" />
            <span className="font-semibold text-base text-text">PolicyForge</span>
          </div>

          {/* Three tabs */}
          <nav className="flex items-center gap-1" role="tablist" aria-label="Main navigation">
            {TABS.map(({ id, label }) => {
              const active = activeTab === id;
              return (
                <button
                  key={id}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setActiveTab(id)}
                  className={`
                    px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150
                    focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary
                    ${active
                      ? "bg-primary/10 text-primary"
                      : "text-muted hover:text-text hover:bg-border/50"
                    }
                  `}
                >
                  {label}
                </button>
              );
            })}
          </nav>

          {/* Right: status + theme toggle */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-sm">
              <span
                className={`w-2 h-2 rounded-full ${
                  error ? "bg-deny" : defaultData ? "bg-allow animate-none" : "bg-warning animate-pulse"
                }`}
              />
              <span className="text-muted text-xs font-mono">
                {error ? "offline" : defaultData ? "connected" : "connecting…"}
              </span>
            </div>
            <button
              aria-label="Toggle dark mode"
              onClick={() => setDark(d => !d)}
              className="p-2 rounded-lg text-muted hover:text-text hover:bg-border/50 transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            >
              {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </header>

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <main className="flex-1 max-w-page mx-auto w-full px-6 py-8">
        {loading ? (
          <SkeletonLoader />
        ) : error ? (
          <ErrorState error={error} onRetry={fetchData} />
        ) : (
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              variants={pageVariants}
              initial="initial"
              animate="animate"
              exit="exit"
              className="w-full"
            >
              {activeTab === "issues"   && <IssuesScreen   defaultData={defaultData} />}
              {activeTab === "policies" && <PoliciesScreen defaultData={defaultData} />}
              {activeTab === "whatif"   && <WhatIfScreen   defaultData={defaultData} />}
            </motion.div>
          </AnimatePresence>
        )}
      </main>
    </div>
  );
}

// ── Skeleton ─────────────────────────────────────────────────────────────
function SkeletonLoader() {
  return (
    <div className="animate-pulse space-y-4" aria-busy="true" aria-label="Loading">
      <div className="h-28 bg-surface rounded-xl border border-border" />
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-4 h-64 bg-surface rounded-xl border border-border" />
        <div className="col-span-8 h-64 bg-surface rounded-xl border border-border" />
      </div>
    </div>
  );
}

// ── Error ─────────────────────────────────────────────────────────────────
function ErrorState({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-24 gap-4 max-w-md mx-auto">
      <div className="w-12 h-12 rounded-xl bg-deny-bg border border-deny/30 flex items-center justify-center">
        <AlertCircle className="w-6 h-6 text-deny" />
      </div>
      <h2 className="text-lg font-semibold text-text">Can't reach the engine</h2>
      <p className="text-muted text-sm leading-relaxed">{error}</p>
      <div className="w-full p-3 bg-surface rounded-lg border border-border text-left font-mono text-xs text-muted">
        uvicorn backend.policyforge.api:app --reload
      </div>
      <button
        onClick={onRetry}
        className="flex items-center gap-2 px-5 py-2.5 rounded-lg bg-primary text-white text-sm font-medium hover:opacity-90 transition-opacity duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      >
        <RefreshCw className="w-4 h-4" />
        Retry
      </button>
    </div>
  );
}
