"""Per-creature use limits, the one model every "per creature / per target" record uses (hunt 76, findings 1-2).

Two printed limits were being compiled as one use for the whole fight, so the button died after the first target:

* ``TAL_YANG_KINDLE_THE_WOUNDED_BREATH`` prints **"Use Limit: Once per Short Rest per creature"** and was typed
  ``once_per_short_rest``, which is the whole-ability limit -- after one Kindling the talent was gone for the
  fight, against every other creature too (hunt 76 finding 1, live evidence: Hao Bing's counter read 1/1).
* ``TAL_AIR_EMPTY_LUNG_EDICT`` prints **"Use Limit: Once per long rest per target"** and was typed ``null``, so
  nothing gated it at all (hunt 76 finding 2).

The machinery already existed and was already the right shape: ``combat/ext/target_limits.py`` widens a per-target
ability's use counter so the count never runs out, and keeps the real limit as a list of the creatures it has been
used on, so a second *different* creature is still offered the ability and only the one it was used on is refused.
What was missing was that the printed rules name the creature **in two different word orders**, and that the
records which print the reversed order were typed as a bare ``once_per_*rest`` key with the per-creature half
dropped. This lane types the records and widens the one detector that reads them; it adds no second model.

The tests below run the table (``legal_candidates`` / ``TabletopService``) rather than a unit call, because the bug
was visible in the list of choices a player is offered. ``_offered`` is what the fighter sees.
"""

import json
import re
from pathlib import Path

import pytest

from combat.ext import target_limits
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet, script
from tests.hunt23_support import ALLY, LEFT, act, fight, reload, turn

APP = Path(__file__).resolve().parents[1]
RULES_TEXT = APP / "authority" / "typed_mechanics" / "rules_text.json"
TYPED_AUTHORITY = APP / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json"

OWNER = "actor:h76.owner"
ALLY_A = "actor:h76.ally_a"
ALLY_B = "actor:h76.ally_b"
FOE_A = "actor:h76.foe_a"
FOE_B = "actor:h76.foe_b"

KINDLE = "TAL_YANG_KINDLE_THE_WOUNDED_BREATH"          # "Once per Short Rest per creature"  (hunt 76 finding 1)
EDICT = "TAL_AIR_EMPTY_LUNG_EDICT"                     # "Once per long rest per target"     (hunt 76 finding 2)
GATE_STRIKE = "TAL_IRON_FIST_QUIVERING_GATE_STRIKE"    # "Once per creature per long rest"   (a different recharge)


@pytest.fixture(scope="module")
def printed() -> dict:
    return json.loads(RULES_TEXT.read_bytes())


@pytest.fixture(scope="module")
def typed() -> dict:
    return json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]


def _label(mechanic_id: str) -> str:
    bundle = compile_character(sheet([mechanic_id], cl=15), actor_id=OWNER)
    return next(a["display_name"] for a in bundle["action_catalog"] if mechanic_id in a["source_definition_id"])


def _fight(mids, allies=(), foes=(), *, seed: str) -> Gate4ControllerEngine:
    """A real fight: one character owning ``mids``, plus the allies and foes those abilities can be aimed at.

    ``allies`` stand on the user's own side (a printed ally-or-self target), ``foes`` across from it (a printed
    hostile target), so one fight can hold a Short-Rest ability aimed at an ally and a Long-Rest one at a foe."""
    mids = [mids] if isinstance(mids, str) else list(mids)
    ids = [OWNER, *allies, *foes]
    teams = {OWNER: "team:a", **{aid: "team:a" for aid in allies}, **{aid: "team:b" for aid in foes}}
    places = {OWNER: {"x": 3, "y": 6}, **{aid: {"x": 3, "y": 7 + i} for i, aid in enumerate(allies)},
              **{aid: {"x": 4, "y": 6 + i} for i, aid in enumerate(foes)}}
    bundles = (compile_character(sheet(mids, cl=15), actor_id=OWNER),
               *(compile_character(sheet([], cl=15), actor_id=aid) for aid in allies),
               *(compile_character(sheet([], cl=15), actor_id=aid) for aid in foes))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": ids, "team_by_actor": teams,
                                                 "starting_positions": places})
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()
    return engine


