"""Unit tests for the BacktestResults dataclass and the hash_data_file helper.

Constructs a small synthetic balance series and asserts the computed
properties return sensible values. Does not depend on the backtester engine
or any data fetch — these tests run in milliseconds and exercise just the
results module.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd

from options_portfolio_backtester.analytics.results import BacktestResults, hash_data_file


def _flat_balance(annual_return: float, years: float = 1.0, n: int = 252) -> pd.DataFrame:
    """Synthesise a balance series that grows at a constant compound rate."""
    dates = pd.date_range("2020-01-01", periods=int(years * n) + 1, freq="B")
    daily = (1 + annual_return) ** (1 / n) - 1
    values = [100_000.0]
    for _ in range(len(dates) - 1):
        values.append(values[-1] * (1 + daily))
    return pd.DataFrame({"total capital": values}, index=dates)


def test_construct():
    bal = _flat_balance(0.10, years=1.0)
    r = BacktestResults(balance=bal, trade_log=None, config={"key": "value"})
    assert r.engine_version != ""
    assert r.config == {"key": "value"}
    assert r.trade_log is None


def test_annual_return_matches_constant_growth():
    bal = _flat_balance(0.10, years=2.0)
    r = BacktestResults(balance=bal, trade_log=None, config={})
    assert abs(r.annual_return - 10.0) < 0.5


def test_max_drawdown_zero_for_monotone_growth():
    bal = _flat_balance(0.05, years=1.0)
    r = BacktestResults(balance=bal, trade_log=None, config={})
    assert r.max_drawdown == 0.0


def test_max_drawdown_negative_when_decline_present():
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    bal = pd.DataFrame({"total capital": [100.0, 110.0, 80.0, 90.0, 95.0]}, index=dates)
    r = BacktestResults(balance=bal, trade_log=None, config={})
    # Peak at 110, trough at 80 → -27.27% drawdown
    assert -28.0 < r.max_drawdown < -27.0


def test_volatility_and_sharpe_for_constant_growth():
    bal = _flat_balance(0.10, years=1.0)
    r = BacktestResults(balance=bal, trade_log=None, config={})
    assert r.annualized_volatility < 0.01
    assert r.sharpe_ratio >= 0.0


def test_summary_contains_expected_keys():
    bal = _flat_balance(0.10, years=1.0)
    r = BacktestResults(
        balance=bal,
        trade_log=pd.DataFrame({"entry_date": ["2020-01-02"], "pnl": [100.0]}),
        config={"alloc": "test"},
        data_hash="abc123",
    )
    s = r.summary()
    assert set(s.keys()) >= {
        "annual_return", "max_drawdown", "volatility", "sharpe",
        "trades", "engine_version", "data_hash",
    }
    assert s["trades"] == 1
    assert s["data_hash"] == "abc123"


def test_hash_data_file_deterministic():
    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "a.bin"
        p2 = Path(td) / "b.bin"
        p3 = Path(td) / "c.bin"
        p1.write_bytes(b"deterministic-test-bytes")
        p2.write_bytes(b"deterministic-test-bytes")
        p3.write_bytes(b"different-content-bytes")
        h1 = hash_data_file(p1)
        h2 = hash_data_file(p2)
        h3 = hash_data_file(p3)
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 64


def test_hash_data_file_streams_large_files():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "large.bin"
        with open(p, "wb") as f:
            for _ in range(5):
                f.write(b"\x00" * (1024 * 1024))
        h = hash_data_file(p, chunk_size=4096)
        h2 = hashlib.sha256(b"\x00" * (5 * 1024 * 1024)).hexdigest()
        assert h == h2
