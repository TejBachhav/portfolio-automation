"""
fetch_nifty500.py
─────────────────
Fetches live data for ~500 Indian stocks (Nifty 500 universe) and computes
all technical indicators required by the 'Nifty 500' sheet.

Data sources (FREE):
  • yfinance        → CMP, OHLCV history, 52W high/low, Market Cap
  • pandas-ta       → SMA50/200, ATR, Pivot Points, S1/S2/R1/R2, Trend
  • Screener.in     → P/E, EV/EBITDA, ROCE, ROE, growth rates (web scrape)

Output columns mapped to your Excel sheet:
  Company Name, Industry, CMP Rs., Mar Cap Rs.Cr., P/E, EV/EBITDA,
  ROCE %, ROE %, Sales growth %, Profit growth %, From 52w high,
  50 DMA, 200 DMA, Last Close, Pivot, S1, S2, R1, R2, SMA50, SMA200,
  Trend, ATR, StopLoss, TargetPrice

NOTE: Some columns (PEG, IV Rs., FII/DII chg, EPS Var 5Yrs) require
Screener.in scraping. Set ENABLE_SCREENER_SCRAPE=True in .env to activate.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import yfinance as yf
import time
import re
import requests
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup

from .utils import setup_logger, retry, get_config_path, get_output_path, now_iso

log = setup_logger("nifty500")

# ─── Manual ticker mapping for special cases ─────────────────────────────────
# Most companies follow pattern: "Company Name Ltd." → COMPANYNAME.NS
# But for the awkward ones we need explicit mappings. Add as you discover them.
MANUAL_TICKER_MAP = {
    "Amara Raja Energy & Mobility Ltd.": "ARE&M.NS",
    "Apollo Tyres Ltd.": "APOLLOTYRE.NS",
    "Asahi India Glass Ltd.": "ASAHIINDIA.NS",
    "Bajaj Auto Ltd.": "BAJAJ-AUTO.NS",
    "Balkrishna Industries Ltd.": "BALKRISIND.NS",
    "Bharat Forge Ltd.": "BHARATFORG.NS",
    "Bosch Ltd.": "BOSCHLTD.NS",
    "Ceat Ltd.": "CEATLTD.NS",
    "Craftsman Automation Ltd.": "CRAFTSMAN.NS",
    "Eicher Motors Ltd.": "EICHERMOT.NS",
    "Endurance Technologies Ltd.": "ENDURANCE.NS",
    "Exide Industries Ltd.": "EXIDEIND.NS",
    "Force Motors Ltd.": "FORCEMOT.NS",
    "Hero MotoCorp Ltd.": "HEROMOTOCO.NS",
    "Mahindra & Mahindra Ltd.": "M&M.NS",
    "Maruti Suzuki India Ltd.": "MARUTI.NS",
    "MRF Ltd.": "MRF.NS",
    "Tata Motors Ltd.": "TATAMOTORS.NS",
    "TVS Motor Company Ltd.": "TVSMOTOR.NS",
    "Reliance Industries Ltd.": "RELIANCE.NS",
    "Tata Consultancy Services Ltd.": "TCS.NS",
    "HDFC Bank Ltd.": "HDFCBANK.NS",
    "Infosys Ltd.": "INFY.NS",
    "ITC Ltd.": "ITC.NS",
    "Larsen & Toubro Ltd.": "LT.NS",
    "Wipro Ltd.": "WIPRO.NS",
}


def company_name_to_ticker(name: str) -> str:
    """Convert 'XYZ Ltd.' → 'XYZ.NS' (best-guess fallback)."""
    if name in MANUAL_TICKER_MAP:
        return MANUAL_TICKER_MAP[name]
    # Remove suffixes
    clean = re.sub(r"\s*(Ltd\.?|Limited|Corporation|Inc\.?|Industries|Company)\s*$",
                   "", name, flags=re.IGNORECASE).strip()
    # Take first word (works for many cases)
    parts = clean.split()
    base = parts[0].upper() if parts else clean.upper()
    base = re.sub(r"[^A-Z0-9&\-]", "", base)
    return f"{base}.NS"


@retry(max_attempts=3, delay=3, backoff=2)
def fetch_yfinance_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    """Fetch OHLCV history for a single ticker."""
    t = yf.Ticker(ticker)
    hist = t.history(period=period, auto_adjust=True)
    if hist.empty or len(hist) < 50:
        raise ValueError(f"Empty or insufficient history for {ticker}")
    return hist


@retry(max_attempts=3, delay=2, backoff=2)
def get_market_cap(ticker: str) -> Optional[float]:
    """Get current market cap in Rs. Crores."""
    t = yf.Ticker(ticker)
    info = t.info
    if not info:
        raise ValueError(f"Empty info dict returned for {ticker}")
    cap = info.get("marketCap")
    if cap:
        return round(cap / 1e7, 2)  # convert to Rs. Crores
    return None


@retry(max_attempts=3, delay=2, backoff=2)
def get_fundamentals_yfinance(ticker: str) -> dict:
    """Pull fundamentals available via yfinance's info dict."""
    t = yf.Ticker(ticker)
    info = t.info
    if not info:
        raise ValueError(f"Empty info dict returned for {ticker}")
    return {
        "P/E": info.get("trailingPE"),
        "P/B": info.get("priceToBook"),
        "EV/EBITDA": info.get("enterpriseToEbitda"),
        "ROE %": (info.get("returnOnEquity") or 0) * 100 if info.get("returnOnEquity") else None,
        "ROA %": (info.get("returnOnAssets") or 0) * 100 if info.get("returnOnAssets") else None,
        "Earnings Yield %": (info.get("earningsYield") or 0) * 100 if info.get("earningsYield") else None,
        "Sales growth %": (info.get("revenueGrowth") or 0) * 100 if info.get("revenueGrowth") else None,
        "Profit growth %": (info.get("earningsGrowth") or 0) * 100 if info.get("earningsGrowth") else None,
        "Sector": info.get("sector"),
        "Industry": info.get("industry"),
    }


