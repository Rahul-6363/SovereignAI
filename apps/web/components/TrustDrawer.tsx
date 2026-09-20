"use client";
/** Screen 5 — Trust drawer: local-only guarantees, models, audit log. */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AuditEventRec, TrustStatus } from "@/lib/types";
import { Badge, Button, Spinner, StatusDot, cn } from "./ui";

export default function TrustDrawer({
  open,
  onClose,
  onStatus,
}: {
  open: boolean;
  onClose: () => void;
  onStatus?: (ok: boolean) => void;
}) {
  const [status, setStatus] = useState<TrustStatus | null>(null);
  const [audit, setAudit] = useState<AuditEventRec[]>([]);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"runtime" | "audit">("runtime");

  useEffect(() => {
    if (!open) return;
    (async () => {
      try {
        const s = await api.trustStatus();
        setStatus(s);
        onStatus?.(s.ollama_connected);
        setAudit(await api.trustAudit(30));
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [open, onStatus]);

  if (!open) return null;

  const guarantees = [
    {
      ok: status?.ollama_connected,
      label: "Local inference (Ollama)",
      detail: status?.ollama_connected
        ? `active model: ${status.active_model}`
        : "Ollama not reachable",
    },
    {
      ok: status ? status.external_llm_calls === 0 : null,
      label: "Zero external LLM calls",
      detail: `${status?.external_llm_calls ?? "—"} external calls this session`,
    },
    {
      ok: status ? status.network_egress.toLowerCase() === "blocked" : null,
      label: "Network egress blocked",
      detail: status?.network_egress ?? "—",
    },
    {
      ok: status?.documents_local,
      label: "Documents stay on device",
      detail: "uploads & pages stored locally",
    },
    {
      ok: status?.audit_logging,
      label: "Audit logging enabled",
      detail: "every AI action is recorded",
    },
  ];
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50"
      onClick={onClose}
      role="dialog"
      aria-label="Trust Center"
    >
      <div
        className="flex h-full w-[420px] flex-col border-l border-ink-800 bg-ink-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-ink-800 px-4 py-3">
          <h2 className="text-sm font-semibold text-zinc-100">Trust Center</h2>
          <Button variant="ghost" onClick={onClose} className="px-2">
            ✕
          </Button>
        </div>

        <div className="flex gap-1 border-b border-ink-800 px-4 py-2">
          {(["runtime", "audit"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={
                t === tab
                  ? "rounded-md bg-ink-700 px-3 py-1 text-xs text-zinc-100"
                  : "rounded-md px-3 py-1 text-xs text-zinc-500 hover:text-zinc-300"
              }
            >
              {t === "runtime" ? "Runtime" : "Audit log"}
            </button>
          ))}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {error && (
            <div className="mb-3 rounded-lg border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          )}
          {!status && !error && (
            <div className="flex items-center gap-2 text-sm text-zinc-500">
              <Spinner /> Checking runtime…
            </div>
          )}
          {status && tab === "runtime" && <RuntimeTab status={status} />}
          {tab === "audit" && <AuditTab audit={audit} />}
        </div>

        <div className="border-t border-ink-800 px-4 py-3 text-[10px] leading-relaxed text-zinc-600">
          This workbench runs entirely on your machine. No prompt, document or
          extracted entity ever leaves the device.
        </div>
      </div>
    </div>
  );
}
function RuntimeTab({ status }: { status: TrustStatus }) {
  const guarantees = [
    {
      ok: status.ollama_connected,
      label: "Local inference (Ollama)",
      detail: status.ollama_connected
        ? `active model: ${status.active_model}`
        : "Ollama not reachable",
    },
    {
      ok: status.external_llm_calls === 0,
      label: "Zero external LLM calls",
      detail: `${status.external_llm_calls} external calls this session`,
    },
    {
      ok: status.network_egress.toLowerCase() === "blocked",
      label: "Network egress blocked",
      detail: status.network_egress,
    },
    {
      ok: status.documents_local,
      label: "Documents stay on device",
      detail: "uploads & pages stored locally",
    },
    {
      ok: status.audit_logging,
      label: "Audit logging enabled",
      detail: "every AI action is recorded",
    },
  ];
  return (
    <div className="space-y-4">
      <section>
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
          Guarantees
        </div>
        <ul className="space-y-1.5">
          {guarantees.map((g) => (
            <li
              key={g.label}
              className="flex items-start gap-2.5 rounded-lg border border-ink-700 bg-ink-850 px-3 py-2"
            >
              <span className="pt-1">
                <StatusDot ok={!!g.ok} />
              </span>
              <div>
                <div className="text-xs font-medium text-zinc-200">
                  {g.label}
                </div>
                <div className="text-[11px] text-zinc-500">{g.detail}</div>
              </div>
            </li>
          ))}
        </ul>
      </section>
      <ModelList status={status} />
    </div>
  );
}

function ModelList({ status }: { status: TrustStatus }) {
  return (
    <section>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        Local models
      </div>
      <ul className="space-y-1.5">
        {status.models.map((m) => (
          <li
            key={m.name}
            className={cn(
              "flex items-center gap-2 rounded-lg border px-3 py-2",
              m.name === status.active_model
                ? "border-accent/50 bg-ink-850"
                : "border-ink-700 bg-ink-850",
            )}
          >
            <div className="min-w-0">
              <div className="truncate font-mono text-xs text-zinc-200">
                {m.name}
              </div>
              <div className="text-[11px] text-zinc-500">
                {m.role} · {m.size}
              </div>
            </div>
            <div className="ml-auto">
              {m.installed ? (
                <Badge color="green">installed</Badge>
              ) : (
                <Badge color="zinc">not pulled</Badge>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
function AuditTab({ audit }: { audit: AuditEventRec[] }) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
        Recent AI actions ({audit.length})
      </div>
      <ul className="space-y-1.5">
        {audit.map((a) => (
          <li
            key={a.id}
            className="rounded-lg border border-ink-700 bg-ink-850 px-3 py-2"
          >
            <div className="flex items-center gap-2">
              <Badge color={a.result_status === "ok" ? "green" : "amber"}>
                {a.result_status}
              </Badge>
              <span className="text-xs text-zinc-200">{a.user_action}</span>
            </div>
            <div className="mt-1 font-mono text-[10px] text-zinc-600">
              {new Date(a.time).toLocaleString()} · {a.model} ·{" "}
              {a.retrieval_count} sources
              {a.tool_name ? ` · tool: ${a.tool_name}` : ""}
            </div>
          </li>
        ))}
        {audit.length === 0 && (
          <li className="text-xs text-zinc-600">No audit events yet.</li>
        )}
      </ul>
    </div>
  );
}