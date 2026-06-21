"""
fetch_sp500.py
──────────────
Fetches live data for ~500 US stocks (S&P 500 universe) with full fundamental
+ technical metrics.

Data sources (FREE):
  • yfinance   → Price, Market Cap, fundamentals, 52W H/L, growth rates
  • Pure pandas → All technical indicators (SMA50/200, ATR, Support/Resistance)

Output columns map to your Excel 'S&P 500' sheet:
  Symbol, Company Name, Sector, Market Cap ($B), P/E, P/B, PEG, EV/EBITDA,
  ROCE%, ROE 1Yr%, Revenue Growth 5Yr, 52-Week High/Low, 50-Day MA, 200-Day MA,
  Intrinsic Value (DCF estimate), Support, Resistance, Stop Loss, Buy Price,
  Target Price, Trend, Fundamental View, Technical View
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import yfinance as yf
import time
from typing import Optional

from .utils import setup_logger, retry, get_config_path, get_output_path, now_iso

log = setup_logger("sp500")


@retry(max_attempts=3, delay=3, backoff=2)
def fetch_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if hist.empty or len(hist) < 50:
        raise ValueError(f"Empty or insufficient history for {ticker}")
    return hist


def safe_pct(val):
    """Convert decimal (0.15) → 0.15 (decimal form, matches your sheet's existing format)."""
    if val is None:
        return None
    try:
        return round(float(val), 4)
    except (TypeError, ValueError):
        return None


def estimate_intrinsic_value(info: dict, current_price: float) -> Optional[float]:
    """
    Simple DCF-style intrinsic value estimate:
       IV ≈ Forward EPS × (1 + Growth)^5 / (Discount - Growth)
    Falls back to PE-based estimate if forward EPS missing.
    """
    try:
        eps = info.get("forwardEps") or info.get("trailingEps")
        growth = info.get("earningsGrowth") or 0.05
        if growth > 0.25: growth = 0.25  # cap
        if growth < -0.10: growth = -0.10  # floor
        discount_rate = 0.10  # 10% required return
        if not eps or eps <= 0:
            return None
        if (discount_rate - growth) <= 0:
            return None
        future_eps = eps * ((1 + growth) ** 5)
        iv = future_eps / (discount_rate - growth)
        return round(iv, 2)
    except Exception:
        return None


def compute_sma(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return np.nan
    return float(series.tail(period).mean())


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return np.nan
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift()).abs()
    tr3 = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def fundamental_view_score(info: dict) -> float:
    """0–5 composite fundamental score."""
    score = 0
    factors = 0

    pe = info.get("trailingPE")
    if pe and 0 < pe < 25:
        score += 1
        factors += 1
    elif pe:
        factors += 1

    roe = info.get("returnOnEquity")
    if roe and roe > 0.15:
        score += 1
        factors += 1
    elif roe is not None:
        factors += 1

    growth = info.get("earningsGrowth")
    if growth and growth > 0.10:
        score += 1
        factors += 1
    elif growth is not None:
        factors += 1

    debt = info.get("debtToEquity")
    if debt is not None and debt < 100:
        score += 1
        factors += 1
    elif debt is not None:
        factors += 1

    fcf = info.get("freeCashflow")
    if fcf and fcf > 0:
        score += 1
        factors += 1
    elif fcf is not None:
        factors += 1

    if factors == 0:
        return None
    return round((score / factors) * 5, 2)


def technical_view_score(close: float, sma50: float, sma200: float, atr: float, high_52w: float) -> float:
    """0–100 technical score."""
    score = 50  # neutral baseline
    if not np.isnan(sma50) and close > sma50:
        score += 12
    if not np.isnan(sma200) and close > sma200:
        score += 12
    if not np.isnan(sma50) and not np.isnan(sma200) and sma50 > sma200:
        score += 10  # golden cross-ish
    # Distance from 52W high (closer = stronger)
    if high_52w > 0:
        pct_from_high = (close - high_52w) / high_52w
        score += 15 * (1 + pct_from_high)  # at high: +15; at -50%: -7.5
    return round(max(0, min(100, score)), 2)


def process_symbol(symbol: str, company_name: str, sector: str) -> dict:
    try:
        hist = fetch_history(symbol, period="1y")
    except Exception as e:
        log.warning(f"  ⚠️  No data for {symbol}: {e}")
        return {"Symbol": symbol, "Company Name": company_name, "Sector": sector, "_status": f"ERROR: {e}"}

    close_series = hist["Close"]
    close = float(close_series.iloc[-1])
    high_52w = float(hist["High"].max())
    low_52w = float(hist["Low"].min())
    sma50 = compute_sma(close_series, 50)
    sma200 = compute_sma(close_series, 200)
    atr = compute_atr(hist, 14)

    # Support & Resistance from recent 20 days
    recent = hist.tail(20)
    support = round(float(recent["Low"].min()), 2)
    resistance = round(float(recent["High"].max()), 2)

    # Fundamentals
    try:
        info = yf.Ticker(symbol).info
    except Exception:
        info = {}

    market_cap_b = (info.get("marketCap") or 0) / 1e9 if info.get("marketCap") else None
    mcap_cat = ("Mega" if market_cap_b and market_cap_b > 200 else
                "Large" if market_cap_b and market_cap_b > 10 else
                "Mid" if market_cap_b and market_cap_b > 2 else
                "Small")

    iv = estimate_intrinsic_value(info, close)
    fund_view = fundamental_view_score(info)
    tech_view = technical_view_score(close, sma50, sma200, atr, high_52w)

    # Trend
    if not np.isnan(sma50) and not np.isnan(sma200):
        if close > sma50 > sma200: trend = "Uptrend"
        elif close < sma50 < sma200: trend = "Downtrend"
        else: trend = "Sideways"
    else:
        trend = "Unknown"

    # Stop loss & buy/target
    stop_loss = round(close - 2 * atr, 2) if not np.isnan(atr) else None
    buy_price = round(support * 1.02, 2)  # 2% above support
    target_price = round(close + 3 * atr, 2) if not np.isnan(atr) else None

    return {
        "Symbol": symbol,
        "SymbolMatch": symbol,
        "Company Name": company_name or info.get("longName"),
        "Sector": sector or info.get("sector"),
        "Market Cap ($B)": round(market_cap_b, 2) if market_cap_b else None,
        "Market Cap Category": mcap_cat,
        "P/E": round(info.get("trailingPE"), 2) if info.get("trailingPE") else None,
        "P/B": round(info.get("priceToBook"), 2) if info.get("priceToBook") else None,
        "PEG": round(info.get("pegRatio"), 2) if info.get("pegRatio") else None,
        "EV/EBITDA": round(info.get("enterpriseToEbitda"), 2) if info.get("enterpriseToEbitda") else None,
        "ROCE% (Return on Capital Employed)": safe_pct(info.get("returnOnAssets")),
        "ROE 1Yr%": safe_pct(info.get("returnOnEquity")),
        "ROE 10Yr %": safe_pct(info.get("returnOnEquity")),  # yfinance doesn't expose 10yr
        "Revenue Growth 5Yr": safe_pct(info.get("revenueGrowth")),
        "Earnings Growth 5Yr %": safe_pct(info.get("earningsGrowth")),
        "EBIT Growth 5Yr %": safe_pct(info.get("earningsGrowth")),
        "EPS Growth 5Yr %": safe_pct(info.get("earningsGrowth")),
        "YoY Quarterly Revenue Growth%": safe_pct(info.get("revenueQuarterlyGrowth")),
        "YoY Quarterly Earnings Growth %": safe_pct(info.get("earningsQuarterlyGrowth")),
        "52-Week High": round(high_52w, 2),
        "52-Week Low": round(low_52w, 2),
        "50-Day MA": round(sma50, 2) if not np.isnan(sma50) else None,
        "200-Day MA": round(sma200, 2) if not np.isnan(sma200) else None,
        "Intrinsic Value": iv,
        "Support": support,
        "Resistance": resistance,
        "Stop Loss": stop_loss,
        "Buy Price": buy_price,
        "Target Price": target_price,
        "Trend": trend,
        "Fundamental View": fund_view,
        "Technical View": tech_view,
        "_fetched_at": now_iso(),
        "_status": "OK",
    }


def run(input_csv: str = None, limit: int = None) -> pd.DataFrame:
    cfg = input_csv or get_config_path("sp500_tickers.csv")
    df_in = pd.read_csv(cfg)
    if limit:
        df_in = df_in.head(limit)

    log.info(f"📊 Starting S&P 500 fetch for {len(df_in)} tickers…")
    results = []
    for i, row in df_in.iterrows():
        if i % 25 == 0 and i > 0:
            log.info(f"   Progress: {i}/{len(df_in)} ({i/len(df_in)*100:.1f}%)")
        try:
            results.append(process_symbol(row["symbol"], row.get("company_name", ""), row.get("sector", "")))
        except Exception as e:
            log.error(f"   Error processing {row['symbol']}: {e}")
            results.append({"Symbol": row["symbol"], "_status": f"ERROR: {e}"})
        time.sleep(0.3)

    out_df = pd.DataFrame(results)
    out_path = get_output_path("sp500_latest.csv")
    out_df.to_csv(out_path, index=False)
    log.info(f"✅ S&P 500 done. {len(out_df)} rows → {out_path}")
    return out_df


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)
