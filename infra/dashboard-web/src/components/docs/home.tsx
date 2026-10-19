"use client";

// Landing page of the documentation hub.

import * as React from "react";
import Link from "next/link";
import { ArrowRight, Bot, CalendarClock, CandlestickChart, Database, FlaskConical, KeyRound, Landmark, Rocket, Search, Trophy } from "lucide-react";

import { useT } from "@/components/locale-provider";
import { CodePanel } from "@/components/docs/reference";
import { useDocsSearch } from "@/components/docs/shell";
import type { ApiReference } from "@/lib/docs";

type Card = { icon: React.ComponentType<{ className?: string }>; title: [string, string]; text: [string, string];
  guide: string; api?: string; tint: string };

const PRODUCTS: Card[] = [
  { icon: CandlestickChart, title: ["Market data", "行情数据"], text: ["Stock, option and futures bars, minute quotes, option chains, rates and dividends, point in time.", "股票、期权、期货的 K 线与分钟报价、期权链、利率与分红，按时点可见。"],
    guide: "/docs/agent-market-data", api: "/docs/api/upq", tint: "text-blue-600 bg-blue-500/10" },
  { icon: CalendarClock, title: ["Events and news", "事件与新闻"], text: ["News, earnings and macro calendars as they were known at any moment.", "新闻、财报与宏观日历，按任一时刻已知的内容返回。"],
    guide: "/docs/esp", api: "/docs/api/esp", tint: "text-violet-600 bg-violet-500/10" },
  { icon: Landmark, title: ["Paper broker", "模拟券商"], text: ["Accounts, orders and sessions with a simulated clock, NBBO fills, futures margin.", "账户、订单和带模拟时钟的会话，按 NBBO 成交，支持期货保证金。"],
    guide: "/docs/agent-trading", api: "/docs/api/pmb", tint: "text-emerald-600 bg-emerald-500/10" },
  { icon: FlaskConical, title: ["Research", "研究"], text: ["A factor language, IC and rank IC evaluation, cost-aware intraday backtests.", "因子语言、IC 与 rank IC 评估、计入成本的日内回测。"],
    guide: "/docs/platform-guide#5-intraday-research", tint: "text-amber-600 bg-amber-500/10" },
  { icon: Database, title: ["Data setup", "数据导入"], text: ["Bring in Databento and massive data: layouts, vendor keys, downloads with cost, compression.", "导入 Databento 和 massive 数据：目录结构、供应商密钥、计费下载与压缩。"],
    guide: "/docs/data-setup", tint: "text-sky-600 bg-sky-500/10" },
  { icon: Trophy, title: ["Agent benchmark", "Agent 基准"], text: ["104 tasks on a redistributable sample dataset, with an oracle and a runner.", "基于可再分发样本数据的 104 个任务，附 oracle 与运行器。"],
    guide: "/docs/benchmark", tint: "text-rose-600 bg-rose-500/10" },
];

const STEPS: { icon: React.ComponentType<{ className?: string }>; title: [string, string]; text: [string, string]; href: string }[] = [
  { icon: Rocket, title: ["Run it", "运行"], text: ["Docker or from source, in about ten minutes.", "Docker 或源码，大约十分钟。"], href: "/docs/getting-started" },
  { icon: KeyRound, title: ["Get an API key", "获取 API key"], text: ["Scoped, expiring keys for scripts and agents.", "带 scope 和到期日的 key，给脚本和 agent 用。"], href: "/docs/api#authentication" },
  { icon: Bot, title: ["Connect an agent", "接入 agent"], text: ["Point any MCP client at /mcp.", "把任意 MCP 客户端指向 /mcp。"], href: "/docs/mcp" },
];

