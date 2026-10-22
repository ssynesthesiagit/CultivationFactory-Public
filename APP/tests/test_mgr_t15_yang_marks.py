"""MGR-T15 Yang marks (1D1): the five source records' intact clauses, through real fights.

Each test fails on the code before this round: marks kept a producer's expression regardless of
willingness, a willing bearer had no way to end its own Kindled Mark, Completing Flame Mantle's
linked mark and Complete Force damage-type rider did nothing, Life Refuses Closure protected a
creature that was killed outright, Dawn's Kindled Mark never expired and its Prone target stayed
down, and Ten-Thousand Motions Become Noon applied no start-of-turn mark, no movement light and
no maximum response die.
"""
import pytest

from combat import typed_reactions
from combat.ext.yang_sun_marks import EXCEPTION, DIM_LIGHT, completion_allows, consume_completion
from combat.ext.yang_recovery import ROUND, pay_complete_aim_slot
from combat.posture import prone_conditions
from combat.typed_executor import CONDITION_PREFIX, bears_mark, block_mark
from combat.ext import states
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn)


def _context(engine, actor, target):
    marker = engine.state.actors[actor] if isinstance(actor, str) else actor
    return states.context(engine, marker, "test:mark", [target], {})


def _kindled_ids(actor, owner=OWNER):
    return [c.condition_id for c in actor.conditions.values()
            if c.condition_id.startswith(CONDITION_PREFIX + "mark.kindled_mark." + owner)]


def _overkindled_ids(actor, owner=OWNER):
    return [c.condition_id for c in actor.conditions.values()
            if c.condition_id.startswith(CONDITION_PREFIX + "mark.overkindled_mark." + owner)]


def _hit(engine, who, damage=30):
    return typed_reactions.on_damage(engine, who, damage, 0, source_definition_id="action:test.attack",
                                     source_actor_id=FOE)


def _move_candidate(combat, mid, destination):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if c.display_name.startswith("Move to ") and c.destination
            and (c.destination.x, c.destination.y) == destination]
    assert rows, f"no move to {destination}"
    return rows[0]


DAGGER = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}


