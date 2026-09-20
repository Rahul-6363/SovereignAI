"use client";
/** Meshcore agent chat — SSE grounded streaming with status, tool/activity
 *  trace, evidence, confidence, attachments and generated deliverables.
 *
 *  README §0.1 / §7 Phase 0: the Claude-like conversation area of the main
 *  workspace. Supports handoff from the home composer (`initialPrompt`), a
 *  restored conversation (`initialConversationId`) and return from the P&ID
 *  capability (`fromPid`).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { streamSSE } from "@/lib/sse";
import type {
  ActivityStep,
  ChatMessage,
  DeliverableRec,
  EvidencePacket,
  EvidenceSource,
} from "@/lib/types";
import { AutoTextarea, Badge, Button, ConfidenceBar, CopyButton, Spinner, cn } from "./ui";
import ActivityTrace from "./ActivityTrace";
import { DeliverableCards } from "./Deliverables";

const STARTERS = [
  "Trace the process path to P-101.",
  "What instruments are connected to P-101?",
  "Which valves are upstream of P-101?",
  "What evidence supports the connection between L-101 and P-101?",
  "Show uncertain extractions from this drawing.",
];

const STAGE_LABELS: Record<string, string> = {
  session: "Preparing session…",
  intent: "Understanding the question…",
  retrieving: "Searching plant memory…",
  grounding: "Checking P&ID evidence…",
  answering: "Writing the answer…",
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

/** Does this sentence ask for a FILE rather than an answer?
 *
 *  Deliberately narrow: it needs an action verb *and* an artefact noun, so
 *  "what does the report say about P-101" stays a question while "generate a
 *  report on P-101" becomes a task. Mistaking a question for a build request
 *  is the more annoying error — it costs the user a slow agent run to get
 *  something they wanted read back to them — so the bar is set high.
 */
const ARTIFACT_VERB =
  /\b(generate|create|make|produce|build|draft|write|export|prepare|compile|render|give me)\b/i;
const ARTIFACT_NOUN =
  /\b(excel|xlsx|spreadsheet|csv|sheet|docx|word|document|report|tracker|register|inventory|note|moc|deliverable|file|table|list)\b/i;

