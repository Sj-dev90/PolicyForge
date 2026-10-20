"use client";
import { DefaultData } from "@/lib/api";

interface PoliciesScreenProps { defaultData: DefaultData | null; }

export function PoliciesScreen({ defaultData }: PoliciesScreenProps) {
  const rules = defaultData?.rules_v1 ?? [];
  return (
    <div className="space-y-5">
      <div className="bg-surface rounded-xl border border-border p-6 shadow-card">
        <h1 className="text-2xl font-bold text-text">Policies</h1>
        <p className="text-muted mt-1">
          {rules.length} rules loaded from NovaCart's refund and replacement policy.
        </p>
      </div>
      <div className="space-y-3">
        {rules.map((rule: any) => (
          <div key={rule.id} className="bg-surface rounded-xl border border-border p-5 shadow-card">
            <div className="flex items-center justify-between gap-4 mb-2">
              <h3 className="text-base font-semibold text-text">{rule.name}</h3>
              <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${
                rule.effect === "ALLOW"
                  ? "bg-allow-bg text-allow border-allow/30"
                  : "bg-deny-bg text-deny border-deny/30"
              }`}>
                {rule.effect === "ALLOW" ? "Allows" : "Denies"}
              </span>
            </div>
            {rule.source?.verbatim_sentence && (
              <blockquote className="border-l-2 border-border pl-3 text-sm text-muted italic">
                &ldquo;{rule.source.verbatim_sentence}&rdquo;
              </blockquote>
            )}
            <p className="text-xs text-muted font-mono mt-2">{rule.id}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
