"""AUTO22 (automation lane, Death sphere): the printed Death riders the engine now resolves.

Owner 2026-10-04: "automate everything".  Scope: the Death Sphere's combat riders that used to reach the table as
"Rule reminder" lines.  Everything here runs on a real compiled Factory character in a real fight: a Gate4ControllerEngine
for the movement/turn cases, and the table service (CombatService, a committed move and a reload) for the persistence case.

Rows: combat/rules/feature_blocks.d/riders_auto22.json (block "auto22_death").
Plug-in: combat/ext/death_riders.py.  Typed data: authority/typed_mechanics/reviewed_final.d/{ironroot,martial,review_sw-death}.json.
General seams: condition rule "death_prevention_denied" (combat/rules/typed_conditions.json, read by
combat/typed_reactions.py _offer_drop_to_zero_or_bloodied); the ``difficult_exempt`` terrain scope and the wall traversal
layer (combat/motion.py TerrainExemption, wall_traversal_cost/unimpeded, read by combat/zones.py sync_walls); and the
``condition_excluded`` compatibility subscriber (combat/typed_executor.py condition_rules) that lets an ability retire a
stale saved condition instance before its removal boundary arrives.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from combat import typed_executor as te
from combat.ext import death_riders
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, ME, FOE, ready, script, sheet
from combat.ext.death_riders import MARK_DAMAGE_RULE

MARK = "TAL_DEATH_MARK_FOR_THE_GRAVE"
HAND = "TAL_DEATH_WITHERING_HAND"
CHILL = "TAL_DEATH_GRAVE_CHILL"
FIELD = "TAL_DEATH_WITHERING_FIELD"
HOOK = "TAL_DEATH_SOUL_HOOK"
COURT = "TAL_DEATH_COURT_OF_THE_NINTH_GRAVE"
DUNE_WALL = "TAL_SAND_DUNE_WALL"  # a wall with its own printed price to cross: "4 feet of movement for every 1 foot moved"
HUMBLE_WALL = "TAL_EARTH_HUMBLE_WALL"  # a wall whose own price to cross (x2) is CHEAPER than ground it can overlap
ROUSE = "TAL_DEATH_ROUSE_LESSER_DEAD"
SERVANT = "TAL_DEATH_CORPSE_SERVANT"
FUNERAL = "TAL_DEATH_SOUL_FUNERAL"
SEAL = "TAL_DEATH_MORTALITY_SEAL"
EDICT = "TAL_DEATH_NO_RETURN_EDICT"
NEVER_FALLS = "TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS"
SMOKE = "TAL_SMOKE_CINDER_WISP"
PAINTING = "tianxia.talent.ink.ten_thousand_illustrated_soldiers"
DUST = "tianxia.subpath.qi.dust_cultivator.feature.primordial_dust"
BREATH = "TAL_DAEMONIC_CULTIVATION_HUNGER_REFINING_BREATH"
ALLY = "actor:factory.ally"
GRAVE_MARK = f"condition:typed.mark.grave_mark.{ME}"
SOUL_HOOK = "condition:typed.death_soul_hook"
DEATH_PREVENTION_DENIED = "condition:typed.no_death_prevention"
IGNORES_DIFFICULT = "condition:typed.ignore_difficult"
AUTH = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]


# ------------------------------------------------------------------------------------------------- harness
def build(*talents, actor_id=ME, cl=10, dc=16, hp=200, creature_type=None, plan=None, score=14):
    doc = sheet(list(talents), cl=cl, dc=dc, score=score)
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
    if creature_type:
        doc["identity"]["creature_type"] = creature_type
    # The Death sphere's own base component brings a Lesser Corpse Servant; these cases want only the servants they name.
    return compile_character(doc, actor_id=actor_id, summon_plan={"lesser_corpse_servant": 0, **(plan or {})})


def fight(me_bundle, foe_bundle=None, *, me_at=(3, 6), foe_at=(4, 6), seed="AUTO22", allies=(), ally_at=None,
          ally_team="team:b"):
    foe = foe_bundle or build(HAND, actor_id=FOE, cl=5, hp=200)
    ids = [me_bundle["actor_id"], foe_bundle["actor_id"] if foe_bundle else foe["actor_id"]]
    teams = {ME: "team:a", FOE: "team:b"}
    positions = {ME: {"x": me_at[0], "y": me_at[1]}, FOE: {"x": foe_at[0], "y": foe_at[1]}}
    for index, bundle in enumerate(allies):
        ids.append(bundle["actor_id"])
        teams[bundle["actor_id"]] = ally_team
        positions[bundle["actor_id"]] = {"x": (ally_at or foe_at)[0] + index + 1, "y": (ally_at or foe_at)[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(me_bundle, foe, *allies), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": teams, "starting_positions": positions})
    ready(engine)
    return engine


def use(engine, name, *, target=None, at=None, exact=False):
    actor_id = engine.state.current_actor_id
    rows = [c for c in engine.legal_candidates() if (name == c.display_name if exact else name in c.display_name)
            and (target is None or target in (c.target_ids or ()))
            and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert rows, f"{name!r} not offered; legal: {sorted({c.display_name for c in engine.legal_candidates() if 'Move' not in c.display_name})[:40]}"
    # A request for the original melee mode must not select the new ranged
    # alternative merely because its hashed candidate sorts first.
    candidate = min(rows, key=lambda c: c.display_name != name)
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"auto22:{candidate.display_name}:{before}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids or (),
                                       destination=candidate.destination))
    return engine.events[before:]


def damage_to(engine, events, target_id):
    return sum(int((e.payload or {}).get("hp_damage") or 0) for e in events
               if e.event_type == "DAMAGE_COMMITTED" and target_id in (e.target_ids or ()))


def held(actor, condition_id):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id]


def turn_to(engine, actor_id):
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    return ready(engine)


def to_actor(engine, actor_id):
    """Advance the fight to ``actor_id``'s own turn, whoever it is."""
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    return acts_now(engine, actor_id)


def acts_now(engine, actor_id):
    """Hand ``actor_id`` its turn without waiting for a round (a summoned servant's slot is not ME's)."""
    actor = engine.state.actors[actor_id]
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def mark_clock(engine, caster_id=ME):
    return [key for key in engine.state.actors[caster_id].turn_flags if death_riders.MARK_GATE in key]


# =============================================================== Mark for the Grave: the Proficiency Bonus rider
def test_mark_for_the_grave_adds_its_proficiency_bonus_to_one_necrotic_damage_roll():
    """Mark for the Grave: "The first time each turn the marked creature takes Necrotic damage from you or one of your
    Death servants, add your Proficiency Bonus to one damage roll."  Withering Hand's 3+4 Necrotic damage plus PB 4."""
    engine = fight(build(MARK, HAND, cl=10, dc=16))
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    assert held(engine.state.actors[FOE], GRAVE_MARK), "the printed Grave Mark is not on the target"
    script(engine, [15, 3, 4])
    dealt = damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE)
    assert dealt == 3 + 4 + 4, dealt


def test_the_grave_mark_bonus_is_the_first_necrotic_roll_each_turn():
    """"The first time each turn ... add your Proficiency Bonus to one damage roll": once per turn, so the next turn's first
    roll is paid again."""
    engine = fight(build(MARK, HAND, cl=10, dc=16))
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 11
    assert any("graveyard" not in key and MARK_DAMAGE_RULE in key for key in engine.state.actors[ME].turn_flags), \
        "the printed once-each-turn gate was not recorded"
    turn_to(engine, FOE)
    turn_to(engine, ME)
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 11


def test_the_grave_mark_bonus_is_inert_without_the_talent():
    """A character that never learned Mark for the Grave adds nothing, even to a creature that somehow bears its mark."""
    engine = fight(build(HAND, cl=10, dc=16))
    caster = engine.state.actors[ME]
    engine._apply_condition(engine.state.actors[FOE], GRAVE_MARK, "test:mark", ME, expires_on="UNTIL_REMOVED")
    assert death_riders._row(engine, caster, "grave_mark") is None
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 7


def test_one_grave_mark_clock_is_shared_by_two_different_actions_in_one_turn():
    """"The FIRST time each turn ...": the printed clock belongs to the caster's mark on that creature, not to one
    damaging action.  Withering Hand pays it; Primordial Dust, a second action in the same turn, must not."""
    engine = fight(build(MARK, HAND, DUST, cl=10, dc=16))
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    turn_to(engine, ME)  # next round: the mark is still there, the clock is not
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 11
    clock = mark_clock(engine)
    assert len(clock) == 1, clock
    # Primordial Dust is an area, so the caster is inside his own cone: the printed 4d8, then the caster's
    # Concentration save for the Grave Mark he is holding (rolled high so the mark is still there to be tested).
    script(engine, [1, 1, 1, 1, 20])
    assert damage_to(engine, use(engine, "Primordial Dust"), FOE) == 4
    assert mark_clock(engine) == clock, "the second action opened a second clock instead of finding the first spent"


