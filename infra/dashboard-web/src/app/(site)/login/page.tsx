"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Lock } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { auth, safeNext } from "@/lib/auth";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

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
    <div className="mx-auto flex max-w-sm flex-col px-4 py-16 md:py-20">
      <div className="rounded-lg border bg-card p-6">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <Lock className="h-5 w-5 text-primary" />
          Sign in
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">Use the account your administrator created.</p>
        {setupRequired && (
          <Alert variant="warning" className="mt-4">
            No accounts exist yet. <Link href="/setup" className="font-medium text-primary underline">Create the first admin</Link>.
          </Alert>
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
          {error && <Alert variant="error">{error}</Alert>}
          <button type="submit" disabled={busy}
                  className={cn(buttonVariants(), "w-full")}>
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
