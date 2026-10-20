"use client";
import { DefaultData } from "@/lib/api";

interface WhatIfScreenProps { defaultData: DefaultData | null; }

export function WhatIfScreen({ defaultData: _ }: WhatIfScreenProps) {
  return (
    <div className="bg-surface rounded-xl border border-border p-6 shadow-card">
      <h1 className="text-2xl font-bold text-text">What-if explorer</h1>
      <p className="text-muted mt-2">
        Compare two versions of the policy to see which customer journeys change outcome.
        Coming in Stage B.
      </p>
    </div>
  );
}
