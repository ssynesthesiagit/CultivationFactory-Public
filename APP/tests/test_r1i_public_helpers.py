"""Shared rider contracts are public and retain stable semantics."""
from types import SimpleNamespace
from combat.ext.arcs import arc_state
from combat.ext.needle import cell_id
from combat.ext.rider_outcomes import settle


def test_public_arc_ledger_and_cell_option_contracts():
    ctx = SimpleNamespace(damage_cache={})
    assert arc_state(ctx) is arc_state(ctx)
    assert arc_state(ctx) == {"before": {}, "hit": [], "primary": None, "failed": []}
    assert cell_id(SimpleNamespace(x=2, y=6)) == "cell:2,6"
    assert settle.__doc__