# ---------------------------------------------------------------- Kindled / Overkindled expression
def test_rising_mark_expression_follows_the_bearers_willingness(tmp_path):
    # "A Rising Mark on you, a willing creature ... is a Kindled Mark. ... on an unwilling
    # creature ... is an Overkindled Mark." A neutral placement is resolved by the bearer; an owning
    # record that already names an expression keeps it (Kindle the Wounded Breath heals a chosen foe
    # and prints a Kindled Mark for it).
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    engine = combat._load_session(mid).engine
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    block_mark(_context(engine, OWNER, ally), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _kindled_ids(ally) and not _overkindled_ids(ally)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _overkindled_ids(foe) and not _kindled_ids(foe)
    block_mark(_context(engine, OWNER, engine.state.actors[OWNER]),
               {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    me = engine.state.actors[OWNER]
    assert _kindled_ids(me) and not _overkindled_ids(me)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert _kindled_ids(foe)  # a named Kindled Mark is not reclassified


def test_a_willing_bearer_ends_its_kindled_mark_without_an_action(tmp_path):
    # "A willing creature may end your Rising Mark on itself at any time, no Action required."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    assert _kindled_ids(reload(tmp_path, mid).state.actors[ALLY])
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    action_available = engine.state.actors[ALLY].action_available
    ending = candidate(combat, mid, "End a Kindled Mark on yourself")
    settle(table, mid, ending.candidate_id)
    engine = reload(tmp_path, mid)
    assert not _kindled_ids(engine.state.actors[ALLY])
    assert engine.state.actors[ALLY].action_available == action_available


# ---------------------------------------------------------------- Completing Flame Mantle
def test_mantle_self_kindle_also_marks_one_willing_creature_within_ten_feet(tmp_path):
    # "when you use Kindle the Rising on yourself, you may also apply a Kindled Mark to one
    # willing creature within 10 feet" -- while the Mantle is active.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"], positions={
        OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    settle(table, mid, candidate(combat, mid, "Completing Flame Mantle").candidate_id)
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=OWNER).candidate_id,
                    picks={"choice:needle.mantle_link": ALLY})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.mantle_link" for p in prompts)
    engine = reload(tmp_path, mid)
    assert _kindled_ids(engine.state.actors[OWNER]) and _kindled_ids(engine.state.actors[ALLY])


def test_mantle_zone_keeps_its_printed_light_and_grappler_damage(tmp_path):
    # "you emit bright light in a 10-foot radius and dim light for an additional 10 feet";
    # "a creature that starts its turn Grappling you takes Fire or Radiant damage equal to
    # your Proficiency Bonus + your Key Ability modifier"; the Mantle "does not count as sunlight".
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    bundle = compile_character(sheet(["TAL_YANG_COMPLETING_FLAME_MANTLE"], cl=15), actor_id=OWNER)
    row = next(a for a in bundle["action_catalog"] if a["source_definition_id"].endswith("TAL_YANG_COMPLETING_FLAME_MANTLE"))
    spec = row["parameters"]["typed"]["zone_spec"]
    assert spec["visual"]["light"]["radius_ft"] == 10 and spec["visual"]["light"]["level"] == "bright"
    assert spec["profile"].get("grappling_owner") == 1
    trigger = spec["triggers"][0]
    assert trigger["on"] == ["grappler_start"]
    damage = trigger["effects"][0]
    assert damage["damage_types"] == ["fire", "radiant"]
    assert damage["formula"] == "key_ability_modifier"
    assert damage["dice"]["bonus_formula"] == "pb"
    assert spec["visual"].get("sunlight") is None  # illumination is not tracked; the Mantle is not sunlight


def test_mantle_wraps_complete_force_damage_only_for_its_owner(tmp_path):
    # "once per turn when you spend a Kindled Mark with Complete Force, the bonus damage may be
    # Fire, Radiant, or Force damage instead."
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    with_mantle = compile_character(sheet(["TAL_YANG_COMPLETING_FLAME_MANTLE"], cl=15), actor_id=OWNER)
    row = next(r for r in with_mantle["typed_reactions"] if r["feature_id"] == "TAL_YANG_KINDLED_RESPONSES#complete_force")
    assert [e.get("type") for e in row["effects"] if e.get("type", "").startswith("yang_completion")] == ["yang_completion_damage"]
    without = compile_character(sheet(["TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising"], cl=15), actor_id=OWNER)
    plain = next(r for r in without["typed_reactions"] if r["feature_id"] == "TAL_YANG_KINDLED_RESPONSES#complete_force")
    assert not any(str(e.get("type", "")).startswith("yang_completion") for e in plain["effects"])


# ---------------------------------------------------------------- Life Refuses Closure
def test_life_refuses_closure_cannot_hold_a_creature_killed_outright(tmp_path):
    # Trigger: "would be reduced to 0 Hit Points but not killed outright". Leftover damage past
    # current + maximum HP is instant death, so 1 Hit Point is not a possible outcome.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    from combat import pending_damage

    with pending_damage.scope(engine, ally, 100, "SLASHING", "action:test.attack", FOE):
        assert _hit(engine, ally, 100) == 100
    assert not _kindled_ids(ally)
    assert not prone_conditions(ally)


def test_life_refuses_closure_records_the_first_damage_exception(tmp_path):
    # "the first time it deals damage, it may spend its Kindled Mark with Complete Force without
    # counting against your once-per-round limit"; a Life mark is Force-only, never Aim.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    held = [c for c in ally.conditions.values() if c.condition_id == EXCEPTION]
    assert held and held[0].data["source"] == "TAL_YANG_LIFE_REFUSES_CLOSURE"
    assert held[0].data["kind"] == "first_damage"
    assert completion_allows(engine, OWNER, ally, "force")
    assert not completion_allows(engine, OWNER, ally, "aim")
    assert consume_completion(engine, OWNER, ally, "force")
    assert not completion_allows(engine, OWNER, ally, "force")


def test_life_refuses_closure_long_rest_limit_is_per_creature(tmp_path):
    # "Use Limit: Once per Long Rest per creature": a second use on the same ally is refused even
    # after the Reaction comes back; another creature still has its own use.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    engine.state.actors[OWNER].reaction_available = True
    assert _hit(engine, ally) == 30


def test_life_exception_pays_complete_force_once(tmp_path):
    # "the first time it deals damage, it may spend its Kindled Mark with Complete Force without
    # counting against your once-per-round limit."
    from combat.ext import yang_sun_marks as sun

    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    bonus = sun.exception_complete_force(engine, ally, engine.state.actors[FOE], {}, None, "action:test.attack")
    assert isinstance(bonus, int) and bonus > 0
    assert not bears_mark(ally, OWNER, "Kindled Mark")
    assert sun.exception_complete_force(engine, ally, engine.state.actors[FOE], {}, None, "action:test.attack") is None
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) is None  # never takes the shared round slot


