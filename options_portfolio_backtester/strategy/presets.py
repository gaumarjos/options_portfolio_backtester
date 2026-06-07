"""Pre-built strategy constructors for common options strategies."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from options_portfolio_backtester.core.types import Direction, OptionType
from options_portfolio_backtester.strategy.strategy import Strategy
from options_portfolio_backtester.strategy.strategy_leg import StrategyLeg

if TYPE_CHECKING:
    from options_portfolio_backtester.data.schema import Schema


def deep_otm_put(
    schema: "Schema",
    underlying: str,
    delta_range: tuple[float, float] = (-0.10, -0.02),
    dte_range: tuple[int, int] = (90, 180),
    dte_exit: int = 14,
    direction: Direction = Direction.BUY,
) -> Strategy:
    """Build a deep-OTM put strategy — the canonical Spitznagel tail-hedge leg.

    Default parameters match the configuration in the article at
    https://federicocarrone.com/series/leptokurtic/the-tail-hedge-debate-spitznagel-is-right/:
    delta in [-0.10, -0.02] (deep out of the money), DTE in [90, 180] at
    entry, exit when DTE drops to 14 or below, monthly roll (set on the
    engine, not here). The leg is sorted by delta ascending so the deepest
    OTM contract within the band is picked first.

    Compose this with ``BacktestEngine.use_external_budget(annual_pct)``
    for the Spitznagel framing, or with ``use_allocation`` for the
    allocation-reducing (AQR) framing.
    """
    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT, direction=direction)
    leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.delta >= delta_range[0])
        & (schema.delta <= delta_range[1])
    )
    leg.entry_sort = ("delta", False)
    leg.exit_filter = schema.dte <= dte_exit
    strat = Strategy(schema)
    strat.add_leg(leg)
    strat.add_exit_thresholds(profit_pct=math.inf, loss_pct=math.inf)
    return strat


def near_atm_put_protection(
    schema: "Schema",
    underlying: str,
    otm_pct: float = 5.0,
    dte_range: tuple[int, int] = (28, 35),
    dte_exit: int = 14,
    direction: Direction = Direction.BUY,
) -> Strategy:
    """Build a near-ATM put-protection strategy — the configuration AQR /
    Israelov actually test in 'Chasing Your Own Tail (Risk)' and
    'Pathetic Protection'.

    Default parameters: ~5% OTM puts (the CBOE PPUT index benchmark),
    monthly DTE band, exit near expiry. These puts have the highest
    theta decay and the lowest convexity per dollar — the opposite of
    the Spitznagel configuration.
    """
    otm_lo = (otm_pct - 1.0) / 100
    otm_hi = (otm_pct + 1.0) / 100
    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT, direction=direction)
    leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike <= schema.underlying_last * (1 - otm_lo))
        & (schema.strike >= schema.underlying_last * (1 - otm_hi))
    )
    leg.exit_filter = schema.dte <= dte_exit
    strat = Strategy(schema)
    strat.add_leg(leg)
    strat.add_exit_thresholds(profit_pct=math.inf, loss_pct=math.inf)
    return strat


def strangle(
    schema: "Schema",
    underlying: str,
    direction: Direction,
    dte_range: tuple[int, int],
    dte_exit: int,
    otm_pct: float = 0.0,
    pct_tolerance: float = 1.0,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a strangle (long or short) strategy."""
    strat = Strategy(schema)

    otm_lo = (otm_pct - pct_tolerance) / 100
    otm_hi = (otm_pct + pct_tolerance) / 100

    call_leg = StrategyLeg("leg_1", schema, option_type=OptionType.CALL, direction=direction)
    call_leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike >= schema.underlying_last * (1 + otm_lo))
        & (schema.strike <= schema.underlying_last * (1 + otm_hi))
    )
    call_leg.exit_filter = schema.dte <= dte_exit

    put_leg = StrategyLeg("leg_2", schema, option_type=OptionType.PUT, direction=direction)
    put_leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike <= schema.underlying_last * (1 - otm_lo))
        & (schema.strike >= schema.underlying_last * (1 - otm_hi))
    )
    put_leg.exit_filter = schema.dte <= dte_exit

    strat.add_legs([call_leg, put_leg])
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


