from qfinzero.clients.upq import UPQClient
import json

qqq_top_10_tickers = ["NVDA", "AAPL", "MSFT", "AMZN", "TSLA", "META", "GOOGL", "WMT", "GOOG", "AVGO"]

def get_stock_prices(upq, tickers):
    ticker_stock_price = {ticker: {} for ticker in tickers}
    print(f"{'Ticker':>6} | {'Date':^10} | {'Close':>8}")
    print("-" * 40)
    for ticker in tickers:
        bars = upq.stock_daily(
            tickers=[ticker],  
            start='2025-01-01',
            end='2025-12-31',
        )
        if bars:
            for bar in bars:
                ticker_stock_price[ticker][bar['date']] = bar['close']
            print(f"{ticker:>6} | {bars[0]['date']:^10} | ${bars[0]['close']:7.2f}")
        else:
            print(f"{ticker:>6} | No data found")
                
    return ticker_stock_price

def main():
    with UPQClient() as upq:
        ticker_stock_price = get_stock_prices(
            upq=upq,
            tickers=qqq_top_10_tickers,
        )
    
    with open('stock_prices.json', 'w') as f:
        json.dump(ticker_stock_price, f, indent=2)
    
 
    
    
if __name__ == '__main__':
    main()