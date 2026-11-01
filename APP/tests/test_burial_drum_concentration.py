"""Burial Drum holds Concentration on the real Gate4 engine (owner ruling, combat/rules/concentration.json: any number of
Concentration techniques, including copies of the same one; duplicate buffs do not stack).

Cast -> Concentration starts and the drum shows in concentration_effects. Recast -> both copies stay held; the drum's effect
still applies once to a creature in the aura. Ending Concentration -> only that copy's aura goes.

Uses the Thrum of the Grave fight fixture from tests/thrum_grave_support.py (no browser, no live server).
"""
from combat import concentration
from combat.presentation import CombatPresentationProjector
from combat import zones
from tests.thrum_grave_support import BEATS, FOE, ME, TG_ALL, fight, heal, turn, use

DRUM = "tianxia.tradition.spirit.thrum_of_the_grave.feature.burial_drum"
RESONANCE = "resource:core.resonance"


def _is_drum(source_id):
    # Runtime ids carry the typed prefix: "action:typed.<hash>.<printed record id>".
    return str(source_id).endswith(DRUM)


def _drums(engine):
    return [z for z in zones.typed_zones(engine) if _is_drum(z.source_definition_id) and z.owner_id == ME]


def test_casting_burial_drum_starts_concentration_and_shows_it():
    engine = fight(TG_ALL, dc=40, foe_at=(5, 6))
    me = engine.state.actors[ME]
    me.resources[RESONANCE] = 20
    use(engine, "Burial Drum")
    assert me.concentration is not None and _is_drum(me.concentration.source_definition_id)
    assert len(_drums(engine)) == 1 and _drums(engine)[0].concentration_link is True
    shown = CombatPresentationProjector._concentration_effects({"concentration": {"source_definition_id": me.concentration.source_definition_id}}, [])
    assert len(shown) == 1


def test_recasting_burial_drum_keeps_both_copies_and_the_effect_applies_once():
    engine = fight(TG_ALL, dc=40, foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.resources[RESONANCE] = 20
    use(engine, "Burial Drum")
    first = _drums(engine)[0].zone_id
    turn(engine, ME)  # a new turn: the action is back
    use(engine, "Burial Drum")
    # Both copies are held: the newest is current, the first is held, and each has its own aura.
    assert me.concentration is not None and _is_drum(me.concentration.source_definition_id)
    assert len(concentration.held(me)) == 1
    assert len(_drums(engine)) == 2 and first in {z.zone_id for z in _drums(engine)}
    # A creature in the aura gets one Wisdom save and one Gravebeat from one healing, not one per copy.
    foe.current_hp = 20
    heal(engine, FOE)
    assert foe.current_hp == 20 and me.resources[BEATS] == 1


def test_ending_concentration_removes_only_that_copys_aura():
    engine = fight(TG_ALL, dc=40, foe_at=(5, 6))
    me = engine.state.actors[ME]
    me.resources[RESONANCE] = 20
    use(engine, "Burial Drum")
    first = _drums(engine)[0].zone_id
    turn(engine, ME)  # a new turn: the action is back
    use(engine, "Burial Drum")
    engine._end_concentration(me, "TEST")  # the newest copy ends; the held one comes back as current
    assert [z.zone_id for z in _drums(engine)] == [first]
    assert me.concentration is not None and _is_drum(me.concentration.source_definition_id)
    engine._end_concentration(me, "TEST")
    assert _drums(engine) == [] and me.concentration is None
