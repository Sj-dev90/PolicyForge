"use client";

import React, { useState, useEffect } from "react";
import {
  FileCode,
  ShieldCheck,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Search,
  ExternalLink,
  Code2,
  Sparkles,
} from "lucide-react";
import { api, DefaultData, CompileResponse } from "@/lib/api";

interface CompilerProps {
  defaultData: DefaultData | null;
}

export function Compiler({ defaultData }: CompilerProps) {
  const [selectedDoc, setSelectedDoc] = useState<string>("refund_policy.md");
  const [docContent, setDocContent] = useState<string>("");
  const [compileReport, setCompileReport] = useState<CompileResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [useMock, setUseMock] = useState<boolean>(true);
  const [activeClauseId, setActiveClauseId] = useState<string | null>(null);

  // Initialize with selected document content
  useEffect(() => {
    if (defaultData?.documents && defaultData.documents[selectedDoc]) {
      setDocContent(defaultData.documents[selectedDoc]);
    }
  }, [selectedDoc, defaultData]);

  // Initial compilation on load
  useEffect(() => {
    if (docContent && !compileReport) {
      handleCompile();
    }
  }, [docContent]);

  const handleCompile = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.compile({
        document_text: docContent,
        doc_name: selectedDoc,
        use_mock: useMock,
        max_repairs: 2,
      });
      setCompileReport(res);
    } catch (err: any) {
      setError(err.message || "Failed to compile document.");
    } finally {
      setLoading(false);
    }
  };

  // Split lines into clauses for highlighting
  const rawLines = docContent.split("\n");
  const unmappedIds = new Set(compileReport?.unmapped_clauses.map((c) => c.id) || []);

  return (
    <div className="space-y-6">
      {/* Top Controls */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-2xl bg-slate-900/90 border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <FileCode className="w-5 h-5 text-indigo-400" />
            Policy Compiler & Grounding Verifier
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Natural-language clauses parsed into deterministic, typed rule schemas with source-grounding checks.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Doc Selector */}
          <div className="flex bg-slate-950 p-1 rounded-xl border border-slate-800 text-xs">
            {["refund_policy.md", "replacement_policy.md", "support_sop.md"].map((doc) => (
              <button
                key={doc}
                onClick={() => {
                  setSelectedDoc(doc);
                  setCompileReport(null);
                }}
                className={`px-3 py-1.5 rounded-lg font-medium transition-all ${
                  selectedDoc === doc ? "bg-indigo-600 text-white shadow-sm" : "text-slate-400 hover:text-white"
                }`}
              >
                {doc.replace(".md", "")}
              </button>
            ))}
          </div>

          {/* Mock toggle */}
          <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer bg-slate-950 px-3 py-1.5 rounded-xl border border-slate-800">
            <input
              type="checkbox"
              checked={useMock}
              onChange={(e) => setUseMock(e.target.checked)}
              className="rounded border-slate-700 text-indigo-600 focus:ring-0"
            />
            <span>Mock Extractor</span>
          </label>

          {/* Compile Button */}
          <button
            onClick={handleCompile}
            disabled={loading}
            className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-medium text-xs flex items-center gap-2 shadow-lg shadow-indigo-600/20 transition-all"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            {loading ? "Compiling..." : "Re-compile Document"}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Compiler Diagnostic Metrics Bar */}
      {compileReport && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Total Clauses</span>
            <div className="text-2xl font-bold text-white mt-1">{compileReport.total_clauses}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Mapped Rules</span>
            <div className="text-2xl font-bold text-emerald-400 mt-1">{compileReport.compiled_rules.length}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Unmapped Clauses</span>
            <div className="text-2xl font-bold text-amber-400 mt-1">{compileReport.unmapped_clauses.length}</div>
          </div>
          <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800">
            <span className="text-[11px] text-slate-400 uppercase font-semibold">Coverage</span>
            <div className="text-2xl font-bold text-indigo-400 mt-1">
              {compileReport.total_clauses
                ? Math.round((compileReport.mapped_clauses / compileReport.total_clauses) * 100)
                : 0}
              %
            </div>
          </div>
        </div>
      )}

      {/* Main Split View: Left Clauses, Right Rules */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Natural Language Document Clauses */}
        <div className="rounded-2xl bg-slate-900/80 border border-slate-800 p-5 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-500" />
              Source Policy Document ({selectedDoc})
            </h3>
            <span className="text-[11px] text-slate-500">Click a clause to highlight rule</span>
          </div>

          <div className="space-y-2.5 max-h-[620px] overflow-y-auto pr-1">
            {rawLines.map((line, idx) => {
              const trimmed = line.trim();
              if (!trimmed) return null;
              if (trimmed.startsWith("#")) {
                return (
                  <h4 key={idx} className="text-xs font-bold text-slate-400 uppercase tracking-wider pt-2">
                    {trimmed.replace(/^#+\s*/, "")}
                  </h4>
                );
              }

              // Match pattern like [RP-1], [REP-2], [SOP-3]
              const match = trimmed.match(/^\[([A-Z0-9_\-]+)\]\s*(.+)$/i);
              const clauseId = match ? match[1] : null;
              const isUnmapped = clauseId ? unmappedIds.has(clauseId) : false;
              const isSelected = clauseId && activeClauseId === clauseId;

              return (
                <div
                  key={idx}
                  onClick={() => clauseId && setActiveClauseId(clauseId)}
                  className={`p-3 rounded-xl border text-xs leading-relaxed transition-all cursor-pointer ${
                    isSelected
                      ? "bg-indigo-950/60 border-indigo-500 text-white shadow-md shadow-indigo-600/20"
                      : isUnmapped
                      ? "bg-amber-950/20 border-amber-900/40 text-amber-200/90 hover:border-amber-700"
                      : "bg-slate-950/40 border-slate-800/80 text-slate-300 hover:border-slate-700"
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    {clauseId ? (
                      <span className="font-mono px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-indigo-300 border border-slate-700">
                        [{clauseId}]
                      </span>
                    ) : (
                      <span className="text-[10px] text-slate-500 italic">Paragraph</span>
                    )}

                    {isUnmapped && (
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/30 flex items-center gap-1">
                        <AlertTriangle className="w-3 h-3" />
                        Unmapped Clause
                      </span>
                    )}
                  </div>

                  <p>{match ? match[2] : trimmed}</p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Extracted Rules */}
        <div className="rounded-2xl bg-slate-900/80 border border-slate-800 p-5 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              Extracted & Grounded Rules
            </h3>
            <span className="text-[11px] text-slate-500">
              {compileReport?.compiled_rules.length || 0} active rules
            </span>
          </div>

          {loading ? (
            <div className="py-24 flex flex-col items-center justify-center text-slate-400">
              <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-3" />
              <p className="text-xs">Compiling clauses with source grounding verification...</p>
            </div>
          ) : compileReport?.compiled_rules && compileReport.compiled_rules.length > 0 ? (
            <div className="space-y-3.5 max-h-[620px] overflow-y-auto pr-1">
              {compileReport.compiled_rules.map((rule: any) => {
                const conf = compileReport.rule_confidence[rule.id];
                const verbatim = rule.source?.verbatim_sentence || "";
                const isHighlighted = activeClauseId && docContent.includes(activeClauseId) && verbatim;

                return (
                  <div
                    key={rule.id}
                    className={`p-4 rounded-xl bg-slate-950/60 border transition-all ${
                      rule.effect === "ALLOW" ? "border-emerald-950/80" : "border-rose-950/80"
                    } hover:border-slate-700`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold font-mono ${
                              rule.effect === "ALLOW"
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                            }`}
                          >
                            {rule.effect}
                          </span>
                          <span className="font-mono text-xs text-white font-semibold">{rule.id}</span>
                        </div>
                        <p className="text-xs text-slate-300 mt-1 font-medium">{rule.name}</p>
                      </div>

                      {/* Confidence Pill */}
                      {conf && (
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            conf.confidence === "HIGH"
                              ? "bg-emerald-950 text-emerald-300 border border-emerald-800"
                              : "bg-amber-950 text-amber-300 border border-amber-800"
                          }`}
                        >
                          {conf.confidence} CONFIDENCE
                        </span>
                      )}
                    </div>

                    {/* Condition Tree Preview */}
                    <div className="mt-3 p-2.5 rounded-lg bg-slate-900 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto">
                      <div className="text-[10px] text-slate-500 uppercase font-semibold mb-1">
                        When Condition Tree:
                      </div>
                      <pre className="text-indigo-300">{JSON.stringify(rule.when, null, 2)}</pre>
                    </div>

                    {/* Grounding Source Quote */}
                    {verbatim && (
                      <div className="mt-2 text-[11px] text-slate-400 italic bg-slate-900/40 p-2 rounded border border-slate-800/40 flex items-start gap-1.5">
                        <ShieldCheck className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" />
                        <span>&ldquo;{verbatim}&rdquo;</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p-8 text-center text-xs text-slate-500">
              No rules extracted. Click &ldquo;Re-compile Document&rdquo; above.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
