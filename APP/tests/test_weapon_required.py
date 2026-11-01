"""A Spear or saber talent needs that weapon (fight audit 2026-09-29: Intercepting Thrust fired four times with a staff for
no damage, spending the Reaction and a Spear Resource each time)."""

from combat import typed_reactions
from combat.ext import weapon_required
from tests.test_reaction_reach import _engine, ME

ROW = {"feature_id": "TAL_SPEAR_INTERCEPTING_THRUST", "name": "Intercepting Thrust", "kind": "enters_range", "costs": [],
       "effects": [{"type": "attach_spear_weapon"}, {"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": []}]}


def test_a_spear_reaction_waits_for_a_spear(monkeypatch):
    engine = _engine({"x": 1, "y": 1}, {"x": 2, "y": 1})
    me = engine.state.actors[ME]
    me.reaction_available = True
    assert not typed_reactions._can_trigger(engine, me, ROW)
    assert typed_reactions._can_trigger(engine, me, {**ROW, "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1}]})
    monkeypatch.setattr(weapon_required, "_carries", lambda engine, actor, words: "spear" in words)
    assert typed_reactions._can_trigger(engine, me, ROW)
