import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq

# -------------------------
# 时间 & 基础工具
# -------------------------
def _to_date(x):
    if isinstance(x, pd.Timestamp):
        return x
    return pd.to_datetime(x)

def yearfrac(date, expiry):
    # ACT/365，日历天
    return max(( _to_date(expiry) - _to_date(date) ).days / 365.0, 0.0)

# -------------------------
# 利率插值（用 1Y / 5Y / 10Y 的零利率按到期 T 做分段线性插值）
# 输入：curve_df 按日有列: date, yield_1_year, yield_5_year, yield_10_year (百分数)
# -------------------------
def build_rate_lookup(curve_df):
    curve_df = curve_df.copy()
    curve_df["date"] = pd.to_datetime(curve_df["date"])
    # 转小数
    for c in ["yield_1_year","yield_5_year","yield_10_year"]:
        curve_df[c] = curve_df[c] / 100.0
    curve_df.set_index("date", inplace=True)
    curve_df.sort_index(inplace=True)

    def get_r(trade_date, T_years):
        # 若没有这天，就用最近日期（向后填充再向前填充）
        # 这里简单：找最近的可用日
        d = _to_date(trade_date)
        if d not in curve_df.index:
            # 最近可用（前向/后向）
            idx = curve_df.index.get_indexer([d], method="nearest")[0]
            row = curve_df.iloc[idx]
        else:
            row = curve_df.loc[d]

        r1 = row["yield_1_year"]
        r5 = row["yield_5_year"]
        r10 = row["yield_10_year"]

        if T_years <= 1.0:
            r = r1
        elif T_years <= 5.0:
            # 1Y-5Y 线性插值
            w = (T_years - 1.0) / (5.0 - 1.0)
            r = r1 * (1 - w) + r5 * w
        elif T_years <= 10.0:
            w = (T_years - 5.0) / (10.0 - 5.0)
            r = r5 * (1 - w) + r10 * w
        else:
            # >10y 就用 10y（或外推）
            r = r10
        return float(r)

    return get_r

# -------------------------
# Black-Scholes 价格（无分红，欧式）
# -------------------------
def bs_price(S, K, T, r, sigma, is_call=True):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return np.nan
    vol_sqrtT = sigma * np.sqrt(T)
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / vol_sqrtT
    d2 = d1 - vol_sqrtT
    if is_call:
        return S*norm.cdf(d1) - K*np.exp(-r*T)*norm.cdf(d2)
    else:
        return K*np.exp(-r*T)*norm.cdf(-d2) - S*norm.cdf(-d1)

# Vega（用于反推 IV）
def bs_vega(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*np.sqrt(T))
    return S * norm.pdf(d1) * np.sqrt(T)

# -------------------------
# 反推隐含波动率（Brent 根求解，稳定）
# -------------------------
def implied_vol(price, S, K, T, r, is_call=True, tol=1e-7):
    if not np.isfinite(price) or price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return np.nan

    # 合理的 sigma 搜索区间
    sigma_low, sigma_high = 1e-6, 5.0

    # 期权最小理论价（内含价值的贴现/或近似），用于快速过滤
    intrinsic = max(0.0, (S - K*np.exp(-r*T)) if is_call else (K*np.exp(-r*T) - S))
    if price < intrinsic - 1e-8:
        return np.nan

    # 定义目标函数
    def f(sig):
        return bs_price(S, K, T, r, sig, is_call) - price

    # 若端点同号，尝试扩张区间
    fl, fh = f(sigma_low), f(sigma_high)
    if np.isnan(fl) or np.isnan(fh):
        return np.nan
    for _ in range(8):
        if fl*fh < 0:
            break
        sigma_high *= 1.5
        fh = f(sigma_high)
        if not np.isfinite(fh):
            return np.nan

    try:
        root = brentq(f, sigma_low, sigma_high, xtol=tol, rtol=tol, maxiter=200)
        return float(root)
    except ValueError:
        # 使用简易牛顿法兜底
        sigma = 0.3
        for _ in range(50):
            p = bs_price(S, K, T, r, sigma, is_call)
            v = bs_vega(S, K, T, r, sigma)
            if v < 1e-10 or not np.isfinite(v):
                break
            diff = p - price
            sigma -= diff / v
            if sigma <= 0:
                sigma = 1e-4
            if abs(diff) < 1e-7:
                return float(sigma)
        return np.nan

