"""Typed data vs printed rules text: the AUDIT1 confirmed rows (fix/audit1-data, MMX3).

The fight audit (AUDIT1, 2026-09-29) compared every printed record in
``authority/typed_mechanics/rules_text.json`` against the typed record and confirmed eighteen rows where the
table did something the sheet did not say. Twelve are corrected here; each fix is a row of existing typed
data, not new behaviour, so the tests below read the built authority and the action the compiler produces.

The rows, and what each printed sentence says that the typing had lost:

* Seven conditional ranges ("Touch, or 30/60 feet if ...") were typed as a bare ``touch`` (5 feet), which
  quietly deleted the longer reach. A range whose second half depends on a condition is carried as
  ``special`` text -- the shape ``factory_authoring.typed_mechanics._range`` produces for "Melee reach or 60
  feet", and the shape TAL_DEATH_WITHERING_HAND already uses.
* Ninefold Adamant Body's Reaction counterstrike printed "your Proficiency Bonus + your Metal key ability
  modifier" and was typed ``pb`` alone, so the modifier never rolled. This is a **data** correction only: the
  counterstrike itself is a deferred Reaction that no plug-in implements, so nothing here claims the table has
  started adding the modifier.
* Iron-Bone Internal Method's Temporary HP printed "twice your Proficiency Bonus + your Metal key ability
  modifier"; the pair ``double_pb`` + ``key_ability_modifier`` is the typed sum used elsewhere (gu.json's
  Digestive Mantle), and ``_fold_temp_hp`` adds a multi-term grant instead of keeping the largest term.
* Province Road Scripture's road "lasts for 24 hours" and was typed ``instant``, disagreeing with its own
  one-minute combat zone.
* Empty-Lung Edict and Steal Ongoing Technique print "Use Limit: Once per long rest per target/creature" and were
  typed ``null``. combat/ext/target_limits.py already implements the per-creature ledger for **actions**: it
  widens the ability's use counter to 99 and keeps the real limit as a per-creature list on the actor.
* Borrowed Lifespan Talisman prints the same per-creature limit but is a **Reaction**, and its limit is already
  enforced per creature by combat/ext/fate_riders.py. It deliberately keeps ``use_limit: null``: a generic counter
  there is once per fight for *every* creature, and its plug-in already does the printed thing better. The tests
  below pin that decision so a later review does not re-add it.

Rows AUDIT1 could not fix in data (a computed save DC, and a CL-scaled damage reduction) are listed in the
lane report as needing engine support and are not asserted here.
"""

import json
from functools import lru_cache
from pathlib import Path

import pytest

from combat.ext import fate_riders, target_limits
from combat.factory_compiler import TYPED_AUTHORITY, _target_kind, compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.typed_amounts import text_formula
from combat.typed_reactions import _ally_row_ok
from tests.h1_support import ROOT, sheet
from tests.test_zones import SHEET

APP = Path(__file__).resolve().parents[1]
RULES_TEXT = APP / "authority/typed_mechanics/rules_text.json"

OWNER = "actor:factory.audit1_owner"
ALLY_A = "actor:factory.audit1_ally_a"
ALLY_B = "actor:factory.audit1_ally_b"
FOE_A = "actor:factory.audit1_foe_a"
FOE_B = "actor:factory.audit1_foe_b"
WEAKER = "actor:factory.audit1_weak"


@lru_cache(maxsize=1)
def _mechanics() -> dict:
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


@lru_cache(maxsize=1)
def _printed() -> dict:
    return json.loads(RULES_TEXT.read_bytes())


def _bundle(mechanic_id: str, actor_id: str = OWNER, cl: int = 15, *, talents=None) -> dict:
    return compile_character(sheet(talents if talents is not None else [mechanic_id], cl=cl), actor_id=actor_id)


def _compiled_action(bundle: dict, mechanic_id: str) -> dict:
    return next(a for a in bundle["action_catalog"] if mechanic_id in a["source_definition_id"])


