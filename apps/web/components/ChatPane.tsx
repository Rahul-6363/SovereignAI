"use client";
/** Meshcore agent chat — SSE streaming with modes, evidence and deliverables.
 *
 *  Layout follows the shape a conversation actually needs rather than the
 *  shape a dashboard does: one centred reading column, user turns as compact
 *  bubbles, assistant turns as unboxed prose at full column width. Chrome
 *  (evidence, provenance, context budget) sits *under* the answer and stays
 *  folded until asked for, so the default view of a thread is the thread.
 *
 *  One composer, one button. Asking a question and asking for a file are two
 *  different operations on the backend — one streams an answer, the other
 *  runs the bounded agent and renders an XLSX, DOCX or PDF — but which one
 *  the user wants is already stated in their sentence, so the sentence
 *  decides. There is no Build button and no format picker.
 *
 *  The mode switcher is the one deliberate exception to "the sentence
 *  decides". Whether a question should be answered from this plant's
 *  documents or from the model's own knowledge is genuinely ambiguous in the
 *  sentence — "how does a relief valve work" is a fair question in either —
 *  and guessing wrong is expensive in both directions. So it is a choice,
 *  made once, visible at all times, and remembered.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import type {
  ActivityStep,
  ChatMessage,
  ChatMode,
  ChatModeSpec,
  ContextReport,
  DeliverableRec,
  EvidencePacket,
  EvidenceSource,
} from "@/lib/types";
import {
  AutoTextarea,
  ConfidenceBar,
  CopyButton,
  IconButton,
  SegmentedControl,
  Spinner,
  cn,
} from "./ui";
import {
  IconAlert,
  IconArrowRight,
  IconArrowUp,
  IconBrain,
  IconCheck,
  IconCode,
  IconPaperclip,
  IconRefresh,
  IconSchematic,
  IconSparkles,
  IconStop,
  IconX,
} from "./icons";
import ActivityTrace from "./ActivityTrace";
import { DeliverableCards } from "./Deliverables";
import Markdown from "./Markdown";

export const CHAT_MODES: ChatModeSpec[] = [
  {
    id: "plant",
    label: "Plant",
    hint: "Reads this project's drawings and documents. Cites every plant-specific claim, and builds files on request.",
    placeholder: "Ask about this plant — or ask for an excel, a document or a PDF…",
  },
  {
    id: "general",
    label: "General",
    hint: "The model's own knowledge. No retrieval and no citations — nothing here is about your plant unless you say so.",
    placeholder: "Ask anything…",
  },
  {
    id: "code",
    label: "Code",
    hint: "Writes and reviews code. This workstation is air-gapped, so it sticks to the standard library and what you already have.",
    placeholder: "Describe what to build, or paste code to review…",
  },
  {
    id: "think",
    label: "Think",
    hint: "Works the problem through visibly before answering. Two passes, so roughly twice the wait.",
    placeholder: "Give it something worth working through…",
  },
];

/** Mode -> glyph. Separate from the spec because the spec is plain data
 *  that crosses into `lib/types`, and a React element is not. */
const MODE_ICON: Record<ChatMode, (p: { size?: number }) => React.ReactElement> = {
  plant: IconSchematic,
  general: IconSparkles,
  code: IconCode,
  think: IconBrain,
};

const MODE_BY_ID = new Map(CHAT_MODES.map((m) => [m.id, m]));
const MODE_STORAGE_KEY = "meshcore.chat.mode";

const STARTERS_BY_MODE: Record<ChatMode, string[]> = {
  plant: [
    "What instruments are connected to P-101?",
    "Build an excel tracker of every instrument.",
    "Draft a PDF change note for valve CV-104.",
    "Prepare the complete deliverables package for this drawing.",
  ],
  general: [
    "How does a pressure relief valve actually work?",
    "Explain ISA-5.1 instrument tag numbering.",
    "What is the difference between a SIS and a BPCS?",
  ],
  code: [
    "Parse a P&ID tag list from CSV into typed records.",
    "Write a retry decorator with exponential backoff.",
    "Review this function for edge cases.",
  ],
  think: [
    "Which of our unit's relief scenarios is most likely under-sized, and why?",
    "Work out a migration plan from the current tag scheme to ISA-5.1.",
  ],
};

