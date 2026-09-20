// End-to-end check: boots the FastAPI (8000) + Next dev (3005), then verifies
// the exact client contract the UI depends on:
//   1. create project -> 201 with JSON body
//   2. delete project -> 204 with EMPTY body (the bug: old client parsed it as JSON)
//   3. deleted project -> 404
//   4. home page renders via next dev
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

const ROOT = "D:/SIH_fixed/SIH";
const API_LOG = `${ROOT}/apps/api/_e2e_api.log`;

function start(cmd, args, opts) {
  const p = spawn(cmd, args, { shell: true, ...opts });
  return p;
}

async function waitFor(url, timeoutMs, label) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch { /* not up yet */ }
    await sleep(500);
  }
  throw new Error(`${label} did not become ready`);
}

const api = start("python", ["-m", "uvicorn", "app.main:app", "--port", "8000", "--log-level", "warning"],
  { cwd: `${ROOT}/apps/api`, stdio: ["ignore", "pipe", "pipe"], shell: false });
api.stdout?.on("data", () => {});
api.stderr?.pipe((await import("node:fs")).createWriteStream(API_LOG));

const next = start(process.execPath,
  ["node_modules/next/dist/bin/next", "dev", "-p", "3005"],
  { cwd: `${ROOT}/apps/web`, stdio: "ignore", shell: false });

let failures = 0;
function check(label, cond, extra = "") {
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${extra ? ` (${extra})` : ""}`);
  if (!cond) failures++;
}

try {
  await waitFor("http://127.0.0.1:8000/api/health", 30000, "API");
  console.log("API ready on :8000");

  const created = await fetch("http://127.0.0.1:8000/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: "__e2e__", description: "" }),
  });
  check("create project -> 201", created.status === 201, `got ${created.status}`);
  const proj = await created.json();

  const del = await fetch(`http://127.0.0.1:8000/api/projects/${proj.id}`, { method: "DELETE" });
  const delBody = await del.text();
  check("delete project -> 204", del.status === 204, `got ${del.status}`);
  check("delete body is empty (204)", delBody === "", delBody ? `body=${delBody.slice(0, 50)}` : "");
  console.log("      ^ old client did resp.json() here -> SyntaxError -> misleading 'is the API running?'");

  const gone = await fetch(`http://127.0.0.1:8000/api/projects/${proj.id}`);
  check("deleted project -> 404", gone.status === 404, `got ${gone.status}`);

  // document delete contract too (also 204 through the same client path)
  // (covered by apps/api/verify_api.py roundtrip; skipped here for speed)

  await waitFor("http://127.0.0.1:3005", 60000, "next dev");
  const page = await fetch("http://127.0.0.1:3005/");
  const html = await page.text();
  check("next dev home page -> 200", page.status === 200, `got ${page.status}`);
  check("home page contains product name", html.includes("Meshcore"));
  check(
    "home page exposes P&ID as a first-class capability",
    html.includes("P&amp;ID") && html.includes("first-class"),
  );
  check(
    "home page has the Claude-like composer",
    html.includes("Start task") && html.includes("Describe the task"),
  );
  check("home page has capability launcher", html.includes("Capabilities"));
  check("home page shows egress counter", html.includes("egress"));

  // The P&ID entry card must NOT re-implement P&ID — it routes into the
  // existing interface (README §0.1).
  check(
    "P&ID entry routes to the existing interface",
    html.includes("view=pid") || html.includes("/projects/"),
  );

  // Project management lives on its own page now (the home screen is the
  // conversational front door, not a project list).
  const projects = await fetch("http://127.0.0.1:3005/workspace");
  const projectsHtml = await projects.text();
  check(
    "projects page -> 200",
    projects.status === 200,
    `got ${projects.status}`,
  );
  check(
    "projects page has create form",
    projectsHtml.includes("Create") && projectsHtml.includes("name="),
  );
} catch (e) {
  console.error("E2E setup error:", e.message);
  failures++;
} finally {
  for (const p of [api, next]) {
    try { spawn("taskkill", ["/PID", String(p.pid), "/T", "/F"], { shell: false }); } catch {}
  }
}
process.exit(failures ? 1 : 0);