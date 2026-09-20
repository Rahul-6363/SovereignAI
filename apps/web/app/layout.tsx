import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meshcore — Sovereign Agentic AI Workbench",
  description:
    "Meshcore is an air-gapped AI workbench that reads your P&IDs and writes your engineering deliverables — on the plant's own GPU workstation.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-ink-900 font-sans text-zinc-200 antialiased">
        {children}
      </body>
    </html>
  );
}
