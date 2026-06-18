"""
update_portfolio_model.py
─────────────────────────
MASTER ORCHESTRATOR — runs the full pipeline:
  1. Fetch Nifty 500 data
  2. Fetch S&P 500 data
  3. Fetch Equity MF data
  4. Fetch Debt MF data
  5. Fetch REIT/InvIT data
  6. Write everything back into the Excel workbook

Usage:
  python update_portfolio_model.py                    # full run, all sheets
  python update_portfolio_model.py --sheet nifty500   # just one sheet
  python update_portfolio_model.py --test             # small test run (5 rows each)

The output file is timestamped and saved to /output/
"""
from __future__ import annotations
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path

# Make src importable when running as script
sys.path.insert(0, str(Path(__file__).parent))

from src.utils import setup_logger, get_project_root, get_output_path
from src import fetch_nifty500, fetch_sp500, fetch_mutual_funds, fetch_reit_invit, update_excel

log = setup_logger("orchestrator")


def main():
    parser = argparse.ArgumentParser(description="Portfolio model auto-updater")
    parser.add_argument("--sheet", choices=["all", "nifty500", "sp500", "equity_mf", "debt_mf", "reit"],
                        default="all", help="Which sheet(s) to refresh")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: fetch only 5 instruments per sheet")
    parser.add_argument("--template", default="PERSONALISED_PORTFOLIO_ALLOCATION_MODEL_.xlsx",
                        help="Path to the Excel template")
    parser.add_argument("--skip-excel", action="store_true",
                        help="Skip the Excel write step (just produce CSVs)")
    args = parser.parse_args()

    limit = 5 if args.test else None
    start = time.time()
    log.info("=" * 70)
    log.info(f"🚀 PORTFOLIO MODEL UPDATE — started {datetime.now()}")
    log.info(f"   Mode: {args.sheet}  |  Test: {args.test}  |  Template: {args.template}")
    log.info("=" * 70)

    if args.sheet in ("all", "nifty500"):
        try:
            fetch_nifty500.run(limit=limit)
        except Exception as e:
            log.error(f"❌ Nifty 500 failed: {e}", exc_info=True)

    if args.sheet in ("all", "sp500"):
        try:
            fetch_sp500.run(limit=limit)
        except Exception as e:
            log.error(f"❌ S&P 500 failed: {e}", exc_info=True)

    if args.sheet in ("all", "equity_mf"):
        try:
            fetch_mutual_funds.run_equity_mf(limit=limit)
        except Exception as e:
            log.error(f"❌ Equity MF failed: {e}", exc_info=True)

    if args.sheet in ("all", "debt_mf"):
        try:
            fetch_mutual_funds.run_debt_mf(limit=limit)
        except Exception as e:
            log.error(f"❌ Debt MF failed: {e}", exc_info=True)

    if args.sheet in ("all", "reit"):
        try:
            fetch_reit_invit.run()
        except Exception as e:
            log.error(f"❌ REIT/InvIT failed: {e}", exc_info=True)

    # ─── Write back to Excel ─────────────────────────────────────────────────
    if not args.skip_excel:
        template_path = Path(args.template)
        if not template_path.exists():
            template_path = get_project_root() / args.template
        if template_path.exists():
            log.info("\n" + "=" * 70)
            log.info("📊 WRITING BACK TO EXCEL")
            log.info("=" * 70)
            try:
                output_file = update_excel.update_excel(str(template_path))
                log.info(f"\n🎉 SUCCESS — updated workbook at: {output_file}")
            except Exception as e:
                log.error(f"❌ Excel write failed: {e}", exc_info=True)
        else:
            log.warning(f"⚠️  Template file not found: {template_path}")
            log.warning("   CSV files are in /output — Excel merge skipped.")

    elapsed = time.time() - start
    log.info(f"\n⏱  Total time: {elapsed/60:.1f} minutes")


if __name__ == "__main__":
    main()