def _offered(engine: Gate4ControllerEngine, label: str) -> set:
    """The creatures the owner is actually offered this ability against, right now."""
    return {target for c in engine.legal_candidates() if c.display_name == label for target in c.target_ids or ()}


def _use(engine: Gate4ControllerEngine, label: str, target: str) -> None:
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == label and target in (c.target_ids or ()))
    engine.execute_intent(ActionIntent(intent_id=f"h76-{label[:8]}-{target}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=OWNER, target_ids=candidate.target_ids,
                                       destination=candidate.destination))


def _next_turn(engine: Gate4ControllerEngine) -> None:
    """A fresh turn for the owner, so a spent Action or Bonus Action is available again."""
    engine.state.current_slot_index = engine.state.initiative_order.index(OWNER)
    engine.state.current_actor_id = OWNER
    engine._system_start_turn()


def _ledger(engine: Gate4ControllerEngine):
    owner = engine.state.actors[OWNER]
    return [c for c in owner.conditions.values() if c.condition_id == target_limits.condition_id()]


def _reason(engine: Gate4ControllerEngine) -> str:
    held = _ledger(engine)
    assert len(held) == 1, "the printed limit kept no record of the creature it was used on"
    return held[0].data["label"]


def _counter(engine: Gate4ControllerEngine, mechanic_id: str) -> str:
    owner = engine.state.actors[OWNER]
    return next(key for key in owner.resource_maximums
                if key.startswith(target_limits.USES) and key.endswith(mechanic_id))


# ------------------------------------------------------------------ hunt 76 finding 1: "Once per Short Rest per creature"
def test_a_once_per_short_rest_per_creature_talent_is_still_offered_against_a_second_creature(printed):
    """Kindle the Wounded Breath prints "Once per Short Rest per creature". Compiled as one use for the whole
    fight, the talent vanished after the first creature it touched, for good -- which is what hunt 76 caught in
    the live build, where Hao Bing's counter read 1/1 and the widening in target_limits never ran.

    The printed limit is per creature: after Kindling one creature, a *different* one must still be offered it."""
    assert "Once per Short Rest per creature" in printed[KINDLE], "the printed text changed; re-check this row"
    label = _label(KINDLE)
    engine = _fight(KINDLE, (ALLY_A, ALLY_B), seed="H76-KINDLE")
    assert {ALLY_A, ALLY_B} <= _offered(engine, label), "the talent was never offered against both creatures"

    _use(engine, label, ALLY_A)
    _next_turn(engine)  # a Bonus Action is spent for the turn, so the second use needs a fresh one

    offered = _offered(engine, label)
    assert ALLY_A not in offered, "the talent was offered again against the creature it was already used on"
    assert ALLY_B in offered, f"the talent stopped being offered against a second, different creature; offered {sorted(offered)}"


def test_the_once_per_short_rest_per_creature_counter_never_runs_out(printed):
    """The model works by widening the ability's use counter, so the count itself never stops a use and the real
    limit is the per-creature list. Read on the compiled actor, which is where the 1/1 came from."""
    assert "Once per Short Rest per creature" in printed[KINDLE]
    engine = _fight(KINDLE, (ALLY_A, ALLY_B), seed="H76-KINDLE-COUNTER")
    owner = engine.state.actors[OWNER]
    counter = _counter(engine, KINDLE)
    assert owner.resource_maximums[counter] == target_limits.PER_TARGET_USES, \
        f"{KINDLE} compiled a counter of {owner.resource_maximums[counter]}, not a per-creature one"
    assert target_limits.is_per_target(owner, counter)


