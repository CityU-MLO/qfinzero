"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, UserPlus } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/components/user-menu";
import { auth, ROLE_LABEL, type Role } from "@/lib/auth";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";
const ROLES: Role[] = ["viewer", "researcher", "admin"];

export default function UsersPage() {
  const { data: me } = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auth", "users"], queryFn: auth.users, enabled: me?.role === "admin" });
  const [form, setForm] = useState({ username: "", password: "", role: "researcher" as Role });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  if (me && me.role !== "admin") return <p className="text-sm text-muted-foreground">Only admins can manage users.</p>;

  const refresh = () => qc.invalidateQueries({ queryKey: ["auth", "users"] });
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
      await refresh();
    } catch (err) {
      setMsg({ ok: false, text: (err as Error).message });
    }
  };
  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    await run(() => auth.createUser(form), `Created ${form.username}`);
    setForm({ username: "", password: "", role: "researcher" });
    setBusy(false);
  };
  const resetPassword = (id: number, name: string) => {
    const pw = window.prompt(`New password for ${name} (10+ characters)`);
    if (pw) run(() => auth.updateUser(id, { password: pw }), `Password reset for ${name}`);
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Users" description="Viewers read; researchers trade, research and use MCP; admins also manage data and users." />
      {msg && <Alert variant={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader><CardTitle>Accounts</CardTitle></CardHeader>
          <CardContent>
            {q.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr><th className="px-3 py-2">User</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Last sign-in</th><th className="px-3 py-2">Status</th><th className="px-3 py-2" /></tr>
                </thead>
                <tbody>
                  {(q.data?.users ?? []).map((u) => (
                    <tr key={u.id} className="border-t">
                      <td className="px-3 py-2 font-medium">{u.username}{u.id === me?.id && <span className="ml-1 text-xs text-muted-foreground">(you)</span>}</td>
                      <td className="px-3 py-2">
                        <select className="rounded-md border bg-card px-2 py-1 text-sm" value={u.role}
                                onChange={(e) => run(() => auth.updateUser(u.id, { role: e.target.value as Role }), `${u.username} is now ${ROLE_LABEL[e.target.value as Role]}`)}>
                          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                        </select>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{u.last_login_at ? new Date(u.last_login_at * 1000).toLocaleString() : "never"}</td>
                      <td className="px-3 py-2">
                        <button className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${u.disabled ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success"}`}
                                onClick={() => run(() => auth.updateUser(u.id, { disabled: !u.disabled }), `${u.username} ${u.disabled ? "enabled" : "disabled"}`)}
                                title="Toggle">
                          {u.disabled ? "Disabled" : "Active"}
                        </button>
                      </td>
                      <td className="space-x-1 px-3 py-2 text-right">
                        <button className="rounded-md px-2 py-1 text-xs hover:bg-accent" onClick={() => resetPassword(u.id, u.username)}>Reset password</button>
                        {u.id !== me?.id && (
                          <button className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                                  onClick={() => window.confirm(`Delete ${u.username} and their API keys?`) && run(() => auth.deleteUser(u.id), `Deleted ${u.username}`)}>
                            <Trash2 className="h-3.5 w-3.5" /> Delete
                          </button>
                        )}
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
            <CardTitle className="flex items-center gap-2"><UserPlus className="h-4 w-4" /> Add a user</CardTitle>
            <CardDescription>Share the temporary password privately; they can change it on their account page.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={create} className="space-y-3">
              <input className={input} placeholder="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
              <input className={input} type="password" placeholder="temporary password (10+ characters)" autoComplete="new-password"
                     value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={10} />
              <select className={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
              <button disabled={busy} className="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} Create user
              </button>
            </form>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>All API keys</CardTitle><CardDescription>Revoke a key from its owner&apos;s row on their account page, or here.</CardDescription></CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-lg border">
            <table className="w-full text-sm">
              <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                <tr><th className="px-3 py-2">Owner</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Key</th><th className="px-3 py-2">Last used</th><th className="px-3 py-2" /></tr>
              </thead>
              <tbody>
                {(q.data?.keys ?? []).filter((k) => !k.revoked).map((k) => (
                  <tr key={k.id} className="border-t">
                    <td className="px-3 py-2">{k.username}</td>
                    <td className="px-3 py-2 font-medium">{k.name}</td>
                    <td className="px-3 py-2 font-mono text-xs">{k.prefix}_…</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">{k.last_used_at ? new Date(k.last_used_at * 1000).toLocaleString() : "never"}</td>
                    <td className="px-3 py-2 text-right">
                      <button className="rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10" onClick={() => run(() => auth.revokeKey(k.id), `Revoked ${k.prefix}`)}>Revoke</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
