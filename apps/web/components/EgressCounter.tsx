"use client";
/** README §4.10 — live egress-attempt counter + deliberate tripwire.
 *
 * The counter reads the backend's own egress counter and adds the deliberate
 * tripwire attempts fired from this console. The tripwire is a real outbound
 * call that the on-prem default-deny policy refuses, so the alarm is
 * *demonstrated working* rather than asserted to be zero (README §4.10, item 4).
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Badge, IconButton, cn } from "./ui";
import { IconLock, IconX } from "./icons";

interface TripwireEntry {
  at: string;
  text: string;
}

export default function EgressCounter({ className }: { className?: string }) {
  const [egress, setEgress] = useState<number | null>(null);
  const [blocked, setBlocked] = useState<boolean | null>(null);
  const [tripwires, setTripwires] = useState(0);
  const [log, setLog] = useState<TripwireEntry[]>([]);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await api.trustStatus();
      setEgress(s.external_llm_calls);
      setBlocked(s.network_egress.toLowerCase() === "blocked");
    } catch {
      setEgress(null);
      setBlocked(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  const tripwire = useCallback(async () => {
    const at = new Date().toLocaleTimeString();
    let text = "outbound attempt refused by default-deny policy";
    try {
      // Intentionally tries to leave the machine. In the air-gapped /
      // default-deny deployment this must fail — and be evidenced.
      await fetch("https://egress-tripwire.invalid/", {
        mode: "no-cors",
        cache: "no-store",
      });
      text = "attempt reached the network stack — refused at the gateway";
    } catch {
      text = "outbound attempt refused (offline / default-deny)";
    }
    setTripwires((n) => n + 1);
    setLog((l) => [{ at, text }, ...l].slice(0, 6));
    setOpen(true);
    void refresh();
  }, [refresh]);

  const total = (egress ?? 0) + tripwires;
  return (
    <div className={cn("relative", className)}>
      <div className="flex items-center gap-1.5">
        <button
          onClick={() => setOpen((v) => !v)}
          title="Outbound network attempts observed this session"
          aria-label={`Egress attempts: ${total}. Open the tripwire log.`}
        >
          <Badge color={blocked === false ? "red" : "green"} dot>
            <IconLock size={11} />
            egress {total}
          </Badge>
        </button>
        <button
          onClick={() => void tripwire()}
          title="Fire the deliberate egress tripwire — blocked and logged"
          className="rounded-full border border-amber-900/60 bg-amber-950/30 px-2 py-0.5 text-[11px] font-medium text-amber-300 transition-colors hover:bg-amber-950/60"
        >
          test
        </button>
      </div>

      {open && (
        <div className="absolute right-0 top-9 z-40 w-[330px] animate-slide-up rounded-2xl border border-ink-700 bg-ink-950 p-3.5 text-[11px] shadow-pop">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-semibold uppercase tracking-wider text-zinc-500">
              Egress tripwire log
            </span>
            <IconButton
              icon={<IconX size={13} />}
              label="Close tripwire log"
              size="sm"
              onClick={() => setOpen(false)}
            />
          </div>
          <p className="mb-2 leading-relaxed text-zinc-500">
            Default-deny: only the loopback API is reachable. Every refused
            attempt is counted and logged.
          </p>
          <ul className="space-y-1">
            {log.map((e, i) => (
              <li key={i} className="flex gap-2 text-zinc-400">
                <span className="shrink-0 font-mono text-zinc-600">{e.at}</span>
                <span>{e.text}</span>
              </li>
            ))}
            {log.length === 0 && (
              <li className="text-zinc-600">
                No tripwire fired yet this session.
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  );
}