const STAGE_LABELS: Record<string, string> = {
  session: "Preparing session…",
  intent: "Understanding the question…",
  retrieving: "Searching plant memory…",
  grounding: "Checking P&ID evidence…",
  thinking: "Working it through…",
  answering: "Writing the answer…",
  intake: "Working out what to build…",
  policy: "Applying policy…",
  blocked: "Stopping — output blocked",
  budget: "Stopping — budget spent",
};

/** status stage → activity-trace label (the visible tool/activity trace). */
const STAGE_STEPS: Record<string, string> = {
  session: "Open session + resolve clearance",
  intent: "Classify intent",
  retrieving: "Retrieve evidence (graph + hybrid index)",
  grounding: "Build grounded evidence packet",
  thinking: "Reason about the question",
  answering: "Synthesise answer",
};

let _id = 0;
const nextId = () => `m${++_id}`;
const stamp = () => new Date().toLocaleTimeString();

/* ── routing: does this sentence ask for a FILE or for an answer? ──
 *
 * Three rules, in order:
 *
 *   1. A question form with no build verb is a question. "What does the
 *      report say about P-101" must not run a 3-minute agent task to hand
 *      back something the user wanted read out.
 *   2. A build verb plus an artefact noun is a build.
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

/** Only these modes can spend three minutes producing a file.
 *
 *  Code mode is the reason this exists: "write a python file that parses the
 *  tag list" trips every rule in `wantsArtifact`, and routing it to the
 *  document agent would answer a coding question with an empty spreadsheet.
 *  Think mode is excluded because its whole point is the visible reasoning,
 *  which the agent path does not produce.
 */
