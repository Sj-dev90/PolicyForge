import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PolicyForge | CI/CD for Business Policies",
  description: "Natural-language policy to structured rules, deterministic simulation, stress testing, and behavioral diffing.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#090d16] text-slate-100 antialiased selection:bg-indigo-500/30 selection:text-indigo-200">
        {children}
      </body>
    </html>
  );
}
