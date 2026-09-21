"use client";
/** Meshcore UI primitives.
 *
 *  Hand-rolled rather than pulled from a component library: the deployment is
 *  air-gapped, and a design system this small does not justify vendoring and
 *  auditing one. Everything here is composition over configuration — the
 *  variants are the ones the app actually uses, not a general-purpose matrix.
 *
 *  The rules these encode, so they are not re-litigated per component:
 *    · One focus treatment, defined globally in `globals.css`.
 *    · Buttons state their weight (`primary` is the one action that matters
 *      on a screen; there is at most one).
 *    · Destructive actions confirm in place rather than through a dialog —
 *      a modal for "delete this chat" is heavier than the decision.
 *    · Icon-only controls always carry a tooltip AND an aria-label. An icon
 *      button with neither is unusable by half the people who meet it.
 */
import {
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { IconCheck, IconCopy, IconSearch, IconX } from "./icons";

export function cn(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

/* ── surfaces ────────────────────────────────────────────── */
export function Card({
  children,
  className,
  interactive = false,
}: {
  children: ReactNode;
  className?: string;
  interactive?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-ink-800 bg-ink-850 shadow-raised",
        interactive &&
          "transition-colors hover:border-ink-700 hover:bg-ink-800/70",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** A labelled section heading, used above every list and grid in the app. */
export function SectionLabel({
  children,
  action,
  className,
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-2.5 flex items-center gap-2", className)}>
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-500">
        {children}
      </h2>
      {action && <div className="ml-auto flex items-center gap-1">{action}</div>}
    </div>
  );
}

export function Separator({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-ink-800", className)} />;
}

/* ── buttons ─────────────────────────────────────────────── */
type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "outline"
  | "danger"
  | "subtle";
type ButtonSize = "sm" | "md" | "lg";

const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white shadow-raised hover:bg-accent-soft active:bg-accent-deep",
  secondary:
    "bg-ink-800 text-zinc-100 shadow-raised hover:bg-ink-750 active:bg-ink-700",
  ghost: "text-zinc-400 hover:bg-ink-800 hover:text-zinc-100",
  outline:
    "border border-ink-700 text-zinc-300 hover:border-ink-600 hover:bg-ink-850 hover:text-zinc-100",
  danger:
    "border border-rose-900/60 text-rose-300 hover:bg-rose-950/40 hover:text-rose-200",
  subtle: "bg-ink-850 text-zinc-400 hover:bg-ink-800 hover:text-zinc-200",
};

const BUTTON_SIZE: Record<ButtonSize, string> = {
  sm: "h-7 gap-1.5 rounded-lg px-2.5 text-xs",
  md: "h-9 gap-2 rounded-xl px-3.5 text-sm",
  lg: "h-11 gap-2 rounded-xl px-5 text-[15px]",
};

export function Button({
  children,
  onClick,
  variant = "ghost",
  size = "md",
  disabled,
  loading,
  className,
  title,
  type = "button",
  icon,
  iconRight,
  full,
}: {
  children?: ReactNode;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  /** Swaps the leading icon for a spinner and blocks the click. */
  loading?: boolean;
  className?: string;
  title?: string;
  type?: "button" | "submit";
  icon?: ReactNode;
  iconRight?: ReactNode;
  full?: boolean;
}) {
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled || loading}
      className={cn(
        "inline-flex select-none items-center justify-center font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-45",
        BUTTON_SIZE[size],
        BUTTON_VARIANT[variant],
        full && "w-full",
        className,
      )}
    >
      {loading ? (
        <Spinner className="h-3.5 w-3.5" />
      ) : (
        icon && <span className="shrink-0">{icon}</span>
      )}
      {children}
      {iconRight && <span className="shrink-0">{iconRight}</span>}
    </button>
  );
}

/** Square icon-only control. `label` is mandatory: it becomes both the
 *  accessible name and the tooltip, so there is no way to ship one without. */
export function IconButton({
  icon,
  label,
  onClick,
  variant = "ghost",
  size = "md",
  disabled,
  active,
  className,
  type = "button",
  tone,
}: {
  icon: ReactNode;
  label: string;
  onClick?: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  /** Renders as pressed — for toggles like the sidebar collapse. */
  active?: boolean;
  className?: string;
  type?: "button" | "submit";
  tone?: "danger";
}) {
  const box =
    size === "sm" ? "h-7 w-7 rounded-lg" : size === "lg" ? "h-11 w-11 rounded-xl" : "h-9 w-9 rounded-xl";
  return (
    <Tooltip label={label}>
      <button
        type={type}
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        aria-pressed={active}
        className={cn(
          "inline-flex shrink-0 items-center justify-center transition-colors",
          "disabled:cursor-not-allowed disabled:opacity-40",
          box,
          active
            ? "bg-ink-800 text-zinc-100"
            : tone === "danger"
              ? "text-zinc-500 hover:bg-rose-950/40 hover:text-rose-300"
              : BUTTON_VARIANT[variant],
          className,
        )}
      >
        {icon}
      </button>
    </Tooltip>
  );
}

/** Hover/focus tooltip. CSS-driven, so it costs nothing until it is needed
 *  and cannot get stuck open when the trigger unmounts mid-hover. */
export function Tooltip({
  label,
  children,
  side = "top",
  className,
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom" | "left" | "right";
  className?: string;
}) {
  const pos = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-1.5",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-1.5",
    left: "right-full top-1/2 -translate-y-1/2 mr-1.5",
    right: "left-full top-1/2 -translate-y-1/2 ml-1.5",
  }[side];
  return (
    <span className={cn("group/tt relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          "pointer-events-none absolute z-50 whitespace-nowrap rounded-lg border border-ink-700 bg-ink-950 px-2 py-1 text-[11px] font-medium text-zinc-200 opacity-0 shadow-pop transition-opacity duration-100",
          "group-hover/tt:opacity-100 group-focus-within/tt:opacity-100",
          pos,
        )}
      >
        {label}
      </span>
    </span>
  );
}

/** Destructive action that asks in place instead of opening a dialog. */
export function ConfirmButton({
  label,
  confirmLabel = "Confirm",
  question,
  onConfirm,
  icon,
  size = "sm",
  className,
}: {
  label: string;
  confirmLabel?: string;
  question: string;
  onConfirm: () => void;
  icon?: ReactNode;
  size?: ButtonSize;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);

  // Arming a destructive control and then walking away should not leave it
  // armed — the next click would delete something the user forgot about.
  useEffect(() => {
    if (!asking) return;
    const t = setTimeout(() => setAsking(false), 5000);
    return () => clearTimeout(t);
  }, [asking]);

  if (!asking) {
    return (
      <Button
        variant="ghost"
        size={size}
        icon={icon}
        onClick={() => setAsking(true)}
        className={cn("text-zinc-500 hover:text-rose-300", className)}
      >
        {label}
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-lg border border-rose-900/60 bg-rose-950/30 px-2 py-1">
      <span className="text-[11px] text-rose-200">{question}</span>
      <button
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
        className="rounded-md bg-rose-900/70 px-2 py-0.5 text-[11px] font-medium text-rose-50 hover:bg-rose-900"
      >
        {confirmLabel}
      </button>
      <button
        onClick={() => setAsking(false)}
        className="rounded-md px-1.5 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-100"
      >
        Cancel
      </button>
    </span>
  );
}

/* ── inputs ──────────────────────────────────────────────── */
export function Input({
  value,
  onChange,
  placeholder,
  className,
  type = "text",
  onKeyDown,
  autoFocus,
  inputRef,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  type?: string;
  onKeyDown?: (e: React.KeyboardEvent<HTMLInputElement>) => void;
  autoFocus?: boolean;
  inputRef?: React.RefObject<HTMLInputElement | null>;
  ariaLabel?: string;
}) {
  return (
    <input
      ref={inputRef}
      type={type}
      value={value}
      aria-label={ariaLabel}
      autoFocus={autoFocus}
      onKeyDown={onKeyDown}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={cn(
        "h-9 w-full rounded-xl border border-ink-700 bg-ink-900 px-3 text-sm text-zinc-100 placeholder-zinc-600",
        "transition-colors focus:border-ink-600 focus:outline-none",
        className,
      )}
    />
  );
}

/** Search field with a leading glyph and a clear affordance once it has text. */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className,
  ariaLabel = "Search",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <IconSearch
        size={14}
        className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-600"
      />
      <input
        value={value}
        aria-label={ariaLabel}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-8 w-full rounded-lg border border-ink-800 bg-ink-900 pl-8 pr-7 text-[13px] text-zinc-100 placeholder-zinc-600 transition-colors focus:border-ink-600 focus:outline-none"
      />
      {value && (
        <button
          onClick={() => onChange("")}
          aria-label="Clear search"
          className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-600 hover:text-zinc-300"
        >
          <IconX size={12} />
        </button>
      )}
    </div>
  );
}