# ------------------------------------------------------------------ hunt 76 finding 2: "Once per long rest per target"
def test_a_once_per_long_rest_per_target_edict_is_refused_on_the_same_creature_and_offered_again_on_another(printed):
    """Empty-Lung Edict prints "Once per long rest per target" and was typed ``null``, so it carried no use
    cost at all and nothing could ever run out (hunt 76 finding 2).

    Per target means one creature per use: the same breath-dependent creature is refused, a different one is not."""
    assert "Once per long rest per target" in printed[EDICT], "the printed text changed; re-check this row"
    label = _label(EDICT)
    engine = _fight(EDICT, foes=(FOE_A, FOE_B), seed="H76-EDICT")
    assert {FOE_A, FOE_B} <= _offered(engine, label), "the edict was never offered against both creatures"

    _use(engine, label, FOE_A)
    _next_turn(engine)  # an Action is spent for the turn, so the second use needs a fresh one

    offered = _offered(engine, label)
    assert FOE_A not in offered, "the edict was offered again against the creature it was already used on"
    assert FOE_B in offered, f"the edict stopped being offered against a second, different creature; offered {sorted(offered)}"


def test_a_saved_against_still_spends_the_per_creature_use_on_that_creature(printed):
    """The printed limit is spent when the use is made, hit or miss. Empty-Lung Edict is a **Constitution
    saving throw**, not an attack, so raising the target's armor class proves nothing about it: this scripts the
    die, forces the save to *succeed*, and asserts the successful-save outcome actually landed -- only then is the
    use accounting below saying something about a creature that got past the save."""
    assert "The target makes a Constitution saving throw." in printed[EDICT], "the printed text changed; re-check this row"
    label = _label(EDICT)
    engine = _fight(EDICT, foes=(FOE_A, FOE_B), seed="H76-EDICT-SAVE")
    script(engine, [20] * 8)  # a d20 of 20 always beats the printed save DC
    _use(engine, label, FOE_A)

    target_conditions = {c.condition_id for c in engine.state.actors[FOE_A].conditions.values()}
    assert "condition:typed.silenced" not in target_conditions, \
        "the save was expected to succeed, but the target was silenced: the scripted die did not take effect"
    assert "condition:typed.concentration_mode" in target_conditions, \
        f"the successful-save outcome never landed; conditions are {sorted(target_conditions)}"

    _next_turn(engine)
    offered = _offered(engine, label)
    assert FOE_A not in offered, "a use the creature saved against was not counted as used on it"
    assert FOE_B in offered, "a saved-against use cost the ability against every other creature"


# ------------------------------------------------------------------ using it on yourself counts
def test_using_a_per_creature_limit_on_yourself_counts_against_you(printed):
    """You are one of the creatures a "once per creature" limit is printed per. Kindle the Wounded Breath is an
    ally-or-self ability, so aiming it at yourself is an explicitly chosen recipient (combat/typed_executor.py
    keeps that target for exactly this reason) -- and before this lane the ledger skipped you, so the healing
    could be repeated on yourself for as long as you could pay for it."""
    assert "Once per Short Rest per creature" in printed[KINDLE]
    label = _label(KINDLE)
    engine = _fight(KINDLE, (ALLY_A, ALLY_B), seed="H76-SELF")
    assert OWNER in _offered(engine, label), "the talent was never offered against its own user"

    _use(engine, label, OWNER)
    assert target_limits.used_on(engine.state.actors[OWNER], _counter(engine, KINDLE), OWNER), \
        "the use on yourself was not recorded, so the printed limit does not count you as a target"
    assert engine.state.actors[OWNER].display_name in _reason(engine), \
        f"the reason does not name you as the creature it was used on: {_reason(engine)!r}"

    _next_turn(engine)
    offered = _offered(engine, label)
    assert OWNER not in offered, "the talent was offered against yourself again after being used on yourself"
    assert {ALLY_A, ALLY_B} <= offered, f"using it on yourself cost the talent against everyone else; offered {sorted(offered)}"


