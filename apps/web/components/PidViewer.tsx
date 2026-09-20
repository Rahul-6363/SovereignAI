"use client";
/** P&ID page viewer with an SVG overlay for 0..1 fraction bounding boxes. */
import { useState } from "react";
import type { EntityRec } from "@/lib/types";
import { Badge, cn } from "./ui";

export default function PidViewer({
  imageUrl,
  bbox,
  label,
  entities = [],
  selectedTag,
  onSelectTag,
  className,
}: {
  imageUrl: string;
  /** [x, y, w, h] in page fractions (0..1), or null for no highlight. */
  bbox?: number[] | null;
  label?: string;
  entities?: EntityRec[];
  selectedTag?: string | null;
  onSelectTag?: (tag: string) => void;
  className?: string;
}) {
  const [showAll, setShowAll] = useState(false);
  const valid =
    !!bbox && bbox.length === 4 && bbox.some((v) => v > 0 || v < 0);

  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="flex items-center gap-2 border-b border-ink-700 px-3 py-1.5">
        <span className="text-xs font-medium text-zinc-400">P&ID view</span>
        <div className="ml-auto flex items-center gap-2">
          {label && valid && (
            <Badge color="amber">▣ {label} highlighted</Badge>
          )}
          {entities.length > 0 && (
            <button
              onClick={() => setShowAll((v) => !v)}
              className="rounded-md border border-ink-600 px-2 py-0.5 text-[11px] text-zinc-400 hover:bg-ink-700 hover:text-zinc-200"
            >
              {showAll ? "Hide all boxes" : "Show all boxes"}
            </button>
          )}
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-auto bg-ink-950 p-3">
        <div className="relative mx-auto w-fit max-w-full">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={imageUrl}
            alt="P&ID page"
            className="block h-auto max-w-full select-none rounded-md"
            draggable={false}
          />
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 h-full w-full"
          >
            {/* faint boxes for every entity */}
            {showAll &&
              entities
                .filter((e) => e.bbox && e.bbox.length === 4)
                .map((e) => (
                  <rect
                    key={`all-${e.id}`}
                    x={e.bbox[0] * 100}
                    y={e.bbox[1] * 100}
                    width={e.bbox[2] * 100}
                    height={e.bbox[3] * 100}
                    fill={
                      e.canonical_tag === selectedTag
                        ? "rgba(217,119,87,0.25)"
                        : "rgba(120,160,255,0.07)"
                    }
                    stroke={
                      e.canonical_tag === selectedTag
                        ? "#d97757"
                        : "rgba(120,160,255,0.35)"
                    }
                    strokeWidth={1.5}
                    vectorEffect="non-scaling-stroke"
                    rx={0.6}
                  />
                ))}

            {/* strong highlight for the selected / evidence bbox */}
            {valid && bbox && (
              <rect
                x={bbox[0] * 100}
                y={bbox[1] * 100}
                width={bbox[2] * 100}
                height={bbox[3] * 100}
                fill="rgba(217,119,87,0.18)"
                stroke="#d97757"
                strokeWidth={2.5}
                vectorEffect="non-scaling-stroke"
                rx={0.8}
              />
            )}
          </svg>

          {/* click targets for entity boxes when showAll is on */}
          {showAll && (
            <div className="absolute inset-0">
              {entities
                .filter((e) => e.bbox && e.bbox.length === 4 && onSelectTag)
                .map((e) => (
                  <button
                    key={`hit-${e.id}`}
                    title={`${e.canonical_tag} — ${e.label}`}
                    onClick={() => onSelectTag?.(e.canonical_tag)}
                    className="absolute cursor-crosshair rounded-sm hover:outline hover:outline-1 hover:outline-accent"
                    style={{
                      left: `${e.bbox[0] * 100}%`,
                      top: `${e.bbox[1] * 100}%`,
                      width: `${Math.max(e.bbox[2] * 100, 2)}%`,
                      height: `${Math.max(e.bbox[3] * 100, 2)}%`,
                    }}
                  />
                ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
