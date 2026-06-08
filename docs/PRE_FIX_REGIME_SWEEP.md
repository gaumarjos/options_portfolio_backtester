# Pre-fix snapshot: budget-mode regime sweep

Engine state: `rust/ob_core/src/backtest.rs` at the commit before the
budget-mode accounting fix. This is the "free puts" semantics, where
in externally-funded mode the engine credits put proceeds to portfolio
cash without ever debiting the entry cost. The numbers below come from
the 17-year SPY parquet pinned in `data/fetch_data.py` and the
`deep_otm_put`-equivalent strategy at three depth bands.

Captured so a future commit can diff against the post-fix numbers and
the published article tables can be reconciled mechanically.

## Framing readings

| Reading | What it models | Engine match | Investor return correct? |
|---|---|---|---|
| 1. Donation | External party gives put budget each year, never wants it back. Puts pay off → pure profit. | Current engine | No — double counts the budget contribution |
| 2. Fee-paid (Universa) | Investor pays X%/yr fee out of pocket, manager buys puts on their behalf. | Requires tracking cumulative external contribution as metadata | Yes, if cumulative external is subtracted |
| 3. 0% loan with full repayment | Someone loans the budget, you repay principal from put proceeds, keep realized P&L. | Requires `*cash -= entry_cost * quantity` at exit in externally_funded branch | Yes |
| 4. Real loan with interest | Same as 3 plus interest cost on outstanding balance. | Requires new engine parameter for funding rate | Yes |

Reading 2 and Reading 3 produce identical investor wealth at every point in time — they're two presentations of the same realistic model. Reading 1 inflates returns by exactly the cumulative external contribution (so the gap grows with budget and time). Reading 4 is Reading 3 with a small drag from interest.

## Regime windows used

| Window | Dates | Character |
|---|---|---|
| GFC + rec | 2007-10 to 2010-12 | Catastrophe regime, peak-to-trough SPY ≈ −52% |
| post-GFC | 2011-01 to 2015-12 | Recovery + 2011/2015 mini-corrections |
| calm bull | 2016-01 to 2019-12 | Volpocalypse 2018 only material drawdown |
| COVID + 22 | 2020-01 to 2022-12 | Two distinct drawdowns: Mar 2020 crash, 2022 bear |
| recent | 2023-01 to 2024-12 | Bull regime |
| FULL | 2007-10 to 2024-12 | Inclusive 17-year window |

## Full sweep (engine = pre-fix, "free puts" semantics)

Cell format: `annual return / max DD / excess vs SPY (pp)`. Depth bands: article default delta −0.10 to −0.02 ≈ 23% OTM, deeper delta −0.05 to −0.01 ≈ 35% OTM, very deep delta −0.02 to −0.005 ≈ 50% OTM.

### 0.5% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +5.31% / −46% / +7.82 | +7.06% / −45% / +9.57 | +9.82% / −44% / +12.32 |
| post-GFC | +12.22% | +16.63% / −13% / +4.40 | +17.00% / −16% / +4.78 | +12.23% / −18% / +0.01 |
| calm bull | +14.75% | +14.67% / −16% / −0.08 | +14.66% / −16% / −0.10 | +14.67% / −16% / −0.08 |
| COVID + 22 | +7.32% | +7.28% / −24% / −0.05 | +7.26% / −24% / −0.06 | +7.25% / −26% / −0.07 |
| recent | +25.90% | +26.20% / −10% / +0.30 | +26.18% / −10% / +0.28 | +26.26% / −10% / +0.36 |
| **FULL** | **+10.65%** | **+13.51% / −46% / +2.86** | **+13.93% / −45% / +3.28** | **+13.06% / −44% / +2.41** |

### 1.0% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +13.91% / −40% / +16.41 | +16.65% / −39% / +19.15 | +22.20% / −38% / +24.71 |
| post-GFC | +12.22% | +20.47% / −15% / +8.25 | +21.13% / −18% / +8.91 | +12.24% / −18% / +0.02 |
| calm bull | +14.75% | +14.58% / −14% / −0.17 | +14.56% / −15% / −0.19 | +14.58% / −15% / −0.17 |
| COVID + 22 | +7.32% | +7.23% / −44% / −0.09 | +7.20% / −38% / −0.13 | +7.19% / −42% / −0.14 |
| recent | +25.90% | +26.22% / −9% / +0.32 | +26.18% / −9% / +0.28 | +26.35% / −9% / +0.45 |
| **FULL** | **+10.65%** | **+16.23% / −44% / +5.58** | **+16.87% / −39% / +6.22** | **+15.26% / −42% / +4.61** |

### 2.0% budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC + rec | −2.50% | +31.82% / −28% / +34.33 | +37.54% / −28% / +40.04 | +47.63% / −30% / +50.14 |
| post-GFC | +12.22% | +26.97% / −27% / +14.75 | +28.06% / −31% / +15.83 | +12.26% / −26% / +0.04 |
| calm bull | +14.75% | +14.42% / −14% / −0.33 | +14.37% / −18% / −0.38 | +14.42% / −18% / −0.33 |
| COVID + 22 | +7.32% | +7.14% / −64% / −0.19 | +7.07% / −58% / −0.25 | +7.05% / −59% / −0.27 |
| recent | +25.90% | +26.26% / −9% / +0.36 | +26.19% / −9% / +0.29 | +26.52% / −11% / +0.62 |
| **FULL** | **+10.65%** | **+21.21% / −64% / +10.56** | **+22.34% / −58% / +11.69** | **+19.25% / −59% / +8.60** |

## What survives the bug (qualitative pattern)

The relative ordering across regimes and depths is genuine — only the absolute magnitudes are inflated by the free-puts mechanic. The following observations should hold under any of the four readings above:

1. **Edge concentrates in catastrophe regimes.** Every depth, every budget shows GFC + post-GFC carrying the strategy's full-period excess. Calm regimes (2016-19) and the mixed COVID/2022 window deliver near-zero excess.
2. **Among depths, ~35% OTM beats the article's ~23% OTM default by ~0.4-1.1pp on full-period excess.** Very deep (~50% OTM) wins huge in catastrophes but goes dead in moderate corrections.
3. **Budget sweet spot is 0.5%-1.0%.** At 2.0% the max drawdown gets worse than SPY-only (continuous premium bleed digs a self-inflicted drawdown). Spitznagel's recommended 3.3% is past this point.
4. **At higher budgets, deepest-OTM band underperforms.** It needs catastrophes to pay; in moderate corrections (post-GFC mini-drawdowns) it's pure decay.

## What does NOT survive (quantitative magnitudes)

- "Spitznagel framing beats SPY by +2.86pp at 0.5% budget, ~23% OTM." This number depends on the free-puts mechanic. Under Reading 3, the analogous comparison would show the strategy roughly at parity with SPY at 0.5% budget; the +2.86pp shrinks toward zero.
- All headline `annual_return` numbers above for the budget-mode strategy. Each cell inflates by approximately the cumulative budget contribution as a fraction of starting capital, compounded.

## How to validate post-fix

After the engine fix lands, re-run this sweep and produce a parallel table. Differences should:
- Preserve regime ordering and the qualitative observations above.
- Deflate full-period annual returns by roughly the cumulative external contribution (a function of budget × portfolio path).
- Cause `tests/test_article_reproduction.py` baselines to fail; update them to the new numbers in the same commit.
- Cause `tests/test_known_bugs.py` xfail tests to xpass; move them to the regular suite.