def iron_condor(
    schema: "Schema",
    underlying: str,
    dte_range: tuple[int, int],
    dte_exit: int,
    short_delta_call: float = 0.30,
    short_delta_put: float = -0.30,
    wing_width: float = 5.0,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a short iron condor (sell inner, buy outer wings).

    This is a simplified version using strike offsets; for delta-based
    selection, use a NearestDelta signal_selector on each leg.
    """
    strat = Strategy(schema)

    # Short call (inner)
    sc = StrategyLeg("leg_1", schema, option_type=OptionType.CALL, direction=Direction.SELL)
    sc.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    sc.exit_filter = schema.dte <= dte_exit

    # Long call (outer wing)
    lc = StrategyLeg("leg_2", schema, option_type=OptionType.CALL, direction=Direction.BUY)
    lc.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    lc.exit_filter = schema.dte <= dte_exit

    # Short put (inner)
    sp = StrategyLeg("leg_3", schema, option_type=OptionType.PUT, direction=Direction.SELL)
    sp.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    sp.exit_filter = schema.dte <= dte_exit

    # Long put (outer wing)
    lp = StrategyLeg("leg_4", schema, option_type=OptionType.PUT, direction=Direction.BUY)
    lp.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    lp.exit_filter = schema.dte <= dte_exit

    strat.add_legs([sc, lc, sp, lp])
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


def covered_call(
    schema: "Schema",
    underlying: str,
    dte_range: tuple[int, int],
    dte_exit: int,
    otm_pct: float = 2.0,
    pct_tolerance: float = 1.0,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a covered call strategy (sell OTM calls against stock)."""
    strat = Strategy(schema)
    otm_lo = (otm_pct - pct_tolerance) / 100
    otm_hi = (otm_pct + pct_tolerance) / 100

    leg = StrategyLeg("leg_1", schema, option_type=OptionType.CALL, direction=Direction.SELL)
    leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike >= schema.underlying_last * (1 + otm_lo))
        & (schema.strike <= schema.underlying_last * (1 + otm_hi))
    )
    leg.exit_filter = schema.dte <= dte_exit

    strat.add_leg(leg)
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


def cash_secured_put(
    schema: "Schema",
    underlying: str,
    dte_range: tuple[int, int],
    dte_exit: int,
    otm_pct: float = 2.0,
    pct_tolerance: float = 1.0,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a cash-secured put strategy (sell OTM puts)."""
    strat = Strategy(schema)
    otm_lo = (otm_pct - pct_tolerance) / 100
    otm_hi = (otm_pct + pct_tolerance) / 100

    leg = StrategyLeg("leg_1", schema, option_type=OptionType.PUT, direction=Direction.SELL)
    leg.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike <= schema.underlying_last * (1 - otm_lo))
        & (schema.strike >= schema.underlying_last * (1 - otm_hi))
    )
    leg.exit_filter = schema.dte <= dte_exit

    strat.add_leg(leg)
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


def collar(
    schema: "Schema",
    underlying: str,
    dte_range: tuple[int, int],
    dte_exit: int,
    call_otm_pct: float = 2.0,
    put_otm_pct: float = 2.0,
    pct_tolerance: float = 1.0,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a collar strategy (long put + short call against stock)."""
    strat = Strategy(schema)
    call_lo = (call_otm_pct - pct_tolerance) / 100
    call_hi = (call_otm_pct + pct_tolerance) / 100
    put_lo = (put_otm_pct - pct_tolerance) / 100
    put_hi = (put_otm_pct + pct_tolerance) / 100

    short_call = StrategyLeg("leg_1", schema, option_type=OptionType.CALL, direction=Direction.SELL)
    short_call.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike >= schema.underlying_last * (1 + call_lo))
        & (schema.strike <= schema.underlying_last * (1 + call_hi))
    )
    short_call.exit_filter = schema.dte <= dte_exit

    long_put = StrategyLeg("leg_2", schema, option_type=OptionType.PUT, direction=Direction.BUY)
    long_put.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
        & (schema.strike <= schema.underlying_last * (1 - put_lo))
        & (schema.strike >= schema.underlying_last * (1 - put_hi))
    )
    long_put.exit_filter = schema.dte <= dte_exit

    strat.add_legs([short_call, long_put])
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


