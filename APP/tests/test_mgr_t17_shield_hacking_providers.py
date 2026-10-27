"""Shield-Hacking against real temporary shield and Glass Prison providers."""
import pytest

from combat.ext import sand_riders, shield_riders
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from tests import test_mgr_t17_shield_hacking_rhythm as base

ALLY = "actor:test.cover_holder"


def fight():
    sheet = base.t._sheet("tianxia.sphere.shield", ["TAL_SHIELD_COVER_ALLY"], base.SHIELD_KIT)
    ally = compile_character(sheet, actor_id=ALLY)
    sand = base.t._sheet("tianxia.sphere.sand", ["TAL_SAND_GLASS_PRISON"], {}, cl=12)
    sand_bundle = compile_character(sand, actor_id="actor:test.sand")
    engine = Gate4ControllerEngine(
        base.ROOT, match_seed="MGR17-PROVIDERS",
        typed_bundles=(base._saber_bundle(), base._foe_bundle(shield=False), ally, sand_bundle),
        roster_setup={"primary_actor_ids": [base.ME, base.AN, ALLY, "actor:test.sand"],
                      "team_by_actor": {base.ME: "team:a", base.AN: "team:b", ALLY: "team:b", "actor:test.sand": "team:a"},
                      "starting_positions": {base.ME: {"x": 3, "y": 6}, base.AN: {"x": 4, "y": 6},
                                             ALLY: {"x": 5, "y": 6}, "actor:test.sand": {"x": 3, "y": 8}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(base.ME)
    engine.state.current_actor_id = base.ME
    engine._system_start_turn()
    me, foe = engine.state.actors[base.ME], engine.state.actors[base.AN]
    me.resources[base.EDGE] = 1
    foe.armor_class = -50
    return engine, foe


def grant(engine, foe, provider):
    if provider == "cover":
        ally = engine.state.actors[ALLY]
        assert shield_riders.rows(engine, ally, "cover_ally")
        engine._apply_condition(ally, shield_riders.EXTENSIVE, "system:test", ALLY,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Extensive Defense"})
    elif provider == "echo":
        engine._apply_condition(foe, shield_riders.ECHO, "system:test", ALLY,
                                expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": "Second Answer"})
    else:
        action = next(a for a in engine.action_catalog.values()
                      if sand_riders.mechanic_of(a) == sand_riders.PRISON)
        engine._apply_condition(foe, sand_riders.RESTRAINED, action.source_definition_id,
                                "actor:test.sand", expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "Glass Prison"})


@pytest.mark.parametrize("provider", ["cover", "echo", "prison"])
def test_provider_offers_rider_and_consuming_attack_loses_its_ac(provider):
    engine, foe = fight()
    grant(engine, foe, provider)
    assert engine._ac_modifier(foe) == 2
    assert base.RHYTHM in base._names(engine)
    base._hit_with(engine, base.RHYTHM)
    assert any(c.condition_id == base.CONDITION for c in foe.conditions.values())
    # Second Answer itself is spent on the triggering attack; replace it to test
    # a new echo being denied by the still-held Shield-Hacking condition.
    if provider == "echo":
        grant(engine, foe, provider)
    from combat.ext.sabers_riders import shield_hacking_takes_the_bonus
    assert shield_hacking_takes_the_bonus(engine, foe) == -2
    from combat import ext
    assert engine._ac_modifier(foe) == 0, [(f.__module__, f.__name__, v) for f, v in ext.run('ac', engine, foe, _with_handlers=True)]
    base._names(engine)
    assert engine._ac_modifier(engine.state.actors[base.AN]) == 0
    before = len(engine.events)
    base._hit_with(engine, "Forward Cut")
    rolled = next(e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and e.actor_id == base.ME)
    assert rolled.payload["target_ac"] == foe.armor_class
    assert not any(c.condition_id == base.CONDITION for c in foe.conditions.values())
