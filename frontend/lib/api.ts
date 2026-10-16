/**
 * API client for the PolicyForge FastAPI backend (default: http://localhost:8000).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DefaultData {
  documents: Record<string, string>;
  rules_v1: any[];
  rules_v2: any[];
  sample_journeys: Array<{
    id: string;
    name: string;
    description: string;
    journey: Array<{
      event_type: string;
      day: number;
      payload?: Record<string, any>;
    }>;
  }>;
}

export interface CompileResponse {
  total_clauses: number;
  mapped_clauses: number;
  unmapped_clauses: Array<{
    id: string;
    text: string;
    doc_name: string;
    line_number: number;
  }>;
  compiled_rules: any[];
  rule_confidence: Record<
    string,
    {
      rule_id: string;
      grounded: boolean;
      lint_clean: boolean;
      confidence: "HIGH" | "MEDIUM" | "LOW";
      notes: string[];
    }
  >;
  rejected_rules: any[];
  lint_warnings: string[];
  token_usage: Record<string, any>;
  latency_ms: number;
  summary: string;
}

export interface SimulateResponse {
  outcomes: Array<{
    event_index: number;
    day: number;
    event_type: string;
    outcome: string;
    action_applied: boolean;
    resolution_type: string;
    findings: any[];
  }>;
  final_state: Record<string, any>;
  trace: {
    event_traces: Array<{
      event_index: number;
      day: number;
      event_type: string;
      is_decision_event: boolean;
      rules_evaluated: string[];
      rules_fired: string[];
      evaluations: any[];
      resolution_type: string;
      outcome: string;
      explanation: string;
    }>;
  };
  findings: any[];
}

export interface SuiteResponse {
  total_scenarios: number;
  passed_scenarios: number;
  failed_scenarios: number;
  total_findings: number;
  findings_count: number;
  findings: Array<{
    signature: [string, string[]];
    finding: {
      type: string;
      severity: string;
      rule_ids: string[];
      event_indices: number[];
      trace: string;
      details?: Record<string, any>;
    };
    shrink?: {
      original_journey: Array<{ event_type: string; day: number; payload?: any }>;
      minimal_journey: Array<{ event_type: string; day: number; payload?: any }>;
      original_length: number;
      minimal_length: number;
      engine_runs: number;
      reduction_pct: number;
    };
  }>;
  summary_table: string;
}

export interface DiffResponse {
  total_scenarios: number;
  changed_rule_ids: string[];
  outcomes_allow_to_deny: number;
  outcomes_deny_to_allow: number;
  outcome_changes: Array<{
    scenario_id: string;
    scenario_name: string;
    event_index: number;
    day: number;
    event_type: string;
    outcome_v1: string;
    outcome_v2: string;
    resolution_v1: string;
    resolution_v2: string;
    attributed_rule_ids: string[];
    explanation: string;
    needs_review: boolean;
  }>;
  finding_deltas: Array<{
    scenario_id: string;
    direction: "INTRODUCED" | "RESOLVED";
    finding: any;
  }>;
  scenarios_needing_review: string[];
  rule_text_diffs: Array<{
    rule_id: string;
    status: "ADDED" | "REMOVED" | "MODIFIED" | "UNCHANGED";
    v1_summary?: string;
    v2_summary?: string;
    changes: string[];
  }>;
  coverage_v1: {
    rule_coverage: number;
    rules_fired: number;
    rules_total: number;
    uncovered_rule_ids: string[];
    event_type_coverage: number;
    transitions_observed: number;
  };
  coverage_v2: {
    rule_coverage: number;
    rules_fired: number;
    rules_total: number;
    uncovered_rule_ids: string[];
    event_type_coverage: number;
    transitions_observed: number;
  };
  health_v1: {
    score: number;
    no_critical_findings: number;
    rule_coverage: number;
    no_gaps: number;
    no_ambiguities: number;
    event_coverage: number;
  };
  health_v2: {
    score: number;
    no_critical_findings: number;
    rule_coverage: number;
    no_gaps: number;
    no_ambiguities: number;
    event_coverage: number;
  };
  summary: string;
}

async function request<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  try {
    const res = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
      },
      ...options,
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(errData.detail || `Request failed with status ${res.status}`);
    }
    return (await res.json()) as T;
  } catch (err: any) {
    if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      throw new Error(`Unable to connect to PolicyForge backend at ${API_BASE}. Ensure the FastAPI server is running.`);
    }
    throw err;
  }
}

export const api = {
  getDefaultData: () => request<DefaultData>("/api/default-data"),

  compile: (params: {
    documents?: Record<string, string>;
    document_text?: string;
    doc_name?: string;
    use_mock?: boolean;
    max_repairs?: number;
  }) =>
    request<CompileResponse>("/api/compile", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  simulate: (params: {
    rules: any[];
    journey: Array<{ event_type: string; day: number; payload?: any }>;
    default_decision_outcome?: string;
  }) =>
    request<SimulateResponse>("/api/simulate", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  runSuite: (params: {
    rules: any[];
    suite_type?: "boundary" | "pairwise" | "custom";
    custom_scenarios?: any[];
    limit?: number;
  }) =>
    request<SuiteResponse>("/api/run-suite", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  shrink: (params: {
    rules: any[];
    journey: Array<{ event_type: string; day: number; payload?: any }>;
    target_finding_type?: string;
    target_rule_ids?: string[];
  }) =>
    request<any>("/api/shrink", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  diff: (params: {
    rules_v1: any[];
    rules_v2: any[];
    suite_type?: "boundary" | "pairwise" | "custom";
    limit?: number;
  }) =>
    request<DiffResponse>("/api/diff", {
      method: "POST",
      body: JSON.stringify(params),
    }),
};