def butterfly(
    schema: "Schema",
    underlying: str,
    dte_range: tuple[int, int],
    dte_exit: int,
    option_type: OptionType = OptionType.CALL,
    exit_thresholds: tuple[float, float] = (float("inf"), float("inf")),
) -> Strategy:
    """Build a long butterfly spread (buy 1 lower, sell 2 middle, buy 1 upper).

    Uses entry_sort on strike to pick the legs. The middle leg is a SELL
    direction with double quantity handled by the sizer.
    """
    strat = Strategy(schema)

    # Lower wing (buy)
    lower = StrategyLeg("leg_1", schema, option_type=option_type, direction=Direction.BUY)
    lower.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    lower.entry_sort = ("strike", True)  # ascending — lowest strike first
    lower.exit_filter = schema.dte <= dte_exit

    # Middle (sell 2x)
    middle = StrategyLeg("leg_2", schema, option_type=option_type, direction=Direction.SELL)
    middle.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    middle.exit_filter = schema.dte <= dte_exit

    # Upper wing (buy)
    upper = StrategyLeg("leg_3", schema, option_type=option_type, direction=Direction.BUY)
    upper.entry_filter = (
        (schema.underlying == underlying)
        & (schema.dte >= dte_range[0])
        & (schema.dte <= dte_range[1])
    )
    upper.entry_sort = ("strike", False)  # descending — highest strike first
    upper.exit_filter = schema.dte <= dte_exit

    strat.add_legs([lower, middle, upper])
    strat.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
    return strat


class Strangle(Strategy):
    """Class-based Strangle constructor."""

    def __init__(
        self,
        schema: "Schema",
        name: str,
        underlying: str,
        dte_entry_range: tuple[int, int],
        dte_exit: int,
        otm_pct: float = 0,
        pct_tolerance: float = 1,
        exit_thresholds: tuple[float, float] = (float('inf'), float('inf')),
        shares_per_contract: int = 100,
    ) -> None:
        assert (name.lower() == 'short' or name.lower() == 'long')
        super().__init__(schema)
        direction = Direction.SELL if name.lower() == 'short' else Direction.BUY

        leg1 = StrategyLeg(
            "leg_1",
            schema,
            option_type=OptionType.CALL,
            direction=direction,
        )

        otm_lower_bound = (otm_pct - pct_tolerance) / 100
        otm_upper_bound = (otm_pct + pct_tolerance) / 100

        leg1.entry_filter = (schema.underlying == underlying) & (schema.dte >= dte_entry_range[0]) & (
            schema.dte <= dte_entry_range[1]) & (schema.strike >= schema.underlying_last *
                                                 (1 + otm_lower_bound)) & (schema.strike <= schema.underlying_last *
                                                                           (1 + otm_upper_bound))
        leg1.exit_filter = (schema.dte <= dte_exit)

        leg2 = StrategyLeg("leg_2", schema, option_type=OptionType.PUT, direction=direction)
        leg2.entry_filter = (schema.underlying == underlying) & (schema.dte >= dte_entry_range[0]) & (
            schema.dte <= dte_entry_range[1]) & (schema.strike <= schema.underlying_last *
                                                 (1 - otm_lower_bound)) & (schema.strike >= schema.underlying_last *
                                                                           (1 - otm_upper_bound))
        leg2.exit_filter = (schema.dte <= dte_exit)

        self.add_legs([leg1, leg2])
        self.add_exit_thresholds(exit_thresholds[0], exit_thresholds[1])
