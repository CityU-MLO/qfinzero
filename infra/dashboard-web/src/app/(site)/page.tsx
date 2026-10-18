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

const REPO = process.env.NEXT_PUBLIC_REPO_URL ?? "https://github.com/CityU-MLO/qfinzero";

const PLATFORM = [
  {
    icon: CandlestickChart,
    name: "Market data",
    tag: "UPQ",
    body: "Minute and daily bars for US stocks and OPRA options, minute NBBO quotes, intraday option-chain snapshots with Greeks priced off the mid, rates and corporate actions.",
  },
  {
    icon: Newspaper,
    name: "News and events",
    tag: "ESP",
    body: "News, earnings calendars and macro releases in one event schema, replayable at any past moment so results appear only after they were published.",
  },
  {
    icon: Wallet,
    name: "Paper broker",
    tag: "PMB",
    body: "Step-driven sessions with market, limit and stop orders, trading hours, DAY and GTD expiry, partial fills, options that fill against the book, and checkpoints to branch experiments.",
  },
  {
    icon: Bot,
    name: "Agent interface",
    tag: "MCP",
    body: "54 tools over the Model Context Protocol, plus REST under one port. step_until lets an agent sleep until a fill, a price or the next open instead of polling every minute.",
  },
  {
    icon: FlaskConical,
    name: "Intraday research",
    tag: "Research",
    body: "A small, safe factor language compiled to columnar SQL: IC, rank IC, quantile spreads, turnover and cost-aware backtests on hundreds of names in seconds.",
  },
  {
    icon: Database,
    name: "Data pipeline",
    tag: "qfz-data",
    body: "Adapters for massive, Tushare and Databento (DBN or parquet, any layout) convert vendor files into one storage format. New vendors need an adapter, not engine changes.",
  },
];

