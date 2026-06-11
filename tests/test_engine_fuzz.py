"""Property-based fuzzing of the backtest engine with runtime invariants on.

Fixed-config tests (tests/test_regression_guards.py) pin specific points in
the config space; this module samples the space. Each example generates a
small random-but-valid synthetic dataset (one underlying, a handful of put
contracts) plus a random engine config, runs the engine with
``assert_invariants = True``, and checks that:

1. ``run()`` does not raise — the engine's own cash-flow/valuation
   invariants surface as exceptions, so a clean run *is* the property;
2. the balance output is structurally sane (non-empty, finite, monotonic);
3. total capital never goes meaningfully negative (long-only puts);
4. the first balance row equals the initial capital.

Data quirks deliberately exercised:
- ``adjClose < close`` (dividend-adjusted series) — exercises the
  unadjusted-intrinsic valuation path (the class-B adjClose bug);
- contracts whose quotes stop appearing after expiration — exercises the
  intrinsic-value fallback for missing quotes;
- external budget modes with entry filters that may or may not fill —
  exercises the budget clawback path (the class-A phantom-money bug).
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from options_portfolio_backtester import BacktestEngine, Stock
from options_portfolio_backtester.core.types import Direction, OptionType
from options_portfolio_backtester.data.providers import (
    HistoricalOptionsData,
    TiingoData,
)
from options_portfolio_backtester.execution.cost_model import NoCosts
from options_portfolio_backtester.execution.fill_model import MarketAtBidAsk
from options_portfolio_backtester.strategy.strategy import Strategy
from options_portfolio_backtester.strategy.strategy_leg import StrategyLeg

UNDERLYING = "XYZ"
INITIAL_CAPITAL = 1_000_000

STOCK_COLUMNS = [
    "symbol", "date", "open", "close", "high", "low", "volume",
    "adjClose", "adjHigh", "adjLow", "adjOpen", "adjVolume",
    "divCash", "splitFactor",
]

OPTION_COLUMNS = [
    "underlying", "underlying_last", "optionroot", "type", "expiration",
    "quotedate", "strike", "last", "bid", "ask", "volume", "openinterest",
    "impliedvol", "delta", "gamma", "theta", "vega", "optionalias",
]

_price = st.floats(min_value=20.0, max_value=200.0,
                   allow_nan=False, allow_infinity=False)
_unit = st.floats(min_value=0.0, max_value=1.0,
                  allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# Synthetic dataset generation
# ---------------------------------------------------------------------------

@st.composite
def datasets(draw) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate (stocks_df, options_df) for one underlying.

    Invariants the engine *requires* of its input (and which we therefore
    guarantee rather than fuzz): the option quote date set equals the stock
    date set, bid <= ask, strike > 0, and every leg schema matches the data
    schema.
    """
    n_days = draw(st.integers(min_value=5, max_value=15))
    start_offset = draw(st.integers(min_value=0, max_value=2500))
    start = pd.Timestamp("2015-01-05") + pd.Timedelta(days=start_offset)
    dates = pd.bdate_range(start, periods=n_days)
    last_date = dates[-1]

    closes = [round(draw(_price), 2) for _ in range(n_days)]
    # adjClose <= close simulates dividend adjustment; valuing intrinsic
    # against adjClose instead of close was a real (class-B) bug.
    adj_factors = [draw(st.floats(min_value=0.7, max_value=1.0,
                                  allow_nan=False)) for _ in range(n_days)]

    stock_rows = []
    for date, close, f in zip(dates, closes, adj_factors):
        adj = round(close * f, 4)
        stock_rows.append({
            "symbol": UNDERLYING,
            "date": date.strftime("%Y-%m-%d"),
            "open": close, "close": close, "high": close, "low": close,
            "volume": 1000,
            "adjClose": adj, "adjHigh": adj, "adjLow": adj, "adjOpen": adj,
            "adjVolume": 1000,
            "divCash": 0.0, "splitFactor": 1.0,
        })
    stocks_df = pd.DataFrame(stock_rows, columns=STOCK_COLUMNS)

    # 1..4 put contracts, each with a fixed strike/expiration across days.
    n_contracts = draw(st.integers(min_value=1, max_value=4))
    contracts = []
    for i in range(n_contracts):
        strike_mult = draw(st.floats(min_value=0.3, max_value=1.2,
                                     allow_nan=False))
        strike = max(5.0, round(closes[0] * strike_mult / 5.0) * 5.0)
        if i == 0:
            exp_offset = draw(st.integers(min_value=10, max_value=60))
            # The engine asserts option dates == stock dates, so at least one
            # contract must quote on every trading day.
            expiration = max(dates[0] + pd.Timedelta(days=exp_offset),
                             last_date)
        else:
            # Later contracts are biased toward expiring mid-window: their
            # rows are dropped after expiration, exercising the intrinsic
            # fallback for positions whose quotes disappear.
            exp_offset = draw(st.integers(min_value=10, max_value=25))
            expiration = dates[0] + pd.Timedelta(days=exp_offset)
        delta = round(draw(st.floats(min_value=-0.95, max_value=-0.01,
                                     allow_nan=False)), 4)
        noise = draw(st.floats(min_value=0.0, max_value=2.0, allow_nan=False))
        spread = draw(st.floats(min_value=0.05, max_value=0.5,
                                allow_nan=False))
        contracts.append((strike, expiration, delta, noise, spread))

    option_rows = []
    for date, close in zip(dates, closes):
        for strike, expiration, delta, noise, spread in contracts:
            if date > expiration:
                continue  # contract gone after expiry: intrinsic fallback
            root = f"{UNDERLYING}{expiration:%y%m%d}P{int(round(strike * 1000)):08d}"
            intrinsic = max(0.0, strike - close)
            bid = round(max(0.05, intrinsic + noise), 2)
            ask = round(bid + spread, 2)
            option_rows.append({
                "underlying": UNDERLYING,
                "underlying_last": close,
                "optionroot": root,
                "type": "put",
                "expiration": expiration.strftime("%Y-%m-%d"),
                "quotedate": date.strftime("%Y-%m-%d"),
                "strike": strike,
                "last": bid,
                "bid": bid,
                "ask": ask,
                "volume": 100,
                "openinterest": 50,
                "impliedvol": 0.2,
                "delta": delta,
                "gamma": 0.01,
                "theta": -0.02,
                "vega": 0.05,
                "optionalias": "",
            })
    options_df = pd.DataFrame(option_rows, columns=OPTION_COLUMNS)
    return stocks_df, options_df


