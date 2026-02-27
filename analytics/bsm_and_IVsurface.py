# This file contains financial mathematical models the classical Black–Scholes–Merton (BSM) model

import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
import json
import pandas as pd
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
from mpl_toolkits.mplot3d import Axes3D
from datetime import datetime, timedelta

def bsm_price(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0:
        if option_type.upper() == 'C':
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    
    if option_type.upper() == 'C':
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif option_type.upper() == 'P':
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
    return 0.0

def find_iv(market_price, S, K, T, r, option_type):
    if option_type.upper() == 'C':
        intrinsic_val = max(0.0, S - K)
    else:
        intrinsic_val = max(0.0, K - S)
        
    if market_price <= intrinsic_val:
        return 0.0

    def objective_function(sigma):
        return bsm_price(S, K, T, r, sigma, option_type) - market_price

    try:
        return brentq(objective_function, 1e-6, 5.0)
    except (ValueError, RuntimeError):
        return 0.0

# Helper function to calculate IV for a list of options
def calculate_iv_for_list(options_list):
    for option in options_list:
        iv = find_iv(
            market_price=option['Price'],
            S=option['Spot'],
            K=option['Strike'],
            T=option['T'],
            r=option['Rate'],
            option_type=option['Type']
        )
        option['IV'] = round(iv, 4)
    return options_list

# --- Applying it to your data ---
with open('analytics/option_data.json', 'r') as file:
    option_data = json.load(file)

with open('analytics/earning_date.json', 'r') as file:
    earnings = json.load(file)
        
# Query NVIDIA first earning events
first_earnings = earnings['NVDA'][0]
day_before = (datetime.strptime(first_earnings, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
day_after = (datetime.strptime(first_earnings, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

# Fetch data for both days safely
options_list_before = option_data['NVDA'].get(day_before, [])
options_list_after = option_data['NVDA'].get(day_after, [])

# Calculate IV for both datasets
options_list_before = calculate_iv_for_list(options_list_before)
options_list_after = calculate_iv_for_list(options_list_after)
    
# Convert to DataFrames
df_before = pd.DataFrame(options_list_before)
df_after = pd.DataFrame(options_list_after)

if df_before.empty or df_after.empty:
    print("❌ Error: One or both of the options lists are empty. Check your data ingestion.")
else:
    print(f"✅ Data loaded: {len(df_before)} rows (Before), {len(df_after)} rows (After).")

    # Filter for Calls
    plot_df_before = df_before[(df_before['Type'] == 'C')].dropna(subset=['IV'])
    plot_df_after = df_after[(df_after['Type'] == 'C')].dropna(subset=['IV'])

    if len(plot_df_before) < 3 or len(plot_df_after) < 3:
        print("❌ Error: Not enough data points to create surfaces. Need at least 3 per day.")
    else:
        # --- STEP 2: Prepare Plotting ---
        # Set up a figure wide enough for two subplots side-by-side
        fig = plt.figure(figsize=(16, 7))
        fig.suptitle(f"NVDA Volatility Surface Comparison: Earnings {first_earnings}", fontsize=16)

        # Helper function for plotting surfaces
        def plot_surface(ax, df, title, cmap):
            x = df['Strike'].values
            y = df['T'].values
            z = df['IV'].values

            xi = np.linspace(min(x), max(x), 50)
            yi = np.linspace(min(y), max(y), 50)
            xi, yi = np.meshgrid(xi, yi)
            
            zi = griddata((x, y), z, (xi, yi), method='linear')

            surf = ax.plot_surface(xi, yi, zi, cmap=cmap, edgecolor='none', alpha=0.9)
            ax.set_xlabel('Strike')
            ax.set_ylabel('Time (T)')
            ax.set_zlabel('IV')
            ax.set_title(title)
            return surf

        # Subplot 1: Day Before
        ax1 = fig.add_subplot(121, projection='3d')
        plot_surface(ax1, plot_df_before, f"Day Before ({day_before})", 'magma')

        # Subplot 2: Day After
        ax2 = fig.add_subplot(122, projection='3d')
        plot_surface(ax2, plot_df_after, f"Day After ({day_after})", 'viridis')

        # --- STEP 3: Generate Plot ---
        plt.tight_layout()
        plt.savefig('surface_plot_comparison.png', dpi=300)
        print("✅ Plot saved as 'surface_plot_comparison.png'")
        
        plt.show()