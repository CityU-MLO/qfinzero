import Link from "next/link";
import {
  ArrowRight,
  Bot,
  CandlestickChart,
  Clock,
  Database,
  FlaskConical,
  Lock,
  Moon,
  Newspaper,
  Wallet,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { getT } from "@/lib/i18n-server";

const REPO = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/CityU-MLO/qfinzero";

type Pair = readonly [string, string];

const PLATFORM: { icon: typeof Bot; name: Pair; tag: string; body: Pair }[] = [
  {
    icon: CandlestickChart,
    name: ["Market data", "行情数据"],
    tag: "UPQ",
    body: [
      "Minute and daily bars for US stocks and OPRA options, minute NBBO quotes, intraday option-chain snapshots with Greeks priced off the mid, rates and corporate actions.",
      "美股与 OPRA 期权的分钟线和日线、分钟级 NBBO 报价、按中间价计算 Greeks 的日内期权链快照、利率和公司行动。",
    ],
  },
  {
    icon: Newspaper,
    name: ["News and events", "新闻与事件"],
    tag: "ESP",
    body: [
      "News, earnings calendars and macro releases in one event schema, replayable at any past moment so results appear only after they were published.",
      "新闻、财报日历和宏观数据使用同一套事件格式，可回放到任意历史时刻：结果只在发布之后才可见。",
    ],
  },
  {
    icon: Wallet,
    name: ["Paper broker", "模拟券商"],
    tag: "PMB",
    body: [
      "Step-driven sessions with market, limit and stop orders, trading hours, DAY and GTD expiry, partial fills, options that fill against the book, and checkpoints to branch experiments.",
      "按步推进的会话：市价、限价和止损单，交易时段，DAY 与 GTD 有效期，部分成交，按盘口成交的期权，以及可分叉实验的检查点。",
    ],
  },
  {
    icon: Bot,
    name: ["Agent interface", "Agent 接口"],
    tag: "MCP",
    body: [
      "54 tools over the Model Context Protocol, plus REST under one port. step_until lets an agent sleep until a fill, a price or the next open instead of polling every minute.",
      "通过 Model Context Protocol 提供 54 个工具，REST 与之共用一个端口。step_until 让 agent 等到成交、价格触发或下一次开盘，不必逐分钟轮询。",
    ],
  },
  {
    icon: FlaskConical,
    name: ["Intraday research", "日内研究"],
    tag: "Research",
    body: [
      "A small, safe factor language compiled to columnar SQL: IC, rank IC, quantile spreads, turnover and cost-aware backtests on hundreds of names in seconds.",
      "小而安全的因子语言，编译为列式 SQL：数秒内在数百只股票上计算 IC、Rank IC、分层收益、换手率和含成本回测。",
    ],
  },
  {
    icon: Database,
    name: ["Data pipeline", "数据管道"],
    tag: "qfz-data",
    body: [
      "Adapters for massive, Tushare and Databento (DBN or parquet, any layout) convert vendor files into one storage format. New vendors need an adapter, not engine changes.",
      "massive、Tushare 和 Databento（DBN 或 parquet，任意目录结构）的适配器把供应商文件转换成统一的存储格式。新增供应商只需写适配器，无需改引擎。",
    ],
  },
];

const SESSIONS: { name: Pair; hours: string; note: Pair }[] = [
  { name: ["Overnight", "夜盘"], hours: "20:00–04:00 ET", note: ["Blue Ocean · limit only", "Blue Ocean · 仅限价单"] },
  { name: ["Pre-market", "盘前"], hours: "04:00–09:30 ET", note: ["extended hours · limit only", "延长时段 · 仅限价单"] },
  { name: ["Regular", "常规"], hours: "09:30–16:00 ET", note: ["stocks and options", "股票与期权"] },
  { name: ["After-hours", "盘后"], hours: "16:00–20:00 ET", note: ["extended hours · limit only", "延长时段 · 仅限价单"] },
];

const MCP_SNIPPET = `{
  "mcpServers": {
    "qfinzero": {
      "url": "https://your-host/mcp/",
      "headers": {
        "Authorization": "Bearer qfz_…",
        "X-QFZ-Session": "sess_3f2a9c1e"
      }
    }
  }
}`;

const SHELL_SNIPPET = `docker compose up -d                # hub, services and a sample dataset
# or from source:
pip install -e ".[server,pipeline]"
qfz-sample generate --out ./qfz-sample
QFZ_DATA_ROOT=./qfz-sample qfz-server   # UI, REST and MCP on :19777`;

const FACTOR_SNIPPET = `qfz-research eval "cs_rank(-pct(close, 15)) * cs_rank(ts_mean(volume, 30))" \\
  --start 2026-08-10 --end 2026-08-21 --universe 500 --horizons 5,15,30`;

function Code({ children, label }: { children: string; label?: string }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      {label && <div className="border-b bg-muted/60 px-3 py-1.5 font-mono text-xs text-muted-foreground">{label}</div>}
      <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed">
        <code>{children}</code>
      </pre>
    </div>
  );
}

function SectionTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="max-w-2xl">
      <h2 className="text-2xl font-semibold tracking-tight">{title}</h2>
      {children && <p className="mt-2 leading-relaxed text-muted-foreground">{children}</p>}
    </div>
  );
}

export default async function LandingPage() {
  const t = await getT();
  const p = (x: Pair) => t(x[0], x[1]);
  return (
    <main>
      {/* hero */}
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 md:px-6 md:pt-20">
        <div className="grid items-start gap-10 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <p className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
              <Lock className="h-4 w-4" /> {t("Point-in-time by construction", "从设计上保证时间点一致")}
            </p>
            <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight md:text-5xl">
              {t("A trading environment where agents cannot see the future", "让 agent 看不到未来的交易环境")}
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
              {t(
                "QFinZero puts market data, news and a paper broker behind one API. Bind an agent to a simulation session and every tool it calls answers as of that bar, enforced by the server rather than by the prompt.",
                "QFinZero 把行情、新闻和模拟券商放在同一套 API 之后。把 agent 绑定到一个模拟会话，它调用的每个工具都只返回当前这根 bar 时已知的信息，由服务器而不是提示词来保证。",
              )}
            </p>
            <div className="mt-7 flex flex-wrap gap-2">
              <Link href="/chat" className={buttonVariants({ size: "lg" })}>
                {t("Open the console", "进入控制台")} <ArrowRight />
              </Link>
              <Link href="/docs/getting-started" className={buttonVariants({ size: "lg", variant: "outline" })}>
                {t("Get started", "开始使用")}
              </Link>
            </div>
            <dl className="mt-10 grid max-w-lg grid-cols-3 gap-6 border-t pt-6 text-sm">
              {([
                ["54", ["MCP tools", "个 MCP 工具"]],
                ["4", ["US sessions, incl. overnight", "个美股交易时段（含夜盘）"]],
                ["1", ["port for UI, REST and MCP", "个端口提供界面、REST 和 MCP"]],
              ] as const).map(([n, label]) => (
                <div key={n}>
                  <dt className="text-2xl font-semibold tabular-nums text-foreground">{n}</dt>
                  <dd className="mt-0.5 text-muted-foreground">{p(label)}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="rounded-lg border bg-card">
            <div className="flex items-center justify-between border-b px-4 py-2.5 text-xs text-muted-foreground">
              <span className="font-mono">sess_3f2a9c1e · 1m · 2026-02-19 09:35 ET</span>
              <Badge variant="success">REGULAR</Badge>
            </div>
            <div className="divide-y text-sm">
              {([
                ["upq_chain_snapshot(\"ANET\")", ["1,596 contracts · bid/ask/mid · IV", "1,596 个合约 · 买/卖/中间价 · IV"]],
                ["esp_search_news(\"ANET\")", ["only stories published before 09:35", "只返回 09:35 之前发布的新闻"]],
                ["pmb_buy_option(… MARKET)", ["filled at the ask 0.44", "按卖价 0.44 成交"]],
                ["upq_stock_minute(… end=16:00)", ["returns bars through 09:34", "只返回到 09:34 的 bar"]],
              ] as const).map(([call, out]) => (
                <div key={call} className="px-4 py-2.5">
                  <p className="font-mono text-[12.5px] text-foreground">{call}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">→ {p(out)}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* platform */}
      <section id="platform" className="scroll-mt-20 border-y bg-card py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title={t("Everything an agent needs to trade, in one place", "agent 交易所需的一切，集中在一处")}>
            {t(
              "Six parts that share one clock, one storage format and one set of credentials.",
              "六个部分共用同一个时钟、同一种存储格式和同一套凭证。",
            )}
          </SectionTitle>
          <div className="mt-8 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-3">
            {PLATFORM.map(({ icon: Icon, name, tag, body }) => (
              <div key={tag} className="bg-card p-5">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" />
                  <h3 className="font-semibold">{p(name)}</h3>
                  <span className="ml-auto font-mono text-[11px] text-muted-foreground">{tag}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{p(body)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* time lock */}
      <section id="time-lock" className="scroll-mt-20 py-16">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 md:px-6 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">
              {t("Look-ahead is closed at the server", "前视偏差在服务器端被杜绝")}
            </h2>
            <ul className="mt-6 space-y-4 text-muted-foreground">
              {([
                [Clock, [
                  "A minute bar is visible only after it closes; a daily bar after 16:00 ET; the end-of-day option chain after 16:15 ET.",
                  "分钟线收盘后才可见；日线在美东 16:00 后可见；收盘期权链在美东 16:15 后可见。",
                ]],
                [Lock, [
                  "Connect with X-QFZ-Session and every data tool is capped at that session's current bar. The agent cannot widen it.",
                  "带上 X-QFZ-Session 连接后，所有数据工具都被限制在该会话的当前 bar，agent 无法放宽。",
                ]],
                [Moon, [
                  "Sessions follow US trading dates: overnight trading from 20:00 ET belongs to the next day, as brokers book it.",
                  "会话按美股交易日划分：美东 20:00 起的夜盘归属下一个交易日，与券商记账方式一致。",
                ]],
              ] as const).map(([Icon, text], i) => (
                <li key={i} className="flex gap-3">
                  <Icon className="mt-0.5 h-5 w-5 flex-none text-primary" />
                  <span className="leading-relaxed">{p(text)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border bg-card">
            <p className="border-b px-4 py-2.5 text-sm font-semibold">
              {t("One trading day, four segments", "一个交易日，四个时段")}
            </p>
            <div className="divide-y">
              {SESSIONS.map((s) => (
                <div key={s.hours} className="flex items-center justify-between px-4 py-2.5">
                  <div>
                    <p className="font-medium">{p(s.name)}</p>
                    <p className="text-xs text-muted-foreground">{p(s.note)}</p>
                  </div>
                  <span className="font-mono text-sm tabular-nums">{s.hours}</span>
                </div>
              ))}
            </div>
            <p className="border-t px-4 py-3 text-xs leading-relaxed text-muted-foreground">
              {t(
                "Orders carry REGULAR, EXTENDED or OVERNIGHT trading hours. Options trade in the regular session only and fill against the NBBO when quotes are loaded.",
                "委托带有 REGULAR、EXTENDED 或 OVERNIGHT 交易时段。期权只在常规时段交易，加载报价后按 NBBO 成交。",
              )}
            </p>
          </div>
        </div>
      </section>

      {/* research */}
      <section id="research" className="scroll-mt-20 border-y bg-card py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title={t("Mine intraday factors without writing a backtester", "不写回测框架也能挖掘日内因子")}>
            {t(
              "Factors are one expression. Windows only look backwards and reset each day; trades enter at the next bar's open; costs include the quoted half-spread.",
              "一个因子就是一个表达式。窗口只向后看并每日重置；交易在下一根 bar 开盘入场；成本包含报价的半个点差。",
            )}
          </SectionTitle>
          <div className="mt-8 max-w-4xl space-y-4">
            <Code label="shell">{FACTOR_SNIPPET}</Code>
            <div className="grid gap-3 sm:grid-cols-4">
              {([
                [["IC · rank IC", "IC · Rank IC"], ["per horizon, with t-stats", "分周期，含 t 值"]],
                [["Quantiles", "分层"], ["forward return by bucket", "各分层的远期收益"]],
                [["Turnover", "换手率"], ["of the top quantile", "最高分层的换手"]],
                [["Backtest", "回测"], ["Sharpe, drawdown, costs", "夏普、回撤、成本"]],
              ] as const).map(([a, b]) => (
                <div key={a[0]} className="rounded-md border px-3 py-2.5">
                  <p className="font-semibold">{p(a)}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{p(b)}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* quick start */}
      <section id="quickstart" className="scroll-mt-20 py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title={t("Run it", "运行")}>
            {t(
              "Start with the bundled synthetic dataset, then point the pipeline at your vendor files. Give each agent an API key from your account page.",
              "先用自带的合成数据集跑起来，再把数据管道指向你自己的供应商文件。在账户页为每个 agent 创建一个 API 密钥。",
            )}
          </SectionTitle>
          <div className="mt-8 grid gap-4 lg:grid-cols-2">
            <Code label="shell">{SHELL_SNIPPET}</Code>
            <Code label="mcp.json">{MCP_SNIPPET}</Code>
          </div>
          <div className="mt-8 flex flex-wrap gap-2">
            <Link href="/docs/getting-started" className={buttonVariants()}>
              {t("Read the guide", "阅读入门指南")} <ArrowRight />
            </Link>
            <a href={REPO} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: "outline" })}>
              {t("Read the source", "查看源代码")}
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