def _compiled_reaction(bundle: dict, mechanic_id: str) -> dict:
    return next(r for r in bundle["typed_reactions"] if r["feature_id"] == mechanic_id)


def _engine(owner_talents, roster, *, seed, cl=15) -> Gate4ControllerEngine:
    """A real engine whose owner holds ``owner_talents`` (may be empty) beside the ``roster``.

    ``roster`` maps each extra actor id to (team, (x, y)); the owner always leads team:a. Every extra actor is a
    talent-less sheet, so nothing but the owner's own rows is in play.
    """
    ids = [OWNER, *roster]
    teams = {OWNER: "team:a", **{aid: team for aid, (team, _at) in roster.items()}}
    positions = {OWNER: {"x": 3, "y": 6}, **{aid: {"x": at[0], "y": at[1]} for aid, (_team, at) in roster.items()}}
    bundles = [compile_character(sheet(list(owner_talents), cl=cl), actor_id=OWNER),
               *(compile_character(sheet([], cl=cl), actor_id=aid) for aid in roster)]
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams,
                                                 "starting_positions": positions})
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    return engine


def _two_foe_engine(mechanic_id: str, seed: str = "AUDIT1-TARGETS"):
    """The owner and two foes on the same grid."""
    return _engine([mechanic_id], {FOE_A: ("team:b", (5, 6)), FOE_B: ("team:b", (5, 7))}, seed=seed), \
        _compiled_action(_bundle(mechanic_id), mechanic_id)["display_name"]


def _next_owner_turn(engine) -> None:
    """Start the owner's next turn, so a spent Action economy is fresh again."""
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()