# ---------------------------------------------------------------- Dawn Commands the Fallen Breath
def test_dawn_stands_the_target_and_times_its_mark(tmp_path):
    # "The target drops to 1 Hit Point instead of dying and gains a Kindled Mark that lasts for
    # 1 minute. It may immediately stand if Prone."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    engine._apply_condition(ally, CONDITION_PREFIX + "prone", "test:prone", FOE, expires_on="UNTIL_REMOVED")
    assert prone_conditions(ally)
    assert _hit(engine, ally) == 4
    assert not prone_conditions(ally)
    mark = [c for c in ally.conditions.values() if c.condition_id in _kindled_ids(ally)]
    from combat.ext import effect_durations
    # "lasts for 1 minute" = ten rounds from now (combat/ext/effect_durations.py), not the fight
    assert mark and mark[0].expires_on == effect_durations.round_token(engine, 10)
    assert any(c.condition_id == EXCEPTION and c.data["kind"] == "first_hit_or_save" for c in ally.conditions.values())


def test_dawn_exception_pays_complete_aim_outside_the_round_slot(tmp_path):
    # "it may spend its Kindled Mark with Complete Force or Complete Aim without counting against
    # your once-per-round limit."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    engine.state.actors[OWNER].turn_flags[ROUND] = engine.state.round_number
    assert completion_allows(engine, OWNER, ally, "aim")
    assert consume_completion(engine, OWNER, ally, "aim")
    assert engine.state.actors[OWNER].turn_flags[ROUND] == engine.state.round_number  # slot untouched by the exception


def test_dawn_exception_is_not_spent_when_complete_aim_takes_the_free_round_slot(tmp_path):
    # Regression: with the once-per-round slot free, a Complete Aim must take the slot and keep the
    # Dawn exception held. Before the fix, the exception was spent and the slot left free, so the
    # owner could take a second Yang response in the same round.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    owner = engine.state.actors[OWNER]
    owner.turn_flags.pop(ROUND, None)
    assert completion_allows(engine, OWNER, ally, "aim")
    pay_complete_aim_slot(engine, owner, ally)
    assert owner.turn_flags[ROUND] == engine.state.round_number
    assert completion_allows(engine, OWNER, ally, "aim")  # exception still held
    assert any(c.condition_id == EXCEPTION and (c.data or {}).get("owner") == OWNER for c in ally.conditions.values())


# ---------------------------------------------------------------- Kindle the Rising in one engine (review 1)
KINDLE = 'TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising'


