"use client";
/** Meshcore project workspace: Sidebar | [capability views] | Inspector.
 *
 * Views (README §0.1):
 *  · overview     — capability launcher + project status + return path
 *  · chat         — Claude-like agent conversation (activity trace, attachments)
 *  · pid          — the EXISTING P&ID upload/processing/review interface
 *  · memory       — Plant Memory entity graph
 *  · deliverables — generated XLSX/DOCX/PDF artefacts
 *
 * The `pid` view intentionally reuses the existing Explorer pane and the
 * existing upload/ingest sidebar rather than rebuilding the P&ID workflow.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type {
  DeliverableRec,
  DocumentRec,
  EntityDetail,
  EntityRec,
  EvidenceSource,
  IngestionStatus,
  PageRec,
  Project,
  RelationshipRec,
  WorkspaceView,
} from "@/lib/types";
import {
  Badge,
  Button,
  EmptyState,
  IconButton,
  SearchInput,
  cn,
} from "./ui";
import {
  IconAlert,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconHome,
  IconMessage,
  IconPlus,
  IconRefresh,
  IconShieldCheck,
} from "./icons";
import Sidebar from "./Sidebar";
import ChatPane from "./ChatPane";
import MemoryPane from "./MemoryPane";
import PidViewer from "./PidViewer";
import Inspector from "./Inspector";
import TrustDrawer from "./TrustDrawer";
import WorkspaceOverview from "./WorkspaceOverview";
import DeliverablesPane from "./Deliverables";
import EgressCounter from "./EgressCounter";
import ConversationRail from "./ConversationRail";

export default function Workspace({
  projectId,
  initialView = "chat",
  initialPrompt = "",
  initialConversationId = null,
  fromPid = false,
}: {
  projectId: number;
  initialView?: WorkspaceView;
  initialPrompt?: string;
  initialConversationId?: number | null;
  fromPid?: boolean;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [docs, setDocs] = useState<DocumentRec[]>([]);
  const [tab, setTab] = useState<WorkspaceView>(initialView);
  const [deliverables, setDeliverables] = useState<DeliverableRec[]>([]);
  const [conversationCount, setConversationCount] = useState(0);
  // The thread the chat pane is showing. Held here, not inside ChatPane, so
  // the rail and the pane cannot disagree about which chat is open.
  const [activeConversationId, setActiveConversationId] = useState<
    number | null
  >(initialConversationId);
  // Bumped after any turn so the rail re-reads titles, counts and ordering.
  const [railVersion, setRailVersion] = useState(0);
  const [activeDocId, setActiveDocId] = useState<number | null>(null);
  const [pages, setPages] = useState<PageRec[]>([]);
  const [entities, setEntities] = useState<EntityRec[]>([]);
  const [relationships, setRelationships] = useState<RelationshipRec[]>([]);
  const [selectedEntityId, setSelectedEntityId] = useState<number | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [inspector, setInspector] = useState<{
    detail: EntityDetail | null;
    loading: boolean;
    error: string;
  }>({ detail: null, loading: false, error: "" });
  const [trustOpen, setTrustOpen] = useState(false);
  const [localOk, setLocalOk] = useState<boolean | null>(null);
  const [localVersion, setLocalVersion] = useState(0); // bump to reload data after ingest
  // load project + documents
  useEffect(() => {
    (async () => {
      try {
        const [ps, ds] = await Promise.all([
          api.projects(),
          api.projectDocuments(projectId),
        ]);
        setProjects(ps);
        setDocs(ds);
      } catch {
        /* surfaced via empty states */
      }
    })();
  }, [projectId, localVersion]);

  // load pages/entities/relationships for the active document
  useEffect(() => {
    setPageIndex(0);
    setSelectedEntityId(null);
    if (!activeDocId) {
      setPages([]);
      setEntities([]);
      setRelationships([]);
      return;
    }
    (async () => {
      try {
        const [pgs, ents, rels] = await Promise.all([
          api.docPages(activeDocId),
          api.docEntities(activeDocId),
          api.docRelationships(activeDocId),
        ]);
        setPages(pgs);
        setEntities(ents);
        setRelationships(rels);
      } catch {
        setPages([]);
        setEntities([]);
        setRelationships([]);
      }
    })();
  }, [activeDocId, localVersion]);

  // check local runtime once for the sidebar badge
  useEffect(() => {
    api
      .health()
      .then((h) => setLocalOk(h.ollama))
      .catch(() => setLocalOk(false));
  }, []);

  // shared session/project context: conversation count for this project
  useEffect(() => {
    api
      .projectConversations(projectId)
      .then((cs) => setConversationCount(cs.length))
      .catch(() => setConversationCount(0));
  }, [projectId, localVersion]);

  // Artefacts live on disk, so what the project has produced is a fact about
  // the project rather than about this browser session. Without this the
  // Overview reported "0 deliverables" for a project full of them, and the
  // count only became right after the agent happened to run again.
  useEffect(() => {
    api
      .deliverables(projectId)
      .then(setDeliverables)
      .catch(() => setDeliverables([]));
  }, [projectId, localVersion]);

  const openEntityDetail = useCallback(
    async (entityId: number) => {
      setSelectedEntityId(entityId);
      // Follow the entity to its own page so the highlight is actually visible.
      const ent = entities.find((e) => e.id === entityId);
      const idx = ent ? pages.findIndex((p) => p.id === ent.page_id) : -1;
      if (idx >= 0) setPageIndex(idx);

      setInspector({ detail: null, loading: true, error: "" });
      try {
        const detail = await api.entityDetail(entityId);
        setInspector({ detail, loading: false, error: "" });
      } catch (e) {
        setInspector({
          detail: null,
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    },
    [entities, pages],
  );

  const openTagDetail = useCallback(
    async (tag: string) => {
      setInspector({ detail: null, loading: true, error: "" });
      try {
        const detail = await api.memoryEntity(projectId, tag);
        setInspector({ detail, loading: false, error: "" });
      } catch (e) {
        setInspector({
          detail: null,
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    },
    [projectId],
  );

  // evidence click from chat → jump to bbox preview in inspector
  const openEvidence = useCallback(
    async (src: EvidenceSource) => {
      if (src.source_type === "graph" && src.entity) {
        await openTagDetail(src.entity);
        return;
      }
      if (src.bbox && src.document_id) {
        // fetch the entity whose bbox matches? Simplest: show preview via page
        try {
          const pgs = await api.docPages(src.document_id);
          const page = pgs.find((p) => p.page_number === src.page) ?? pgs[0];
          if (src.document_id === activeDocId) {
            const idx = pgs.findIndex((p) => p.id === page?.id);
            if (idx >= 0) setPageIndex(idx);
          }
          if (page) {
            const ents = await api.docEntities(src.document_id);
            setInspector((prev) => ({
              ...prev,
              loading: false,
              error: "",
              detail: {
                entity: {
                  id: 0,
                  page_id: page.id,
                  entity_type: src.source_type,
                  canonical_tag: src.entity ?? "",
                  label: src.text ?? "",
                  raw_text: "",
                  confidence: src.confidence ?? 0,
                  bbox: src.bbox ?? [],
                },
                connections: [],
                source_document: src.document ?? "",
                page_number: src.page ?? page.page_number,
                image_url: page.image_url,
              },
            }));
          }
        } catch {
          /* ignore preview failures */
        }
      }
    },
    [openTagDetail, activeDocId],
  );

  const onIngested = useCallback(
    (_docId: number, status: IngestionStatus) => {
      if (status.status === "ready") {
        setLocalVersion((v) => v + 1);
      }
    },
    [],
  );

  // Opening a blank thread is three state changes that must happen together:
  // clear the selection, tell the rail to re-read, and make sure the chat
  // view is the one on screen. Doing it in one place is why the sidebar, the
  // rail and the header can all offer it without drifting apart.
  const startNewChat = useCallback(() => {
    setActiveConversationId(null);
    setRailVersion((v) => v + 1);
    setTab("chat");
  }, []);

  const onDocDeleted = useCallback((docId: number) => {
    setDocs((prev) => prev.filter((d) => d.id !== docId));
    setActiveDocId((cur) => (cur === docId ? null : cur));
    setLocalVersion((v) => v + 1); // refresh project stats + graph
  }, []);

  const activePage = pages[Math.min(pageIndex, Math.max(pages.length - 1, 0))] ?? null;
  // Entities are per-page: showing page 3's drawing with page 1's boxes put
  // every highlight in the wrong place.
  const pageEntities = activePage
    ? entities.filter((e) => e.page_id === activePage.id)
    : entities;
  return (
    <div className="flex h-screen overflow-hidden bg-ink-900">
      <Sidebar
        projects={projects}
        projectId={projectId}
        view={tab}
        onView={setTab}
        docs={docs}
        activeDocId={activeDocId}
        onSelectDoc={(d) => setActiveDocId(d.id)}
        onIngested={onIngested}
        onDocDeleted={onDocDeleted}
        onOpenTrust={() => setTrustOpen(true)}
        onNewChat={startNewChat}
        localOk={localOk}
        counts={{
          conversations: conversationCount,
          deliverables: deliverables.length,
        }}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <WorkspaceHeader
          projectName={projects.find((p) => p.id === projectId)?.name ?? ""}
          view={tab}
          onView={setTab}
          onOpenTrust={() => setTrustOpen(true)}
          onNewChat={startNewChat}
          onRefresh={() => setLocalVersion((v) => v + 1)}
          docCount={docs.length}
        />

        {/* active capability */}
        <div className="min-h-0 flex-1">
          {tab === "overview" && (
            <WorkspaceOverview
              project={projects.find((p) => p.id === projectId)}
              projects={projects}
              onView={setTab}
              onOpenTrust={() => setTrustOpen(true)}
              deliverableCount={deliverables.length}
              conversationCount={conversationCount}
            />
          )}
          {/* Chat stays MOUNTED across tab changes and is only hidden.
              Unmounting it threw away the transcript and any in-flight
              stream, so glancing at the P&ID mid-answer lost the answer. */}
          <div className={cn("h-full", tab === "chat" ? "flex" : "hidden")}>
            <ConversationRail
              projectId={projectId}
              activeId={activeConversationId}
              onSelect={setActiveConversationId}
              onNew={startNewChat}
              refreshKey={railVersion}
            />
            <div className="min-w-0 flex-1">
              <ChatPane
                projectId={projectId}
                onSelectEvidence={openEvidence}
                initialPrompt={initialPrompt || undefined}
                initialConversationId={activeConversationId}
                fromPid={fromPid}
                onConversationChange={(id) => {
                  setActiveConversationId(id);
                  setRailVersion((v) => v + 1);
                }}
                onDeliverables={(items) =>
                  setDeliverables((prev) => {
                    const seen = new Set(prev.map((d) => d.id));
                    return [...prev, ...items.filter((d) => !seen.has(d.id))];
                  })
                }
              />
            </div>
          </div>
          {tab === "pid" && (
            <div className="flex h-full min-h-0 flex-col">
              <ExplorerPane
                pages={pages}
                pageIndex={pageIndex}
                onPageChange={setPageIndex}
                activePage={activePage}
                entities={pageEntities}
                totalEntities={entities.length}
                relationships={relationships}
                selectedEntityId={selectedEntityId}
                onSelectEntity={(e) => openEntityDetail(e.id)}
              />
            </div>
          )}
          {tab === "memory" && (
            <MemoryPane
              projectId={projectId}
              onInspector={(d) =>
                setInspector({ detail: d, loading: false, error: "" })
              }
            />
          )}
          {tab === "deliverables" && (
            <DeliverablesPane items={deliverables} projectId={projectId} />
          )}
        </div>
      </main>

      {/* inspector (Screen 2/5 details) */}
      <Inspector
        detail={inspector.detail}
        loading={inspector.loading}
        error={inspector.error}
        onClose={() => setInspector({ detail: null, loading: false, error: "" })}
      />

      <TrustDrawer
        open={trustOpen}
        onClose={() => setTrustOpen(false)}
        onStatus={setLocalOk}
      />
    </div>
  );
}
/** Screen 2 — Explorer: paged P&ID viewer + searchable entity list. */
function ExplorerPane({
  pages,
  pageIndex,
  onPageChange,
  activePage,
  entities,
  totalEntities,
  relationships,
  selectedEntityId,
  onSelectEntity,
}: {
  pages: PageRec[];
  pageIndex: number;
  onPageChange: (i: number) => void;
  activePage: PageRec | null;
  entities: EntityRec[];
  totalEntities: number;
  relationships: RelationshipRec[];
  selectedEntityId: number | null;
  onSelectEntity: (e: EntityRec) => void;
}) {
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [reviewOnly, setReviewOnly] = useState(false);

  if (!activePage) {
    return (
      <EmptyState
        title="No page rendered yet"
        hint="Upload and ingest a P&ID; its rendered page will appear here with clickable entities."
      />
    );
  }

  const types = Array.from(new Set(entities.map((e) => e.entity_type))).sort();
  const needsReview = (e: EntityRec) => Boolean(e.metadata?.needs_review);
  const reviewCount = entities.filter(needsReview).length;
  const q = query.trim().toLowerCase();
  const visible = entities.filter((e) => {
    if (typeFilter !== "all" && e.entity_type !== typeFilter) return false;
    if (reviewOnly && !needsReview(e)) return false;
    if (!q) return true;
    return (
      e.canonical_tag.toLowerCase().includes(q) ||
      e.label.toLowerCase().includes(q) ||
      e.raw_text.toLowerCase().includes(q)
    );
  });
  const selected = entities.find((e) => e.id === selectedEntityId) ?? null;

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        {pages.length > 1 && (
          <div className="flex items-center gap-2 border-b border-ink-800 bg-ink-900 px-3 py-1.5">
            <IconButton
              icon={<IconChevronLeft size={15} />}
              label="Previous page"
              size="sm"
              variant="outline"
              disabled={pageIndex === 0}
              onClick={() => onPageChange(pageIndex - 1)}
            />
            <div className="flex min-w-0 gap-1 overflow-x-auto">
              {pages.map((p, i) => (
                <button
                  key={p.id}
                  onClick={() => onPageChange(i)}
                  className={cn(
                    "shrink-0 rounded-md px-2 py-1 font-mono text-[11px] transition-colors",
                    i === pageIndex
                      ? "bg-accent/20 text-accent"
                      : "text-zinc-500 hover:bg-ink-800 hover:text-zinc-300",
                  )}
                >
                  p{p.page_number}
                </button>
              ))}
            </div>
            <IconButton
              icon={<IconChevronRight size={15} />}
              label="Next page"
              size="sm"
              variant="outline"
              disabled={pageIndex >= pages.length - 1}
              onClick={() => onPageChange(pageIndex + 1)}
            />
            <span className="ml-auto shrink-0 font-mono text-[10px] text-zinc-600">
              page {activePage.page_number} of {pages.length}
            </span>
          </div>
        )}
        <div className="min-h-0 flex-1">
          <PidViewer
            imageUrl={activePage.image_url}
            bbox={selected?.bbox ?? null}
            label={selected?.canonical_tag}
            entities={visible}
            selectedTag={selected?.canonical_tag ?? null}
            onSelectTag={(tag) => {
              const e = entities.find((x) => x.canonical_tag === tag);
              if (e) onSelectEntity(e);
            }}
            className="h-full"
          />
        </div>
      </div>

      <div className="flex w-[300px] shrink-0 flex-col border-l border-ink-800 bg-ink-950">
        <div className="border-b border-ink-800 px-3 py-2">
          <div className="mb-2 flex items-baseline gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Entities
            </span>
            <span className="font-mono text-[11px] text-zinc-400">
              {visible.length}
              {visible.length !== entities.length && `/${entities.length}`}
            </span>
            {pages.length > 1 && (
              <span className="ml-auto font-mono text-[10px] text-zinc-600">
                {totalEntities} in doc
              </span>
            )}
          </div>
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Filter tag or label…"
            ariaLabel="Filter entities"
            className="mb-1.5"
          />
          {reviewCount > 0 && (
            <button
              onClick={() => setReviewOnly((v) => !v)}
              title="A validation rule fired on these — they are not settled fact"
              className={cn(
                "mb-1.5 flex w-full items-center gap-1.5 rounded-lg border px-2 py-1.5 text-left text-[11px] transition-colors",
                reviewOnly
                  ? "border-amber-800 bg-amber-950/40 text-amber-300"
                  : "border-ink-700 text-zinc-500 hover:border-ink-600 hover:text-amber-300",
              )}
            >
              <IconAlert size={12} className="shrink-0" />
              {reviewCount} need review
              {reviewOnly && (
                <IconCheck size={12} className="ml-auto shrink-0" />
              )}
            </button>
          )}
          {types.length > 1 && (
            <div className="flex flex-wrap gap-1">
              {["all", ...types].map((t) => (
                <button
                  key={t}
                  onClick={() => setTypeFilter(t)}
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[10px] transition-colors",
                    typeFilter === t
                      ? "bg-accent/20 text-accent"
                      : "bg-ink-800 text-zinc-500 hover:text-zinc-300",
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          )}
        </div>

        <ul className="min-h-0 flex-1 overflow-y-auto p-2">
          {visible.map((e) => (
            <li key={e.id}>
              <button
                onClick={() => onSelectEntity(e)}
                className={cn(
                  "mb-1 w-full rounded-lg border px-2.5 py-2 text-left transition-colors",
                  e.id === selectedEntityId
                    ? "border-accent/60 bg-ink-850"
                    : "border-ink-700 bg-ink-850/50 hover:border-ink-600",
                )}
              >
                <div className="flex items-center gap-2">
                  <Badge color={e.confidence >= 0.8 ? "green" : "amber"}>
                    {e.entity_type}
                  </Badge>
                  <span className="truncate font-mono text-xs text-zinc-100">
                    {e.canonical_tag || e.raw_text}
                  </span>
                  {needsReview(e) && (
                    <span
                      title={
                        "Validation: " +
                        (e.metadata?.review_reasons ?? []).join(", ")
                      }
                      className="ml-auto shrink-0 text-[10px] text-amber-400"
                    >
                      ⚠
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-zinc-500">
                  <span className="truncate">{e.label || "—"}</span>
                  <span className="ml-auto shrink-0 font-mono">
                    {Math.round(e.confidence * 100)}%
                  </span>
                </div>
              </button>
            </li>
          ))}
          {visible.length === 0 && (
            <li className="px-2 py-1 text-xs text-zinc-600">
              {entities.length === 0
                ? "No entities extracted on this page."
                : "No entity matches this filter."}
            </li>
          )}
        </ul>

        <div className="border-t border-ink-800 px-3 py-2 text-[10px] leading-relaxed text-zinc-600">
          {relationships.length} links detected · click an entity to highlight
          its bbox on the drawing
          {reviewCount > 0 && (
            <>
              {" · "}
              <span className="text-amber-500">
                {reviewCount} flagged by validation rules
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** App chrome for the active view.
 *
 *  Deliberately thin. This bar carries where-you-are (breadcrumb) and the
 *  things that are true everywhere (egress counter, trust, shortcuts); each
 *  pane keeps its own toolbar for actions that only make sense inside it.
 *  Collapsing both into one bar was the obvious move and the wrong one — it
 *  put "Download all" next to "Meshcore" and made the chrome jump every time
 *  the view changed.
 */
const VIEW_TITLE: Record<WorkspaceView, string> = {
  overview: "Overview",
  chat: "Agent chat",
  pid: "P&ID",
  memory: "Plant Memory",
  deliverables: "Deliverables",
};

function WorkspaceHeader({
  projectName,
  view,
  onView,
  onOpenTrust,
  onNewChat,
  onRefresh,
  docCount,
}: {
  projectName: string;
  view: WorkspaceView;
  onView: (v: WorkspaceView) => void;
  onOpenTrust: () => void;
  onNewChat: () => void;
  onRefresh: () => void;
  docCount: number;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-ink-800 bg-ink-900 px-4">
      {/* breadcrumb */}
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2">
        <Link
          href="/"
          className="shrink-0 rounded-lg p-1 text-zinc-600 transition-colors hover:bg-ink-850 hover:text-zinc-300"
          title="Meshcore home"
        >
          <IconHome size={15} />
        </Link>
        <span className="shrink-0 text-zinc-700">/</span>
        {projectName && (
          <>
            <span className="max-w-[14rem] truncate text-[13px] text-zinc-500">
              {projectName}
            </span>
            <span className="shrink-0 text-zinc-700">/</span>
          </>
        )}
        <h1 className="shrink-0 text-[13px] font-medium text-zinc-100">
          {VIEW_TITLE[view]}
        </h1>
      </nav>

      {/* view-scoped shortcut: the one action most likely wanted next */}
      <div className="ml-3 flex items-center gap-1.5">
        {view === "chat" && (
          <Button
            variant="outline"
            size="sm"
            icon={<IconPlus size={14} />}
            onClick={onNewChat}
          >
            New chat
          </Button>
        )}
        {view === "pid" && docCount === 0 && (
          <span className="text-[11px] text-amber-300/90">
            Upload a drawing in the Files rail to begin
          </span>
        )}
        {view === "pid" && docCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            icon={<IconMessage size={14} />}
            onClick={() => onView("chat")}
          >
            Ask about this drawing
          </Button>
        )}
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <EgressCounter />
        <IconButton
          icon={<IconRefresh size={15} />}
          label="Reload project data"
          size="sm"
          onClick={onRefresh}
        />
        <Button
          variant="outline"
          size="sm"
          icon={<IconShieldCheck size={14} />}
          onClick={onOpenTrust}
        >
          Trust
        </Button>
      </div>
    </header>
  );
}