const BUILDING_MODES: ReadonlySet<ChatMode> = new Set<ChatMode>([
  "plant",
  "general",
]);

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
 *  that used a tool twice — the MOC and project plans retrieve twice —
 *  because both rows went active together and then both went done, so the
 *  trace claimed work that had not happened yet.
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
   *  sync with the conversation. */
  onDeliverables?: (items: DeliverableRec[]) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ChatMode>("plant");
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
  const modeRef = useRef<ChatMode>("plant");

  // The mode is a working preference, not thread state: someone who works in
  // Code mode should not be dropped back into Plant on every reload.
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem(MODE_STORAGE_KEY);
      if (saved && MODE_BY_ID.has(saved as ChatMode)) {
        setMode(saved as ChatMode);
        modeRef.current = saved as ChatMode;
      }
    } catch {
      /* storage blocked — the default mode is fine */
    }
  }, []);

  const changeMode = useCallback((next: ChatMode) => {
    setMode(next);
    modeRef.current = next;
    try {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      /* non-fatal */
    }
  }, []);

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
      setMessages([]); // "New chat" starts genuinely empty
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
      mode: modeRef.current,
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
      error:
        error && !aborted
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

  // ── answer path: streams tokens from the chat endpoint ──────────────
  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setInput("");
    const { patch, controller } = openTurn(q, STAGE_LABELS.session);

    try {
      await streamSSE(
        `/api/projects/${projectId}/chat`,
        {
          message: q,
          conversation_id: conversationRef.current ?? undefined,
          mode: modeRef.current,
        },
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
                            : d.detail
                              ? String(d.detail)
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
          } else if (ev.event === "reasoning") {
            patch((m) => ({
              ...m,
              reasoning: (m.reasoning ?? "") + String(d.text ?? ""),
            }));
          } else if (ev.event === "token") {
            patch((m) => ({ ...m, content: m.content + String(d.text ?? "") }));
          } else if (ev.event === "replace") {
            // Output screening rejected what streamed. Replace it rather than
            // appending, so the rejected text does not stay on screen under
            // the notice saying it was rejected.
            patch((m) => ({ ...m, content: String(d.text ?? "") }));
          } else if (ev.event === "done") {
            patch((m) => ({
              ...m,
              content: String(d.message ?? m.content),
              confidence: Number(d.confidence ?? 0),
              claims: (d.claims as ChatMessage["claims"]) ?? [],
              sources: (d.sources as ChatMessage["sources"]) ?? [],
              intent: String(d.intent ?? ""),
              model: String(d.model ?? ""),
              mode: (d.mode as ChatMode) ?? m.mode,
              reasoning: String(d.reasoning ?? m.reasoning ?? ""),
              refused: d.refused ? String(d.refused) : undefined,
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
              stage: String(d.detail ?? "") || STAGE_LABELS[stage] || m.stage,
            }));
          } else if (ev.event === "phases") {
            // A package run decomposes before it plans. Shown as the turn's
            // reasoning, which is exactly what it is.
            const phases = (d.phases as { phase: string; detail: string }[]) ?? [];
            patch((m) => ({
              ...m,
              reasoning: phases
                .map((p, i) => `${i + 1}. **${p.phase}** — ${p.detail}`)
                .join("\n"),
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
              refused: d.refused ? String(d.refused) : undefined,
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
      if (BUILDING_MODES.has(modeRef.current) && wantsArtifact(question)) {
        return runAgentTask(question);
      }
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

  // ── chat-composer file attachment ────────────────────────────────────
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
    // Retry in the mode that produced it, not whatever is selected now.
    const previous = modeRef.current;
    if (lastAssistant?.mode) modeRef.current = lastAssistant.mode;
    void send(prompt);
    modeRef.current = previous;
  }, [lastAssistant?.prompt, lastAssistant?.mode, streaming, send]);

  const spec = MODE_BY_ID.get(mode) ?? CHAT_MODES[0];

  return (
    <div className="flex h-full min-h-0 flex-col bg-ink-900">
      {fromPid && (
        <div className="border-b border-ink-800 bg-accent/[0.06] px-6 py-2 text-[11px] text-zinc-400">
          <span className="text-accent">Returned from P&amp;ID.</span> The
          drawing context and extracted plant memory of this project are already
          available to the agent below.
        </div>
      )}
      {historyLoading && (
        <div className="flex items-center gap-2 border-b border-ink-800 px-6 py-2 text-[11px] text-zinc-500">
          <Spinner className="h-3 w-3" /> Restoring conversation history…
        </div>
      )}
      <MessageList
        messages={messages}
        onEvidence={onSelectEvidence}
        scrollRef={scrollRef}
        onScroll={onScroll}
        projectId={projectId}
        spec={spec}
        onStarter={(s) => send(s)}
        streaming={streaming}
        retryableId={
          !streaming && lastAssistant?.prompt ? lastAssistant.id : null
        }
        onRetry={retry}
      />
      <Composer
        input={input}
        setInput={setInput}
        send={send}
        mode={mode}
        setMode={changeMode}
        streaming={streaming}
        stop={() => abortRef.current?.abort()}
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

/** The centred reading column every turn is laid out in. */
const COLUMN = "mx-auto w-full max-w-3xl px-6";

function MessageList({
  messages,
  onEvidence,
  scrollRef,
  onScroll,
  projectId,
  spec,
  onStarter,
  streaming,
  retryableId,
  onRetry,
}: {
  messages: ChatMessage[];
  onEvidence: (src: EvidenceSource) => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onScroll?: () => void;
  projectId: number;
  spec: ChatModeSpec;
  onStarter: (s: string) => void;
  streaming: boolean;
  retryableId: string | null;
  onRetry: () => void;
}) {
  if (messages.length === 0) {
    return (
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <EmptyThread spec={spec} onStarter={onStarter} streaming={streaming} />
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="min-h-0 flex-1 overflow-y-auto py-8"
    >
      {messages.map((m) =>
        m.role === "user" ? (
          <div key={m.id} className={cn(COLUMN, "mb-6 animate-fade-in")}>
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-2xl rounded-br-md bg-ink-800 px-4 py-2.5 text-[15px] leading-relaxed text-zinc-100">
                <span className="whitespace-pre-wrap">{m.content}</span>
                {m.attachments && m.attachments.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.attachments.map((a) => (
                      <span
                        key={a.name}
                        className="rounded-md border border-ink-600 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400"
                      >
                        {a.name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <AssistantTurn
            key={m.id}
            m={m}
            onEvidence={onEvidence}
            projectId={projectId}
            retryable={m.id === retryableId}
            onRetry={onRetry}
          />
        ),
      )}
    </div>
  );
}

/** One assistant turn: reasoning, trace, answer, then the evidence chrome. */
function AssistantTurn({
  m,
  onEvidence,
  projectId,
  retryable,
  onRetry,
}: {
  m: ChatMessage;
  onEvidence: (src: EvidenceSource) => void;
  projectId: number;
  retryable: boolean;
  onRetry: () => void;
}) {
  return (
    <div className={cn(COLUMN, "group mb-10 animate-fade-in")}>
      {m.stage && (
        <div className="mb-3 flex items-center gap-2 text-xs text-zinc-500">
          <Spinner className="h-3 w-3" />
          {m.stage}
        </div>
      )}

      {m.reasoning && (
        <ReasoningBlock text={m.reasoning} live={Boolean(m.streaming)} />
      )}

      {(m.activity?.length ?? 0) > 0 && <TraceDisclosure steps={m.activity!} />}

      {m.refused && (
        <div className="mb-3 flex items-center gap-2 text-[11px] font-medium uppercase tracking-wider text-amber-400/90">
          <IconAlert size={13} /> Declined on policy
        </div>
      )}

      {m.content && (
        <div className="answer-body text-[15px] leading-[1.7] text-zinc-200">
          <Markdown text={m.content} />
        </div>
      )}

      {/* A caret while the model is mid-sentence, so a slow local model is
          visibly working rather than apparently finished. */}
      {m.streaming && (
        <span
          aria-hidden
          className="ml-0.5 inline-block h-4 w-[2px] translate-y-[3px] animate-pulse-dot bg-accent"
        />
      )}

      {m.stopped && (
        <p className="mt-3 text-[11px] italic text-zinc-500">
          Stopped. The answer above is incomplete.
        </p>
      )}

      {m.deliverables && m.deliverables.length > 0 && (
        <DeliverableCards items={m.deliverables} compact projectId={projectId} />
      )}

      {m.error && (
        <div className="mt-3 rounded-xl border border-rose-900/50 bg-rose-950/30 px-3.5 py-2.5 text-xs text-rose-300">
          {m.error}
        </div>
      )}

      {m.evidence && <EvidenceChips packet={m.evidence} onEvidence={onEvidence} />}

      {/* Hover actions, Claude-style: present but not competing with the
          answer until the pointer is in the turn. Keyboard focus reveals
          them too, so they are not pointer-only affordances. */}
      {m.done && (m.content || m.error) && (
        <div className="mt-3 flex items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
          {m.content && <CopyButton text={m.content} />}
          {retryable && (
            <button
              onClick={onRetry}
              title="Run this question again"
              className="inline-flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-[11px] text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300"
            >
              <IconRefresh size={13} /> Retry
            </button>
          )}
          {m.mode && m.mode !== "plant" && (
            <span className="rounded-md px-1.5 py-0.5 font-mono text-[10px] text-zinc-600">
              {MODE_BY_ID.get(m.mode)?.label ?? m.mode}
            </span>
          )}
          {m.confidence !== undefined && m.confidence > 0 && (
            <span className="ml-1 w-28">
              <ConfidenceBar value={m.confidence} />
            </span>
          )}
          {m.context && <ContextBadge report={m.context} />}
        </div>
      )}

      {m.done && <WhyThisAnswer message={m} />}
    </div>
  );
}

/** Think mode's scratchpad — folded by default, like extended thinking.
 *
 *  Expanded while it streams, because watching it is the point of asking for
 *  it; collapsed once the answer arrives, because by then the answer is.
 */
function ReasoningBlock({ text, live }: { text: string; live: boolean }) {
  const [open, setOpen] = useState(live);
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live) setOpen(false);
    wasLive.current = live;
  }, [live]);

  return (
    <div className="mb-4 rounded-xl border border-ink-800 bg-ink-850/50">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3.5 py-2 text-left text-[11px] font-medium text-zinc-400 transition-colors hover:text-zinc-200"
      >
        <span className={cn("text-accent", live && "animate-pulse-dot")}>
          <IconBrain size={14} />
        </span>
        {live ? "Thinking…" : "Thought process"}
        <span className="ml-auto text-zinc-600">{open ? "−" : "+"}</span>
      </button>
      {open && (
        <div className="border-t border-ink-800 px-3.5 py-2.5 text-[13px] leading-relaxed text-zinc-500">
          <Markdown text={text} />
        </div>
      )}
    </div>
  );
}

/** The tool trace, folded. It is evidence of *how*, not part of the answer.
 *
 *  It used to render expanded above every turn, which meant the first thing
 *  in the reading column was a list of internal step names — useful once,
 *  noise on the forty-first answer.
 */
function TraceDisclosure({ steps }: { steps: ActivityStep[] }) {
  const [open, setOpen] = useState(false);
  const running = steps.some((s) => s.status === "active" || s.status === "pending");
  const failed = steps.filter((s) => s.status === "failed").length;
  const done = steps.filter((s) => s.status === "done").length;

  return (
    <div className="mb-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1.5 rounded-md text-[11px] text-zinc-600 transition-colors hover:text-zinc-400"
      >
        <span
          className={cn(
            "grid place-items-center",
            failed ? "text-rose-400" : running ? "text-amber-400" : "text-zinc-600",
          )}
        >
          {running ? (
            <span className="h-1.5 w-1.5 animate-pulse-dot rounded-full bg-current" />
          ) : failed ? (
            <IconX size={12} />
          ) : (
            <IconCheck size={12} />
          )}
        </span>
        {running
          ? `${done}/${steps.length} steps`
          : failed
            ? `${steps.length} steps · ${failed} failed`
            : `${steps.length} steps`}
        <span className="text-zinc-700">{open ? "hide" : "show work"}</span>
      </button>
      {open && <ActivityTrace steps={steps} className="mt-2" />}
    </div>
  );
}

/** The screen a thread starts on. */
function EmptyThread({
  spec,
  onStarter,
  streaming,
}: {
  spec: ChatModeSpec;
  onStarter: (s: string) => void;
  streaming: boolean;
}) {
  const Icon = MODE_ICON[spec.id];
  return (
    <div className="flex min-h-full items-center">
      <div className={cn(COLUMN, "py-12")}>
        <div className="mb-3 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-2xl bg-accent/12 text-accent">
            <Icon size={19} />
          </span>
          <h2 className="text-[26px] font-medium tracking-tight text-zinc-100">
            {spec.label} mode
          </h2>
        </div>
        <p className="mb-7 max-w-xl text-[15px] leading-relaxed text-zinc-500">
          {spec.hint}
        </p>
        <div className="flex flex-col items-start gap-1.5">
          {STARTERS_BY_MODE[spec.id].map((s) => (
            <button
              key={s}
              onClick={() => onStarter(s)}
              disabled={streaming}
              className="group/s flex w-full items-center gap-2 rounded-xl border border-ink-800 px-3.5 py-2.5 text-left text-sm text-zinc-400 transition-colors hover:border-ink-600 hover:bg-ink-850 hover:text-zinc-200 disabled:opacity-40"
            >
              <span className="min-w-0 flex-1">{s}</span>
              <IconArrowRight
                size={14}
                className="shrink-0 text-zinc-700 transition-colors group-hover/s:text-accent"
              />
            </button>
          ))}
        </div>
      </div>
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
        <div className="absolute bottom-full right-0 z-10 mb-1 w-72 animate-slide-up rounded-2xl border border-ink-700 bg-ink-850 p-3 text-left shadow-pop">
          <div className="mb-1.5 text-[11px] font-semibold text-zinc-300">
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
            <ul className="mt-2 space-y-0.5 border-t border-ink-800 pt-2 text-[11px] text-amber-400/80">
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
          className="rounded-lg border border-ink-700 bg-ink-850 px-2 py-1 text-left text-[11px] text-zinc-300 transition-colors hover:border-accent hover:text-zinc-100"
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
                  {" "}
                  · {c.document}
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
    <div className="mt-4 rounded-xl border border-ink-800 bg-ink-850/40 p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
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
        className="text-xs text-zinc-600 underline-offset-2 hover:text-zinc-400 hover:underline"
      >
        {open ? "Hide provenance" : "Why this answer?"}
      </button>
      {open && (
        <div className="mt-2 space-y-3 rounded-xl border border-ink-800 bg-ink-850 p-3.5 text-xs">
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
                    ? (s.relation ?? "graph link")
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

/** The composer: one box, controls inside it.
 *
 *  The mode pills live in the same rounded container as the textarea rather
 *  than in a toolbar above it, because the mode is part of what you are about
 *  to send — the same reason the send button is in there and not beside it.
 */
function Composer({
  input,
  setInput,
  send,
  mode,
  setMode,
  streaming,
  stop,
  attaching,
  attachError,
  onAttachClick,
  textareaRef,
}: {
  input: string;
  setInput: (v: string) => void;
  /** Routes to an answer or a build, whichever the sentence asks for. */
  send: (q: string) => void;
  mode: ChatMode;
  setMode: (m: ChatMode) => void;
  streaming: boolean;
  stop: () => void;
  attaching: boolean;
  attachError: string;
  onAttachClick: () => void;
  textareaRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  // Shown live, so the routing decision is never a surprise after the fact.
  const willBuild = BUILDING_MODES.has(mode) && wantsArtifact(input);
  const format = willBuild ? detectFormat(input) : null;
  const empty = input.trim() === "";
  const spec = MODE_BY_ID.get(mode) ?? CHAT_MODES[0];

  // Focus returns to the composer the moment a turn ends, so a follow-up is
  // typed rather than clicked-then-typed.
  useEffect(() => {
    if (!streaming) textareaRef.current?.focus();
  }, [streaming, textareaRef]);

  const footnote = useMemo(() => {
    if (willBuild)
      return `Reading this as a file request — it will run the agent and produce a ${format} you can download here and in Deliverables.`;
    if (mode === "plant")
      return "Grounded in this project's drawings and documents · 100% local";
    if (mode === "code")
      return "Air-gapped: no package downloads, so answers stay on the standard library and what you have.";
    if (mode === "think")
      return "Two passes — the reasoning streams first, then the answer.";
    return "General knowledge · not about your plant unless you say so · 100% local";
  }, [willBuild, format, mode]);

  return (
    <div className="border-t border-ink-800 bg-ink-900 pb-4 pt-3">
      <div className={COLUMN}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!streaming) send(input);
          }}
          className={cn(
            "rounded-2xl border bg-ink-850 shadow-panel transition-colors",
            streaming
              ? "border-ink-800 opacity-70"
              : willBuild
                ? "border-accent/50 focus-within:border-accent"
                : "border-ink-700 focus-within:border-ink-600",
          )}
        >
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
            minRows={1}
            maxRows={12}
            placeholder={
              streaming ? "Working… press Stop to interrupt" : spec.placeholder
            }
            className="w-full bg-transparent px-4 pb-1 pt-3.5 text-[15px] leading-6 text-zinc-100 placeholder-zinc-600 focus:outline-none"
          />

          <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
            <IconButton
              icon={
                attaching ? (
                  <Spinner className="h-4 w-4" />
                ) : (
                  <IconPaperclip size={16} />
                )
              }
              label="Attach a PDF or drawing to this project"
              size="sm"
              disabled={attaching || streaming}
              onClick={onAttachClick}
            />

            <ModeSwitch mode={mode} setMode={setMode} disabled={streaming} />

            <div className="ml-auto flex items-center gap-2">
              {willBuild && (
                <span className="hidden shrink-0 rounded-md bg-accent/15 px-2 py-1 font-mono text-[10px] text-accent sm:block">
                  → {format}
                </span>
              )}
              {streaming ? (
                <IconButton
                  icon={<IconStop size={14} />}
                  label="Stop generating"
                  size="sm"
                  variant="outline"
                  onClick={stop}
                />
              ) : (
                <button
                  type="submit"
                  disabled={empty}
                  title={
                    willBuild
                      ? `Build a ${format} and file it under Deliverables`
                      : "Send"
                  }
                  className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-white shadow-raised transition-colors hover:bg-accent-soft disabled:bg-ink-800 disabled:text-zinc-700"
                >
                  <IconArrowUp size={16} />
                </button>
              )}
            </div>
          </div>
        </form>

        {attachError && (
          <p className="mt-1.5 text-[11px] text-rose-400">{attachError}</p>
        )}
        <p
          className={cn(
            "mt-2 text-center text-[11px] leading-relaxed",
            willBuild ? "text-accent/90" : "text-zinc-600",
          )}
        >
          {footnote}
        </p>
      </div>
    </div>
  );
}

/** Segmented mode control.
 *
 *  Uses the shared primitive rather than a private copy, so the chat mode
 *  switch and the deliverables type filter cannot drift into two different
 *  looking controls doing the same job.
 */
function ModeSwitch({
  mode,
  setMode,
  disabled,
}: {
  mode: ChatMode;
  setMode: (m: ChatMode) => void;
  disabled: boolean;
}) {
  return (
    <SegmentedControl
      size="sm"
      value={mode}
      onChange={setMode}
      disabled={disabled}
      ariaLabel="Chat mode"
      options={CHAT_MODES.map((m) => {
        const Icon = MODE_ICON[m.id];
        return {
          value: m.id,
          label: m.label,
          title: m.hint,
          icon: <Icon size={13} />,
        };
      })}
    />
  );
}
