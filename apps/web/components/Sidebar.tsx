"use client";
/** Left rail: brand, primary action, view navigation, project switcher,
 *  files and status.
 *
 *  Navigation lives here and only here. It used to be duplicated — a nav list
 *  in this rail AND a tab strip in the workspace header — which was not just
 *  redundant but actively broken: the rail's entries were `<Link href>`, so
 *  using them did a full page navigation and discarded the mounted chat pane
 *  along with any answer still streaming into it. These are buttons that
 *  switch the view in place, and the header is now contextual to whichever
 *  view is open.
 *
 *  The rail collapses to a 60px icon strip. On a 13" laptop the P&ID viewer
 *  and the drawing inspector are both fighting for the same horizontal space,
 *  and 200px back is the difference between reading a tag and guessing at it.
 */
import { useEffect, useState } from "react";
import Link from "next/link";
import type { DocumentRec, IngestionStatus, Project, WorkspaceView } from "@/lib/types";
import {
  Badge,
  Button,
  IconButton,
  Menu,
  SectionLabel,
  Tooltip,
  cn,
} from "./ui";
import {
  IconChevronDown,
  IconFile,
  IconGraph,
  IconHome,
  IconMessage,
  IconPanelLeft,
  IconPlus,
  IconSchematic,
  IconShieldCheck,
  IconTable,
} from "./icons";
import UploadIngest from "./UploadIngest";

const COLLAPSE_KEY = "meshcore.sidebar.collapsed";

const NAV: {
  id: WorkspaceView;
  label: string;
  icon: (p: { size?: number }) => React.ReactElement;
}[] = [
  { id: "overview", label: "Overview", icon: IconHome },
  { id: "chat", label: "Agent chat", icon: IconMessage },
  { id: "pid", label: "P&ID", icon: IconSchematic },
  { id: "memory", label: "Plant Memory", icon: IconGraph },
  { id: "deliverables", label: "Deliverables", icon: IconTable },
];

