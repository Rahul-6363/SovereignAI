/** Shared state shape for `useActionState`-based server actions.
 *  (Lives outside actions.ts because "use server" modules may only
 *  export async functions.) */
export type ActionState = { ok: boolean; error: string };

export const initialActionState: ActionState = { ok: false, error: "" };
