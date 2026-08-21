"""Variante di primo_backtest.py: overlay Spitznagel con budget put ridotto a 1,5%/yr.

Stessa configurazione dell'articolo di federicocarrone.com, salvo BUDGET = 0.015.
Modifica i parametri nella sezione CONFIG e rilancia:

    cd ~/options_portfolio_backtester
    source .venv/bin/activate
    python my_experiments/budget_1p5.py
"""




### TODO
# 0) Add a plot with live quantities
# 2) Run through time instead of buy-hold




import math
import warnings
from pathlib import Path
import pandas as pd

warnings.filterwarnings("ignore")

from options_portfolio_backtester import (
    BacktestEngine,
    Direction,
    OptionType,
    Stock,
    Strategy,
    StrategyLeg,
)
from options_portfolio_backtester.analytics.tearsheet import build_tearsheet
from options_portfolio_backtester.data.providers import HistoricalOptionsData, TiingoData


# ----------------- CONFIG: i pomelli da girare -----------------
TEST_STR = "test1"

BUDGET = 0.015          # budget put esterno, frazione annua (0.005 = 0.5%/yr scala Universa)
OTM_LO, OTM_HI = 0.40, 0.45  # depth OTM (40-45%)
DTE_LO, DTE_HI = 90, 180     # 
EXIT_DTE = 30                #
REBAL_FREQ, REBAL_UNIT = 2, "BMS"  # bimestrale; (1, "BMS") = mensile
CAPITALE = 100_000

# What opens a new put position:
#   "calendar"      — only on rebalance dates. This is what the engine always
#                     did. It leaves the book bare between a DTE-30 exit and
#                     the next rebalance date: 138 days (3.1%) over 2008-2025,
#                     and the gaps land right AFTER the hedge pays, because
#                     that is when the winner rolls off.
#   "roll"          — buy whenever the book is flat, on any day. Closes every
#                     gap, but holds only one position at a time and so gives
#                     up the stacking that "calendar" gets for free from the
#                     top-up budget model. Measurably worse: see table below.
#   "roll+calendar" — roll AND top up on rebalance dates. Continuous coverage
#                     with the stacking kept.
#
# SPY 2008-2025, BUDGET=0.015, 40-45% OTM, DTE 90-180, EXIT_DTE 30, 2BMS:
#
#   mode            CAGR     maxDD    bare days   spend/yr   entries
#   calendar       14.38%   -27.11%   138 (3.1%)   1.218%      101
#   roll           11.59%   -40.43%     0 (0.0%)   1.112%       80
#   roll+calendar  14.33%   -27.17%     0 (0.0%)   1.261%      117
#
# Pure "roll" underperforms for a structural reason worth remembering: it holds
# exactly one position, so when it re-enters during a vol spike the fixed
# budget buys almost nothing. In Oct 2008 it rolled into a single contract at
# $148 and carried that through the crash — mean option value over the GFC was
# 1.40% of NAV against 3.80% for "calendar".
WHEN_TO_BUY = "roll+calendar"
TEARSHEET = "output/{}_tearsheet.html".format(TEST_STR)
CSV = "output/{}_curve.csv".format(TEST_STR)
CONTRACTS_PNG = "output/{}_contracts_per_day.png".format(TEST_STR)






def engine_spitznagel(opts, stocks, schema):
    """100% SPY + put deep OTM from external budged (framing Spitznagel)."""
    bt = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0}, initial_capital=CAPITALE)
    bt.options_budget_annual_pct = BUDGET   # 
    bt.check_exits_daily = True             # controlli di uscita giornalieri
    bt.rebalance_stocks_on_exit = True      # monetizza e ricompra SPY
    bt.when_to_buy = WHEN_TO_BUY            # calendar | roll | roll+calendar
    bt.stocks = [Stock("SPY", 1.0)]
    bt.stocks_data = stocks
    bt.options_data = opts

    leg = StrategyLeg("put_lunga", schema, option_type=OptionType.PUT, direction=Direction.BUY)
    leg.entry_filter = (
        (schema.underlying == "SPY")
        & (schema.dte >= DTE_LO)
        & (schema.dte <= DTE_HI)
        & (schema.strike <= schema.underlying_last * (1 - OTM_LO))
        & (schema.strike >= schema.underlying_last * (1 - OTM_HI))
    )
    leg.entry_sort = ("strike", False)      # a parità di filtro, preferisci lo strike più alto
    leg.exit_filter = schema.dte <= EXIT_DTE

    strat = Strategy(schema)
    strat.add_leg(leg)
    strat.add_exit_thresholds(profit_pct=math.inf, loss_pct=math.inf)  # nessun profit target
    bt.options_strategy = strat
    return bt