# ---------------------------------------------------------------------------
# Engine config generation
# ---------------------------------------------------------------------------

@st.composite
def configs(draw) -> dict:
    alloc = draw(st.sampled_from([
        {"stocks": 0.6, "options": 0.3, "cash": 0.1},
        {"stocks": 1.0, "options": 0.0, "cash": 0.0},
    ]))
    budget_mode = draw(st.sampled_from(["none", "per_rebalance", "annual"]))
    if budget_mode == "per_rebalance":
        budget = draw(st.floats(min_value=0.01, max_value=0.2,
                                allow_nan=False))
    elif budget_mode == "annual":
        budget = draw(st.floats(min_value=0.01, max_value=0.1,
                                allow_nan=False))
    else:
        budget = None
    check_exits_daily = draw(st.booleans())
    return {
        "allocation": alloc,
        "budget_mode": budget_mode,
        "budget": budget,
        "check_exits_daily": check_exits_daily,
        # Only meaningful with daily exit checks.
        "rebalance_stocks_on_exit": (
            check_exits_daily and draw(st.booleans())
        ),
        "entry_dte_min": draw(st.integers(min_value=1, max_value=5)),
        # None = no delta band on entry.
        "entry_delta_max": draw(st.sampled_from([None, -0.05, -0.30])),
        "exit_dte": draw(st.integers(min_value=1, max_value=30)),
        "profit_pct": draw(st.sampled_from([math.inf])
                           | st.floats(min_value=0.5, max_value=5.0,
                                       allow_nan=False)),
    }