# ------------------------------------------------------------------ the reason the player is given
def test_the_refusal_reason_names_the_creature_the_ability_and_when_it_comes_back():
    """When a use is refused the player is shown a sentence, not a code name: which creature, which ability, and
    when it is available again. "a Short Rest" / "a Long Rest" are the printed words of the limit itself."""
    for mechanic_id, printed_limit, recharge in ((KINDLE, "Once per Short Rest per creature", "a Short Rest"),
                                                 (EDICT, "Once per long rest per target", "a Long Rest")):
        assert printed_limit in json.loads(RULES_TEXT.read_bytes())[mechanic_id]
        assert target_limits.recharge_label(printed_limit) == recharge
        assert target_limits.recharge_for(f"{target_limits.USES}action:typed.x.{mechanic_id}") == recharge

    label = _label(KINDLE)
    engine = _fight(KINDLE, (ALLY_A,), seed="H76-REASON")
    _use(engine, label, ALLY_A)

    reason = _reason(engine)
    assert engine.state.actors[ALLY_A].display_name in reason, f"the reason does not name the creature: {reason!r}"
    assert "comes back after a Short Rest" in reason, f"the reason does not say when it recharges: {reason!r}"
    assert label in reason, f"the reason does not name the ability: {reason!r}"
    for code_name in ("TAL_", "resource:uses", "target_uses", "condition:"):
        assert code_name not in reason, f"the reason leaks an internal code name ({code_name}): {reason!r}"


@pytest.mark.parametrize("order", ["short_first", "long_first"])
def test_each_recorded_ability_is_told_its_own_recharge(order, printed):
    """Two abilities with **different** printed limits, used on one character, each get their own rest in the
    text. A single shared recharge explained both by whichever came first, so a character who had used Soul
    Sunder and Kindle the Wounded Breath was told both come back after a Long Rest -- or both after a Short Rest,
    depending only on the order the uses happened in."""
    assert "Once per Short Rest per creature" in printed[KINDLE]
    assert "Once per creature per long rest" in printed[GATE_STRIKE]
    kindling, striking = _label(KINDLE), _label(GATE_STRIKE)
    short_use, long_use = (kindling, ALLY_A, "a Short Rest"), (striking, FOE_A, "a Long Rest")
    steps = (long_use, short_use) if order == "long_first" else (short_use, long_use)

    engine = _fight((KINDLE, GATE_STRIKE), (ALLY_A,), (FOE_A,), seed=f"H76-MIXED-{order}")
    for label, target, _recharge in steps:
        _use(engine, label, target)
        _next_turn(engine)

    reason = _reason(engine)
    for label, target, recharge in steps:
        sentence = next(part for part in reason.split("Already used on ") if label in part)
        assert engine.state.actors[target].display_name in sentence, f"{label}: no creature named in {sentence!r}"
        assert f"comes back after {recharge}." in sentence, \
            f"{label} is told the wrong recharge in {sentence!r} (the full reason is {reason!r})"
    # and the wrong pairing is what is gone: a Long Rest must not be claimed for the Short-Rest ability
    short_sentence = next(part for part in reason.split("Already used on ") if kindling in part)
    assert "Long Rest" not in short_sentence, f"the Short-Rest ability was described with a Long Rest: {short_sentence!r}"


def test_the_use_comes_back_when_the_printed_rest_clears_the_record():
    """A fight is shorter than a Short Rest, so within one fight the record is rightly kept (owner ruling
    2026-09-29). It is not permanent, though: the limit lives in the fight's own condition, so when the printed
    rest arrives and that record is dropped, the very same creature is offered the ability again. This is what
    shows the ability is gated by the record and not by a count that can only ever go down."""
    label = _label(KINDLE)
    engine = _fight(KINDLE, (ALLY_A, ALLY_B), seed="H76-RECHARGE")
    _use(engine, label, ALLY_A)
    _next_turn(engine)
    assert ALLY_A not in _offered(engine, label), "the use was not recorded at all"

    engine._remove_condition(engine.state.actors[OWNER], target_limits.condition_id(), "system:short_rest")
    _next_turn(engine)
    offered = _offered(engine, label)
    assert ALLY_A in offered, f"after a rest the ability did not come back on the same creature; offered {sorted(offered)}"
    assert _counter(engine, KINDLE) in engine.state.actors[OWNER].resource_maximums, "the use counter was lost"


