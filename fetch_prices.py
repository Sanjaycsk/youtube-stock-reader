"""
Price Reader — PRODUCER (run on a RESIDENTIAL IP, e.g. your home PC).

Why this exists (same idea as fetch_transcripts.py):
  yfinance / Yahoo Finance is BLOCKED from Anthropic's cloud (a datacenter IP),
  so the InvestAI cloud routine can't fetch prices directly — it was scraping
  Google/Moneycontrol quotes instead, which sometimes returned a WRONG number
  (e.g. GOLDBEES logged at ~68 instead of ~117) and corrupted the grading.

  This script runs at HOME (where yfinance works), pulls clean end-of-day prices
  and technicals for the fixed 26-instrument universe, and writes them to
  data/prices.json. run_daily.ps1 pushes that file to the PUBLIC GitHub repo so
  the cloud routine can read ONE reliable source via the raw URL:

    https://raw.githubusercontent.com/Sanjaycsk/youtube-stock-reader/main/data/prices.json

Display prices (`close`, `recent_closes`) are AS-TRADED (unadjusted) so they
match what you see on your broker. Technicals (`dma20/50/200`, `rsi14`) are
computed on the split/dividend-ADJUSTED series so moving averages stay correct
across corporate actions. Both come from the same yfinance pull, so a value and
its next-day value are always consistent — which is what fixes the grading.

Run:
    python fetch_prices.py
Then commit + push (run_daily.ps1 does fetch + push in one step).
"""
from __future__ import annotations

import json
import pathlib
import sys
import warnings
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

BASE = pathlib.Path(__file__).resolve().parent
DATA_PATH = BASE / "data" / "prices.json"

# The FIXED universe — keep in sync with the cloud routine (agent/routine_prompt.md).
EQUITIES = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "TCS", "INFY", "BHARTIARTL", "ITC",
    "HINDUNILVR", "LT", "MARUTI", "SUNPHARMA", "TATASTEEL", "SBIN", "FEDERALBNK",
    "SUZLON", "TATAPOWER", "WAAREEENER", "NTPC", "ADANIENT", "BEL", "BHEL",
    "VEDL", "BPCL",
]
INDEX_ETF = ["GROWWN200"]
COMMODITY_ETFS = ["GOLDBEES", "SILVERBEES"]
UNIVERSE = EQUITIES + INDEX_ETF + COMMODITY_ETFS  # 26 instruments
BENCHMARK = {"NIFTY50": "^NSEI"}  # context only, not graded

RECENT_DAYS = 8  # how many recent closes to publish (enough to grade + eyeball trend)


def rsi(series: pd.Series, window: int = 14) -> float | None:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    v = out.dropna()
    return round(float(v.iloc[-1]), 1) if len(v) else None


def _last(series: pd.Series) -> float | None:
    s = series.dropna()
    return round(float(s.iloc[-1]), 2) if len(s) else None


def fetch_one(symbol: str, yf_symbol: str) -> dict | None:
    """Fetch ~1y daily data for one instrument and summarise it."""
    df = yf.download(yf_symbol, period="1y", auto_adjust=False, progress=False)
    if df is None or len(df) == 0:
        print(f"  ! {symbol}: no data")
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    raw = df["Close"].dropna()                       # as-traded (matches broker)
    adj = (df["Adj Close"] if "Adj Close" in df else df["Close"]).dropna()  # for technicals
    if len(raw) < 2:
        print(f"  ! {symbol}: too few rows")
        return None

    close = round(float(raw.iloc[-1]), 2)
    prev = round(float(raw.iloc[-2]), 2)
    change_pct = round((close - prev) / prev * 100, 2) if prev else None
    last_date = pd.to_datetime(raw.index[-1]).strftime("%Y-%m-%d")

    dma20 = _last(adj.rolling(20).mean())
    dma50 = _last(adj.rolling(50).mean())
    dma200 = _last(adj.rolling(200).mean())
    adj_last = float(adj.iloc[-1])

    def pct_vs(dma: float | None) -> float | None:
        return round((adj_last - dma) / dma * 100, 1) if dma else None

    recent = [
        {"date": pd.to_datetime(d).strftime("%Y-%m-%d"), "close": round(float(c), 2)}
        for d, c in raw.tail(RECENT_DAYS).items()
    ]

    return {
        "date": last_date,
        "close": close,
        "prev_close": prev,
        "change_pct": change_pct,
        "dma20": dma20,
        "dma50": dma50,
        "dma200": dma200,
        "pct_vs_dma50": pct_vs(dma50),
        "pct_vs_dma200": pct_vs(dma200),
        "rsi14": rsi(adj, 14),
        "high_52w": round(float(raw.max()), 2),
        "low_52w": round(float(raw.min()), 2),
        "recent_closes": recent,
    }


def main() -> None:
    today = date.today().isoformat()
    print(f"Fetching prices for {len(UNIVERSE)} instruments — {today}")

    instruments: dict[str, dict] = {}
    failed: list[str] = []
    for sym in UNIVERSE:
        data = fetch_one(sym, f"{sym}.NS")
        if data:
            instruments[sym] = data
            print(f"  ok {sym}: close {data['close']} ({data['date']})")
        else:
            failed.append(sym)

    benchmarks: dict[str, dict] = {}
    for name, ysym in BENCHMARK.items():
        # ^NSEI has no .NS suffix, so fetch it directly rather than via fetch_one.
        try:
            df = yf.download(ysym, period="1y", auto_adjust=False, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            c = df["Close"].dropna()
            if len(c):
                benchmarks[name] = {
                    "date": pd.to_datetime(c.index[-1]).strftime("%Y-%m-%d"),
                    "close": round(float(c.iloc[-1]), 2),
                    "change_pct": round((float(c.iloc[-1]) - float(c.iloc[-2])) / float(c.iloc[-2]) * 100, 2)
                    if len(c) > 1 else None,
                }
        except Exception as exc:
            print(f"  ! benchmark {name}: {exc}")

    payload = {
        "last_updated": today,
        "last_updated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance (Yahoo) EOD — as-traded close; technicals on adjusted series",
        "instrument_count": len(instruments),
        "failed": failed,
        "note": (
            "Read prices FROM HERE, not from web scraping. 'close' is the latest "
            "as-traded close (Ref Price). Grade a prior call with 'recent_closes'. "
            "DMAs/RSI are adjusted for splits. If a symbol is missing/stale, fall "
            "back to a web quote for just that one."
        ),
        "instruments": instruments,
        "benchmarks": benchmarks,
    }

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nWrote {DATA_PATH.name}: {len(instruments)}/{len(UNIVERSE)} instruments"
        f"{' (failed: ' + ', '.join(failed) + ')' if failed else ''}. last_updated={today}"
    )


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    main()
