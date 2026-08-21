Options Portfolio Backtester
============================

Backtest options strategies with realistic execution, Greeks-aware risk management, and contract-level inventory. Also handles equities and multi-asset portfolios. Built on a Rust compute core.


## My additions:
1) Fixed backcalculation errors at rebalancing
2) Roll and calendar+roll scheduling schemes. Goal is to avoid unocovered periods.
3) Plot with number of contracts held day-by-day

### TODO
1) Incremental purchasing vs buy-and-hold
2) Cost of margin if overlay is bought at margin
3) German taxes
4) Add SPX and XSP
5) 

### ⚠️ Known data traps

**Greeks and IV are unusable before 2010.** In `data/processed/options.parquet`
the 2008-2009 rows carry a broken implied vol, and delta/gamma/theta/vega are
derived from it, so they are self-consistently wrong. Median IV is 0.025 in 2008
and 0.034 in 2009 (vs ~0.20-0.30 from 2010 on); 56% of 2008 rows report IV below
5%, and 37% have vega and gamma at exactly zero. Concretely, on 2008-11-20 —
VIX near 80 — the SPY Dec-08 76-strike put is stored with `impliedvol=0.01488`
and `delta=-0.94589`, while its own stored price of 7.00/7.20 implies ~80% vol
and a delta near -0.47.

*Prices (bid/ask) are fine* — only the vol-derived fields are affected. So a
strike-based strategy is unaffected, but anything selecting on delta
(`NearestDelta`, `deep_otm_put`, a `schema.delta` entry filter) or gating on
`MaxDelta`/`MaxVega` will silently produce nonsense **exactly across the GFC** —
the window that dominates tail-hedge results. No error is raised.

This includes `deep_otm_put`, the canonical Spitznagel preset used in the
quickstart below, which filters on `delta in [-0.10, -0.02]` and sorts by it.
Share of DTE 90-180 puts passing that delta band, by year:

| 2008 | 2009 | 2010 | 2014 | 2020 | 2024 |
|------|------|------|------|------|------|
| 2.24% | 1.61% | 14.4% | 20.6% | 18.5% | 25.0% |

~10x fewer candidates in 2008-2009 — the preset is starved precisely when the
hedge is supposed to pay. Select on strike (e.g. `strike <= underlying_last *
0.60`) if the sample includes 2008-2009.

**bid_size / ask_size are dropped by `fetch_data.py`.** They exist in
`data/raw/release/*.parquet` but not in `data/processed/`, so the processed file
cannot answer "was this fill size actually available". Do not use `openinterest`
as a substitute: it counts positions already open, not liquidity, since a market
maker writes a new contract rather than sourcing an existing one. Real example —
`SPY200417P00194000` on 2020-01-02 shows `open_interest=2` while `ask_size` was
3756. They are also unusable before 2012 (87% of 2008 rows carry zero sizes).

**<p style="text-align:center"> ======== ORIGINAL README FROM HERE ONWARD ======== </p>**


## Get started

### Install

With Nix:
```shell
nix develop
```

Without Nix (Python >= 3.12):
```shell
python -m venv .venv && source .venv/bin/activate
make install-dev
```

### Get data

```shell
python scripts/fetch_data.py all --symbols SPY
```

Downloads SPY stock prices and options chains to `data/processed/`. Supports 104+ symbols. See [`data/README.md`](data/README.md) for details.

The canonical SPY parquets are pinned by SHA-256 in `scripts/fetch_data.py`:

- `SPY_options.parquet`: `a7152991b45b81f090f970e945bf88def8093b8ecb9b250e9891cb6d88041f0a`
- `SPY_underlying.parquet`: `847e60a441eb10969d87cd4a6da604257b782d9076168f68d5730b84096c79db`

A hash mismatch warning means the source has been updated; published-article reproductions are pinned to the hashes above. Provenance and redistribution posture: [`data/DATA_NOTICE.md`](data/DATA_NOTICE.md). Verify any copy with `python scripts/fetch_data.py verify`. Pass `--allow-fallback` to permit the secondary mirrors (options-data CDN / yfinance) when the canonical source is unreachable. Fallbacks return different bytes and break bit-for-bit reproducibility.

### Run your first backtest

```python
from options_portfolio_backtester import (
    BacktestEngine, Stock,
    HistoricalOptionsData, TiingoData,
    deep_otm_put,
)

# Load data. Parquet is ~5x smaller on disk and ~30x faster to load than CSV.
options_data = HistoricalOptionsData("data/processed/options.parquet")
stocks_data = TiingoData("data/processed/stocks.csv")

# Build the strategy with a canonical preset — the Spitznagel tail-hedge leg
strategy = deep_otm_put(options_data.schema, "SPY")

# Configure the framing: 100% SPY + 0.5% external put budget (Spitznagel)
engine = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0},
                       initial_capital=1_000_000)
engine.use_external_budget(annual_pct=0.005)
engine.stocks = [Stock("SPY", 1.0)]
engine.stocks_data = stocks_data
engine.options_data = options_data
engine.options_strategy = strategy
engine.run(rebalance_freq=1, rebalance_unit="BMS")

# Inspect the results — the dataclass bundles balance, trades, config, and engine version
results = engine.get_results()
print(results.summary())
# {'annual_return': 13.5, 'max_drawdown': -46.4, 'sharpe': 0.72, 'trades': 327, ...}
```