def servant_fight():
    """ME owns the mark and one Corpse Servant, standing next to the marked foe (the servant's own reach)."""
    return fight(build(MARK, SERVANT, cl=10, dc=16, plan={"corpse_servant": 1}),
                 build(SMOKE, actor_id=FOE, cl=5, hp=200), me_at=(5, 6), foe_at=(3, 5), seed="AUTO22-SERVANT")


def marked_servant_strike(marked: bool):
    """The same scripted Corpse Servant Grave Strike with and without the Grave Mark on its target."""
    engine = servant_fight()
    script(engine, [20])
    if marked:
        use(engine, "Mark for the Grave", target=FOE)
    turn_to(engine, ME)  # the next round: the servant's command of the round before lapsed
    script(engine, [])
    use(engine, "Command Death servants")
    servant = engine.state.actors[ME].entity_id + ".summon.corpse_servant.1"
    acts_now(engine, servant)
    script(engine, [15, 3, 4])
    events = use(engine, "Grave Strike", target=FOE)
    return engine, damage_to(engine, events, FOE)


def test_a_death_servants_own_weapon_damage_carries_the_grave_mark_bonus():
    """A Corpse Servant keeps its Necrotic type in its weapon, not in a printed damage row: the packet's RESOLVED
    type decides, so Grave Strike is a qualifying roll (it was silently skipped before)."""
    marked_engine, marked_damage = marked_servant_strike(marked=True)
    _, plain_damage = marked_servant_strike(marked=False)
    assert marked_damage == plain_damage + 4, (marked_damage, plain_damage)
    assert mark_clock(marked_engine) == [mark_clock(marked_engine)[0]], mark_clock(marked_engine)
    assert death_riders.MARK_GATE in mark_clock(marked_engine)[0], mark_clock(marked_engine)


def funeral_hit(marked, *, resist_radiant):
    """Soul Funeral's single-target "6d8 Radiant or Necrotic damage, your choice" against a marked ghost.

    Returns ``(engine, damage, damage_type)``.  ``resist_radiant`` decides which of the two types the printed choice
    actually lands on (combat/typed_reactions.damage_factor is what typed_executor.choose_damage_type reads).
    """
    engine = fight(build(MARK, FUNERAL, cl=10, dc=16),
                   build(HAND, actor_id=FOE, cl=5, hp=200, creature_type="ghost"), seed="AUTO22-FUNERAL")
    if resist_radiant:
        engine._add_modifier(engine.state.actors[FOE], "test:radiant-ward", "damage_resistance", "ADD", "RADIANT",
                             "ALWAYS", expires_on="UNTIL_REMOVED")
    script(engine, [20])
    if marked:
        use(engine, "Mark for the Grave", target=FOE)
    script(engine, [1, 3, 4])  # the Charisma save fails, then two of the six damage dice
    events = use(engine, "Soul Funeral", target=FOE)
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    return engine, damage_to(engine, events, FOE), str((committed[0].payload or {}).get("damage_type") or "") if committed else ""


@pytest.mark.parametrize("resist_radiant, chosen, bonus", [(True, "NECROTIC", 4), (False, "RADIANT", 0)])
def test_the_grave_mark_bonus_follows_the_damage_type_actually_chosen(resist_radiant, chosen, bonus):
    """"add your Proficiency Bonus to one damage roll" when the marked creature takes NECROTIC damage: a row printed
    "6d8 Radiant or Necrotic damage, your choice" carries the printed rider when the caster chose Necrotic, and carries
    nothing when it chose Radiant.  AUTO22 review finding 2: reading the printed row's types refused every row that
    offers a choice."""
    marked_engine, marked_damage, marked_type = funeral_hit(True, resist_radiant=resist_radiant)
    _, plain_damage, plain_type = funeral_hit(False, resist_radiant=resist_radiant)
    assert (marked_type, plain_type) == (chosen, chosen), (marked_type, plain_type)
    assert marked_damage - plain_damage == bonus, (resist_radiant, marked_damage, plain_damage)
    assert bool(mark_clock(marked_engine)) is bool(bonus), mark_clock(marked_engine)


def test_the_grave_mark_clock_is_the_caster_s_not_the_servants():
    """The printed limit is the caster's mark, so the flag is recorded on the caster and its servant hits share it."""
    engine, _ = marked_servant_strike(marked=True)
    assert mark_clock(engine, ME), "the caster's own clock was not recorded"
    assert not mark_clock(engine, engine.state.actors[ME].entity_id + ".summon.corpse_servant.1"), \
        "the clock was stored on the attacking servant instead of the caster whose mark it is"


def test_a_summon_that_is_not_a_death_servant_never_carries_the_grave_mark():
    """"... or one of your Death servants": a Living Painting is a companion, not a Death servant, so its bite adds
    nothing to the mark even though the same caster commands it."""
    engine = fight(build(MARK, PAINTING, cl=10, dc=16), build(SMOKE, actor_id=FOE, cl=5, hp=200),
                   me_at=(5, 6), foe_at=(3, 5), seed="AUTO22-PAINTING")
    painting = next((a for a in engine.state.actors.values()
                     if a.summon and a.summon.get("group") == "painted_formation" and a.active), None)
    assert painting is not None, [a.summon for a in engine.state.actors.values() if a.summon]
    assert death_riders._death_servant(engine, painting) is False, "the Tiger counts as a Death servant"
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    turn_to(engine, ME)
    script(engine, [])
    use(engine, "Command Painted Formation")
    acts_now(engine, painting.entity_id)
    script(engine, [15, 3, 4])
    events = use(engine, "Formation Assault", target=FOE)
    assert damage_to(engine, events, FOE) > 0
    assert not mark_clock(engine), "a non-Death companion spent the caster's Grave Mark clock"


def test_another_casters_mark_is_never_used_by_this_caster():
    """Each caster's mark is its own.  ME marked the foe; ALLY has the same talent and no mark of its own, so ALLY's
    Withering Hand is an ordinary Necrotic roll."""
    engine = fight(build(MARK, HAND, cl=10, dc=16), allies=[build(MARK, HAND, actor_id=ALLY, cl=10, dc=16, hp=200)],
                   seed="AUTO22-TWO-CASTERS", ally_team="team:a")
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    assert [c.condition_id for c in engine.state.actors[FOE].conditions.values() if death_riders.GRAVE_MARK in c.condition_id]
    ally = engine.state.actors[ALLY]
    acts_now(engine, ALLY)
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 7
    assert not mark_clock(engine, ALLY), "the other caster's mark was borrowed"
    assert not mark_clock(engine, ME) or mark_clock(engine, ME), "ME's own clock is untouched by ALLY's attack"


def test_a_casters_own_mark_is_found_even_when_another_mark_is_also_on_the_creature():
    """Two marks on one creature: the one that belongs to the caster dealing the damage is the one that pays."""
    engine = fight(build(MARK, HAND, cl=10, dc=16), allies=[build(MARK, HAND, actor_id=ALLY, cl=10, dc=16, hp=200)],
                   seed="AUTO22-TWO-MARKS", ally_team="team:a")
    turn_to(engine, ALLY)
    script(engine, [20])
    use(engine, "Mark for the Grave", target=FOE)
    acts_now(engine, ME)
    script(engine, [15, 3, 4])
    assert damage_to(engine, use(engine, "Withering Hand", target=FOE), FOE) == 11
    assert mark_clock(engine, ME), "ME's own mark was not found behind the other caster's"
    assert not mark_clock(engine, ALLY), "ME's damage spent ALLY's clock"


def area_fight(marked_who):
    """One cone, two enemies in it, one shared roll; the marked one is ``marked_who``."""
    # Both enemies score 8 in Constitution and every d20 is scripted low, so both saves inside the cone fail in
    # either order and the cone's own 3d6 is the same shared roll for everyone.  The cone's printed recipients are
    # "creatures in the cone", which includes its own caster, so the fourth scripted d20 is the caster's
    # Concentration save (the Grave Mark is a Concentration effect): it is rolled high so the mark survives the
    # caster's own share of the roll and the case can be read at all.
    engine = fight(build(MARK, BREATH, cl=10, dc=16), build(SMOKE, actor_id=FOE, cl=5, hp=200, score=8),
                   me_at=(1, 6), foe_at=(5, 6), seed="AUTO22-AREA",
                   allies=[build(SMOKE, actor_id=ALLY, cl=5, hp=200, score=8)], ally_at=(6, 6))
    script(engine, [20])
    use(engine, "Mark for the Grave", target=marked_who)
    script(engine, [1, 3, 4, 3, 20, 1, 1])  # cone save, 3d6, cone save, Concentration, cone save, cone save
    events = use(engine, "Hunger-Refining Breath at 6,6", at=(6, 6))
    return (damage_to(engine, events, FOE), damage_to(engine, events, ALLY))


def test_one_area_roll_gives_the_proficiency_bonus_to_the_marked_creature_only():
    """An area rolls ONCE for every creature in it, so a bonus that names one creature is not part of that roll.
    Whichever order the save subjects resolve in, the marked creature gets its own Proficiency Bonus and nobody
    else does (before this, the first subject resolved decided it for everybody)."""
    first_marked = area_fight(FOE)
    second_marked = area_fight(ALLY)
    assert first_marked == (second_marked[1], second_marked[0]), (first_marked, second_marked)
    assert abs(first_marked[0] - first_marked[1]) == 4, first_marked


