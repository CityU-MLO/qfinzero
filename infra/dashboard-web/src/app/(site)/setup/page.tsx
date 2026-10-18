"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { auth } from "@/lib/auth";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

export default function SetupPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [state, setState] = useState<"loading" | "open" | "done">("loading");
  const [form, setForm] = useState({ token: "", username: "admin", password: "", confirm: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    auth.status()
      .then((s) => setState(s.setup_required ? "open" : "done"))
      .catch(() => setState("done"));
  }, []);

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm) return setError("passwords do not match");
    setBusy(true);
    try {
      await auth.setup(form.token.trim(), form.username, form.password);
      await qc.invalidateQueries({ queryKey: ["auth"] });
      router.replace("/account");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md px-4 py-16 md:py-20">
      <div className="rounded-lg border bg-card p-6">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <ShieldCheck className="h-5 w-5 text-primary" />
          Create the first admin
        </h1>
        {state === "done" ? (
          <p className="mt-3 text-sm text-muted-foreground">
            This server is already set up. <Link href="/login" className="font-semibold text-primary underline">Sign in</Link> instead.
          </p>
        ) : (
          <>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              Enter the one-time setup token printed in the hub log on first start (also in
              <code className="mx-1 rounded-sm bg-secondary px-1 font-mono text-xs">$QFZ_DATA_ROOT/_state/setup_token</code>).
            </p>
            <form onSubmit={submit} className="mt-6 space-y-4">
              <label className="block text-sm font-medium">
                Setup token
                <input className={`${input} mt-1.5 font-mono`} value={form.token} onChange={set("token")} required autoFocus />
              </label>
              <label className="block text-sm font-medium">
                Admin username
                <input className={`${input} mt-1.5`} value={form.username} onChange={set("username")} required />
              </label>
              <label className="block text-sm font-medium">
                Password <span className="font-normal text-muted-foreground">(10+ characters)</span>
                <input className={`${input} mt-1.5`} type="password" autoComplete="new-password"
                       value={form.password} onChange={set("password")} required minLength={10} />
              </label>
              <label className="block text-sm font-medium">
                Confirm password
                <input className={`${input} mt-1.5`} type="password" autoComplete="new-password"
                       value={form.confirm} onChange={set("confirm")} required />
              </label>
              {error && <Alert variant="error">{error}</Alert>}
              <button type="submit" disabled={busy || state === "loading"}
                      className={cn(buttonVariants(), "w-full")}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} Create admin and sign in
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
