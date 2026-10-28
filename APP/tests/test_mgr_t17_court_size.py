"""Court's printed grapple-only size step: scoped to acting, owned by the Court row, and proved through a committed table reload."""
from types import SimpleNamespace

import pytest

from combat.ext import wrestling
from combat.ext.effective_size import rank
from tests.test_c2_review import action, reload, send, table_fixture, until_turn
from tests.test_riders_c2 import ATK, ME, _sheet

COURT_ROW = {"block": "wrestling", "kind": "court"}


class _Engine:
    def __init__(self, actor, rows=(COURT_ROW,)):
        self.actor_footprints = {
            actor.entity_id: SimpleNamespace(width_cells=1, height_cells=1)
        }
        self.typed_passive_rows = {actor.entity_id: list(rows)}

    def _footprint(self, actor):
        return SimpleNamespace(width_cells=1)


def _actor(court):
    return SimpleNamespace(
        entity_id="court-user",
        size_category="Medium",
        transformed_size_category=None,
        conditions={
            "court": SimpleNamespace(condition_id=wrestling.COURT)
        } if court else {},
    )


def test_court_size_step_applies_only_while_acting_on_grapple():
    actor = _actor(True)
    engine = _Engine(actor)
    assert rank(engine, actor, "act", {"grapple"}) == 3
    assert rank(engine, actor, "resist", {"grapple"}) == 2
    assert rank(engine, actor, "act", {"shove"}) == 2

    actor.conditions.clear()
    assert rank(engine, actor, "act", {"grapple"}) == 2
    assert wrestling.court_size_steps(engine, actor, "act", {"grapple"}) is None


def test_court_size_step_needs_the_owned_row():
    actor = _actor(True)
    engine = _Engine(actor, rows=())
    assert rank(engine, actor, "act", {"grapple"}) == 2
    assert wrestling.court_size_steps(engine, actor, "act", {"grapple"}) is None


def _grapple_offered(table, mid, target):
    menu = table.state(mid)["menu"]
    return any(g["label"] == "Grapple" and any(target in o.get("target_ids", []) for o in g["options"])
               for g in menu["actions"])


@pytest.mark.parametrize("court,category,offered", [
    (True, "Huge", True),         # Medium acting + Court step = Huge limit: the newly legal Grapple target
    (True, "Gargantuan", False),  # one size beyond the Court step still refuses
    (False, "Huge", False),       # without the active Court state the Huge target stays refused
])
def test_court_grapple_size_is_committed_and_reloaded(tmp_path, court, category, offered):
    foe = _sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"])
    foe["identity"]["size"] = category
    combat, table, mid = table_fixture(tmp_path, {
        ME: _sheet(["TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE"], cl=17),
        ATK: foe,
    }, {ME: (3, 6), ATK: (4, 6)}, seed="MGR-T17-COURT-SIZE", foes=(ATK,))
    until_turn(table, mid, ME)
    if court:
        assert send(table, mid, action(table, mid, "Court of the Closed Distance", ME))["status"] == "COMMITTED"
    reload(tmp_path, mid)
    assert _grapple_offered(table, mid, ATK) == offered
