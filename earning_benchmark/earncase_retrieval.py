import sqlite3
import pandas as pd
import os
from pandas.tseries.offsets import BDay
import json
import numpy as np
# Configuration
DATA_DIR = os.path.join(os.path.dirname(__file__), "Data")
DB_PATH_earnings = os.path.join(DATA_DIR, "benzinga_earnings.sqlite3")
DB_PATH_guidance = os.path.join(DATA_DIR, "benzinga_guidance.sqlite3")

with open('earning_benchmark/stock_daily_data.json', 'r') as f:
    daily_stock = json.load(f)
    
with open('earning_benchmark/stock_15m_data.json', 'r') as f:
     stock_15m = json.load(f) 
    

TIER_A = ["NVDA", "TSLA", "META", "AMZN", "MSFT", "GOOG", "GOOGL", "NFLX", "AVGO", "TSM", "ASML", "INTC"]
TIER_B = ["HOOD", "ORCL", "RGTI", "CRWV", "NBIS"]
TIER_C = ["AMD", "ARM", "MU", "QCOM", "SMCI", "CRM", "NOW", "SNOW", "PLTR", "AAPL", "SHOP", "COIN", "CRCL"]
trading_date = list(daily_stock['closes']['MSFT'])
calendar = pd.Series(trading_date)

def classify_intraday_event(row):
    # 1. VALIDATION: Check if data exists and is the correct type
    bars = row.get('intraday_15m_bars')
    
    fallback = pd.Series([None, None, "Invalid or missing bar data"], 
                         index=['intraday_structure', 'severity', 'notes'])

    if not isinstance(bars, list) or len(bars) < 3:
        return fallback

    try:
        # 2. EXTRACT & VECTORIZE
        opens = np.array([b['open'] for b in bars])
        highs = np.array([b['high'] for b in bars])
        lows = np.array([b['low'] for b in bars])
        closes = np.array([b['close'] for b in bars])
        
        start_o, end_c = opens[0], closes[-1]
        day_h, day_l = highs.max(), lows.min()
        total_range = day_h - day_l
        num_bars = len(bars)
        
        # Avoid division by zero
        if total_range == 0 or start_o == 0:
            return pd.Series(["Flat / No Vol", "S", "No price movement detected."], 
                             index=['intraday_structure', 'severity', 'notes'])

        # 3. TIMING & RATIOS
        # Divide by (num_bars - 1) to correctly scale from 0.0 to 1.0
        idx_h_pct = highs.argmax() / (num_bars - 1)
        idx_l_pct = lows.argmin() / (num_bars - 1)
        net_progress = end_c - start_o

        # 4. SEVERITY
        # Safely handle potential pandas NaN values
        range_pct = row.get('range_pct')
        if pd.isna(range_pct): 
            range_pct = total_range / start_o
        
        gap_level = row.get('gap_level')

        if range_pct < 0.02 or gap_level == 'small' or gap_level == 'no_gap': 
            severity = "S"
        elif range_pct <= 0.05 or gap_level == 'medium': 
            severity = "M"
        else: 
            severity = "L"

        # 5. PATTERN LOGIC
        pattern = "High-Vol Chop"
        notes = "Volatile session with no sustained directional breakout."

        # Trend Days (High displacement, closes near extreme)
        if abs(net_progress) > (total_range * 0.85):
            if net_progress > 0:
                pattern = "Trend Day Up"
                notes = "Consistent intraday strength; closed near highs."
            else:
                pattern = "Trend Day Down"
                notes = "Consistent intraday weakness; closed near lows."

        # Pop-and-Drop / Flush-and-Recover (Extreme in first 15% of bars)
        elif row.get('gap_pattern') == 'gap_up' and idx_h_pct < 0.15 and end_c < start_o:
            pattern = "Pop-and-Drop"
            notes = "Gap up was sold into immediately; heavy fade from opening high."
            
        elif row.get('gap_pattern') == 'gap_down' and idx_l_pct < 0.15 and end_c > start_o:
            pattern = "Flush-and-Recover"
            notes = "Initial flush found a floor early; price recovered to close above open."

        # V-Shape Reversals (Extreme in first 40% of bars)
        # Added check: Open must be significantly distant from the absolute extreme to prove a "reversal" happened
        elif idx_l_pct < 0.40 and end_c > (day_l + (total_range * 0.7)) and start_o > (day_l + (total_range * 0.2)):
            pattern = "V-shaped Reversal Up"
            notes = "Price dipped significantly mid-morning before a strong bullish reversal."
            
        elif idx_h_pct < 0.40 and end_c < (day_h - (total_range * 0.7)) and start_o < (day_h - (total_range * 0.2)):
            pattern = "Inverted-V Reversal Down"
            notes = "Early rally attempt failed; price reversed to close near lows."

        return pd.Series([pattern, severity, notes], 
                         index=['intraday_structure', 'severity', 'notes'])

    except Exception as e:
        return pd.Series(["Error", "N/A", f"Logic Error: {str(e)}"], 
                         index=['intraday_structure', 'severity', 'notes'])

