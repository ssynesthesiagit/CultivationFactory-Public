"""Court's printed grapple-only size step: scoped to acting, owned by the Court row, and proved through a committed table reload."""
from types import SimpleNamespace

import pytest

from combat.ext import wrestling
from combat.ext.effective_size import rank
from combat.gate2_runtime_models import ActionIntent, Position
from tests.test_c2_review import action, reload, send, sheet, table_fixture, until_turn
from tests.test_riders_c2 import ATK, ME


def payloads(events, kind):
    return [e.payload or {} for e in events if e.event_type == kind]

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


def _grapple(engine, target_id):
    """Grapple through the engine; a refused size gate runs no save (same admission signal as test_riders_c7)."""
    matches = [c for c in engine.legal_candidates()
               if c.display_name == "Grapple" and c.actor_id == ME and target_id in (c.target_ids or ())]
    if not matches:
        return False
    candidate = matches[0]
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"mgr-t17-court-{start}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids, destination=candidate.destination))
    return bool(payloads(engine.events[start:], "SAVE_ROLLED"))


def _footprint(engine, actor_id, width):
    engine.actor_footprints[actor_id] = engine._footprint(actor_id).model_copy(update={
        "width_cells": width, "height_cells": width,
        "occupied_relative_cells": tuple(Position(x=x, y=y) for x in range(width) for y in range(width))})


@pytest.mark.parametrize("court,width,admitted", [
    (True, 3, True),    # Huge target (3 cells): Medium + Court step reaches it, the newly legal Grapple
    (True, 4, False),   # Gargantuan target (4 cells): still two sizes beyond the acting rank
    (False, 3, False),  # Huge target without the Court state: refused as before
])
def test_court_grapple_size_is_committed_and_reloaded(tmp_path, court, width, admitted):
    combat, table, mid = table_fixture(tmp_path, {
        ME: sheet(["TAL_WRESTLING_COURT_OF_THE_CLOSED_DISTANCE"], initiative=20, cl=17),
        ATK: sheet(["TAL_ALCHEMY_CALMING_HEART_PILL"]),
    }, {ME: (3, 6), ATK: (4, 4)}, seed="MGR-T17-COURT-SIZE", foes=(ATK,))
    until_turn(table, mid, ME)
    if court:
        assert send(table, mid, action(table, mid, "Court of the Closed Distance", ME))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == wrestling.COURT for c in engine.state.actors[ME].conditions.values()) == court
    _footprint(engine, ATK, width)
    assert _grapple(engine, ATK) == admitted
