# Portfolio Model Auto-Update Pipeline

Fully automated, real-time data refresh for your 5-sheet portfolio Excel model — **3,123 instruments** across Indian equities, US equities, mutual funds, and REITs.

---

## What this does

Every Sunday morning (or whenever you run it), this pipeline:

1. **Downloads live data** for all 498 Nifty 500 stocks, 503 S&P 500 stocks, 1,649 Equity MFs, 462 Debt MFs, and 11 REITs/InvITs
2. **Computes all technical indicators** (SMA50/200, ATR, Pivot Points, S1/S2/R1/R2, Trend, StopLoss, TargetPrice)
3. **Computes risk metrics** for mutual funds (Sharpe, Sortino, Mean, Std Dev) from 3-year NAV history
4. **Computes returns** across 15 periods (1 day → 25 years) for every mutual fund
5. **Writes everything back** into your Excel file, preserving formatting

---

## Quick Start (5 minutes)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Validate setup (checks all APIs are reachable)
python test_setup.py

# 3. Run a small test (5 instruments per sheet, ~2 minutes)
python update_portfolio_model.py --test

# 4. Full pipeline run (~45-60 minutes for 3,123 instruments)
python update_portfolio_model.py
```

Output Excel file: `output/PORTFOLIO_MODEL_UPDATED_YYYYMMDD_HHMMSS.xlsx`

---

## Project Structure

```
portfolio-automation/
├── README.md                       ← This file
├── requirements.txt                ← Python dependencies
├── .env.example                    ← Copy to .env for API keys (optional)
├── update_portfolio_model.py       ← MASTER orchestrator (run this)
├── test_setup.py                   ← Validates setup before first run
│
├── config/                         ← Your instrument universe
│   ├── nifty500_companies.csv      (498 companies)
│   ├── sp500_tickers.csv           (503 US tickers)
│   ├── equity_mf_schemes.csv       (1,649 schemes)
│   ├── debt_mf_schemes.csv         (462 schemes)
│   └── reit_invit.csv              (11 REITs/InvITs)
│
├── src/                            ← Core pipeline modules
│   ├── utils.py                    Logger, retry, paths
│   ├── fetch_nifty500.py           Indian equities
│   ├── fetch_sp500.py              US equities
│   ├── fetch_mutual_funds.py       Both MF universes (AMFI)
│   ├── fetch_reit_invit.py         REITs & InvITs
│   └── update_excel.py             Writes results back to Excel
│
├── .github/workflows/
│   └── weekly_update.yml           ← GitHub Actions weekly cron
│
├── output/                         ← Generated CSVs and updated Excel
└── logs/                           ← Pipeline run logs
```

---

## Data Sources

| Sheet | Source | Cost | Auth |
|---|---|---|---|
| Nifty 500 | yfinance (Yahoo Finance) | **Free** | None |
| S&P 500 | yfinance (Yahoo Finance) | **Free** | None |
| Equity MF | AMFI India + MFAPI.in | **Free** | None |
| Debt MF | AMFI India + MFAPI.in | **Free** | None |
| REIT/InvIT | yfinance | **Free** | None |

**Total cost for free pipeline: ₹0/month** (just hosting if you use GitHub Actions — also free).

---

## What gets fetched automatically vs. what needs manual updates

### ✅ Fully automated (refresh every Sunday)
- **All price data** (CMP, 52W H/L, OHLCV history)
- **All technical indicators** (SMA, ATR, Pivot, S1-S2, R1-R2, Trend, StopLoss, TargetPrice)
- **All mutual fund NAVs** and 15 period returns
- **Risk metrics** (Sharpe, Sortino, Mean, Std Dev) for all 2,111 MFs
- **Basic fundamentals** (P/E, P/B, ROE, growth rates) where Yahoo provides them
- **Intrinsic value** (DCF estimate for US stocks)
- **Fundamental & Technical View scores** for S&P 500

### ⚠️ Still needs manual quarterly updates
These fields aren't available via free APIs — they come from company filings:
- **REIT Occupancy Rate** (in investor presentations)
- **Distribution Per Unit** (quarterly announcement)
- **Free Cash Flow, Debt/Equity, Interest Coverage** for REITs (annual reports)

These are stored in `src/fetch_reit_invit.py` → `FUNDAMENTAL_OVERRIDES` dictionary. Update them once a quarter when REITs publish their filings.

---

## Running on a Schedule

### Option 1: GitHub Actions (Recommended — Free)

1. Push this entire folder to a GitHub repo (can be private)
2. The included `.github/workflows/weekly_update.yml` runs every Sunday 06:30 IST
3. Updated Excel is uploaded as a GitHub artifact (downloadable for 30 days)
4. You can also trigger manually from the GitHub "Actions" tab

### Option 2: Linux/Mac Cron

```bash
# Edit crontab
crontab -e

# Add this line (runs every Sunday at 6:30 AM)
30 6 * * 0 cd /path/to/portfolio-automation && /usr/bin/python3 update_portfolio_model.py
```

### Option 3: Windows Task Scheduler

Create a basic task that runs:
```
C:\Python311\python.exe C:\path\to\portfolio-automation\update_portfolio_model.py
```

---

## Command-line Usage

```bash
# Run everything (full universe)
python update_portfolio_model.py

# Run just one sheet
python update_portfolio_model.py --sheet nifty500
python update_portfolio_model.py --sheet sp500
python update_portfolio_model.py --sheet equity_mf
python update_portfolio_model.py --sheet debt_mf
python update_portfolio_model.py --sheet reit

# Test mode (5 instruments per sheet — quick validation)
python update_portfolio_model.py --test

# Custom template path
python update_portfolio_model.py --template /path/to/your.xlsx

