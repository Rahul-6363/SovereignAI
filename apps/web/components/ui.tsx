"use client";
/** Small accessible UI primitives (no external component dependency). */
import { ReactNode, useEffect, useRef, useState } from "react";

export function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-ink-700 bg-ink-850 shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

type ButtonVariant = "primary" | "ghost" | "outline" | "danger";

export function Button({
  children,
  onClick,
  variant = "ghost",
  disabled,
  className,
  title,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  className?: string;
  title?: string;
  type?: "button" | "submit";
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60";
  const styles: Record<ButtonVariant, string> = {
    primary: "bg-accent text-white hover:bg-accent-soft",
    ghost: "text-zinc-300 hover:bg-ink-700 hover:text-zinc-100",
    outline:
      "border border-ink-600 text-zinc-300 hover:border-ink-600 hover:bg-ink-700 hover:text-zinc-100",
    danger: "border border-rose-900/60 text-rose-300 hover:bg-rose-950/40",
  };
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={cn(base, styles[variant], className)}
    >
      {children}
    </button>
  );
}

export function Badge({
  children,
  color = "zinc",
  className,
}: {
  children: ReactNode;
  color?: "zinc" | "green" | "red" | "amber" | "sky" | "rose" | "emerald" | "violet";
  className?: string;
}) {
  const colors: Record<string, string> = {
    zinc: "bg-ink-700 text-zinc-300",
    green: "bg-emerald-950/60 text-emerald-300",
    red: "bg-rose-950/60 text-rose-300",
    amber: "bg-amber-950/60 text-amber-300",
    sky: "bg-sky-950/60 text-sky-300",
    rose: "bg-rose-950/60 text-rose-300",
    emerald: "bg-emerald-950/60 text-emerald-300",
    violet: "bg-violet-950/60 text-violet-300",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
        colors[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round((value ?? 0) * 100);
  const tone =
    pct >= 80 ? "bg-emerald-500" : pct >= 55 ? "bg-amber-500" : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-700">
        <div
          className={`h-full rounded-full ${tone} transition-all`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-zinc-400">
        {pct}%
      </span>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn("h-4 w-4 animate-spin text-zinc-400", className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-label="loading"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 0 1 8-8v4a4 4 0 0 0-4 4H4z"
      />
    </svg>
  );
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="text-lg font-medium text-zinc-300">{title}</div>
      {hint && <p className="max-w-sm text-sm text-zinc-500">{hint}</p>}
      {action}
    </div>
  );
}

export function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-block h-2 w-2 rounded-full",
        ok ? "animate-pulse-dot bg-emerald-400" : "bg-rose-500",
      )}
    />
  );
}

/** Fraction bbox [x,y,w,h] (0..1) → chip label helper. */
export function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}

/** Textarea that grows with its content up to `maxRows`, then scrolls. */
export function AutoTextarea({
  value,
  onChange,
  onKeyDown,
  placeholder,
  minRows = 1,
  maxRows = 8,
  className,
  autoFocus,
  textareaRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onKeyDown?: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  placeholder?: string;
  minRows?: number;
  maxRows?: number;
  className?: string;
  autoFocus?: boolean;
  textareaRef?: React.RefObject<HTMLTextAreaElement | null>;
}) {
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const ref = textareaRef ?? ownRef;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const style = window.getComputedStyle(el);
    const lineHeight = parseFloat(style.lineHeight) || 20;
    const padding =
      parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    // Reset first: scrollHeight never shrinks while the old height is applied.
    el.style.height = "auto";
    const min = lineHeight * minRows + padding;
    const max = lineHeight * maxRows + padding;
    el.style.height = `${Math.min(Math.max(el.scrollHeight, min), max)}px`;
    el.style.overflowY = el.scrollHeight > max ? "auto" : "hidden";
  }, [value, minRows, maxRows, ref]);

  return (
    <textarea
      ref={ref}
      value={value}
      autoFocus={autoFocus}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={onKeyDown}
      placeholder={placeholder}
      rows={minRows}
      className={cn("resize-none", className)}
    />
  );
}

/** Copy-to-clipboard button with a transient confirmation. */
export function CopyButton({
  text,
  label = "Copy",
  className,
}: {
  text: string;
  label?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
        } catch {
          /* clipboard blocked (insecure origin) — stay silent */
        }
      }}
      title="Copy this answer"
      className={cn(
        "rounded-md px-1.5 py-0.5 text-[11px] text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300",
        className,
      )}
    >
      {copied ? "✓ Copied" : label}
    </button>
  );
}
