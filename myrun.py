"""Variante di primo_backtest.py: overlay Spitznagel con budget put ridotto a 1,5%/yr.

Stessa configurazione dell'articolo di federicocarrone.com, salvo BUDGET = 0.015.
Modifica i parametri nella sezione CONFIG e rilancia:

    cd ~/options_portfolio_backtester
    source .venv/bin/activate
    python my_experiments/budget_1p5.py
"""




### TODO
# 0) Add a plot with live quantities
# 1) Rolling (buy on sell date), code there, a few things to fix
# 2) Run through time instead of buy-hold
#





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

# Roll the put the same day it is sold, instead of waiting for the next
# calendar rebalance. Entries only ever happen on rebalance dates, so this
# works by ADDING every exit date to the rebalance calendar. Exit dates are
# DTE-driven and unknown in advance -> iterate to a fixed point.
#
# CAVEAT: options_alloc = NAV * BUDGET / rebalances_per_year, so adding
# rebalance dates shrinks the per-rebalance budget and lowers realized spend.
# Compare the "premium spend" line below across runs and scale BUDGET if you
# want spend held constant.
ROLL_ON_EXIT = True
ROLL_ITERS = 3
TEARSHEET = "output/{}_tearsheet.html".format(TEST_STR)
CSV = "output/{}_curve.csv".format(TEST_STR)






