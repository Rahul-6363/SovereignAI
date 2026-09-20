"use client";
/** Overview tab — the Meshcore capability launcher inside a project.
 *
 * Also the return path: after a P&ID task the user lands here and continues in
 * the same project context (README §0.1 "Return path").
 */
import Link from "next/link";
import { useState } from "react";
import type { Project, WorkspaceView } from "@/lib/types";
import { Badge } from "./ui";
import CapabilityGrid, { CAPABILITIES } from "./CapabilityGrid";
import ProductStatus from "./ProductStatus";

export default function WorkspaceOverview({
  project,
  projects,
  onView,
  onOpenTrust,
  deliverableCount,
  conversationCount,
}: {
  project: Project | undefined;
  projects: Project[];
  onView: (v: WorkspaceView) => void;
  onOpenTrust: () => void;
  deliverableCount: number;
  conversationCount: number;
}) {
  const stats = project?.stats;
  const [notice, setNotice] = useState("");

  return (
    <div className="h-full overflow-y-auto px-6 py-6">
      <div className="mx-auto max-w-4xl">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <h1 className="text-lg font-semibold text-zinc-100">
            {project?.name ?? "Workspace"}
          </h1>
          <Badge color="violet">Meshcore workspace</Badge>
          {project?.description && (
            <span className="text-xs text-zinc-500">{project.description}</span>
          )}
          <Link
            href="/"
            className="ml-auto text-[11px] text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
          >
            ← Meshcore home
          </Link>
        </div>
        <p className="mb-5 text-xs leading-relaxed text-zinc-500">
          P&amp;ID is a first-class capability of this workspace. Selecting it
          opens the completed P&amp;ID upload, extraction, review and result
          flow — the same module, not a second implementation.
        </p>

        <div className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-5">
          {[
            ["Drawings", stats?.documents ?? 0],
            ["Entities", stats?.entities ?? 0],
            ["Links", stats?.relationships ?? 0],
            ["Conversations", conversationCount],
            ["Deliverables", deliverableCount],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="rounded-xl border border-ink-700 bg-ink-850 px-3 py-2"
            >
              <div className="font-mono text-lg text-zinc-100">{value}</div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-500">
                {label}
              </div>
            </div>
          ))}
        </div>

        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Capabilities
        </h2>
        <CapabilityGrid
          columns={4}
          onSelect={(id) => {
            setNotice("");
            switch (id) {
              case "pid":
                onView("pid");
                return;
              case "agent":
                onView("chat");
                return;
              case "memory":
                onView("memory");
                return;
              case "deliverables":
                onView("deliverables");
                return;
              case "trust":
                onOpenTrust();
                return;
              default: {
                const cap = CAPABILITIES.find((c) => c.id === id);
                // Honest boundary: not wired to the workspace yet (README §7).
                setNotice(
                  `${cap?.name ?? id} is not connected to the workspace yet — ${
                    cap?.status === "phase1" ? "Phase 1" : "Phase 2"
                  } of the roadmap. The P&ID capability is complete and available now.`,
                );
              }
            }
          }}
        />
        {notice && <p className="mt-2 text-[11px] text-amber-300">{notice}</p>}

        <h2 className="mb-2 mt-6 text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Project status
        </h2>
        <ProductStatus />

        {projects.length > 1 && (
          <p className="mt-5 text-[11px] text-zinc-600">
            {projects.length} projects in this workspace instance ·{" "}
            <Link
              href="/workspace"
              className="text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
            >
              switch project
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}