# ------------------------------------------------------------------ persistence, through the real service
def _table_offered(table, match_id, label=_label(KINDLE)) -> set:
    """The creatures the fighter is offered this ability against, in the real table menu."""
    menu = table.state(match_id)["menu"]
    return {target for group in menu["actions"] if group["label"] == label
            for option in group["options"] for target in option.get("target_ids") or ()}


def _fresh_turn(table, match_id, actor_id) -> None:
    """A whole new turn for ``actor_id``, so a spent Bonus Action is available again."""
    if table.state(match_id)["menu"]["actor_id"] == actor_id:
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    turn(table, match_id, actor_id)


def test_the_ledger_survives_a_real_table_commit_and_a_fresh_load(tmp_path):
    """The ledger is stored in fight state, so it has to come back through the **shipped** persistence path: a
    real table action, a real commit to disk, and a brand new ``CombatService`` reloading the match. An in-memory
    copy of the engine can only prove the object still says what it said, and would pass even if the journal,
    the reducer or the commit lost the record."""
    label = _label(KINDLE)
    combat, table, match_id = fight(tmp_path, (KINDLE,), ally=(), seed="H76-SERVICE")
    turn(table, match_id, LEFT)
    assert {LEFT, ALLY} <= _table_offered(table, match_id, label), "the talent was never offered against both"

    assert act(table, match_id, label, target_id=LEFT)["status"] == "COMMITTED"
    _fresh_turn(table, match_id, LEFT)
    assert LEFT not in _table_offered(table, match_id, label), "the use on yourself was not committed to the table"
    assert ALLY in _table_offered(table, match_id, label), "using it on yourself cost the talent against the ally"

    # a brand new service, reading the match back off disk
    engine = reload(combat, match_id)
    held = [c for c in engine.state.actors[LEFT].conditions.values() if c.condition_id == target_limits.condition_id()]
    assert len(held) == 1, "the record was lost by the commit and reload"
    counter = _counter_for(engine, LEFT, KINDLE)
    assert target_limits.used_on(engine.state.actors[LEFT], counter, engine.state.actors[LEFT]), \
        "the use on yourself did not survive a real commit and reload"
    assert not target_limits.used_on(engine.state.actors[LEFT], counter, engine.state.actors[ALLY]), \
        "a reload invented a use on a creature it was never used on"

    stored = held[0].data["used"]
    assert stored[counter] == [LEFT], f"the ledger stored something other than the creature it was used on: {stored}"
    assert all(isinstance(value, str) for value in (*stored, *stored[counter], counter)), \
        "the ledger stored something that is not a string"
    assert engine.state.actors[LEFT].display_name in held[0].data["label"], \
        f"the reason the player reads did not survive the reload: {held[0].data['label']!r}"

    # and the table still refuses the same creature while offering the other one
    _fresh_turn(table, match_id, LEFT)
    offered = _table_offered(table, match_id, label)
    assert LEFT not in offered, "the committed use on yourself was forgotten, so it was offered again"
    assert ALLY in offered, f"after a real commit and reload offered {sorted(offered)}"


def _counter_for(engine, actor_id, mechanic_id) -> str:
    owner = engine.state.actors[actor_id]
    return next(key for key in owner.resource_maximums
                if key.startswith(target_limits.USES) and key.endswith(mechanic_id))