def test_two_kindle_owners_share_one_engine_and_each_keeps_its_own_end_button(tmp_path):
    # The end-button id must be per owner: a fixed id collided (TYPED_ACTION_ID_COLLISION) when two
    # Kindle the Rising bundles were registered in the same engine.
    from combat.ext import yang_sun_marks as sun

    combat, table, mid = fixture(tmp_path, [KINDLE], ally_talents=[KINDLE])
    engine = combat._load_session(mid).engine
    ids = {str(a.source_definition_id) for a in engine.action_catalog.values()
           if str(a.source_definition_id).startswith(sun.CANCEL)}
    assert ids == {sun.cancel_id(OWNER), sun.cancel_id(ALLY)}
    block_mark(_context(engine, OWNER, engine.state.actors[ALLY]), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    block_mark(_context(engine, ALLY, engine.state.actors[FOE]), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert sun.offer_cancel(engine, engine.state.actors[ALLY]) == [sun.cancel_id(OWNER)]
    assert sun.offer_cancel(engine, engine.state.actors[FOE]) == [sun.cancel_id(ALLY)]


def test_overkindled_replaces_a_kindled_mark_from_the_same_owner(tmp_path):
    # A Kindled and an Overkindled Mark are one Rising Mark family: a neutral Rising Mark on an
    # unwilling creature that already holds the owner's Kindled Mark leaves exactly one, Overkindled.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert _kindled_ids(foe)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _overkindled_ids(foe) and not _kindled_ids(foe)
    assert len([c for c in foe.conditions.values() if c.condition_id.startswith(CONDITION_PREFIX + "mark.")]) == 1


# ---------------------------------------------------------------- Ten-Thousand Motions Become Noon
def _cast_noon(table, combat, mid, at):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if c.display_name.startswith("Ten-Thousand Motions Become Noon")
            and c.destination and (c.destination.x, c.destination.y) == at]
    assert rows, f"Ten-Thousand Motions Become Noon cannot be centred on {at}"
    settle(table, mid, rows[0].candidate_id)


def test_noon_ally_start_of_turn_may_gain_a_kindled_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert _kindled_ids(engine.state.actors[ALLY])


def test_noon_concealed_enemy_gains_an_overkindled_mark(tmp_path):
    # "enemies that start their turn Hidden, Invisible, heavily obscured, or under an illusion
    # gain one Overkindled Mark." The same turn_start_choice checkpoint is proven in the ally
    # test; this one sets the Hidden condition directly because no table action sets a condition.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 8}, FOE: {"x": 5, "y": 6}})
    _cast_noon(table, combat, mid, (3, 6))
    from combat import ext, stealth

    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, stealth.HIDDEN, "test:hidden", FOE, expires_on="UNTIL_REMOVED")
    ext.run_strict("turn_start_choice", engine, foe)
    assert _overkindled_ids(foe)


def test_noon_twenty_feet_of_movement_emits_dim_light(tmp_path):
    # "when any creature in the area moves at least 20 feet during its turn, it emits dim light
    # until the start of its next turn."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    settle(table, mid, _move_candidate(combat, mid, (2, 6)).candidate_id)
    settle(table, mid, _move_candidate(combat, mid, (4, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == DIM_LIGHT for c in engine.state.actors[ALLY].conditions.values())


def test_noon_spent_rising_mark_gives_complete_aim_its_maximum_die(tmp_path):
    # "when you spend a Rising Mark in the area, increase one die rolled by the response to its
    # maximum result." CL 15 -> Complete Aim's die is 1d6, so the recorded die is 6.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"], cl=15,
                                 owner_kit={"starting_kit": DAGGER},
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 8}, FOE: {"x": 4, "y": 6}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, "Bi Shou (Dagger) attack", target=FOE).candidate_id,
            picks={"choice:needle.yang_aim_attack": "use"})
    engine = reload(tmp_path, mid)
    aim = next(r for r in engine.events
               if r.event_type == "CHECK_ROLLED" and str(r.source_definition_id).endswith("#complete_aim"))
    assert aim.payload["dice"] == [6] and aim.payload["total"] == 6
