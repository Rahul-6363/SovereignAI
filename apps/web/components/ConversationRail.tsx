"use client";
/** Chat thread rail — the list of conversations in this project.
 *
 *  Threads are the unit of context: everything in one is remembered together
 *  and nothing leaks between them. Keeping separate lines of work apart is
 *  the whole reason to have more than one, so this is deliberately plain —
 *  a list, a New chat button, and rename/delete on the row.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ConversationRec } from "@/lib/types";
import { cn } from "./ui";

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

  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-ink-800 bg-ink-950">
      <div className="p-3">
        <button
          onClick={onNew}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-sm font-medium text-ink-100 transition hover:border-accent hover:text-accent"
        >
          <span aria-hidden>+</span> New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {loading && (
          <p className="px-2 py-3 text-xs text-zinc-500">Loading chats…</p>
        )}

        {!loading && rows.length === 0 && (
          <p className="px-2 py-3 text-xs leading-relaxed text-zinc-500">
            No chats yet. Ask a question to start one — it will be saved here
            with its evidence and any files it produces.
          </p>
        )}

        <ul className="space-y-0.5">
          {rows.map((c) => {
            const active = c.id === activeId;
            return (
              <li key={c.id} className="group relative">
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
                    className="w-full rounded-md border border-accent bg-ink-900 px-2.5 py-2 text-sm text-ink-100 outline-none"
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
                      "w-full rounded-md px-2.5 py-2 text-left transition",
                      active
                        ? "bg-ink-800 text-ink-50"
                        : "text-zinc-400 hover:bg-ink-900 hover:text-ink-100",
                    )}
                  >
                    <span className="block truncate pr-12 text-sm">
                      {c.title || "New chat"}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-zinc-600">
                      {whenLabel(c.updated_at)}
                      {c.message_count ? ` · ${c.message_count} messages` : ""}
                    </span>
                  </button>
                )}

                {renaming !== c.id && (
                  <div className="absolute right-1.5 top-1.5 hidden gap-0.5 group-hover:flex">
                    <button
                      onClick={() => {
                        setDraftTitle(c.title);
                        setRenaming(c.id);
                      }}
                      title="Rename"
                      className="rounded p-1 text-xs text-zinc-500 hover:bg-ink-700 hover:text-ink-100"
                    >
                      ✎
                    </button>
                    <button
                      onClick={() => setConfirmDelete(c.id)}
                      title="Delete chat"
                      className="rounded p-1 text-xs text-zinc-500 hover:bg-ink-700 hover:text-red-400"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {confirmDelete === c.id && (
                  <div className="mt-1 rounded-md border border-red-900/60 bg-red-950/30 p-2">
                    <p className="text-[11px] text-red-200">
                      Delete this chat and its messages?
                    </p>
                    <div className="mt-1.5 flex gap-1.5">
                      <button
                        onClick={() => void remove(c.id)}
                        className="rounded bg-red-900/60 px-2 py-0.5 text-[11px] text-red-100 hover:bg-red-900"
                      >
                        Delete
                      </button>
                      <button
                        onClick={() => setConfirmDelete(null)}
                        className="rounded px-2 py-0.5 text-[11px] text-zinc-400 hover:text-ink-100"
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

      <p className="border-t border-ink-800 px-3 py-2 text-[11px] leading-relaxed text-zinc-600">
        Each chat keeps its own context. Double-click a title to rename.
      </p>
    </aside>
  );
}