const SESSIONS = [
  { name: "Overnight", hours: "20:00–04:00 ET", note: "Blue Ocean · limit only" },
  { name: "Pre-market", hours: "04:00–09:30 ET", note: "extended hours · limit only" },
  { name: "Regular", hours: "09:30–16:00 ET", note: "stocks and options" },
  { name: "After-hours", hours: "16:00–20:00 ET", note: "extended hours · limit only" },
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

export default function LandingPage() {
  return (
    <main>
      {/* hero */}
      <section className="mx-auto max-w-6xl px-4 pb-16 pt-14 md:px-6 md:pt-20">
        <div className="grid items-start gap-10 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <p className="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
              <Lock className="h-4 w-4" /> Point-in-time by construction
            </p>
            <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight md:text-5xl">
              A trading environment where agents cannot see the future
            </h1>
            <p className="mt-5 max-w-xl text-lg leading-relaxed text-muted-foreground">
              QFinZero puts market data, news and a paper broker behind one API. Bind an agent to a
              simulation session and every tool it calls answers as of that bar, enforced by the
              server rather than by the prompt.
            </p>
            <div className="mt-7 flex flex-wrap gap-2">
              <Link href="/chat" className={buttonVariants({ size: "lg" })}>
                Open the console <ArrowRight />
              </Link>
              <a href="#quickstart" className={buttonVariants({ size: "lg", variant: "outline" })}>
                Run it yourself
              </a>
            </div>
            <dl className="mt-10 grid max-w-lg grid-cols-3 gap-6 border-t pt-6 text-sm">
              {[
                ["54", "MCP tools"],
                ["4", "US sessions, incl. overnight"],
                ["1", "port for UI, REST and MCP"],
              ].map(([n, label]) => (
                <div key={label}>
                  <dt className="text-2xl font-semibold tabular-nums text-foreground">{n}</dt>
                  <dd className="mt-0.5 text-muted-foreground">{label}</dd>
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
              {[
                ["upq_chain_snapshot(\"ANET\")", "1,596 contracts · bid/ask/mid · IV"],
                ["esp_search_news(\"ANET\")", "only stories published before 09:35"],
                ["pmb_buy_option(… MARKET)", "filled at the ask 0.44"],
                ["upq_stock_minute(… end=16:00)", "returns bars through 09:34"],
              ].map(([call, out]) => (
                <div key={call} className="px-4 py-2.5">
                  <p className="font-mono text-[12.5px] text-foreground">{call}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">→ {out}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* platform */}
      <section id="platform" className="scroll-mt-20 border-y bg-card py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title="Everything an agent needs to trade, in one place">
            Six parts that share one clock, one storage format and one set of credentials.
          </SectionTitle>
          <div className="mt-8 grid gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-2 lg:grid-cols-3">
            {PLATFORM.map(({ icon: Icon, name, tag, body }) => (
              <div key={name} className="bg-card p-5">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" />
                  <h3 className="font-semibold">{name}</h3>
                  <span className="ml-auto font-mono text-[11px] text-muted-foreground">{tag}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* time lock */}
      <section id="time-lock" className="scroll-mt-20 py-16">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 md:px-6 lg:grid-cols-2">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Look-ahead is closed at the server</h2>
            <ul className="mt-6 space-y-4 text-muted-foreground">
              {[
                [Clock, "A minute bar is visible only after it closes; a daily bar after 16:00 ET; the end-of-day option chain after 16:15 ET."],
                [Lock, "Connect with X-QFZ-Session and every data tool is capped at that session's current bar. The agent cannot widen it."],
                [Moon, "Sessions follow US trading dates: overnight trading from 20:00 ET belongs to the next day, as brokers book it."],
              ].map(([Icon, text], i) => {
                const I = Icon as typeof Clock;
                return (
                  <li key={i} className="flex gap-3">
                    <I className="mt-0.5 h-5 w-5 flex-none text-primary" />
                    <span className="leading-relaxed">{text as string}</span>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="rounded-lg border bg-card">
            <p className="border-b px-4 py-2.5 text-sm font-semibold">One trading day, four segments</p>
            <div className="divide-y">
              {SESSIONS.map((s) => (
                <div key={s.name} className="flex items-center justify-between px-4 py-2.5">
                  <div>
                    <p className="font-medium">{s.name}</p>
                    <p className="text-xs text-muted-foreground">{s.note}</p>
                  </div>
                  <span className="font-mono text-sm tabular-nums">{s.hours}</span>
                </div>
              ))}
            </div>
            <p className="border-t px-4 py-3 text-xs leading-relaxed text-muted-foreground">
              Orders carry REGULAR, EXTENDED or OVERNIGHT trading hours. Options trade in the regular
              session only and fill against the NBBO when quotes are loaded.
            </p>
          </div>
        </div>
      </section>

      {/* research */}
      <section id="research" className="scroll-mt-20 border-y bg-card py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title="Mine intraday factors without writing a backtester">
            Factors are one expression. Windows only look backwards and reset each day; trades enter
            at the next bar&apos;s open; costs include the quoted half-spread.
          </SectionTitle>
          <div className="mt-8 max-w-4xl space-y-4">
            <Code label="shell">{FACTOR_SNIPPET}</Code>
            <div className="grid gap-3 sm:grid-cols-4">
              {[
                ["IC · rank IC", "per horizon, with t-stats"],
                ["Quantiles", "forward return by bucket"],
                ["Turnover", "of the top quantile"],
                ["Backtest", "Sharpe, drawdown, costs"],
              ].map(([a, b]) => (
                <div key={a} className="rounded-md border px-3 py-2.5">
                  <p className="font-semibold">{a}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* quick start */}
      <section id="quickstart" className="scroll-mt-20 py-16">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle title="Run it">
            Start with the bundled synthetic dataset, then point the pipeline at your vendor files.
            Give each agent an API key from your account page.
          </SectionTitle>
          <div className="mt-8 grid gap-4 lg:grid-cols-2">
            <Code label="shell">{SHELL_SNIPPET}</Code>
            <Code label="mcp.json">{MCP_SNIPPET}</Code>
          </div>
          <div className="mt-8 flex flex-wrap gap-2">
            <Link href="/login" className={buttonVariants()}>
              Sign in <ArrowRight />
            </Link>
            <a href={REPO} target="_blank" rel="noopener noreferrer" className={buttonVariants({ variant: "outline" })}>
              Read the source
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