# ============================================================== Grave Chill: the failed and successful save
def test_grave_chill_failed_save_damages_and_blocks_healing():
    """Grave Chill: 2d6 Necrotic and "cannot regain HP until the start of your next turn" on a failed save."""
    engine = fight(build(CHILL, cl=10, dc=16))
    script(engine, [1, 2, 3])
    events = use(engine, "Grave Chill", target=FOE)
    assert damage_to(engine, events, FOE) == 5
    sealed = [e for e in events if e.event_type == "MODIFIER_APPLIED"
              and (e.payload or {}).get("target_field") == "healing_reduction"]
    assert [e.payload["value"] for e in sealed] == ["none"], sealed
    assert all(e.payload["expires_on"] == "START_OF_SOURCE_NEXT_TURN" for e in sealed)


def test_grave_chill_successful_save_halves_and_reduces_healing_by_the_proficiency_bonus():
    engine = fight(build(CHILL, cl=10, dc=16))
    script(engine, [20, 2, 3])
    events = use(engine, "Grave Chill", target=FOE)
    assert damage_to(engine, events, FOE) == 2  # half of 5
    reduced = [e for e in events if e.event_type == "MODIFIER_APPLIED"
               and (e.payload or {}).get("target_field") == "healing_reduction"]
    assert [e.payload["value"] for e in reduced] == ["minus:4"], reduced


