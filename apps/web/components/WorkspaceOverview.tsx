"use client";
/** Overview — the project dashboard and capability launcher.
 *
 *  Also the return path: after a P&ID task the user lands here and continues
 *  in the same project context.
 *
 *  The stats are buttons, not decoration. "18 entities" that you cannot click
 *  is a fact you have to act on somewhere else; the same number that opens
 *  Plant Memory is a navigation affordance that happens to also be a fact.
 */
import Link from "next/link";
import { useState } from "react";
import type { Project, WorkspaceView } from "@/lib/types";
import { Badge, Button, SectionLabel, Stat } from "./ui";
import {
  IconAlert,
  IconFile,
  IconGraph,
  IconMessage,
  IconSchematic,
  IconTable,
  IconUpload,
} from "./icons";
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
  const empty = (stats?.documents ?? 0) === 0;

  return (
    <div className="h-full overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-4xl">
        {/* ── heading ──────────────────────────────────────── */}
        <div className="mb-8">
          <div className="mb-2 flex flex-wrap items-center gap-2.5">
            <h1 className="text-[26px] font-medium tracking-tight text-zinc-100">
              {project?.name ?? "Workspace"}
            </h1>
            <Badge color="accent" dot>
              air-gapped
            </Badge>
          </div>
          <p className="max-w-2xl text-[14px] leading-relaxed text-zinc-500">
            {project?.description ||
              "Everything in this project — drawings, extracted plant memory, conversations and generated deliverables — stays on this workstation."}
          </p>
        </div>

        {/* ── first run: one obvious next step ─────────────── */}
        {empty && (
          <div className="mb-8 flex flex-wrap items-center gap-3 rounded-2xl border border-accent/30 bg-accent/[0.06] px-4 py-3.5">
            <IconUpload size={18} className="shrink-0 text-accent" />
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium text-zinc-100">
                This project has no drawings yet
              </div>
              <p className="text-[12px] text-zinc-500">
                Upload a P&amp;ID and Meshcore extracts its tags, connections
                and instruments into a queryable graph.
              </p>
            </div>
            <Button
              variant="primary"
              size="sm"
              icon={<IconSchematic size={14} />}
              onClick={() => onView("pid")}
            >
              Open P&amp;ID
            </Button>
          </div>
        )}

        {/* ── stats ────────────────────────────────────────── */}
        <div className="mb-8 grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-5">
          <Stat
            label="Drawings"
            value={stats?.documents ?? 0}
            icon={<IconFile size={13} />}
            onClick={() => onView("pid")}
          />
          <Stat
            label="Entities"
            value={stats?.entities ?? 0}
            icon={<IconGraph size={13} />}
            onClick={() => onView("memory")}
          />
          <Stat
            label="Links"
            value={stats?.relationships ?? 0}
            icon={<IconGraph size={13} />}
            onClick={() => onView("memory")}
          />
          <Stat
            label="Chats"
            value={conversationCount}
            icon={<IconMessage size={13} />}
            onClick={() => onView("chat")}
          />
          <Stat
            label="Deliverables"
            value={deliverableCount}
            icon={<IconTable size={13} />}
            onClick={() => onView("deliverables")}
          />
        </div>

        {/* ── capabilities ─────────────────────────────────── */}
        <section className="mb-8">
          <SectionLabel>Capabilities</SectionLabel>
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
                  // Honest boundary: not wired to the workspace yet.
                  setNotice(
                    `${cap?.name ?? id} is not connected to the workspace yet — ${
                      cap?.status === "phase1" ? "in progress" : "on the roadmap"
                    }. Everything marked Available works today.`,
                  );
                }
              }
            }}
          />
          {notice && (
            <p className="mt-2.5 flex items-start gap-1.5 text-[11px] leading-relaxed text-amber-300/90">
              <IconAlert size={13} className="mt-px shrink-0" />
              {notice}
            </p>
          )}
        </section>

        {/* ── status ───────────────────────────────────────── */}
        <section className="mb-8">
          <SectionLabel>Project status</SectionLabel>
          <ProductStatus />
        </section>

        {projects.length > 1 && (
          <p className="text-[11px] text-zinc-600">
            {projects.length} projects in this workspace ·{" "}
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