The AQR / allocation-reducing framing is one helper away:

```python
engine.use_allocation(stocks=0.99, options=0.01, cash=0.0)
engine.options_strategy = near_atm_put_protection(schema, "SPY")
```

See [`research/spitznagel_spy/FRAMINGS.md`](https://github.com/unbalancedparentheses/finance_research/blob/main/research/spitznagel_spy/FRAMINGS.md) in the companion repo for the difference between the two framings and what each one produces.

### Reports and tearsheets

One call produces a single self-contained HTML report with every panel —
equity curve vs benchmark, underwater plot, rolling Sharpe/volatility,
monthly heatmap, plus the options-specific panels (P&L attribution by leg,
premium spend vs budget, crash-window zooms, per-trade P&L on a symlog
scale, options exposure):

```python
from options_portfolio_backtester.analytics.tearsheet import build_tearsheet

report = build_tearsheet(
    engine.balance,
    benchmark_balance=spy_engine.balance,   # optional
    trade_log=engine.trade_log,             # optional, powers the trade panels
    budget_annual_pct=0.033,                # optional, draws the budget rule
)
report.to_file("tearsheet.html")
```

Charts embed as static SVG when `vl-convert-python` is installed (the
`charts` extra) — fully offline — and fall back to interactive vega-embed
otherwise. For the full generic quantstats report (install the `reports`
extra), every backtest exposes a clean daily-returns series:

```python
import quantstats as qs
qs.reports.html(results.returns, benchmark_results.returns)
```

### Strategy presets

Instead of building legs manually:

```python
from options_portfolio_backtester import (
    Strangle, deep_otm_put, near_atm_put_protection,
)

# Tail-hedge primitives (function style, return a configured Strategy)
spitznagel_leg = deep_otm_put(schema, "SPY")   # delta -0.10 to -0.02, DTE 90-180
aqr_leg = near_atm_put_protection(schema, "SPY")  # 5% OTM, monthly

# Other presets (class style)
strangle = Strangle(schema, "short", "SPY",
                    dte_entry_range=(30, 60), dte_exit=7,
                    otm_pct=5, pct_tolerance=1,
                    exit_thresholds=(0.2, 0.2))
```

Available presets: `deep_otm_put`, `near_atm_put_protection`, `Strangle`, `IronCondor`, `CoveredCall`, `CashSecuredPut`, `Collar`, `Butterfly`.

### Stock-only backtest with algo pipeline

For equity portfolios without options, use the pipeline API:

```python
from options_portfolio_backtester.engine.pipeline import (
    AlgoPipelineBacktester,
    RunMonthly, SelectAll, WeighInvVol, LimitWeights, Rebalance,
)
import pandas as pd

prices = pd.read_csv("data/processed/stocks.csv", parse_dates=["date"])
prices = prices.pivot(index="date", columns="symbol", values="adjClose")

bt = AlgoPipelineBacktester(
    prices=prices,
    initial_capital=1_000_000,
    algos=[
        RunMonthly(),
        SelectAll(),
        WeighInvVol(lookback=252),
        LimitWeights(limit=0.25),
        Rebalance(),
    ],
)
bt.run()
```

## Execution models

Every component is swappable. Pass them to `BacktestEngine(...)` or override per-leg.

**Signal selectors** — which contract to pick from candidates:
`FirstMatch()`, `NearestDelta(target)`, `MaxOpenInterest()`

**Cost models** — commissions and fees:
`NoCosts()`, `PerContractCommission(rate)`, `TieredCommission(tiers)`, `SpreadSlippage(pct)`

**Fill models** — execution price:
`MarketAtBidAsk()`, `MidPrice()`, `VolumeAwareFill(threshold)`

**Position sizers** — how many contracts:
`CapitalBased()`, `FixedQuantity(qty)`, `FixedDollar(amount)`, `PercentOfPortfolio(pct)`

**Risk constraints** — pre-trade gating:
`MaxDelta(limit)`, `MaxVega(limit)`, `MaxDrawdown(max_dd_pct)`

## Rebalancing model

At each rebalance date, the engine follows a **full liquidation** approach:

1. **Liquidate all options** — every open option position is sold at current market price (bid for long, ask for short)
2. **Compute total capital** — cash + stock value (options are zero after liquidation)
3. **Rebalance stocks** — sell all stocks, buy fresh at target allocation (e.g. 97%)
4. **Buy new options** — use the full options allocation (e.g. 3%) to purchase contracts matching entry criteria (DTE, delta, etc.)

This ensures:
- **Clean accounting** — no stale option value carried across rebalances, no money creation
- **Fresh positions** — every rebalance picks the best available contracts for current market conditions
- **Simple math** — `total_capital = cash + stocks` at the point of redeployment, no complex delta tracking

Between rebalance dates, positions are held (mark-to-market for balance tracking). If `check_exits_daily=True`, exit filters run daily but no new entries are made until the next rebalance.

For the **Spitznagel leverage** model (`options_budget` parameter), options are funded separately from the stock allocation so `{stocks: 1.0, options: 0.005}` means 100% equity + 0.5% put budget on top.

## Rust acceleration

Required: the backtest engine imports the Rust core at load time, so it must be built before use. There is no Python fallback.

```shell
make rust-build
```

| Benchmark | Time |
|-----------|------|
| Full options backtest (17-year SPY chain, ~22M rows) | ~4s |
| Stock-only monthly rebalance | ~0.6s |
| Parallel grid sweep (100 configs) | 5-8x vs sequential (Rayon, bypasses GIL) |

(The former Python-engine comparison column was removed along with the
Python engine path itself; those numbers are no longer reproducible.)

## Data

```shell
# SPY stock + options data
python scripts/fetch_data.py all --symbols SPY

# Multiple symbols
python scripts/fetch_data.py all --symbols SPY IWM QQQ --start 2020-01-01 --end 2023-01-01

# FRED macro signals (VIX, GDP, Buffett Indicator, etc.)
python scripts/fetch_signals.py

# Convert OptionsDX format
python scripts/convert_optionsdx.py data/raw/spx_eod_2020.csv --output data/processed/spx_options.csv
```

You can also bring your own CSVs. Required columns:
- **Stocks**: `date`, `symbol`, `adjClose`
- **Options**: `quotedate`, `underlying`, `type`, `strike`, `expiration`, `dte`, `bid`, `ask`, `volume`, `openinterest`, `delta`

## Tests

```shell
make test            # default suite (~1300 tests: unit + oracles + convexity)
make test-heavy      # data-heavy at-scale correctness tests (needs SPY data)
make verify-articles # reproduce all published-article tables and assert they match
make lint            # ruff
make typecheck       # mypy (informational; typing debt documented in CI)
make rust-test       # Rust unit tests
make rust-bench      # criterion performance benchmarks
```

See [`tests/README.md`](tests/README.md) for the test-tier model (unit /
oracles / heavy / convexity) and what each tier guards against.

## Architecture

```
options_portfolio_backtester/
├── core/            # Types: Direction, OptionType, Greeks, Fill, Order
├── data/            # Schema DSL, CSV providers
├── strategy/        # Strategy, StrategyLeg, presets
├── execution/       # CostModel, FillModel, Sizer, SignalSelector
├── portfolio/       # Portfolio, OptionPosition, RiskManager
├── engine/          # BacktestEngine, AlgoPipelineBacktester, StrategyTreeEngine
├── convexity/       # Convexity scoring/backtest (used by presets)
└── analytics/       # BacktestStats, BacktestResults, TradeLog, TearsheetReport, charts

rust/
├── ob_core/         # Backtest loop, stats, execution models, filter parser
└── ob_python/       # PyO3 bindings, parallel sweep, Arrow bridge
```

## Pipeline algos

40+ composable algos for the `AlgoPipelineBacktester`. All follow `__call__(ctx) -> StepDecision`.

**Scheduling**: `RunDaily`, `RunWeekly`, `RunMonthly`, `RunQuarterly`, `RunYearly`, `RunOnce`, `RunOnDate`, `RunAfterDate`, `RunAfterDays`, `RunEveryNPeriods`, `RunIfOutOfBounds`, `Or`, `Not`, `Require`

**Selection**: `SelectAll`, `SelectThese`, `SelectHasData`, `SelectN`, `SelectMomentum`, `SelectWhere`, `SelectRandomly`, `SelectActive`, `SelectRegex`

**Weighting**: `WeighEqually`, `WeighSpecified`, `WeighTarget`, `WeighInvVol`, `WeighMeanVar`, `WeighERC`, `TargetVol`, `WeighRandomly`

**Risk & rebalancing**: `LimitWeights`, `LimitDeltas`, `ScaleWeights`, `HedgeRisks`, `Margin`, `MaxDrawdownGuard`, `Rebalance`, `RebalanceOverTime`, `CapitalFlow`, `CloseDead`, `ClosePositionsAfterDates`, `ReplayTransactions`, `CouponPayingPosition`

## Research

Research notebooks and analysis: [finance_research](https://github.com/unbalancedparentheses/finance_research).
