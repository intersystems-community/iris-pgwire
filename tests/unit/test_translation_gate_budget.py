"""Constitution Principle V: measure what the translation gates cost.

> Any feature that adds latency to the query path MUST measure its own cost
> against the 5 ms budget before merge. "Probably fast enough" is not a
> measurement.

Feature 044 added four predicates that run on **every** statement, before any
rewrite happens, to decide whether a rewrite is needed at all:

    has_array_param                 ANY($n) membership
    has_boolean_projection          a boolean used as a value
    has_pg_function_call            obj_description() and friends
    has_boolean_literal_comparison  relispartition = 'f'

Only the second was measured when it landed. This test measures all four
together and fails if they ever eat a material share of the budget, so the
number cannot quietly drift.

Measured on this machine at the time of writing: 0.09 ms on a plain 30-column
query, 0.62 ms (12.4% of budget) on a paren-heavy one, where
`has_boolean_projection` dominates because it runs the parenthesis scanner over
every select-list item.

The threshold is deliberately far below 5 ms: these gates are pure string work
that runs *before* the translation the budget is actually for.
"""

from __future__ import annotations

import time

import pytest

from iris_pgwire.sql_translator.array_params import has_array_param
from iris_pgwire.sql_translator.boolean_expr import (
    has_boolean_literal_comparison,
    has_boolean_projection,
)
from iris_pgwire.sql_translator.pg_functions import has_pg_function_call

TRANSLATION_BUDGET_MS = 5.0

# No more than this share of the budget may go on deciding whether to translate.
GATE_SHARE_LIMIT = 0.25

GATES = (
    has_array_param,
    has_boolean_projection,
    has_pg_function_call,
    has_boolean_literal_comparison,
)

PLAIN = (
    "SELECT " + ", ".join(f"t.col{i}" for i in range(30)) + " FROM orders t "
    "WHERE t.status = $1 ORDER BY t.id"
)

# Parentheses defeat the cheap short-circuit in the projection gate, so this is
# the honest worst case for ordinary application SQL.
PAREN_HEAVY = (
    "SELECT " + ", ".join(f"COALESCE(t.col{i}, 0)" for i in range(30)) + " FROM orders t "
    "JOIN customers c ON (c.id = t.customer_id) "
    "WHERE (t.status = $1 AND t.total > 100) ORDER BY t.id"
)


def _gate_cost_ms(sql: str, iterations: int = 500) -> float:
    """Total wall-clock cost of running every gate once, in milliseconds."""
    start = time.perf_counter()
    for _ in range(iterations):
        for gate in GATES:
            gate(sql)
    return (time.perf_counter() - start) / iterations * 1000


@pytest.mark.parametrize(("label", "sql"), [("plain", PLAIN), ("paren-heavy", PAREN_HEAVY)])
def test_gates_stay_within_their_share_of_the_budget(label, sql):
    cost = _gate_cost_ms(sql)
    limit = TRANSLATION_BUDGET_MS * GATE_SHARE_LIMIT
    assert cost < limit, (
        f"{label}: deciding whether to translate costs {cost:.3f} ms, over the "
        f"{limit:.2f} ms allowed ({GATE_SHARE_LIMIT:.0%} of the {TRANSLATION_BUDGET_MS} ms "
        "Principle V budget). The gates run on every statement."
    )


def test_a_statement_needing_no_rewrite_is_cheap():
    """The common case — ordinary application SQL — must be nearly free."""
    cost = _gate_cost_ms(PLAIN)
    assert cost < 0.5, f"{cost:.3f} ms on a query with nothing to rewrite"


def test_every_gate_declines_ordinary_sql():
    """A gate that fires on ordinary SQL would put every query through a rewrite."""
    for gate in GATES:
        assert not gate(PLAIN), f"{gate.__name__} fired on a query with nothing to rewrite"
        assert not gate(PAREN_HEAVY), f"{gate.__name__} fired on ordinary parenthesised SQL"
