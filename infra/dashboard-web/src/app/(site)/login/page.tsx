"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Lock } from "lucide-react";

import { auth, safeNext } from "@/lib/auth";

const input =
  "w-full rounded-lg border bg-white px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const qc = useQueryClient();
  const next = safeNext(params.get("next"));
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [setupRequired, setSetupRequired] = useState(false);

  useEffect(() => {
    auth.status().then((s) => setSetupRequired(s.setup_required)).catch(() => undefined);
    auth.me().then((me) => me && router.replace(next));
  }, [next, router]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await auth.login(username, password);
      await qc.invalidateQueries({ queryKey: ["auth"] });
      router.replace(next);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-md flex-col px-4 py-16 md:py-24">
      <div className="rounded-2xl border bg-white/90 p-8 shadow-xl">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-secondary text-primary">
          <Lock className="h-5 w-5" />
        </span>
        <h1 className="mt-5 text-2xl font-bold tracking-tight">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">Use the account your administrator created.</p>
        {setupRequired && (
          <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            No accounts exist yet. <Link href="/setup" className="font-semibold underline">Create the first admin</Link>.
          </p>
        )}
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm font-medium">
            Username
            <input className={`${input} mt-1.5`} autoComplete="username" value={username}
                   onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label className="block text-sm font-medium">
            Password
            <input className={`${input} mt-1.5`} type="password" autoComplete="current-password"
                   value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">{error}</p>}
          <button type="submit" disabled={busy}
                  className="flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-sm font-semibold text-primary-foreground shadow hover:bg-primary/90 disabled:opacity-60">
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} Sign in
          </button>
        </form>
      </div>
      <p className="mt-6 text-center text-xs text-muted-foreground">
        Agents and scripts use API keys instead of passwords: create one on your account page.
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
