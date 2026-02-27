from qfinzero.clients.npp import NPPClient
from qfinzero.clients.upq import UPQClient
import pprint
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
qqq_top_10_tickers = ["NVDA", "AAPL", "MSFT", "AMZN", "TSLA", "META", "GOOGL", "WMT", "GOOG", "AVGO"]


ticker_stock_price = {ticker: [] for ticker in qqq_top_10_tickers}

import numpy as np

def get_interpolated_rate(target_T, interest_rate, date):
    """
    Interpolates interest rates for a given T (in years).
    
    Args:
        target_T (float): Time to maturity in years.
        interest_rate (dict): Dictionary with keys like '1_month', '10_year'.
        date (str/datetime): The date to pull the rate for.
        
    Returns:
        float: The interpolated interest rate.
    """
    # 1. Map string tenors to numerical years
    tenor_map = {
        '1_month': 1/12,
        '3_month': 3/12,
        '1_year': 1.0,
        '2_year': 2.0,
        '5_year': 5.0,
        '10_year': 10.0,
        '30_year': 30.0
    }
    
    market_rates = {}
    for key in tenor_map.keys():
        rate_string = interest_rate[key][date]
        market_rates[key] = float(rate_string)
        
    # 2. Create sorted lists of X (years) and Y (rates)
    data = []
    for label, rate in market_rates.items():
        if label in tenor_map:
            data.append((tenor_map[label], rate))
    
    data.sort() 
    years, rates = zip(*data)
    
    # 3. Use numpy to interpolate
    interpolated_rate = np.interp(target_T, years, rates)
    
    return interpolated_rate

def get_option_chain(ticker, current_date):
    upq = UPQClient()
    
    with open('analytics/stock_prices.json', 'r') as file:
        stock_price = json.load(file)
    
    with open('analytics/interest_rate_2025.json', 'r') as file:
        interest_rate = json.load(file)
    
    records = []
    # Using a list for type to capture both Call and Put
    call_chain = upq.option_chain(
        underlying=ticker,
        date=current_date,
        type=["C"], # Requesting both types
        strike_min=50,       
        strike_max=300,      
        expiry_max="2025-12-31", 
    )
    put_chain = upq.option_chain(
        underlying=ticker,
        date=current_date,
        type=["P"], # Requesting both types
        strike_min=50,       
        strike_max=300,      
        expiry_max="2025-12-31", 
    )
    chain = call_chain + put_chain
    if not chain:
        print(f"No contracts found for {ticker} on {current_date}.")
        return

    # Updated header to include Type and T (Years)

    for opt in chain:
        K = opt.get("strike", 0.0)
        expiry = opt.get("expiry", "N/A")
        close = opt.get("close", 0.0)
        S = stock_price[ticker][current_date]
        
        # Pulling the option type (check if your API uses 'type' or 'option_type')
        opt_type = opt.get("type", opt.get("option_type", "N/A"))
        
        # Calculate T (Time to Expiration in Years)
        expiry_dt = pd.to_datetime(expiry)
        current_date_dt = pd.to_datetime(current_date)
        seconds_in_year = 365.25 * 24 * 60 * 60 # Using 365.25 for leap year accuracy
        T = (expiry_dt - current_date_dt).total_seconds() / seconds_in_year
        
        # Get interpolated rate based on T
        
        r = (get_interpolated_rate(T, interest_rate, current_date))/100
        records.append({
            "Ticker": ticker,
            "Type": opt_type,
            "Strike": K,
            "Expiry": expiry,
            "T": T,
            "Price": close,
            "Spot": S,
            "Rate": r
        })
        # Print the adjusted row
        
    print(f"\nTotal: {len(chain)} contracts for {ticker} on {current_date} retrieved.")
    df = pd.DataFrame(records)
    return df

    
def main():
    npp = NPPClient()
    result = npp.earnings_calendar(
        start_date="2025-01-01",
        end_date="2025-12-31",
        tickers=qqq_top_10_tickers, 
        limit=50,
    )

    earnings_map = {}
    for ev in result.get("events", []):
        ticker = ev["tickers"][0] if ev["tickers"] else "UNKNOWN"
        date = ev["time_utc"][:10]
        if ticker not in earnings_map:
            earnings_map[ticker] = []
        earnings_map[ticker].append(date)

    for ticker, dates in earnings_map.items():
        print(f"Ticker: {ticker} | Earnings Dates: {dates}")
    
    with open('earning_date.json', 'w') as f:
        json.dump(earnings_map, f, indent = 2)
    option_data = {}
    for ticker in qqq_top_10_tickers:
        option_data[ticker] = {} 
        for date in earnings_map[ticker]:
            if date < '2025-11-06':
                day_before = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                day_after = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                df_before = get_option_chain(ticker, day_before)
                df_after = get_option_chain(ticker, day_after)
                option_data[ticker][day_before] = df_before.to_dict(orient='records')
                option_data[ticker][day_after] = df_after.to_dict(orient='records')

   
    with open('option_data.json', 'w') as f:
        json.dump(option_data, f, indent=2)

if __name__ == "__main__":
    main()