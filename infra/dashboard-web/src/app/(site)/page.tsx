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

const SHELL_SNIPPET = `pip install -e ".[pipeline,server,databento]"
qfz-data convert --all            # vendor files -> UPQ storage
qfz-auth create-user you --role admin
qfz-server                        # UI, REST and MCP on :19777`;

const FACTOR_SNIPPET = `qfz-research eval "cs_rank(-pct(close, 15)) * cs_rank(ts_mean(volume, 30))" \\
  --start 2026-08-10 --end 2026-08-21 --universe 500 --horizons 5,15,30`;

function Code({ children, label }: { children: string; label?: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800/80 bg-slate-950 shadow-lg">
      {label && (
        <div className="flex items-center gap-1.5 border-b border-slate-800 px-4 py-2 text-xs text-slate-400">
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="h-2.5 w-2.5 rounded-full bg-slate-700" />
          <span className="ml-2 font-mono">{label}</span>
        </div>
      )}
      <pre className="overflow-x-auto p-4 font-mono text-[13px] leading-relaxed text-slate-100">
        <code>{children}</code>
      </pre>
    </div>
  );
}

function SectionTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">{eyebrow}</p>
      <h2 className="mt-2 text-3xl font-bold tracking-tight md:text-4xl">{title}</h2>
      {children && <p className="mt-4 text-base leading-relaxed text-muted-foreground">{children}</p>}
    </div>
  );
}

