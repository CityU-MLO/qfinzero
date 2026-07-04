import { NextResponse } from "next/server";
import { promises as fs } from "fs";
import path from "path";

// Repo root relative to the Next process cwd (infra/dashboard-web).
const REPO_ROOT = path.resolve(process.cwd(), "../../");
const SKIP = new Set([
  "node_modules", ".next", ".git", ".venv", "__pycache__", "results",
  "logs", ".pytest_cache", "qfinzero.egg-info", "earning_benchmark",
]);

async function walk(dir: string, acc: string[], depth = 0): Promise<void> {
  if (depth > 4) return;
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const e of entries) {
    if (e.name.startsWith(".")) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (SKIP.has(e.name)) continue;
      await walk(full, acc, depth + 1);
    } else if (e.name.toLowerCase().endsWith(".md")) {
      acc.push(path.relative(REPO_ROOT, full));
    }
  }
}

export async function GET(req: Request) {
  const rel = new URL(req.url).searchParams.get("path");
  if (rel) {
    const target = path.resolve(REPO_ROOT, rel);
    if (!target.startsWith(REPO_ROOT + path.sep) || !target.toLowerCase().endsWith(".md")) {
      return NextResponse.json({ error: "invalid path" }, { status: 400 });
    }
    try {
      const content = await fs.readFile(target, "utf8");
      return NextResponse.json({ path: rel, content });
    } catch {
      return NextResponse.json({ error: "not found" }, { status: 404 });
    }
  }
  const acc: string[] = [];
  await walk(REPO_ROOT, acc);
  acc.sort();
  return NextResponse.json({ docs: acc });
}
