"use client";
/** Meshcore — main home workspace.
 *
 *  The single front door: one conversational composer, capability cards with
 *  P&ID as a first-class capability, recent projects and conversations, and
 *  an explicit product-status boundary.
 *
 *  Structured as a landing page rather than a dashboard, because that is what
 *  it is. The composer is the product, so it sits directly under the sentence
 *  explaining the product and above everything else; the cards below answer
 *  "what else can this do", which is the second question, not the first.
 */
import { useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ConversationRec, Project } from "@/lib/types";
import {
  AutoTextarea,
  Badge,
  Button,
  Card,
  SectionLabel,
  Select,
  cn,
} from "./ui";
import {
  IconAlert,
  IconArrowRight,
  IconArrowUp,
  IconGraph,
  IconMessage,
  IconSchematic,
  IconShieldCheck,
} from "./icons";
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
  "Prepare the complete deliverables package for this drawing",
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
        if (targetId) router.push(`/projects/${targetId}?view=pid&from=meshcore`);
        else
          pidRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
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
            cap?.status === "phase1" ? "in progress" : "on the roadmap"
          }. Everything marked Available works today.`,
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

      {/* ── top bar ──────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-ink-800 bg-ink-900/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center gap-2.5 px-6">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-accent text-sm font-bold text-white shadow-raised">
            M
          </span>
          <span className="text-[15px] font-semibold tracking-tight text-zinc-100">
            Meshcore
          </span>
          <Badge color={localOk === false ? "red" : "accent"} dot>
            {localOk === false ? "model offline" : "air-gapped"}
          </Badge>
          <div className="ml-auto flex items-center gap-2">
            <EgressCounter />
            <Button
              variant="outline"
              size="sm"
              icon={<IconShieldCheck size={14} />}
              onClick={() => setTrustOpen(true)}
            >
              Trust centre
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-5xl px-6 pb-16">
        {/* ── hero + composer ────────────────────────────── */}
        <section className="pb-12 pt-14">
          <h1 className="mb-4 max-w-2xl text-[38px] font-medium leading-[1.12] tracking-tight text-zinc-100">
            Turn a refinery&apos;s locked filing cabinet into an AI that writes
            your engineering deliverables.
          </h1>
          <p className="mb-8 max-w-xl text-[15px] leading-relaxed text-zinc-500">
            With the network cable unplugged, and an audit trail that proves
            nothing left the building.
          </p>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              startTask(prompt);
            }}
            className="rounded-2xl border border-ink-700 bg-ink-850 shadow-panel transition-colors focus-within:border-ink-600"
          >
            <AutoTextarea
              textareaRef={composerRef}
              value={prompt}
              onChange={setPrompt}
              ariaLabel="Describe the task"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  startTask(prompt);
                }
              }}
              minRows={2}
              maxRows={10}
              placeholder="Describe the task — e.g. draft a change note for CV-104 and check it against DOC-4412"
              className="w-full bg-transparent px-4 pb-1 pt-4 text-[15px] leading-6 text-zinc-100 placeholder-zinc-600 focus:outline-none"
            />
            <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
              {projects.length > 0 ? (
                <label className="flex items-center gap-1.5 text-[11px] text-zinc-600">
                  <span className="pl-1">run in</span>
                  <Select
                    value={targetId ?? ""}
                    onChange={(v) => setTargetId(Number(v))}
                    ariaLabel="Project to run the task in"
                    className="border-transparent bg-ink-900/70"
                    options={projects.map((p) => ({
                      value: p.id,
                      label: p.name,
                    }))}
                  />
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
                aria-label="Start this task"
                className="ml-auto grid h-8 w-8 place-items-center rounded-lg bg-accent text-white shadow-raised transition-colors hover:bg-accent-soft disabled:bg-ink-800 disabled:text-zinc-700"
              >
                <IconArrowUp size={16} />
              </button>
            </div>
          </form>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {TASK_STARTERS.map((s) => (
              <button
                key={s}
                onClick={() => {
                  setPrompt(s);
                  composerRef.current?.focus();
                }}
                className="rounded-full border border-ink-800 px-3 py-1.5 text-[11px] text-zinc-500 transition-colors hover:border-ink-600 hover:bg-ink-850 hover:text-zinc-300"
              >
                {s}
              </button>
            ))}
          </div>
          {notice && (
            <p className="mt-3 flex items-start gap-1.5 text-[11px] text-amber-300">
              <IconAlert size={13} className="mt-px shrink-0" />
              {notice}
            </p>
          )}
        </section>

        {/* ── P&ID entry: never duplicates the P&ID workflow ── */}
        <section ref={pidRef} className="mb-10 scroll-mt-20">
          <PidEntryCard projects={projects} />
        </section>

        {/* ── capabilities ───────────────────────────────── */}
        <section className="mb-10">
          <SectionLabel>Capabilities</SectionLabel>
          <CapabilityGrid onSelect={onCapability} columns={4} />
        </section>

        {/* ── recents ────────────────────────────────────── */}
        <section className="mb-10 grid gap-6 lg:grid-cols-2">
          <div>
            <SectionLabel
              action={
                <Link
                  href="/workspace"
                  className="text-[11px] text-zinc-600 underline-offset-2 hover:text-zinc-300 hover:underline"
                >
                  all projects
                </Link>
              }
            >
              Recent projects
            </SectionLabel>
            <ul className="space-y-1.5">
              {projects.slice(0, 5).map((p) => (
                <li key={p.id}>
                  <Card interactive className="px-3.5 py-3">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-zinc-100">
                        {p.name}
                      </span>
                      <span className="shrink-0 font-mono text-[10px] text-zinc-600">
                        {p.stats.documents} drawings · {p.stats.entities} tags
                      </span>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <QuickLink
                        href={`/projects/${p.id}?view=pid&from=meshcore`}
                        icon={<IconSchematic size={12} />}
                        accent
                      >
                        P&amp;ID
                      </QuickLink>
                      <QuickLink
                        href={`/projects/${p.id}?view=chat`}
                        icon={<IconMessage size={12} />}
                      >
                        Chat
                      </QuickLink>
                      <QuickLink
                        href={`/projects/${p.id}?view=memory`}
                        icon={<IconGraph size={12} />}
                      >
                        Memory
                      </QuickLink>
                    </div>
                  </Card>
                </li>
              ))}
              {projects.length === 0 && (
                <li className="rounded-2xl border border-dashed border-ink-800 p-4 text-[12px] leading-relaxed text-zinc-500">
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
            <SectionLabel>Recent conversations</SectionLabel>
            <ul className="space-y-1.5">
              {conversations.slice(0, 5).map((c) => (
                <li key={c.id}>
                  <Link
                    href={`/projects/${c.project_id}?view=chat&conversation=${c.id}`}
                    className="group flex items-center gap-3 rounded-2xl border border-ink-800 bg-ink-850 px-3.5 py-3 shadow-raised transition-colors hover:border-ink-700 hover:bg-ink-800/70"
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-ink-800 text-zinc-600">
                      <IconMessage size={14} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13px] text-zinc-200">
                        {c.title || "Untitled chat"}
                      </span>
                      <span className="block font-mono text-[10px] text-zinc-600">
                        {byId.get(c.project_id)?.name ??
                          `project ${c.project_id}`}{" "}
                        · {new Date(c.updated_at).toLocaleDateString()}
                      </span>
                    </span>
                    <IconArrowRight
                      size={14}
                      className="shrink-0 text-zinc-700 transition-colors group-hover:text-accent"
                    />
                  </Link>
                </li>
              ))}
              {conversations.length === 0 && (
                <li className="rounded-2xl border border-dashed border-ink-800 p-4 text-[12px] text-zinc-500">
                  No conversations yet. Ask something above to start one.
                </li>
              )}
            </ul>
          </div>
        </section>

        {/* ── product status boundary ────────────────────── */}
        <section className="mb-8">
          <SectionLabel>Project status</SectionLabel>
          <ProductStatus />
        </section>

        <footer className="border-t border-ink-800 pt-6 text-[11px] text-zinc-600">
          Meshcore runs entirely on the plant&apos;s own workstation — no
          external inference, no document egress.
        </footer>
      </div>
    </main>
  );
}

function QuickLink({
  href,
  icon,
  accent = false,
  children,
}: {
  href: string;
  icon: React.ReactNode;
  accent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] transition-colors",
        accent
          ? "border-accent/40 text-accent hover:bg-accent/10"
          : "border-ink-700 text-zinc-500 hover:border-ink-600 hover:text-zinc-200",
      )}
    >
      {icon}
      {children}
    </Link>
  );
}
