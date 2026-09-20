"use client";
/** Meshcore agent chat — SSE grounded streaming with status, tool/activity
 *  trace, evidence, confidence, attachments and generated deliverables.
 *
 *  README §0.1 / §7 Phase 0: the Claude-like conversation area of the main
 *  workspace. Supports handoff from the home composer (`initialPrompt`), a
 *  restored conversation (`initialConversationId`) and return from the P&ID
 *  capability (`fromPid`).
 *
 *  One composer, one button. Asking a question and asking for a file are two
 *  different operations on the backend — one streams a grounded answer, the
 *  other runs the bounded agent and renders an XLSX, DOCX or PDF — but which
 *  one the user wants is already stated in their sentence, so the sentence
 *  decides. There is no Build button and no format picker: "generate an excel
 *  of all instruments" produces a spreadsheet, and the composer says so
 *  before it is sent rather than after.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import type {
  ActivityStep,
  ChatMessage,
  ContextReport,
  DeliverableRec,
  EvidencePacket,
  EvidenceSource,
} from "@/lib/types";
import { AutoTextarea, Badge, Button, ConfidenceBar, CopyButton, Spinner, cn } from "./ui";
import ActivityTrace from "./ActivityTrace";
import { DeliverableCards } from "./Deliverables";
import Markdown from "./Markdown";

const STARTERS = [
  "Trace the process path to P-101.",
  "What instruments are connected to P-101?",
  "Build an excel tracker of every instrument.",
  "Draft a PDF change note for valve CV-104.",
  "Show uncertain extractions from this drawing.",
];

const STAGE_LABELS: Record<string, string> = {
  session: "Preparing session…",
  intent: "Understanding the question…",
  retrieving: "Searching plant memory…",
  grounding: "Checking P&ID evidence…",
  answering: "Writing the answer…",
  intake: "Working out what to build…",
  budget: "Stopping — budget spent",
};

/** status stage → activity-trace label (the visible tool/activity trace). */
const STAGE_STEPS: Record<string, string> = {
  session: "Open session + resolve clearance",
  intent: "Classify intent",
  retrieving: "Retrieve evidence (graph + hybrid index)",
  grounding: "Build grounded evidence packet",
  answering: "Synthesise answer",
};

let _id = 0;
const nextId = () => `m${++_id}`;
const stamp = () => new Date().toLocaleTimeString();

/* ── routing: does this sentence ask for a FILE or for an answer? ──
 *
 * The bar used to be "an action verb AND an artefact noun", which missed the
 * most common phrasing of all — naming the format and nothing else ("an
 * excel of all instruments"). It is now three rules, in order:
 *
 *   1. A question form with no build verb is a question. "What does the
 *      report say about P-101" must not run a 3-minute agent task to hand
 *      back something the user wanted read out.
 *   2. A build verb plus an artefact noun is a build. (The original rule.)
 *   3. Naming a concrete file format is a build on its own — nobody types
 *      "xlsx" conversationally.
 *
 * Mistaking a question for a build is still the more annoying error, which is
 * why rule 1 comes first and wins.
 */
const FORMAT_WORD =
  /\b(excel|xlsx|spreadsheet|csv|workbook|docx|pdf|word document|word doc)\b/i;
const ARTIFACT_VERB =
  /\b(generate|create|make|produce|build|draft|write|export|prepare|compile|render|give me|send me|i need|i want)\b/i;
const ARTIFACT_NOUN =
  /\b(excel|xlsx|spreadsheet|csv|sheet|docx|word|document|pdf|report|tracker|register|inventory|note|moc|deliverable|file|table|list)\b/i;
const QUESTION_FORM =
  /^\s*(what|which|who|whom|whose|when|where|why|how|is|are|was|were|does|do|did|can|could|should|would|will|has|have|had|tell me)\b/i;

export function wantsArtifact(text: string): boolean {
  const t = (text ?? "").trim();
  if (!t) return false;
  const hasVerb = ARTIFACT_VERB.test(t);
  if (QUESTION_FORM.test(t) && !hasVerb) return false;
  if (hasVerb && ARTIFACT_NOUN.test(t)) return true;
  return FORMAT_WORD.test(t);
}

/** Which file the sentence asks for — mirrors `agent.detect_format`.
 *
 *  Only used for the composer's own label. The backend decides for real; if
 *  the two ever disagree the file is still correct, the hint is just wrong,
 *  which is the right way round for a duplicated rule to fail.
 */
const TABULAR_SHAPE =
  /\b(sheet|table|tabular|tracker|register|inventory|matrix|schedule|list of|all instruments|all valves|all equipment)\b/i;