def get_15m_ohlc(ticker, d0_date):
    """Safely extracts and formats the full 15-minute OHLC candles."""
    
    # 1. CRITICAL FIX: Force ticker and date to clean strings
    # This prevents the dictionary lookup from failing and returning None
    clean_ticker = str(ticker).strip()
    
    if hasattr(d0_date, 'strftime'):
        clean_date = d0_date.strftime('%Y-%m-%d')
    else:
        clean_date = str(d0_date).strip()
        
    # 2. Extract the raw lists from the nested dictionary safely
    
    opens = stock_15m.get('opens', {}).get(clean_ticker, {}).get(clean_date, [])
    highs = stock_15m.get('highs', {}).get(clean_ticker, {}).get(clean_date, [])
    lows = stock_15m.get('lows', {}).get(clean_ticker, {}).get(clean_date, [])
    closes = stock_15m.get('closes', {}).get(clean_ticker, {}).get(clean_date, [])
   
    # 3. If no data is found for this date, return an empty list
    if not closes:
        return []

    # 4. Build the OHLC list of dictionaries
    candles = []
    # Using len(closes) handles days that might have fewer than 26 bars
    for i in range(len(closes)):
        candles.append({
            "bar": i + 1,
            # We safely round the numbers, adding a small check just in case lists are uneven
            "open": round(opens[i], 2) if i < len(opens) else None,
            "high": round(highs[i], 2) if i < len(highs) else None,
            "low": round(lows[i], 2) if i < len(lows) else None,
            "close": round(closes[i], 2)
        })
        
    return candles


def process_row(row):
    t_raw = str(row['time']).strip().upper() if pd.notnull(row['time']) else ""
    
    # Default values
    timing = 'BMO'
    reaction_date_D0 = row['date']
    
    # 1. Logic: Parse by Hour (Best for HH:MM:SS format)
    try:
        hour = int(t_raw.split(':')[0])
        
        if hour >= 16:
            timing = 'AMC'
            reaction_date_D0 = row['date'] + BDay(1)
        elif hour < 9:
            timing = 'BMO'
            reaction_date_D0 = row['date']
        else:
            # If it's between 09:00 and 15:59, it's technically "During Market"
            # Most traders treat "During Market" as immediate reaction (T)
            timing = 'DURING'
            reaction_date_D0 = row['date']

    except (ValueError, IndexError):
        # 2. Fallback: String-based flags if hour parsing fails
        if any(k in t_raw for k in ['AMC', 'AFTER', 'POST', 'PM']):
            timing = 'AMC'
            reaction_date_D0 = row['date'] + BDay(1)
        else:
            timing = 'BMO'
            reaction_date_D0 = row['date']

    # 3. Summary Generation
    # Based on your data: 0.0800 represents 8.00%
    surprise_pct = row['eps_surprise_percent'] * 100
    status = "beat" if surprise_pct >= 0 else "missed"
    
    summary = (f"{row['ticker']} {status} estimates by {surprise_pct:.2f}% "
               f"(Actual: {row['actual_eps']}, Est: {row['estimated_eps']}).")
    
    return pd.Series([timing, reaction_date_D0, summary])



def get_guidance(ticker):
    conn = sqlite3.connect(DB_PATH_guidance)
    
    # Fixed the operator from =< to <=
    query = """
    SELECT ticker, date, estimated_revenue_guidance, fiscal_period, importance
    FROM guidance
    WHERE ticker = ? 
      AND date >= '2022-01-01' 
    """
    
    # Use params as a list or tuple
    df = pd.read_sql_query(query, conn, params=(ticker,))
    conn.close()
    
    if df.empty:
        print(f"No guidance found for {ticker} in Jan 2022.")
    else:
        print(df.head(10))
    return df