def _use_candidate(engine, candidate_id):
    from combat.gate2_runtime_models import ActionIntent

    candidate = next(c for c in engine.legal_candidates() if c.candidate_id == candidate_id)
    engine.execute_intent(ActionIntent(intent_id=candidate.display_name, decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=OWNER, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _borrowed_engine(seed: str = "AUDIT1-BORROWED") -> Gate4ControllerEngine:
    """The Fate owner, two willing allies it can keep alive, and the foe hurting them."""
    return _engine([BORROWED], {ALLY_A: ("team:a", (4, 6)), ALLY_B: ("team:a", (4, 7)),
                                FOE_A: ("team:b", (8, 6))}, seed=seed)


def _borrowed_ok(engine, subject_id: str) -> bool:
    """The production gate for an ally Reaction row: the real _ally_row_ok, which runs the ext hooks
    (fate_riders.borrowed_once_each) the printed per-creature limit lives in.

    The subject is one of the reactor's *allies* -- the talent keeps a creature the reactor is protecting, so an
    opponent is refused by the team check long before the printed limit is consulted.
    """
    reactor = engine.state.actors[OWNER]
    row = _compiled_reaction(_bundle(BORROWED), BORROWED)
    return bool(_ally_row_ok(engine, reactor, engine.state.actors[FOE_A], engine.state.actors[subject_id], row))


# ------------------------------------------------------------------ conditional range (AUDIT1 #3-#9)
CONDITIONAL_RANGES = {
    "DISEASE_BASE_DIAGNOSE_THE_SICKNESS": "Touch, or 30 feet if you can clearly perceive the target",
    "POISON_BASE_APPRAISE_THE_VENOM": "Touch, or 30 feet if you can clearly perceive the target",
    "TAL_EARTH_EARTHEN_HANDHOLD": "Touch, or 30 feet if Projected Earth is legal for you",
    "TAL_EARTH_HUMBLE_WALL": "Touch, or 30 feet if Projected Earth is legal for you",
    "TAL_EARTH_STONE_LUNG_SHELTER": "Touch, or 30 feet if Projected Earth is legal for you",
    "TAL_EARTH_RAISE_THE_LOAD_BEARING_WALL": "Touch, or 60 feet if Projected Earth is legal for you",
    "TAL_EARTH_TERRACED_ASCENT": "Touch, or 60 feet if Projected Earth is legal for you",
}


@pytest.mark.parametrize("mechanic_id, printed_range", sorted(CONDITIONAL_RANGES.items()))
def test_conditional_range_keeps_its_touch_arm_and_the_printed_sentence(mechanic_id, printed_range):
    """'Range: Touch, or 30/60 feet if ...' typed as a bare touch/5 left the record saying the ability is
    touch-only: the longer reach the sheet promised was nowhere in the data. The record now carries the
    printed sentence next to the touch arm it always has, the shape TAL_THREAD_MERIDIAN_STITCH already uses
    (a numeric kind plus the printed reach in "text")."""
    mechanics, printed = _mechanics(), _printed()
    assert printed_range in printed[mechanic_id], "the printed text changed; re-check this row"
    reach = mechanics[mechanic_id]["range"]
    assert reach["kind"] == "touch" and reach["feet"] == 5, f"{mechanic_id} range is {reach}"
    assert reach["text"] == printed_range


def test_a_conditional_range_still_targets_what_its_printed_target_line_names():
    """A bare 'special' range has no distance, so combat/factory_compiler.py::_target_kind fell back to
    ("SELF", None) and these abilities stopped being aimed at a creature -- Appraise the Venom's printed
    target is "One creature, corpse, object, ...". Carrying the printed sentence beside the touch arm keeps
    the compiled targeting exactly as it was."""
    mechanics = _mechanics()
    for mechanic_id in CONDITIONAL_RANGES:
        reach = mechanics[mechanic_id]["range"]
        assert reach["kind"] in ("touch", "feet", "reach"), f"{mechanic_id} range is {reach}"
        assert reach["feet"] == 5, f"{mechanic_id} claims {reach['feet']} feet outright"
    for mechanic_id in ("DISEASE_BASE_DIAGNOSE_THE_SICKNESS", "POISON_BASE_APPRAISE_THE_VENOM"):
        row = mechanics[mechanic_id]
        target_kind, reach_ft = _target_kind(row, 10)
        assert (target_kind, reach_ft) == ("ALLY_OR_SELF", 5), (mechanic_id, target_kind, reach_ft)


# ------------------------------------------------------------------ key ability modifier (AUDIT1 #10)
def test_ninefold_adamant_body_counterstrike_names_the_key_ability_modifier():
    """"deal Piercing damage equal to your Proficiency Bonus + your Metal key ability modifier" was typed
    "pb": the key ability modifier was never added, so the counterstrike rolled short by up to 5.

    Scope, stated honestly: this is a **data** correction. The record carries the printed sum, and the record is
    what the compiler reads, but Ninefold's counterstrike is a deferred Reaction that no code in ``combat/ext/``
    or the feature-block rules implements (combat/typed_executor.py:3212 registers deferred *extra-damage* and
    watch effects, not this deferred ``damage`` row). So this test proves the record, not that the table has
    started adding the modifier -- the missing reaction is inherited work, not this lane's, and the lane report
    no longer claims otherwise. A counterstrike that fires is a separate lane to write."""
    row = _mechanics()["TAL_METAL_NINEFOLD_ADAMANT_BODY"]["effects"][2]
    assert row["type"] == "damage" and row["applies_to"] == "attacker"
    assert "key ability modifier" in row["evidence"]
    assert row["formula"] == "text:your Proficiency Bonus + your key ability modifier"
    value, rest = text_formula(row["formula"].removeprefix("text:"), {"pb": 3, "cl": 5, "key_mod": 4})
    assert (value, rest) == (7, "")  # 3 + 4, the printed sum


# ------------------------------------------------------------------ temporary HP sum (AUDIT1 #11)
def test_iron_bone_internal_method_grants_the_printed_temporary_hp_in_a_fight():
    """"Temporary HP equal to twice your Proficiency Bonus + your Metal key ability modifier" was one row
    holding the printed prose. The typed pair is double_pb plus the key ability modifier (the shape gu.json's
    Digestive Mantle uses), which _fold_temp_hp adds into one grant instead of keeping a single term.

    This runs the ability: the old test only asserted the record's fields and then computed the printed sum
    itself, so an executor that ignored the row would have passed it."""
    row = _mechanics()["TAL_METAL_IRON_BONE_INTERNAL_METHOD"]["options"][0]["effects"][0]["effects"][0]
    assert row["type"] == "temp_hp"
    assert row["formula"] == "double_pb"
    assert row["dice"]["bonus_formula"] == "key_ability_modifier"

    # and the grant actually happens in an engine, at the printed 2 x PB + key modifier.
    engine = _engine(["TAL_METAL_IRON_BONE_INTERNAL_METHOD"], {FOE_A: ("team:b", (5, 6))}, seed="AUDIT1-IRONBONE")
    owner = engine.state.actors[OWNER]
    label = "Iron-Bone Internal Method: Temporary HP"
    candidates = [c for c in engine.legal_candidates() if c.display_name == label]
    assert candidates, "Iron-Bone's Temporary HP option compiled to nothing"
    _use_candidate(engine, candidates[0].candidate_id)
    typed = _compiled_action(_bundle("TAL_METAL_IRON_BONE_INTERNAL_METHOD"), "TAL_METAL_IRON_BONE_INTERNAL_METHOD")
    pb = typed["parameters"]["typed"]["numbers"]["pb"]
    key_mod = typed["parameters"]["typed"]["numbers"]["key_mod"]
    expected = 2 * pb + key_mod
    assert owner.temporary_hp == expected, f"granted {owner.temporary_hp}, printed sum is {expected} (2*{pb}+{key_mod})"


# ------------------------------------------------------------------ duration (AUDIT1 #15)
def test_province_road_scripture_road_lasts_24_hours():
    """"the path may cover ... and lasts for 24 hours" was typed "instant" at the record level, which also
    disagreed with the zone's own one minute. The record now names the printed 24 hours, a duration kind the
    engine keeps (combat/typed_executor.py duration_expiry: hours last the fight, which is true of 24)."""
    row = _mechanics()["TAL_EARTH_PROVINCE_ROAD_SCRIPTURE"]
    # the authority now anchors every duration (duration_anchors.json); compare the lifetime, not the anchor key
    from combat.ext.effect_durations import kind_of
    assert {k: v for k, v in row["duration"].items() if k != "anchor"} == {"kind": "hours", "amount": 24, "concentration": False}
    assert kind_of(row["duration"]) == "hours"
    # the combat road's own printed "For 1 minute" stays on the zone effect
    assert row["effects"][0]["type"] == "zone"
    assert kind_of(row["effects"][0]["duration"]) == "one_minute"


# ------------------------------------------------------------------ use limits (AUDIT1 #16-#18)
# The two rows whose printed limit is enforced by combat/ext/target_limits.py's per-creature ledger. Both are
# *actions*, which is what that plug-in's counter machinery is built for.
ACTION_USE_LIMITS = {
    "TAL_AIR_EMPTY_LUNG_EDICT": "text:once per target per long rest",
    "TAL_SCOUNDREL_STEAL_ONGOING_TECHNIQUE": "text:once per creature per long rest",
}
BORROWED = "TAL_FATE_BORROWED_LIFESPAN_TALISMAN"
FOCUS = "resource:core.martial_focus"


def _give(actor, resource_id: str, amount: int) -> None:
    """Put ``amount`` of a resource back, maximum included (spending a use takes both down)."""
    actor.resource_maximums[resource_id] = max(amount, actor.resource_maximums.get(resource_id, 0))
    actor.resources[resource_id] = amount


def _ward_by_its_own_side(engine, foe_id: str) -> None:
    """Give ``foe_id`` a standing Armour Class bonus that its *own* side put on it.

    Steal Ongoing Technique's printed target is "One creature benefiting from a non-Secret ongoing effect", and
    combat/ext/end_effect.py::_sources_ok counts an effect as a benefit only when its source is on the holder's own
    team -- so the modifier is filed under the foe itself, which is the same fixture
    tests/test_sys_resources_states.py builds for that ability. A bare foe is benefiting from nothing, so the printed
    target has to be made legal here rather than assumed.
    """
    engine.state.current_actor_id = foe_id
    engine._add_modifier(engine.state.actors[foe_id], "action:test.foe_ward", "armor_class", "ADD", 3, "ALWAYS",
                         expires_on="UNTIL_REMOVED")
    engine.state.current_actor_id = OWNER


def _lowest_rolls(engine) -> None:
    """Every d20 the engine rolls from now on comes up 1, so the Scoundrel Check misses.

    Missing is the honest fixture for a *limit* test. combat/ext/target_limits.py spends the use "hit or miss", so
    creature A is recorded as used while it **keeps** its ward -- which keeps A a legal target for this ability's own
    printed target line, so the limit is the only thing standing between A and a second offer. A successful theft
    would instead empty A's ward (removing the printed target for a reason that has nothing to do with the limit) and
    leave the thief holding the one stolen technique it may maintain at a time, which would deny B as well.
    """
    from combat.gate2_runtime_models import RollRecord

    count = [0]

    def d20(**kw):
        count[0] += 1
        return RollRecord(roll_id=f"fixed-{count[0]}", counter_start=count[0], counter_end=count[0] + 1,
                          expression=f"1d20{kw['modifier']:+d}", actor_id=kw["actor_id"], reason=kw["reason"],
                          dice=(1,), modifier=kw["modifier"], total=1 + kw["modifier"], natural_result=1)

    engine.roller.d20 = d20


def _engine_action(engine, mechanic_id: str):
    """The one compiled action the engine's own catalog holds for ``mechanic_id``."""
    actions = [a for a in engine.action_catalog.values() if mechanic_id in a.source_definition_id]
    assert len(actions) == 1, f"{mechanic_id} compiled {len(actions)} actions; expected exactly one"
    return actions[0]


def _per_target_counter(engine, mechanic_id: str) -> str:
    """The use counter the engine charges for ``mechanic_id``.

    Its id embeds a per-bundle hash, so it is read from the engine's own compiled action rather than written out --
    a hardcoded id silently fails to match and would make the ledger assertions below vacuous.
    """
    counters = [resource for resource, _amount in _engine_action(engine, mechanic_id).costs
                if resource.startswith(target_limits.USES)]
    assert len(counters) == 1, \
        (f"{mechanic_id} compiled {counters} use counters, expected exactly one; the printed per-creature limit is "
         "carried by that counter, and a row with none was typed as unlimited")
    return counters[0]


def _prepare_two_creature_fixture(engine, mechanic_id: str) -> None:
    """Make the printed target of ``mechanic_id`` legal against **both** foes.

    Empty-Lung Edict's printed target is "One breath-dependent creature", which two talent-less foes satisfy as they
    stand. Steal Ongoing Technique's is "One creature benefiting from a non-Secret ongoing effect", so each foe is
    given a benefit of its own side and the thief its printed Martial Focus cost.
    """
    if mechanic_id == "TAL_SCOUNDREL_STEAL_ONGOING_TECHNIQUE":
        for foe_id in (FOE_A, FOE_B):
            _ward_by_its_own_side(engine, foe_id)
        _give(engine.state.actors[OWNER], FOCUS, 1)
        _lowest_rolls(engine)


@pytest.mark.parametrize("mechanic_id, use_limit", sorted(ACTION_USE_LIMITS.items()))
def test_printed_per_creature_use_limit_is_typed_and_read_as_per_creature(mechanic_id, use_limit):
    """"Use Limit: Once per long rest per target/creature" typed as null let the ability be used again in the
    same fight. combat/ext/target_limits.py already gates such a limit per creature.

    The gate reads the limit in whichever of the two printed word orders the record carries: the record may say
    "once per target per long rest" (the normalized order) or the printed "once per long rest per target". Both
    are the same printed limit and both are read (mmx45 2026-10-02: the detector accepted only the first, so a
    record carrying the printed order fell back to one use for the whole fight -- hunt 76 finding 1)."""
    mechanics, printed = _mechanics(), _printed()
    row = mechanics[mechanic_id]
    assert row["use_limit"] == use_limit, f"{mechanic_id} use_limit is {row['use_limit']}"
    assert "Once per long rest" in printed[mechanic_id] or "Once per Long Rest" in printed[mechanic_id]
    assert target_limits.per_target_limit(row), "the per-creature gate does not read this limit"
    # both printed word orders name the same limit, and the gate reads both
    assert target_limits.PER_TARGET.search("once per long rest per creature")
    assert target_limits.PER_TARGET.search("once per creature per long rest")
    # a limit that names no creature is still the whole ability's one use
    assert not target_limits.PER_TARGET.search("once per long rest")


@pytest.mark.parametrize("mechanic_id", sorted(ACTION_USE_LIMITS))
def test_an_action_per_creature_limit_compiles_to_a_counter_that_never_runs_out(mechanic_id):
    """The per-creature ledger works by widening the ability's use counter to PER_TARGET_USES, so the count itself
    never stops a use and the real limit is the per-creature list kept on the actor. Read at the level the bug
    showed: the compiled action's own cost list, not the record's string."""
    bundle = _bundle(mechanic_id)
    counters = {r["resource_id"]: r for r in bundle["actor_template"]["resources"]
                if r["resource_id"].startswith(target_limits.USES) and mechanic_id in r["resource_id"]}
    assert len(counters) == 1, f"{mechanic_id} compiled use counters {sorted(counters)}"
    counter = next(iter(counters.values()))
    assert counter["initial"] == counter["maximum"] == target_limits.PER_TARGET_USES, counter
    action = _compiled_action(bundle, mechanic_id)
    charged = {resource for resource, _amount in action["costs"]}
    assert set(counters) <= charged, f"{mechanic_id} compiled a counter it never charges: {action['costs']}"


@pytest.mark.parametrize("mechanic_id", sorted(ACTION_USE_LIMITS))
def test_a_second_different_creature_is_still_offered_the_per_creature_edicts(mechanic_id):
    """The whole point of the printed "per target/creature" limit: the same edict may be met against a *second*
    creature, only not a second time against the first. One fight with two foes covers it -- the first use records
    creature A, and B must still be offered on the owner's next turn.

    Nothing here skips. Both rows are held to the same behaviour, and the fixture builds the printed target for each
    (see ``_prepare_two_creature_fixture``), so an ability that stops compiling, or stops finding a legal creature to
    aim at, fails these assertions instead of quietly passing.

    The last pair asks ``target_limits`` itself for its verdict, and that is deliberate. Both abilities are *also*
    refused a second time by some other plug-in -- Empty-Lung Edict by its own ``once_per_caster`` mark
    (combat/ext/once_per_creature.py) and Steal Ongoing Technique by the thief's ``_round_stolen_from`` record
    (combat/ext/effect_transfer.py, which records the creature before it rolls the Scoundrel Check). So a table-level
    "A is gone" assertion on its own cannot tell the printed limit from those, and stays green if the per-creature
    limit this lane feeds stops working. Asking the limit directly is what makes this a regression test for the
    typed ``use_limit`` rather than for whichever rule happens to deny A.
    """
    engine, label = _two_foe_engine(mechanic_id)
    _prepare_two_creature_fixture(engine, mechanic_id)
    candidates = {c.target_ids: c for c in engine.legal_candidates() if c.display_name == label}
    assert (FOE_A,) in candidates, f"{mechanic_id} was not offered against the first foe; offered {sorted(candidates)}"
    assert (FOE_B,) in candidates, f"{mechanic_id} was not offered against the second foe; offered {sorted(candidates)}"

    _use_candidate(engine, candidates[(FOE_A,)].candidate_id)

    # The use is recorded against the creature it was actually used on, and only against that one.
    owner = engine.state.actors[OWNER]
    counter = _per_target_counter(engine, mechanic_id)
    assert target_limits.used_on(owner, counter, FOE_A), \
        f"{mechanic_id} did not record its use against the creature it was actually used on"
    assert not target_limits.used_on(owner, counter, FOE_B), \
        f"{mechanic_id} recorded a use against a creature it was never used on"

    # Restore what the printed use itself spends, so the next refusal is the limit's and not the economy's.
    _give(owner, FOCUS, 1)  # "Cost: Expend Martial Focus"
    _next_owner_turn(engine)  # an Action is spent for the turn, so the second use needs a fresh one

    again = {c.target_ids: c for c in engine.legal_candidates() if c.display_name == label}
    assert (FOE_A,) not in again, f"{mechanic_id} was offered again against the creature it was already used on"
    assert (FOE_B,) in again, \
        f"{mechanic_id} stopped being offered against a second, different creature; offered {sorted(again)}"

    # and the printed limit is what refuses A, and what still allows B
    action = _engine_action(engine, mechanic_id)
    assert target_limits.not_twice_on_one_creature(engine, owner, candidates[(FOE_A,)], action) is False, \
        f"the printed per-creature limit no longer refuses a second use against {FOE_A}"
    assert target_limits.not_twice_on_one_creature(engine, owner, again[(FOE_B,)], action) is not False, \
        f"the printed per-creature limit refuses a *first* use against a different creature ({FOE_B})"


def test_borrowed_lifespan_saves_a_second_different_creature():
    """Borrowed Lifespan Talisman prints "Use Limit: Once per Long Rest per creature" -- per *target* creature, so
    keeping a second, different creature at 1 HP has to stay possible.

    Typing that limit as a generic ``use_limit`` gave the compiled Reaction a
    ``resource:uses.reaction:typed.TAL_FATE_BORROWED_LIFESPAN_TALISMAN`` cost of 1. target_limits' per-creature
    ledger only widens *action* counters (its ``mechanic_key`` reads ``action:typed.``), so the counter was never
    widened: the first save exhausted it and ``_generic_affordable`` refused the second, whatever the CP and the
    Reaction. The printed limit is already enforced per creature by combat/ext/fate_riders.py, so the record must
    carry no fight-wide counter at all."""
    bundle = _bundle(BORROWED)
    row = _compiled_reaction(bundle, BORROWED)
    assert not [c for c in row["costs"] if c["resource_id"].startswith(target_limits.USES)], \
        f"Borrowed Lifespan carries a fight-wide use counter: {row['costs']}"

    engine = _borrowed_engine()
    reactor = engine.state.actors[OWNER]
    first, second = ALLY_A, ALLY_B
    assert _borrowed_ok(engine, first), "the printed limit must not stop the first save"
    # Spend the one printed use on A, exactly as the Fate plug-in records it.
    fate_riders._borrowed_cost(engine, OWNER, [first])
    assert reactor.turn_flags[fate_riders._borrowed_key(engine.state.actors[first])] == 1
    assert not _borrowed_ok(engine, first), "A was already saved; the printed per-creature limit must deny it"
    assert _borrowed_ok(engine, second), \
        "a second, different creature must still be saveable -- the bug was a fight-wide counter"


def test_borrowed_lifespan_per_creature_ledger_survives_a_persistence_clone():
    """Checklist: what the printed limit stores in fight state must come back through the engine's own persistence
    round trip (``CombatService._clone_engine``), and the per-creature keys must still distinguish A from B.

    The full table path -- a real drop, the real Reaction, a real commit, and a fresh service reading it back off
    disk -- is already covered for this talent by ``tests/test_r9i_fate_persistence.py``; what is pinned here is
    that the ledger this lane depends on is keyed per creature, and stores only a string key and an int."""
    from tests.test_riders_lane9 import ALLY as LANE9_ALLY, ME, THEM, _fate_fight, _stab

    engine = _fate_fight(["BORROWED_LIFESPAN_TALISMAN"], them_at=(4, 7))
    ally = engine.state.actors[LANE9_ALLY]
    ally.armor_class, ally.current_hp = -50, 1
    _stab(engine, target=LANE9_ALLY)  # the drop the talent answers, through the real damage path
    # the real reaction already recorded the use against that creature
    assert engine.state.actors[ME].turn_flags.get(fate_riders._borrowed_key(ally)) == 1, \
        "the drop did not record the printed use"

    clone = CombatService._clone_engine(ROOT, engine)
    caster, protected, other = (clone.state.actors[aid] for aid in (ME, LANE9_ALLY, THEM))
    assert caster.turn_flags.get(fate_riders._borrowed_key(protected)) == 1, "the per-creature key did not survive"
    assert fate_riders.borrowed_once_each(clone, caster, protected, {"feature_id": BORROWED}) is False, \
        "A was already saved; the printed per-creature limit must still deny it after the round trip"
    assert fate_riders.borrowed_once_each(clone, caster, other, {"feature_id": BORROWED}) is True, \
        "a second, different creature must still be saveable"


def test_an_ability_without_a_printed_per_creature_limit_is_still_fight_limited_once():
    """The rows above gained a use counter. A row with no per-creature limit must keep the plain
    once-per-fight reading, so target_limits' regex stays narrow."""
    mechanics = _mechanics()
    assert not target_limits.per_target_limit(mechanics["TAL_EARTH_PROVINCE_ROAD_SCRIPTURE"])
    plain = _bundle("TAL_EARTH_PROVINCE_ROAD_SCRIPTURE")
    assert not [r for r in plain["actor_template"]["resources"]
                if r["resource_id"].startswith(target_limits.USES)], "an unlimited-per-creature row grew a counter"


def test_borrowed_lifespan_keeps_no_typed_use_limit():
    """The record stays null on purpose: the printed limit is the Fate plug-in's, and a generic counter is a
    different (wrong) limit. This pins the decision so a later review does not re-add it."""
    row = _mechanics()[BORROWED]
    assert row.get("use_limit") is None, f"{BORROWED} use_limit is {row.get('use_limit')!r}"
    assert "Once per Long Rest per creature" in _printed()[BORROWED]
    assert not target_limits.per_target_limit(row)


# ------------------------------------------------------------------ area count (AUDIT1 #14)
def test_buried_trace_area_carries_the_printed_number_of_spaces():
    """"erase or preserve tracks across a number of 5-foot spaces equal to your Proficiency Bonus + your Earth
    key ability modifier" survived only as a rider, with no area at all. The area now carries the printed
    count; the space count itself is still the GM's (no typed count-by-formula on an area)."""
    row = _mechanics()["TAL_EARTH_BURIED_TRACE"]
    assert row["area"] == {
        "shape": "special",
        "size_ft": None,
        "text": "a number of 5-foot spaces equal to your Proficiency Bonus + your Earth key ability modifier",
    }


# ------------------------------------------------------------------ the compiler reads the fixed rows
def test_the_compiled_terraced_ascent_keeps_its_printed_range_text():
    """The compiler builds the action the table offers. Terraced Ascent's longer range is a printed
    condition, so the compiled action must still name the reach the sheet promised rather than claim plain
    touch."""
    stats = {**SHEET["ability_scores_and_statistics"], "technique_save_dc": 10}
    compiled = compile_character(
        {**SHEET, "equipment": [],
         "ability_scores_and_statistics": stats,
         "spheres_and_talents": {"sphere_record_ids": ["tianxia.sphere.earth"],
                                 "learned_talent_record_ids": ["TAL_EARTH_TERRACED_ASCENT"]}},
        actor_id="actor:factory.audit1_data")
    catalog = compiled.get("action_catalog") or []
    actions = [a for a in catalog if "TAL_EARTH_TERRACED_ASCENT" in json.dumps(a)]
    assert actions, f"Terraced Ascent compiled no action (catalog holds {len(catalog)} actions)"
    # the compiled action names the printed range, so the sheet and the table agree
    assert CONDITIONAL_RANGES["TAL_EARTH_TERRACED_ASCENT"] in json.dumps(actions)
