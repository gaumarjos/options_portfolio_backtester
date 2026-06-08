# Post-fix snapshot: regime sweep with ANNUAL budget semantics

Engine state: `rust/ob_core/src/backtest.rs` with the externally-funded
exit accounting fix applied AND budget interpreted as `options_budget_annual_pct`
(true annual percentage) rather than `options_budget_pct` (per-rebalance).

This is the most-realistic view: realistic cash accounting AND the
budget magnitude that matches what Spitznagel actually recommends in
the literature.

For comparison: `POST_FIX_REGIME_SWEEP.md` uses the same fixed engine
but `options_budget_pct` (per-rebalance) — on monthly rebalancing,
"3.3%" actually meant 40%/yr of budget allocated to puts, which is
why the strategy looked so different across budgets.

## SPY baseline

`SPY full-period: +10.68%/yr  final $5,606,661`

## Sweep table

Cell format: `annual return / max DD / excess vs SPY (pp)`.

### 0.5%/yr annual budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC+rec | −2.50% | −1.59% / −51% / +0.90 | −2.06% / −52% / +0.44 | −1.46% / −51% / +1.04 |
| post-GFC | +12.22% | +12.30% / −17% / +0.08 | +12.30% / −17% / +0.08 | +11.83% / −19% / −0.39 |
| calm bull | +14.75% | +14.49% / −19% / −0.26 | +14.47% / −19% / −0.28 | +14.46% / −19% / −0.29 |
| COVID+22 | +7.32% | +7.09% / −30% / −0.23 | +7.11% / −31% / −0.21 | +7.08% / −32% / −0.25 |
| recent | +26.17% | +25.91% / −10% / −0.26 | +25.87% / −10% / −0.30 | +25.88% / −10% / −0.29 |
| **FULL** | **+10.68%** | **+10.75% / −51% / +0.07** | **+10.65% / −52% / −0.03** | **+10.62% / −51% / −0.05** |

### 1.0%/yr annual budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC+rec | −2.50% | −1.33% / −51% / +1.17 | −1.35% / −51% / +1.15 | −0.81% / −51% / +1.69 |
| post-GFC | +12.22% | +12.38% / −17% / +0.16 | +12.37% / −17% / +0.15 | +11.44% / −19% / −0.78 |
| calm bull | +14.75% | +14.23% / −19% / −0.53 | +14.19% / −19% / −0.57 | +14.17% / −19% / −0.58 |
| COVID+22 | +7.32% | +6.85% / −28% / −0.47 | +6.89% / −29% / −0.43 | +6.83% / −30% / −0.49 |
| recent | +26.17% | +25.64% / −10% / −0.53 | +25.58% / −10% / −0.60 | +25.58% / −10% / −0.59 |
| **FULL** | **+10.68%** | **+10.68% / −51% / +0.01** | **+10.67% / −51% / −0.01** | **+10.49% / −51% / −0.19** |

### 2.0%/yr annual budget

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC+rec | −2.50% | −0.57% / −50% / +1.93 | −0.03% / −50% / +2.46 | +0.89% / −50% / +3.39 |
| post-GFC | +12.22% | +12.53% / −16% / +0.31 | +12.51% / −17% / +0.29 | +10.65% / −19% / −1.57 |
| calm bull | +14.75% | +13.70% / −18% / −1.06 | +13.62% / −19% / −1.13 | +13.59% / −18% / −1.16 |
| COVID+22 | +7.32% | +6.38% / −25% / −0.94 | +6.46% / −25% / −0.86 | +6.34% / −27% / −0.98 |
| recent | +26.17% | +25.12% / −10% / −1.05 | +24.98% / −10% / −1.19 | +25.00% / −10% / −1.17 |
| **FULL** | **+10.68%** | **+10.62% / −50% / −0.06** | **+10.69% / −50% / +0.02** | **+10.29% / −50% / −0.38** |

### 3.3%/yr annual budget (Spitznagel's actual recommendation)

| Period | SPY | Article ~23% OTM | Deeper ~35% OTM | Very deep ~50% OTM |
|---|---|---|---|---|
| GFC+rec | −2.50% | +0.93% / −49% / +3.43 | +1.58% / −49% / +4.08 | +3.17% / −48% / +5.67 |
| post-GFC | +12.22% | +12.68% / −15% / +0.46 | +12.63% / −17% / +0.41 | +9.63% / −20% / −2.59 |
| calm bull | +14.75% | +13.01% / −18% / −1.74 | +12.88% / −18% / −1.87 | +12.84% / −18% / −1.91 |
| COVID+22 | +7.32% | +5.76% / −25% / −1.56 | +5.90% / −25% / −1.43 | +5.70% / −25% / −1.62 |
| recent | +26.17% | +24.43% / −10% / −1.74 | +24.20% / −10% / −1.97 | +24.24% / −10% / −1.93 |
| **FULL** | **+10.68%** | **+10.60% / −49% / −0.07** | **+10.68% / −49% / +0.00** | **+10.04% / −48% / −0.63** |

## Final wealth comparison ($1M start, 17 years)

| Configuration | Final wealth |
|---|---|
| SPY only | $5,606,661 |
| 0.5%/yr ~23% OTM | $5,667,358 |
| 0.5%/yr ~35% OTM | $5,583,094 |
| 0.5%/yr ~50% OTM | $5,560,441 |
| 1.0%/yr ~23% OTM | $5,614,815 |
| 1.0%/yr ~35% OTM | $5,599,255 |
| 1.0%/yr ~50% OTM | $5,448,172 |
| 2.0%/yr ~23% OTM | $5,556,503 |
| 2.0%/yr ~35% OTM | $5,620,568 |
| 2.0%/yr ~50% OTM | $5,286,664 |
| 3.3%/yr ~23% OTM | $5,545,082 |
| 3.3%/yr ~35% OTM | $5,608,902 |
| 3.3%/yr ~50% OTM | $5,087,756 |

## The honest read

Under realistic accounting + annual budget semantics, the deep-OTM Spitznagel strategy **tracks SPY to within ±1pp at every budget × depth tested**. The biggest edge is +0.07pp (0.5% × ~23% OTM); the biggest drag is −0.63pp (3.3% × ~50% OTM). On final wealth: ±$580K out of $5.6M.

**What does survive:**
- During GFC sub-period, the strategy beats SPY by +0.4 to +5.7pp depending on budget × depth. Catastrophe protection is real but smaller than the pre-fix numbers suggested.
- Max drawdown is 1-3pp better during catastrophe windows (−49% vs SPY's −52% at 3.3%/yr).
- Calm periods show consistent small drag (the cost of insurance).

**What dies:**
- "Spitznagel deep-OTM strategy beats SPY by 2-12pp on annual return." Not in this 17-year SPY window with realistic accounting.
- The sweet-spot story — there's no budget × depth where the strategy clearly wins.

## Near-ATM ≠ deep OTM

For completeness: the near-ATM 3.3%/yr case (delta −0.40 to −0.25, NOT Spitznagel's recommendation) returns +13.33%/yr — beats SPY by +2.65pp. But that's a different strategy than what Spitznagel publishes; he recommends deep OTM specifically because near-ATM "wastes" premium on the in-the-money portion.
