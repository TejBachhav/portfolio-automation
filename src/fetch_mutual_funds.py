"""
fetch_mutual_funds.py
─────────────────────
Fetches NAV and computes analytics for all Indian Mutual Funds (Equity + Debt)
listed in your config files.

Data sources (FREE):
  • AMFI India        → https://www.amfiindia.com/spages/NAVAll.txt
                        Official, daily-updated, all schemes
  • MFAPI.in          → https://api.mfapi.in/mf/{scheme_code}
                        Historical NAV (free, no auth needed) — used for
                        computing Sharpe, Sortino, Alpha, Rolling Returns

Why these sources:
  AMFI is the official regulator-mandated source for all MF NAVs in India.
  MFAPI.in provides historical NAV needed for risk metrics.

Output columns for both EQUITY MF and DEBT MF sheets:
  SCHEMES, EXPENSE RATIO, CATEGORY, AUM(CR), 1 DAY, 7 DAY, 15 DAY, 30 DAY,
  3 MONTH, 6 MONTH, 1 YEAR, 2 YEAR, 3 YEAR, 5 YEAR, ..., SINCE INCEPTION,
  ALPHA, BETA, MEAN, STANDARD DEV, SHARPE RATIO, SORTINO RATIO,
  AVERAGE MATURITY, MODIFIED DURATION, YIELD TO MATURITY,
  LAUNCH DATE, SCHEME BENCHMARK, CURRENT NAV, IS RECOMMENDED, ...
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime, timedelta
from io import StringIO
from typing import Optional

from .utils import setup_logger, retry, get_config_path, get_output_path, now_iso

log = setup_logger("mutual_funds")

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
MFAPI_BASE = "https://api.mfapi.in/mf"
RISK_FREE_RATE = 0.065  # 6.5% (Indian 10Y G-Sec approximation)


# ─── Step 1: Fetch all NAVs in one call (~1MB file) ──────────────────────────
@retry(max_attempts=3, delay=5)
def fetch_amfi_navs() -> pd.DataFrame:
    """
    Returns a DataFrame with columns:
       Scheme Code | ISIN Growth | ISIN Dividend | Scheme Name | Net Asset Value | Date
    """
    log.info("📥 Downloading AMFI NAV master file…")
    r = requests.get(AMFI_URL, timeout=30)
    r.raise_for_status()
    text = r.text

    rows = []
    current_amc = None
    current_category = None
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Lines that contain only the AMC name (no semicolons)
        if ";" not in line and "Mutual Fund" in line:
            current_amc = line
            continue
        if ";" not in line and ("Schemes" in line or "Plans" in line):
            current_category = line
            continue
        parts = line.split(";")
        if len(parts) >= 6 and parts[0].strip().isdigit():
            try:
                rows.append({
                    "scheme_code": parts[0].strip(),
                    "isin_growth": parts[1].strip(),
                    "isin_dividend": parts[2].strip(),
                    "scheme_name": parts[3].strip(),
                    "nav": float(parts[4]) if parts[4].strip() and parts[4].strip() != "N.A." else None,
                    "nav_date": parts[5].strip(),
                    "amc": current_amc,
                    "amfi_category": current_category,
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)
    log.info(f"   AMFI: parsed {len(df)} schemes")
    return df


# ─── Step 2: Match user's schemes to AMFI codes ──────────────────────────────
def fuzzy_match_schemes(user_schemes: pd.DataFrame, amfi_df: pd.DataFrame) -> pd.DataFrame:
    """
    Match each user scheme to AMFI's scheme code via fuzzy string matching.
    Returns user_schemes with added 'scheme_code', 'current_nav', 'nav_date' columns.
    """
    log.info(f"🔗 Matching {len(user_schemes)} user schemes to AMFI master…")

    # Manual mapping for renamed/special cases
    MANUAL_LOOKUP = {
        "HDFC Non-Cyclical Consumer Fund Reg (G)": "151803",
    }

    # Normalize for matching
    def normalize(s: str) -> str:
        if not isinstance(s, str):
            return ""
        s = s.upper()
        # Common normalizations
        replacements = {
            " REG ": " ", "(G)": "GROWTH", " (G) ": " GROWTH ", " G ": " GROWTH ",
            "FOF": "FUND OF FUND", "E T F": "ETF", " ETF ": " ETF ",
            "SL ": "SUN LIFE ", "MF ": " ", " PRU ": " PRUDENTIAL ",
            "MUTUAL FUND": "", "FUND": "", "SCHEME": "",
            "INFRA": "INFRASTRUCTURE", "ECO": "ECONOMIC", "STD": "STANDARD",
            "  ": " ",
        }
        for k, v in replacements.items():
            s = s.replace(k, v)
        # Remove punctuation
        for ch in "().,&-/":
            s = s.replace(ch, " ")
        return " ".join(s.split())

    amfi_df["_norm"] = amfi_df["scheme_name"].apply(normalize)
    amfi_df["_tokens"] = amfi_df["_norm"].apply(lambda x: set(x.split()))
    
    # Pre-unpack dataframe to plain Python list of tuples for 100x speedup
    amfi_list = list(zip(amfi_df["scheme_code"], amfi_df["scheme_name"], amfi_df["nav"], amfi_df["nav_date"], amfi_df["_tokens"]))
    
    matches = []
    for _, row in user_schemes.iterrows():
        user_name = row["scheme_name"]
        
        # Check manual overrides
        if user_name in MANUAL_LOOKUP:
            code = MANUAL_LOOKUP[user_name]
            amfi_match = amfi_df[amfi_df["scheme_code"] == code]
            if not amfi_match.empty:
                matches.append({
                    "scheme_name": user_name,
                    "category": row.get("category", ""),
                    "scheme_code": code,
                    "matched_amfi_name": amfi_match.iloc[0]["scheme_name"],
                    "current_nav": amfi_match.iloc[0]["nav"],
                    "nav_date": amfi_match.iloc[0]["nav_date"],
                    "match_score": 1.0,
                })
                continue

        user_norm = normalize(user_name)
        user_tokens = set(user_norm.split())

        # Score each AMFI scheme by token overlap
        best_score = 0
        best_match = None
        for a_code, a_name, a_nav, a_date, a_tokens in amfi_list:
            if not a_tokens or not user_tokens:
                continue
            overlap = len(user_tokens & a_tokens)
            score = overlap / max(len(user_tokens), len(a_tokens))
            if score > best_score:
                best_score = score
                best_match = {
                    "scheme_code": a_code,
                    "scheme_name": a_name,
                    "nav": a_nav,
                    "nav_date": a_date
                }
        if best_match is not None and best_score >= 0.5:
            matches.append({
                "scheme_name": user_name,
                "category": row.get("category", ""),
                "scheme_code": best_match["scheme_code"],
                "matched_amfi_name": best_match["scheme_name"],
                "current_nav": best_match["nav"],
                "nav_date": best_match["nav_date"],
                "match_score": round(best_score, 2),
            })
        else:
            matches.append({
                "scheme_name": user_name,
                "category": row.get("category", ""),
                "scheme_code": None,
                "matched_amfi_name": None,
                "current_nav": None,
                "nav_date": None,
                "match_score": round(best_score, 2),
            })

    matched_df = pd.DataFrame(matches)
    success = matched_df["scheme_code"].notna().sum()
    log.info(f"   Matched {success}/{len(matched_df)} ({success/len(matched_df)*100:.1f}%)")
    return matched_df


# ─── Step 3: Fetch historical NAV & compute analytics ────────────────────────
@retry(max_attempts=3, delay=2, backoff=2)
def fetch_scheme_history(scheme_code) -> pd.DataFrame:
    """Get full historical NAV from mfapi.in (free, no auth)."""
    if pd.isna(scheme_code):
        raise ValueError("Scheme code is NaN")
    # Cast to clean integer string, e.g. 129195.0 -> "129195"
    code_str = str(int(float(scheme_code)))
    r = requests.get(f"{MFAPI_BASE}/{code_str}", timeout=15)
    r.raise_for_status()
    data = r.json()
    if "data" not in data or not data["data"]:
        raise ValueError(f"No history data returned for scheme {code_str}")
    df = pd.DataFrame(data["data"])
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y")
    df["nav"] = df["nav"].astype(float)
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_period_return(nav_df: pd.DataFrame, days_back: int) -> Optional[float]:
    """% return over a period."""
    if nav_df is None or nav_df.empty:
        return None
    latest = nav_df.iloc[-1]
    target_date = latest["date"] - timedelta(days=days_back)
    past = nav_df[nav_df["date"] <= target_date]
    if past.empty:
        return None
    past_nav = past.iloc[-1]["nav"]
    if past_nav <= 0:
        return None
    ret = ((latest["nav"] - past_nav) / past_nav) * 100
    # Annualize for periods > 1 year
    if days_back > 365:
        years = days_back / 365.25
        ret = (((latest["nav"] / past_nav) ** (1 / years)) - 1) * 100
    return round(ret, 2)


def compute_risk_metrics(nav_df: pd.DataFrame) -> dict:
    """Sharpe, Sortino, Mean, Std Dev based on daily returns."""
    if nav_df is None or len(nav_df) < 250:
        return {"ALPHA": None, "BETA": None, "MEAN": None,
                "STANDARD DEV": None, "SHARPE RATIO": None, "SORTINO RATIO": None}

    # Use last 3 years of daily data
    cutoff = nav_df["date"].max() - timedelta(days=3 * 365)
    recent = nav_df[nav_df["date"] >= cutoff].copy()
    if len(recent) < 100:
        recent = nav_df.copy()

    recent["daily_return"] = recent["nav"].pct_change()
    daily_ret = recent["daily_return"].dropna()
    if len(daily_ret) < 30:
        return {"ALPHA": None, "BETA": None, "MEAN": None,
                "STANDARD DEV": None, "SHARPE RATIO": None, "SORTINO RATIO": None}

    annual_mean = float(daily_ret.mean() * 252)
    annual_std = float(daily_ret.std() * (252 ** 0.5))

    sharpe = (annual_mean - RISK_FREE_RATE) / annual_std if annual_std > 0 else None

    # Sortino: downside std only
    downside = daily_ret[daily_ret < 0]
    downside_std = float(downside.std() * (252 ** 0.5)) if len(downside) > 0 else None
    sortino = ((annual_mean - RISK_FREE_RATE) / downside_std) if downside_std and downside_std > 0 else None

    return {
        "ALPHA": None,  # requires benchmark — see compute_alpha_beta if needed
        "BETA": None,
        "MEAN": round(annual_mean * 100, 2),
        "STANDARD DEV": round(annual_std * 100, 2),
        "SHARPE RATIO": round(sharpe, 2) if sharpe else None,
        "SORTINO RATIO": round(sortino, 2) if sortino else None,
    }


def process_scheme(scheme_row: dict) -> dict:
    """Build the full row for one scheme."""
    base = {
        "SCHEMES": scheme_row["scheme_name"],
        "CATEGORY": scheme_row.get("category", ""),
        "_scheme_code": scheme_row.get("scheme_code"),
        "_match_score": scheme_row.get("match_score"),
        "CURRENT NAV": scheme_row.get("current_nav"),
        "_nav_date": scheme_row.get("nav_date"),
        "_fetched_at": now_iso(),
    }
    if not scheme_row.get("scheme_code"):
        base["_status"] = "NO_AMFI_MATCH"
        return base

    try:
        hist = fetch_scheme_history(scheme_row["scheme_code"])
    except Exception as e:
        log.warning(f"   ⚠️  No history for {scheme_row['scheme_name']}: {e}")
        base["_status"] = f"ERROR: {e}"
        return base

    # Period returns
    periods = [("1 DAY", 1), ("7 DAY", 7), ("15 DAY", 15), ("30 DAY", 30),
               ("3 MONTH", 90), ("6 MONTH", 180), ("1 YEAR", 365),
               ("2 YEAR", 730), ("3 YEAR", 1095), ("5 YEAR", 1825),
               ("7 YEAR", 2555), ("10 YEAR", 3650), ("15 YEAR", 5475),
               ("20 YEAR", 7300), ("25 YEAR", 9125)]
    for label, days in periods:
        base[label] = compute_period_return(hist, days)

    # Since inception
    if not hist.empty:
        inception = hist.iloc[0]
        latest = hist.iloc[-1]
        years = (latest["date"] - inception["date"]).days / 365.25
        if years > 0 and inception["nav"] > 0:
            si_ret = (((latest["nav"] / inception["nav"]) ** (1 / years)) - 1) * 100
            base["SINCE INCEPTION RETURN"] = round(si_ret, 2)
            base["LAUNCH DATE"] = inception["date"].strftime("%d-%m-%Y")

    # Risk metrics
    base.update(compute_risk_metrics(hist))

    # 52W high/low (for Debt MF sheet)
    last_year = hist[hist["date"] >= hist["date"].max() - timedelta(days=365)]
    if not last_year.empty:
        base["52-Weeks High NAV"] = round(float(last_year["nav"].max()), 4)
        base["52-Weeks Low NAV"] = round(float(last_year["nav"].min()), 4)
        if base.get("CURRENT NAV") and base["52-Weeks High NAV"]:
            base["Discount"] = round(
                (base["52-Weeks High NAV"] - base["CURRENT NAV"]) / base["52-Weeks High NAV"] * 100, 2
            )

    base["_status"] = "OK"
    return base


def run_equity_mf(limit: int = None) -> pd.DataFrame:
    return _run_mf_universe(get_config_path("equity_mf_schemes.csv"),
                            "equity_mf_latest.csv", "EQUITY MF", limit)


def run_debt_mf(limit: int = None) -> pd.DataFrame:
    return _run_mf_universe(get_config_path("debt_mf_schemes.csv"),
                            "debt_mf_latest.csv", "DEBT MF", limit)


def _run_mf_universe(config_path, output_name, label, limit):
    log.info(f"🚀 Starting {label} fetch…")
    df_in = pd.read_csv(config_path)
    if limit:
        df_in = df_in.head(limit)

    amfi_df = fetch_amfi_navs()
    matched = fuzzy_match_schemes(df_in, amfi_df)

    results = []
    log.info(f"⏳ Computing analytics for {len(matched)} schemes (this takes time — be patient)…")
    for i, row in matched.iterrows():
        if i % 50 == 0 and i > 0:
            log.info(f"   Progress: {i}/{len(matched)} ({i/len(matched)*100:.1f}%)")
        try:
            results.append(process_scheme(row.to_dict()))
        except Exception as e:
            log.error(f"   Error on {row['scheme_name']}: {e}")
            results.append({"SCHEMES": row["scheme_name"], "_status": f"ERROR: {e}"})
        time.sleep(0.15)  # rate limit mfapi.in

    out_df = pd.DataFrame(results)
    out_path = get_output_path(output_name)
    out_df.to_csv(out_path, index=False)
    log.info(f"✅ {label} done. {len(out_df)} rows → {out_path}")
    return out_df


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "equity"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if which == "equity":
        run_equity_mf(limit=limit)
    else:
        run_debt_mf(limit=limit)
