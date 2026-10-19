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
- Indicators: MA20, MA50, EMA9, EMA21, Bollinger bands (20, 2), VWAP (restarts
  each trading day).
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