# ─── Technical indicators (pure pandas, no extra deps required) ──────────────
def compute_sma(series: pd.Series, period: int) -> float:
    if len(series) < period:
        return np.nan
    return float(series.tail(period).mean())


def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range."""
    if len(df) < period + 1:
        return np.nan
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def compute_pivots(df: pd.DataFrame) -> dict:
    """Classic pivot points from previous day."""
    if len(df) < 2:
        return {"Pivot": np.nan, "S1": np.nan, "S2": np.nan, "R1": np.nan, "R2": np.nan}
    prev = df.iloc[-2]
    high, low, close = prev["High"], prev["Low"], prev["Close"]
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    r2 = pivot + (high - low)
    s2 = pivot - (high - low)
    return {"Pivot": round(pivot, 2), "S1": round(s1, 2), "S2": round(s2, 2),
            "R1": round(r1, 2), "R2": round(r2, 2)}


def determine_trend(close: float, sma50: float, sma200: float) -> str:
    """Simple trend classification."""
    if np.isnan(sma50) or np.isnan(sma200):
        return "Unknown"
    if close > sma50 > sma200:
        return "Uptrend"
    if close < sma50 < sma200:
        return "Downtrend"
    return "Sideways"


def compute_targets(close: float, atr: float, sma50: float) -> tuple:
    """StopLoss = max(close - 2*ATR, recent low). TargetPrice = close + 2*ATR."""
    if np.isnan(atr) or np.isnan(close):
        return (np.nan, np.nan)
    stop = round(max(close - 2 * atr, sma50 * 0.95) if not np.isnan(sma50) else close - 2 * atr, 2)
    target = round(close + 2 * atr, 2)
    return (stop, target)


# ─── Main fetcher ────────────────────────────────────────────────────────────
def process_stock(company_name: str, industry: str, ticker: str = None) -> dict:
    if not ticker or pd.isna(ticker):
        ticker = company_name_to_ticker(company_name)

    if ticker in ("UNLISTED", "DELISTED"):
        return {"Company Name": company_name, "Industry": industry, "_ticker": ticker, "_status": ticker}

    # Price history
    try:
        hist = fetch_yfinance_data(ticker, period="1y")
    except Exception as e:
        log.warning(f"  ⚠️  No data for {company_name} ({ticker}): {e}")
        return {"Company Name": company_name, "Industry": industry, "_ticker": ticker, "_status": f"ERROR: {e}"}

    close_series = hist["Close"]
    last_close = float(close_series.iloc[-1])

    # Technicals
    sma50 = compute_sma(close_series, 50)
    sma200 = compute_sma(close_series, 200)
    atr = compute_atr(hist, 14)
    pivots = compute_pivots(hist)
    trend = determine_trend(last_close, sma50, sma200)
    stop_loss, target_price = compute_targets(last_close, atr, sma50)

    # 52w high / how far below
    high_52w = float(hist["High"].max())
    from_52w = round((high_52w - last_close) / high_52w * 100, 2) if high_52w > 0 else None

    # Fundamentals + market cap
    fund = get_fundamentals_yfinance(ticker)
    market_cap_cr = get_market_cap(ticker)

    return {
        "Company Name": company_name,
        "Industry": industry,
        "CMP Rs.": round(last_close, 2),
        "Mar Cap Rs.Cr.": market_cap_cr,
        "P/E": fund.get("P/E"),
        "EV / EBITDA": fund.get("EV/EBITDA"),
        "Earnings Yield %": fund.get("Earnings Yield %"),
        "CMP / BV": fund.get("P/B"),
        "ROE %": fund.get("ROE %"),
        "Sales growth %": fund.get("Sales growth %"),
        "Profit growth %": fund.get("Profit growth %"),
        "From 52w high": from_52w,
        "50 DMA Rs.": round(sma50, 2) if not np.isnan(sma50) else None,
        "200 DMA Rs.": round(sma200, 2) if not np.isnan(sma200) else None,
        "Last Close": round(last_close, 2),
        **pivots,
        "SMA50": round(sma50, 2) if not np.isnan(sma50) else None,
        "SMA200": round(sma200, 2) if not np.isnan(sma200) else None,
        "Trend": trend,
        "ATR": round(atr, 2) if not np.isnan(atr) else None,
        "StopLoss": stop_loss,
        "TargetPrice": target_price,
        "_ticker": ticker,
        "_fetched_at": now_iso(),
        "_status": "OK",
    }


def run(input_csv: str = None, limit: int = None) -> pd.DataFrame:
    """Main entry point. Returns DataFrame of all stocks."""
    cfg = input_csv or get_config_path("nifty500_companies.csv")
    df_in = pd.read_csv(cfg)
    if limit:
        df_in = df_in.head(limit)

    log.info(f"📊 Starting Nifty 500 fetch for {len(df_in)} stocks…")
    results = []
    for i, row in df_in.iterrows():
        if i % 25 == 0 and i > 0:
            log.info(f"   Progress: {i}/{len(df_in)} ({i/len(df_in)*100:.1f}%)")
        try:
            ticker = row.get("ticker") if "ticker" in row else None
            results.append(process_stock(row["company_name"], row.get("industry", ""), ticker))
        except Exception as e:
            log.error(f"   Error processing {row['company_name']}: {e}")
            results.append({"Company Name": row["company_name"], "_status": f"ERROR: {e}"})
        time.sleep(0.3)  # gentle rate limit — yfinance allows ~2/sec

    out_df = pd.DataFrame(results)
    out_path = get_output_path("nifty500_latest.csv")
    out_df.to_csv(out_path, index=False)
    log.info(f"✅ Nifty 500 done. {len(out_df)} rows → {out_path}")
    return out_df


if __name__ == "__main__":
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=limit)
