#!/usr/bin/env python3
"""Unified data fetch script for the options backtester.

Downloads stock and options data, converts to backtester CSV formats,
and aligns dates between datasets.

Download priority (for each symbol):
  1. Self-hosted GitHub Release (lambdaclass/options_backtester data-v1)
  2. philippdubach/options-data CDN — 104 symbols
  3. philippdubach/options-dataset-hist — SPY/IWM/QQQ underlying prices
  4. yfinance (last resort, stocks only)

Usage:
    python scripts/fetch_data.py all --symbols SPY --start 2020-01-01 --end 2023-01-01
    python scripts/fetch_data.py stocks --symbols SPY --start 2020-01-01 --end 2023-01-01
    python scripts/fetch_data.py options --symbols SPY --start 2020-01-01 --end 2023-01-01
    python scripts/fetch_data.py all --symbols SPY --start 2020-01-01 --end 2023-01-01 --update
"""

import argparse
import shutil
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

# Data lives in <repo>/data regardless of where this script lives.
BASE_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DIR = BASE_DIR / "raw"
PROCESSED_DIR = BASE_DIR / "processed"

# Self-hosted data on GitHub Releases (primary, canonical source).
# This is the source we pin reproductions to; fallbacks below give different
# bytes and are only consulted when --allow-fallback is passed.
RELEASE_URL = "https://github.com/lambdaclass/options_backtester/releases/download/data-v1"

# Canonical SHA-256 hashes for files served from RELEASE_URL. When the
# downloaded file's hash does not match what is recorded here, the
# downloader prints a warning so the user can decide whether to keep
# stale-but-reproducible bytes or accept a new canonical version. This
# is what gives reproducibility a name: pin the hash, you pin the result.
CANONICAL_HASHES = {
    "SPY_options.parquet":    "a7152991b45b81f090f970e945bf88def8093b8ecb9b250e9891cb6d88041f0a",
    "SPY_underlying.parquet": "847e60a441eb10969d87cd4a6da604257b782d9076168f68d5730b84096c79db",
}

# Fallback sources. These give different bytes than the canonical release
# and are only consulted when --allow-fallback is passed on the command
# line. Default behaviour is to fail loudly if the canonical source is
# unreachable rather than silently substitute.
OPTIONS_DATA_URL = "https://static.philippdubach.com/data/options"
HIST_REPO_RAW = "https://github.com/philippdubach/options-dataset-hist/raw/main/data"
HIST_SYMBOLS = {"SPY", "IWM", "QQQ"}

# Module-level toggle, set by main() from the CLI flag.
ALLOW_FALLBACK = False