export function detectFormat(text: string): "XLSX" | "DOCX" | "PDF" {
  const t = text ?? "";
  if (/\b(excel|xlsx|spreadsheet|csv|workbook)\b/i.test(t)) return "XLSX";
  if (/\bpdf\b/i.test(t)) return "PDF";
  if (/\b(docx|word)\b/i.test(t)) return "DOCX";
  if (TABULAR_SHAPE.test(t)) return "XLSX";
  return "DOCX";
}

/** Advance the FIRST unfinished step matching `tool`.
 *
 *  Matching every step whose label starts with the tool name broke any plan
 *  that used a tool twice — the MOC plan retrieves twice — because both rows
 *  went active together and then both went done, so the trace claimed work
 *  that had not happened yet.
 */
function advanceStep(
  steps: ActivityStep[],
  tool: string,
  status: ActivityStep["status"],
  detail?: string,
): ActivityStep[] {
  const i = steps.findIndex(
    (s) => s.tool === tool && s.status !== "done" && s.status !== "failed",
  );
  if (i < 0) return steps;
  const next = [...steps];
  next[i] = {
    ...next[i],
    status,
    detail: detail ?? next[i].detail,
    at: stamp(),
  };
  return next;
}

/** Persisted sources → a packet, so a reopened thread keeps its citations.
 *
 *  Restoring the transcript without this left old turns with a "Why this
 *  answer?" disclosure but no clickable evidence, so the same answer looked
 *  differently grounded depending on whether you had reloaded the page.
 */
function packetFromSources(
  sources: ChatMessage["sources"],
  confidence?: number,
): EvidencePacket | undefined {
  if (!sources || sources.length === 0) return undefined;
  return {
    answer_context: sources.map((s) => {
      if (s.source_type === "graph") {
        // Graph sources are persisted as one "A RELATION B" string.
        const [entity, relation, ...rest] = (s.relation ?? "").split(" ");
        return {
          source_type: "graph",
          entity: entity || null,
          relation: relation || null,
          target: rest.join(" ") || null,
          text: s.relation ?? null,
        } as EvidenceSource;
      }
      return {
        source_type: s.source_type,
        document: s.document || null,
        page: s.page || null,
        bbox: s.bbox ?? null,
        text: null,
      } as EvidenceSource;
    }),
    confidence: confidence ?? 0,
    query_intent: "",
    retrieved_from: "restored from this conversation",
  };
}

