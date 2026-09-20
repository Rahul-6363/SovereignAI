"use server";

import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";
import type { ActionState } from "@/lib/action-state";

/** Human-readable failure reason; distinguishes "API down" from API errors. */
function readableError(e: unknown): string {
  if (e instanceof TypeError) {
    // fetch() itself failed: connection refused / DNS — API not reachable.
    return "Cannot reach the API. Start it with: python -m uvicorn app.main:app (in apps/api)";
  }
  return e instanceof Error ? e.message : "Unexpected error";
}

export async function createProjectAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const name = String(formData.get("name") || "").trim();
  const description = String(formData.get("description") || "").trim();
  if (!name) return { ok: false, error: "Project name is required." };
  try {
    await api.createProject(name, description);
  } catch (e) {
    console.error("createProjectAction failed:", e);
    return { ok: false, error: readableError(e) };
  }
  revalidatePath("/");
  return { ok: true, error: "" };
}

export async function deleteProjectAction(
  _prev: ActionState,
  formData: FormData,
): Promise<ActionState> {
  const projectId = Number(formData.get("projectId"));
  if (!Number.isFinite(projectId) || projectId <= 0) {
    return { ok: false, error: "Invalid project id." };
  }
  try {
    await api.deleteProject(projectId);
  } catch (e) {
    console.error("deleteProjectAction failed:", e);
    return { ok: false, error: readableError(e) };
  }
  revalidatePath("/");
  return { ok: true, error: "" };
}