# Skip the Excel write step (just generate CSVs)
python update_portfolio_model.py --skip-excel
```

---

## Run Times (approximate)

| Operation | Instruments | Time | Notes |
|---|---|---|---|
| Nifty 500 fetch | 498 | ~12 min | 1.5s per stock incl. fundamentals |
| S&P 500 fetch | 503 | ~12 min | Same throughput as Nifty |
| AMFI master download | 1 file | ~5 sec | One ~1MB file with all NAVs |
| Equity MF analytics | 1,649 | ~25 min | History + Sharpe for each |
| Debt MF analytics | 462 | ~8 min | Same per-fund time as Equity |
| REIT fetch | 11 | ~30 sec | Tiny universe |
| Excel write-back | All | ~10 sec | One-time merge |
| **TOTAL** | **3,123** | **~55–65 min** | Once per week |

Tip: Run individual sheets if you only need a partial refresh — much faster.

---

## Architecture (Council Report Recommendation Implemented)

```
┌─────────────────────────────────────────────────────────────┐
│  WEEKLY CRON (GitHub Actions / Linux cron / Task Scheduler) │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — INGESTION (one Python module per sheet)          │
│    fetch_nifty500.py    → yfinance (Indian equities)        │
│    fetch_sp500.py       → yfinance (US equities)            │
│    fetch_mutual_funds.py → AMFI + MFAPI.in (all MFs)        │
│    fetch_reit_invit.py  → yfinance (REITs/InvITs)           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — ANALYTICS (pure pandas, deterministic)           │
│    Technical: SMA, ATR, Pivot, S1/S2/R1/R2, StopLoss        │
│    Risk:      Sharpe, Sortino, Mean, Std Dev (3yr daily)    │
│    Returns:   1D, 7D, 15D, 30D, 3M, 6M, 1Y → 25Y            │
│    Valuation: DCF intrinsic value, Fund/Tech View scores    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — STORAGE (per-sheet CSVs)                         │
│    output/nifty500_latest.csv                               │
│    output/sp500_latest.csv                                  │
│    output/equity_mf_latest.csv                              │
│    output/debt_mf_latest.csv                                │
│    output/reit_invit_latest.csv                             │
│                                                             │
│  Each CSV includes _fetched_at, _status columns for audit   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4 — EXCEL WRITE-BACK (preserves formatting)          │
│    output/PORTFOLIO_MODEL_UPDATED_<timestamp>.xlsx          │
│    + auto-generated UPDATE_LOG sheet with metadata          │
└─────────────────────────────────────────────────────────────┘
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `yfinance` returns empty data | Rate limited (too many requests) | Pipeline includes 0.3s delay. If still failing, increase `time.sleep(0.5)` in fetcher files |
| Many "NO_AMFI_MATCH" rows for MFs | Scheme name in your Excel doesn't match AMFI naming | Inspect `output/equity_mf_latest.csv` — check the `_match_score` column. Edit scheme name in `config/equity_mf_schemes.csv` to match AMFI's official name |
| Some stocks return NO_DATA | Yahoo's ticker symbol differs from your company name | Add the mapping to `MANUAL_TICKER_MAP` in `src/fetch_nifty500.py` |
| Excel file locked when writing | Excel has the file open | Close the Excel app before running, OR the script saves to a timestamped new file (won't conflict) |
| Pipeline crashes mid-run | Network issue or one bad ticker | The retry decorator handles transient failures. Individual stock errors log a warning and continue — check `logs/YYYYMMDD_pipeline.log` |

---

## Cost Breakdown (Indian context, monthly)

| Component | Service | ₹/month | Notes |
|---|---|---:|---|
| Price data — India | yfinance | 0 | Yahoo Finance, free |
| Price data — US | yfinance | 0 | Same |
| MF NAVs | AMFI India | 0 | Official regulator source |
| MF historical NAV | MFAPI.in | 0 | Community API, very reliable |
| Compute / hosting | GitHub Actions | 0 | 2,000 free minutes/month |
| Email/Slack alerts | Sentry.io free | 0 | Optional |
| **TOTAL** | | **₹0** | Bootstrap phase |

### Optional paid upgrades (only if needed)
| Add-on | Cost | When to consider |
|---|---:|---|
| Financial Modeling Prep (US) | ₹3,500/mo | If you need PEG, deeper fundamentals for S&P 500 |
| Screener.in Pro API | ₹1,500/mo | If you need FII/DII holding changes, 5yr variance |
| Morningstar India | ₹2-5L/year | Only if SEBI compliance demands audited MF analytics |

---

## Compliance Reminder

⚠️ Your Excel has an **"IS RECOMMENDED"** column. If you use this in client-facing advice, you may need SEBI Investment Adviser registration. **Get this reviewed by a SEBI-registered compliance officer before deploying for live client use.**

The pipeline includes audit columns (`_fetched_at`, `_status`) on every row so you can prove when and from where each data point was sourced — useful for both compliance and debugging.

---

## Next Steps (After Pipeline is Stable)

The council report recommended these as Phase 2 enhancements:

1. **Migrate from CSV → PostgreSQL** — store historical data, enable querying by date
2. **Add client-portfolio overlay** — match each client's holdings to the updated dataset, generate per-client drift reports
3. **WhatsApp / email alerts** — notify when a holding crosses StopLoss or 52W Low
4. **PDF report generator** — auto-generate weekly client summaries
5. **Add INR/USD FX rate** — convert S&P 500 metrics to INR-effective returns for Indian investors

All of these can be built incrementally on top of the working CSV outputs.

---

## Support

Logs are written to `logs/YYYYMMDD_pipeline.log`. Each row in every output CSV has a `_status` column showing OK / NO_DATA / ERROR with the reason.

For any sheet, you can re-run that sheet alone without affecting the others:
```bash
python update_portfolio_model.py --sheet nifty500
```
