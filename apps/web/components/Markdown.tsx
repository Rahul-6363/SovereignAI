"use client";
/** Markdown renderer for assistant answers.
 *
 * The answers this app produces are structurally rich — the grounded-answer
 * path appends a "Verified from Plant Memory" section of bullet lists, the
 * agent path reports file names as inline code, and the calculation path
 * emits headings and tables. All of that was previously printed as literal
 * `**text**` and `- item` inside one pre-wrapped paragraph, which made the
 * most trustworthy part of every answer the hardest part to read.
 *
 * Deliberately hand-written rather than pulled from npm: the deployment is
 * air-gapped, so every dependency is one more thing to vendor and audit, and
 * the subset that actually appears here is small and closed. It is also why
 * there is no `dangerouslySetInnerHTML` anywhere below — the text includes
 * model output and retrieved document text, and neither is trusted markup.
 */
import { useMemo } from "react";
import { CopyButton, cn } from "./ui";
import { INLINE_SOURCE, LINK, parseBlocks } from "@/lib/markdown";
import type { Block } from "@/lib/markdown";

export function renderInline(text: string, keyPrefix = ""): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const inline = new RegExp(INLINE_SOURCE, "g");
  let last = 0;
  let k = 0;
  let m: RegExpExecArray | null;

  while ((m = inline.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}i${k++}`;

    if (tok.startsWith("`")) {
      out.push(
        <code
          key={key}
          className="rounded bg-ink-700/70 px-1 py-0.5 font-mono text-[0.85em] text-accent-soft"
        >
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (tok.startsWith("**") || tok.startsWith("__")) {
      out.push(
        <strong key={key} className="font-semibold text-zinc-100">
          {renderInline(tok.slice(2, -2), key)}
        </strong>,
      );
    } else if (tok.startsWith("~~")) {
      out.push(
        <s key={key} className="text-zinc-500">
          {renderInline(tok.slice(2, -2), key)}
        </s>,
      );
    } else if (tok.startsWith("[")) {
      const link = LINK.exec(tok);
      if (link) {
        // Only http(s) is followed. Answer text includes retrieved document
        // content, and a javascript: URL in a citation is not a link.
        const safe = /^https?:\/\//i.test(link[2]);
        out.push(
          safe ? (
            <a
              key={key}
              href={link[2]}
              target="_blank"
              rel="noreferrer noopener"
              className="text-accent underline decoration-accent/40 underline-offset-2 hover:decoration-accent"
            >
              {link[1]}
            </a>
          ) : (
            <span key={key}>{link[1]}</span>
          ),
        );
      } else {
        out.push(tok);
      }
    } else {
      out.push(
        <em key={key} className="italic text-zinc-300">
          {renderInline(tok.slice(1, -1), key)}
        </em>,
      );
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/* ── block rendering ────────────────────────────────────────── */
function CodeBlock({ lang, code }: { lang: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-ink-700 bg-ink-950">
      <div className="flex items-center gap-2 border-b border-ink-700 bg-ink-900/60 px-3 py-1.5">
        <span className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
          {lang || "text"}
        </span>
        <CopyButton text={code} className="ml-auto" />
      </div>
      <pre className="overflow-x-auto px-3 py-2.5">
        <code className="font-mono text-[12px] leading-relaxed text-zinc-200">
          {code}
        </code>
      </pre>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-ink-700">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="bg-ink-800">
            {head.map((h, i) => (
              <th
                key={i}
                className="whitespace-nowrap px-2.5 py-1.5 font-semibold text-zinc-300"
              >
                {renderInline(h, `th${i}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-t border-ink-800">
              {head.map((_, c) => (
                <td key={c} className="px-2.5 py-1.5 align-top text-zinc-400">
                  {renderInline(row[c] ?? "", `td${r}-${c}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const HEADING_CLASS: Record<2 | 3 | 4, string> = {
  2: "mt-1 text-[15px] font-semibold text-zinc-100",
  3: "mt-1 text-[13.5px] font-semibold text-zinc-200",
  4: "mt-1 text-[12.5px] font-semibold uppercase tracking-wide text-zinc-400",
};

export default function Markdown({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  // Re-parsed on every streamed token, so the parse has to stay cheap; it is
  // a single linear pass and memoised on the exact string.
  const blocks = useMemo(() => parseBlocks(text), [text]);

  return (
    <div
      className={cn(
        "space-y-3 text-sm leading-relaxed text-zinc-200",
        className,
      )}
    >
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "h": {
            const Tag = (`h${b.level}` as unknown) as "h2";
            return (
              <Tag key={i} className={HEADING_CLASS[b.level]}>
                {renderInline(b.text, `h${i}`)}
              </Tag>
            );
          }
          case "ul":
            return (
              <ul key={i} className="ml-1 space-y-1">
                {b.items.map((item, j) => (
                  <li key={j} className="flex gap-2">
                    <span
                      aria-hidden
                      className="mt-[0.45em] h-1 w-1 shrink-0 rounded-full bg-zinc-600"
                    />
                    <span className="min-w-0">
                      {renderInline(item, `u${i}-${j}`)}
                    </span>
                  </li>
                ))}
              </ul>
            );
          case "ol":
            return (
              <ol key={i} className="ml-1 space-y-1">
                {b.items.map((item, j) => (
                  <li key={j} className="flex gap-2">
                    <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                      {b.start + j}.
                    </span>
                    <span className="min-w-0">
                      {renderInline(item, `o${i}-${j}`)}
                    </span>
                  </li>
                ))}
              </ol>
            );
          case "code":
            return <CodeBlock key={i} lang={b.lang} code={b.code} />;
          case "quote":
            return (
              <blockquote
                key={i}
                className="border-l-2 border-ink-600 pl-3 text-zinc-400"
              >
                {renderInline(b.text, `q${i}`)}
              </blockquote>
            );
          case "table":
            return <Table key={i} head={b.head} rows={b.rows} />;
          case "hr":
            return <hr key={i} className="border-ink-700" />;
          default:
            return (
              <p key={i} className="whitespace-pre-wrap">
                {renderInline(b.text, `p${i}`)}
              </p>
            );
        }
      })}
    </div>
  );
}