def engine_spy(opts, stocks, schema):
    """Baseline: SPY buy-and-hold"""
    bt = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0}, initial_capital=CAPITALE)
    bt.stocks = [Stock("SPY", 1.0)]
    bt.stocks_data = stocks
    bt.options_data = opts
    bt.options_strategy = Strategy(schema)
    return bt


def metriche(series):
    anni = (series.index[-1] - series.index[0]).days / 365.25
    cagr = ((series.iloc[-1] / series.iloc[0]) ** (1 / anni) - 1) * 100
    maxdd = ((series - series.cummax()) / series.cummax()).min() * 100
    return cagr, maxdd, series.iloc[-1]


def _flat_trades(bt):
    """trade_log with its MultiIndex columns flattened and dates parsed."""
    tl = bt.trade_log.copy()
    if isinstance(tl.columns, pd.MultiIndex):
        tl.columns = ["_".join(c) for c in tl.columns]
    tl["date"] = pd.to_datetime(tl["totals_date"])
    return tl


def coverage(bt):
    """Days holding no put at all ("uncovered").

    Reconstructed from trade_log by pairing BTO->STC per contract. This is kept
    as an INDEPENDENT cross-check of bt.balance["options qty"] rather than
    reading that column directly: the two now agree day-for-day, and any future
    divergence means one of them has regressed.

    (Before the compute_balance_period fix, "options qty" was backfilled with
    end-of-window state and disagreed badly -- 385 bare days vs 129 -- because
    a position opened and closed inside one rebalance window never appeared.
    That is fixed; the column is trustworthy now.)

    Convention: a position is counted open from its entry date up to but NOT
    including its exit date -- you sold that day, so you end it flat. A position
    never closed stays open through the final row.

    Exits are DTE-driven (checked every day when check_exits_daily=True) but
    entries happen ONLY on rebalance dates: the gaps come from that mismatch,
    not from unfilled entries (option_fill_rate stays 100%).
    """
    # Row 0 is the synthetic pre-start row the engine prepends (initial capital
    # at stocks_data.start_date - 1 day). It predates any trading, so counting
    # it as "uncovered" is noise.
    days = pd.to_datetime(bt.balance.index)[1:]
    tl = _flat_trades(bt)

    open_count = pd.Series(0, index=days)
    for _contract, g in tl.groupby("leg_1_contract"):
        g = g.sort_values("date")
        bto = g[g["leg_1_order"] == "BTO"]
        stc = g[g["leg_1_order"] == "STC"]
        if bto.empty:
            continue
        start = bto["date"].iloc[0]
        if stc.empty:
            held = days >= start
        else:
            held = (days >= start) & (days < stc["date"].iloc[0])
        open_count.loc[held] += 1

    uncovered = open_count == 0
    blocks = (uncovered != uncovered.shift()).cumsum()
    stretches = [(g.index[0], g.index[-1], len(g))
                 for _k, g in uncovered.groupby(blocks) if g.iloc[0]]
    stretches.sort(key=lambda s: -s[2])
    return uncovered, stretches