export function DocsHome({ ref_ }: { ref_?: ApiReference }) {
  const t = useT();
  const onSearch = useDocsSearch();
  const L = (x: [string, string]) => t(x[0], x[1]);
  const [origin, setOrigin] = React.useState("https://your-host");
  React.useEffect(() => setOrigin(window.location.origin), []);
  const n = (ref_?.services ?? []).reduce((a, s) => a + s.endpoints.length, 0);
  return (
    <div className="pb-10">
      <section className="grid items-center gap-10 border-b pb-12 lg:grid-cols-[1fr_28rem]">
        <div>
          <p className="text-[13px] font-semibold uppercase tracking-wider text-primary">{t("Documentation", "文档")}</p>
          <h1 className="mt-3 text-[2.4rem] font-semibold leading-tight tracking-tight">{t("Build and evaluate market agents on QFinZero", "在 QFinZero 上构建与评估交易 agent")}</h1>
          <p className="mt-4 max-w-xl text-[16.5px] leading-relaxed text-muted-foreground">
            {t("Point-in-time market data, events and a paper broker behind one hub, for people, scripts and agents.",
              "按时点可见的行情、事件和模拟券商，统一由一个 hub 提供给人、脚本和 agent。")}
          </p>
          <button onClick={onSearch} className="mt-7 flex h-11 w-full max-w-md items-center gap-3 rounded-xl border bg-background px-4 text-left text-[14px] text-muted-foreground shadow-sm hover:border-ring/50">
            <Search className="h-4 w-4" /><span className="flex-1">{t("Search guides, endpoints, tools…", "搜索指南、接口、工具…")}</span><kbd className="kbd">⌘K</kbd>
          </button>
          <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-[13.5px]">
            <Link href="/docs/getting-started" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">{t("Quickstart", "快速开始")} <ArrowRight className="h-3.5 w-3.5" /></Link>
            <Link href="/docs/api" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">{t(`API reference · ${n} endpoints`, `API 参考 · ${n} 个接口`)} <ArrowRight className="h-3.5 w-3.5" /></Link>
            <Link href="/docs/mcp" className="inline-flex items-center gap-1 font-medium text-primary hover:underline">{t(`MCP · ${ref_?.mcp.length ?? 0} tools`, `MCP · ${ref_?.mcp.length ?? 0} 个工具`)} <ArrowRight className="h-3.5 w-3.5" /></Link>
          </div>
        </div>
        <CodePanel tabs={[
          { id: "curl", label: "cURL", code: `curl "${origin}/svc/upq/stock/daily?tickers=SPY&start=2025-01-02&end=2025-01-10" \\\n  -H "Authorization: Bearer $QFZ_API_KEY"` },
          { id: "python", label: "Python", code: `import os, requests\n\nr = requests.get(\n    "${origin}/svc/upq/stock/daily",\n    params={"tickers": "SPY", "start": "2025-01-02", "end": "2025-01-10"},\n    headers={"Authorization": f"Bearer {os.environ['QFZ_API_KEY']}"},\n)\nfor bar in r.json():\n    print(bar["date"], bar["close"])` },
          { id: "mcp", label: "MCP", code: JSON.stringify({ mcpServers: { qfinzero: { type: "http", url: `${origin}/mcp/`, headers: { Authorization: "Bearer qfz_…" } } } }, null, 2) },
        ]} />
      </section>

      <section className="py-10">
        <h2 className="text-[18px] font-semibold tracking-tight">{t("Start here", "从这里开始")}</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <Link key={s.href} href={s.href} className="group flex gap-4 rounded-xl border p-4 transition-colors hover:border-primary/40 hover:bg-primary/[0.02]">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[13px] font-semibold text-primary">{i + 1}</span>
              <span>
                <span className="flex items-center gap-1.5 font-semibold"><s.icon className="h-4 w-4 text-muted-foreground" />{L(s.title)}</span>
                <span className="mt-1 block text-[13px] text-muted-foreground">{L(s.text)}</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="border-t pt-10">
        <h2 className="text-[18px] font-semibold tracking-tight">{t("Products", "产品")}</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {PRODUCTS.map((p) => (
            <div key={p.guide} className="flex flex-col rounded-xl border p-5">
              <span className={`flex h-9 w-9 items-center justify-center rounded-lg ${p.tint}`}><p.icon className="h-[18px] w-[18px]" /></span>
              <h3 className="mt-4 font-semibold">{L(p.title)}</h3>
              <p className="mt-1.5 flex-1 text-[13.5px] leading-relaxed text-muted-foreground">{L(p.text)}</p>
              <div className="mt-4 flex gap-4 text-[13px] font-medium">
                <Link href={p.guide} className="text-primary hover:underline">{t("Guide", "指南")}</Link>
                {p.api && <Link href={p.api} className="text-primary hover:underline">{t("API reference", "API 参考")}</Link>}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
