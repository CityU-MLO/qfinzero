"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Loader2, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/components/user-menu";
import { auth, ROLE_LABEL, type ApiKey } from "@/lib/auth";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

function when(ts: number | null) {
  return ts ? new Date(ts * 1000).toLocaleString() : "never";
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="inline-flex items-center gap-1 rounded-md border bg-card px-2 py-1 text-xs hover:bg-accent"
            onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); })}>
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />} {done ? "Copied" : "Copy"}
    </button>
  );
}

export default function AccountPage() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["auth", "keys"], queryFn: auth.keys, enabled: !!me });
  const [keyName, setKeyName] = useState("");
  const [fresh, setFresh] = useState<{ key: ApiKey; token: string } | null>(null);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [origin, setOrigin] = useState("https://your-host");
  useEffect(() => setOrigin(window.location.origin), []);

  if (!me) {
    return <p className="text-sm text-muted-foreground">Accounts are managed by the QFinZero hub. Sign in through it to manage keys.</p>;
  }

  const createKey = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      setFresh(await auth.createKey(keyName || "agent"));
      setKeyName("");
      await qc.invalidateQueries({ queryKey: ["auth", "keys"] });
    } finally {
      setBusy(false);
    }
  };
  const revoke = async (id: number) => {
    await auth.revokeKey(id);
    await qc.invalidateQueries({ queryKey: ["auth", "keys"] });
  };
  const changePw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.next !== pw.confirm) return setPwMsg({ ok: false, text: "new passwords do not match" });
    try {
      await auth.changePassword(pw.current, pw.next);
      setPw({ current: "", next: "", confirm: "" });
      setPwMsg({ ok: true, text: "Password changed. Other browsers were signed out." });
    } catch (err) {
      setPwMsg({ ok: false, text: (err as Error).message });
    }
  };

  const mcp = JSON.stringify({ mcpServers: { qfinzero: { url: `${origin}/mcp/`,
    headers: { Authorization: `Bearer ${fresh?.token ?? "qfz_…"}` } } } }, null, 2);
  const live = (keys.data?.keys ?? []).filter((k) => !k.revoked);

  return (
    <>
    <PageHeader title="Account" description="Your profile, password and API keys for agents and scripts." />
    <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>{me.display_name || me.username}</CardTitle>
            <CardDescription>Signed in as <span className="font-mono">{me.username}</span> · {ROLE_LABEL[me.role]}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {me.role === "viewer" && "Viewers can read data and sessions but cannot trade or use MCP."}
            {me.role === "researcher" && "Researchers can trade in sessions, run research and connect agents over MCP."}
            {me.role === "admin" && "Admins can also manage data sources and users."}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Change password</CardTitle>
            <CardDescription>Changing it signs out every other browser.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={changePw} className="space-y-3">
              <input className={input} type="password" placeholder="Current password" autoComplete="current-password"
                     value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
              <input className={input} type="password" placeholder="New password (10+ characters)" autoComplete="new-password"
                     value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required minLength={10} />
              <input className={input} type="password" placeholder="Confirm new password" autoComplete="new-password"
                     value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
              {pwMsg && <p className={`text-sm ${pwMsg.ok ? "text-success" : "text-destructive"}`}>{pwMsg.text}</p>}
              <button className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">Update password</button>
            </form>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> API keys</CardTitle>
            <CardDescription>For agents, scripts and MCP clients. A key acts with your role; the token is shown once.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <form onSubmit={createKey} className="flex gap-2">
              <input className={input} placeholder="Key name, e.g. eval-runner" value={keyName} onChange={(e) => setKeyName(e.target.value)} />
              <button disabled={busy} className="flex h-9 flex-none items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} Create key
              </button>
            </form>
            {fresh && (
              <div className="rounded-lg border border-success/30 bg-success/10 p-4">
                <p className="text-sm font-semibold text-success">New key “{fresh.key.name}”: copy it now, it will not be shown again.</p>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 overflow-x-auto rounded-md bg-card px-2 py-1.5 font-mono text-xs">{fresh.token}</code>
                  <CopyButton text={fresh.token} />
                </div>
              </div>
            )}
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr><th className="px-3 py-2">Name</th><th className="px-3 py-2">Key</th><th className="px-3 py-2">Last used</th><th className="px-3 py-2" /></tr>
                </thead>
                <tbody>
                  {live.length === 0 && <tr><td colSpan={4} className="px-3 py-4 text-center text-muted-foreground">No keys yet.</td></tr>}
                  {live.map((k) => (
                    <tr key={k.id} className="border-t">
                      <td className="px-3 py-2 font-medium">{k.name}</td>
                      <td className="px-3 py-2 font-mono text-xs">{k.prefix}_…</td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{when(k.last_used_at)}</td>
                      <td className="px-3 py-2 text-right">
                        <button onClick={() => revoke(k.id)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10" title="Revoke">
                          <Trash2 className="h-3.5 w-3.5" /> Revoke
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Connect an agent over MCP</CardTitle>
            <CardDescription>
              Add the header <span className="font-mono">X-QFZ-Session: sess_…</span> to lock every data tool to a simulation session&apos;s clock.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="relative">
              <pre className="overflow-x-auto rounded-lg bg-muted p-4 font-mono text-[12.5px] leading-relaxed text-foreground">{mcp}</pre>
              <div className="absolute right-2 top-2"><CopyButton text={mcp} /></div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
    </>
  );
}
