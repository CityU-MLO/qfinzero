# QFZView

> 中文: [docs/cn/qfzview.md](../cn/qfzview.md)

QFZView (console bar, `/view`) is a market viewer over whatever the store
holds, in the style of TradingView. What it offers for a symbol follows the
data: intervals, the bid/ask overlay and the ranges shown are those the store
has for that kind of asset.

## Symbols

| Write | Kind | Times |
|---|---|---|
| `SPY`, `AAPL` | stock | US/Eastern |
| `/CL`, `/ZNZ6` | future (root or contract) | US/Eastern |
| `X:BTC-USD` | crypto pair | UTC |
| `C:EUR-USD` | FX pair | UTC |
| `O:SPY260821C00766000` | option contract | US/Eastern |

The search box suggests the most traded symbols (by dollar volume) and the
popular crypto and FX pairs. The watchlist on the right is kept in the browser.

## Using the chart

- Intervals: 1, 5, 15 and 30 minutes, 1 and 4 hours (built from minute bars,
  aligned to the wall clock of the market's zone), and daily bars.
- Scroll to zoom, drag to pan; the legend shows the bar under the cursor.
  Reaching the first loaded bar loads the page before it, so history goes back
  as far as the store does.
- **Go to date** opens the chart at a day (09:30 ET for US markets, 00:00 UTC
  for crypto and FX); scrolling right from there loads the following pages,
  and **Latest** returns to the newest data. The date is in the URL (`&d=`).
- The moon button switches the view to a dark background (kept in the
  browser); the expand button fills the window, and the browser's full screen
  where it allows it (Esc leaves).
- Indicators: MA20, MA50, EMA9, EMA21, Bollinger bands (20, 2), VWAP (restarts
  each trading day).
- **Sessions** (US stocks, intraday intervals): the chart shades the overnight
  session (20:00–04:00 ET, Blue Ocean) darkest, pre-market (04:00–09:30)
  lighter and after-hours (16:00–20:00) lightest; the regular session
  (09:30–16:00) is not shaded. Wide bands carry their name and the legend shows
  the session of the bar under the cursor. A bar of an hour or more takes the
  busiest session it touches (the 09:00 hour holds the open, so it is regular).
  *All* shows every session, *Extended* drops the overnight session, *Regular*
  keeps 09:30–16:00 only; the choice is kept in the browser. The broker's chart
  shades the sessions too.
- **Option chain** (stocks and option contracts): opens the underlying's chain
  beside the chart for one expiry at a chosen ET minute, on the days the store
  has the underlying's option minutes: calls | strike | puts with bid/ask,
  last trade, volume so far, IV and delta, the at-the-money strike marked.
  Clicking a contract charts it; an option contract's chart shows its expiry,
  strike and right, links back to the underlying and starts at its expiry.
- **Bid/Ask** draws the last quote of each bar (up to 15-minute bars) for
  stocks, futures, FX and option contracts when the store has quotes.
- The panel under the watchlist lists the date range of each data level of the
  symbol's kind in the store.

The URL holds the symbol and interval (`/view?s=X:BTC-USD&i=1440`), so a view
can be shared.

## Data

QFZView reads UPQ through the console (`/api/upq/...`): `/stock`, `/future`,
`/crypto`, `/fx`, `/option/ticker_query` and their daily and quote endpoints,
100,000 rows a page. The broker's chart uses the same component; there history
is time-locked to the session start.