export default function ChatPane({
  projectId,
  onSelectEvidence,
  initialPrompt,
  initialConversationId = null,
  fromPid = false,
  onDeliverables,
  onConversationChange,
}: {
  projectId: number;
  onSelectEvidence: (src: EvidenceSource) => void;
  initialPrompt?: string;
  /** The thread to show. Changing it swaps the transcript, so the rail can
   *  drive this pane without remounting it and losing in-flight state. */
  initialConversationId?: number | null;
  fromPid?: boolean;
  /** Fires when a turn creates or touches a thread, so the rail can refresh
   *  its titles and counts. */
  onConversationChange?: (id: number) => void;
  /** Reports artefacts emitted by the agent so the Deliverables view stays in
   *  sync with the conversation (README §0.1 "generated deliverables"). */
  onDeliverables?: (items: DeliverableRec[]) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<number | null>(
    initialConversationId,
  );
  const [historyLoading, setHistoryLoading] = useState(false);
  const [attaching, setAttaching] = useState(false);
  const [attachError, setAttachError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const autoranRef = useRef(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  // Read inside the SSE callbacks, which close over the render that started
  // the stream — the state value there is stale by the second event.
  const conversationRef = useRef<number | null>(initialConversationId);

  // Only follow the stream while the user is already at the bottom; otherwise
  // scrolling up to re-read an earlier answer is fought by every new token.
  const pinnedRef = useRef(true);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !pinnedRef.current) return;
    el.scrollTo({ top: el.scrollHeight });
  }, [messages]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  const setConversation = useCallback(
    (id: number) => {
      if (conversationRef.current === id) return;
      conversationRef.current = id;
      setConversationId(id);
      onConversationChange?.(id);
    },
    [onConversationChange],
  );

  // Restore a thread whenever the selected one changes — not only on mount.
  // Switching chats in the rail has to swap the transcript, and reopening a
  // thread has to bring back its evidence and its files, or the history is
  // only a transcript of text and every citation and download is lost.
  useEffect(() => {
    setConversationId(initialConversationId);
    conversationRef.current = initialConversationId;
    // A newly opened thread must start at its bottom even if the user had
    // scrolled up in the thread they were reading before.
    pinnedRef.current = true;

    if (!initialConversationId) {
      setMessages([]);       // "New chat" starts genuinely empty
      setHistoryLoading(false);
      return;
    }

    let cancelled = false;
    setHistoryLoading(true);
    (async () => {
      try {
        const rows = await api.messages(initialConversationId);
        if (cancelled) return;
        setMessages(
          rows
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({
              id: `h${m.id}`,
              role: m.role === "user" ? "user" : "assistant",
              content: m.content,
              confidence: m.confidence ?? undefined,
              sources: m.sources ?? [],
              claims: m.claims ?? [],
              deliverables: m.artifacts ?? [],
              evidence: packetFromSources(m.sources, m.confidence ?? 0),
              done: true,
            })),
        );
      } catch {
        if (!cancelled) setMessages([]);
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initialConversationId]);

  /** Open a turn pair and return the assistant id plus its patcher. */
  const openTurn = (question: string, stage: string) => {
    const userMsg: ChatMessage = {
      id: nextId(),
      role: "user",
      content: question,
      done: true,
    };
    const assistant: ChatMessage = {
      id: nextId(),
      role: "assistant",
      content: "",
      streaming: true,
      stage,
      activity: [],
      prompt: question,
      done: false,
    };
    pinnedRef.current = true;
    setMessages((m) => [...m, userMsg, assistant]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((ms) => ms.map((m) => (m.id === assistant.id ? fn(m) : m)));
    return { patch, controller };
  };

  /** Shared teardown: an aborted stream is a stop, not an error. */
  const closeTurn = (
    patch: (fn: (m: ChatMessage) => ChatMessage) => void,
    error?: unknown,
  ) => {
    const aborted = error instanceof DOMException && error.name === "AbortError";
    patch((m) => ({
      ...m,
      streaming: false,
      stage: undefined,
      stopped: aborted ? true : m.stopped,
      error: error && !aborted
        ? error instanceof Error
          ? error.message
          : String(error)
        : m.error,
      activity: (m.activity ?? []).map((s) =>
        s.status === "active" || s.status === "pending"
          ? { ...s, status: aborted ? ("failed" as const) : ("done" as const) }
          : s,
      ),
      done: true,
    }));
    setStreaming(false);
    abortRef.current = null;
  };

  // ── grounded answer: streams tokens from the chat endpoint ──────────
  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setInput("");
    const { patch, controller } = openTurn(q, STAGE_LABELS.session);

    try {
      await streamSSE(
        `/api/projects/${projectId}/chat`,
        { message: q, conversation_id: conversationRef.current ?? undefined },
        (ev) => {
          const d = ev.data;
          if (d.conversation_id) setConversation(Number(d.conversation_id));

          if (ev.event === "status") {
            const stage = String(d.stage ?? "");
            patch((m) => {
              const steps = m.activity ?? [];
              // close the previous step, open this one (tool/activity trace)
              const closed: ActivityStep[] = steps.map((s) =>
                s.status === "active" ? { ...s, status: "done" as const } : s,
              );
              const label = STAGE_STEPS[stage];
              return {
                ...m,
                stage: STAGE_LABELS[stage] ?? String(d.detail ?? stage),
                activity: label
                  ? [
                      ...closed,
                      {
                        id: `s${closed.length + 1}`,
                        label,
                        detail:
                          stage === "session" && d.conversation_id
                            ? `conversation ${d.conversation_id}`
                            : undefined,
                        status: "active" as const,
                        at: stamp(),
                      },
                    ]
                  : closed,
              };
            });
          } else if (ev.event === "evidence") {
            const packet = d.packet as EvidencePacket;
            patch((m) => ({
              ...m,
              evidence: packet,
              activity: (m.activity ?? []).map((s) =>
                s.status === "active" && s.label.startsWith("Retrieve")
                  ? {
                      ...s,
                      status: "done" as const,
                      detail: `${packet.answer_context?.length ?? 0} sources`,
                    }
                  : s,
              ),
            }));
          } else if (ev.event === "context") {
            // What the model was actually shown, before it says anything.
            const report = d.report as ContextReport;
            patch((m) => ({
              ...m,
              context: report,
              activity: [
                ...(m.activity ?? []),
                {
                  id: `c${(m.activity ?? []).length + 1}`,
                  tool: "context",
                  label: "Fit prompt to context window",
                  detail:
                    `${report.prompt_tokens}/${report.window} tokens · ` +
                    `${report.evidence_kept}/${report.evidence_total} sources`,
                  status: "done" as const,
                  at: stamp(),
                },
              ],
            }));
          } else if (ev.event === "tool") {
            patch((m) => ({
              ...m,
              activity: [
                ...(m.activity ?? []),
                {
                  id: `t${(m.activity ?? []).length + 1}`,
                  tool: String(d.tool ?? "unknown"),
                  label: `Tool: ${String(d.tool ?? "unknown")}`,
                  detail: d.detail ? String(d.detail) : undefined,
                  status:
                    String(d.status ?? "done") === "failed" ? "failed" : "done",
                  at: stamp(),
                },
              ],
            }));
          } else if (ev.event === "token") {
            patch((m) => ({ ...m, content: m.content + String(d.text ?? "") }));
          } else if (ev.event === "done") {
            const artifacts = (d.artifacts as DeliverableRec[]) ?? [];
            if (artifacts.length > 0) onDeliverables?.(artifacts);
            patch((m) => ({
              ...m,
              content: String(d.message ?? m.content),
              confidence: Number(d.confidence ?? 0),
              claims: (d.claims as ChatMessage["claims"]) ?? [],
              sources: (d.sources as ChatMessage["sources"]) ?? [],
              deliverables: artifacts,
              intent: String(d.intent ?? ""),
              model: String(d.model ?? ""),
              context: (d.context as ContextReport) ?? m.context,
              streaming: false,
              stage: undefined,
              activity: (m.activity ?? []).map((s) =>
                s.status === "active" ? { ...s, status: "done" as const } : s,
              ),
              done: true,
            }));
          } else if (ev.event === "error") {
            patch((m) => ({
              ...m,
              error: String(d.message ?? "Unknown error"),
              streaming: false,
              stage: undefined,
              done: true,
            }));
          }
        },
        controller.signal,
      );
      closeTurn(patch);
    } catch (e) {
      closeTurn(patch, e);
    }
  };

  // ── agent task: bounded loop that produces a downloadable artefact ──
  const runAgentTask = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setInput("");
    const { patch, controller } = openTurn(q, "Working out what to build…");

    try {
      await streamSSE(
        `/api/projects/${projectId}/agent`,
        { prompt: q, conversation_id: conversationRef.current ?? undefined },
        (ev) => {
          const d = ev.data;
          // An agent turn belongs to the same thread as the chat turns around
          // it, so the id it resolves has to reach both this pane and the rail.
          if (d.conversation_id) setConversation(Number(d.conversation_id));

          if (ev.event === "status") {
            const stage = String(d.stage ?? "");
            patch((m) => ({
              ...m,
              stage:
                String(d.detail ?? "") || STAGE_LABELS[stage] || m.stage,
            }));
          } else if (ev.event === "plan") {
            const steps = (d.steps as { tool: string; why: string }[]) ?? [];
            const fmt = d.format ? String(d.format).toUpperCase() : "";
            patch((m) => ({
              ...m,
              stage: fmt
                ? `Planned ${steps.length} steps → ${fmt}`
                : `Planned ${steps.length} steps`,
              activity: steps.map((s, i) => ({
                id: `p${i}`,
                tool: s.tool,
                label: `${s.tool} — ${s.why}`,
                status: "pending" as const,
                at: stamp(),
              })),
            }));
          } else if (ev.event === "policy") {
            if (String(d.decision) === "deny") {
              patch((m) => ({
                ...m,
                activity: advanceStep(
                  m.activity ?? [],
                  String(d.tool),
                  "failed",
                  String(d.reason),
                ),
              }));
            }
          } else if (ev.event === "tool") {
            const tool = String(d.tool);
            const status = String(d.status);
            const mapped: ActivityStep["status"] =
              status === "done"
                ? "done"
                : status === "failed"
                  ? "failed"
                  : "active";
            patch((m) => ({
              ...m,
              stage: status === "running" ? `Running ${tool}…` : m.stage,
              activity: advanceStep(
                m.activity ?? [],
                tool,
                mapped,
                d.detail ? String(d.detail) : undefined,
              ),
            }));
          } else if (ev.event === "verify") {
            const checks = (d.checks ?? {}) as Record<string, boolean | null>;
            const failed = Object.entries(checks)
              .filter(([, v]) => v === false)
              .map(([k]) => k);
            patch((m) => ({
              ...m,
              stage: failed.length
                ? `Verification flagged: ${failed.join(", ")}`
                : "Verified",
            }));
          } else if (ev.event === "agent_done") {
            const artifacts = (d.artifacts as DeliverableRec[]) ?? [];
            if (artifacts.length > 0) onDeliverables?.(artifacts);
            // The reply text comes from the run that produced it, so the live
            // turn and the same turn after a reload read identically.
            patch((m) => ({
              ...m,
              content: String(d.message ?? m.content),
              deliverables: artifacts,
              streaming: false,
              stage: undefined,
              activity: (m.activity ?? []).map((s) =>
                s.status === "pending" || s.status === "active"
                  ? { ...s, status: "done" as const }
                  : s,
              ),
              done: true,
            }));
          } else if (ev.event === "error") {
            patch((m) => ({
              ...m,
              error: String(d.message ?? "Unknown error"),
              streaming: false,
              stage: undefined,
              done: true,
            }));
          }
        },
        controller.signal,
      );
      closeTurn(patch);
    } catch (e) {
      closeTurn(patch, e);
    }
  };

  // ── one input, one button ────────────────────────────────────────────
  const send = useCallback(
    (question: string) => {
      if (wantsArtifact(question)) return runAgentTask(question);
      return submit(question);
    },
    // Both paths read their inputs from refs and arguments, so the identity
    // of `send` does not need to change between renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [projectId, streaming],
  );

  // ── handoff from the home composer: run the prompt once ──────────────
  useEffect(() => {
    if (!initialPrompt || autoranRef.current) return;
    autoranRef.current = true;
    void send(initialPrompt);
    // send is stable for the life of the mount; intentionally run once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPrompt]);

  // ── chat-composer file attachment (README §0.1) ──────────────────────
  const attach = useCallback(
    async (file: File) => {
      setAttachError("");
      setAttaching(true);
      const userMsg: ChatMessage = {
        id: nextId(),
        role: "user",
        content: `Attached “${file.name}” to this project.`,
        attachments: [{ name: file.name, kind: file.type || "file" }],
        done: true,
      };
      const assistant: ChatMessage = {
        id: nextId(),
        role: "assistant",
        content: "",
        streaming: true,
        stage: "Uploading attachment…",
        activity: [
          {
            id: "a1",
            tool: "upload",
            label: `Upload ${file.name}`,
            status: "active",
            at: stamp(),
          },
        ],
        done: false,
      };
      pinnedRef.current = true;
      setMessages((m) => [...m, userMsg, assistant]);
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((ms) => ms.map((m) => (m.id === assistant.id ? fn(m) : m)));
      try {
        const doc = await api.attachDocument(projectId, file);
        patch((m) => ({
          ...m,
          streaming: false,
          stage: undefined,
          content: `**${doc.name}** accepted into this project's P&ID pipeline. Ingestion is queued — progress is shown in the Files panel; the extracted entities become queryable when it reaches *Ready*.`,
          activity: [
            ...(m.activity ?? []).map((s) =>
              s.status === "active" ? { ...s, status: "done" as const } : s,
            ),
            {
              id: "a2",
              tool: "ingest",
              label: "Queue ingestion (render → extract → graph → index)",
              status: "done" as const,
              at: stamp(),
            },
          ],
          deliverables: [],
          done: true,
        }));
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setAttachError(msg);
        patch((m) => ({
          ...m,
          error: msg,
          streaming: false,
          stage: undefined,
          activity: (m.activity ?? []).map((s) =>
            s.status === "active" ? { ...s, status: "failed" as const } : s,
          ),
          done: true,
        }));
      } finally {
        setAttaching(false);
      }
    },
    [projectId],
  );

  // ── retry: re-run the prompt that produced the last turn ─────────────
  // Only the newest assistant turn offers it. Re-running an old turn would
  // append its answer at the bottom, out of order with the question it
  // answers, which reads as a different conversation than it is.
  const lastAssistant = [...messages]
    .reverse()
    .find((m) => m.role === "assistant" && m.done);
  const retry = useCallback(() => {
    const prompt = lastAssistant?.prompt;
    if (!prompt || streaming) return;
    void send(prompt);
  }, [lastAssistant?.prompt, streaming, send]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      {fromPid && (
        <div className="border-b border-ink-700 bg-accent/[0.06] px-6 py-2 text-[11px] text-zinc-400">
          <span className="text-accent">Returned from P&amp;ID.</span> The
          drawing context and extracted plant memory of this project are already
          available to the agent below.
        </div>
      )}
      {historyLoading && (
        <div className="flex items-center gap-2 border-b border-ink-700 px-6 py-2 text-[11px] text-zinc-500">
          <Spinner className="h-3 w-3" /> Restoring conversation history…
        </div>
      )}
      <MessageList
        messages={messages}
        onEvidence={onSelectEvidence}
        scrollRef={scrollRef}
        onScroll={onScroll}
        projectId={projectId}
        retryableId={
          !streaming && lastAssistant?.prompt ? lastAssistant.id : null
        }
        onRetry={retry}
      />
      <Composer
        input={input}
        setInput={setInput}
        send={send}
        streaming={streaming}
        stop={() => abortRef.current?.abort()}
        starters={messages.length === 0 ? STARTERS : []}
        attaching={attaching}
        attachError={attachError}
        onAttachClick={() => fileRef.current?.click()}
        textareaRef={composerRef}
      />
      <input
        ref={fileRef}
        type="file"
        accept=".pdf,image/*"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void attach(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

function MessageList({
  messages,
  onEvidence,
  scrollRef,
  onScroll,
  projectId,
  retryableId,
  onRetry,
}: {
  messages: ChatMessage[];
  onEvidence: (src: EvidenceSource) => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onScroll?: () => void;
  projectId: number;
  retryableId: string | null;
  onRetry: () => void;
}) {
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto px-6 py-4"
    >
      {messages.map((m) =>
        m.role === "user" ? (
          <div key={m.id} className="mb-4 flex justify-end animate-fade-in">
            <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-ink-700 px-4 py-2.5 text-sm text-zinc-100">
              <span className="whitespace-pre-wrap">{m.content}</span>
              {m.attachments && m.attachments.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {m.attachments.map((a) => (
                    <span
                      key={a.name}
                      className="rounded-md border border-ink-600 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400"
                    >
                      📎 {a.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div key={m.id} className="mb-6 animate-fade-in">
            {m.stage && (
              <div className="mb-2 flex items-center gap-2 text-xs text-zinc-500">
                <Spinner className="h-3 w-3" />
                {m.stage}
              </div>
            )}
            <ActivityTrace steps={m.activity ?? []} />
            {m.content && <Markdown text={m.content} />}
            {/* A caret while the model is mid-sentence, so a slow local model
                is visibly working rather than apparently finished. */}
            {m.streaming && (
              <span
                aria-hidden
                className="ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] animate-pulse-dot bg-accent"
              />
            )}
            {m.stopped && (
              <p className="mt-2 text-[11px] italic text-zinc-500">
                Stopped. The answer above is incomplete.
              </p>
            )}
            {m.deliverables && m.deliverables.length > 0 && (
              <DeliverableCards
                items={m.deliverables}
                compact
                projectId={projectId}
              />
            )}
            {m.error && (
              <div className="mt-2 rounded-lg border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
                {m.error}
              </div>
            )}
            {m.evidence && (
              <EvidenceChips packet={m.evidence} onEvidence={onEvidence} />
            )}
            {m.done && m.confidence !== undefined && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Badge color="violet">intent: {m.intent || "—"}</Badge>
                <Badge color="zinc">model: {m.model || "—"}</Badge>
                <div className="w-40">
                  <ConfidenceBar value={m.confidence} />
                </div>
              </div>
            )}
            {m.done && (m.content || m.error) && (
              <div className="mt-2 flex items-center gap-1">
                {m.content && <CopyButton text={m.content} />}
                {m.id === retryableId && (
                  <button
                    onClick={onRetry}
                    title="Run this question again"
                    className="rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300"
                  >
                    ↻ Retry
                  </button>
                )}
                {m.context && <ContextBadge report={m.context} />}
              </div>
            )}
            {m.done && <WhyThisAnswer message={m} />}
          </div>
        ),
      )}
      {messages.length === 0 && (
        <div className="grid h-full place-items-center text-center">
          <div>
            <div className="mb-1 text-lg font-medium text-zinc-300">
              Ask about this plant
            </div>
            <p className="max-w-md text-sm text-zinc-500">
              Answers are grounded in extracted plant memory with visible
              evidence, and the activity trace shows how each one was produced.
              Ask for a spreadsheet, a document or a PDF and it gets built and
              filed under Deliverables.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** What the model was shown, on demand.
 *
 *  A 1B model that answers badly because a source was cut for space looks
 *  identical to one that answered badly on its own. This is the difference,
 *  stated rather than left to be inferred.
 */
function ContextBadge({ report }: { report: ContextReport }) {
  const [open, setOpen] = useState(false);
  const pct = report.window
    ? Math.round((report.prompt_tokens / report.window) * 100)
    : 0;
  return (
    <span className="relative ml-auto">
      <button
        onClick={() => setOpen((v) => !v)}
        title="What this model was actually shown"
        className="rounded-md px-1.5 py-0.5 font-mono text-[10px] text-zinc-600 transition-colors hover:bg-ink-800 hover:text-zinc-400"
      >
        ctx {pct}% · {report.evidence_kept}/{report.evidence_total} src
      </button>
      {open && (
        <div className="absolute bottom-full right-0 z-10 mb-1 w-72 rounded-lg border border-ink-700 bg-ink-850 p-2.5 text-left shadow-lg">
          <div className="mb-1 text-[11px] font-semibold text-zinc-300">
            Context window
          </div>
          <dl className="space-y-0.5 text-[11px] text-zinc-500">
            <div className="flex justify-between gap-2">
              <dt>prompt</dt>
              <dd className="font-mono text-zinc-400">
                {report.prompt_tokens} / {report.window} tokens
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>reserved for answer</dt>
              <dd className="font-mono text-zinc-400">
                {report.reserve_for_answer}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>evidence rows</dt>
              <dd className="font-mono text-zinc-400">
                {report.evidence_kept} of {report.evidence_total}
              </dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt>history turns</dt>
              <dd className="font-mono text-zinc-400">
                {report.history_turns_kept} kept ·{" "}
                {report.history_turns_digested} digested
              </dd>
            </div>
          </dl>
          {report.dropped.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 border-t border-ink-700 pt-1.5 text-[11px] text-amber-400/80">
              {report.dropped.map((d, i) => (
                <li key={i}>· {d}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}

/** Clickable evidence chips for one turn, collapsed to 8 by default. */
function EvidenceChips({
  packet,
  onEvidence,
}: {
  packet: EvidencePacket;
  onEvidence: (src: EvidenceSource) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const ctx = packet.answer_context ?? [];
  const LIMIT = 8;
  const shown = expanded ? ctx : ctx.slice(0, LIMIT);

  return (
    <EvidenceSection
      packet={packet}
      hidden={Math.max(0, ctx.length - LIMIT)}
      expanded={expanded}
      onToggle={() => setExpanded((v) => !v)}
      chips={shown.map((c, i) => (
        <button
          key={i}
          onClick={() => onEvidence(c)}
          title={c.text ?? ""}
          className="rounded-lg border border-ink-600 bg-ink-850 px-2 py-1 text-left text-[11px] text-zinc-300 transition-colors hover:border-accent hover:text-zinc-100"
        >
          {c.source_type === "graph" ? (
            <span>
              <span className="font-mono text-accent-soft">{c.entity}</span>{" "}
              <span className="text-zinc-500">→ {c.relation} →</span>{" "}
              <span className="font-mono text-accent-soft">{c.target}</span>
            </span>
          ) : (
            <span>
              <span className="font-mono text-sky-300">
                {c.entity ?? c.document ?? "doc"}
              </span>
              {c.document && (
                <span className="text-zinc-500">
                  {" "}· {c.document}
                  {c.page ? ` p${c.page}` : ""}
                </span>
              )}
              {!c.document && c.page ? (
                <span className="text-zinc-500"> · p{c.page}</span>
              ) : null}
            </span>
          )}
        </button>
      ))}
    />
  );
}

function EvidenceSection({
  packet,
  chips,
  hidden = 0,
  expanded,
  onToggle,
}: {
  packet: EvidencePacket;
  chips: React.ReactNode;
  hidden?: number;
  expanded?: boolean;
  onToggle?: () => void;
}) {
  const ctx = packet.answer_context ?? [];
  if (ctx.length === 0) return null;
  return (
    <div className="mt-3 rounded-lg border border-ink-700/70 bg-ink-850/40 p-2.5">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Evidence
        </span>
        <span className="text-[11px] text-zinc-500">
          {ctx.length} sources · confidence{" "}
          {Math.round((packet.confidence ?? 0) * 100)}%
        </span>
        {packet.retrieved_from && (
          <span
            title="Which retrievers contributed, and how many hits each"
            className="font-mono text-[10px] text-zinc-600"
          >
            via {packet.retrieved_from}
          </span>
        )}
        {hidden > 0 && onToggle && (
          <button
            onClick={onToggle}
            className="ml-auto text-[11px] text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
          >
            {expanded ? "show fewer" : `+${hidden} more`}
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">{chips}</div>
    </div>
  );
}

function WhyThisAnswer({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const claims = message.claims ?? [];
  const sources = message.sources ?? [];
  if (claims.length === 0 && sources.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
      >
        {open ? "Hide provenance" : "Why this answer?"}
      </button>
      {open && (
        <div className="mt-2 space-y-3 rounded-lg border border-ink-700 bg-ink-850 p-3 text-xs">
          <div>
            <div className="mb-1 font-semibold text-zinc-400">Claims</div>
            <ul className="space-y-1">
              {claims.map((c, i) => (
                <li key={i} className="flex items-center gap-2">
                  <span className="text-zinc-300">{c.text}</span>
                  <span className="text-zinc-500">
                    ({Math.round(c.confidence * 100)}%)
                  </span>
                </li>
              ))}
              {claims.length === 0 && <li className="text-zinc-600">—</li>}
            </ul>
          </div>
          <div>
            <div className="mb-1 font-semibold text-zinc-400">Sources</div>
            <ul className="space-y-1">
              {sources.map((s, i) => (
                <li key={i} className="text-zinc-500">
                  {s.source_type === "graph"
                    ? s.relation ?? "graph link"
                    : `${s.document || "unknown"}${s.page ? ` · page ${s.page}` : ""}`}
                </li>
              ))}
              {sources.length === 0 && <li className="text-zinc-600">—</li>}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

function Composer({
  input,
  setInput,
  send,
  streaming,
  stop,
  starters,
  attaching,
  attachError,
  onAttachClick,
  textareaRef,
}: {
  input: string;
  setInput: (v: string) => void;
  /** Routes to an answer or a build, whichever the sentence asks for. */
  send: (q: string) => void;
  streaming: boolean;
  stop: () => void;
  starters: string[];
  attaching: boolean;
  attachError: string;
  onAttachClick: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  // Shown live, so the routing decision is never a surprise after the fact.
  const willBuild = wantsArtifact(input);
  const format = willBuild ? detectFormat(input) : null;
  const empty = input.trim() === "";

  // Focus returns to the composer the moment a turn ends, so a follow-up is
  // typed rather than clicked-then-typed.
  useEffect(() => {
    if (!streaming) textareaRef.current?.focus();
  }, [streaming, textareaRef]);

  return (
    <div className="border-t border-ink-700 bg-ink-950/80 px-6 py-4">
      {starters.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {starters.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              disabled={streaming}
              className="rounded-full border border-ink-600 px-3 py-1 text-xs text-zinc-400 transition-colors hover:border-accent hover:text-zinc-200 disabled:opacity-40"
            >
              {s}
            </button>
          ))}
        </div>
      )}
      <form
        className="flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!streaming) send(input);
        }}
      >
        <button
          type="button"
          onClick={onAttachClick}
          disabled={attaching || streaming}
          title="Attach a PDF or drawing to this project"
          className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-xl border border-ink-600 text-zinc-400 transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
        >
          {attaching ? <Spinner className="h-4 w-4" /> : "📎"}
        </button>
        <AutoTextarea
          value={input}
          onChange={setInput}
          textareaRef={textareaRef}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!streaming) send(input);
            }
          }}
          maxRows={8}
          placeholder={
            streaming
              ? "Working… press Stop to interrupt"
              : "Ask anything, or ask for an excel, a document or a PDF…"
          }
          className={cn(
            "min-h-[42px] flex-1 rounded-xl border bg-ink-850 px-3.5 py-2.5 text-sm leading-6 text-zinc-200 placeholder-zinc-600 focus:outline-none",
            streaming
              ? "border-ink-700 opacity-60"
              : willBuild
                ? "border-accent/60 focus:border-accent"
                : "border-ink-600 focus:border-accent",
          )}
        />
        {streaming ? (
          <Button variant="outline" onClick={stop} title="Stop generating">
            ■ Stop
          </Button>
        ) : (
          <Button
            variant="primary"
            type="submit"
            disabled={empty}
            title={
              willBuild
                ? `Build a ${format} and file it under Deliverables`
                : "Send"
            }
          >
            {willBuild ? `⚙ Create ${format}` : "↑ Send"}
          </Button>
        )}
      </form>
      {attachError && (
        <p className="mt-1.5 text-[11px] text-rose-400">{attachError}</p>
      )}
      <p className="mt-1.5 text-[10px] leading-relaxed text-zinc-600">
        {willBuild ? (
          <span className="text-accent">
            Reading this as a file request — it will run the agent and produce a{" "}
            {format} you can download here and in Deliverables. Say “as a PDF”
            or “as a spreadsheet” to change the format.
          </span>
        ) : (
          <>
            Answers are grounded in this project&apos;s drawings and documents.
            Ask for a spreadsheet, a document or a PDF and one gets built. 📎
            attaches a drawing · 100% local
          </>
        )}
      </p>
    </div>
  );
}