export function wantsArtifact(text: string): boolean {
  const t = (text ?? "").trim();
  if (!t) return false;
  return ARTIFACT_VERB.test(t) && ARTIFACT_NOUN.test(t);
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
    pinnedRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }, []);

  // Restore a thread whenever the selected one changes — not only on mount.
  // Switching chats in the rail has to swap the transcript, and reopening a
  // thread has to bring back its evidence and its files, or the history is
  // only a transcript of text and every citation and download is lost.
  useEffect(() => {
    setConversationId(initialConversationId);

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

  const submit = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setInput("");
    const userMsg: ChatMessage = {
      id: nextId(),
      role: "user",
      content: q,
      done: true,
    };
    const assistant: ChatMessage = {
      id: nextId(),
      role: "assistant",
      content: "",
      streaming: true,
      stage: "Preparing session…",
      activity: [],
      done: false,
    };
    pinnedRef.current = true;
    setMessages((m) => [...m, userMsg, assistant]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((ms) =>
        ms.map((m) => (m.id === assistant.id ? fn(m) : m)),
      );

    try {
      await streamSSE(
        `/api/projects/${projectId}/chat`,
        { message: q, conversation_id: conversationId ?? undefined },
        (ev) => {
          const d = ev.data;
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
                        detail: stage === "session" && d.conversation_id
                          ? `conversation ${d.conversation_id}`
                          : undefined,
                        status: "active" as const,
                        at: stamp(),
                      },
                    ]
                  : closed,
              };
            });
            if (d.conversation_id) {
              setConversationId(Number(d.conversation_id));
              onConversationChange?.(Number(d.conversation_id));
            }
          } else if (ev.event === "evidence") {
            const packet = d.packet as EvidencePacket;
            patch((m) => ({
              ...m,
              evidence: packet,
              activity: [
                ...(m.activity ?? []).map((s) =>
                  s.status === "active" && s.label.startsWith("Retrieve")
                    ? { ...s, status: "done" as const, detail: `${packet.answer_context?.length ?? 0} sources` }
                    : s,
                ),
              ],
            }));
          } else if (ev.event === "tool") {
            // Forward-compatible: the agent loop (Phase 1) emits typed tool
            // calls; they appear in the same activity trace when connected.
            patch((m) => ({
              ...m,
              activity: [
                ...(m.activity ?? []),
                {
                  id: `t${(m.activity ?? []).length + 1}`,
                  label: `Tool: ${String(d.tool ?? "unknown")}`,
                  detail: d.detail ? String(d.detail) : undefined,
                  status: String(d.status ?? "done") === "failed" ? "failed" : "done",
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
              streaming: false,
              stage: undefined,
              activity: (m.activity ?? []).map((s) =>
                s.status === "active" ? { ...s, status: "done" as const } : s,
              ),
              done: true,
            }));
          } else if (ev.event === "done_meta") {
            if (d.conversation_id) {
              setConversationId(Number(d.conversation_id));
              onConversationChange?.(Number(d.conversation_id));
            }
          } else if (ev.event === "error") {
            patch((m) => ({
              ...m,
              error: String(d.message ?? "Unknown error"),
              streaming: false,
              done: true,
            }));
          }
        },
        controller.signal,
      );
      patch((m) => ({ ...m, streaming: false, done: true }));
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === "AbortError";
      patch((m) => ({
        ...m,
        error: aborted ? "" : e instanceof Error ? e.message : String(e),
        streaming: false,
        done: true,
      }));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  // ── agent task: bounded loop that produces a downloadable artefact ──
  const runAgentTask = async (question: string) => {
    const q = question.trim();
    if (!q || streaming) return;
    setInput("");
    const userMsg: ChatMessage = {
      id: nextId(), role: "user", content: q, done: true,
    };
    const assistant: ChatMessage = {
      id: nextId(), role: "assistant", content: "",
      streaming: true, stage: "Planning the task…", activity: [], done: false,
    };
    pinnedRef.current = true;
    setMessages((m) => [...m, userMsg, assistant]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const patch = (fn: (m: ChatMessage) => ChatMessage) =>
      setMessages((ms) => ms.map((m) => (m.id === assistant.id ? fn(m) : m)));

    try {
      await streamSSE(
        `/api/projects/${projectId}/agent`,
        { prompt: q, conversation_id: conversationId ?? undefined },
        (ev) => {
          const d = ev.data;
          // An agent turn belongs to the same thread as the chat turns around
          // it, so the id it resolves has to reach both this pane and the rail.
          if (d.conversation_id) {
            const cid = Number(d.conversation_id);
            if (cid !== conversationId) {
              setConversationId(cid);
              onConversationChange?.(cid);
            }
          }
          if (ev.event === "plan") {
            const steps = (d.steps as { tool: string; why: string }[]) ?? [];
            patch((m) => ({
              ...m,
              stage: `Plan: ${steps.map((s) => s.tool).join(" -> ")}`,
              activity: steps.map((s, i) => ({
                id: `p${i}`,
                label: `${s.tool} — ${s.why}`,
                status: "pending" as const,
                at: stamp(),
              })),
            }));
          } else if (ev.event === "policy") {
            if (String(d.decision) === "deny") {
              patch((m) => ({
                ...m,
                activity: (m.activity ?? []).map((s) =>
                  s.label.startsWith(String(d.tool))
                    ? { ...s, status: "failed" as const, detail: String(d.reason) }
                    : s,
                ),
              }));
            }
          } else if (ev.event === "tool") {
            const tool = String(d.tool);
            const status = String(d.status);
            patch((m) => ({
              ...m,
              stage: status === "running" ? `Running ${tool}…` : m.stage,
              activity: (m.activity ?? []).map((s) =>
                s.label.startsWith(tool) && s.status !== "done"
                  ? {
                      ...s,
                      status:
                        status === "done"
                          ? ("done" as const)
                          : status === "failed"
                            ? ("failed" as const)
                            : ("active" as const),
                      detail: d.detail ? String(d.detail) : s.detail,
                      at: stamp(),
                    }
                  : s,
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
            const budget = d.budget as Record<string, number> | undefined;
            const calc = d.calculation as Record<string, unknown> | undefined;
            const failures = (d.failures as string[]) ?? [];

            const lines: string[] = [];
            if (artifacts.length) {
              lines.push(
                `Produced **${artifacts.length}** deliverable${
                  artifacts.length > 1 ? "s" : ""
                } from ${d.evidence_count ?? 0} retrieved sources.`,
              );
            } else if (failures.length) {
              lines.push("The task did not produce an artefact.");
            } else {
              lines.push(
                `Retrieved ${d.evidence_count ?? 0} sources for this question.`,
              );
            }
            if (calc) {
              lines.push(
                `\n\n**Calculation ${calc.calculation_id}:** ${calc.result} ` +
                  `${calc.unit} — \`${calc.formula}\`\nStatus: ${calc.status}. ` +
                  "The number came from the deterministic engine, not from a " +
                  "language model.",
              );
            }
            if (failures.length) {
              lines.push(`\n\n_Blocked:_ ${failures.join("; ")}`);
            }
            if (budget) {
              lines.push(
                `\n\n_Budget: ${budget.tool_calls}/${budget.max_tool_calls} tool ` +
                  `calls, ${budget.replans}/${budget.max_replans} replans, ` +
                  `${budget.elapsed_s}s of ${budget.wall_clock_seconds}s._`,
              );
            }
            patch((m) => ({
              ...m,
              content: lines.join(""),
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
              ...m, error: String(d.message ?? "Unknown error"),
              streaming: false, done: true,
            }));
          }
        },
        controller.signal,
      );
      patch((m) => ({ ...m, streaming: false, done: true }));
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === "AbortError";
      patch((m) => ({
        ...m,
        error: aborted ? "" : e instanceof Error ? e.message : String(e),
        streaming: false,
        done: true,
      }));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  // ── one input, two paths ─────────────────────────────────────────────
  // Asking a question and asking for a file are different operations here:
  // one streams a grounded answer, the other runs the bounded agent and
  // produces a DOCX or XLSX. Making the user choose the right button first
  // is the kind of thing that should be inferred, so it is — from whether
  // the sentence asks for an artefact. The explicit Build button stays for
  // when the guess is wrong.
  const send = (question: string) => {
    if (wantsArtifact(question)) return runAgentTask(question);
    return submit(question);
  };

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
            label: `Upload ${file.name}`,
            status: "active",
            at: stamp(),
          },
        ],
        done: false,
      };
      setMessages((m) => [...m, userMsg, assistant]);
      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((ms) =>
          ms.map((m) => (m.id === assistant.id ? fn(m) : m)),
        );
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
      />
      <Composer
        input={input}
        setInput={setInput}
        send={send}
        runAgentTask={runAgentTask}
        streaming={streaming}
        stop={() => abortRef.current?.abort()}
        starters={messages.length === 0 ? STARTERS : []}
        attaching={attaching}
        attachError={attachError}
        onAttachClick={() => fileRef.current?.click()}
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
}: {
  messages: ChatMessage[];
  onEvidence: (src: EvidenceSource) => void;
  scrollRef: React.RefObject<HTMLDivElement | null>;
  onScroll?: () => void;
  projectId: number;
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
              {m.content}
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
            {m.content && <AnswerBody text={m.content} />}
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
                {m.content && <CopyButton text={m.content} className="ml-auto" />}
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
            <p className="text-sm text-zinc-500">
              Answers are grounded in extracted plant memory with visible
              evidence — and the tool/activity trace shows how each answer was
              produced, or the system says so.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** Markdown-lite renderer: `code`, **bold**, _em_, newlines. */
function AnswerBody({ text }: { text: string }) {
  const blocks = text.split(/\n\n+/);
  return (
    <div className="answer-body space-y-3 text-sm leading-relaxed text-zinc-200">
      {blocks.map((b, i) => (
        <p key={i} className="whitespace-pre-wrap">
          {renderInline(b)}
        </p>
      ))}
    </div>
  );
}

function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|_[^_]+_)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) {
      out.push(<code key={k++}>{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith("**")) {
      out.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    } else {
      out.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
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
  runAgentTask,
  streaming,
  stop,
  starters,
  attaching,
  attachError,
  onAttachClick,
}: {
  input: string;
  setInput: (v: string) => void;
  /** Routes to an answer or a build, whichever the sentence asks for. */
  send: (q: string) => void;
  runAgentTask: (q: string) => void;
  streaming: boolean;
  stop: () => void;
  starters: string[];
  attaching: boolean;
  attachError: string;
  onAttachClick: () => void;
}) {
  // Shown live, so the routing decision is never a surprise after the fact.
  const willBuild = wantsArtifact(input);

  return (
    <div className="border-t border-ink-700 bg-ink-950/80 px-6 py-4">
      {starters.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {starters.map((s) => (
            <button
              key={s}
              onClick={() => send(s)}
              className="rounded-full border border-ink-600 px-3 py-1 text-xs text-zinc-400 transition-colors hover:border-accent hover:text-zinc-200"
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
          send(input);
        }}
      >
        <button
          type="button"
          onClick={onAttachClick}
          disabled={attaching}
          title="Attach a PDF or drawing to this project"
          className="grid h-[42px] w-[42px] shrink-0 place-items-center rounded-xl border border-ink-600 text-zinc-400 transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
        >
          {attaching ? <Spinner className="h-4 w-4" /> : "📎"}
        </button>
        <AutoTextarea
          value={input}
          onChange={setInput}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          maxRows={8}
          placeholder="Ask anything, or ask for a document or spreadsheet…"
          className="min-h-[42px] flex-1 rounded-xl border border-ink-600 bg-ink-850 px-3.5 py-2.5 text-sm leading-6 text-zinc-200 placeholder-zinc-600 focus:border-accent focus:outline-none"
        />
        {streaming ? (
          <Button variant="outline" onClick={stop} title="Stop generating">
            ■ Stop
          </Button>
        ) : (
          <>
            {!willBuild && input.trim() !== "" && (
              <Button
                variant="outline"
                onClick={() => runAgentTask(input)}
                title="Force the agent path — produces a DOCX or XLSX"
              >
                ⚙ Build
              </Button>
            )}
            <Button variant="primary" type="submit" disabled={!input.trim()}>
              {willBuild ? "⚙ Create" : "↑ Send"}
            </Button>
          </>
        )}
      </form>
      {attachError && (
        <p className="mt-1.5 text-[11px] text-rose-400">{attachError}</p>
      )}
      <p className="mt-1.5 text-[10px] leading-relaxed text-zinc-600">
        {willBuild ? (
          <span className="text-accent">
            This looks like a file request — it will run the agent and produce
            a document you can download right here.
          </span>
        ) : (
          <>
            Answers are grounded in this project&apos;s drawings and documents.
            Ask for a spreadsheet or a report and one gets built. 📎 attaches a
            drawing · 100% local
          </>
        )}
      </p>
    </div>
  );
}
