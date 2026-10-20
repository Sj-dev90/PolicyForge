import { Variants } from "framer-motion";

// ─── Tab/page transitions: fade + 8px slide, ≤300ms ─────────────────────
export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease: "easeOut" } },
  exit:    { opacity: 0, y: -6, transition: { duration: 0.15, ease: "easeIn" } },
};

// ─── Cross-fade for right panel when selection changes ───────────────────
export const panelVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.18, ease: "easeOut" } },
  exit:    { opacity: 0, transition: { duration: 0.12 } },
};

// ─── Stagger container — 50ms between children ───────────────────────────
export const listContainer: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.05 } },
};

export const listItem: Variants = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.18, ease: "easeOut" } },
};

// ─── Timeline steps: appear left-to-right ────────────────────────────────
export const timelineContainer: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
};

export const timelineStep: Variants = {
  initial: { opacity: 0, x: -10 },
  animate: { opacity: 1, x: 0, transition: { duration: 0.2, ease: "easeOut" } },
};

// ─── Result badge flash ───────────────────────────────────────────────────
export const badgeVariants: Variants = {
  initial: { opacity: 0, scale: 0.9 },
  animate: { opacity: 1, scale: 1, transition: { duration: 0.2, ease: "easeOut" } },
};
