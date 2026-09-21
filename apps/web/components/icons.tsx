/** Inline stroke icon set.
 *
 *  Hand-drawn rather than pulled from an icon package, for the same reason
 *  the Markdown renderer is: the deployment is air-gapped, so every npm
 *  dependency is one more thing to vendor, audit and keep current on a
 *  machine with no network. The subset an engineering workbench actually
 *  needs is small and closed.
 *
 *  What this replaces is the real problem: the UI was drawn with whatever
 *  glyph was to hand — 📎 for attach, ✦ ⬡ ▤ ∑ ⛨ ▲ ▣ for capabilities, ✎ ✕ ↻
 *  ■ ↑ for actions. Emoji render in colour on some platforms and monochrome
 *  on others, Unicode geometric shapes have wildly different optical weights
 *  and baselines, and none of them line up with each other. A single 1.5px
 *  stroke on a 24-unit grid is most of the distance between "student project"
 *  and "product".
 *
 *  All icons inherit `currentColor` and size from the `size` prop (default
 *  16), so they sit inside buttons and text without per-site overrides.
 */
import type { SVGProps } from "react";

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  size?: number;
}

function Svg({ size = 16, ...rest }: IconProps & { children: React.ReactNode }) {
  const { children, ...props } = rest as IconProps & {
    children: React.ReactNode;
  };
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      {children}
    </svg>
  );
}

/* ── navigation & layout ─────────────────────────────────── */
export const IconHome = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10.5 12 3l9 7.5" />
    <path d="M5 9.5V20a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9.5" />
  </Svg>
);

export const IconPanelLeft = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9.5 4v16" />
  </Svg>
);

export const IconChevronLeft = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 5l-7 7 7 7" />
  </Svg>
);

export const IconChevronRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 5l7 7-7 7" />
  </Svg>
);

export const IconChevronDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 9l7 7 7-7" />
  </Svg>
);

export const IconSelector = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 9l4-4 4 4" />
    <path d="M16 15l-4 4-4-4" />
  </Svg>
);

export const IconArrowRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 12h15" />
    <path d="M13 6l6 6-6 6" />
  </Svg>
);

export const IconArrowUp = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 20V5" />
    <path d="M6 11l6-6 6 6" />
  </Svg>
);

export const IconExternal = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 5h6v6" />
    <path d="M19 5l-8 8" />
    <path d="M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" />
  </Svg>
);

/* ── actions ─────────────────────────────────────────────── */
export const IconPlus = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5v14" />
    <path d="M5 12h14" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Svg>
);

export const IconX = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12" />
    <path d="M18 6L6 18" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12.5l4.5 4.5L19 7" />
  </Svg>
);

export const IconCopy = (p: IconProps) => (
  <Svg {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a1 1 0 0 1 1-1h9" />
  </Svg>
);

export const IconPencil = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20l4.5-1 9-9a2.1 2.1 0 0 0-3-3l-9 9L4 20z" />
    <path d="M14 6.5l3.5 3.5" />
  </Svg>
);

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16" />
    <path d="M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7" />
    <path d="M6 7l.8 12a1 1 0 0 0 1 .9h8.4a1 1 0 0 0 1-.9L18 7" />
  </Svg>
);

export const IconRefresh = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 1 0-.6 4" />
    <path d="M20 4.5V11h-6.5" />
  </Svg>
);

export const IconStop = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2" fill="currentColor" />
  </Svg>
);

export const IconPaperclip = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 11.5l-8 8a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10 17.5a2 2 0 0 1-3-3l7.5-7.5" />
  </Svg>
);

export const IconDownload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4v11" />
    <path d="M7.5 10.5L12 15l4.5-4.5" />
    <path d="M5 19h14" />
  </Svg>
);

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V5" />
    <path d="M7.5 9.5L12 5l4.5 4.5" />
    <path d="M5 19h14" />
  </Svg>
);

export const IconMore = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="5.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
    <circle cx="18.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconSettings = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M17.9 6.1l-1.4 1.4M7.5 16.5l-1.4 1.4M17.9 17.9l-1.4-1.4M7.5 7.5L6.1 6.1" />
  </Svg>
);

/* ── capabilities & content ──────────────────────────────── */
export const IconSparkles = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5l1.6 4.4 4.4 1.6-4.4 1.6L12 15.5l-1.6-4.4L6 9.5l4.4-1.6L12 3.5z" />
    <path d="M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />
  </Svg>
);

export const IconMessage = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.5a2 2 0 0 1-2 2H9l-4 3.5v-3.5H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8z" />
  </Svg>
);

export const IconSchematic = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9h4.5a2 2 0 0 1 2 2v2a2 2 0 0 0 2 2H21" />
    <circle cx="15.5" cy="8.5" r="2" />
  </Svg>
);

export const IconGraph = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="6" cy="7" r="2.5" />
    <circle cx="18" cy="7" r="2.5" />
    <circle cx="12" cy="18" r="2.5" />
    <path d="M8.2 8.4l2.4 7.2M15.8 8.4l-2.4 7.2M8.5 7h7" />
  </Svg>
);

export const IconFile = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V8l-5-5z" />
    <path d="M13 3v5h5" />
  </Svg>
);

export const IconTable = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M3 9.5h18M3 15h18M10 9.5V20" />
  </Svg>
);

export const IconCode = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 7l-5 5 5 5" />
    <path d="M15 7l5 5-5 5" />
  </Svg>
);

export const IconBrain = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 5.5a3 3 0 0 0-5.7-1.3A2.8 2.8 0 0 0 4 9.4a3 3 0 0 0 .7 4.9A2.8 2.8 0 0 0 8 19a3 3 0 0 0 4-.7z" />
    <path d="M12 5.5a3 3 0 0 1 5.7-1.3A2.8 2.8 0 0 1 20 9.4a3 3 0 0 1-.7 4.9A2.8 2.8 0 0 1 16 19a3 3 0 0 1-4-.7z" />
  </Svg>
);

export const IconSigma = (p: IconProps) => (
  <Svg {...p}>
    <path d="M17.5 5H6.5l5.5 7-5.5 7h11" />
  </Svg>
);

export const IconShield = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7 3v5.5c0 4.3-2.9 8-7 9.5-4.1-1.5-7-5.2-7-9.5V6l7-3z" />
  </Svg>
);

export const IconShieldCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7 3v5.5c0 4.3-2.9 8-7 9.5-4.1-1.5-7-5.2-7-9.5V6l7-3z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);

export const IconLock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="10" width="14" height="10" rx="2" />
    <path d="M8.5 10V7.5a3.5 3.5 0 0 1 7 0V10" />
  </Svg>
);

export const IconSandbox = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="3.5" width="17" height="17" rx="2" />
    <rect x="8" y="8" width="8" height="8" rx="1" />
  </Svg>
);

/* ── status ──────────────────────────────────────────────── */
export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4l9 16H3l9-16z" />
    <path d="M12 10v4" />
    <circle cx="12" cy="17" r=".8" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11.5v5" />
    <circle cx="12" cy="8.2" r=".8" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconClock = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 2" />
  </Svg>
);

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 12S6 6 12 6s9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" />
    <circle cx="12" cy="12" r="2.5" />
  </Svg>
);

/** Maps a deliverable/file kind to the right glyph. */
export function fileIcon(kind: string) {
  const k = (kind || "").toLowerCase();
  if (k === "xlsx" || k === "csv") return IconTable;
  if (k === "code") return IconCode;
  return IconFile;
}
