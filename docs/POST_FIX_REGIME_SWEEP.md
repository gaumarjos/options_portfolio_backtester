# Post-fix snapshot: budget-mode regime sweep

Engine state: `rust/ob_core/src/backtest.rs` with the externally-funded
exit accounting fix applied. In `execute_exits`, when the strategy is
in externally-funded mode, the entry cost is debited from portfolio
cash on exit so that the lifetime cash flow per put trade equals
realized P&L (proceeds − cost), not the full sale value.

Same data (17-year SPY parquet pinned in `data/fetch_data.py`), same
strategy spec (puts, DTE 90-180, exit ≤14 DTE, monthly BMS rebalance),
same regime windows as `PRE_FIX_REGIME_SWEEP.md` — only the engine
differs.

## Full sweep

Cell format: `annual return / max DD / excess vs SPY (pp)`.

### 0.5% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +4.03% / −47% / +6.53 | +5.71% / −46% / +8.21 | +8.23% / −45% / +10.73 |
| post-GFC | +12.22% | +12.89% / −14% / +0.67 | +12.76% / −17% / +0.54 | +7.51% / −21% / −4.71 |
| calm bull | +14.75% | +11.57% / −16% / −3.18 | +11.34% / −17% / −3.41 | +11.27% / −17% / −3.48 |
| COVID + 22 | +7.32% | +4.48% / −26% / −2.85 | +4.71% / −26% / −2.61 | +4.36% / −27% / −2.96 |
| recent | +26.17% | +22.99% / −11% / −3.18 | +22.58% / −10% / −3.59 | +22.64% / −10% / −3.53 |
| **FULL** | **+10.68%** | **+10.52% / −47% / −0.16** | **+10.73% / −46% / +0.05** | **+9.53% / −45% / −1.15** |

### 1.0% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +10.93% / −42% / +13.43 | +13.80% / −40% / +16.30 | +18.77% / −38% / +21.27 |
| post-GFC | +12.22% | +12.86% / −15% / +0.64 | +12.48% / −19% / +0.26 | +2.85% / −23% / −9.37 |
| calm bull | +14.75% | +8.40% / −16% / −6.35 | +7.97% / −17% / −6.78 | +7.82% / −17% / −6.93 |
| COVID + 22 | +7.32% | +1.65% / −45% / −5.68 | +2.12% / −39% / −5.21 | +1.42% / −43% / −5.90 |
| recent | +26.17% | +19.82% / −11% / −6.35 | +19.01% / −11% / −7.16 | +19.13% / −10% / −7.04 |
| **FULL** | **+10.68%** | **+10.11% / −45% / −0.57** | **+10.37% / −40% / −0.31** | **+8.09% / −43% / −2.59** |

### 2.0% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +25.71% / −29% / +28.21 | +31.29% / −30% / +33.79 | +40.22% / −31% / +42.71 |
| post-GFC | +12.22% | +11.35% / −28% / −0.87 | +10.18% / −31% / −2.04 | −6.27% / −33% / −18.49 |
| calm bull | +14.75% | +2.15% / −22% / −12.61 | +1.33% / −28% / −13.42 | +1.03% / −26% / −13.72 |
| COVID + 22 | +7.32% | −3.94% / −65% / −11.27 | −3.04% / −59% / −10.36 | −4.39% / −61% / −11.71 |
| recent | +26.17% | +13.52% / −12% / −12.65 | +11.95% / −12% / −14.22 | +12.15% / −12% / −14.02 |
| **FULL** | **+10.68%** | **+8.71% / −65% / −1.97** | **+8.95% / −59% / −1.73** | **+4.63% / −61% / −6.05** |

## Pre-fix → post-fix delta on full period

| Cell (full-period excess vs SPY, pp) | Pre-fix | Post-fix | Δ |
|---|---|---|---|
| 0.5% × ~23% OTM | +2.86 | −0.16 | −3.02 |
| 0.5% × ~35% OTM | +3.28 | +0.05 | −3.23 |
| 0.5% × ~50% OTM | +2.41 | −1.15 | −3.56 |
| 1.0% × ~23% OTM | +5.58 | −0.57 | −6.15 |
| 1.0% × ~35% OTM | +6.22 | −0.31 | −6.53 |
| 1.0% × ~50% OTM | +4.61 | −2.59 | −7.20 |
| 2.0% × ~23% OTM | +10.56 | −1.97 | −12.53 |
| 2.0% × ~35% OTM | +11.69 | −1.73 | −13.42 |
| 2.0% × ~50% OTM | +8.60 | −6.05 | −14.65 |

Deflation scales with budget × time × put-MTM, as expected.

## What changed in the qualitative picture

**Survives the fix:**
- Catastrophe-regime edge: every depth × budget still beats SPY massively in GFC (+6 to +43pp excess).
- Drawdown improvement during catastrophes: GFC max DD is −45/−47% vs SPY's −52%.
- Calm regimes underperform — protection has a real cost in tail-light periods.
- Among depths, ~35% OTM has the best full-period excess at 0.5% and 1.0% budgets.

**Breaks under the fix:**
- "Spitznagel framing beats SPY at any budget" — gone. The strategy is at parity or below SPY on full-period return at every budget × depth tested.
- "Sweet spot at 0.5%-1.0% budget" — there's no Sharpe-improving zone; all configs match or underperform SPY on return, only catastrophe-windowed DD improves.
- "3.3% budget recommended" — at this budget the strategy badly underperforms SPY (deep OTM 3.3% final capital: $2.6M vs SPY's $5.5M over the period).

## Bug-canary residual

The near-ATM 3.3% budget case went from $3.5B (pre-fix) to $470M (post-fix). Better but still implausibly high — 41%/yr from $1M. The fix closed the largest leak path (exit-side accounting), but the rebalance-time stock-allocation path probably still inflates `liquid_capital` with unrealized put MTM. The article uses deep-OTM only, so this doesn't affect the published numbers, but `tests/test_known_bugs.py` will still xfail and the residual leak is a follow-up.

| Budget | Depth | Pre-fix final | Post-fix final |
|---|---|---|---|
| 3.3% | near-ATM (delta −0.40 to −0.25) | ~$3,500M | $471M |
| 3.3% | standard OTM (delta −0.25 to −0.10) | ~$600M | $205M |
| 3.3% | deep OTM (delta −0.10 to −0.02) | ~$60M | $2.6M |

## Implications for the published article

The Spitznagel piece's quantitative claim ("free-tier 0.5%-1.0% Spitznagel framing beats SPY by 2.86-5.58pp") is an artifact of the pre-fix engine. Under realistic accounting:

- The strategy's full-period return is bounded above by SPY at every tested config.
- The drawdown-improvement-during-catastrophe story still holds.
- The regime-conditional alpha thesis still holds.
- The Spitznagel-vs-AQR framing comparison still favors Spitznagel directionally (AQR pays even more for protection because it gives up equity exposure), but neither framing produces excess return — they produce path-dependent volatility profiles.

The article needs either a substantial rewrite around the drawdown/catastrophe thesis or a full retraction of the headline claim.
