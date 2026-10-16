"""SONNET1-talents batch 1 (fix/HUNT177 Confirmed 3: Talents with empty typed effects and no
implementation): regression for each talent, through the table service with cold reload where the
printed text needs one, at the engine level where an existing general seam already carries it.
"""
from pathlib import Path

from combat import carry, summons, typed_executor
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ME, bundle
from tests.test_carry import KIT
from tests.test_summons import OWNER, _engine, _turn_of, _use

ROOT = Path(__file__).resolve().parents[1]


def _solo_engine(talents):
    b = bundle(talents, kit={"starting_kit": KIT})
    engine = Gate4ControllerEngine(ROOT, match_seed="SONNET1B1", typed_bundles=(b,),
                                   roster_setup={"primary_actor_ids": [ME, AN], "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, AN: {"x": 4, "y": 6}}})
    engine.state.current_actor_id = ME
    me = engine.state.actors[ME]
    me.action_available = me.bonus_action_available = me.reaction_available = True
    return engine, me


def test_flying_sword_technique_summons_a_controllable_flying_sword():
    engine = _engine(["TAL_SWORD_FLYING_SWORD_TECHNIQUE"])
    sword = summons.owned_by(engine, OWNER, "flying_sword")[0]
    assert not sword.active and sword.summon["status"] == "waiting"
    owner = engine.state.actors[OWNER]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".TAL_SWORD_FLYING_SWORD_TECHNIQUE")
    assert sword.active and sword.summon["status"] == "present" and sword.current_hp == sword.maximum_hp
    # printed flat statistics (no Cultivation Level or Proficiency Bonus scaling)
    assert sword.armor_class == 15 and sword.maximum_hp == 20 and sword.speed_ft == 40
    assert engine.grid.distance_ft(sword.position, owner.position) <= 30
    assert sword.team_id == owner.team_id and not sword.primary_combatant


def test_flying_sword_strike_hits_and_leaves_sword_intent():
    engine = _engine(["TAL_SWORD_FLYING_SWORD_TECHNIQUE"])
    sword = summons.owned_by(engine, OWNER, "flying_sword")[0]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, ".TAL_SWORD_FLYING_SWORD_TECHNIQUE")
    foe = engine.state.actors[next(aid for aid in engine.state.actors if aid != OWNER and aid != sword.entity_id)]
    foe.position = Position(x=sword.position.x + 1, y=sword.position.y, z=sword.position.z)
    foe.armor_class = 1  # guarantee the hit; the roll itself is covered by the shared attack pipeline
    engine.state.current_actor_id = sword.entity_id
    sword.action_available, sword.bonus_action_available = True, False
    attack = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(".attack0"))
    before = foe.current_hp
    engine.execute_intent(ActionIntent(intent_id="sword-strike", decision_id=attack.decision_id,
                                       candidate_id=attack.candidate_id, state_version=attack.state_version,
                                       actor_id=sword.entity_id, target_ids=attack.target_ids, destination=attack.destination))
    assert foe.current_hp < before
    assert typed_executor.bears_mark(foe, OWNER, "Sword Intent")
    assert not typed_executor.bears_mark(foe, sword.entity_id, "Sword Intent")


def _store(engine):
    store = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(".shadow_stash.store"))
    engine.execute_intent(ActionIntent(intent_id=f"store-{store.state_version}", decision_id=store.decision_id, candidate_id=store.candidate_id,
                                       state_version=store.state_version, actor_id=ME, target_ids=store.target_ids,
                                       destination=store.destination))


def test_shadow_stash_hides_a_weapon_weightless_and_disarmed_until_retrieved():
    engine, me = _solo_engine(["TAL_DARK_SHADOW_STASH"])
    dagger_key = next(item["key"] for item in carry.carrying_of(engine, me.entity_id)["items"] if "bi_shou" in item["key"])
    before = carry.weight(engine, me)
    assert carry.holds(engine, me, dagger_key)
    _store(engine)  # the only weapon offered (armour stays worn): the table's default pick, no human driving this test
    assert carry.weight(engine, me) < before
    assert not carry.holds(engine, me, dagger_key)
    me.bonus_action_available = True
    retrieve = next(c for c in engine.legal_candidates() if c.source_definition_id.endswith(".shadow_stash.retrieve"))
    engine.execute_intent(ActionIntent(intent_id="retrieve", decision_id=retrieve.decision_id, candidate_id=retrieve.candidate_id,
                                       state_version=retrieve.state_version, actor_id=ME, target_ids=retrieve.target_ids,
                                       destination=retrieve.destination))
    assert carry.weight(engine, me) == before
    assert carry.holds(engine, me, dagger_key)
    assert carry.holds(engine, me, dagger_key)