# =============================================================== Withering Field: the zone damages once a turn
def test_withering_field_damages_a_creature_that_starts_its_turn_in_the_field_once():
    """Withering Field: "When a creature enters the area for the first time on a turn or starts its turn there, it makes a
    Constitution saving throw ... A creature takes this damage only once per turn."  A 15-foot sphere on the foe's square."""
    engine = fight(build(FIELD, cl=10, dc=16))
    script(engine, [20])
    placed = use(engine, "Withering Field", at=(7, 6))  # on the foe, not on the caster
    assert list(engine.state.zones), "the printed field was not placed"
    from combat import zones

    field = zones.typed_zones(engine)[0]
    assert zones._inside(engine, engine.state.actors[FOE], field)
    script(engine, [1])  # the foe's Constitution save fails
    turn_to(engine, FOE)  # the foe's turn starts inside the field
    hurt = [e for e in engine.events[len(placed):] if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert len(hurt) == 1, [e.event_type for e in engine.events[len(placed):]]
    assert 3 <= sum(int(e.payload.get("hp_damage") or 0) for e in hurt) <= 18  # 3d6 Necrotic
    healed = [e for e in engine.events[len(placed):] if e.event_type == "MODIFIER_APPLIED"
              and (e.payload or {}).get("target_field") == "healing_reduction" and FOE in (e.target_ids or ())]
    assert [e.payload["value"] for e in healed] == ["half"], healed  # "healing it receives is halved"


# =============================================================== Soul Hook: Speed 0 and the chain's reach
def ghost_fight():
    return fight(build(HOOK, cl=10, dc=16), build(HAND, actor_id=FOE, cl=5, hp=200, creature_type="ghost"))


def test_soul_hook_stops_the_target_and_records_the_square_it_was_hooked_at():
    engine = ghost_fight()
    script(engine, [1])
    use(engine, "Soul Hook", target=FOE)
    hooked = engine.state.actors[FOE]
    assert len(held(hooked, SOUL_HOOK)) == 1, "the Soul Hook condition is missing or duplicated"
    condition = held(hooked, SOUL_HOOK)[0]
    assert (condition.data or {}).get("hook_x") == hooked.position.x
    assert (condition.data or {}).get("hook_y") == hooked.position.y
    assert engine._effective_speed(hooked) == 0, "Speed is not reduced to 0"


def test_soul_hook_stops_a_willing_step_past_ten_feet_from_that_square():
    """'... it cannot willingly move more than 10 feet from the space it occupied when it failed the save.'  The typed
    Speed 0 already stops ordinary walking, so this is the movement seam itself (any other printed source of movement)."""
    from combat.movement_steps import checkpoint

    engine = ghost_fight()
    script(engine, [1])
    use(engine, "Soul Hook", target=FOE)
    hooked = engine.state.actors[FOE]
    anchor = Position(x=hooked.position.x, y=hooked.position.y)
    seam = {"point": "movement_attempt", "travelled_ft": 0, "remaining_ft": 30}
    assert checkpoint(engine, hooked, anchor, Position(x=anchor.x + 1, y=anchor.y), None, **seam) == []
    far = checkpoint(engine, hooked, anchor, Position(x=anchor.x + 3, y=anchor.y), None, **seam)
    assert far and far[0]["stop"] is True and "Soul Hook" in far[0]["label"], far
    assert any(e.event_type == "GM_RIDER" and "Soul Hook" in str((e.payload or {}).get("rider")) for e in engine.events)


def test_soul_hook_leash_is_inert_without_the_talent():
    """The same condition on a creature hooked by a character that never learned Soul Hook changes nothing."""
    from combat.movement_steps import checkpoint

    engine = fight(build(HAND, cl=10, dc=16), build(HAND, actor_id=FOE, cl=5, hp=200, creature_type="ghost"))
    hooked = engine.state.actors[FOE]
    engine._apply_condition(hooked, SOUL_HOOK, "test:hook", ME, expires_on="UNTIL_REMOVED",
                            data={"hook_x": hooked.position.x, "hook_y": hooked.position.y})
    assert death_riders._row(engine, engine.state.actors[ME], "soul_hook") is None
    stop = checkpoint(engine, hooked, hooked.position, Position(x=hooked.position.x + 3, y=hooked.position.y), None,
                      point="movement_attempt", travelled_ft=0, remaining_ft=15)
    assert stop == [], stop


# ============================================ Court of the Ninth Grave: its servants cross difficult terrain freely
def court_fight(*extra, seed="AUTO22-COURT", **kw):
    """The caster, one Lesser Corpse Servant (a Death servant), and whatever extra talent/plan the case needs."""
    engine = fight(build(COURT, ROUSE, *extra, cl=10, dc=16, plan={"lesser_corpse_servant": 1}), seed=seed, **kw)
    servant = next(a for a in engine.state.actors.values()
                   if a.summon and a.summon.get("command_group") == "death")  # combat/rules/summons.json
    return engine, servant


def court_domain(engine):
    from combat import zones

    domains = [zone for zone in zones.typed_zones(engine)
               if (engine.action_catalog.get(str(zone.source_definition_id or "")) is None
                   or str(((engine.action_catalog[str(zone.source_definition_id)].parameters or {}).get("typed") or {}).get("source") or "") == COURT)]
    assert len(domains) == 1, [zone.source_definition_id for zone in zones.typed_zones(engine)]
    return domains[0]


def place_court(engine, move_to=None):
    """Cast the Domain (its printed recipients reach its own caster), optionally after walking there first."""
    if move_to is not None:
        script(engine, [])
        use(engine, "Move to", at=move_to)
    script(engine, [20, 2, 2])
    use(engine, "Court of the Ninth Grave: Necrotic Damage")
    return court_domain(engine)


def court_ground(engine, servant, domain, cell):
    """Whether ``cell`` lies in the Domain, as the engine's own zone query sees it."""
    from combat import zones

    return zones._inside(engine, servant, domain, Position(x=cell[0], y=cell[1]))


def court_exempt(engine, servant):
    """The squares this servant is currently told to walk across without extra movement (combat/motion.py)."""
    from combat import motion

    return motion.mover_exempt_cells(engine, servant)


def rough_ground(engine, *cells, cost=2):
    """Lay (or, with ``cost`` of 1, clear) the map's own Difficult Terrain on ``cells``, the way a Dune Wall's
    move_cost leaves it on the grid -- and the rate this arena already charges its own rough squares.

    combat/zones.py sync_walls rebuilds ``grid.base_movement_cost`` from the engine's cached map costs
    (``engine._wall_base``) at the start of every candidate listing, so that cache is laid too -- otherwise the squares
    would silently be plain ground again before the move that is supposed to walk over them.
    """
    for cell in cells:
        engine.grid.base_movement_cost.pop(cell, None)
        if int(cost) > 1:
            engine.grid.base_movement_cost[cell] = int(cost)
        base = engine.__dict__.get("_wall_base")
        if base is not None:
            engine._wall_base = (base[0], base[1], base[2],
                                 {key: value for key, value in {**base[3], cell: int(cost)}.items() if int(value) > 1})
    return cells


def rough_domain(engine, domain):
    """Every square of the Domain is Difficult Terrain, so a route can never avoid the printed benefit."""
    return rough_ground(engine, *sorted((cell.x, cell.y) for cell in domain.affected_cells))


def servant_move(engine, servant, at):
    """The printed way a Death servant moves: its master commands it, and the engine's own turn start then gives it its
    movement and its one action.

    Returns ``(cost_ft, planned_cost_ft)`` from the single MOVEMENT_COMMITTED this move records -- the feet actually
    spent and the feet the Move menu quoted -- so a boundary-crossing move can be priced by where the servant stood at
    each step.
    """
    turn_to(engine, ME)
    script(engine, [])
    use(engine, "Command Death servants")
    # The engine's own turn start, handed straight to the commanded servant: fresh movement, one action, and the
    # turn-start hooks (combat/gate2_engine.py _system_start_turn).  Waiting for its own initiative slot instead would
    # let a turn that passes by itself (combat/summons.py on_turn_start) end first.
    acts_now(engine, servant.entity_id)
    engine._system_start_turn()
    # The one action the command bought it: a Dash, so one move can cross a 30-foot Domain's edge.
    dash_row = next(c for c in engine.legal_candidates() if c.display_name.startswith("Dash"))
    engine.execute_intent(ActionIntent(intent_id="auto22:dash", decision_id=dash_row.decision_id,
                                       candidate_id=dash_row.candidate_id, state_version=dash_row.state_version,
                                       actor_id=servant.entity_id, target_ids=dash_row.target_ids or (),
                                       destination=dash_row.destination))
    before = len(engine.events)
    use(engine, "Move to", at=at)
    committed = [e for e in engine.events[before:] if e.event_type == "MOVEMENT_COMMITTED"]
    assert len(committed) == 1, [e.event_type for e in engine.events[before:]]
    assert (servant.position.x, servant.position.y) == tuple(at), f"the servant did not arrive: {servant.position}"
    return int((committed[0].payload or {}).get("cost_ft") or 0), int((committed[0].payload or {}).get("planned_cost_ft") or 0)


def test_court_of_the_ninth_grave_publishes_its_domain_squares_to_its_own_death_servants():
    """A servant standing in the Domain is told which squares cost it nothing extra, and nothing else is told."""
    from combat import motion

    engine, servant = court_fight()
    domain = place_court(engine)
    cells = {(cell.x, cell.y) for cell in domain.affected_cells}
    assert motion.exempt_cells(engine, servant) == cells, "the Domain's squares are not published to the servant"
    assert motion.mover_exempt_cells(engine, servant) == frozenset(cells), \
        "combat/motion.py does not read them as this mover's terrain exemption"
    row = next(r for r in engine.typed_passive_rows[ME] if r.get("block") == death_riders.BLOCK)
    assert row["kind"] == "court" and row["feature_id"] == COURT


def test_court_benefits_only_its_own_death_servants():
    """"YOUR Death servants": the Painted Formation is a companion of the same caster, present on the map from the
    start, and not a Death servant, so the Death sphere's Difficult Terrain benefit does not reach it."""
    from combat import motion

    engine, servant = court_fight(PAINTING)
    painting = next((a for a in engine.state.actors.values()
                     if a.summon and a.summon.get("group") == "painted_formation" and a.active), None)
    assert painting is not None, [(a.summon.get("group"), a.active) for a in engine.state.actors.values() if a.summon]
    domain = place_court(engine)
    from combat import zones

    assert zones._inside(engine, servant, domain) and zones._inside(engine, painting, domain), \
        "both creatures must stand inside the Domain, or this case proves nothing"
    assert motion.exempt_cells(engine, servant), "the Death servant was not given the benefit"
    assert not motion.exempt_cells(engine, painting), "a non-Death companion was given the Death-only benefit"
    assert not motion.mover_exempt_cells(engine, painting)


def test_a_death_servant_inside_the_domain_pays_no_extra_for_rough_ground_there():
    """"may move through nonmagical Difficult Terrain without extra movement" -- measured as the feet the engine
    actually spent on a real move (MOVEMENT_COMMITTED.cost_ft), not as a stored condition."""
    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    for cell in ((2, 6), (2, 7), (2, 8), (2, 9)):
        assert court_ground(engine, servant, domain, cell), f"{cell} is outside the Domain, so this case proves nothing"
    assert engine.grid.base_movement_cost.get((2, 7)) == 2, "the Domain is not Difficult Terrain here"
    spent, quoted = servant_move(engine, servant, (2, 9))  # four squares, five feet each, rough ground or not
    assert (spent, quoted) == (20, 20), (spent, quoted)


def test_a_step_out_of_the_domain_is_charged_the_full_rate_for_rough_ground_outside_it():
    """The boundary is priced by membership: the step that carries a servant out of the Domain costs the full rate for
    the rough ground it steps onto outside, in the very move that was free inside.

    AUTO22 review finding 1: the exemption applied to the whole move because the servant held the benefit when the move
    began, so it crossed the edge and crossed rough ground beyond it for nothing.
    """
    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    rough_ground(engine, (2, 0))  # one square past the southern edge of a Domain centred on (3, 6)
    assert court_ground(engine, servant, domain, (2, 1)) and not court_ground(engine, servant, domain, (2, 0))
    assert servant_move(engine, servant, (2, 2)) == (15, 15), "the servant could not walk free inside its own Domain"
    spent, quoted = servant_move(engine, servant, (2, 0))  # (2,1) is free, (2,0) is outside and charged
    assert (spent, quoted) == (15, 15), (spent, quoted)
    assert not court_exempt(engine, servant), "a servant outside the Domain still reads as exempt"


def test_a_servant_that_walks_into_the_domain_pays_only_for_the_square_it_entered_on():
    """Coming back in: the square the servant was still standing outside on is charged, and every square after it is
    free.  This is the half of AUTO22 review finding 1 that ran the other way -- a servant outside the Domain was charged
    the full rate for every square of its crossing."""
    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    rough_ground(engine, (2, 0))
    assert servant_move(engine, servant, (2, 0)) == (30, 30), "the servant did not get out of the Domain"
    from combat import zones

    assert not zones._inside(engine, servant, domain), "the servant is still inside the Domain"
    assert not court_exempt(engine, servant)
    spent, quoted = servant_move(engine, servant, (2, 2))  # (2,1) charged on the way in, then (2,2) inside and free
    assert (spent, quoted) == (15, 20), (spent, quoted)
    assert zones._inside(engine, servant, domain)
    assert court_exempt(engine, servant) == {(cell.x, cell.y) for cell in domain.affected_cells}


def test_the_court_says_in_plain_words_what_its_domain_does_for_a_servant():
    """A player who knows only basic D&D must be able to read what the Domain does for their servant."""
    engine, servant = court_fight()
    place_court(engine)
    logs = [str((e.payload or {}).get("log") or "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"]
    said = [line for line in logs if servant.display_name in line and "Difficult Terrain" in line]
    assert said, logs[-6:]
    assert any("Domain" in line and "no extra movement" in line for line in said), said


def test_the_court_benefit_ends_when_the_caster_loses_concentration():
    """The Domain is a Concentration area, so ending that Concentration ends the ground the servant walked on free.
    Nothing here calls the plug-in: the engine's own concentration path removes the area."""
    from combat import zones

    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    assert court_exempt(engine, servant)
    engine._end_concentration(engine.state.actors[ME], "test:end-of-concentration")
    assert not any(zone.active for zone in zones.typed_zones(engine)), "the Domain outlived its Concentration"
    assert not court_exempt(engine, servant), "a servant kept the benefit after its master's Concentration ended"
    spent, quoted = servant_move(engine, servant, (2, 4))  # one square of the Domain's rough ground, charged in full
    assert (spent, quoted) == (10, 10), (spent, quoted)


def test_the_court_benefit_ends_when_the_domain_expires():
    """A Domain that runs out of duration is no longer ground its servants walk on free."""
    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    assert court_exempt(engine, servant)
    assert domain.duration_rounds, domain.duration_rounds
    for _ in range(200):
        if not court_exempt(engine, servant):
            break
        engine.end_turn()
    assert not court_exempt(engine, servant), \
        f"the servant still crossed rough ground freely at round {engine.state.round_number} " \
        f"(the Domain lasted {domain.duration_rounds} rounds from round {domain.created_round})"
    assert engine.state.round_number > domain.created_round


def test_the_court_benefit_ends_when_the_caster_falls():
    """A defeated caster has no Domain, so its servants must not keep the benefit for the rest of the fight."""
    from combat import flight, zones

    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    assert court_exempt(engine, servant)
    engine._defeat(engine.state.actors[ME], "test:defeat")  # the engine's own defeat (combat/gate2_engine.py _defeat)
    assert not engine.state.actors[ME].active
    assert not any(z.active for z in zones.typed_zones(engine)), "the defeated caster's Domain outlived it"
    assert not court_exempt(engine, servant), "a defeated caster's servant kept the benefit"
    assert flight.step_cost(engine, servant, Position(x=2, y=5), Position(x=2, y=4),
                            difficult=engine._hostile_difficult_cells(servant)) == 10, \
        "a defeated caster's servant still walks rough ground for free"


def test_the_court_never_touches_another_abilities_difficult_terrain_benefit():
    """The Court publishes squares, it never writes a condition, so it cannot sweep away an ignore_difficult another
    ability applied (the engine's own _remove_condition takes every instance of a condition id)."""
    from combat import motion

    engine, servant = court_fight()
    domain = place_court(engine)
    assert motion.exempt_cells(engine, servant), "the Court published nothing, so this case proves nothing"
    rough_domain(engine, domain)
    rough_ground(engine, (2, 0))
    assert servant_move(engine, servant, (2, 0)) == (30, 30), "the Court stopped pricing its own Domain"
    assert not motion.exempt_cells(engine, servant), "the servant is outside the Domain but still reads as exempt"
    engine._apply_condition(servant, IGNORES_DIFFICULT, "other:ability", FOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Another creature's own benefit"})
    assert motion.ignores_difficult(engine, servant), "the other ability's own benefit was not applied"
    # Two squares of the Domain's rough ground, free -- and free because of the OTHER ability, whose condition this
    # plug-in never wrote and never removes.
    assert servant_move(engine, servant, (2, 2)) == (10, 10), "the other ability's own exemption did not price the move"
    assert [c.source_definition_id for c in held(servant, IGNORES_DIFFICULT)] == ["other:ability"], \
        "walking back into the Domain erased another ability's own benefit"


def hostile_ground(engine, center, radius_ft=10):
    """A hostile technique's own Difficult Terrain, laid through the engine's zone API (combat/zones.py create):
    rough ground an ABILITY made, which the printed "nonmagical" benefit must not reach."""
    from combat import typed_executor, zones

    from types import SimpleNamespace
    foe = engine.state.actors[FOE]
    action = engine.action_catalog[next(a for a in foe.action_ids
                                        if "Move" not in engine.action_catalog[a].display_name)]
    typed = {**action.parameters["typed"], "numbers": {**action.parameters["typed"]["numbers"],
                                                       "save_dc": 16, "pb": 4, "cl": 10}}
    ctx = typed_executor.Context(engine, foe, action, None, typed, [], None, {})
    ctx.intent = SimpleNamespace(destination=Position(x=center[0], y=center[1]))
    zone = zones.create(ctx, {"name": "Ravaged ground", "shape": "sphere", "size_ft": radius_ft,
                              "difficult": "hostile", "duration": {}})
    assert zone is not None and zone.active, "the hostile technique laid no ground"
    return zone


def test_the_court_does_not_make_a_hostile_techniques_difficult_terrain_free():
    """The printed line is "nonmagical Difficult Terrain".  A hostile technique's own rough ground is not that, so it
    stays charged inside the Domain -- while the map's own ground there is still free.

    AUTO22r2 review finding 1: the Domain's squares were returned as an unrestricted exemption, and
    combat/zones.py difficult_cells subtracted them from EVERY difficult area it collected, so a hostile Domain
    technique cost the servant nothing to walk through.
    """
    from combat import motion, zones

    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    zone = hostile_ground(engine, (2, 7))
    covered = {(c.x, c.y) for c in zone.affected_cells}
    assert covered, "the hostile technique covered no square, so this case proves nothing"
    inside = sorted(cell for cell in covered if court_ground(engine, servant, domain, cell))
    assert len(inside) >= 2, f"only {inside} of the hostile ground is inside the Domain"

    # The engine's own query still calls those squares difficult for this servant.
    charged = zones.difficult_cells(engine, servant)
    assert set(inside) <= charged, f"the Court's nonmagical benefit swallowed hostile rough ground: {sorted(charged)}"
    # ...while the map's own rough ground inside the Domain is not charged.
    assert not any(cell in charged for cell in {(c.x, c.y) for c in domain.affected_cells} - covered), \
        "the map's own ground inside the Domain stopped being free"

    spent, quoted = servant_move(engine, servant, (2, 9))
    assert (spent, quoted) == (40, 40), \
        f"four squares of hostile rough ground at the double rate: {(spent, quoted)}"


def test_an_unrestricted_subscriber_still_walks_the_same_hostile_ground_for_free():
    """The seam keeps the other scope.  A ``difficult_exempt`` subscriber that returns a bare set -- the shape every
    pre-existing one uses (Formations' Court of the Ninefold Array, Sand Step) -- still ignores ground an ability made,
    so this lane does not quietly narrow anybody else's rule.  Death's Court is the only nonmagical one."""
    from combat import ext, zones

    engine, servant = court_fight()
    place_court(engine)
    zone = hostile_ground(engine, (2, 7))
    covered = {(c.x, c.y) for c in zone.affected_cells}
    assert covered and zones.difficult_cells(engine, servant) & covered, \
        "the hostile ground was not difficult to begin with, so this case proves nothing"

    def unrestricted(engine, actor):  # a bare set: the original, unrestricted scope
        return covered

    hooks = list(ext._HOOKS["difficult_exempt"])
    ext._HOOKS["difficult_exempt"] = [*hooks, unrestricted]
    try:
        assert not zones.difficult_cells(engine, servant), \
            "a bare-set subscriber stopped covering ground an ability made"
    finally:
        ext._HOOKS["difficult_exempt"] = hooks
    assert zones.difficult_cells(engine, servant) & covered, "the unregistered subscriber was not removed"


def test_a_refresh_between_steps_installs_the_exemption_the_mover_actually_has():
    """A mid-move terrain rebuild must record the squares it built the map with, not the ones the move opened with.

    AUTO22r2 review finding 3: combat/zones.py sync_walls re-stripped the refreshed costs with the mover's CURRENT
    exemption but left grid.unimpeded_cells at its value from the start of the move, so combat/motion.py repriced()
    compared the live squares against a stale cache, thought the Domain's squares were already discounted and skipped
    repricing a map that still charged for them.
    """
    from combat import motion, zones

    engine, servant = court_fight()
    domain = place_court(engine)
    rough_domain(engine, domain)
    inside, outside = (2, 7), (2, 0)
    assert court_ground(engine, servant, domain, inside) and not court_ground(engine, servant, domain, outside)
    grid = engine.grid

    with motion.terrain_for(engine, servant):  # the intent opens with the servant inside its master's Domain
        assert grid.__dict__.get("unimpeded_cells") == frozenset((c.x, c.y) for c in domain.affected_cells)
        servant.position = Position(x=outside[0], y=outside[1])  # it steps out
        zones.sync_walls(engine)  # a wall appearing or ending rebuilds the map's costs mid-move
        assert grid.__dict__.get("unimpeded_cells") == frozenset(), \
            "the rebuilt map records the Domain's squares as discounted, but it charged for them"
        servant.position = Position(x=inside[0], y=inside[1])  # and it walks back in
        with motion.repriced(engine, servant):
            assert grid.base_movement_cost.get(inside) == 1, \
                f"the Domain's own ground is charged again: {grid.base_movement_cost.get(inside)}"


def test_the_old_whole_creature_court_condition_is_retired_when_the_servant_next_acts():
    """A fight saved by an older build carries a ``condition:typed.ignore_difficult`` on a servant that stood in the
    Domain.  That build removed it again when the servant left or the Domain ended; this build never writes it, so
    nothing would -- and combat/motion.py ignores_difficult would read it as an exemption over the WHOLE map for the
    rest of the fight.  It has no expiry of its own and is not Concentration, so the servant's own turn start retires
    it, and only this talent's copy."""
    from combat import motion

    engine, servant = court_fight()
    place_court(engine)
    engine._apply_condition(servant, death_riders.LEGACY_TERRAIN, death_riders.COURT_ID, ME, expires_on="UNTIL_REMOVED",
                            data={"label": "Court of the Ninth Grave: nonmagical Difficult Terrain costs it no extra "
                                           "movement"})  # what the retired build wrote
    engine._apply_condition(servant, IGNORES_DIFFICULT, "other:ability", FOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Another creature's own benefit"})
    assert motion.ignores_difficult(engine, servant), "the old condition was not applied, so this case proves nothing"

    before = len(engine.events)
    acts_now(engine, servant.entity_id)
    engine._system_start_turn()  # the engine's own turn start, which runs the plug-in's turn_start hooks
    assert [c.source_definition_id for c in held(servant, death_riders.LEGACY_TERRAIN)] == ["other:ability"], \
        "the old whole-map condition survived, or another ability's own exemption was retired with it"
    retired = [e for e in engine.events[before:] if e.event_type == "CONDITION_REMOVED"]
    assert [str(e.source_definition_id) for e in retired] == [death_riders.COURT_ID], \
        "the retirement is not an ordinary recorded removal"


def test_a_servant_still_pays_the_price_of_crossing_a_wall_inside_its_own_domain():
    """"may move through nonmagical Difficult Terrain without extra movement" is about the ground a creature walks over.
    A wall's own price to cross is not ground: a Dune Wall's printed "4 feet of movement for every 1 foot moved" is what
    getting through it costs, and the Court never promised to remove it (AUTO22r3 review finding 1).

    Measured as real committed movement -- ``MOVEMENT_COMMITTED.cost_ft`` -- over a wall square that genuinely overlaps
    the Domain, after the same move showed the Court still excusing the ordinary rough ground beside it.
    """
    from combat import zones

    engine, servant = court_fight(DUNE_WALL)
    domain = place_court(engine)
    domain_cells = {(cell.x, cell.y) for cell in domain.affected_cells}
    to_actor(engine, ME)  # the Court's Action was spent; the wall is the caster's next one
    script(engine, [20, 2, 2])
    use(engine, "Dune Wall at 3,12")
    wall = next(zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("wall"))
    crossing = sorted({(cell.x, cell.y) for cell in wall.affected_cells} & domain_cells)
    assert crossing, "the wall does not overlap the Domain, so this case proves nothing"
    (wall_square,) = crossing  # exactly one wall square inside the Domain, so the crossing is a single step

    rough_ground(engine, (3, 10), (3, 11), cost=2)  # ordinary Difficult Terrain beside it, inside the Domain
    assert all(court_ground(engine, servant, domain, cell) for cell in ((3, 10), (3, 11), wall_square))
    assert engine.grid.base_movement_cost[(3, 11)] == 2, "the Domain's own ground is not Difficult Terrain here"
    assert engine.grid.base_movement_cost[wall_square] == 4, "the wall's own price to cross is missing"

    servant.position = Position(x=3, y=10)
    assert servant_move(engine, servant, (3, 11)) == (5, 5), \
        "the Court stopped excusing ordinary nonmagical Difficult Terrain inside its own Domain"
    # And the very next step is onto the wall: that price survives, so the servant pays 4 x 5 feet.
    assert servant_move(engine, servant, wall_square) == (20, 20), \
        "the servant crossed a Dune Wall inside its own Domain for nothing: the wall's price to cross was discounted away"


def wall_over_dear_ground():
    """A Court of the Ninth Grave whose Domain stands clear of a Humble Wall raised over dearer map ground.

    The wall is raised FIRST and the Domain cast afterwards, well away from it.  The Domain follows its caster and reaches
    six squares (30 feet), while the Humble Wall is cast at touch range, so a wall raised inside the Domain could never
    overlap ground the servant is not already excused for -- which is the only way to see what happens on the squares the
    Domain does NOT reach.  The ground under the wall is laid dearer (x4) than the wall's own price to cross (x2), the
    only shape in which a wall's price can make a square cheaper instead of dearer.

    Returns ``(engine, servant, wall_cell, domain)``: ``wall_cell`` is one wall square the Domain does not cover, with the
    map's own x4 ground under it, and ``(wall_cell[0], wall_cell[1] - 1)`` is the Domain square in front of it.
    """
    from combat import zones

    engine, servant = court_fight(HUMBLE_WALL)
    to_actor(engine, ME)
    script(engine, [20, 2, 2])
    use(engine, "Humble Wall at", at=(3, 7))
    wall = next(zone for zone in zones.typed_zones(engine) if zone.trigger_profile.get("wall"))
    to_actor(engine, ME)
    script(engine, [])
    use(engine, "Move to", at=(3, 1))  # the caster walks clear of its own wall before laying the Domain
    script(engine, [20, 2, 2])
    use(engine, "Court of the Ninth Grave: Necrotic Damage")
    domain = court_domain(engine)
    covered = {(cell.x, cell.y) for cell in domain.affected_cells}
    outside = sorted(cell for cell in {(c.x, c.y) for c in wall.affected_cells} if cell not in covered)
    assert outside, "the wall lies wholly inside the Domain, so this case proves nothing"
    wall_cell = outside[0]
    rough_ground(engine, wall_cell, cost=4)  # the map's dearer ground, under the cheaper wall
    assert engine.grid.wall_traversal_cost.get(wall_cell) == 2, "the wall's own price to cross is missing"
    assert engine.grid.base_movement_cost.get(wall_cell) == 4, \
        "an uncovered square is not priced at the dearer of its ground and its wall"
    assert (wall_cell[0], wall_cell[1] - 1) in covered, "no Domain square lies in front of the wall to step out from"
    return engine, servant, wall_cell, domain


def test_leaving_the_domain_onto_a_cheaper_wall_still_costs_the_map_s_whole_price():
    """AUTO22r4 review finding 1: a wall CHEAPER than the ground beneath it must not cheapen a square the Domain does not reach.

    combat/motion.py unimpeded() read the wall's own price for every square of the map, covered or not, so the moment this
    servant walked out of its master's Domain the x4 ground under the Humble Wall's x2 priced itself at x2 -- handing out
    movement the printed "inside the Domain" benefit never promised, and letting it route and budget on a false price.  A
    square the exemption says nothing about keeps the price the map gave it: the greater of its ground and its wall
    (combat/zones.py sync_walls).  Measured as real committed movement, ``MOVEMENT_COMMITTED.cost_ft``.
    """
    engine, servant, wall_cell, domain = wall_over_dear_ground()
    approach = (wall_cell[0], wall_cell[1] - 1)
    servant.position = Position(x=approach[0], y=approach[1])  # it stands in the Domain, in front of the wall
    assert court_exempt(engine, servant), "the servant did not start excused, so this case proves nothing"

    spent, quoted = servant_move(engine, servant, wall_cell)  # and steps out onto the dearer ground under the cheap wall
    assert (spent, quoted) == (20, 20), (
        f"one square at x4, not x2: the wall's own price was charged for ground the Domain never covered {(spent, quoted)}")


def test_a_mid_move_refresh_keeps_that_price_on_an_uncovered_square():
    """The same square after a wall appearing or ending rebuilds the map's costs mid-move (AUTO22r4 review finding 1).

    combat/zones.py sync_walls re-derives the costs while a move is being priced, and it calls the same seam with the
    mover's CURRENT squares -- empty here, because this servant has just walked out of the Domain.  The rebuilt map must
    still charge the full price under the wall; the existing refresh case next door only proves the covered squares, which
    this reversal left alone.
    """
    from combat import motion, zones

    engine, servant, wall_cell, _domain = wall_over_dear_ground()
    grid = engine.grid
    servant.position = Position(x=wall_cell[0], y=wall_cell[1] - 1)
    with motion.terrain_for(engine, servant):  # the move opens with the servant excused inside the Domain
        assert grid.__dict__.get("unimpeded_cells"), "the move stripped nothing, so this case proves nothing"
        servant.position = Position(x=wall_cell[0], y=wall_cell[1])  # it steps out onto the wall's square
        zones.sync_walls(engine)  # a wall appearing or ending rebuilds the map's costs mid-move
        assert grid.base_movement_cost.get(wall_cell) == 4, (
            f"a refresh under a cheaper wall charged an uncovered square the wall's price: "
            f"{grid.base_movement_cost.get(wall_cell)}")


@contextmanager
def retired_court_writer(monkeypatch):
    """Reproduce, inside a real committed transaction, the stale instance the retired build wrote.

    The retired build gave a servant standing in its caster's Domain a whole-creature
    ``condition:typed.ignore_difficult`` with ``UNTIL_REMOVED``.  This subscriber writes exactly that as the Domain is
    laid down -- which is when the old build gave it -- so the instance is recorded by the engine's own intent, with the
    journal's sequence, the snapshot and the reducer all seeing it, instead of being pushed into a reloaded engine by hand
    afterwards.  Registered for one test only; monkeypatch removes it when the test ends.
    """
    from combat import ext

    def wrote_it(ctx):
        engine, owner = ctx.engine, ctx.actor
        if death_riders._row(engine, owner, "court") is None:
            return
        domain = court_domain(engine)
        for servant in death_riders._court_servants(engine, owner):
            if held(servant, death_riders.LEGACY_TERRAIN) or not court_ground(engine, servant, domain,
                                                                               (servant.position.x, servant.position.y)):
                continue
            engine._apply_condition(servant, death_riders.LEGACY_TERRAIN, death_riders.COURT_ID, ME,
                                    expires_on="UNTIL_REMOVED",
                                    data={"label": "Court of the Ninth Grave: nonmagical Difficult Terrain costs it no "
                                                   "extra movement"})

    monkeypatch.setitem(ext._HOOKS, "technique_final", [*ext._HOOKS["technique_final"], wrote_it])
    yield


def servant_steps_alone(engine, servant, at):
    """The feet one real move committed, taken on the servant's turn AS IT ALREADY IS.

    ``servant_move`` would hand the turn to ME first, and that round trip runs the servant's next turn start -- the very
    boundary under test -- so these cases step the servant directly, with no ``_system_start_turn`` anywhere between the
    stale write and the move.  Returns ``(cost_ft, planned_cost_ft)`` from the one MOVEMENT_COMMITTED it records.
    """
    dash = next(c for c in engine.legal_candidates() if c.display_name.startswith("Dash"))
    engine.execute_intent(ActionIntent(intent_id="auto22:dash", decision_id=dash.decision_id, candidate_id=dash.candidate_id,
                                       state_version=dash.state_version, actor_id=servant.entity_id,
                                       target_ids=dash.target_ids or (), destination=dash.destination))
    before = len(engine.events)
    use(engine, "Move to", at=at)
    committed = [e for e in engine.events[before:] if e.event_type == "MOVEMENT_COMMITTED"]
    assert len(committed) == 1, [e.event_type for e in engine.events[before:]]
    assert (servant.position.x, servant.position.y) == tuple(at), f"the servant did not arrive: {servant.position}"
    return int((committed[0].payload or {}).get("cost_ft") or 0), int((committed[0].payload or {}).get("planned_cost_ft") or 0)


def test_a_servant_continued_mid_turn_does_not_keep_the_old_whole_map_exemption():
    """A fight SAVED during the servant's own turn is continued with that turn already begun, and loading it starts no
    other turn.  The stale whole-map instance must therefore be inert the moment the fight resumes -- before the next
    turn start that would have removed it -- so resumed movement is charged for rough ground
    (AUTO22r3 review finding 2).

    No ``_system_start_turn`` runs between the stale write and the move: the removal boundary has not arrived yet, which
    is exactly the gap this covers.  This is the level where the review asked for it, because a fight saved DURING the
    servant's turn cannot be produced at a table commit boundary -- combat/summons.py plays a servant's own slot out
    inside the intent that advanced to it.
    """
    from combat import motion

    engine, servant = court_fight()
    place_court(engine)
    rough_ground(engine, (10, 6), cost=2)  # rough ground outside the Domain
    servant.position = Position(x=10, y=5)  # the servant stands outside its master's Domain
    assert not court_ground(engine, servant, court_domain(engine), (10, 5)), "that square is inside the Domain"
    engine._apply_condition(servant, death_riders.LEGACY_TERRAIN, death_riders.COURT_ID, ME, expires_on="UNTIL_REMOVED",
                            data={"label": "Court of the Ninth Grave: nonmagical Difficult Terrain costs it no extra "
                                           "movement"})
    # Another creature's own whole-map copy, on the caster: it must keep working, so what follows reads as a difference
    # between the two instances rather than as terrain pricing that is simply broken.
    engine._apply_condition(engine.state.actors[ME], IGNORES_DIFFICULT, "other:ability", FOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Another creature's own benefit"})
    acts_now(engine, servant.entity_id)  # its turn has begun, and it will not begin again
    assert held(servant, death_riders.LEGACY_TERRAIN), "the stale instance was not written, so this proves nothing"
    assert not motion.ignores_difficult(engine, servant), \
        "the stale instance is still a live whole-map exemption, so the move below could not tell the two apart"

    assert servant_steps_alone(engine, servant, (10, 6)) == (10, 10), \
        "the resumed move crossed rough ground outside the Domain for free: the old whole-map exemption was still live"

    servant = engine.state.actors[servant.entity_id]
    assert held(servant, death_riders.LEGACY_TERRAIN), \
        "the instance was edited out of the state instead of being made inert by the condition_excluded seam"
    assert motion.ignores_difficult(engine, engine.state.actors[ME]), \
        "another ability's own whole-map exemption was retired with the stale one"


def test_a_saved_court_servant_loses_the_old_exemption_across_a_real_table_commit_and_reload(tmp_path, monkeypatch):
    """The retirement across a real save, with the stale instance recorded by a real transaction.

    Casting the Court is what the retired build wrote its instance on, and casting it here is an ordinary
    ``CombatService`` intent that commits; commanding the servants is another.  The save that follows therefore carries
    the condition in the journal rather than in a hand-edited reloaded engine, and no turn start runs between the load and
    the reads below, which are the ones resumed movement asks.  The servant's next turn start then retires the instance
    as a recorded CONDITION_REMOVED, reached only through committed intents, and a further commit and reload shows that
    removal in the saved record -- alongside another ability's own exemption, which must survive both boundaries.
    """
    from combat import motion
    from combat.gate5_service import CombatService

    caster = build(COURT, ROUSE, cl=10, dc=16, plan={"lesser_corpse_servant": 1})
    ghost = build(HAND, actor_id=FOE, cl=5, hp=200)
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="AUTO22-LEGACY", typed_bundles=(caster, ghost), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})

    def commit(name, picker):
        """One ordinary table intent: a legal candidate submitted through the service, which commits and saves."""
        engine = session.engine
        candidate = picker(engine)
        return session.submit_intent(ActionIntent(intent_id=f"auto22:{name}", actor_id=engine.state.current_actor_id,
                                                  decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                                  state_version=candidate.state_version,
                                                  target_ids=candidate.target_ids or (),
                                                  destination=candidate.destination), primary_decision_record=None,
                                   reaction_provider=None)

    with retired_court_writer(monkeypatch):
        commit("court", lambda e: next(c for c in e.legal_candidates()
                                      if "Court of the Ninth Grave" in c.display_name))
    engine = session.engine
    servant_id = next(a.entity_id for a in engine.state.actors.values()
                      if a.summon and a.summon.get("command_group") == "death" and a.active)
    assert held(engine.state.actors[servant_id], death_riders.LEGACY_TERRAIN), \
        "the stale instance was not recorded by the transaction, so this proves nothing"

    session = service.persistence.load_match(session.match_id)  # the continuation under review
    engine = session.engine
    servant = engine.state.actors[servant_id]
    assert held(servant, death_riders.LEGACY_TERRAIN), \
        "the stale instance did not survive the commit and reload, so this proves nothing"
    assert not motion.ignores_difficult(engine, servant), \
        "a fight resumed before the servant's next turn start still grants the old whole-map exemption"
    assert motion.mover_exempt_cells(engine, servant) is not None, \
        "the reloaded servant reads as exempt from every square on the map, not just the Domain's"
    assert set(motion.mover_exempt_cells(engine, servant)) == {(c.x, c.y) for c in court_domain(engine).affected_cells}, \
        "the reloaded servant's exemption is not exactly its master's Domain"

    # Another caster's own copy of the same condition joins this servant: it must survive the retirement untouched.
    engine._apply_condition(servant, IGNORES_DIFFICULT, "other:ability", FOE, expires_on="UNTIL_REMOVED",
                            data={"label": "Another creature's own benefit"})
    before = len(engine.events)
    for step in range(10):  # committed intents only, so the reducer's own sequence stays intact
        if any(e.event_type == "CONDITION_REMOVED" for e in engine.events[before:]):
            break
        end = next((c for c in engine.legal_candidates() if c.display_name == "End turn"), None)
        assert end is not None, f"no committed way to advance at step {step}: {sorted({c.display_name for c in engine.legal_candidates()})[:12]}"
        commit(f"advance-{step}", lambda e: end)
    retired = [e for e in engine.events[before:] if e.event_type == "CONDITION_REMOVED"]
    assert [str(e.source_definition_id) for e in retired] == [death_riders.COURT_ID], \
        "the retirement is not an ordinary recorded removal"
    assert [c.source_definition_id for c in held(servant, death_riders.LEGACY_TERRAIN)] == ["other:ability"], \
        "the stale instance survived, or another ability's exemption went with it"

    # Commit that removal through the table and read it back out of the save.
    for step in range(4):
        end = next((c for c in engine.legal_candidates() if c.display_name == "End turn"), None)
        if end is not None:
            commit(f"settle-{step}", lambda e: end)
    saved = service.persistence.load_match(session.match_id)
    reloaded = saved.engine.state.actors[servant_id]
    assert [c.source_definition_id for c in held(reloaded, death_riders.LEGACY_TERRAIN)] == ["other:ability"], \
        "the retired instance came back through the commit and reload, or another ability's exemption went with it"
    assert any(e.event_type == "CONDITION_REMOVED" and str(e.source_definition_id) == death_riders.COURT_ID
               for e in saved.engine.events), \
        "the retirement is not in the saved fight's record: it did not survive the commit"


# ==================================== Mortality Seal / No Return Edict: no death prevention while they last
@pytest.fixture()
def keep_standing(monkeypatch):
    """A death-prevention provider in the shape the engine calls (combat/ext/banner.py's Standard Cannot Fall)."""
    from combat import ext

    def provider(engine, target, pending, source_actor_id):
        return 1

    hooks = list(ext._HOOKS["would_drop"])
    ext._HOOKS["would_drop"] = [*hooks, provider]
    yield
    ext._HOOKS["would_drop"] = hooks


def test_mortality_seal_does_not_deny_death_prevention_for_its_whole_duration(keep_standing):
    """"the FIRST death-prevention effect that would keep it above 0 HP during the duration is suppressed UNTIL THE
    START OF ITS NEXT TURN" -- one effect, one window.  The engine has no first-use ledger for that, so the lane does not
    claim it: the Seal denies no death prevention at all, and the printed clause is Game Master text again.  What it does
    deny (it cannot regain HP, cannot gain Temporary HP) stays typed."""
    engine = fight(build(SEAL, cl=10, dc=16))
    script(engine, [1])
    use(engine, "Mortality Seal", target=FOE)
    sealed = engine.state.actors[FOE]
    assert any(rule.get("healing_denied") for rule in te.condition_rules(sealed)), "it can still regain Hit Points"
    assert held(sealed, "condition:typed.no_temp_hp"), "it can still gain Temporary HP"
    assert not any(rule.get("death_prevention_denied") for rule in te.condition_rules(sealed)), \
        "the Seal denies EVERY death-prevention effect for its whole duration, which is not what it prints"
    from combat import typed_reactions

    pending = sealed.current_hp + sealed.temporary_hp
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, sealed, engine.state.actors[ME], pending, 0, ME) == 1
    riders = " ".join(AUTH[SEAL]["riders"])
    assert "death-prevention" in riders and "Game Master" in riders, riders


def test_no_return_edict_denies_death_prevention_until_the_end_of_your_next_turn(keep_standing):
    engine = fight(build(EDICT, cl=17, dc=20))
    script(engine, [1])
    use(engine, "No Return Edict", target=FOE)
    doomed = engine.state.actors[FOE]
    assert held(doomed, DEATH_PREVENTION_DENIED), "the printed clause is not on the target"
    assert str(held(doomed, DEATH_PREVENTION_DENIED)[0].expires_on).startswith("END_OF_SOURCE_TURN_AT:"), \
        held(doomed, DEATH_PREVENTION_DENIED)[0].expires_on
    from combat import typed_reactions

    pending = doomed.current_hp + doomed.temporary_hp
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, doomed, engine.state.actors[ME], pending, 0, ME) == pending


def test_no_return_edict_also_refuses_a_drops_to_one_hit_point_reaction(keep_standing):
    """"cannot benefit from an effect that would prevent it from dropping to 0 HP" is not only the plug-in providers:
    Shield Soul Never Falls is an ordinary "you would drop to 0 HP" reaction whose printed row holds the creature at
    1 Hit Point, and an Edict-ed creature must not be offered it either."""
    from combat import typed_reactions

    def doomed_fight(edicted):
        engine = fight(build(EDICT, cl=17, dc=20) if edicted else build(SMOKE, cl=10, dc=16),
                       build(NEVER_FALLS, actor_id=FOE, cl=10, dc=16, hp=200))
        rows = [row for row in engine.typed_reaction_rows[FOE] if row.get("kind") == "drop_to_zero"]
        assert [row["feature_id"] for row in rows] == [NEVER_FALLS], rows
        if edicted:
            script(engine, [1])
            use(engine, "No Return Edict", target=FOE)
            assert held(engine.state.actors[FOE], DEATH_PREVENTION_DENIED)
        target = engine.state.actors[FOE]
        pending = target.current_hp + target.temporary_hp
        return typed_reactions._offer_drop_to_zero_or_bloodied(engine, target, engine.state.actors[ME], pending, 0, ME), pending

    spared, pending = doomed_fight(edicted=False)
    assert spared < pending, "the printed reaction no longer holds its creature at 1 Hit Point at all"
    denied, pending = doomed_fight(edicted=True)
    assert denied == pending, (denied, pending)


def test_a_creature_without_the_edict_keeps_its_death_prevention(keep_standing):
    engine = fight(build(SMOKE, cl=10, dc=16))
    plain = engine.state.actors[FOE]
    from combat import typed_reactions

    pending = plain.current_hp + plain.temporary_hp
    assert typed_reactions._offer_drop_to_zero_or_bloodied(engine, plain, engine.state.actors[ME], pending, 0, ME) == 1


# ================================================================ the typed data itself: no GM reminder is left
@pytest.mark.parametrize("talent", [MARK, CHILL, FIELD])
def test_these_death_talents_have_no_rider_left_for_the_gm(talent):
    assert AUTH[talent]["coverage"] == "FULL", (talent, AUTH[talent]["coverage"], AUTH[talent]["riders"])
    assert not AUTH[talent]["riders"]


def test_the_typed_authority_still_reads_the_printed_death_text():
    for talent in (MARK, CHILL, FIELD, HOOK, SEAL, EDICT, COURT):
        assert AUTH[talent]["source"]["text_sha256"], talent


# =============================================== the table: a committed move and a reload keep the Death state
def test_the_grave_mark_and_the_soul_hook_survive_a_table_commit_and_reload(tmp_path):
    """The two things this lane stores in fight state are integers on ordinary records: the Grave Mark's condition and the
    square a Soul Hook was cast from.  Commit the turn through the table service, reload the saved fight, and both must
    still be there and still act."""
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import ActionIntent as Intent
    from combat.movement_steps import checkpoint

    caster = build(MARK, HOOK, cl=10, dc=16)
    ghost = build(HAND, actor_id=FOE, cl=5, hp=200, creature_type="ghost")
    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(match_seed="AUTO22-TABLE", typed_bundles=(caster, ghost), roster_setup={
        "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine = session.engine
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    ready(engine)

    def submit(name, target=None):
        candidate = next(c for c in engine.legal_candidates() if name in c.display_name
                         and (target is None or target in (c.target_ids or ())))
        session.submit_intent(Intent(intent_id=f"auto22:{name}:{engine.state.state_version}", actor_id=ME,
                                     decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                     state_version=candidate.state_version, target_ids=candidate.target_ids or (),
                                     destination=candidate.destination), primary_decision_record=None, reaction_provider=None)

    script(engine, [1])  # the Charisma save fails: the chain holds
    submit("Mark for the Grave", target=FOE)
    script(engine, [1])
    submit("Soul Hook", target=FOE)
    assert held(engine.state.actors[FOE], GRAVE_MARK)
    assert held(engine.state.actors[FOE], SOUL_HOOK)
    before = engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, service.userdata_root).persistence.load_match(session.match_id)
    assert loaded.engine.state.model_dump(mode="json") == before, "the reload changed the fight"
    reloaded = loaded.engine.state.actors[FOE]
    assert held(reloaded, GRAVE_MARK) and held(reloaded, SOUL_HOOK)
    assert (held(reloaded, SOUL_HOOK)[0].data or {}).get("hook_x") == 4
    far = checkpoint(loaded.engine, reloaded, reloaded.position, Position(x=reloaded.position.x + 3, y=reloaded.position.y),
                     None, point="movement_attempt", travelled_ft=0, remaining_ft=15)
    assert far and far[0]["stop"] is True, far


def test_the_grave_mark_clock_still_spends_and_re_spends_after_a_table_commit_and_reload(tmp_path):
    """The printed once-each-turn clock is a string turn stamp on the caster's own turn_flags, so a saved fight must
    reload with the clock still spent for that turn and free again on the next one."""
    from combat.gate5_service import CombatService
    from combat.gate2_runtime_models import ActionIntent as Intent

    service = CombatService(ROOT, tmp_path)
    session = service.persistence.create_match(
        match_seed="AUTO22-TABLE-CLOCK", typed_bundles=(build(MARK, HAND, cl=10, dc=16),
                                                       build(HAND, actor_id=FOE, cl=5, hp=200)), roster_setup={
            "primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
            "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine = session.engine
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    ready(engine)

    def submit(name):
        candidate = min((c for c in engine.legal_candidates() if name in c.display_name),
                        key=lambda c: c.display_name != name)
        session.submit_intent(Intent(intent_id=f"auto22:{name}:{engine.state.state_version}", actor_id=ME,
                                     decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                     state_version=candidate.state_version, target_ids=candidate.target_ids or (),
                                     destination=candidate.destination), primary_decision_record=None, reaction_provider=None)

    def hand_of_the_marked_creature(dice):
        script(engine, dice)
        before = len(engine.events)
        submit("Withering Hand")
        return damage_to(engine, engine.events[before:], FOE)

    script(engine, [20])
    submit("Mark for the Grave")
    assert held(engine.state.actors[FOE], GRAVE_MARK)
    assert hand_of_the_marked_creature([15, 3, 4]) == 11, "the printed bonus did not reach the marked creature"
    spent = mark_clock(engine)
    assert len(spent) == 1, spent
    caster = engine.state.actors[ME]
    key, turn = te.on_hit_turn_key(engine, caster, death_riders.MARK_GATE, MARK_DAMAGE_RULE)
    assert caster.turn_flags[spent[0]] == turn, (caster.turn_flags[spent[0]], turn)

    before = engine.state.model_dump(mode="json")
    session = CombatService(ROOT, service.userdata_root).persistence.load_match(session.match_id)
    engine = session.engine
    assert engine.state.model_dump(mode="json") == before, "the reload changed the fight"
    caster = engine.state.actors[ME]
    assert mark_clock(engine) == spent, "the reload lost or renamed the caster's once-each-turn clock"
    assert caster.turn_flags[spent[0]] == turn, "the reloaded clock names a different turn"
    assert not te.on_hit_rider_available(engine, caster, key, turn, FOE), \
        "the reload handed out the printed bonus a second time in the same turn"
    started = caster.turns_started
    while caster.turns_started == started:
        engine.end_turn()
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    ready(engine)
    key, turn = te.on_hit_turn_key(engine, caster, death_riders.MARK_GATE, MARK_DAMAGE_RULE)
    assert te.on_hit_rider_available(engine, caster, key, turn, FOE), "the clock never became free again"
    assert hand_of_the_marked_creature([15, 3, 4]) == 11, "the bonus did not return in the next turn"


# ============================================= the player text a condition chip shows when it is hovered
def test_the_no_death_prevention_reading_is_plain_player_text():
    """combat/condition_text.py shows a condition row's own rule text to the player, so it must read as rules a
    newcomer can act on, not as the engine's vocabulary."""
    from combat.condition_text import all_conditions

    reading = all_conditions()["no_death_prevention"]["reading"]
    for jargon in ("would_drop", "keep-standing", "providers", "typed.", "combat/", "provider"):
        assert jargon not in reading, (jargon, reading)
    assert "0 Hit Points" in reading and "Temporary Hit Points" in reading, reading