# -------------------------
# Greeks（无分红）
# -------------------------
def bs_greeks(S, K, T, r, sigma, is_call=True):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return dict(delta=np.nan, gamma=np.nan, theta=np.nan, vega=np.nan, rho=np.nan)

    vol_sqrtT = sigma * np.sqrt(T)
    d1 = (np.log(S/K) + (r + 0.5*sigma**2)*T) / vol_sqrtT
    d2 = d1 - vol_sqrtT

    if is_call:
        delta = norm.cdf(d1)
        theta = (-(S*norm.pdf(d1)*sigma)/(2*np.sqrt(T)) - r*K*np.exp(-r*T)*norm.cdf(d2))
        rho   =  K*T*np.exp(-r*T)*norm.cdf(d2)
    else:
        delta = norm.cdf(d1) - 1.0
        theta = (-(S*norm.pdf(d1)*sigma)/(2*np.sqrt(T)) + r*K*np.exp(-r*T)*norm.cdf(-d2))
        rho   = -K*T*np.exp(-r*T)*norm.cdf(-d2)

    gamma = norm.pdf(d1) / (S*vol_sqrtT)
    vega  = S * norm.pdf(d1) * np.sqrt(T)

    # 习惯单位：theta按“每日”，vega/rho按“1%变动”
    return dict(
        delta=delta,
        gamma=gamma,
        theta=theta/365.0,
        vega=vega/100.0,
        rho=rho/100.0
    )

# -------------------------
# 主函数：按行计算 IV + Greeks
# 输入:
#   opt_df: 期权时序（见上面的列要求）
#   curve_df: 国债曲线（date, yield_1_year, yield_5_year, yield_10_year）
#   price_cols 优先级：bid/ask -> option_mid -> option_close -> option_price
# -------------------------
def compute_iv_and_greeks_timeseries(opt_df, curve_df,
                                     price_cols=("option_mid","option_close","option_price"),
                                     min_price=1e-4):
    df = opt_df.copy()
    # 规范日期
    df["date"] = pd.to_datetime(df["date"])
    df["expiry"] = pd.to_datetime(df["expiry"])
    # 价格选择：若有 bid/ask 优先用中间价
    if {"bid","ask"}.issubset(df.columns):
        df["option_price"] = (df["bid"] + df["ask"]) / 2.0
    else:
        # 按优先级找一个可用列
        # found = None
        # for c in price_cols:
        #     if c in df.columns:
        #         found = c
        #         break
        # if found is None:
        #     raise ValueError(f"没有找到期权价格列，支持：{price_cols} 或 (bid, ask)")
        df["option_price"] = df["close"]

    # 到期时间 T
    df["T"] = (df["expiry"] - df["date"]).dt.days / 365.0
    df.loc[df["T"] < 0, "T"] = 0.0

    # 利率查找器
    get_r = build_rate_lookup(curve_df)

    # 行计算
    out = []
    for row in df.itertuples(index=False):
        # import pdb;pdb.set_trace()  
        S = getattr(row, "S")
        K = float(getattr(row, "strike"))
        T = float(getattr(row, "T"))
        
        price = float(getattr(row, "option_price"))

        typ = getattr(row, "type").lower()
        is_call = (typ == "call")

        # 极端/无效直接 NaN
        if not (np.isfinite(S) and np.isfinite(K) and np.isfinite(T) and np.isfinite(price)) or price < min_price:
            out.append((np.nan, np.nan, np.nan, np.nan, np.nan, np.nan))
            continue

        r = get_r(getattr(row, "date"), max(T, 1e-6))

        iv = implied_vol(price, S, K, T, r, is_call=is_call)
        if not np.isfinite(iv) or iv <= 0:
            out.append((np.nan, np.nan, np.nan, np.nan, np.nan, np.nan))
            continue

        g = bs_greeks(S, K, T, r, iv, is_call=is_call)
        out.append((iv, g["delta"], g["gamma"], g["theta"], g["vega"], g["rho"]))

    df[["iv","delta","gamma","theta","vega","rho"]] = pd.DataFrame(out, index=df.index)
    return df

# -------------------------
# 示例（按需替换成你的数据）
# -------------------------
if __name__ == "__main__":
    # 假数据示例结构（请换成你的真实数据）
    opt_df = pd.DataFrame({
        "date": ["2025-01-13","2025-01-13","2025-01-13"],
        "expiry": ["2025-01-24","2025-02-21","2025-03-21"],
        "type": ["call","put","call"],
        "strike": [125, 120, 140],
        "S": [120, 120, 120],
        # 你可能有 bid/ask，这里直接给 mid
        "option_mid": [7.65, 7.80, 3.10],
    })

    curve_df = pd.DataFrame({
        "date": ["2025-01-13"],
        "yield_1_year": [4.5],
        "yield_5_year": [4.2],
        "yield_10_year":[4.1],
    })

    res = compute_iv_and_greeks_timeseries(opt_df, curve_df)
    print(res)
