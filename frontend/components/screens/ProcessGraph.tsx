"use client";

import React, { useState } from "react";
import {
  Workflow,
  Package,
  Truck,
  RotateCcw,
  RefreshCw,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  HelpCircle,
  ArrowRight,
  Info,
} from "lucide-react";
import { DefaultData } from "@/lib/api";

interface ProcessGraphProps {
  defaultData: DefaultData | null;
}

export function ProcessGraph({ defaultData }: ProcessGraphProps) {
  const [selectedNode, setSelectedNode] = useState<string>("refund_branch");

  const nodesInfo: Record<
    string,
    {
      title: string;
      category: string;
      description: string;
      rules: string[];
      stateFields: string[];
      invariants: string[];
    }
  > = {
    order_placed: {
      title: "1. Order Placed",
      category: "Intake",
      description: "Initial purchase event. Sets order_placed=True and order_day. Delivery has not yet occurred.",
      rules: ["None (Non-decision event)"],
      stateFields: ["order_placed", "order_day", "amount_paid"],
      invariants: ["order_placed is prerequisite for downstream fulfillment."],
    },
    delivered: {
      title: "2. Item Delivered",
      category: "Fulfillment Baseline",
      description: "Physical item received by customer. Starts the delivery clock: days_since_delivery = current_day - delivery_day.",
      rules: ["Establishes baseline delivery_day"],
      stateFields: ["item_delivered", "delivery_day", "days_since_delivery"],
      invariants: ["delivery_day >= order_day; days_since_delivery >= 0"],
    },
    refund_branch: {
      title: "3A. Refund Decision Branch",
      category: "Decision Event",
      description: "Customer initiates REFUND_REQUESTED. Evaluates standard 30d window, VIP 60d window, final sale exclusion, and opened item limits.",
      rules: [
        "rule_refund_standard_window (p=0, ALLOW <=30d)",
        "rule_refund_past_deadline (p=0, DENY >30d)",
        "rule_refund_vip_extended_window (p=2, ALLOW <=60d)",
        "rule_refund_final_sale_deny (p=10, overrides standard)",
        "rule_refund_before_delivery_deny (p=5, DENY if undelivered)",
        "rule_refund_after_replacement_cancelled (p=0, ALLOW)",
      ],
      stateFields: ["refund_requested", "refund_request_day", "days_since_delivery", "is_final_sale", "customer_tier"],
      invariants: ["refund_amount <= amount_paid; no chargeback while refund active"],
    },
    replacement_branch: {
      title: "3B. Replacement Decision Branch",
      category: "Decision Event",
      description: "Customer initiates REPLACEMENT_REQUESTED. Evaluates standard 30d window, 45d transit damage extension, and duplicate active request limits.",
      rules: [
        "rule_replacement_standard_window (p=0, ALLOW <=30d)",
        "rule_replacement_past_deadline (p=0, DENY >30d)",
        "rule_replacement_damaged_override (p=5, overrides past_deadline)",
        "rule_replacement_final_sale_deny (p=10, overrides standard)",
        "rule_replacement_duplicate_request_deny (p=10, DENY if active)",
      ],
      stateFields: ["replacement_requested", "replacement_active", "item_damaged", "days_since_delivery"],
      invariants: ["Cannot have both replacement_active and replacement_cancelled"],
    },
    resolution_engine: {
      title: "4. Deterministic Conflict Resolution",
      category: "PolicyForge Engine",
      description: "Deterministic conflict resolution: Explicit overrides take precedence; otherwise higher priority wins. Ties produce structured CONTRADICTION or AMBIGUITY findings.",
      rules: ["Conflict Resolution Protocol (10 deterministic branches)"],
      stateFields: ["action_denied"],
      invariants: ["Never execute eval/exec; pure functional AST traversal"],
    },
    terminal_allow: {
      title: "5A. Action Approved (ALLOW)",
      category: "Terminal Outcome",
      description: "Decision passes all policy checks. Monetary disbursement scheduled or replacement item dispatched.",
      rules: ["State updates applied (e.g. refund_eligibility_restored)"],
      stateFields: ["refund_requested=True or replacement_active=True"],
      invariants: ["Full refund + completed replacement cannot co-exist without explicit return"],
    },
    terminal_deny: {
      title: "5B. Action Denied (DENY)",
      category: "Terminal Outcome",
      description: "Decision blocked by policy rule or gap. Action does NOT take effect; state remains un-mutated, action_denied=True.",
      rules: ["Denial semantics strictly preserve pre-decision state"],
      stateFields: ["action_denied=True"],
      invariants: ["Zero state leakage upon denial"],
    },
  };

  const currentInfo = nodesInfo[selectedNode] || nodesInfo.refund_branch;

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800">
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <Workflow className="w-5 h-5 text-indigo-400" />
          Interactive Policy Process Graph
        </h1>
        <p className="text-xs text-slate-400 mt-1">
          Visual architecture of the NovaCart customer order lifecycle, decision nodes, conflict resolution stages, and invariant guardrails.
        </p>
      </div>

      {/* Main Process Diagram Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Diagram Nodes Canvas (Col 1 & 2) */}
        <div className="lg:col-span-2 p-6 rounded-2xl bg-slate-900/80 border border-slate-800 space-y-6">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
            <span>Lifecycle Pipeline Nodes</span>
            <span className="text-[10px] text-slate-500">Click any node to inspect rules & state</span>
          </div>

          <div className="space-y-4">
            {/* Step 1 & 2: Intake */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                onClick={() => setSelectedNode("order_placed")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "order_placed"
                    ? "bg-indigo-950/80 border-indigo-500 shadow-lg shadow-indigo-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-bold mb-1">
                  <Package className="w-4 h-4 text-indigo-400" />
                  ORDER_PLACED
                </div>
                <div className="text-xs text-slate-300 font-medium">1. Order Placement</div>
                <div className="text-[10px] text-slate-500 mt-1">amount_paid, customer_tier</div>
              </button>

              <button
                onClick={() => setSelectedNode("delivered")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "delivered"
                    ? "bg-indigo-950/80 border-indigo-500 shadow-lg shadow-indigo-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-bold mb-1">
                  <Truck className="w-4 h-4 text-indigo-400" />
                  ITEM_DELIVERED
                </div>
                <div className="text-xs text-slate-300 font-medium">2. Fulfillment Delivery</div>
                <div className="text-[10px] text-slate-500 mt-1">starts days_since_delivery clock</div>
              </button>
            </div>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center text-slate-600">
              <span className="text-xs font-mono">↓ Customer Initiates Restitution / Exchange</span>
            </div>

            {/* Step 3: Decision Branches */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <button
                onClick={() => setSelectedNode("refund_branch")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "refund_branch"
                    ? "bg-indigo-950/80 border-indigo-500 shadow-lg shadow-indigo-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-bold mb-1">
                  <RotateCcw className="w-4 h-4 text-cyan-400" />
                  REFUND_REQUESTED
                </div>
                <div className="text-xs text-slate-200 font-bold">3A. Refund Decision Logic</div>
                <div className="text-[10px] text-slate-400 mt-1.5 space-y-0.5">
                  <div>• Standard 30d (VIP 60d)</div>
                  <div>• Final sale strict deny</div>
                  <div>• Opened item 14d limit</div>
                </div>
              </button>

              <button
                onClick={() => setSelectedNode("replacement_branch")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "replacement_branch"
                    ? "bg-indigo-950/80 border-indigo-500 shadow-lg shadow-indigo-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-bold mb-1">
                  <RefreshCw className="w-4 h-4 text-emerald-400" />
                  REPLACEMENT_REQUESTED
                </div>
                <div className="text-xs text-slate-200 font-bold">3B. Replacement Decision Logic</div>
                <div className="text-[10px] text-slate-400 mt-1.5 space-y-0.5">
                  <div>• Standard 30d window</div>
                  <div>• Damaged item 45d extension</div>
                  <div>• Duplicate active request deny</div>
                </div>
              </button>
            </div>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center text-slate-600">
              <span className="text-xs font-mono">↓ Evaluation & Precedence Arbitration</span>
            </div>

            {/* Step 4: Conflict Resolution Engine */}
            <button
              onClick={() => setSelectedNode("resolution_engine")}
              className={`w-full p-4 rounded-xl border text-left transition-all ${
                selectedNode === "resolution_engine"
                  ? "bg-indigo-950/80 border-indigo-500 shadow-lg shadow-indigo-600/20"
                  : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
              }`}
            >
              <div className="flex items-center gap-2 text-indigo-300 font-mono text-xs font-bold mb-1">
                <ShieldCheck className="w-4 h-4 text-indigo-400" />
                DETERMINISTIC CONFLICT RESOLUTION
              </div>
              <div className="text-xs text-slate-200 font-bold">4. PolicyForge Rule Engine</div>
              <div className="text-[11px] text-slate-400 mt-1">
                Evaluates overrides, priorities, and flags CONTRADICTION or POLICY_GAP if unresolved.
              </div>
            </button>

            {/* Downward Connector Arrow */}
            <div className="flex justify-center text-slate-600">
              <span className="text-xs font-mono">↓ Final Verdict</span>
            </div>

            {/* Step 5: Terminal States */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <button
                onClick={() => setSelectedNode("terminal_allow")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "terminal_allow"
                    ? "bg-emerald-950/80 border-emerald-500 shadow-lg shadow-emerald-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-emerald-400 font-mono text-xs font-bold mb-1">
                  <CheckCircle2 className="w-4 h-4" />
                  ALLOW (Approved)
                </div>
                <div className="text-[11px] text-slate-300">
                  Action takes effect; refund disbursed or replacement dispatched.
                </div>
              </button>

              <button
                onClick={() => setSelectedNode("terminal_deny")}
                className={`p-4 rounded-xl border text-left transition-all ${
                  selectedNode === "terminal_deny"
                    ? "bg-rose-950/80 border-rose-500 shadow-lg shadow-rose-600/20"
                    : "bg-slate-950/60 border-slate-800 hover:border-slate-700"
                }`}
              >
                <div className="flex items-center gap-2 text-rose-400 font-mono text-xs font-bold mb-1">
                  <XCircle className="w-4 h-4" />
                  DENY (Rejected)
                </div>
                <div className="text-[11px] text-slate-300">
                  Zero state mutation; action_denied flag recorded.
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* Node Inspector Panel (Col 3) */}
        <div className="p-6 rounded-2xl bg-slate-900/90 border border-slate-800 space-y-5">
          <div className="pb-3 border-b border-slate-800">
            <span className="text-[10px] font-bold text-indigo-400 uppercase tracking-wider font-mono">
              {currentInfo.category}
            </span>
            <h3 className="text-base font-bold text-white mt-0.5">{currentInfo.title}</h3>
          </div>

          <p className="text-xs text-slate-300 leading-relaxed bg-slate-950 p-3 rounded-xl border border-slate-800">
            {currentInfo.description}
          </p>

          {/* Associated Rules */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Enforced Policy Rules
            </h4>
            <div className="space-y-1.5 max-h-48 overflow-y-auto">
              {currentInfo.rules.map((r, i) => (
                <div
                  key={i}
                  className="p-2 rounded bg-slate-950 border border-slate-800 text-[11px] font-mono text-indigo-300"
                >
                  {r}
                </div>
              ))}
            </div>
          </div>

          {/* State Fields */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              State Fields Mutated / Inspected
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {currentInfo.stateFields.map((f, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-950 text-slate-300 border border-slate-800"
                >
                  {f}
                </span>
              ))}
            </div>
          </div>

          {/* Invariants Enforced */}
          <div className="space-y-2">
            <h4 className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Safety Invariants Enforced
            </h4>
            <div className="space-y-1.5 text-xs text-slate-400">
              {currentInfo.invariants.map((inv, i) => (
                <div key={i} className="flex items-start gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0 mt-0.5" />
                  <span>{inv}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