def engine_spitznagel(opts, stocks, schema):
    """100% SPY + put deep OTM from external budged (framing Spitznagel)."""
    bt = BacktestEngine({"stocks": 1.0, "options": 0.0, "cash": 0.0}, initial_capital=CAPITALE)
    bt.options_budget_annual_pct = BUDGET   # 
    bt.check_exits_daily = True             # controlli di uscita giornalieri
    bt.rebalance_stocks_on_exit = True      # monetizza e ricompra SPY
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

    Reconstructed from trade_log by pairing BTO->STC per contract, NOT from
    bt.balance["options qty"]: that column reports 0 on days where the trade
    log shows open positions, so it understates coverage. The engine backfills
    each [prev_rebalance, rebalance) window with the state as of the END of the
    window, so any position opened and closed inside a window never appears.

    Exits are DTE-driven (checked every day when check_exits_daily=True) but
    entries happen ONLY on rebalance dates: the gaps come from that mismatch,
    not from unfilled entries (option_fill_rate stays 100%).
    """
    days = pd.to_datetime(bt.balance.index)
    tl = _flat_trades(bt)

    open_count = pd.Series(0, index=days)
    for _contract, g in tl.groupby("leg_1_contract"):
        g = g.sort_values("date")
        bto = g[g["leg_1_order"] == "BTO"]
        stc = g[g["leg_1_order"] == "STC"]
        if bto.empty:
            continue
        start = bto["date"].iloc[0]
        end = stc["date"].iloc[0] if not stc.empty else days[-1]
        open_count.loc[(days >= start) & (days <= end)] += 1

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



### EXTRA CODE TO ROLL (SELL/BUY) ON SAME DAY

# WHY A GAP EXISTS AT ALL
# Exits are DTE-driven and, with check_exits_daily=True, evaluated on every
# trading day. Entries happen ONLY on rebalance dates. A put sold at DTE 30 is
# therefore not replaced until the next calendar rebalance, which with 2BMS can
# be up to ~43 trading days later. Measured on the baseline config: 130 days
# (2.9%) with no put at all, in 6 stretches -- and the stretches land right
# AFTER the hedge pays, because that is when the winner rolls off. The worst
# ones were 2020-03-19 -> 2020-04-30 (through the COVID bottom of 03-23) and
# 2008-11-21 -> 2008-12-31. Note this is NOT a fill problem: option_fill_rate
# was 100% (101 attempts, 0 unfilled) over 2008-2025.
#
# HOW THIS FIXES IT
# The only lever is to MAKE each exit date a rebalance date. run() accepts a
# `rebalance_dates` override which takes precedence over rebalance_freq (see
# engine.py, the `if rebalance_dates_override` branch before `elif
# rebalance_freq`). Inside a rebalance the engine runs exits FIRST, then
# recomputes options_cap (now 0), so remaining_budget > 0 and the entry fires
# the same day: a true roll.
# Exit dates are not known in advance -- they depend on which contracts were
# entered, which depends on the calendar -- so run_rolling() iterates to a
# fixed point: run, collect STC dates, fold them into the calendar, repeat.
#
# MEASURED (SPY 2008-2025, BUDGET=0.015, 40-45% OTM, DTE 90-180, EXIT_DTE 30)
#                       baseline      roll-on-exit
#   days with no put    130 (2.9%)    28 (0.6%)
#   premium spend       1.218%/yr     0.775%/yr
#   CAGR                14.38%        12.82%
#
# THREE CAVEATS
# 1. The CAGR comparison above is CONFOUNDED. options_alloc =
#    NAV * BUDGET / rebalances_per_year, and this goes from ~108 to ~254
#    rebalance dates, so the per-rebalance allocation shrinks and realized
#    spend falls to ~2/3. For a like-for-like test scale BUDGET by
#    1.218/0.775 ~= 1.57 (i.e. BUDGET = 0.0236) and compare again.
# 2. The date set does not converge in 3 iterations (each new entry creates a
#    new exit date), but the metric that matters does: 28 bare days at both
#    iteration 2 and 3. Raising ROLL_ITERS buys little.
# 3. The residual 27-day gap (2008-11-21 -> 2008-12-31) is NOT the calendar.
#    Fill rate drops to 99.1% with 2 unfilled entries: the roll was attempted
#    on 2008-11-20 and the chain offered no 40-45% OTM strike at 90-180 DTE.
#    At the peak of the GFC that contract simply did not exist.
#
# ALTERNATIVE THAT WAS TRIED AND REJECTED
# Setting check_exits_daily=False also makes exit and entry happen in the same
# rebalance step, with no budget dilution. But then the dte<=30 filter is only
# evaluated every ~61 days, and 80 of 98 puts EXPIRED before a rebalance ever
# looked at them -- booked at totals_cost=0.0 via the intrinsic fallback. The
# GFC winner that sold for $29,400 on 2008-11-20 instead expired on 2008-12-20
# and was written off at zero. CAGR 9.87% under that setting is an artifact of
# throwing away the payoffs, not a clean baseline.


def exit_dates(bt):
    tl = _flat_trades(bt)
    return sorted(set(tl.loc[tl["leg_1_order"] == "STC", "date"]))


def calendar_rebalance_dates(trading_days, freq, unit):
    """The dates run() would pick for (freq, unit): first trading day of each
    bucket — same rule the engine uses internally."""
    s = pd.Series(1, index=pd.to_datetime(trading_days))
    picked = (s.groupby(pd.Grouper(freq=f"{freq}{unit}"))
               .apply(lambda x: x.index.min()).dropna())
    return list(pd.to_datetime(picked.values))


def run_rolling(make_engine, iters=ROLL_ITERS):
    """Run so every exit date is also a rebalance date -> the put is replaced
    the same day it is sold.

    Exit dates depend on which contracts were entered, which depends on the
    rebalance calendar, so this iterates: run, collect exit dates, fold them
    into the calendar, repeat until the exit dates stop changing.
    """
    bt = make_engine()
    bt.run(rebalance_freq=REBAL_FREQ, rebalance_unit=REBAL_UNIT)
    base = calendar_rebalance_dates(bt.balance.index, REBAL_FREQ, REBAL_UNIT)
    seen = exit_dates(bt)
    for i in range(iters):
        dates = sorted(set(base) | set(seen))
        nxt = make_engine()
        nxt.run(rebalance_freq=REBAL_FREQ, rebalance_unit=REBAL_UNIT,
                rebalance_dates=dates)
        found = exit_dates(nxt)
        bt = nxt
        if set(found) == set(seen):
            print(f"  roll calendar converged after {i + 1} iteration(s), "
                  f"{len(dates)} rebalance dates")
            break
        seen = found
    else:
        print(f"  roll calendar not converged in {iters} iterations, "
              f"{len(dates)} rebalance dates")
    return bt


###


def main():
    opts = HistoricalOptionsData("data/processed/options.parquet")
    stocks = TiingoData("data/processed/stocks.csv")
    schema = opts.schema

    print(f"Backtest overlay Spitznagel (budget {BUDGET:.1%}/yr, {OTM_LO:.0%}-{OTM_HI:.0%} OTM)")
    if ROLL_ON_EXIT:
        bt = run_rolling(lambda: engine_spitznagel(opts, stocks, schema))
    else:
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


if __name__ == "__main__":
    main()
