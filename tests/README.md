# Test suite layout

The suite is organized by **intent**, in tiers. If you're adding a test,
pick the tier by asking *what failure it is supposed to catch*.

| Tier | Where | Runs | What it catches |
|------|-------|------|-----------------|
| **Unit** | `tests/<module>/` mirroring the package (`engine/`, `data/`, `strategy/`, `execution/`, `portfolio/`, `analytics/`, `core/`) | default suite | a module's behavior in isolation |
| **Oracles** | `tests/oracles/` | default suite (+ CI `article-reproduction` job for the data-dependent one) | engine-level correctness against *independent* references — see below |
| **Heavy / opt-in** | `tests/bench/` | `pytest tests/bench -o addopts=""` and the CI `article-reproduction` job | data-heavy invariants at production scale (17-year SPY chain), property suites, edge cases. Misnamed historically — these are correctness tests, not benchmarks; performance benchmarks live in `/benchmarks` |
| **Legacy-gated** | `tests/compat/`, `tests/convexity/` | explicitly only (ignored in `pyproject.toml` addopts) | compatibility with external libs / the convexity research module |

## What "oracle" means here

Every entry in `tests/oracles/` checks the engine against a reference that
is **computed outside the engine's own code paths**, so an engine bug
cannot corrupt the expectation along with the result:

- `test_golden_scenario.py` — a synthetic crash whose final capital is
  derived by **paper arithmetic** in comments and asserted to the cent.
  Catches value *vanishing* as well as phantom money.
- `test_regression_guards.py` — algebraic identities (zero budget ≡
  stock-only; unfilled budget fully clawed back; per-rebalance ≠ annual
  knob) plus the unknown-config seal.
- `test_engine_fuzz.py` — hypothesis samples the data × config space and
  requires the engine to pass its own runtime invariants
  (`assert_invariants=True`) on every example.
- `test_article_reproduction.py` — pins the published-article tables
  (needs the SPY dataset; skips without it; CI provides it from cache).

History motivates the split: six correctness bugs (see CHANGELOG) passed
the unit tier because both sides of each assertion flowed through the
same buggy code. Oracles exist so that cannot happen again.