# ---------------------------------------------------------------------------
# Engine construction
# ---------------------------------------------------------------------------

def _buy_put_strategy(schema, cfg) -> Strategy:
    strat = Strategy(schema)
    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT,
                      direction=Direction.BUY)
    entry = ((schema.underlying == UNDERLYING)
             & (schema.dte >= cfg["entry_dte_min"]))
    if cfg["entry_delta_max"] is not None:
        entry = entry & (schema.delta <= cfg["entry_delta_max"])
    leg.entry_filter = entry
    leg.exit_filter = schema.dte <= cfg["exit_dte"]
    strat.add_legs([leg])
    if not math.isinf(cfg["profit_pct"]):
        strat.add_exit_thresholds(profit_pct=cfg["profit_pct"])
    return strat


def _build_engine(tmpdir: str, stocks_df: pd.DataFrame,
                  options_df: pd.DataFrame, cfg: dict) -> BacktestEngine:
    stocks_path = Path(tmpdir) / "stocks.csv"
    options_path = Path(tmpdir) / "options.csv"
    stocks_df.to_csv(stocks_path, index=False)
    options_df.to_csv(options_path, index=False)

    stocks_data = TiingoData(str(stocks_path))
    options_data = HistoricalOptionsData(str(options_path))

    eng = BacktestEngine(
        cfg["allocation"],
        initial_capital=INITIAL_CAPITAL,
        cost_model=NoCosts(),
        fill_model=MarketAtBidAsk(),
    )
    eng.stocks = [Stock(UNDERLYING, 1.0)]
    eng.stocks_data = stocks_data
    eng.options_data = options_data
    eng.options_strategy = _buy_put_strategy(options_data.schema, cfg)

    if cfg["budget_mode"] == "per_rebalance":
        eng.options_budget_pct = cfg["budget"]
    elif cfg["budget_mode"] == "annual":
        eng.options_budget_annual_pct = cfg["budget"]
    eng.rebalance_stocks_on_exit = cfg["rebalance_stocks_on_exit"]
    eng.assert_invariants = True  # the point of this module
    return eng


# ---------------------------------------------------------------------------
# The fuzz test
# ---------------------------------------------------------------------------

class TestEngineFuzz:

    @given(data=datasets(), cfg=configs())
    @settings(
        max_examples=30,
        deadline=None,
        derandomize=True,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.data_too_large,
        ],
    )
    def test_random_config_passes_runtime_invariants(self, data, cfg):
        stocks_df, options_df = data
        with tempfile.TemporaryDirectory() as tmpdir:
            eng = _build_engine(tmpdir, stocks_df, options_df, cfg)
            # Property 1: a clean run. The engine's cash-flow and valuation
            # invariants (assert_invariants=True) raise on violation, so any
            # exception here is a finding, not a flake.
            eng.run(rebalance_freq=1, rebalance_unit="BMS",
                    check_exits_daily=cfg["check_exits_daily"])

        # Property 2: structurally sane balance.
        bal = eng.balance
        assert bal is not None and len(bal) > 0, "empty balance"
        tc = bal["total capital"].to_numpy(dtype=float)
        assert np.isfinite(tc).all(), (
            f"non-finite total capital: {tc[~np.isfinite(tc)][:5]}"
        )
        assert bal.index.is_monotonic_increasing, "balance index not monotonic"

        # Property 3: long-only puts can't take the portfolio below zero
        # (beyond float dust).
        assert (tc >= -1.0).all(), f"negative total capital: min={tc.min()}"

        # Property 4: the first balance row is the initial capital.
        assert math.isclose(tc[0], INITIAL_CAPITAL, rel_tol=1e-6), (
            f"first balance row {tc[0]} != initial capital {INITIAL_CAPITAL}"
        )