def add_drift_patterns(df):
    """
    Calculates PEAD and Reversion patterns using both Price and EPS Surprise.
    """
    if df.empty:
        return df

    # --- 1. Calculated Metrics ---
    # 5-Day Drift: D0 close to D5 close
    df['drift_5d_pct'] = ((df['D5_close'] - df['D0_close']) / df['D0_close']).round(4)
    # Day 1 vs D0 Close (for reversion/confirmation)
    df['d1_move'] = ((df['D1_close'] - df['D0_close']) / df['D0_close']).round(4)
    
    # Define Surprise Thresholds (e.g., 4% beat/miss)
    SURPRISE_THRESHOLD = 0.04

    # --- 2. Pattern 1 & 2: Post-ER Drift (Up/Down) ---
    # Definition: Fundamental Surprise + Price Gap + Continuation
    df['is_drift_up'] = (
        (df['eps_surprise_percent'] > SURPRISE_THRESHOLD) & 
        (df['gap'] > 0.01) & 
        (df['drift_5d_pct'] > 0)
    )
    
    df['is_drift_down'] = (
        (df['eps_surprise_percent'] < -SURPRISE_THRESHOLD) & 
        (df['gap'] < -0.01) & 
        (df['drift_5d_pct'] < 0)
    )


        
    conditions = [
        (df['is_drift_up'] == True),
        (df['is_drift_down'] == True)
    ]

    # 2. Define the corresponding values
    choices = ['up', 'down']

    # 3. Apply the logic with a default value of 'none'
    df['drift_trend'] = np.select(conditions, choices, default='none')
    # --- 3. Pattern 3: Mean Reversion (The "Fade") ---
    # Definition: Significant surprise/gap, but price exhausts and reverses on D1.
    # Often occurs when the "Good News" is already priced in (Sell the news).
    df['is_mean_reversion'] = (
        (df['day_return'].abs() > 0.04) & 
        (np.sign(df['d1_move']) != np.sign(df['day_return']))
    ).astype(bool)

    # --- 4. Pattern 4: 2nd-Day Confirmation / Failure ---
    # Logic: Does the stock maintain the new price level relative to D0 range?
    df['day2_status'] = np.select(
        [
            (df['gap'] > 0) & (df['D1_close'] > df['D0_high']), # Confirm Strength
            (df['gap'] > 0) & (df['D1_close'] < df['D0_low']),  # Immediate Rejection
            (df['gap'] < 0) & (df['D1_close'] < df['D0_low']),  # Confirm Weakness
            (df['gap'] < 0) & (df['D1_close'] > df['D0_high'])  # Bear Trap
        ],
        ['Confirm_Up', 'Fail_Up', 'Confirm_Down', 'Fail_Down'],
        default='Inside_Range'
    )

    return df