export function Select({
  value,
  onChange,
  options,
  className,
  ariaLabel,
}: {
  value: string | number;
  onChange: (v: string) => void;
  options: { value: string | number; label: string }[];
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <select
      value={value}
      aria-label={ariaLabel}
      onChange={(e) => onChange(e.target.value)}
      className={cn(
        "h-8 rounded-lg border border-ink-800 bg-ink-900 px-2 text-[13px] text-zinc-200 transition-colors focus:border-ink-600 focus:outline-none",
        className,
      )}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

/** Tab-style segmented control, used for view switching and chat modes. */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  size = "md",
  disabled,
  ariaLabel,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; icon?: ReactNode; title?: string }[];
  size?: "sm" | "md";
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-xl bg-ink-950/70 p-0.5",
        className,
      )}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="tab"
            aria-selected={active}
            disabled={disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg font-medium transition-colors disabled:opacity-50",
              size === "sm" ? "h-7 px-2 text-[11px]" : "h-8 px-2.5 text-[13px]",
              active
                ? "bg-ink-800 text-zinc-100 shadow-raised"
                : "text-zinc-500 hover:text-zinc-300",
            )}
          >
            {o.icon && (
              <span className={active ? "text-accent" : "text-zinc-600"}>
                {o.icon}
              </span>
            )}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/* ── dropdown menu ───────────────────────────────────────── */
