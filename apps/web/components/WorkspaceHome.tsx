"use client";
/** Meshcore — main home workspace (README §0.1, §7 Phase 0).
 *
 * The single front door: a Claude-like conversational composer, capability
 * cards with P&ID as a first-class capability, recent projects/conversations
 * and an explicit product-status boundary.
 */
import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ConversationRec, Project } from "@/lib/types";
import { AutoTextarea, Badge, Button } from "./ui";
import CapabilityGrid, { CAPABILITIES } from "./CapabilityGrid";
import PidEntryCard from "./PidEntryCard";
import ProductStatus from "./ProductStatus";
import EgressCounter from "./EgressCounter";
import TrustDrawer from "./TrustDrawer";

// A mix on purpose: two questions and two file requests, so the one composer
// visibly does both. The file ones name their format, because that is how the
// format gets chosen — there is no picker.
const TASK_STARTERS = [
  "Draft a PDF change note for replacing valve CV-104",
  "What protects line L-2201, and what is its design pressure?",
  "Generate an excel tracker of every instrument on sheet 3",
  "Does the relief valve setting comply with DOC-4412?",
];

export default function WorkspaceHome({
  projects,
  conversations,
}: {
  projects: Project[];
  conversations: ConversationRec[];
}) {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [targetId, setTargetId] = useState<number | null>(
    projects[0]?.id ?? null,
  );
  const [notice, setNotice] = useState("");
  const [trustOpen, setTrustOpen] = useState(false);
  const [localOk, setLocalOk] = useState<boolean | null>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const pidRef = useRef<HTMLDivElement>(null);

  const byId = useMemo(() => {
    const m = new Map<number, Project>();
    projects.forEach((p) => m.set(p.id, p));
    return m;
  }, [projects]);

  const startTask = (text: string) => {
    const q = text.trim();
    if (!q) return;
    if (!targetId) {
      setNotice("Create a project first — the agent needs a workspace to run in.");
      pidRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    router.push(`/projects/${targetId}?view=chat&q=${encodeURIComponent(q)}`);
  };

  const onCapability = (id: string) => {
    setNotice("");
    switch (id) {
      case "pid":
        if (targetId)
          router.push(`/projects/${targetId}?view=pid&from=meshcore`);
        else pidRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      case "agent":
        composerRef.current?.focus();
        return;
      case "memory":
        if (targetId) router.push(`/projects/${targetId}?view=memory`);
        else setNotice("Create a project first to open Plant Memory.");
        return;
      case "deliverables":
        if (targetId) router.push(`/projects/${targetId}?view=deliverables`);
        else setNotice("Create a project first to open Deliverables.");
        return;
      case "trust":
        setTrustOpen(true);
        return;
      default: {
        const cap = CAPABILITIES.find((c) => c.id === id);
        setNotice(
          `${cap?.name ?? id} is not connected to the workspace yet — ${
            cap?.status === "phase1" ? "Phase 1" : "Phase 2"
          } of the roadmap. The P&ID capability is complete and available now.`,
        );
      }
    }
  };

  return (
    <main className="min-h-screen">
      <TrustDrawer
        open={trustOpen}
        onClose={() => setTrustOpen(false)}
        onStatus={setLocalOk}
      />
      <div className="mx-auto max-w-5xl px-6 py-10">
        <header className="mb-10 flex flex-wrap items-center gap-3">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-white">
            M
          </span>
          <span className="text-lg font-semibold tracking-tight text-zinc-100">
            Meshcore
          </span>
          <Badge color={localOk === false ? "red" : "violet"}>air-gapped</Badge>
          <div className="ml-auto flex items-center gap-2">
            <EgressCounter />
            <Button variant="outline" onClick={() => setTrustOpen(true)}>
              Trust center
            </Button>
          </div>
        </header>

        {/* ── hero + composer ──────────────────────────────
            One centred block. The composer is the product's front door, so
            it sits directly under the sentence that explains it rather than
            below a row of cards competing for the same attention. */}
        <section className="mb-12 pt-4">
          <h1 className="mb-3 max-w-2xl text-[32px] font-medium leading-[1.2] tracking-tight text-zinc-100">
            Turn a refinery&apos;s locked filing cabinet into an AI that writes
            your engineering deliverables.
          </h1>
          <p className="mb-7 max-w-xl text-[15px] leading-relaxed text-zinc-500">
            With the network cable unplugged, and an audit trail that proves
            nothing left the building.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              startTask(prompt);
            }}
            className="rounded-2xl border border-ink-700 bg-ink-850 shadow-lg transition-colors focus-within:border-ink-600"
          >
            <AutoTextarea
              textareaRef={composerRef}
              value={prompt}
              onChange={setPrompt}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  startTask(prompt);
                }
              }}
              minRows={2}
              maxRows={10}
              placeholder="Describe the task — e.g. draft a change note for CV-104 and check it against DOC-4412"
              className="w-full bg-transparent px-4 pb-1 pt-3.5 text-[15px] leading-6 text-zinc-100 placeholder-zinc-600 focus:outline-none"
            />
            <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
              {projects.length > 0 ? (
                <label className="flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <span className="pl-1">in</span>
                  <select
                    value={targetId ?? ""}
                    onChange={(e) => setTargetId(Number(e.target.value))}
                    className="rounded-md bg-ink-900/70 px-2 py-1 text-[11px] text-zinc-300 focus:outline-none"
                  >
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : (
                <span className="pl-1 text-[11px] text-amber-300/90">
                  no project yet — create one below
                </span>
              )}
              <button
                type="submit"
                disabled={!prompt.trim()}
                title="Start this task"
                className="ml-auto grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-semibold text-white transition-colors hover:bg-accent-soft disabled:bg-ink-700 disabled:text-zinc-600"
              >
                ↑
              </button>
            </div>
          </form>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {TASK_STARTERS.map((s) => (
              <button
                key={s}
                onClick={() => setPrompt(s)}
                className="rounded-full border border-ink-800 px-3 py-1.5 text-[11px] text-zinc-500 transition-colors hover:border-ink-600 hover:bg-ink-850 hover:text-zinc-300"
              >
                {s}
              </button>
            ))}
          </div>
          {notice && <p className="mt-2 text-[11px] text-amber-300">{notice}</p>}
        </section>

        {/* ── P&ID entry card: never duplicates the P&ID workflow ── */}
        <section ref={pidRef} className="mb-8 scroll-mt-6">
          <PidEntryCard projects={projects} />
        </section>

        {/* ── capabilities ─────────────────────────────────── */}
        <section className="mb-8">
          <div className="mb-2.5 flex items-center gap-2">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
              Capabilities
            </h2>
            <span className="text-[11px] text-zinc-600">
              P&amp;ID opens the completed module
            </span>
          </div>
          <CapabilityGrid onSelect={onCapability} columns={4} />
        </section>
        {/* ── recents ──────────────────────────────────────── */}
        <section className="mb-8 grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-500">
                Recent projects
              </h2>
              <Link
                href="/workspace"
                className="ml-auto text-[11px] text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
              >
                all projects →
              </Link>
            </div>
            <ul className="space-y-1.5">
              {projects.slice(0, 5).map((p) => (
                <li
                  key={p.id}
                  className="rounded-xl border border-ink-700 bg-ink-850 px-3 py-2.5"
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm text-zinc-100">
                      {p.name}
                    </span>
                    <span className="shrink-0 font-mono text-[10px] text-zinc-500">
                      {p.stats.documents}docs · {p.stats.entities}ents
                    </span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-1.5 text-[11px]">
                    <Link
                      href={`/projects/${p.id}?view=pid&from=meshcore`}
                      className="rounded-md border border-accent/50 px-1.5 py-0.5 text-accent transition-colors hover:bg-accent/10"
                    >
                      P&amp;ID
                    </Link>
                    <Link
                      href={`/projects/${p.id}?view=chat`}
                      className="rounded-md border border-ink-600 px-1.5 py-0.5 text-zinc-400 transition-colors hover:text-zinc-200"
                    >
                      Agent chat
                    </Link>
                    <Link
                      href={`/projects/${p.id}?view=memory`}
                      className="rounded-md border border-ink-600 px-1.5 py-0.5 text-zinc-400 transition-colors hover:text-zinc-200"
                    >
                      Plant Memory
                    </Link>
                  </div>
                </li>
              ))}
              {projects.length === 0 && (
                <li className="rounded-xl border border-ink-700 bg-ink-850 p-3 text-xs text-zinc-500">
                  No projects yet. Use the P&amp;ID card above, or{" "}
                  <Link
                    href="/workspace"
                    className="text-accent underline-offset-2 hover:underline"
                  >
                    create one
                  </Link>
                  .
                </li>
              )}
            </ul>
          </div>

          <div>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-zinc-500">
              Recent conversations
            </h2>
            <ul className="space-y-1.5">
              {conversations.slice(0, 5).map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/projects/${c.project_id}?view=chat&conversation=${c.id}`}
                    className="block rounded-xl border border-ink-700 bg-ink-850 px-3 py-2.5 transition-colors hover:border-ink-600"
                  >
                    <div className="truncate text-sm text-zinc-200">
                      {c.title || "Untitled chat"}
                    </div>
                    <div className="font-mono text-[10px] text-zinc-500">
                      {byId.get(c.project_id)?.name ?? `project ${c.project_id}`}{" "}
                      · {new Date(c.updated_at).toLocaleString()}
                    </div>
                  </Link>
                </li>
              ))}
              {conversations.length === 0 && (
                <li className="rounded-xl border border-ink-700 bg-ink-850 p-3 text-xs text-zinc-500">
                  No conversations yet. Ask a question to start one.
                </li>
              )}
            </ul>
          </div>
        </section>

        {/* ── product status boundary ──────────────────────── */}
        <section className="mb-6">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-zinc-500">
            Project status
          </h2>
          <ProductStatus />
        </section>

        <footer className="pb-6 text-[11px] text-zinc-600">
          Meshcore runs entirely on the plant&apos;s own GPU workstation — no
          external inference, no document egress.
        </footer>
      </div>
    </main>
  );
}
