import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PolicyForge",
  description: "Find problems in business policies before they hit customers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // `class` is toggled by JS in page.tsx via useEffect; starting without "dark"
    // lets the prefers-color-scheme media query in CSS apply as default.
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
