"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";

import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useMe } from "@/components/user-menu";
import { CopyButton, CreateKey, FreshToken, KeyTable, useOrigin } from "@/components/api-keys";
import { auth, roleLabel, type ApiKey } from "@/lib/auth";
import { useLocale, useT } from "@/components/locale-provider";

const input =
  "w-full rounded-md border border-input bg-card px-3 py-2 text-sm outline-none focus:border-ring focus:ring-2 focus:ring-ring/20";

export default function AccountPage() {
  const { data: me } = useMe();
  const t = useT();
  const { locale } = useLocale();
  const qc = useQueryClient();
  const keys = useQuery({ queryKey: ["auth", "keys"], queryFn: auth.keys, enabled: !!me });
  const [fresh, setFresh] = useState<{ key: ApiKey; token: string } | null>(null);
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const origin = useOrigin();

  if (!me) {
    return <p className="text-sm text-muted-foreground">{t("Accounts are managed by the QFinZero hub. Sign in through it to manage keys.", "账户由 QFinZero hub 管理。请通过 hub 登录以管理密钥。")}</p>;
  }

  const refresh = () => qc.invalidateQueries({ queryKey: ["auth", "keys"] });
  const changePw = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pw.next !== pw.confirm) return setPwMsg({ ok: false, text: t("New passwords do not match", "两次输入的新密码不一致") });
    try {
      await auth.changePassword(pw.current, pw.next);
      setPw({ current: "", next: "", confirm: "" });
      setPwMsg({ ok: true, text: t("Password changed. Other browsers were signed out.", "密码已修改，其他浏览器已退出登录。") });
    } catch (err) {
      setPwMsg({ ok: false, text: (err as Error).message });
    }
  };

  const mcp = JSON.stringify({ mcpServers: { qfinzero: { url: `${origin}/mcp/`,
    headers: { Authorization: "Bearer qfz_…" } } } }, null, 2);

  return (
    <>
    <PageHeader
      title={t("Account", "账户")}
      description={t("Your profile, password and API keys for agents and scripts.", "你的个人资料、密码，以及供 agent 和脚本使用的 API 密钥。")}
    />
    <div className="grid gap-5 xl:grid-cols-[1fr_2fr]">
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>{me.display_name || me.username}</CardTitle>
            <CardDescription>{t("Signed in as", "当前登录：")} <span className="font-mono">{me.username}</span> · {roleLabel(me.role, locale)}</CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {me.role === "viewer" && t("Viewers can read data and sessions but cannot trade or use MCP.", "访客可以查看数据和会话，但不能交易或使用 MCP。")}
            {me.role === "researcher" && t("Researchers can trade in sessions, run research and connect agents over MCP.", "研究员可以在会话中交易、运行研究，并通过 MCP 接入 agent。")}
            {me.role === "admin" && t("Admins can also manage data sources and users.", "管理员还可以管理数据源和用户。")}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("Change password", "修改密码")}</CardTitle>
            <CardDescription>{t("Changing it signs out every other browser.", "修改后，其他所有浏览器都会退出登录。")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={changePw} className="space-y-3">
              <input className={input} type="password" placeholder={t("Current password", "当前密码")} autoComplete="current-password"
                     value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
              <input className={input} type="password" placeholder={t("New password (10+ characters)", "新密码（至少 10 个字符）")} autoComplete="new-password"
                     value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required minLength={10} />
              <input className={input} type="password" placeholder={t("Confirm new password", "确认新密码")} autoComplete="new-password"
                     value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} required />
              {pwMsg && <p className={`text-sm ${pwMsg.ok ? "text-success" : "text-destructive"}`}>{pwMsg.text}</p>}
              <button className="h-9 rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90">{t("Update password", "更新密码")}</button>
            </form>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4" /> {t("API keys", "API 密钥")}</CardTitle>
            <CardDescription>{t("For agents, scripts and MCP clients. A key never exceeds your role and can be narrowed to some services, read-only, an expiry date and a rate limit. The token is shown once.", "供 agent、脚本和 MCP 客户端使用。密钥权限不超过你的角色，并可限定服务范围、只读、到期日和速率。令牌只显示一次。")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {fresh && <FreshToken fresh={fresh} onDismiss={() => setFresh(null)} />}
            <KeyTable keys={keys.data?.keys ?? []} roleOf={() => me.role} onChanged={refresh} />
            <details className="rounded-lg border p-4 open:pb-5">
              <summary className="cursor-pointer text-sm font-medium">{t("Create a key", "创建密钥")}</summary>
              <div className="mt-4">
                <CreateKey ownerRole={me.role} onCreated={(r) => { setFresh(r); refresh(); }} />
              </div>
            </details>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>{t("Connect an agent over MCP", "通过 MCP 接入 agent")}</CardTitle>
            <CardDescription>
              {t("Add the header", "添加请求头")} <span className="font-mono">X-QFZ-Session: sess_…</span>{" "}
              {t("to lock every data tool to a simulation session's clock.", "，即可将所有数据工具锁定到某个模拟会话的时钟。")}
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
