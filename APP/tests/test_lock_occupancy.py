"""Default-inert shared occupancy contract; no game rules are granted by a hook."""
import pytest

from combat import ext
from tests.test_auto_tabik import _engine, ME, AN


def pair_engine(monkeypatch):
    e, _ = _engine([])
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "shared_occupancy", [
        lambda engine, left, right: {"rider_id": ME, "mount_id": AN}])
    original = e._actor_cells

    def cells(actor, position=None):
        if actor.entity_id == AN:
            p = position or actor.position
            return tuple((p.x + x, p.y + y) for x in range(2) for y in range(2))
        return original(actor, position)

    monkeypatch.setattr(e, "_actor_cells", cells)
    return e


def test_default_overlap_rejected_and_transaction_rolled_back():
    e, _ = _engine([])
    before = e.state.model_dump(mode="json")
    with pytest.raises(ValueError, match="occupied footprint invariant"):
        with e._transaction("test:mount", "test:overlap", ME):
            e.state.actors[ME].position = e.state.actors[AN].position
    assert e.state.model_dump(mode="json") == before


def test_valid_pair_shares_cells_and_mutual_collision_only(monkeypatch):
    e = pair_engine(monkeypatch)
    e.state.actors[ME].position = e.state.actors[AN].position
    e._assert_invariants()
    assert not set(e._actor_cells(e.state.actors[AN])) & e._occupied_cells_except(ME)
    assert not set(e._actor_cells(e.state.actors[ME])) & e._occupied_cells_except(AN)
    third = e.state.actors[ME].model_copy(deep=True, update={"entity_id": "actor:third"})
    e.state.actors[third.entity_id] = third
    with pytest.raises(ValueError, match="occupied footprint invariant"):
        e._assert_invariants()


def test_unvalidated_and_equal_size_pairs_fail(monkeypatch):
    e, _ = _engine([])
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "shared_occupancy", [
        lambda *args: {"rider_id": ME, "mount_id": AN}])
    e.state.actors[ME].position = e.state.actors[AN].position
    with pytest.raises(ValueError, match="occupied footprint invariant"):
        e._assert_invariants()
