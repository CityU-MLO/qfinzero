"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2, UserPlus } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/components/user-menu";
import { CreateKey, FreshToken, KeyTable } from "@/components/api-keys";
import { auth, roleLabel, type ApiKey, type Role } from "@/lib/auth";
import { useLocale, useT } from "@/components/locale-provider";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";
const ROLES: Role[] = ["viewer", "researcher", "admin"];

export default function UsersPage() {
  const { data: me } = useMe();
  const t = useT();
  const { locale } = useLocale();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["auth", "users"], queryFn: auth.users, enabled: me?.role === "admin" });
  const [form, setForm] = useState({ username: "", password: "", role: "researcher" as Role });
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState<{ key: ApiKey; token: string } | null>(null);

  if (me && me.role !== "admin") return <p className="text-sm text-muted-foreground">{t("Only admins can manage users.", "只有管理员可以管理用户。")}</p>;

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
    await run(() => auth.createUser(form), t(`Created ${form.username}`, `已创建 ${form.username}`));
    setForm({ username: "", password: "", role: "researcher" });
    setBusy(false);
  };
  const resetPassword = (id: number, name: string) => {
    const pw = window.prompt(t(`New password for ${name} (10+ characters)`, `为 ${name} 设置新密码（至少 10 个字符）`));
    if (pw) run(() => auth.updateUser(id, { password: pw }), t(`Password reset for ${name}`, `已重置 ${name} 的密码`));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("Users", "用户")}
        description={t(
          "Viewers read; researchers trade, research and use MCP; admins also manage data and users.",
          "访客只读；研究员可交易、做研究并使用 MCP；管理员还可管理数据和用户。",
        )}
      />
      {msg && <Alert variant={msg.ok ? "success" : "error"}>{msg.text}</Alert>}
      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader><CardTitle>{t("Accounts", "账户")}</CardTitle></CardHeader>
          <CardContent>
            {q.isLoading && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
            <div className="overflow-hidden rounded-lg border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/50 text-left text-xs text-muted-foreground">
                  <tr><th className="px-3 py-2">{t("User", "用户")}</th><th className="px-3 py-2">{t("Role", "角色")}</th><th className="px-3 py-2">{t("Last sign-in", "最近登录")}</th><th className="px-3 py-2">{t("Status", "状态")}</th><th className="px-3 py-2" /></tr>
                </thead>
                <tbody>
                  {(q.data?.users ?? []).map((u) => (
                    <tr key={u.id} className="border-t">
                      <td className="px-3 py-2 font-medium">{u.username}{u.id === me?.id && <span className="ml-1 text-xs text-muted-foreground">{t("(you)", "（你）")}</span>}</td>
                      <td className="px-3 py-2">
                        <select className="rounded-md border bg-card px-2 py-1 text-sm" value={u.role}
                                onChange={(e) => run(() => auth.updateUser(u.id, { role: e.target.value as Role }), t(`${u.username} is now ${roleLabel(e.target.value as Role, "en")}`, `${u.username} 现在是${roleLabel(e.target.value as Role, "zh")}`))}>
                          {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r, locale)}</option>)}
                        </select>
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">{u.last_login_at ? new Date(u.last_login_at * 1000).toLocaleString() : t("never", "从未")}</td>
                      <td className="px-3 py-2">
                        <button className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${u.disabled ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success"}`}
                                onClick={() => run(() => auth.updateUser(u.id, { disabled: !u.disabled }), u.disabled ? t(`${u.username} enabled`, `已启用 ${u.username}`) : t(`${u.username} disabled`, `已停用 ${u.username}`))}
                                title={u.disabled ? t("Enable", "启用") : t("Disable", "停用")}>
                          {u.disabled ? t("Disabled", "已停用") : t("Active", "正常")}
                        </button>
                      </td>
                      <td className="space-x-1 px-3 py-2 text-right">
                        <button className="rounded-md px-2 py-1 text-xs hover:bg-accent" onClick={() => resetPassword(u.id, u.username)}>{t("Reset password", "重置密码")}</button>
                        {u.id !== me?.id && (
                          <button className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-destructive hover:bg-destructive/10"
                                  onClick={() => window.confirm(t(`Delete ${u.username} and their API keys?`, `删除 ${u.username} 及其所有 API 密钥？`)) && run(() => auth.deleteUser(u.id), t(`Deleted ${u.username}`, `已删除 ${u.username}`))}>
                            <Trash2 className="h-3.5 w-3.5" /> {t("Delete", "删除")}
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
            <CardTitle className="flex items-center gap-2"><UserPlus className="h-4 w-4" /> {t("Add a user", "添加用户")}</CardTitle>
            <CardDescription>{t("Share the temporary password privately; they can change it on their account page.", "请私下告知临时密码；对方可在其账户页面自行修改。")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={create} className="space-y-3">
              <input className={input} placeholder={t("username", "用户名")} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
              <input className={input} type="password" placeholder={t("temporary password (10+ characters)", "临时密码（至少 10 个字符）")} autoComplete="new-password"
                     value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={10} />
              <select className={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
                {ROLES.map((r) => <option key={r} value={r}>{roleLabel(r, locale)}</option>)}
              </select>
              <button disabled={busy} className="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60">
                {busy && <Loader2 className="h-4 w-4 animate-spin" />} {t("Create user", "创建用户")}
              </button>
            </form>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>{t("API keys", "API 密钥")}</CardTitle>
          <CardDescription>{t("Issue scoped keys to people and agents, see what each key is used for, and change or revoke it.", "给用户或 agent 发放限定权限的密钥，查看每个密钥的用量，并修改或吊销。")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {fresh && <FreshToken fresh={fresh} onDismiss={() => setFresh(null)} />}
          <KeyTable keys={q.data?.keys ?? []} showOwner onChanged={refresh}
                    roleOf={(k) => q.data?.users.find((u) => u.id === k.user_id)?.role ?? "viewer"} />
          <details className="rounded-lg border p-4">
            <summary className="cursor-pointer text-sm font-medium">{t("Issue a key", "发放密钥")}</summary>
            <div className="mt-4">
              {me && <CreateKey ownerRole={me.role} users={q.data?.users} onCreated={(r) => { setFresh(r); refresh(); }} />}
            </div>
          </details>
        </CardContent>
      </Card>
    </div>
  );
}