def test_a_fight_saved_with_the_old_one_use_resource_still_loads(tmp_path):
    """Fights saved before this lane carry a **1-use** bundle: the ability had one use for the whole fight. Such a
    fight must load, replay and keep behaving exactly as it was saved rather than being rewritten, because the
    plug-in keys off the compiled counter and a 1-use counter is not a per-creature one."""
    label = _label(KINDLE)

    def old_bundle(bundle):
        """Rebuild the actor's resources the way the compiler did before per-creature widening."""
        for row in bundle["actor_template"]["resources"]:
            if row["resource_id"].startswith(target_limits.USES) and KINDLE in row["resource_id"]:
                row["initial"] = row["maximum"] = 1

    combat, table, match_id = fight(tmp_path, (KINDLE,), ally=(), seed="H76-LEGACY", prepare_bundle=old_bundle)
    owner = combat._load_session(match_id).engine.state.actors[LEFT]
    counter = next(key for key in owner.resource_maximums
                   if key.startswith(target_limits.USES) and key.endswith(KINDLE))
    assert owner.resource_maximums[counter] == 1, "the fixture is not the old one-use bundle"

    turn(table, match_id, LEFT)
    assert act(table, match_id, label, target_id=LEFT)["status"] == "COMMITTED"

    engine = reload(combat, match_id)  # asserts the replay passes and the state is identical
    owner = engine.state.actors[LEFT]
    assert owner.resource_maximums[counter] == 1, "a reload rewrote an old saved fight's use counter"
    assert not target_limits.is_per_target(owner, counter), \
        "an old saved fight was treated as per-creature, so the plug-in would change how it plays"
    assert not [c for c in owner.conditions.values() if c.condition_id == target_limits.condition_id()], \
        "an old one-use fight grew a per-creature ledger it was never saved with"


# ------------------------------------------------------------------ one model for every printed per-creature record
def limit_line(text: str) -> str:
    """The printed "Use Limit:" line, if the record has one."""
    found = re.search(r"^\s*(?:Use )?Limit\s*:\s*(.+)$", text or "", re.I | re.M)
    return found.group(1).strip() if found else ""


# Written out by hand from the owner's own sheets, NOT derived from the detector under test: a record printed
# here that the model does not recognise is one use for the whole fight again, and a record printed in the rules
# that is missing from this table is a record no test would ever look at.
PRINTED_PER_CREATURE = {
    "TAL_AIR_EMPTY_LUNG_EDICT": "Once per long rest per target",
    "TAL_BRUTE_SOUL_SUNDER": "Once per creature per long rest",
    "TAL_FATE_BORROWED_LIFESPAN_TALISMAN": "Once per Long Rest per creature",
    "TAL_FLOWERS_FLOWER_OF_FALSE_DEATH": "Once per long rest per creature",
    "TAL_FLOWERS_IMMORTAL_LOTUS_SEED": "Once per Realm per creature",
    "TAL_GUARDIAN_PUNISHING_CHALLENGE": "Once per turn per creature",
    "TAL_IRON_FIST_QUIVERING_GATE_STRIKE": "Once per creature per long rest",
    "TAL_SCOUNDREL_STEAL_ONGOING_TECHNIQUE": "Once per long rest per creature",
    "TAL_SCOUNDREL_STEAL_TALENT": "Once per long rest per creature",
    "TAL_SWORD_MERIDIAN_CUTTING_STRIKE": "Once per creature per short rest",
    "TAL_WRESTLING_MERIDIAN_WRENCHING_LOCK": "Once per creature per short rest",
    "TAL_YANG_KINDLE_THE_WOUNDED_BREATH": "Once per Short Rest per creature",
    "TAL_YANG_LIFE_REFUSES_CLOSURE": "Once per Long Rest per creature",
    "tianxia.talent.blood.bloodline_ascension": "Once per Realm per creature",
}

# The printed limits that are not a rest, scene or fight a character takes one use per. A realm, a month or a turn
# is not a per-fight budget, so the model deliberately leaves them on the compiler's own counter.
NOT_FIGHT_SHAPED = {
    "TAL_FLOWERS_IMMORTAL_LOTUS_SEED": "Once per Realm per creature",
    "TAL_GUARDIAN_PUNISHING_CHALLENGE": "Once per turn per creature",
    "tianxia.talent.blood.bloodline_ascension": "Once per Realm per creature",
}

# Per-creature limits this lane deliberately does **not** execute, so they must not grow a widened counter:
# a 99-wide counter that nothing records would be unlimited, a worse bug than the one being fixed.
REACTION_OR_PASSIVE = {
    "TAL_YANG_LIFE_REFUSES_CLOSURE": "a Reaction",
    "TAL_FLOWERS_FLOWER_OF_FALSE_DEATH": "a Reaction",
    "TAL_SCOUNDREL_STEAL_TALENT": "a passive talent",
    # already enforced per creature by combat/ext/fate_riders.py, which owns Borrowed Lifespan's limit
    "TAL_FATE_BORROWED_LIFESPAN_TALISMAN": "enforced by combat/ext/fate_riders.py",
}