export function Menu({
  trigger,
  items,
  align = "right",
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  items: {
    label: string;
    onSelect: () => void;
    icon?: ReactNode;
    tone?: "danger";
    disabled?: boolean;
  }[];
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Closing on outside click AND on Escape: a menu that only closes on
  // outside click traps keyboard users behind it.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div
          role="menu"
          className={cn(
            "absolute z-50 mt-1 min-w-[10rem] animate-slide-up rounded-xl border border-ink-700 bg-ink-850 p-1 shadow-pop",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {items.map((item) => (
            <button
              key={item.label}
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors disabled:opacity-40",
                item.tone === "danger"
                  ? "text-rose-300 hover:bg-rose-950/40"
                  : "text-zinc-300 hover:bg-ink-800 hover:text-zinc-100",
              )}
            >
              {item.icon && (
                <span className="shrink-0 text-zinc-500">{item.icon}</span>
              )}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── indicators ──────────────────────────────────────────── */
export function Badge({
  children,
  color = "zinc",
  className,
  dot = false,
}: {
  children: ReactNode;
  color?:
    | "zinc"
    | "green"
    | "red"
    | "amber"
    | "sky"
    | "rose"
    | "emerald"
    | "violet"
    | "accent";
  className?: string;
  dot?: boolean;
}) {
  const colors: Record<string, string> = {
    zinc: "border-ink-700 bg-ink-800 text-zinc-300",
    green: "border-emerald-900/70 bg-emerald-950/50 text-emerald-300",
    emerald: "border-emerald-900/70 bg-emerald-950/50 text-emerald-300",
    red: "border-rose-900/70 bg-rose-950/50 text-rose-300",
    rose: "border-rose-900/70 bg-rose-950/50 text-rose-300",
    amber: "border-amber-900/70 bg-amber-950/50 text-amber-300",
    sky: "border-sky-900/70 bg-sky-950/50 text-sky-300",
    violet: "border-violet-900/70 bg-violet-950/50 text-violet-300",
    accent: "border-accent/40 bg-accent/10 text-accent-soft",
  };
  const dotColor: Record<string, string> = {
    zinc: "bg-zinc-500",
    green: "bg-emerald-400",
    emerald: "bg-emerald-400",
    red: "bg-rose-400",
    rose: "bg-rose-400",
    amber: "bg-amber-400",
    sky: "bg-sky-400",
    violet: "bg-violet-400",
    accent: "bg-accent",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        colors[color],
        className,
      )}
    >
      {dot && (
        <span
          aria-hidden
          className={cn("h-1.5 w-1.5 rounded-full", dotColor[color])}
        />
      )}
      {children}
    </span>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded border border-ink-700 bg-ink-850 px-1.5 font-mono text-[10px] font-medium text-zinc-400">
      {children}
    </kbd>
  );
}

/** One headline number with its label. */
export function Stat({
  label,
  value,
  icon,
  hint,
  onClick,
}: {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  hint?: string;
  onClick?: () => void;
}) {
  const body = (
    <>
      <div className="mb-1 flex items-center gap-1.5">
        {icon && <span className="text-zinc-600">{icon}</span>}
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-zinc-500">
          {label}
        </span>
      </div>
      <div className="font-mono text-[22px] leading-none text-zinc-100">
        {value}
      </div>
      {hint && <div className="mt-1.5 text-[11px] text-zinc-600">{hint}</div>}
    </>
  );
  const shell =
    "rounded-2xl border border-ink-800 bg-ink-850 px-3.5 py-3 text-left shadow-raised";
  if (!onClick) return <div className={shell}>{body}</div>;
  return (
    <button
      onClick={onClick}
      className={cn(
        shell,
        "transition-colors hover:border-ink-700 hover:bg-ink-800/70",
      )}
    >
      {body}
    </button>
  );
}

export function ConfidenceBar({ value }: { value: number }) {
  const pctValue = Math.round((value ?? 0) * 100);
  const tone =
    pctValue >= 80
      ? "bg-emerald-500"
      : pctValue >= 55
        ? "bg-amber-500"
        : "bg-rose-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-800">
        <div
          className={`h-full rounded-full ${tone} transition-all`}
          style={{ width: `${Math.min(100, Math.max(0, pctValue))}%` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-zinc-400">
        {pctValue}%
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

/** Loading placeholder shaped like the content it stands in for. */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("animate-shimmer rounded-lg bg-ink-800", className)} />
  );
}

export function EmptyState({
  title,
  hint,
  action,
  icon,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      {icon && (
        <span className="grid h-11 w-11 place-items-center rounded-2xl border border-ink-800 bg-ink-850 text-zinc-600">
          {icon}
        </span>
      )}
      <div className="text-[15px] font-medium text-zinc-200">{title}</div>
      {hint && (
        <p className="max-w-sm text-[13px] leading-relaxed text-zinc-500">
          {hint}
        </p>
      )}
      {action && <div className="mt-1">{action}</div>}
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
  ariaLabel,
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
  ariaLabel?: string;
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
      aria-label={ariaLabel}
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
  iconOnly = false,
}: {
  text: string;
  label?: string;
  className?: string;
  iconOnly?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(false), 1600);
    return () => clearTimeout(t);
  }, [copied]);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard blocked (insecure origin) — stay silent */
    }
  }, [text]);

  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-1.5 py-1 text-[11px] text-zinc-500 transition-colors hover:bg-ink-800 hover:text-zinc-300",
        className,
      )}
    >
      {copied ? (
        <IconCheck size={13} className="text-emerald-400" />
      ) : (
        <IconCopy size={13} />
      )}
      {!iconOnly && (copied ? "Copied" : label)}
    </button>
  );
}