export default function LandingPage() {
  return (
    <main>
      {/* hero */}
      <section className="mx-auto max-w-6xl px-4 pb-20 pt-16 md:px-6 md:pt-24">
        <div className="grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
          <div>
            <p className="inline-flex items-center gap-2 rounded-full border bg-white/70 px-3 py-1 text-xs font-semibold text-muted-foreground shadow-sm">
              <Lock className="h-3.5 w-3.5 text-primary" /> Point-in-time by construction
            </p>
            <h1 className="mt-6 text-4xl font-bold leading-[1.1] tracking-tight md:text-6xl">
              A trading environment where agents
              <span className="bg-gradient-to-r from-cyan-600 to-emerald-500 bg-clip-text text-transparent"> cannot see the future</span>.
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground">
              QFinZero puts market data, news and a paper broker behind one API. Bind an agent to a
              simulation session and every tool it calls answers as of that bar, enforced by the
              server rather than by the prompt.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/chat" className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground shadow hover:bg-primary/90">
                Open the console <ArrowRight className="h-4 w-4" />
              </Link>
              <a href="#quickstart" className="inline-flex h-11 items-center rounded-lg border bg-white px-6 text-sm font-semibold shadow-sm hover:bg-accent">
                Run it yourself
              </a>
            </div>
            <dl className="mt-10 grid max-w-lg grid-cols-3 gap-6 text-sm">
              {[
                ["54", "MCP tools"],
                ["4", "US sessions, incl. overnight"],
                ["1", "port for UI, REST and MCP"],
              ].map(([n, label]) => (
                <div key={label}>
                  <dt className="text-3xl font-bold text-foreground">{n}</dt>
                  <dd className="mt-1 text-muted-foreground">{label}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="relative">
            <div className="absolute -inset-4 -z-10 rounded-3xl bg-gradient-to-br from-cyan-200/50 via-white to-amber-100/60 blur-2xl" />
            <div className="rounded-2xl border bg-white/90 p-5 shadow-xl">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span className="font-mono">sess_3f2a9c1e · 1m</span>
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-semibold text-emerald-700">REGULAR</span>
              </div>
              <p className="mt-3 font-mono text-sm">2026-02-19 09:35 ET</p>
              <div className="mt-4 space-y-2 text-sm">
                {[
                  ["upq_chain_snapshot(\"ANET\")", "1,596 contracts · bid/ask/mid · IV"],
                  ["esp_search_news(\"ANET\")", "only stories published before 09:35"],
                  ["pmb_buy_option(… MARKET)", "filled at the ask 0.44"],
                  ["upq_stock_minute(… end=16:00)", "returns bars through 09:34"],
                ].map(([call, out]) => (
                  <div key={call} className="rounded-lg border bg-secondary/40 px-3 py-2">
                    <p className="font-mono text-[12.5px] text-foreground">{call}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">→ {out}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* platform */}
      <section id="platform" className="scroll-mt-20 border-y bg-white/60 py-20">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle eyebrow="Platform" title="Everything an agent needs to trade, in one place">
            Six parts that share one clock, one storage format and one set of credentials.
          </SectionTitle>
          <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {PLATFORM.map(({ icon: Icon, name, tag, body }) => (
              <div key={name} className="rounded-2xl border bg-card p-6 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
                <div className="flex items-center justify-between">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-secondary text-primary">
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="rounded-full border px-2.5 py-0.5 font-mono text-[11px] text-muted-foreground">{tag}</span>
                </div>
                <h3 className="mt-4 text-lg font-semibold">{name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* time lock */}
      <section id="time-lock" className="scroll-mt-20 py-20">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 md:px-6 lg:grid-cols-2">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-primary">Time lock</p>
            <h2 className="mt-2 text-3xl font-bold tracking-tight md:text-4xl">Look-ahead is closed at the server</h2>
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
          <div className="rounded-2xl border bg-white/80 p-6 shadow-sm">
            <p className="text-sm font-semibold">One trading day, four segments</p>
            <div className="mt-5 space-y-3">
              {SESSIONS.map((s) => (
                <div key={s.name} className="flex items-center justify-between rounded-xl border bg-card px-4 py-3">
                  <div>
                    <p className="font-medium">{s.name}</p>
                    <p className="text-xs text-muted-foreground">{s.note}</p>
                  </div>
                  <span className="font-mono text-sm">{s.hours}</span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Orders carry REGULAR, EXTENDED or OVERNIGHT trading hours. Options trade in the regular
              session only and fill against the NBBO when quotes are loaded.
            </p>
          </div>
        </div>
      </section>

      {/* research */}
      <section id="research" className="scroll-mt-20 border-y bg-white/60 py-20">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle eyebrow="Research" title="Mine intraday factors without writing a backtester">
            Factors are one expression. Windows only look backwards and reset each day; trades enter
            at the next bar&apos;s open; costs include the quoted half-spread.
          </SectionTitle>
          <div className="mx-auto mt-10 max-w-4xl space-y-5">
            <Code label="shell">{FACTOR_SNIPPET}</Code>
            <div className="grid gap-4 sm:grid-cols-4">
              {[
                ["IC · rank IC", "per horizon, with t-stats"],
                ["Quantiles", "forward return by bucket"],
                ["Turnover", "of the top quantile"],
                ["Backtest", "Sharpe, drawdown, costs"],
              ].map(([a, b]) => (
                <div key={a} className="rounded-xl border bg-card p-4 text-center shadow-sm">
                  <p className="font-semibold">{a}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* quick start */}
      <section id="quickstart" className="scroll-mt-20 py-20">
        <div className="mx-auto max-w-6xl px-4 md:px-6">
          <SectionTitle eyebrow="Quick start" title="Run it on your own data">
            Point the pipeline at your vendor files, create an admin, start the hub. Give each agent
            an API key from your account page.
          </SectionTitle>
          <div className="mt-10 grid gap-5 lg:grid-cols-2">
            <Code label="shell">{SHELL_SNIPPET}</Code>
            <Code label="mcp.json">{MCP_SNIPPET}</Code>
          </div>
          <div className="mt-10 flex flex-wrap justify-center gap-3">
            <Link href="/login" className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground shadow hover:bg-primary/90">
              Sign in <ArrowRight className="h-4 w-4" />
            </Link>
            <a href={REPO} target="_blank" rel="noopener noreferrer" className="inline-flex h-11 items-center rounded-lg border bg-white px-6 text-sm font-semibold shadow-sm hover:bg-accent">
              Read the source
            </a>
          </div>
        </div>
      </section>
    </main>
  );
}