def _verify_canonical_hash(dest, expected_hash):
    """Compare the downloaded file's SHA-256 to the canonical hash and
    print a warning if it differs. Does not delete or refuse the file;
    callers decide what to do with mismatches."""
    import hashlib
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    got = h.hexdigest()
    if got != expected_hash:
        print(
            f"  WARNING: hash mismatch for {dest.name}:\n"
            f"    expected {expected_hash}\n"
            f"    got      {got}\n"
            f"  The canonical release may have been updated. If you need "
            f"bit-for-bit reproducibility against a published article, "
            f"check the article's pinned hash.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download(url, dest, force=False):
    """Download url to dest. Returns dest on success, None on failure."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        print(f"  Using cached {dest}")
        return dest

    print(f"  Downloading {url} ...")
    try:
        req = Request(url, headers={"User-Agent": "options-backtester/1.0"})
        with urlopen(req) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
        print(f"  Saved to {dest}")
    except Exception as e:
        print(f"  Error: {e}", file=sys.stderr)
        if dest.exists():
            dest.unlink()
        return None
    return dest


def download_options_parquet(symbol, force=False):
    """Download options parquet. Priority: GitHub Release (canonical) >
    options-data CDN (only if --allow-fallback was passed)."""
    sym = symbol.upper()

    # 1. Self-hosted GitHub Release (canonical source)
    fname = f"{sym}_options.parquet"
    dest = RAW_DIR / "release" / fname
    url = f"{RELEASE_URL}/{fname}"
    result = _download(url, dest, force)
    if result is not None:
        if fname in CANONICAL_HASHES:
            _verify_canonical_hash(result, CANONICAL_HASHES[fname])
        return result

    if not ALLOW_FALLBACK:
        print(
            f"  Canonical source for {sym} options is unreachable. "
            f"Pass --allow-fallback to attempt the options-data CDN instead "
            f"(returns different bytes; not pinned to any article reproduction).",
            file=sys.stderr,
        )
        return None

    # 2. options-data CDN (fallback)
    dest = RAW_DIR / "options-data" / sym / "options.parquet"
    url = f"{OPTIONS_DATA_URL}/{sym.lower()}/options.parquet"
    return _download(url, dest, force)


def download_underlying(symbol, force=False):
    """Download underlying prices.

    Priority: GitHub Release > options-dataset-hist > options-data > None (caller falls back to yfinance).
    """
    sym = symbol.upper()

    # 1. Self-hosted GitHub Release
    dest = RAW_DIR / "release" / f"{sym}_underlying.parquet"
    url = f"{RELEASE_URL}/{sym}_underlying.parquet"
    result = _download(url, dest, force)
    if result is not None:
        df = pd.read_parquet(result)
        if not df.empty:
            return result
        print(f"  Warning: release underlying empty for {sym}")

    # 2. options-dataset-hist has proper underlying for SPY/IWM/QQQ
    if sym in HIST_SYMBOLS:
        dest = RAW_DIR / "options-dataset-hist" / sym / "underlying_prices.parquet"
        url = f"{HIST_REPO_RAW}/parquet_{sym.lower()}/underlying_prices.parquet"
        result = _download(url, dest, force)
        if result is not None:
            df = pd.read_parquet(result)
            if not df.empty:
                return result
            print(f"  Warning: options-dataset-hist underlying empty for {sym}")

    # 3. options-data underlying
    dest = RAW_DIR / "options-data" / sym / "underlying.parquet"
    url = f"{OPTIONS_DATA_URL}/{sym.lower()}/underlying.parquet"
    result = _download(url, dest, force)
    if result is not None:
        df = pd.read_parquet(result)
        if not df.empty:
            return result
        print(f"  Warning: options-data underlying empty for {sym}")

    return None


# ---------------------------------------------------------------------------
# Underlying price reading
# ---------------------------------------------------------------------------

def read_underlying_prices(symbol, und_path, start, end):
    """Read underlying parquet and return (date, close) DataFrame for joining."""
    und = pd.read_parquet(und_path)
    und["date"] = pd.to_datetime(und["date"])
    und = und[(und["date"] >= start) & (und["date"] <= end)]
    if und.empty:
        return None
    return und[["date", "close"]].rename(columns={"close": "underlying_last"})


def underlying_to_tiingo(symbol, und_path, start, end):
    """Convert an underlying.parquet to Tiingo-format DataFrame."""
    und = pd.read_parquet(und_path)
    und["date"] = pd.to_datetime(und["date"])
    und = und[(und["date"] >= start) & (und["date"] <= end)]

    if und.empty:
        return pd.DataFrame()

    ratio = und["adjusted_close"] / und["close"]

    return pd.DataFrame({
        "symbol": symbol,
        "date": und["date"].values,
        "close": und["close"].values,
        "high": und["high"].values,
        "low": und["low"].values,
        "open": und["open"].values,
        "volume": und["volume"].values,
        "adjClose": und["adjusted_close"].values,
        "adjHigh": (und["high"] * ratio).values,
        "adjLow": (und["low"] * ratio).values,
        "adjOpen": (und["open"] * ratio).values,
        "adjVolume": und["volume"].values,
        "divCash": und["dividend_amount"].values,
        "splitFactor": und["split_coefficient"].values,
    })


def fetch_yfinance(symbol, start, end):
    """Fetch one symbol via yfinance (last resort)."""
    try:
        import yfinance as yf
    except ImportError:
        print(f"  yfinance not installed, cannot fetch {symbol}", file=sys.stderr)
        return pd.DataFrame()

    print(f"  Last resort: fetching {symbol} from yfinance...")
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=str(start.date()), end=str(end.date()), auto_adjust=False)

    if df.empty:
        return pd.DataFrame()

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    ratio = df["Adj Close"] / df["Close"]

    return pd.DataFrame({
        "symbol": symbol,
        "date": df.index,
        "close": df["Close"].values,
        "high": df["High"].values,
        "low": df["Low"].values,
        "open": df["Open"].values,
        "volume": df["Volume"].values,
        "adjClose": df["Adj Close"].values,
        "adjHigh": (df["High"] * ratio).values,
        "adjLow": (df["Low"] * ratio).values,
        "adjOpen": (df["Open"] * ratio).values,
        "adjVolume": df["Volume"].values,
        "divCash": 0.0,
        "splitFactor": 1.0,
    })


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def fetch_options(symbols, start, end, output, force=False):
    """Download options parquets and convert to backtester CSV format."""
    frames = []

    for symbol in symbols:
        sym = symbol.upper()
        print(f"Fetching options for {sym}...")

        opt_path = download_options_parquet(sym, force)
        if opt_path is None:
            print(f"  Skipping {sym} options (download failed)", file=sys.stderr)
            continue

        opts = pd.read_parquet(opt_path)
        opts["date"] = pd.to_datetime(opts["date"])
        opts = opts[(opts["date"] >= start) & (opts["date"] <= end)]

        if opts.empty:
            print(f"  No options data for {sym} in [{start}, {end}]")
            continue

        # Get underlying close prices for underlying_last
        und_path = download_underlying(sym, force)
        und_prices = None
        if und_path is not None:
            und_prices = read_underlying_prices(sym, und_path, start, end)

        if und_prices is None:
            yf_df = fetch_yfinance(sym, start, end)
            if not yf_df.empty:
                und_prices = pd.DataFrame({
                    "date": pd.to_datetime(yf_df["date"]),
                    "underlying_last": yf_df["close"].values,
                })

        if und_prices is not None:
            opts = opts.merge(und_prices, on="date", how="left")
        else:
            opts["underlying_last"] = float("nan")

        # Last price: use column if present, else mid
        if "last" in opts.columns:
            opts["_last"] = opts["last"].fillna((opts["bid"] + opts["ask"]) / 2)
        else:
            opts["_last"] = (opts["bid"] + opts["ask"]) / 2

        out = pd.DataFrame({
            "underlying": sym,
            "underlying_last": opts["underlying_last"].values,
            "optionroot": opts["contract_id"].values,
            "type": opts["type"].values,
            "expiration": pd.to_datetime(opts["expiration"]).values,
            "quotedate": opts["date"].values,
            "strike": opts["strike"].values,
            "last": opts["_last"].values,
            "bid": opts["bid"].values,
            "ask": opts["ask"].values,
            "volume": opts["volume"].values,
            "openinterest": opts["open_interest"].values,
            "impliedvol": opts["implied_volatility"].values,
            "delta": opts["delta"].values,
            "gamma": opts["gamma"].values,
            "theta": opts["theta"].values,
            "vega": opts["vega"].values,
            "optionalias": opts["contract_id"].values,
        })
        frames.append(out)
        print(f"  {len(out)} option rows for {sym}")

    if not frames:
        print("No options data fetched.", file=sys.stderr)
        return None

    result = pd.concat(frames, ignore_index=True)
    result = result.sort_values(["quotedate", "underlying", "expiration", "strike", "type"])
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    # Also write the engine-ready parquet — same schema, ~5x smaller on disk,
    # ~30x faster to load via HistoricalOptionsData. CSV stays the default
    # interchange format; users who care about reload speed pass the
    # .parquet path to the engine instead.
    parquet_output = str(output).replace(".csv", ".parquet")
    if parquet_output != str(output):
        result.to_parquet(parquet_output, index=False)
        print(f"Wrote {len(result)} option rows to {output} and {parquet_output}")
    else:
        print(f"Wrote {len(result)} option rows to {output}")
    return result


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

def fetch_stocks(symbols, start, end, output, force=False):
    """Download stock data. Priority: options-dataset-hist > options-data > yfinance."""
    frames = []

    for symbol in symbols:
        sym = symbol.upper()
        print(f"Fetching stocks for {sym}...")

        und_path = download_underlying(sym, force)
        if und_path is not None:
            df = underlying_to_tiingo(sym, und_path, start, end)
            if not df.empty:
                source = "options-dataset-hist" if "options-dataset-hist" in str(und_path) else "options-data"
                frames.append(df)
                print(f"  {len(df)} stock rows for {sym} (from {source})")
                continue

        df = fetch_yfinance(sym, start, end)
        if not df.empty:
            frames.append(df)
            print(f"  {len(df)} stock rows for {sym} (from yfinance)")
        else:
            print(f"  No stock data for {sym}", file=sys.stderr)

    if not frames:
        print("No stock data fetched.", file=sys.stderr)
        return None

    result = pd.concat(frames, ignore_index=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)
    parquet_output = str(output).replace(".csv", ".parquet")
    if parquet_output != str(output):
        result.to_parquet(parquet_output, index=False)
    print(f"Wrote {len(result)} stock rows to {output}")
    return result


# ---------------------------------------------------------------------------
# Date alignment
# ---------------------------------------------------------------------------

def align_dates(stocks_path, options_path):
    """Align stock and option dates to their intersection."""
    stocks = pd.read_csv(stocks_path, parse_dates=["date"])
    options = pd.read_csv(options_path, parse_dates=["quotedate", "expiration"])

    stock_dates = set(stocks["date"].dt.normalize())
    option_dates = set(options["quotedate"].dt.normalize())
    shared = stock_dates & option_dates

    if not shared:
        print("Warning: no overlapping dates between stocks and options!", file=sys.stderr)
        return

    stocks_filtered = stocks[stocks["date"].dt.normalize().isin(shared)]
    options_filtered = options[options["quotedate"].dt.normalize().isin(shared)]

    stocks_filtered.to_csv(stocks_path, index=False)
    options_filtered.to_csv(options_path, index=False)

    # Keep the parquet twins in sync. The engine asserts stock/option date
    # alignment at run(), and parquet is the recommended fast load path —
    # leaving it unaligned makes every parquet-based run fail that assert.
    for path, df in ((stocks_path, stocks_filtered), (options_path, options_filtered)):
        pq = Path(path).with_suffix(".parquet")
        if pq.exists():
            df.to_parquet(pq, index=False)

    dropped_stock = len(stocks) - len(stocks_filtered)
    dropped_opt = len(options) - len(options_filtered)
    print(f"Aligned dates: {len(shared)} shared trading days")
    if dropped_stock:
        print(f"  Dropped {dropped_stock} stock rows without matching option dates")
    if dropped_opt:
        print(f"  Dropped {dropped_opt} option rows without matching stock dates")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch stock and options data for the backtester"
    )
    parser.add_argument(
        "command", nargs="?", default="all",
        choices=["all", "stocks", "options"],
        help="What to fetch (default: all)",
    )
    parser.add_argument(
        "--symbols", nargs="+", required=True,
        help="Ticker symbols (e.g. SPY IWM QQQ AAPL)",
    )
    parser.add_argument("--start", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--stocks-output", default="data/processed/stocks.csv",
        help="Stock CSV output path",
    )
    parser.add_argument(
        "--options-output", default="data/processed/options.csv",
        help="Options CSV output path",
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Re-download parquets to get latest data",
    )
    parser.add_argument(
        "--allow-fallback", action="store_true",
        help=(
            "If the canonical GitHub Release source is unreachable, fall back "
            "to the options-data CDN, the dataset-hist repo, or yfinance. "
            "Fallbacks return different bytes than the canonical source and "
            "break bit-for-bit reproducibility against published articles."
        ),
    )
    args = parser.parse_args()

    global ALLOW_FALLBACK
    ALLOW_FALLBACK = args.allow_fallback

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    force = args.update

    if args.command in ("all", "options"):
        fetch_options(args.symbols, start, end, args.options_output, force)

    if args.command in ("all", "stocks"):
        fetch_stocks(args.symbols, start, end, args.stocks_output, force)

    if args.command == "all":
        if Path(args.stocks_output).exists() and Path(args.options_output).exists():
            print("\nAligning dates...")
            align_dates(args.stocks_output, args.options_output)

    print("\nDone!")


if __name__ == "__main__":
    main()