def print_coverage(bt):
    uncovered, stretches = coverage(bt)
    tl = _flat_trades(bt)
    bto = tl[tl["leg_1_order"] == "BTO"]
    nav = bt.balance["total capital"]
    days = pd.to_datetime(bt.balance.index)
    years = (days[-1] - days[0]).days / 365.25
    spent = (bto["totals_cost"] * bto["totals_qty"]).sum()
    print()
    print(f"{'Coverage':24}")
    print(f"  entry fill rate         {bt.option_fill_rate:>7.1%} "
          f"({bt.option_entry_attempts} attempts, "
          f"{bt.option_entry_unfilled} unfilled)")
    print(f"  days with no put        {uncovered.sum():>7} / {len(uncovered)} "
          f"({uncovered.mean():.1%})")
    print(f"  uncovered stretches     {len(stretches):>7}")
    for start, end, n in stretches[:5]:
        print(f"    {start.date()} -> {end.date()}  {n:>3} days")
    # Realized spend is what actually bought protection; it sits below BUDGET
    # because of integer contract lots and the options_cap deduction the engine
    # applies to each rebalance's allocation.
    print(f"  premium spend           {spent / years / nav.mean():>7.3%}/yr "
          f"(nominal {BUDGET:.3%}/yr, {len(bto)} entries)")



### ROLLING (SELL/BUY ON THE SAME DAY)
#
# This used to be a workaround here: run once, collect the exit dates, feed
# them back in as extra rebalance dates via run()'s `rebalance_dates` override,
# and iterate to a fixed point. It closed most of the gaps (130 bare days -> 28)
# but was wrong in a way worth recording: adding dates to the rebalance calendar
# inflates `rebalances_per_year`, and the per-entry budget is
# NAV * BUDGET / rebalances_per_year -- so it silently cut premium spend from
# 1.218%/yr to 0.775%/yr and made every comparison against calendar mode
# meaningless.
#
# The engine now does this natively and without touching the calendar: set
# WHEN_TO_BUY above. Entries fire on any day the book is flat, so a roll that
# finds no tradeable contract retries the next day instead of leaving the book
# bare (which is what a one-shot buy-on-the-exit-date rule would do -- and did,
# for 27 days after 2008-11-20 when the chain had no 40-45% OTM strike at
# 90-180 DTE).


def main():
    opts = HistoricalOptionsData("data/processed/options.parquet")
    stocks = TiingoData("data/processed/stocks.csv")
    schema = opts.schema

    print(f"Backtest overlay Spitznagel (budget {BUDGET:.1%}/yr, "
          f"{OTM_LO:.0%}-{OTM_HI:.0%} OTM, when_to_buy={WHEN_TO_BUY})")
    bt = engine_spitznagel(opts, stocks, schema)
    bt.run(rebalance_freq=REBAL_FREQ, rebalance_unit=REBAL_UNIT)

    print("Backtest baseline SPY")
    spy = engine_spy(opts, stocks, schema)
    spy.run(rebalance_freq=1, rebalance_unit="BMS")

    report = build_tearsheet(
        bt.balance,
        benchmark_balance=spy.balance,
        trade_log=bt.trade_log,
        budget_annual_pct=BUDGET,
    )
    report.to_file(TEARSHEET)


    # Additional metrics
    serie_strat = bt.balance["total capital"].copy()
    serie_strat.index = pd.to_datetime(serie_strat.index)
    serie_spy = spy.balance["total capital"].copy()
    serie_spy.index = pd.to_datetime(serie_spy.index)
    c1, d1, f1 = metriche(serie_strat)
    c0, d0, f0 = metriche(serie_spy)
    print()
    print(f"{'':24}{'CAGR':>8}  {'MaxDD':>8}  {'Finale':>14}")
    print(f"{'SPY buy-and-hold':24}{c0:>7.2f}%  {d0:>7.1f}%  ${f0:>13,.0f}")
    print(f"{'Overlay Spitznagel':24}{c1:>7.2f}%  {d1:>7.1f}%  ${f1:>13,.0f}")
    print(f"{'Excess':24}{c1 - c0:>+7.2f}pp {d1 - d0:>+7.1f}pp")

    print_coverage(bt)

    timeseries = serie_strat.rename("strategia_usd").rename_axis("data")
    timeseries.to_csv(CSV, float_format="%.2f")

    # One bar per trading day is unreadable at the tearsheet's 700px, so also
    # write a full-width PNG sized from the data (~2px per day).
    from options_portfolio_backtester.analytics.options_charts import (
        save_contracts_held_png,
    )
    png = save_contracts_held_png(bt.balance, CONTRACTS_PNG)
    print(f"\nwrote {png}")


if __name__ == "__main__":
    main()
