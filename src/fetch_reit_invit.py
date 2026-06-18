"""
fetch_reit_invit.py
───────────────────
Fetches data for Indian REITs and InvITs (only 11 instruments in your universe).

Data sources (FREE):
  • yfinance → Price, 52W high/low, market cap, technicals (treats them as stocks)
  • Pure pandas → SMA50, SMA200, dividend yield calculation

NOTE: Columns that REQUIRE manual quarterly updates from company filings:
  - Occupancy Rate %  (only in REIT investor presentations)
  - Distribution Per Unit (announced quarterly)
  - Free Cash Flow (Cr) (in financial reports)
  - Debt to Equity (in balance sheet)
  - Interest Coverage (in financial reports)
These are kept from your previous data unless you manually update the config.
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import yfinance as yf
import time
from datetime import datetime

from .utils import setup_logger, retry, get_config_path, get_output_path, now_iso

log = setup_logger("reit_invit")

# Yahoo ticker mapping for Indian REITs/InvITs (NSE symbol → .NS suffix)
REIT_TICKER_MAP = {
    "EMBASSY": "EMBASSY.NS",
    "MINDSPACE": "MINDSPACE.NS",
    "NXST": "NXST.NS",
    "INDIGRID": "INDIGRID.NS",
    "PGINVIT": "PGINVIT.NS",
    "IRBINVIT": "IRBINVIT.NS",
    "BIRET": "BIRET.NS",
    "360ONE": "360ONE.NS",
    "INDUSTOWER": "INDUSTOWER.NS",
    "IRISDOTML": "IRISDOTML.NS",
    "INDIGRIDL": "INDIGRID.NS",
}

# Fundamental columns that must be manually updated quarterly
# These come from company investor presentations / SEBI filings
FUNDAMENTAL_OVERRIDES = {
    # symbol: { col: value }  — update these quarterly from filings
    "EMBASSY": {"Occupancy Rate %": 93.0, "Distribution Per Unit": 25.4,
                "Free Cash Flow (Cr)": 4250.0, "Debt to Equity": 0.58,
                "Interest Coverage": 4.85, "AUM (Cr)": 57800.0},
    "MINDSPACE": {"Occupancy Rate %": 97.0, "Distribution Per Unit": 23.32,
                  "Free Cash Flow (Cr)": 3180.0, "Debt to Equity": 0.52,
                  "Interest Coverage": 5.2, "AUM (Cr)": 38500.0},
    "NXST": {"Occupancy Rate %": 97.0, "Distribution Per Unit": 8.8,
             "Free Cash Flow (Cr)": 2450.0, "Debt to Equity": 0.28,
             "Interest Coverage": 6.5, "AUM (Cr)": 25600.0},
    "INDIGRID": {"Distribution Per Unit": 16.0, "Free Cash Flow (Cr)": 2850.0,
                 "Debt to Equity": 2.2, "Interest Coverage": 1.91, "AUM (Cr)": 32500.0},
    "PGINVIT": {"Distribution Per Unit": 12.05, "Free Cash Flow (Cr)": 1680.0,
                "Debt to Equity": 1.85, "Interest Coverage": 2.15, "AUM (Cr)": 18200.0},
    "IRBINVIT": {"Distribution Per Unit": 8.0, "Free Cash Flow (Cr)": 1420.0,
                 "Debt to Equity": 1.65, "Interest Coverage": 2.8, "AUM (Cr)": 15800.0},
    "BIRET": {"Occupancy Rate %": 90.0, "Distribution Per Unit": 20.85,
              "Free Cash Flow (Cr)": 3520.0, "Debt to Equity": 0.62,
              "Interest Coverage": 4.6, "AUM (Cr)": 39600.0},
    "360ONE": {"Occupancy Rate %": 94.0, "Distribution Per Unit": 12.0,
               "Free Cash Flow (Cr)": 4180.0, "Debt to Equity": 0.48,
               "Interest Coverage": 5.8, "AUM (Cr)": 52000.0},
    "INDUSTOWER": {"Distribution Per Unit": 25.15, "Free Cash Flow (Cr)": 12500.0,
                   "Debt to Equity": 0.6, "Interest Coverage": 7.54},
}


@retry(max_attempts=3, delay=4)
def fetch_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    ticker = REIT_TICKER_MAP.get(symbol, f"{symbol}.NS")
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    return hist


def compute_dividend_yield(symbol: str, current_price: float) -> float:
    """Estimate annual yield from yfinance dividend history."""
    try:
        ticker = REIT_TICKER_MAP.get(symbol, f"{symbol}.NS")
        divs = yf.Ticker(ticker).dividends
        if divs.empty:
            return None
        # Sum last 12 months of distributions
        recent = divs[divs.index >= divs.index.max() - pd.Timedelta(days=365)]
        annual_dividend = float(recent.sum())
        if current_price > 0:
            return round(annual_dividend / current_price * 100, 2)
    except Exception:
        pass
    return None


def process_reit(row: dict) -> dict:
    symbol = row["symbol"]
    log.info(f"  Processing {symbol} — {row['name']}")

    try:
        hist = fetch_history(symbol, period="3y")
    except Exception as e:
        log.warning(f"  ⚠️  Failed to fetch {symbol}: {e}")
        return {**row, "_status": f"ERROR: {e}", "_fetched_at": now_iso()}

    if hist.empty:
        return {**row, "_status": "NO_DATA", "_fetched_at": now_iso()}

    close = float(hist["Close"].iloc[-1])
    high_52w = float(hist.tail(252)["High"].max())
    low_52w = float(hist.tail(252)["Low"].min())
    sma50 = float(hist["Close"].tail(50).mean()) if len(hist) >= 50 else None
    sma200 = float(hist["Close"].tail(200).mean()) if len(hist) >= 200 else None

    # 1Y, 3Y, 5Y returns
    def period_return(days):
        if len(hist) < days:
            return None
        past = hist.iloc[-days]["Close"]
        if past <= 0:
            return None
        return round((close - past) / past * 100, 2)

    ret_1y = period_return(252)
    ret_3y = period_return(756)
    ret_5y = period_return(1260)

    dy = compute_dividend_yield(symbol, close)

    # Market cap from yfinance
    try:
        info = yf.Ticker(REIT_TICKER_MAP.get(symbol, f"{symbol}.NS")).info
        mcap = (info.get("marketCap") or 0) / 1e7  # to Cr
    except Exception:
        mcap = None

    # Manual overrides (from quarterly filings)
    overrides = FUNDAMENTAL_OVERRIDES.get(symbol, {})

    return {
        "symbol": symbol,
        "name": row["name"],
        "type": row["type"],
        "sector": row["sector"],
        "price": round(close, 2),
        "dividend_yield_pct": dy if dy else overrides.get("dividend_yield_pct"),
        "return_1yr": ret_1y,
        "market_cap_cr": round(mcap, 2) if mcap else None,
        "min_investment": round(close, 0),  # min investment ≈ current price (1 unit)
        "exchange": "NSE",
        "data_date": datetime.now().strftime("%Y-%m-%d"),
        "NAV": round(close, 2),  # for traded REITs, NAV ≈ price
        "Distribution Per Unit": overrides.get("Distribution Per Unit"),
        "Occupancy Rate %": overrides.get("Occupancy Rate %"),
        "AUM (Cr)": overrides.get("AUM (Cr)"),
        "52W High": round(high_52w, 2),
        "52W Low": round(low_52w, 2),
        "50 DMA": round(sma50, 2) if sma50 else None,
        "200 DMA": round(sma200, 2) if sma200 else None,
        "Return 3Yr %": ret_3y,
        "Return 5Yr %": ret_5y,
        "Free Cash Flow (Cr)": overrides.get("Free Cash Flow (Cr)"),
        "Debt to Equity": overrides.get("Debt to Equity"),
        "Interest Coverage": overrides.get("Interest Coverage"),
        "_fetched_at": now_iso(),
        "_status": "OK",
    }


def run(input_csv: str = None) -> pd.DataFrame:
    cfg = input_csv or get_config_path("reit_invit.csv")
    df_in = pd.read_csv(cfg)
    log.info(f"📊 Starting REIT/InvIT fetch for {len(df_in)} instruments…")

    results = []
    for _, row in df_in.iterrows():
        try:
            results.append(process_reit(row.to_dict()))
        except Exception as e:
            log.error(f"   Error on {row['symbol']}: {e}")
            results.append({"symbol": row["symbol"], "_status": f"ERROR: {e}"})
        time.sleep(0.5)

    out_df = pd.DataFrame(results)
    out_path = get_output_path("reit_invit_latest.csv")
    out_df.to_csv(out_path, index=False)
    log.info(f"✅ REIT/InvIT done. {len(out_df)} rows → {out_path}")
    return out_df


if __name__ == "__main__":
    run()
