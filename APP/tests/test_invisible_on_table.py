"""An Invisible or Hidden fighter is left off the other side's view unless someone there perceives it (owner 2026-09-29)."""

from combat import senses
from combat.tabletop_service import TabletopService
from tests.test_effect_durations import _fight


def _invisible(engine, actor):
    engine._apply_condition(actor, "condition:typed.invisible", "test:invisibility", actor.entity_id, expires_on="UNTIL_REMOVED")


def test_only_the_invisible_fighters_own_side_perceives_it_by_default():
    engine, me, foe = _fight("INVISIBLE")
    assert foe.entity_id in senses.perception(engine, me)["creatures"]
    _invisible(engine, foe)
    allies = sorted(a.entity_id for a in engine.state.actors.values() if a.active and a.team_id == foe.team_id and a is not foe)
    assert all(foe.entity_id in senses.perception(engine, engine.state.actors[aid])["creatures"] for aid in allies)
    assert foe.entity_id not in senses.perception(engine, me)["creatures"]


def test_blindsight_or_tremorsense_perceives_it(monkeypatch):
    engine, me, foe = _fight("INVISIBLE")
    _invisible(engine, foe)
    monkeypatch.setattr(senses, "perceives", lambda engine, viewer, seen, **kw: viewer is me)
    assert foe.entity_id in senses.perception(engine, me)["creatures"]
    monkeypatch.setattr(senses, "perceives", lambda *args, **kw: False)
    monkeypatch.setattr(senses, "pinpoints", lambda engine, viewer, seen: viewer is me)
    assert foe.entity_id in senses.perception(engine, me)["creatures"]


def test_hidden_counts_too():
    engine, me, foe = _fight("INVISIBLE")
    engine._apply_condition(me, "condition:typed.hidden", "test:hide", me.entity_id, expires_on="UNTIL_REMOVED")
    assert me.entity_id not in senses.perception(engine, foe)["creatures"]