def get_event_metadata(ticker):
    if not os.path.exists(DB_PATH_earnings):
        print(f"Database not found at {DB_PATH_earnings}")
        return pd.DataFrame()

    # 1. Database Fetch
    conn = sqlite3.connect(DB_PATH_earnings)
    query = """
    SELECT ticker, date, time, benzinga_id as event_id,
           actual_eps, estimated_eps, eps_surprise_percent
    FROM earnings 
    WHERE ticker = ? AND date_status = 'confirmed' AND date >= '2022-01-01'
    ORDER BY date DESC
    """
    df = pd.read_sql_query(query, conn, params=(ticker,))
    conn.close()

    if df.empty:
        return df

    # 2. Setup Trading Calendar 
    # Ensure trading_dates are string format to match searchsorted logic
    ticker_data = daily_stock['closes'].get(ticker, {})
    trading_dates = sorted(list(ticker_data.keys()))
    
    if not trading_dates:
        return df
    
    calendar = pd.Series(trading_dates)
    
    # 3. Determine D0 Index
    df['date'] = pd.to_datetime(df['date'])
    # result_type='expand' is crucial here
    df[['timing', 'D0_temp', 'summary']] = df.apply(process_row, axis=1, result_type='expand')
    
    # Ensure we are comparing strings
    d0_strings = pd.to_datetime(df['D0_temp']).dt.strftime('%Y-%m-%d')
    
    # Use searchsorted to find the closest trading day index
    d0_idx = np.searchsorted(trading_dates, d0_strings)

    # 4. Map OHLC for the 5-Day Window
    t_opens  = daily_stock.get('opens', {}).get(ticker, {})
    t_highs  = daily_stock.get('highs', {}).get(ticker, {})
    t_lows   = daily_stock.get('lows', {}).get(ticker, {})
    t_closes = daily_stock.get('closes', {}).get(ticker, {})

    for offset in range(-2, 6): 
        prefix = "D"
        date_col = f"D{offset}" if offset != 0 else "D0"
        
        target_idx = d0_idx + offset
        mask = (target_idx >= 0) & (target_idx < len(trading_dates))
        
        df[date_col] = np.where(
            mask, 
            calendar.values[target_idx.clip(0, len(trading_dates)-1)], 
            None
        )

        df[f'{date_col}_open']  = df[date_col].map(t_opens)
        df[f'{date_col}_high']  = df[date_col].map(t_highs)
        df[f'{date_col}_low']   = df[date_col].map(t_lows)
        df[f'{date_col}_close'] = df[date_col].map(t_closes)

    # 5. Vectorized Metrics (Added 0-check for safety)
    d1_close_safe = df['D-1_close'].replace(0, np.nan)
    d0_open_safe = df['D0_open'].replace(0, np.nan)
    
    df['gap']        = ((df['D0_open'] - d1_close_safe) / d1_close_safe).round(4)
    df['day_return'] = ((df['D0_close'] - d0_open_safe) / d0_open_safe).round(4)
    df['range_pct']  = ((df['D0_high'] - df['D0_low']) / d0_open_safe).round(4)
    df['fade']       = ((df['D0_close'] - df['D0_high'].replace(0, np.nan)) / df['D0_high'].replace(0, np.nan)).round(4)
    df['recovery']   = ((df['D0_close'] - df['D0_low'].replace(0, np.nan)) / df['D0_low'].replace(0, np.nan)).round(4)



    # 6. Pattern Logic
    gap_mag = df['gap'].abs()
    df['gap_pattern'] = np.select(
        [gap_mag < 0.005, df['gap'] > 0, df['gap'] < 0],
        ['flat', 'gap_up', 'gap_down'], 
        default='unknown'
    )

    # Gap Level Logic
    df['gap_level'] = np.select(
        [gap_mag < 0.005, gap_mag > 0.03, gap_mag > 0.01, gap_mag >= 0.005],
        ['no_gap', 'large', 'medium', 'small'], 
        default='None'
    )
    
     # 7. Intraday Bars & Pattern Classification
    df['intraday_15m_bars'] = df.apply(lambda row: get_15m_ohlc(row['ticker'], row['D0']), axis=1)
    df[['intraday_structure', 'severity', 'notes']] = df.apply(classify_intraday_event, axis=1)
    
    
     # 8. Drift Event:
    df = add_drift_patterns(df)
    
    df['date'] = df['date'].dt.strftime('%Y-%m-%d')
    return df


if __name__ == "__main__":
    # --- Test Execution ---
    ticker_to_check = "AMD"
    metadata = get_event_metadata(ticker_to_check)
    if not metadata.empty:
        print(f"\nSuccessfully processed {len(metadata)} events for {ticker_to_check}:")
        # Display the most relevant columns for debugging
        metadata['post_earnings_drift'] = metadata.apply(
            lambda row: {
                "drift_trend": row['drift_trend'],
                "is_mean_reversion": row['is_mean_reversion'],
                'day2_status': row['day2_status']
            }, axis=1
        )
        metadata = metadata.drop(columns=['drift_trend', 'is_mean_reversion', 'day2_status'])
        cols_to_show = [
            # (A) Event Metadata
            'ticker', 
            'date',
            'time', 
            'timing', 
            'event_id', 
            'summary', 

            # (B) Price Window (Daily OHLC arrays/dicts and Intraday Bars)
            'D-2_open', 'D-2_high', 'D-2_low', 'D-2_close',
            'D-1_open', 'D-1_high', 'D-1_low', 'D-1_close',
            'D0_open',  'D0_high',  'D0_low',  'D0_close',
            'D1_open',  'D1_high',  'D1_low',  'D1_close',
            'D2_open',  'D2_high',  'D2_low',  'D2_close',
            'intraday_15m_bars',

            # (C) Computed Metrics
            'gap', 
            'day_return', 
            'range_pct', 
            'fade', 
            'recovery', 

            # (D) Labels
            'gap_pattern',
            'gap_level',
            'intraday_structure',
            'severity',  #Combine gap_level and intraday range
            'notes',
            'post_earnings_drift'
        ]

        print(metadata[cols_to_show])
        df_export = metadata[cols_to_show]
        
        metadata[cols_to_show].to_csv(f'earncase_{ticker_to_check}.csv')
        output_dir = "earning_benchmark"
        os.makedirs(output_dir, exist_ok=True) # Ensures the folder exists
        
        output_filepath = os.path.join(output_dir, f"earncase_{ticker_to_check}.json")
        
        # Export as a list of dictionaries (orient='records')
        json_output = df_export.to_json(output_filepath, orient='records', indent=4)
        print(json_output)