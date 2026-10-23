"""Wax sphere automation (auto lane AUTO15, round 24): the printed effects the engine now resolves itself.

Every test here drives the real table (compiled character, live engine, printed action) and asserts what the owner's
printed text says happens.  Each one fails on the branch this lane started from:

* **Flowing Wax Step** -- "you ignore Difficult Terrain" and "your movement does not provoke Opportunity Attacks from
  creatures standing in that wax" were a GM note; the record had no effects at all.
* **Mold Wax: Soft Spread** / **White Wax Edict of Stillness** -- "The area is Difficult Terrain for hostile creatures"
  was never applied: the compiled zone carried no terrain policy.
* **Candle Procession** -- its 10-foot radius was compiled as Difficult Terrain for *everyone*, which the printed text
  never says (its only Difficult Terrain line is an ally benefit).
* **Wax Cage** / **Wax Tomb** -- the held creature had no way out of the wax.
* **Court of Ten Thousand Candles** -- "Allies in the court ignore Difficult Terrain created by your Wax talents".
* **Living Wax Form: Wick Body** -- "The first time each round a creature hits you with a melee attack, you may use your
  Reaction to deal fire damage equal to your Proficiency Bonus".
* **Molten Snare** -- "the creature takes fire damage equal to your Proficiency Bonus whenever it moves willingly or is
  moved through the wax" (the point CP was charged; nothing ever burned).
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat import motion, typed_executor, zones
from combat.ext import effect_durations, states, wax_footing
from combat.ext.wax_reactions import WICK_BODY
from combat.factory_compiler import TYPED_AUTHORITY, compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, EconomyKind, Position
from tests.test_auto_support import ME, _engine
from tests.test_effect_durations import _end_turn
from tests.test_zones import SHEET

FAILS = 30  # the foe's saving throw never succeeds against this DC
REVIEW = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d/review_sw-water.json"
ELEMENTS = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d/elements.json"


@lru_cache(maxsize=None)
def _mechanics(path: str) -> dict:
    return json.loads(Path(path).read_text())["mechanics"]


def _authority() -> dict:
    return _mechanics(str(TYPED_AUTHORITY))


@lru_cache(maxsize=None)
def _bundle(talents: tuple, cl: int, dc: int) -> dict:
    sphere = "tianxia.sphere.wax"
    base = [key for key, row in _authority().items() if row.get("sphere_id") == sphere and row["kind"] == "base_ability"]
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": dc}
    sheet = {**SHEET, "identity": {**SHEET["identity"], "cultivation_level": cl}, "ability_scores_and_statistics": stats,
             "spheres_and_talents": {"sphere_record_ids": [sphere], "automatic_sphere_component_record_ids": base,
                                     "learned_talent_record_ids": list(talents)}}
    return copy.deepcopy(compile_character(sheet, actor_id=ME))


def _fight(talents, *, cl: int = 10, dc: int = FAILS, foe_at=(4, 6), ally=False):
    bundle = _bundle(tuple(talents), cl, dc)
    engine = _engine(bundle, foe_at=foe_at)
    if ally:
        engine.state.actors[AN].team_id = engine.state.actors[ME].team_id
    return bundle, engine


def _do(engine, name, target=None, actor=ME) -> None:
    candidates = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or tuple(c.target_ids) == (target,))]
    assert candidates, f"{name!r} is not offered: {sorted({c.display_name for c in engine.legal_candidates()})[:14]}"
    candidate = candidates[0]
    engine.execute_intent(ActionIntent(intent_id="do", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _cast(engine, prefix: str, near=None) -> None:
    """Use the area ability whose name starts with ``prefix``, placed on the square nearest ``near`` (the foe by default)."""
    goal = near or (engine.state.actors[AN].position.x, engine.state.actors[AN].position.y)
    where = lambda c: 0 if c.destination is None else abs(c.destination.x - goal[0]) + abs(c.destination.y - goal[1])  # noqa: E731
    candidates = [c for c in engine.legal_candidates() if c.display_name.startswith(prefix)]
    assert candidates, f"{prefix!r} is not offered"
    candidate = min(candidates, key=where)
    engine.execute_intent(ActionIntent(intent_id="cast", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _has(actor, condition_id: str) -> bool:
    return any(row.condition_id == condition_id for row in actor.conditions.values())


def _walk_to(engine, actor_id: str) -> None:
    """End real turns until ``actor_id`` is the creature whose turn it is."""
    for _ in range(2 * len(engine.state.initiative_order) + 2):
        if engine.state.current_actor_id == actor_id:
            return
        _end_turn(engine)
    raise AssertionError(f"{actor_id} never came around: {engine.state.current_actor_id}")


def _acting(engine, actor_id: str) -> None:
    """Put ``actor_id``'s turn at the front of the round and begin it, so the printed order the test needs really holds.

    A creature that is already acting is left alone: beginning its turn twice spends the turn's own bookkeeping twice.
    """
    if engine.state.current_actor_id == actor_id:
        return
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()


def _apply_sovereign(engine, owner) -> None:
    """"Thousand-Faced Wax Sovereign ... For the duration, you gain the following benefits", running on its owner.

    The printed state the wax_reactions plug-in asks about, put there the way the record's own ``state`` row puts it there, so
    the test exercises the printed Reaction (a real confirmed hit answering it) and its clock.
    """
    row = next(action for action in engine.action_catalog.values()
               if "TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN" in str(action.source_definition_id))
    typed = dict((row.parameters or {}).get("typed") or {})
    states.state(typed_executor.Context(engine, owner, row, None, {**typed, "numbers": {}}, [], None, {}),
                 {"type": "state", "name": "thousand_faced_wax_sovereign", "duration": "one_hour"})
    assert states.active(engine, owner, "thousand_faced_wax_sovereign") is not None


def _wax_cells(engine, who) -> set:
    return {(cell.x, cell.y) for zone in zones.typed_zones(engine)
            if wax_footing.MOLD_WAX in str(zone.source_definition_id) or wax_footing.COURT in str(zone.source_definition_id)
            for cell in zone.affected_cells}


def _without_set_body_record(do):
    """Run ``do`` with the Set Body hit-point record switched off, which is what the engine did before it existed.

    Everything else is the real fight: the form's own state, the Temporary Hit Points it granted, and the recorded grant that
    put them there. A saved fight from before this lane has exactly this shape.
    """
    from combat.ext import wax_footing

    recorded = wax_footing._record_set_body_pool
    wax_footing._record_set_body_pool = lambda *a, **k: None
    try:
        return do()
    finally:
        wax_footing._record_set_body_pool = recorded


# --------------------------------------------------------------------------- Flowing Wax Step: footing, and no strike out of your own wax
def test_flowing_wax_step_excuses_yielding_surfaces_until_your_turn_ends():
    # "Until the end of your turn, you ignore Difficult Terrain created by wax, mud, snow, shallow water, slick stone, or
    # similar yielding surfaces": before the review the record had no effects and the GM applied it by hand.
    _, engine = _fight(["TAL_WAX_FLOWING_WAX_STEP"])
    me = engine.state.actors[ME]
    assert not motion.ignores_difficult(engine, me)
    _do(engine, "Flowing Wax Step")
    from combat.gate2_runtime_models import ZoneState
    wax = ZoneState(zone_id="test:wax", source_definition_id="test:wax", owner_id=ME,
                    center=me.position, affected_cells=(me.position,), radius_cells=0,
                    concentration_link=False, created_round=engine.state.round_number,
                    trigger_profile={"name": "Soft Wax", "difficult": "all"})
    stone = wax.model_copy(update={"zone_id": "test:rubble", "trigger_profile": {"name": "Rigid Rubble", "difficult": "all"}})
    assert states.active(engine, me, "flowing_wax_step") is not None
    assert not zones.zone_is_difficult(engine, wax, me)
    assert zones.zone_is_difficult(engine, stone, me)
    _end_turn(engine)
    assert zones.zone_is_difficult(engine, wax, me)


def test_flowing_wax_step_stops_an_opportunity_attack_from_a_creature_standing_in_your_wax():
    # "If you move through your own Soft Wax this turn, that movement does not provoke Opportunity Attacks from creatures
    # standing in that wax."
    _, engine = _fight(["TAL_WAX_FLOWING_WAX_STEP", "TAL_WAX_MOLD_WAX"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Flowing Wax Step")
    _cast(engine, "Mold Wax: Soft Spread", near=(6, 6))
    wax = [zone for zone in zones.typed_zones(engine) if wax_footing.MOLD_WAX in zone.source_definition_id]
    assert wax, "the Soft Spread did not make a wax area"
    foe.position = wax[0].affected_cells[len(wax[0].affected_cells) // 2].model_copy()
    me.position = wax[0].affected_cells[0].model_copy()  # the mover is inside the wax too: the printed line is about the reactor
    assert wax_footing.soft_wax_opportunity(engine, foe, me) is False


def test_flowing_wax_step_leaves_other_opportunity_attacks_alone():
    # The plug-in is inert without its own state, and inert for a creature that is not standing in the wax.
    _, engine = _fight(["TAL_WAX_MOLD_WAX"])
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert wax_footing.soft_wax_opportunity(engine, foe, me) is None
    _cast(engine, "Mold Wax: Soft Spread", near=(6, 6))
    wax = [zone for zone in zones.typed_zones(engine) if wax_footing.MOLD_WAX in zone.source_definition_id]
    assert wax
    inside = wax[0].affected_cells[0]
    me.position = Position(x=inside.x, y=inside.y)
    assert wax_footing.soft_wax_opportunity(engine, foe, me) is None  # the foe is not in the wax, so its strike stands


def test_flowing_wax_step_keeps_the_strike_when_you_are_not_moving_through_your_wax():
    # "**If you move through your own Soft Wax this turn**, that movement does not provoke Opportunity Attacks from creatures
    # standing in that wax." A creature standing in the caster's wax lost its strike for the whole turn even while the caster
    # walked about on open ground, because nothing checked that the movement went through the wax at all.
    from combat.gate2_runtime_models import Position

    _, engine = _fight(["TAL_WAX_FLOWING_WAX_STEP", "TAL_WAX_MOLD_WAX"], foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Flowing Wax Step")
    _cast(engine, "Mold Wax: Soft Spread", near=(6, 6))
    wax = [zone for zone in zones.typed_zones(engine) if wax_footing.MOLD_WAX in zone.source_definition_id][0]
    foe.position = wax.affected_cells[len(wax.affected_cells) // 2].model_copy()
    me.position = Position(x=2, y=2)  # far from the caster's own wax, on open ground
    assert not any(cell.x == 2 and cell.y == 2 for cell in wax.affected_cells)
    assert wax_footing.soft_wax_opportunity(engine, foe, me) is None, \
        "a creature standing in your wax lost its strike to a movement that never touched the wax"


# --------------------------------------------------------------------------- the areas that are Difficult Terrain for enemies
def test_soft_spread_is_difficult_terrain_for_hostiles_and_not_for_allies():
    # "Soft Spread ... The area is Difficult Terrain for hostile creatures": the zone carried no terrain policy at all.
    _, engine = _fight(["TAL_WAX_MOLD_WAX"], foe_at=(5, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "Mold Wax: Soft Spread")
    cells = _wax_cells(engine, me)
    assert cells, "the Soft Spread made no area"
    first, last = sorted(cells)[0], sorted(cells)[-1]
    foe.position = type(foe.position)(x=first[0], y=first[1])
    assert any(cell in cells for cell in zones.difficult_cells(engine, foe)), "the hostile creature still walks through the wax freely"
    me.position = type(me.position)(x=last[0], y=last[1])
    assert not any(cell in cells for cell in zones.difficult_cells(engine, me)), "your own wax slowed you down"


def test_white_wax_edict_makes_its_area_difficult_for_hostiles():
    # "White wax seals spread across the ground ... Hostile creatures treat the area as Difficult Terrain."
    bundle, engine = _fight(["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"], cl=15, foe_at=(14, 6))
    spec = next(row["parameters"]["typed"]["zone_spec"] for row in bundle["action_catalog"]
                if row["source_definition_id"].endswith("TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"))
    assert spec["difficult"] == "hostile"


def test_candle_procession_is_not_difficult_terrain_for_anyone():
    # Its printed text says nothing about the ground being hard to cross; the compiled zone made it Difficult Terrain for
    # everyone, because the ally benefit's sentence was the only "Difficult Terrain" the compiler could see.
    bundle, _ = _fight(["TAL_WAX_CANDLE_PROCESSION"])
    spec = next(row["parameters"]["typed"]["zone_spec"] for row in bundle["action_catalog"]
                if row["source_definition_id"].endswith("TAL_WAX_CANDLE_PROCESSION"))
    assert spec["difficult"] is None


# --------------------------------------------------------------------------- a way out of the wax
def test_wax_cage_gives_the_held_creature_its_own_break_free_action():
    # "A restrained creature can use its Action to attempt a Strength (Athletics) or Dexterity (Acrobatics) check against
    # your Cultivation Save DC, ending the restraint on a success."
    _, engine = _fight(["TAL_WAX_WAX_CAGE"], foe_at=(4, 6))
    foe = engine.state.actors[AN]
    _do(engine, "Wax Cage", target=AN)
    assert _has(foe, "condition:typed.restrained")
    engine.state.current_actor_id = AN
    assert any("break free" in candidate.display_name.lower() for candidate in engine.legal_candidates()), \
        sorted({c.display_name for c in engine.legal_candidates()})


def test_wax_tomb_gives_the_sealed_creature_its_own_strength_save_to_break_free():
    # "A sealed creature can use its Action to attempt a Strength saving throw against your Cultivation Save DC, breaking
    # free on a success."
    _, engine = _fight(["TAL_WAX_WAX_TOMB"], foe_at=(4, 6))
    foe = engine.state.actors[AN]
    _do(engine, "Wax Tomb", target=AN)
    assert _has(foe, "condition:typed.restrained") and _has(foe, "condition:typed.blinded")
    engine.state.current_actor_id = AN
    assert any("break free" in candidate.display_name.lower() for candidate in engine.legal_candidates()), \
        sorted({c.display_name for c in engine.legal_candidates()})


# --------------------------------------------------------------------------- the court's footing
def test_court_allies_ignore_the_difficult_terrain_of_your_wax():
    # "Allies in the court gain ... They ignore Difficult Terrain created by your Wax talents."
    _, engine = _fight(["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"], foe_at=(14, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "Court of Ten Thousand Candles")
    assert states.active(engine, me, wax_footing.COURT_STATE) is not None
    cells = _wax_cells(engine, me)
    assert cells
    inside = sorted(cells)[len(cells) // 2]
    ally = type(me.position)(x=inside[0], y=inside[1])
    me.position = ally
    assert not any(cell in cells for cell in zones.difficult_cells(engine, me))
    foe.position = type(foe.position)(x=inside[0], y=inside[1])
    assert any(cell in cells for cell in zones.difficult_cells(engine, foe)), "the court no longer slows its enemies down"


def test_court_allies_still_pay_for_terrain_the_wax_did_not_make():
    # "Difficult Terrain **created by your Wax talents**". combat/zones.difficult_cells merges map paint and every area into
    # one set before difficult_exempt subtracts from it, so without this scope the ally in the court also walked through
    # broken ground it had nothing to do with.
    from combat.gate2_runtime_models import ZoneState

    _, engine = _fight(["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"], foe_at=(14, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "Court of Ten Thousand Candles")
    court = [zone for zone in zones.typed_zones(engine) if wax_footing.COURT in zone.source_definition_id][0]
    foe.team_id = me.team_id  # an ally of the wax owner, standing in its court
    ally = foe
    inside = court.affected_cells[len(court.affected_cells) // 2]
    ally.position = type(ally.position)(x=inside.x, y=inside.y)
    rubble_id = "zone:probe:not_the_wax"
    engine.state.zones[rubble_id] = ZoneState(
        zone_id=rubble_id, source_definition_id="probe:not_the_wax", owner_id="zone:map", center=inside, radius_cells=0,
        affected_cells=tuple(court.affected_cells), concentration_link=False, duration_rounds=None, created_round=0,
        trigger_profile={"kind": zones.KIND, "name": "Broken ground", "difficult": "all", "visual": {},
                         "follows_owner": False, "triggers": [], "inside": [], "numbers": {}})
    assert (inside.x, inside.y) in zones.difficult_cells(engine, ally), \
        "the court exempted the ally from ground the wax never made"


def test_court_allies_still_pay_for_painted_ground_under_the_wax():
    # The same scope, for the map's own rough ground under a wax area.
    _, engine = _fight(["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"], foe_at=(14, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "Court of Ten Thousand Candles")
    court = [zone for zone in zones.typed_zones(engine) if wax_footing.COURT in zone.source_definition_id][0]
    foe.team_id = me.team_id
    ally = foe
    inside = court.affected_cells[len(court.affected_cells) // 2]
    ally.position = type(ally.position)(x=inside.x, y=inside.y)
    engine.grid.base_movement_cost = {**engine.grid.base_movement_cost, (inside.x, inside.y): 2}
    exempt = wax_footing.court_footing(engine, ally) or set()
    assert (inside.x, inside.y) not in exempt, \
        "the court exempted the ally from rough ground painted on the map"


def test_court_gives_a_summoned_ally_the_same_footing():
    # "**Allies in the court** gain the following benefits." A summoned helper is an ally too: the first draft read
    # actor.summon and quietly excluded it.
    _, engine = _fight(["TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"], foe_at=(14, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "Court of Ten Thousand Candles")
    cells = _wax_cells(engine, me)
    inside = sorted(cells)[len(cells) // 2]
    foe.team_id = me.team_id
    foe.summon = {"summoner": me.entity_id, "group": "wax"}
    ally = foe
    ally.position = type(ally.position)(x=inside[0], y=inside[1])
    assert inside in (wax_footing.court_footing(engine, ally) or set()), \
        "a summoned ally in the court was left on the difficult ground"


# --------------------------------------------------------------------- Living Wax Form, Set Body: heavy footing
def _set_body_ctx(engine, me):
    """A forced_movement_reduction context: the hook reads the engine and the creature that is being moved."""
    from types import SimpleNamespace

    return SimpleNamespace(engine=engine)


def test_set_body_reduces_forced_movement_by_ten_while_its_temporary_hit_points_remain():
    # "Set Body ... You gain temporary hit points equal to twice your Cultivation Level. While these temporary hit points
    # remain, you reduce forced movement by 10 feet." The record dropped that rider and typed it, but a forced_movement row
    # causes a push rather than shortening one, so nothing answered the printed sentence.
    from combat.ext.wax_footing import SET_BODY, SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me = engine.state.actors[ME]
    ctx = _set_body_ctx(engine, me)
    assert set_body_footing(ctx, me) == 0, "Set Body shortened movement before it was activated"
    _do(engine, "Living Wax Form: Set Body")
    assert states.active(engine, me, SET_BODY) is not None
    assert me.temporary_hp > 0, "Set Body grants no Temporary Hit Points to hold on to"
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT
    me.temporary_hp = 0  # "while these temporary hit points remain"
    assert set_body_footing(ctx, me) == 0, "the reduction outlived the Temporary Hit Points it needs"


def test_set_body_reduction_shifts_a_printed_push_at_the_table():
    # The same rule read by the engine when it actually pushes the Set Body creature: a printed 20-foot shove travels 10.
    from combat.ext.wax_footing import SET_BODY_REDUCTION_FT

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Living Wax Form: Set Body")
    shove = ActionDefinition(source_definition_id="action:typed.test.foe_shove", display_name="Foe shove", owner_id=AN,
                             economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                             parameters={"typed": {"effects": [{"type": "forced_movement", "applies_to": "target",
                                                                "distance_ft": 20, "evidence": "probe shove"}],
                                                   "numbers": {"pb": 4, "cl": 10, "save_dc": 15, "attack_bonus": 0},
                                                   "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[shove.source_definition_id] = shove
    foe.action_ids = (*foe.action_ids, shove.source_definition_id)
    before = me.position
    engine.state.current_actor_id = AN
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == shove.source_definition_id)
    engine.execute_intent(ActionIntent(intent_id="shove", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    moved = engine.grid.distance_ft(before, me.position)
    assert moved == 20 - SET_BODY_REDUCTION_FT, f"a 20-foot push became {moved} feet"


def _damage(engine, target, amount: int, source: str = "action:probe.hit") -> None:
    """Real damage through the engine, so Temporary Hit Points are absorbed the way they are in a fight."""
    engine._commit_damage(target, amount, "SLASHING", source, AN, None, reaction_depth=0)


def test_set_body_stops_shortening_forced_movement_when_another_ability_grants_temporary_hit_points():
    # "You gain temporary hit points equal to twice your Cultivation Level. **While these temporary hit points remain**, you
    # reduce forced movement by 10 feet." Reading the aggregate pool switched the reduction back on after the form's own points
    # were spent and an unrelated ability handed out new ones; the form's own grant is now recorded instead of guessed at.
    from combat.ext.wax_footing import SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _set_body_ctx(engine, me)
    _do(engine, "Living Wax Form: Set Body")
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT
    _damage(engine, me, me.temporary_hp, "action:probe.spent_by_a_hit")
    assert me.temporary_hp == 0 and set_body_footing(ctx, me) == 0
    engine._grant_temp_hp(me, 9, "action:typed.some_other_talent", AN)
    assert me.temporary_hp == 9
    assert set_body_footing(ctx, me) == 0, \
        "Temporary Hit Points from another ability switched the Set Body reduction back on"


def test_set_body_lets_go_of_a_larger_temporary_hit_point_pool_it_never_replaced():
    # Temporary Hit Points do not stack (combat/gate2_engine.py _grant_temp_hp keeps the maximum), so a creature already holding
    # more than twice its Cultivation Level gains none of the form's points and has none of them to hold on to.
    from combat.ext.wax_footing import SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me = engine.state.actors[ME]
    ctx = _set_body_ctx(engine, me)
    engine._grant_temp_hp(me, 25, "action:typed.some_other_talent", AN)
    _do(engine, "Living Wax Form: Set Body")
    assert me.temporary_hp == 25, "Set Body's own 20 points should not have stacked on the larger pool"
    assert set_body_footing(ctx, me) == 0, \
        "the reduction was reading 25 Temporary Hit Points that Set Body never granted"


def test_set_body_records_the_hit_points_it_granted_on_the_forms_own_clock():
    # The record the reduction reads is stored state: one integer amount, on the same expiry the form's own state carries, so
    # it can never outlive "Duration 1 minute" and survives a saved fight as a plain integer and a string.
    from combat.ext.wax_footing import SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me = engine.state.actors[ME]
    ctx = _set_body_ctx(engine, me)
    _do(engine, "Living Wax Form: Set Body")
    rows = [row for row in me.conditions.values() if row.condition_id == SET_BODY_HP]
    assert len(rows) == 1, [row.condition_id for row in me.conditions.values()]
    assert rows[0].data["amount"] == me.temporary_hp == 2 * 10, rows[0].data
    assert type(rows[0].data["amount"]) is int
    assert rows[0].expires_on == states.active(engine, me, wax_footing.SET_BODY).expires_on, \
        "the record must end with the form, not after it"
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT
    # a bigger pool from anywhere takes the record away with it
    engine._grant_temp_hp(me, 30, "action:typed.some_other_talent", AN)
    assert not _has(me, SET_BODY_HP) and set_body_footing(ctx, me) == 0


def test_set_body_recast_puts_the_hit_point_record_on_the_activation_that_was_just_cast():
    # "Duration 1 minute" is a fresh minute for every use, and the typed row grants the hit points *before* it places the
    # form's own state -- so a second Set Body saw the first activation's state and recorded its deadline. The record then came
    # off with the old form while the new form kept running, and the printed 10-foot reduction stopped a minute early.
    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me = engine.state.actors[ME]
    ctx = _set_body_ctx(engine, me)
    _do(engine, "Living Wax Form: Set Body")
    first = states.active(engine, me, SET_BODY).expires_on
    _damage(engine, me, 4, "action:probe.spent_by_a_hit")  # spend some of the form's own points
    for _ in range(len(engine.state.initiative_order)):  # a whole round later, so the two deadlines can differ at all
        _end_turn(engine)
    _walk_to(engine, ME)
    _do(engine, "Living Wax Form: Set Body")
    (row,) = [row for row in me.conditions.values() if row.condition_id == SET_BODY_HP]
    form = states.active(engine, me, SET_BODY)
    assert row.expires_on == form.expires_on, \
        f"the record ends at {row.expires_on} while the form it belongs to ends at {form.expires_on}"
    assert row.expires_on != first, "the two activations shared a deadline, so this test cannot see the bug"
    # and the record is still there once the previous activation's own clock has come and gone
    for _ in range(2 * 10 * len(engine.state.initiative_order)):
        if effect_durations.due(engine, first):
            break
        _end_turn(engine)
    assert effect_durations.due(engine, first), "the first activation's deadline never came due"
    assert states.active(engine, me, SET_BODY) is not None, "the form itself ended early"
    assert _has(me, SET_BODY_HP), "the record ended with the previous activation's deadline"
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT


def test_a_set_body_saved_before_its_hit_point_record_reads_the_forms_own_grant():
    # A fight saved before the record existed carries the form's state and its Temporary Hit Points but nothing naming the
    # grant that put them there, so the record reads nothing and the printed reduction is lost on every later turn. It has to
    # come back from the fight's own recorded grants -- and only from this talent's own gain, never from an aggregate pool.
    from combat.ext.wax_footing import SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _set_body_ctx(engine, me)
    _without_set_body_record(lambda: _do(engine, "Living Wax Form: Set Body"))
    assert not _has(me, SET_BODY_HP) and me.temporary_hp == 20, "this is meant to be the shape of an older save"
    assert states.active(engine, me, wax_footing.SET_BODY) is not None
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT, \
        "a Set Body running in a fight saved before the record lost its printed reduction"
    _damage(engine, me, 5, "action:probe.spent_by_a_hit")  # the form's own points still hold the wax
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT
    # a larger pool from another ability afterwards is not the form's points, exactly as the record decides
    engine._grant_temp_hp(me, 30, "action:typed.some_other_talent", AN)
    assert set_body_footing(ctx, me) == 0
    me.temporary_hp = 0
    assert set_body_footing(ctx, me) == 0


def test_another_abilities_impressed_mark_keeps_the_ordinary_mark_path():
    # The wax clock answers this Sphere's own Edict sentence. An unrelated mark that happens to share the name and the printed
    # duration must keep the ordinary path -- END_OF_HOLDER_NEXT_TURN, with the capacity and family handling around it -- and
    # not be captured by the wax, or the next plug-in to use the word "Impressed" silently changes meaning.
    from combat.gate2_runtime_models import ActionDefinition

    from combat.ext import wax_edict

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    branded = ActionDefinition(source_definition_id="action:typed.test.brand", display_name="Brand", owner_id=AN,
                               economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                               parameters={"typed": {"effects": [{"type": "mark", "mark": wax_edict.IMPRESSED,
                                                                  "applies_to": "target",
                                                                  "duration": {"kind": wax_edict.HOLDER_TURN},
                                                                  "evidence": "probe: some other talent's own mark"}],
                                                     "numbers": {"pb": 4, "save_dc": 15, "attack_bonus": 0, "cl": 10},
                                                     "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[branded.source_definition_id] = branded
    foe.action_ids = (*foe.action_ids, branded.source_definition_id)
    engine.state.current_actor_id = AN
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == branded.source_definition_id and c.target_ids == (ME,))
    engine.execute_intent(ActionIntent(intent_id="brand", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN, target_ids=candidate.target_ids))
    rows = [row for row in me.conditions.values() if row.condition_id == typed_executor.mark_condition_id(wax_edict.IMPRESSED,
                                                                                                        AN)]
    assert len(rows) == 1, [row.condition_id for row in me.conditions.values()]
    assert rows[0].expires_on == "END_OF_HOLDER_NEXT_TURN", \
        f"the wax took over another ability's mark: {rows[0].expires_on}"
    assert not effect_durations.parse(rows[0].expires_on), "the wax wrote its own turn token on a foreign mark"


# --------------------------------------------------------------------------- Living Wax Form: Wick Body
def _foe_strike(engine, *, damage=6):
    """A plain melee strike by the foe against the caster, which always lands."""
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    engine._add_modifier(me, "test", "armor_class", "ADD", -30, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
    engine._add_modifier(foe, "test", "armor_class", "ADD", 30, "SELF", expires_on="START_OF_SELF_NEXT_TURN")
    attack = [{"type": "attack", "attack_kind": "cultivation_melee", "count": 1, "on_miss": [],
               "on_hit": [{"type": "damage", "dice": {"count": damage, "sides": 6}, "damage_types": ["SLASHING"]}]}]
    strike = ActionDefinition(source_definition_id="action:typed.test.foe_strike", display_name="Foe strike", owner_id=AN,
                              economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                              parameters={"typed": {"effects": attack, "numbers": {"pb": 4, "save_dc": 15, "attack_bonus": 0, "cl": 10},
                                                   "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[strike.source_definition_id] = strike
    foe.action_ids = (*foe.action_ids, strike.source_definition_id)
    return strike


def _strike(engine) -> None:
    strike = engine.action_catalog["action:typed.test.foe_strike"]
    engine.state.current_actor_id = AN
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == strike.source_definition_id and c.target_ids == (ME,))
    engine.execute_intent(ActionIntent(intent_id="strike", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN, target_ids=candidate.target_ids))


def test_wick_body_burns_the_creature_that_hits_you_in_melee_for_your_proficiency_bonus():
    # "Wick Body. The first time each round a creature hits you with a melee attack, you may use your Reaction to deal fire
    # damage equal to your Proficiency Bonus and shed bright candlelight in a 10-foot radius."
    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Living Wax Form: Wick Body")
    assert states.active(engine, me, WICK_BODY) is not None
    _foe_strike(engine)
    hp = foe.current_hp
    _strike(engine)
    assert hp - foe.current_hp == me.proficiency_bonus, (hp, foe.current_hp, me.proficiency_bonus)
    lit = [((zone.trigger_profile or {}).get("visual") or {}).get("light") or {} for zone in zones.typed_zones(engine)]
    assert any(row.get("level") == "bright" for row in lit), f"the wax did not flare: {lit}"


def test_wick_body_does_not_burn_you_for_a_ranged_hit():
    # "hits you with a melee attack": a creature that strikes from farther off does not set the wax alight.
    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(14, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Living Wax Form: Wick Body")
    _foe_strike(engine)
    ranged = engine.action_catalog["action:typed.test.foe_strike"].model_copy(update={"range_ft": 60})
    engine.action_catalog[ranged.source_definition_id] = ranged.model_copy(
        update={"parameters": {"typed": {**engine.action_catalog[ranged.source_definition_id].parameters["typed"], "range_ft": 60}}})
    hp = foe.current_hp
    _strike(engine)
    assert foe.current_hp == hp, "a ranged hit lit the wax up"


def test_wick_body_candlelight_ends_at_the_start_of_your_next_turn():
    # "shed bright candlelight in a 10-foot radius until the start of your next turn". ``duration_rounds`` is compared with the
    # ROUND number (combat/zones.py on_turn_start), so one round is the whole clock only when the owner has already taken its
    # turn this round: a hit that lands before the owner's own slot left the light burning through that turn as well, and the
    # old regression only read the stored number instead of advancing a single turn. The clock is the owner's next turn START,
    # counted in turns, whichever side of the attacker it falls on.
    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    order = engine.state.initiative_order
    assert order.index(ME) != order.index(AN)
    # the attacker strikes in the round BEFORE the owner's own slot: the hard case for a round-count clock
    engine.state.current_slot_index = order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _do(engine, "Living Wax Form: Wick Body")
    _end_turn(engine)
    assert engine.state.current_actor_id == AN, engine.state.initiative_order
    _foe_strike(engine)
    _strike(engine)
    lit = [zone for zone in zones.typed_zones(engine) if "wax_light" in zone.zone_id]
    assert len(lit) == 1, [zone.zone_id for zone in zones.typed_zones(engine)]
    assert lit[0].duration_rounds is None, "the light still rides the round clock, which only reads right half the time"
    assert _end_turn(engine) == ME, "the owner's next turn did not follow the attacker's"
    assert not [zone for zone in zones.typed_zones(engine) if "wax_light" in zone.zone_id], \
        "the candlelight is still burning at the start of your next turn"


# --------------------------------------------------------------------------- Molten Snare
def test_molten_snare_burns_a_creature_that_moves_through_the_wax():
    # "Until the start of your next turn, the creature takes fire damage equal to your Proficiency Bonus whenever it moves
    # willingly or is moved through the wax." The point was charged by the combination; nothing burned before this lane.
    from combat.ext import rider_movement

    _, engine = _fight(["TAL_WAX_WAX_CAGE", "TAL_WAX_MOLTEN_SNARE"], foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Wax Cage + Molten Snare", target=AN)
    assert _has(foe, wax_footing.MOLTEN_BURN), "the failed save did not brand the creature"
    assert foe.current_hp == foe.maximum_hp, "the wax burned it before it moved"

    from combat.gate2_runtime_models import Position

    before = len(engine.events)
    hp = foe.current_hp
    rider_movement.step(engine, foe, [foe.position, Position(x=foe.position.x - 1, y=foe.position.y)], "system:test.move")
    assert hp - foe.current_hp == me.proficiency_bonus, [event.payload for event in engine.events[before:]
                                                         if event.event_type == "DAMAGE_COMMITTED"]


def test_molten_snare_is_inert_without_the_paid_combination():
    # Plain Wax Cage (no Molten Snare point spent) brands nobody.
    _, engine = _fight(["TAL_WAX_WAX_CAGE", "TAL_WAX_MOLTEN_SNARE"], foe_at=(4, 6))
    foe = engine.state.actors[AN]
    _do(engine, "Wax Cage", target=AN)
    assert _has(foe, "condition:typed.restrained") and not _has(foe, wax_footing.MOLTEN_BURN)


def test_molten_snare_stops_burning_at_the_start_of_your_next_turn():
    # "Until the start of your next turn": the branding carries an expiry name the engine removes, not one that leaves the
    # wax burning for the rest of the fight (tests/test_expiry_names.py guards the names; this guards the clock it sets).
    from combat.ext import effect_durations

    _, engine = _fight(["TAL_WAX_WAX_CAGE", "TAL_WAX_MOLTEN_SNARE"], foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _do(engine, "Wax Cage + Molten Snare", target=AN)
    row = next(row for row in foe.conditions.values() if row.condition_id == wax_footing.MOLTEN_BURN)
    assert effect_durations.parse(row.expires_on) == ("start", me.entity_id, me.turns_started + 1)


# --------------------------------------------------------------------------- White Wax Edict of Stillness
def _edict_with_foe_inside():
    """A compiled Wax Edict with the hostile creature standing in it (the printed "attempts ... inside the area")."""
    from combat.ext import wax_edict

    _, engine = _fight(["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"], cl=15, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "White Wax Edict of Stillness", near=(6, 6))
    edicts = [zone for zone in zones.typed_zones(engine) if wax_edict.EDICT in zone.source_definition_id]
    assert edicts, "the Edict made no area"
    spot = edicts[0].affected_cells[len(edicts[0].affected_cells) // 2]
    foe.position = type(foe.position)(x=spot.x, y=spot.y)
    return engine, me, foe, edicts[0], spot


def _impressed_rows(actor):
    return [row for row in actor.conditions.values() if "impressed" in row.condition_id.lower()]


def _foe_teleport(engine, *, destination):
    """Give the hostile creature a plain typed teleport, so the Edict answers a real self-teleport and not a hook call."""
    from combat.gate2_runtime_models import ActionDefinition

    foe = engine.state.actors[AN]
    jump = ActionDefinition(source_definition_id="action:typed.test.foe_teleport", display_name="Foe teleport",
                            owner_id=AN, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
                            range_ft=90,
                            parameters={"typed": {"effects": [{"type": "teleport", "distance_ft": 30}],
                                                  "numbers": {"pb": 4, "save_dc": 15, "attack_bonus": 0, "cl": 10},
                                                  "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[jump.source_definition_id] = jump
    foe.action_ids = (*foe.action_ids, jump.source_definition_id)
    engine.state.current_actor_id = AN
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id == jump.source_definition_id
                     and c.destination is not None and tuple(c.destination.model_dump().values())[:2] == destination)
    engine.execute_intent(ActionIntent(intent_id="jump", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=AN, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def test_white_wax_edict_refuses_a_hostile_creature_that_fails_the_charisma_save():
    # "The first time each round a hostile creature attempts to teleport, become invisible, change shape, or pass through a
    # sealed threshold inside the area, it must succeed on a Charisma saving throw or the attempt fails and the creature
    # becomes impressed by the wax until the end of its next turn."
    # teleport_check answers False for a self-teleport that fails, so the wax refusing the creature is the NEGATION of
    # "the save failed". This test answered that flag itself, which let the creature the wax had stopped teleport away and
    # blocked every later teleport of that round; the printed rules decide both answers, so both are asserted here.
    from combat.ext import wax_edict

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    away = Position(x=spot.x, y=spot.y + 8)

    before = len(engine.events)
    refused = wax_edict.teleport_refused(engine, foe, foe.position, away)
    rolled = [event for event in engine.events[before:] if event.event_type == "SAVE_ROLLED"]
    assert rolled, "no Charisma save was rolled for the teleport attempt"
    assert refused is False, "a creature that failed the save was allowed to teleport away"
    assert _impressed_rows(foe), [row.condition_id for row in foe.conditions.values()]
    assert wax_edict.teleport_refused(engine, foe, foe.position, away) is True, \
        "the second attempt that round must go through: 'the first time each round'"


def test_white_wax_edict_lets_a_teleport_through_when_the_creature_saves():
    # "On a successful save, the attempt works": the same negation, the other way round -- a save that succeeds must not
    # answer False, or the wax blocks the creature it just let go.
    from combat.ext import wax_edict
    import combat.ext.spirit_traditions as st_mod

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    away = Position(x=spot.x, y=spot.y + 8)
    original = st_mod.save
    try:
        st_mod.save = lambda *a, **k: False  # the creature makes its Charisma save
        assert wax_edict.teleport_refused(engine, foe, foe.position, away) is True
    finally:
        st_mod.save = original
    assert not _impressed_rows(foe), "a creature that saved was marked by the wax"


def test_white_wax_edict_actually_stops_a_teleport_at_the_table():
    # The same rule through the real table: the hostile creature uses a typed teleport inside the edict and, its Charisma
    # save failing against Cultivation Save DC 30, does not move.
    from combat.ext import wax_edict

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    start = foe.position
    _foe_teleport(engine, destination=(spot.x, spot.y + 4))
    assert foe.position == start, "the wax did not stop the teleport it had just refused"
    assert _impressed_rows(foe)


def test_white_wax_edict_impression_ends_with_the_creatures_own_next_turn():
    # "becomes impressed by the wax until the end of its next turn": the clock belongs to the creature that carries the mark.
    # The "until_end_of_your_next_turn" spelling is filed under the wax owner (typed_executor.marker_expiry ->
    # END_OF_MARKER_NEXT_TURN, "until the end of its placer's next turn" to a player), which outlived the printed window by a
    # whole round.
    from combat.ext import wax_edict

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    away = Position(x=spot.x, y=spot.y + 8)
    wax_edict.teleport_refused(engine, foe, foe.position, away)  # the save fails: the creature is marked
    assert _impressed_rows(foe)
    assert _end_turn(engine) == AN
    assert _impressed_rows(foe), "the wax mark ended before the creature's own turn"
    assert _end_turn(engine) == ME
    assert not _impressed_rows(foe), "the wax mark outlived the end of the creature's next turn"


def test_white_wax_edict_impression_survives_the_turn_it_was_placed_on():
    # The same printed clock for the case every Edict attempt actually is: the creature tries to teleport, change shape or
    # step out ON ITS OWN TURN, so it is the one acting when the wax marks it. The rules table's "until_end_of_next_turn"
    # becomes the sealed engine's END_OF_HOLDER_NEXT_TURN, which is taken off at the end of whichever turn the marked creature
    # is taking right now -- so the mark lasted no time at all and the creature was free again the moment its turn ended.
    from combat.ext import wax_edict

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    away = Position(x=spot.x, y=spot.y + 8)
    _acting(engine, AN)  # a hostile creature makes its own attempt, on its own turn
    assert engine.state.current_actor_id == AN
    assert wax_edict.teleport_refused(engine, foe, foe.position, away) is False
    (row,) = _impressed_rows(foe)
    assert row.expires_on == effect_durations.token("end", foe.entity_id, foe.turns_started + 1), row.expires_on
    assert _end_turn(engine) != AN
    assert _impressed_rows(foe), "the wax mark ended with the very turn the creature was marked on"
    _end_turn(engine)  # the end of the creature's next turn
    assert _end_turn(engine) == ME
    assert not _impressed_rows(foe), "the wax mark outlived the end of the creature's next turn"


@pytest.mark.parametrize("first", [ME, AN], ids=["wax_owner_first", "attacker_first"])
def test_thousand_faced_wax_sovereign_impresses_the_attacker_until_the_end_of_the_wax_owners_next_turn(first):
    # "When a creature hits you with an attack, you may use your Reaction to cause one wax false-face to break. The attack still
    # hits, but the attacker becomes impressed by your Wax until the end of your next turn." The printed sentence says *your*,
    # so the turn it counts is the Wax owner's own next turn -- not the attacker's, which is the only other candidate and
    # would end the mark before the owner had taken a turn at all, the Sovereign being answered on the attacker's turn.
    # "until_end_of_your_next_turn" is the rules table's name for the marker's own next turn (typed_executor.marker_expiry ->
    # END_OF_MARKER_NEXT_TURN), which the ordinary mark path keeps and this mark therefore never needs intercepting.
    bundle, engine = _fight(["TAL_WAX_MOLD_WAX", "TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN"], cl=15, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert any("TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN" in str(row["source_definition_id"])
               for row in bundle["action_catalog"]), "the Sovereign did not compile"
    _acting(engine, first)
    _walk_to(engine, ME)
    _apply_sovereign(engine, me)  # the printed "For the duration, you gain ...", on the owner
    _walk_to(engine, AN)
    _foe_strike(engine)
    _strike(engine)  # a real hit through the table, so the printed Reaction answers it
    (row,) = _impressed_rows(foe)
    assert row.source_actor_id == me.entity_id, "the attacker is not the one carrying the mark"
    assert row.expires_on == "END_OF_MARKER_NEXT_TURN", row.expires_on
    assert (row.data or {}).get("marker_turn") == me.turns_started, (row.data or {})
    _end_turn(engine)  # the end of the attacker's own turn
    _walk_to(engine, ME)
    _cast(engine, "Mold Wax")  # the wax owner uses an ability on its own next turn
    assert _impressed_rows(foe), "the wax mark ended before the end of the wax owner's next turn"
    _end_turn(engine)  # the end of the wax owner's next turn
    _walk_to(engine, ME)
    _cast(engine, "Mold Wax")  # the next creature to use an ability is when an ended mark comes off
    assert not _impressed_rows(foe), "the wax mark outlived the end of the wax owner's next turn"
    # the wax mark is left to the ordinary mark path: this Sphere's own Edict, not this mark, needs the turn-token clock
    from combat.ext import wax_edict

    assert wax_edict.impressed(me, wax_edict.OWNER_TURN)[0]["duration"]["kind"] == "until_end_of_your_next_turn"
    assert wax_edict.impressed(me, wax_edict.HOLDER_TURN)[0]["duration"]["kind"] == "until_end_of_next_turn"


def test_white_wax_edict_leaves_a_wax_impression_where_a_creature_got_away():
    # "On a successful save, the attempt works, but the creature still leaves a visible wax Impression at the point of
    # departure." The first draft only wrote that sentence into the log and left nothing on the battlefield.
    from combat.ext import wax_edict
    import combat.ext.spirit_traditions as st_mod

    def _marks(engine):
        return [zone for zone in zones.typed_zones(engine) if zone.source_definition_id == wax_edict.IMPRESSION]

    engine, me, foe, edict, spot = _edict_with_foe_inside()
    away = Position(x=spot.x, y=spot.y + 8)
    original = st_mod.save
    try:
        st_mod.save = lambda *a, **k: False  # the creature makes its Charisma save and gets away
        assert wax_edict.teleport_refused(engine, foe, foe.position, away) is True
    finally:
        st_mod.save = original
    left = _marks(engine)
    assert len(left) == 1, [zone.zone_id for zone in zones.typed_zones(engine)]
    assert (left[0].center.x, left[0].center.y) == (foe.position.x, foe.position.y), "the impression is not where it left"
    assert (left[0].trigger_profile or {}).get("difficult") is None and not (left[0].trigger_profile or {}).get("triggers"), \
        "the impression is only a mark to look at, not a rule"
    assert left[0].owner_id == me.entity_id and left[0].duration_rounds == edict.duration_rounds, \
        "the impression must last as long as the wax that made it"

    # a refused attempt leaves nothing behind: the creature never got away from the wax
    other, _me2, foe2, _edict2, spot2 = _edict_with_foe_inside()
    wax_edict.teleport_refused(other, foe2, foe2.position, Position(x=spot2.x, y=spot2.y + 8))
    assert not _marks(other)


def test_white_wax_edict_leaves_a_creature_outside_it_alone():
    # The plug-in is inert for anyone who is not a hostile creature standing in an edict.
    from combat.ext import wax_edict

    _, engine = _fight(["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"], cl=15, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert wax_edict.teleport_refused(engine, foe, foe.position, foe.position) is None
    _cast(engine, "White Wax Edict of Stillness", near=(6, 6))
    assert wax_edict.teleport_refused(engine, me, me.position, me.position) is None, "your own edict stopped you"


def test_white_wax_edict_stops_a_failing_creature_from_going_invisible():
    # "become invisible" is answered by condition_attempt, whose veto is False: a failed save must withhold the answer, and a
    # successful one must let the wax slip. The test forces each outcome so neither branch is left to chance.
    from types import SimpleNamespace

    from combat.ext import wax_edict

    _, engine = _fight(["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"], cl=15, foe_at=(6, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    _cast(engine, "White Wax Edict of Stillness", near=(6, 6))
    spot = [zone for zone in zones.typed_zones(engine) if wax_edict.EDICT in zone.source_definition_id][0]
    foe.position = type(foe.position)(x=spot.affected_cells[0].x, y=spot.affected_cells[0].y)
    row = {"type": "condition", "condition": "invisible", "applies_to": "self"}

    class _Ctx(SimpleNamespace):
        pass

    import combat.ext.spirit_traditions as st_mod

    original = st_mod.save
    try:
        for failed, expected in ((True, False), (False, True)):
            foe.turn_flags.pop(wax_edict.EDICT_ROUND, None)
            st_mod.save = lambda *a, **k: failed
            answer = wax_edict.shapes_refused(_Ctx(engine=engine, actor=foe), foe, row)
            assert answer is expected, (failed, answer)
    finally:
        st_mod.save = original


def test_white_wax_edict_needs_no_reminder_text_left():
    # The coverage report's own number: the Edict is FULL, so no rider text can remind the GM of this rule.
    assert _authority()["TAL_WAX_WHITE_WAX_EDICT_OF_STILLNESS"]["coverage"] == "FULL"
    assert _authority()["TAL_WAX_MOLTEN_SNARE"]["coverage"] == "FULL"


# --------------------------------------------------------------------------- the table: stored state survives a commit and a reload
def _probe_push(engine, pusher, pushed, feet=20) -> int:
    """Really shove ``pushed`` ``feet`` feet, and return how far it travelled.

    A typed ``forced_movement`` row on the engine that is holding the fight (a reloaded table session counts), so the
    printed reduction is measured in feet travelled rather than read out of the plug-in that answers it.
    """
    shove = ActionDefinition(source_definition_id="action:typed.test.probe_push", display_name="Probe push",
                             owner_id=pusher.entity_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5,
                             parameters={"typed": {"effects": [{"type": "forced_movement", "applies_to": "target",
                                                                "distance_ft": feet, "evidence": "probe push"}],
                                                   "numbers": {"pb": 4, "cl": 10, "save_dc": 15, "attack_bonus": 0},
                                                   "duration": {"kind": "instant"}, "weapon": None, "riders": []}})
    engine.action_catalog[shove.source_definition_id] = shove
    pusher.action_ids = (*pusher.action_ids, shove.source_definition_id)
    before = pushed.position
    engine.state.current_actor_id = pusher.entity_id
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == shove.source_definition_id
                     and pushed.entity_id in (c.target_ids or ()))
    engine.execute_intent(ActionIntent(intent_id="push", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=pusher.entity_id, target_ids=candidate.target_ids))
    return engine.grid.distance_ft(before, pushed.position)


def _rejected_temp_hp_offer(table, mid):
    """Have the ally offer Waxen Shell's smaller Temporary Hit Points to the wax owner: an offer the engine rejects.

    "The target gains temporary hit points equal to your Proficiency Bonus + your key ability modifier" is a real printed
    grant, and against Set Body's own pool of 20 it raises nothing -- the receipt that is committed says so (``after`` is
    still ``before``), which is exactly what a smaller or equal offer looks like in a saved fight.
    """
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import ALLY, LEFT

    for _ in range(12):
        state = table.state(mid)
        menu = state["menu"]
        if menu["actor_id"] == ALLY:
            group = next(g for g in menu["actions"] if "TAL_WAX_WAXEN_SHELL" in str(g["source_definition_id"]))
            option = next(o for o in group["options"] if LEFT in (o.get("target_ids") or ()))
            assert table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                             state["last_sequence"], [])["status"] == "COMMITTED"
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError("the ally never came up to offer the wax shell")


def _last_temp_hp_grant(engine, who):
    return [(event.source_definition_id, dict(event.payload or {}).get("before"),
             dict(event.payload or {}).get("after")) for event in engine.events
            if event.event_type == "TEMP_HP_GRANTED" and who in (event.target_ids or ())][-1]


def test_a_set_body_saved_before_its_hit_point_record_keeps_its_reduction_after_a_rejected_offer(tmp_path):
    # Temporary Hit Points do not stack, so another ability's smaller offer is REJECTED: the wax owner keeps the points its
    # form granted. Reading the newest receipt instead of the grant that was actually accepted dropped the form's own points
    # on the floor, and the printed 10-foot reduction silently lapsed for the rest of an old save -- a 20-foot push then
    # travelled its full 20. The fight is real here: the ally casts the printed Waxen Shell, the offer is committed with the
    # fight, and the shove below is the engine actually pushing the reloaded creature.
    from types import SimpleNamespace

    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, answer_action, table_fight

    _, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM", "TAL_WAX_WAXEN_SHELL"], cl=10)
    _without_set_body_record(lambda: answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt1"))
    _rejected_temp_hp_offer(table, mid)
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    me = engine.state.actors[LEFT]
    granted, before, after = _last_temp_hp_grant(engine, LEFT)
    assert (before, after) == (20, 20) and "WAXEN_SHELL" in str(granted), (granted, before, after)
    assert not _has(me, SET_BODY_HP), "the save under test must not already carry the record it predates"
    assert states.active(engine, me, SET_BODY) is not None and me.temporary_hp == 2 * 10
    assert set_body_footing(SimpleNamespace(engine=engine), me) == SET_BODY_REDUCTION_FT, \
        "a rejected offer for Temporary Hit Points switched the Set Body reduction off in an older save"
    assert _probe_push(engine, engine.state.actors[RIGHT], me, 20) == 20 - SET_BODY_REDUCTION_FT, \
        "the 10-foot reduction did not shorten the printed push after the rejected offer"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_a_set_body_saved_before_its_hit_point_record_keeps_its_reduction_after_a_recast_at_a_full_pool(tmp_path):
    # The same reading, from the other end: Set Body used again while its own points are all still there grants nothing new
    # (Temporary Hit Points do not stack), so the newest receipt is an equal offer rather than a gain -- and an old save has
    # no record of its own to fall back on. "Duration 1 minute" is a fresh minute either way, and the printed reduction has to
    # run the whole of it.
    from types import SimpleNamespace

    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, answer_action, table_fight

    def _cast_when_offered() -> str:
        """Cast Set Body the first time the wax owner is actually offered it on a fresh turn (it is a Bonus Action)."""
        for _ in range(12):
            menu = table.state(mid)["menu"]
            if menu["actor_id"] == LEFT and any("TAL_WAX_LIVING_WAX_FORM#opt1" in g["source_definition_id"]
                                                for g in menu["actions"]):
                return answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt1")["status"]
            assert act(table, mid, "end")["status"] == "COMMITTED"
        raise AssertionError("the wax owner never got a fresh turn to change form on")

    _, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM", "TAL_WAX_WAXEN_SHELL"], cl=10)
    assert _without_set_body_record(_cast_when_offered) == "COMMITTED"
    assert _without_set_body_record(_cast_when_offered) == "COMMITTED"  # a round later: "Duration 1 minute" is fresh
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = session.engine
    me = engine.state.actors[LEFT]
    granted, before, after = _last_temp_hp_grant(engine, LEFT)
    assert "LIVING_WAX_FORM" in str(granted) and (before, after) == (20, 20), \
        f"this is meant to be an equal offer from a recast at a full pool: {(granted, before, after)}"
    assert not _has(me, SET_BODY_HP), "the save under test must not already carry the record it predates"
    assert states.active(engine, me, SET_BODY) is not None and me.temporary_hp == 2 * 10
    assert set_body_footing(SimpleNamespace(engine=engine), me) == SET_BODY_REDUCTION_FT, \
        "a Set Body used again at its own full pool lost its printed reduction in an older save"
    assert _probe_push(engine, engine.state.actors[RIGHT], me, 20) == 20 - SET_BODY_REDUCTION_FT, \
        "the 10-foot reduction did not shorten the printed push after the recast"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_a_set_body_saved_before_its_hit_point_record_keeps_the_grant_a_later_pool_did_not_take():
    # The reading itself, both ways: a rejected or equal offer leaves the form's own accepted grant standing (that is what
    # the engine's ``max(before, offered)`` means), while a LARGER pool from another ability really does replace it. This is
    # the one shared reader -- ``temp_hp_grants.held_grant`` -- that Bark-Back's guard also uses, so a saved fight and a
    # hit-triggered guard cannot disagree about whose Temporary Hit Points a pool is.
    from types import SimpleNamespace

    from combat.ext import temp_hp_grants
    from combat.ext.wax_footing import (SET_BODY_HP, SET_BODY_REDUCTION_FT, WAX_FORM, set_body_footing)

    _, engine = _fight(["TAL_WAX_LIVING_WAX_FORM"], cl=10, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    ctx = _set_body_ctx(engine, me)
    _without_set_body_record(lambda: _do(engine, "Living Wax Form: Set Body"))
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT
    engine._grant_temp_hp(me, 9, "action:typed.some_other_talent", AN)  # a smaller offer: rejected, 20 stays
    assert me.temporary_hp == 20
    assert WAX_FORM in str(temp_hp_grants.held_grant(engine.events, me.entity_id)[0]), \
        "the shared reader handed the accepted form grant to the rejected offer"
    assert set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT, "a rejected offer threw away the form's own grant"
    engine._grant_temp_hp(me, 20, "action:typed.an_equal_talent", AN)  # an equal offer: rejected, 20 stays
    assert me.temporary_hp == 20 and set_body_footing(ctx, me) == SET_BODY_REDUCTION_FT, \
        "an equal offer threw away the form's own grant"
    engine._grant_temp_hp(me, 30, "action:typed.a_bigger_talent", AN)  # a larger pool: really the other ability's
    assert me.temporary_hp == 30
    assert set_body_footing(ctx, me) == 0, "a larger pool from another ability was read as the form's own points"
    assert not _has(me, SET_BODY_HP), "the test is meant to stay on the older save's own reading"


def test_a_set_body_saved_before_its_hit_point_record_keeps_its_reduction_after_a_reload(tmp_path):
    # The compatibility reading is a reading, so it has to hold across the disk: a fight saved before the record existed is
    # committed and reloaded like any other, and the form's printed reduction is still answered from the fight's own log.
    from types import SimpleNamespace

    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_tabletop_hunt6 import LEFT, answer_action, table_fight

    _, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM"], cl=10)
    _without_set_body_record(lambda: answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt1"))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    me = loaded.engine.state.actors[LEFT]
    assert states.active(loaded.engine, me, SET_BODY) is not None and me.temporary_hp == 2 * 10
    assert not _has(me, SET_BODY_HP), "the save under test must not already carry the record it predates"
    assert set_body_footing(SimpleNamespace(engine=loaded.engine), me) == SET_BODY_REDUCTION_FT, \
        "the reloaded older save lost the form's printed reduction"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_a_set_body_recast_keeps_one_record_on_the_new_activation_after_a_reload(tmp_path):
    # "Duration 1 minute" restarts with every use, and the record has to restart with it: a second Set Body through the table,
    # a round later, leaves exactly one record on the new form's clock, and that is what comes back off disk.
    from types import SimpleNamespace

    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import LEFT, answer_action, table_fight

    def _cast_when_offered() -> str:
        """Cast Set Body the first time the wax owner is actually offered it on a fresh turn (it is a Bonus Action)."""
        for _ in range(12):
            menu = table.state(mid)["menu"]
            if menu["actor_id"] == LEFT and any("TAL_WAX_LIVING_WAX_FORM#opt1" in g["source_definition_id"]
                                                for g in menu["actions"]):
                return answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt1")["status"]
            assert act(table, mid, "end")["status"] == "COMMITTED"
        raise AssertionError("the wax owner never got a fresh turn to change form on")

    _, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM"], cl=10)
    assert _cast_when_offered() == "COMMITTED"
    first = [row.expires_on for row in CombatService(ROOT, tmp_path)._load_session(mid).engine.state.actors[LEFT].conditions.values()
             if row.condition_id == SET_BODY_HP]
    assert len(first) == 1, first
    assert _cast_when_offered() == "COMMITTED"  # a round later: "Duration 1 minute" is a fresh minute
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    me = engine.state.actors[LEFT]
    rows = [row for row in me.conditions.values() if row.condition_id == SET_BODY_HP]
    assert len(rows) == 1, [row.condition_id for row in me.conditions.values()]
    assert rows[0].expires_on == states.active(engine, me, SET_BODY).expires_on
    assert rows[0].expires_on != first[0], "the two activations shared a deadline, so this test cannot see the bug"
    assert set_body_footing(SimpleNamespace(engine=engine), me) == SET_BODY_REDUCTION_FT
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_set_body_record_and_its_reduction_survive_a_table_commit_and_reload(tmp_path):
    # The record the reduction reads is stored fight state, so it has to come back off disk with the fight: one integer
    # amount, the form's own expiry name (a string the shared sweep removes), and the reduction still answered from it.
    from types import SimpleNamespace

    from combat.ext.wax_footing import SET_BODY, SET_BODY_HP, SET_BODY_REDUCTION_FT, set_body_footing
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_tabletop_hunt6 import LEFT, answer_action, table_fight

    _, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM"], cl=10)
    assert answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt1")["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    me = engine.state.actors[LEFT]
    rows = [row for row in me.conditions.values() if row.condition_id == SET_BODY_HP]
    assert len(rows) == 1, [row.condition_id for row in me.conditions.values()]
    assert type(rows[0].data["amount"]) is int and rows[0].data["amount"] == 2 * 10, rows[0].data
    assert rows[0].expires_on == states.active(engine, me, SET_BODY).expires_on
    assert set_body_footing(SimpleNamespace(engine=engine), me) == SET_BODY_REDUCTION_FT
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_wax_impression_clock_survives_a_table_commit_and_reload(tmp_path):
    # The Impressed mark's deadline is stored state, so a saved fight keeps counting the wax owner's turns after it is
    # reloaded rather than falling back to whatever is acting: "END_OF_MARKER_NEXT_TURN" plus the marker's own turn counter
    # at placement (two integers/strings, nothing else). The wax owner takes the printed talent through the table, the
    # attacker strikes it in a real fight, and the mark is read off disk and still expires when it should.
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, answer_action, table_fight

    combat, table, mid = table_fight(tmp_path, ["TAL_WAX_MOLD_WAX", "TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN"], cl=15, ask=True)
    assert answer_action(table, mid, "TAL_WAX_THOUSAND_FACED_WAX_SOVEREIGN")["status"] == "COMMITTED"
    marked = None
    for _ in range(12):  # the attacker takes its own turn and strikes the wax owner, through the table
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == RIGHT:
            for group in menu["actions"]:
                if "strike" not in str(group["source_definition_id"]):
                    continue
                if not any(LEFT in (option.get("target_ids") or ()) for option in group["options"]):
                    continue
                assert answer_action(table, mid, group["source_definition_id"])["status"] == "COMMITTED"
                break
        else:
            assert act(table, mid, "end")["status"] == "COMMITTED"
        session = combat._load_session(mid)
        everyone = (session.engine.state.actors[LEFT], session.engine.state.actors[ALLY],
                    session.engine.state.actors[RIGHT])
        marked = next(((actor.entity_id, row.expires_on, row.source_actor_id, dict(row.data or {}))
                       for actor in everyone
                       for row in actor.conditions.values() if "impressed" in row.condition_id.lower()), None)
        if marked:
            break
    assert marked, "the Sovereign never impressed the creature that hit the wax owner"
    attacker, expires_on, placer, data = marked
    assert placer in (LEFT, ALLY), "only the creature that cast the Sovereign can place its mark"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    bear, owner = loaded.engine.state.actors[attacker], loaded.engine.state.actors[placer]
    (row,) = [r for r in bear.conditions.values() if "impressed" in r.condition_id.lower()]
    assert row.expires_on == expires_on == "END_OF_MARKER_NEXT_TURN", row.expires_on
    assert dict(row.data or {}) == data and data["marker_turn"] == owner.turns_started, (row.data, data)
    assert row.source_actor_id == placer
    # the reloaded fight still ends the mark at the end of the wax owner's next turn, and not before
    survived, ended = False, False
    for _ in range(3 * len(loaded.engine.state.initiative_order) + 3):
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        rows = [r for r in session.engine.state.actors[attacker].conditions.values() if "impressed" in r.condition_id.lower()]
        if rows and session.engine.state.actors[placer].turns_started > data["marker_turn"]:
            survived = True
        if survived and not rows:
            ended = True
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    assert survived, "the reloaded wax mark did not survive to the end of the wax owner's next turn"
    assert ended, "the reloaded wax mark outlived the end of the wax owner's next turn"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_wick_body_candlelight_survives_a_table_commit_and_reload_until_your_next_turn(tmp_path):
    # "shed bright candlelight in a 10-foot radius until the start of your next turn" is stored fight state: an area whose
    # whole clock is the owner's next turn START, held as one integer turn counter. This drives it through the table -- the
    # wax owner takes the printed Wick Body, an attacker strikes it in melee, and the reaction prompt is answered -- then
    # commits and reloads while the light is burning, because a saved fight that came back with no deadline would leave the
    # wax lit forever. The area is still gone at the start of the owner's next turn, and no earlier.
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT
    from tests.test_lock2_persistence import act
    from tests.test_tabletop_hunt6 import ALLY, LEFT, RIGHT, answer_action, table_fight

    combat, table, mid = table_fight(tmp_path, ["TAL_WAX_LIVING_WAX_FORM"], cl=10, ask=True)
    assert answer_action(table, mid, "TAL_WAX_LIVING_WAX_FORM#opt2")["status"] == "COMMITTED"
    assert not any("wax_light" in zone.zone_id for zone in zones.typed_zones(combat._load_session(mid).engine))
    for _ in range(12):  # the attacker takes its own turn and strikes the wax owner in melee, through the table
        state = table.state(mid)
        menu = state["menu"]
        if menu["actor_id"] == RIGHT:
            group = next(g for g in menu["actions"] if "strike" in str(g["source_definition_id"])
                         and any(LEFT in (option.get("target_ids") or ()) for option in g["options"]))
            # The group's first option attacks Ally, not the creature in Wick Body.
            # Select Left explicitly; premature activation light used to hide this mistake.
            cid = next(option["candidate_id"] for option in group["options"] if LEFT in option["target_ids"])
            answers = []
            for _ in range(4):
                result = table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
                if result["status"] == "COMMITTED":
                    break
                prompt = result["reaction"]
                assert "Wick Body" in prompt["moment"]
                answers.append({**prompt["context"], "selection": "USE", "option_ids": ["react"]})
            assert result["status"] == "COMMITTED" and answers
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    else:
        raise AssertionError("the attacker never got a turn to strike the wax owner")

    def _candlelight(session):
        return [zone for zone in zones.typed_zones(session.engine) if "wax_light" in zone.zone_id]

    session = CombatService(ROOT, tmp_path)._load_session(mid)
    lit = _candlelight(session)
    assert len(lit) == 1, [zone.zone_id for zone in zones.typed_zones(session.engine)]
    (zone,) = lit
    deadline = (zone.trigger_profile or {}).get("start_of_owner_turn")
    assert type(deadline) is int, f"the owner-turn deadline is not a plain integer: {deadline!r}"
    owner = session.engine.state.actors[LEFT]
    assert deadline == owner.turns_started + 1, (deadline, owner.turns_started)
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"

    # The clock is one turn and not "about a round": on EVERY reload before the deadline the light must still be
    # burning, and on the FIRST reload at the deadline it must already be gone. Anything that lets it go dark early (the
    # saved deadline is lost, read as 0, or counted in rounds) or lets it burn past the owner's next turn start fails here,
    # which a "it disappeared somewhere in the next few turns" assertion would let through.
    reached_deadline = False
    for _ in range(3 * len(session.engine.state.initiative_order) + 3):
        session = CombatService(ROOT, tmp_path)._load_session(mid)
        owner = session.engine.state.actors[LEFT]
        lit_now = _candlelight(session)
        if owner.turns_started < deadline:
            assert lit_now, (f"the reloaded candlelight went out early: owner turn {owner.turns_started} of "
                             f"{deadline}, still before the wax owner's next turn start")
            assert act(table, mid, "end")["status"] == "COMMITTED"
            continue
        reached_deadline = True
        assert not lit_now, (f"the reloaded candlelight is still lit at the start of the wax owner's next turn: "
                             f"owner turn {owner.turns_started}, deadline {deadline}")
        break
    assert reached_deadline, "the wax owner's next turn never came round, so the deadline was never checked"
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


# --------------------------------------------------------------------------- the data itself
def test_every_wax_edit_is_bound_to_its_printed_text_and_the_built_authority():
    mechanics = _authority()
    checked = 0
    for path in (REVIEW, ELEMENTS):
        for key, final in json.loads(path.read_text())["mechanics"].items():
            if key not in mechanics or "auto-wax" not in str(final.get("reviewed_by") or ""):
                continue
            checked += 1
            assert final["text_sha256"] == mechanics[key]["source"]["text_sha256"], key
            assert mechanics[key]["typing_status"] == "reviewed_final", key
    assert checked >= 4, checked
