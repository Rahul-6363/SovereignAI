"use client";

/** Create-project form with inline errors + pending state (no page crash). */
import { useActionState } from "react";
import { createProjectAction } from "@/actions";
import { initialActionState } from "@/lib/action-state";

export default function NewProjectForm() {
  const [state, formAction, pending] = useActionState(
    createProjectAction,
    initialActionState,
  );
  return (
    <form
      key={state.ok ? "reset" : "form"} // remount clears inputs after success
      action={formAction}
      className="flex w-full flex-col items-start gap-3 rounded-xl border border-ink-700 bg-ink-850 p-4 sm:flex-row sm:items-center"
    >
      <input
        name="name"
        required
        minLength={1}
        maxLength={120}
        placeholder="e.g. Refinery Unit A"
        className="min-w-[200px] rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-accent focus:outline-none"
      />
      <input
        name="description"
        placeholder="Optional description"
        className="min-w-[200px] rounded-lg border border-ink-600 bg-ink-900 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:border-accent focus:outline-none"
      />
      <button
        type="submit"
        disabled={pending}
        className="shrink-0 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-soft disabled:opacity-60"
      >
        {pending ? "Creating…" : "+ Create project"}
      </button>
      {state.error && (
        <p className="text-sm text-rose-400">{state.error}</p>
      )}
    </form>
  );
}
