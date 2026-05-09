"""
conftest.py — pytest fixtures shared across the test suite.

Patterns:
- mock_supabase: drop-in replacement for the supabase client. Lets reconciler
  tests run without touching the live DB. Returns empty data for all queries
  by default; individual tests override return values for specific chains.
- supabase_with: factory that builds a mock supabase pre-loaded with rows.
"""

import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_supabase():
    """
    A bare MagicMock-based supabase client. Empty data for every query chain
    by default. Tests can override specific chains by reassigning
    `mock.table.return_value.select.return_value...execute.return_value.data`.

    Use `supabase_with` if you want fixture-style row preloading.
    """
    mock = MagicMock()
    # The bottom of every supabase chain is .execute() returning an object with .data
    # MagicMock auto-creates intermediate attributes; we just need to set the leaf.
    empty = MagicMock(data=[], count=0)
    # Common chains used by purchase_reconciler:
    mock.table.return_value.select.return_value.execute.return_value = empty
    mock.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = empty
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = empty
    mock.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = empty
    mock.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = empty
    mock.table.return_value.select.return_value.eq.return_value.neq.return_value.execute.return_value = empty
    # Writes return an empty success-like object
    mock.table.return_value.upsert.return_value.execute.return_value = empty
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = empty
    mock.table.return_value.delete.return_value.eq.return_value.execute.return_value = empty
    return mock


@pytest.fixture
def supabase_with():
    """
    Factory fixture: returns a function that builds a mock supabase preloaded
    with rows for a given table.

    Usage:
        def test_something(supabase_with):
            sb = supabase_with({"confirmed_purchases": [{"ticker": "MSTR", ...}]})
            # ... assert behavior
    """
    def _build(rows_by_table):
        mock = MagicMock()
        empty = MagicMock(data=[], count=0)
        # Default: empty for unknown tables
        mock.table.return_value.select.return_value.execute.return_value = empty
        mock.table.return_value.upsert.return_value.execute.return_value = empty
        mock.table.return_value.update.return_value.eq.return_value.execute.return_value = empty

        # Per-table preloading: when .table("X") is called with a known X,
        # return a child mock whose select chains return the preloaded rows.
        original_table = mock.table

        def table_dispatch(name):
            if name in rows_by_table:
                t = MagicMock()
                preloaded = MagicMock(data=rows_by_table[name], count=len(rows_by_table[name]))
                t.select.return_value.execute.return_value = preloaded
                t.select.return_value.order.return_value.limit.return_value.execute.return_value = preloaded
                t.select.return_value.eq.return_value.execute.return_value = preloaded
                t.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = preloaded
                t.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = preloaded
                t.upsert.return_value.execute.return_value = MagicMock(data=[], count=0)
                t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[], count=0)
                t.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[], count=0)
                return t
            return original_table(name)

        mock.table = MagicMock(side_effect=table_dispatch)
        return mock

    return _build
