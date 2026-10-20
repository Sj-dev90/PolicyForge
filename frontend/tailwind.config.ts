import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  // Dark mode controlled via class on <html>
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Semantic tokens – resolved via CSS variables so light/dark swap is free
        bg:      "var(--color-bg)",
        surface: "var(--color-surface)",
        border:  "var(--color-border)",
        text:    "var(--color-text)",
        muted:   "var(--color-muted)",
        primary: "var(--color-primary)",
        allow:   "var(--color-allow)",
        "allow-bg": "var(--color-allow-bg)",
        deny:    "var(--color-deny)",
        "deny-bg":  "var(--color-deny-bg)",
        warning: "var(--color-warning)",
        "warning-bg": "var(--color-warning-bg)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        // 8px grid scale
        xs:  ["12px", { lineHeight: "16px" }],
        sm:  ["14px", { lineHeight: "20px" }],
        base:["16px", { lineHeight: "24px" }],
        lg:  ["20px", { lineHeight: "28px" }],
        xl:  ["24px", { lineHeight: "32px" }],
        "2xl": ["28px", { lineHeight: "36px" }],
      },
      borderRadius: {
        DEFAULT: "12px",
        sm: "6px",
        md: "8px",
        lg: "12px",
        xl: "16px",
        "2xl": "20px",
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(0 0 0 / 0.08), 0 1px 2px -1px rgb(0 0 0 / 0.06)",
        panel:"0 4px 12px -2px rgb(0 0 0 / 0.10)",
      },
      spacing: {
        // 8px grid
        "1": "8px",
        "2": "16px",
        "3": "24px",
        "4": "32px",
        "5": "40px",
        "6": "48px",
        "7": "56px",
        "8": "64px",
      },
      maxWidth: {
        page: "1120px",
      },
      transitionDuration: {
        fast: "150ms",
        base: "200ms",
        slow: "300ms",
      },
    },
  },
  plugins: [],
};

export default config;