export default function Sidebar({
  projects,
  projectId,
  view,
  onView,
  docs,
  activeDocId,
  onSelectDoc,
  onIngested,
  onDocDeleted,
  onOpenTrust,
  onNewChat,
  localOk,
  counts,
}: {
  projects: Project[];
  projectId: number;
  view: WorkspaceView;
  onView: (v: WorkspaceView) => void;
  docs: DocumentRec[];
  activeDocId: number | null;
  onSelectDoc: (d: DocumentRec) => void;
  onIngested: (docId: number, status: IngestionStatus) => void;
  onDocDeleted: (docId: number) => void;
  onOpenTrust: () => void;
  onNewChat: () => void;
  localOk: boolean | null;
  counts: { conversations: number; deliverables: number };
}) {
  const [collapsed, setCollapsed] = useState(false);
  const project = projects.find((p) => p.id === projectId);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1");
    } catch {
      /* storage blocked — expanded is the right default */
    }
  }, []);

  const toggle = () => {
    setCollapsed((v) => {
      const next = !v;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {
        /* non-fatal */
      }
      return next;
    });
  };

  const badgeFor = (id: WorkspaceView): number | null => {
    if (id === "pid") return docs.length || null;
    if (id === "deliverables") return counts.deliverables || null;
    if (id === "chat") return counts.conversations || null;
    if (id === "memory") return project?.stats.entities || null;
    return null;
  };

  return (
    <aside
      className={cn(
        "flex h-full shrink-0 flex-col border-r border-ink-800 bg-ink-975 transition-[width] duration-200",
        collapsed ? "w-[60px]" : "w-[252px]",
      )}
    >
      {/* ── brand ─────────────────────────────────────────── */}
      <div
        className={cn(
          "flex h-14 items-center gap-2 border-b border-ink-800",
          collapsed ? "justify-center px-2" : "px-3",
        )}
      >
        <Link
          href="/"
          title="Meshcore home"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-accent text-sm font-bold text-white shadow-raised"
        >
          M
        </Link>
        {!collapsed && (
          <>
            <span className="truncate text-sm font-semibold tracking-tight text-zinc-100">
              Meshcore
            </span>
            <IconButton
              icon={<IconPanelLeft size={16} />}
              label="Collapse sidebar"
              size="sm"
              onClick={toggle}
              className="ml-auto"
            />
          </>
        )}
      </div>

      {collapsed && (
        <div className="flex justify-center border-b border-ink-800 py-2">
          <IconButton
            icon={<IconPanelLeft size={16} />}
            label="Expand sidebar"
            size="sm"
            onClick={toggle}
          />
        </div>
      )}

      {/* ── primary action ────────────────────────────────── */}
      <div className={cn("pt-3", collapsed ? "px-2" : "px-3")}>
        {collapsed ? (
          <IconButton
            icon={<IconPlus size={17} />}
            label="New chat"
            variant="primary"
            onClick={() => {
              onNewChat();
              onView("chat");
            }}
            className="mx-auto"
          />
        ) : (
          <Button
            variant="primary"
            full
            icon={<IconPlus size={16} />}
            onClick={() => {
              onNewChat();
              onView("chat");
            }}
          >
            New chat
          </Button>
        )}
      </div>

      {/* ── views ─────────────────────────────────────────── */}
      <nav className={cn("pt-3", collapsed ? "px-2" : "px-3")}>
        {!collapsed && <SectionLabel className="px-1">Workspace</SectionLabel>}
        <ul className="space-y-0.5">
          {NAV.map(({ id, label, icon: Icon }) => {
            const active = view === id;
            const count = badgeFor(id);
            const button = (
              <button
                onClick={() => onView(id)}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-xl text-[13px] font-medium transition-colors",
                  collapsed ? "h-9 justify-center" : "h-9 px-2.5",
                  active
                    ? "bg-ink-850 text-zinc-100"
                    : "text-zinc-500 hover:bg-ink-900 hover:text-zinc-200",
                )}
              >
                <Icon size={16} />
                {!collapsed && (
                  <>
                    <span className="min-w-0 flex-1 truncate text-left">
                      {label}
                    </span>
                    {count !== null && (
                      <span className="shrink-0 font-mono text-[10px] text-zinc-600">
                        {count}
                      </span>
                    )}
                  </>
                )}
              </button>
            );
            return (
              <li key={id}>
                {collapsed ? (
                  <Tooltip label={label} side="right" className="w-full">
                    {button}
                  </Tooltip>
                ) : (
                  button
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      {/* ── project switcher ──────────────────────────────── */}
      {!collapsed && (
        <div className="px-3 pt-4">
          <SectionLabel className="px-1">Project</SectionLabel>
          <Menu
            align="left"
            trigger={({ open, toggle: t }) => (
              <button
                onClick={t}
                aria-expanded={open}
                className="flex w-full items-center gap-2 rounded-xl border border-ink-800 bg-ink-900 px-2.5 py-2 text-left transition-colors hover:border-ink-700"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-zinc-100">
                    {project?.name ?? `Project ${projectId}`}
                  </span>
                  <span className="block font-mono text-[10px] text-zinc-600">
                    {project?.stats.documents ?? 0} drawings ·{" "}
                    {project?.stats.entities ?? 0} tags
                  </span>
                </span>
                <IconChevronDown size={14} className="shrink-0 text-zinc-600" />
              </button>
            )}
            items={[
              ...projects
                .filter((p) => p.id !== projectId)
                .slice(0, 8)
                .map((p) => ({
                  label: p.name,
                  onSelect: () => {
                    window.location.href = `/projects/${p.id}`;
                  },
                })),
              {
                label: "All projects…",
                icon: <IconHome size={14} />,
                onSelect: () => {
                  window.location.href = "/workspace";
                },
              },
            ]}
          />
        </div>
      )}

      {/* ── files ─────────────────────────────────────────── */}
      {!collapsed && (
        <div className="mt-4 flex min-h-0 flex-1 flex-col px-3">
          <SectionLabel
            className="px-1"
            action={
              docs.length > 0 ? (
                <span className="font-mono text-[10px] text-zinc-600">
                  {docs.length}
                </span>
              ) : undefined
            }
          >
            Files
          </SectionLabel>
          <UploadIngest
            projectId={projectId}
            docs={docs}
            activeDocId={activeDocId}
            onSelectDoc={(d) => {
              onSelectDoc(d);
              onView("pid");
            }}
            onIngested={onIngested}
            onDocDeleted={onDocDeleted}
          />
        </div>
      )}
      {collapsed && <div className="flex-1" />}

      {/* ── status ────────────────────────────────────────── */}
      <div
        className={cn(
          "border-t border-ink-800",
          collapsed ? "flex justify-center px-2 py-3" : "px-3 py-3",
        )}
      >
        {collapsed ? (
          <IconButton
            icon={<IconShieldCheck size={16} />}
            label="Trust centre"
            size="sm"
            onClick={onOpenTrust}
            className={localOk === false ? "text-rose-400" : "text-emerald-400"}
          />
        ) : (
          <button
            onClick={onOpenTrust}
            className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left transition-colors hover:bg-ink-900"
          >
            <IconShieldCheck
              size={16}
              className={localOk === false ? "text-rose-400" : "text-emerald-400"}
            />
            <span className="min-w-0 flex-1">
              <span className="block text-[12px] font-medium text-zinc-300">
                Trust centre
              </span>
              <span className="block text-[10px] text-zinc-600">
                {localOk === false
                  ? "Model offline"
                  : "Air-gapped · audit chain"}
              </span>
            </span>
            <Badge color={localOk === false ? "red" : "green"} dot>
              {localOk === false ? "off" : "local"}
            </Badge>
          </button>
        )}
      </div>
    </aside>
  );
}
