"""
test_setup.py
─────────────
Validates that all dependencies are installed and external data sources are
reachable. Run this AFTER `pip install -r requirements.txt` to confirm setup
before running the full pipeline.

Usage:
    python test_setup.py
"""
import sys
from pathlib import Path

def test_imports():
    print("─" * 60)
    print("TEST 1: Library imports")
    print("─" * 60)
    libs = ["pandas", "numpy", "yfinance", "openpyxl", "requests", "bs4"]
    all_ok = True
    for lib in libs:
        try:
            __import__(lib)
            print(f"  ✅ {lib}")
        except ImportError as e:
            print(f"  ❌ {lib} — {e}")
            all_ok = False
    return all_ok


def test_yfinance():
    print("\n" + "─" * 60)
    print("TEST 2: yfinance live data (RELIANCE.NS)")
    print("─" * 60)
    try:
        import yfinance as yf
        t = yf.Ticker("RELIANCE.NS")
        h = t.history(period="5d")
        if h.empty:
            print("  ❌ Got empty data — yfinance may be rate-limited")
            return False
        latest = h.iloc[-1]
        print(f"  ✅ Latest close: ₹{latest['Close']:.2f} on {h.index[-1].date()}")
        print(f"     Volume: {latest['Volume']:,.0f}")
        return True
    except Exception as e:
        print(f"  ❌ yfinance failed: {e}")
        return False


def test_amfi():
    print("\n" + "─" * 60)
    print("TEST 3: AMFI India NAV endpoint")
    print("─" * 60)
    try:
        import requests
        r = requests.get("https://www.amfiindia.com/spages/NAVAll.txt", timeout=20)
        if r.status_code == 200 and len(r.text) > 100000:
            line_count = len(r.text.split("\n"))
            print(f"  ✅ AMFI reachable — {len(r.text):,} bytes, {line_count:,} lines")
            return True
        print(f"  ❌ AMFI returned {r.status_code}")
        return False
    except Exception as e:
        print(f"  ❌ AMFI failed: {e}")
        return False


def test_mfapi():
    print("\n" + "─" * 60)
    print("TEST 4: MFAPI.in historical NAV")
    print("─" * 60)
    try:
        import requests
        # Scheme 100027 = Aditya Birla SL India GenNext Fund (verified working)
        r = requests.get("https://api.mfapi.in/mf/100027", timeout=15)
        if r.status_code == 200:
            data = r.json()
            if "data" in data and len(data["data"]) > 100:
                print(f"  ✅ MFAPI.in reachable — fund: {data.get('meta', {}).get('scheme_name', 'OK')[:60]}")
                print(f"     {len(data['data'])} NAV history entries")
                return True
        print(f"  ❌ MFAPI returned {r.status_code}")
        return False
    except Exception as e:
        print(f"  ❌ MFAPI failed: {e}")
        return False


def test_config_files():
    print("\n" + "─" * 60)
    print("TEST 5: Config files present")
    print("─" * 60)
    config_dir = Path(__file__).parent / "config"
    files = ["nifty500_companies.csv", "sp500_tickers.csv",
             "equity_mf_schemes.csv", "debt_mf_schemes.csv", "reit_invit.csv"]
    all_ok = True
    for f in files:
        p = config_dir / f
        if p.exists():
            import csv
            with open(p) as fh:
                rows = sum(1 for _ in csv.reader(fh)) - 1
            print(f"  ✅ {f} — {rows} rows")
        else:
            print(f"  ❌ {f} — MISSING")
            all_ok = False
    return all_ok


def main():
    print("\n🔧 PORTFOLIO AUTOMATION — SETUP VALIDATOR\n")
    results = [
        ("Library imports", test_imports()),
        ("yfinance (live data)", test_yfinance()),
        ("AMFI India NAV", test_amfi()),
        ("MFAPI.in historical NAV", test_mfapi()),
        ("Config files", test_config_files()),
    ]
    print("\n" + "═" * 60)
    print("SUMMARY")
    print("═" * 60)
    all_pass = True
    for name, passed in results:
        icon = "✅" if passed else "❌"
        print(f"  {icon} {name}")
        if not passed:
            all_pass = False
    print()
    if all_pass:
        print("🎉 All checks passed! Run:")
        print("     python update_portfolio_model.py --test")
        print("   for a 5-instrument-per-sheet trial run.")
    else:
        print("⚠️  Some checks failed. Fix issues above before running pipeline.")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