def test_the_list_of_printed_per_creature_records_is_the_whole_of_them(printed):
    """Every printed "Use Limit" line that names a creature or a target, and no others, is the table above. A
    newly printed per-creature record that nobody added here fails this test instead of slipping through."""
    found = {mid: limit_line(text) for mid, text in printed.items()
             if re.search(r"per (creature|target)\b", limit_line(text), re.I)}
    only_here = sorted(set(found) - set(PRINTED_PER_CREATURE))
    missing_here = sorted(set(PRINTED_PER_CREATURE) - set(found))
    reworded = {mid: found[mid] for mid in sorted(set(found) & set(PRINTED_PER_CREATURE))
                if PRINTED_PER_CREATURE[mid] != found[mid]}
    assert found == PRINTED_PER_CREATURE, (
        "the printed per-creature records changed, so the table above needs re-checking. "
        f"printed but not in the table: {only_here}; in the table but no longer printed: {missing_here}; "
        f"printed with different words: {reworded}")


def test_every_fight_shaped_per_creature_limit_is_typed_for_the_one_model(printed, typed):
    """Each printed per-creature limit is handed to the one model: the record's typed ``use_limit`` has to be one
    the detector reads, so the compiler widens the counter and the ledger enforces it. The documented exceptions
    are excluded by name, so each one has to be re-justified here rather than quietly dropped."""
    for mechanic_id, printed_limit in PRINTED_PER_CREATURE.items():
        assert printed_limit in printed[mechanic_id], \
            f"{mechanic_id} no longer prints {printed_limit!r}; the table above needs updating"
        if mechanic_id in NOT_FIGHT_SHAPED or mechanic_id in REACTION_OR_PASSIVE:
            continue
        use_limit = typed[mechanic_id]["use_limit"]
        assert target_limits.per_target_limit({"use_limit": use_limit}), \
            f"{mechanic_id} prints {printed_limit!r} but is typed {use_limit!r}, which the model does not read, " \
            f"so it compiles to one use for the whole fight"


@pytest.mark.parametrize("mechanic_id", sorted(REACTION_OR_PASSIVE))
def test_a_non_action_per_creature_record_carries_the_printed_limit_without_a_widened_counter(mechanic_id, printed):
    """These print a per-creature limit but are a Reaction or a passive, so the action ledger never records a use
    for them. The record carries the printed limit where that is the whole fix, and the counter is left at one
    rather than widened: a 99-wide counter that nothing records would be unlimited, which is a worse bug than
    the one being fixed."""
    assert mechanic_id in PRINTED_PER_CREATURE, f"{mechanic_id} is listed as an exception but prints no per-creature limit"
    bundle = compile_character(sheet([mechanic_id], cl=15), actor_id=OWNER)
    counters = {row["resource_id"]: (row["initial"], row["maximum"])
                for row in bundle["actor_template"]["resources"]
                if row["resource_id"].startswith(target_limits.USES) and mechanic_id in row["resource_id"]}
    assert not counters or all(size == (1, 1) for size in counters.values()), \
        f"{mechanic_id} grew a per-creature counter with no ledger to record its uses: {counters}"


# ------------------------------------------------------------------ the widening is only for a per-creature limit
def test_a_limit_that_names_no_creature_is_not_given_the_per_creature_model():
    """The widening is only for a limit that names a creature or a target. "Once per long rest" and
    "Once per item per scene" stay one use for the whole ability, exactly as printed."""
    for text in ("once per long rest", "once per short or long rest", "once per item per scene",
                 "once per realm per month", "once per combat", ""):
        assert not target_limits.per_target_limit({"use_limit": text}), text
    for text in ("once per creature per long rest", "once per long rest per creature",
                 "once per target per long rest", "once per short rest per creature",
                 "once per scene per target", "text:once per target per long rest"):
        assert target_limits.per_target_limit({"use_limit": text}), text
