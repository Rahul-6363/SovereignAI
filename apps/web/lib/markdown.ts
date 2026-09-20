/** Markdown parsing for assistant answers — grammar only, no rendering.
 *
 * Split from the renderer so the grammar decisions can be exercised on their
 * own: which line starts a list, when a pipe row is a table rather than a
 * sentence containing a pipe, and what a half-streamed code fence should look
 * like before its closing fence arrives.
 *
 * Deliberately hand-written rather than pulled from npm. The deployment is
 * air-gapped, so every dependency is one more thing to vendor and audit, and
 * the subset of Markdown that actually appears in these answers is small and
 * closed.
 */

/* ── block model ────────────────────────────────────────────── */
export type Block =
  | { kind: "p"; text: string }
  | { kind: "h"; level: 2 | 3 | 4; text: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[]; start: number }
  | { kind: "code"; lang: string; code: string }
  | { kind: "quote"; text: string }
  | { kind: "table"; head: string[]; rows: string[][] }
  | { kind: "hr" };

const FENCE = /^```(\w*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^[-*+]\s+(.*)$/;
const NUMBERED = /^(\d+)[.)]\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;
const RULE = /^([-*_])\1{2,}\s*$/;
// A trailing pipe is optional in practice — plenty of generated tables omit
// it — so the row test only requires a leading one. The separator row on the
// next line is what actually confirms this is a table.
const TABLE_ROW = /^\|.*\S/;
const TABLE_SEP = /^\|[\s:|-]+$/;

function cells(line: string): string[] {
  return line
    .replace(/^\||\|\s*$/g, "")
    .split("|")
    .map((c) => c.trim());
}

/** Parse the markdown subset these answers use into a block list. */
export function parseBlocks(source: string): Block[] {
  const lines = (source ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    const text = paragraph.join("\n").trim();
    if (text) blocks.push({ kind: "p", text });
    paragraph = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // fenced code — consumed verbatim, including blank lines inside it
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const lang = fence[1] ?? "";
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      blocks.push({ kind: "code", lang, code: body.join("\n") });
      continue;
    }

    if (!line.trim()) {
      flush();
      continue;
    }

    if (RULE.test(line)) {
      flush();
      blocks.push({ kind: "hr" });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      // h1 is the answer's own container, so document headings start at h2
      // and cannot outrank the surrounding page.
      const level = Math.min(Math.max(heading[1].length + 1, 2), 4) as 2 | 3 | 4;
      blocks.push({ kind: "h", level, text: heading[2].trim() });
      continue;
    }

    // table: a pipe row followed by a separator row. Without the separator
    // it is prose that happens to contain a pipe, and forcing it into a
    // table loses the sentence.
    if (TABLE_ROW.test(line) && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flush();
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        rows.push(cells(lines[i]));
        i++;
      }
      i--;
      blocks.push({ kind: "table", head, rows });
      continue;
    }

    const bullet = BULLET.exec(line);
    if (bullet) {
      flush();
      const items = [bullet[1]];
      while (i + 1 < lines.length) {
        const next = BULLET.exec(lines[i + 1]);
        // An indented continuation line belongs to the item above it.
        if (next) {
          items.push(next[1]);
          i++;
        } else if (/^\s{2,}\S/.test(lines[i + 1])) {
          items[items.length - 1] += " " + lines[i + 1].trim();
          i++;
        } else break;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    const numbered = NUMBERED.exec(line);
    if (numbered) {
      flush();
      const items = [numbered[2]];
      while (i + 1 < lines.length) {
        const next = NUMBERED.exec(lines[i + 1]);
        if (next) {
          items.push(next[2]);
          i++;
        } else if (/^\s{2,}\S/.test(lines[i + 1])) {
          items[items.length - 1] += " " + lines[i + 1].trim();
          i++;
        } else break;
      }
      blocks.push({ kind: "ol", items, start: Number(numbered[1]) || 1 });
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      flush();
      const parts = [quote[1]];
      while (i + 1 < lines.length && QUOTE.test(lines[i + 1])) {
        parts.push(QUOTE.exec(lines[++i])![1]);
      }
      blocks.push({ kind: "quote", text: parts.join("\n") });
      continue;
    }

    paragraph.push(line);
  }
  flush();
  return blocks;
}

/* ── inline spans ───────────────────────────────────────────── */
// Ordered longest-delimiter-first so `**bold**` is not read as two `*em*`.
// Built fresh per call rather than shared: `renderInline` recurses into the
// contents of a bold or italic span, and a module-level /g regex carries
// `lastIndex` into the nested call and back out of it, so the outer scan
// resumed from the wrong offset and dropped text after `**bold `code` **`.
export const INLINE_SOURCE =
  "(`[^`\\n]+`|\\*\\*[^*\\n]+\\*\\*|__[^_\\n]+__|\\*[^*\\n]+\\*|" +
  "(?<![A-Za-z0-9])_[^_\\n]+_(?![A-Za-z0-9])|~~[^~\\n]+~~|" +
  "\\[[^\\]\\n]+\\]\\([^)\\s]+\\))";

export const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/;

