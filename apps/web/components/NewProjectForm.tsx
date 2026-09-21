"use client";

/** Create-project form with inline errors + pending state (no page crash). */
import { useActionState } from "react";
import { createProjectAction } from "@/actions";
import { initialActionState } from "@/lib/action-state";
import { IconPlus } from "./icons";

export default function NewProjectForm() {
  const [state, formAction, pending] = useActionState(
    createProjectAction,
    initialActionState,
  );
  return (
    <form
      key={state.ok ? "reset" : "form"} // remount clears inputs after success
      action={formAction}
      className="w-full rounded-2xl border border-ink-800 bg-ink-850 p-3 shadow-raised"
    >
      <div className="flex w-full flex-col items-stretch gap-2 sm:flex-row sm:items-center">
        <input
          name="name"
          required
          minLength={1}
          maxLength={120}
          aria-label="Project name"
          placeholder="e.g. Refinery Unit A"
          className="h-9 min-w-[180px] flex-1 rounded-xl border border-ink-700 bg-ink-900 px-3 text-sm text-zinc-100 placeholder-zinc-600 transition-colors focus:border-ink-600 focus:outline-none"
        />
        <input
          name="description"
          aria-label="Project description"
          placeholder="Optional description"
          className="h-9 min-w-[180px] flex-1 rounded-xl border border-ink-700 bg-ink-900 px-3 text-sm text-zinc-100 placeholder-zinc-600 transition-colors focus:border-ink-600 focus:outline-none"
        />
        <button
          type="submit"
          disabled={pending}
          className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-white shadow-raised transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-50"
        >
          <IconPlus size={15} />
          {pending ? "Creating…" : "Create project"}
        </button>
      </div>
      {state.error && (
        <p className="mt-2 text-[12px] text-rose-400">{state.error}</p>
      )}
    </form>
  );
}
