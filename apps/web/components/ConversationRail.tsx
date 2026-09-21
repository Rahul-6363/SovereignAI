"use client";
/** Chat thread rail — the conversations in this project.
 *
 *  Threads are the unit of context: everything in one is remembered together
 *  and nothing leaks between them. Keeping separate lines of work apart is
 *  the whole reason to have more than one.
 *
 *  Two things make a thread list usable past about fifteen chats, and this
 *  had neither: search, and date grouping. Without them the only way back to
 *  last Tuesday's relief-valve thread is to scroll a flat list reading
 *  truncated titles, which is exactly when people give up and start a new
 *  chat instead — losing the context the threads existed to keep.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConversationRec } from "@/lib/types";
import {
  IconButton,
  Menu,
  SearchInput,
  Skeleton,
  cn,
} from "./ui";
import { IconMessage, IconMore, IconPencil, IconTrash } from "./icons";

/** "3:04 pm" today, "Tue" this week, "4 Mar" beyond it. */
function whenLabel(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const now = new Date();
  const sameDay = then.toDateString() === now.toDateString();
  if (sameDay) {
    return then.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  const days = (now.getTime() - then.getTime()) / 86_400_000;
  if (days < 7) return then.toLocaleDateString([], { weekday: "short" });
  return then.toLocaleDateString([], { day: "numeric", month: "short" });
}

/** Which bucket a thread belongs to. Ordered, so the groups render in order. */
const GROUPS = ["Today", "Yesterday", "Previous 7 days", "Older"] as const;
type Group = (typeof GROUPS)[number];

function groupOf(iso: string): Group {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "Older";
  const now = new Date();
  if (then.toDateString() === now.toDateString()) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  if ((now.getTime() - then.getTime()) / 86_400_000 < 7)
    return "Previous 7 days";
  return "Older";
}

export default function ConversationRail({
  projectId,
  activeId,
  onSelect,
  onNew,
  refreshKey = 0,
}: {
  projectId: number;
  activeId: number | null;
  onSelect: (id: number) => void;
  onNew: () => void;
  /** Bumped by the chat pane after a turn, so titles and counts stay live. */
  refreshKey?: number;
}) {
  const [rows, setRows] = useState<ConversationRec[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [renaming, setRenaming] = useState<number | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const renameRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.projectConversations(projectId));
    } catch {
      /* the rail is navigation, not content: a failure must not block chat */
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (renaming !== null) renameRef.current?.focus();
  }, [renaming]);

  const commitRename = async (id: number) => {
    const title = draftTitle.trim();
    setRenaming(null);
    if (!title) return;
    // Optimistic: the rename is trivially reversible and waiting on a round
    // trip to see your own typing appear feels broken.
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, title } : r)));
    try {
      await api.renameConversation(id, title);
    } catch {
      void load();
    }
  };

  const remove = async (id: number) => {
    setConfirmDelete(null);
    setRows((rs) => rs.filter((r) => r.id !== id));
    try {
      await api.deleteConversation(id);
    } catch {
      void load();
      return;
    }
    // Deleting the thread you are reading has to move you somewhere.
    if (id === activeId) onNew();
  };

  // Searching the preview as well as the title matters because the title is
  // the first 48 characters of the first question — the thing you remember
  // about a thread is often in its second sentence, not its first.
  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q
      ? rows.filter(
          (r) =>
            r.title.toLowerCase().includes(q) ||
            (r.preview ?? "").toLowerCase().includes(q),
        )
      : rows;
    const buckets = new Map<Group, ConversationRec[]>();
    for (const row of matched) {
      const g = groupOf(row.updated_at);
      const list = buckets.get(g);
      if (list) list.push(row);
      else buckets.set(g, [row]);
    }
    return GROUPS.filter((g) => buckets.has(g)).map((g) => ({
      group: g,
      rows: buckets.get(g)!,
    }));
  }, [rows, query]);

  const total = rows.length;
  const shown = grouped.reduce((n, g) => n + g.rows.length, 0);

  return (
    <aside className="flex h-full w-[248px] shrink-0 flex-col border-r border-ink-800 bg-ink-950">
      <div className="border-b border-ink-800 p-2.5">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search chats…"
          ariaLabel="Search conversations"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {loading && (
          <div className="space-y-1.5 px-1 pt-1">
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
          </div>
        )}

        {!loading && total === 0 && (
          <div className="px-2 py-6 text-center">
            <span className="mx-auto mb-2 grid h-9 w-9 place-items-center rounded-xl border border-ink-800 bg-ink-900 text-zinc-600">
              <IconMessage size={16} />
            </span>
            <p className="text-[12px] leading-relaxed text-zinc-500">
              No chats yet. Ask a question to start one — it is saved here with
              its evidence and any files it produces.
            </p>
          </div>
        )}

        {!loading && total > 0 && shown === 0 && (
          <p className="px-2 py-6 text-center text-[12px] text-zinc-500">
            No chat matches “{query}”.
          </p>
        )}

        {grouped.map(({ group, rows: groupRows }) => (
          <div key={group} className="mb-3">
            <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-zinc-600">
              {group}
            </div>
            <ul className="space-y-0.5">
              {groupRows.map((c) => {
                const active = c.id === activeId;
                return (
                  <li key={c.id} className="group/row relative">
                    {renaming === c.id ? (
                      <input
                        ref={renameRef}
                        value={draftTitle}
                        onChange={(e) => setDraftTitle(e.target.value)}
                        onBlur={() => void commitRename(c.id)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void commitRename(c.id);
                          if (e.key === "Escape") setRenaming(null);
                        }}
                        aria-label="Rename chat"
                        className="w-full rounded-lg border border-accent bg-ink-900 px-2.5 py-2 text-[13px] text-zinc-100 outline-none"
                      />
                    ) : (
                      <button
                        onClick={() => onSelect(c.id)}
                        onDoubleClick={() => {
                          setDraftTitle(c.title);
                          setRenaming(c.id);
                        }}
                        title={c.preview || c.title}
                        className={cn(
                          "w-full rounded-lg px-2.5 py-2 text-left transition-colors",
                          active
                            ? "bg-ink-850 text-zinc-100"
                            : "text-zinc-400 hover:bg-ink-900 hover:text-zinc-200",
                        )}
                      >
                        <span className="block truncate pr-7 text-[13px] leading-snug">
                          {c.title || "New chat"}
                        </span>
                        <span className="mt-0.5 block text-[10px] text-zinc-600">
                          {whenLabel(c.updated_at)}
                          {c.message_count ? ` · ${c.message_count} msg` : ""}
                        </span>
                      </button>
                    )}

                    {renaming !== c.id && confirmDelete !== c.id && (
                      <div
                        className={cn(
                          "absolute right-1 top-1.5 opacity-0 transition-opacity",
                          "group-hover/row:opacity-100 group-focus-within/row:opacity-100",
                          active && "opacity-100",
                        )}
                      >
                        <Menu
                          trigger={({ toggle }) => (
                            <IconButton
                              icon={<IconMore size={14} />}
                              label="Chat options"
                              size="sm"
                              onClick={toggle}
                            />
                          )}
                          items={[
                            {
                              label: "Rename",
                              icon: <IconPencil size={14} />,
                              onSelect: () => {
                                setDraftTitle(c.title);
                                setRenaming(c.id);
                              },
                            },
                            {
                              label: "Delete chat",
                              icon: <IconTrash size={14} />,
                              tone: "danger",
                              onSelect: () => setConfirmDelete(c.id),
                            },
                          ]}
                        />
                      </div>
                    )}

                    {confirmDelete === c.id && (
                      <div className="mt-1 rounded-lg border border-rose-900/60 bg-rose-950/30 p-2">
                        <p className="text-[11px] leading-snug text-rose-200">
                          Delete this chat and its messages?
                        </p>
                        <div className="mt-1.5 flex gap-1.5">
                          <button
                            onClick={() => void remove(c.id)}
                            className="rounded-md bg-rose-900/70 px-2 py-0.5 text-[11px] font-medium text-rose-50 hover:bg-rose-900"
                          >
                            Delete
                          </button>
                          <button
                            onClick={() => setConfirmDelete(null)}
                            className="rounded-md px-2 py-0.5 text-[11px] text-zinc-400 hover:text-zinc-100"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <p className="border-t border-ink-800 px-3 py-2 text-[10px] leading-relaxed text-zinc-600">
        Each chat keeps its own context. Double-click a title to rename.
      </p>
    </aside>
  );
}
