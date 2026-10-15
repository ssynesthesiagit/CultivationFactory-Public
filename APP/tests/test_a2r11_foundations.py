"""A2R03 (automation pass r11): the Ancient Desolate Sacred Body and
Beast-Echo Marrow foundations' printed combat effects.

Every effect runs through the real engine the table service drives
(Gate4ControllerEngine.execute_intent); the tests marked "table
service" run the full CombatService + TabletopService stack, answer
the rendered prompts the way a player reads them, and reload the
fight cold after each commit, so what they read back is the shipped
automation rather than an in-memory leftover.
"""

from __future__ import annotations

import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, run_effects
from non_sphere_authority.foundation_features import features_for_stage
from tests.h1_support import (
    ALLY, FOE, ME, ROOT, amount, attack, duel, events, force_save,
    give, rewrites, script, sheet, use,
)

SACRED_BARE = "ancient_desolate_sacred_body_v0_2C"
MARROW_BARE = "beast_echo_marrow_v0_2A"
SACRED = "foundation." + SACRED_BARE
MARROW = "foundation." + MARROW_BARE

# The Ancient Desolate Sacred Body's eight features, as printed.
GENERATE = SACRED + ".generate_golden_sea_pulse"
FRAME = SACRED + ".saint_body_frame"
GUARD = SACRED + ".golden_sea_guard"
REBUKE = SACRED + ".saint_body_rebuke"
RESCUE = SACRED + ".refuse_heaven_lock"
BLOOD = SACRED + ".refined_golden_blood_root"
METHOD = SACRED + ".refined_pressure_becomes_method"
WAKE = SACRED + ".perfected_sacred_body_wake"

# The Beast-Echo Marrow's eight in-scope features, as printed.
M_GENERATE = MARROW + ".generate_pack_echo"
M_STRIKE = MARROW + ".pack_marrow_strike"
M_WITNESS = MARROW + ".beast_sense_witness"
M_GUARD = MARROW + ".marrow_pack_guard"
M_COMPANION = MARROW + ".companion_echo"
M_MARROW = MARROW + ".pack_marrow"
M_PREDATOR = MARROW + ".predator_answer"
M_STATE = MARROW + ".beast_echo_marrow_state"

PULSE = "resource:foundation.golden_sea_pulse"
ECHO = "resource:foundation.pack_echo"

FIGHTER = FACTORY_ACTOR_PREFIX + "a2r03-fighter"
SERVICE_FOE = FACTORY_ACTOR_PREFIX + "a2r03-foe"
SERVICE_ALLY = FACTORY_ACTOR_PREFIX + "a2r03-ally"

WAKE_CONDITION = "condition:typed.sacred_body_wake"
STATE_CONDITION = "condition:typed.beast_echo_marrow_state"


@pytest.fixture(autouse=True)
def _foundation_rule_inputs():
    """Declare the rule files consumed by the runtime feature-block glob.

    Public CI exports static fixture dependencies; checking these explicit
    paths keeps the real compiler inputs present and reports missing data
    before an unrelated combat assertion fails.
    """
    for relative in (
        "combat/rules/feature_blocks.d/sacred_body.json",
        "combat/rules/feature_blocks.d/beast_echo.json",
    ):
        assert (ROOT / relative).is_file(), f"Missing foundation combat rules: {relative}"


def _sacred(stage="Perfected"):
    return {"foundation_id": SACRED_BARE, "stage": stage,
            "resource": {"name": "Golden Sea Pulse",
                         "resource_id": f"foundation.resource.{SACRED_BARE}",
                         "maximum": 3, "current": 0, "initial_current": 0}}


def _marrow(stage="Perfected"):
    return {"foundation_id": MARROW_BARE, "stage": stage,
            "resource": {"name": "Pack Echo",
                         "resource_id": f"foundation.resource.{MARROW_BARE}",
                         "maximum": 3, "current": 0, "initial_current": 0}}


def _doc(mids, name, *, foundation=None, creature_types=(), hp=500, ac=14):
    doc = sheet(mids, cl=10, dc=16, key="CON", foundation=foundation)
    doc["identity"]["display_name"] = name
    if creature_types:
        doc["identity"]["creature_types"] = list(creature_types)
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
    doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = ac
    return doc


def _first_feature(bare):
    return features_for_stage(bare, "Perfected")[0]["id"]


# ------------------------------------------------------------------ the engine harness


def _provider(picks=None):
    """The table's reaction provider.

    A Foundation's own typed reaction consent (``reaction:typed.``)
    is answered USE, so the fighter takes the printed benefit; an
    extension choice on it is answered with the named option or the
    first on offer. A stock guard the fixture foe would spend
    (Stamina Guard, Sheath-Bone Guard, ...) is declined instead --
    it is not the Foundation's own reaction, and answering it would
    ask for a spend the scripted duel never set up."""
    picks = dict(picks or {})

    def react(request):
        from combat.gate4_models import ReactionDecision

        source = str(request.get("reaction_source_id") or "")
        options = request.get("legal_option_ids") or []
        trigger = request.get("choice_trigger") or {}
        if not source.startswith("reaction:typed."):
            return None, {}
        if options:
            picked = picks.get(str(trigger.get("choice_id")), options[0])
            option_ids = (picked if picked in options else options[0],)
        else:
            option_ids = ()
        return ReactionDecision(
            checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
            reaction_source_id=source, selection="USE", option_ids=option_ids), {}

    return react


def _duel(mids, foundation, *, ally_mids=None, seed="A2R03", picks=None):
    engine = duel(mids, ally_mids=ally_mids, cl=10, dc=16, key="CON",
                      foundation=foundation, seed=seed)
    engine.set_reaction_provider(_provider(picks))
    return engine


# ------------------------------------------------------------------ the table service


def _scripted_die(roller, sides):
    counter = roller.counter
    roller.counter += 1
    return min(10, sides), counter


def _service_fight(tmp_path, monkeypatch, foundation, bare, *,
                    foe_creature_types=(), ally=False, seed="A2R03", prepare=None,
                    positions=None):
    """A real CombatService match: the fighter (a player, MANUAL) owns
    the foundation; the LOCAL_AUTO foe attacks it. ``ally`` adds a
    fighter on the player's own side."""
    monkeypatch.setattr(DeterministicRollAuthority, "_die", _scripted_die)
    ids = [SERVICE_FOE, FIGHTER] + ([SERVICE_ALLY] if ally else [])
    team = {SERVICE_FOE: "team:b", FIGHTER: "team:a",
            **({SERVICE_ALLY: "team:a"} if ally else {})}
    where = {SERVICE_FOE: {"x": 4, "y": 6}, FIGHTER: {"x": 3, "y": 6},
             **({SERVICE_ALLY: {"x": 3, "y": 7}} if ally else {})}
    where.update(positions or {})
    docs = {SERVICE_FOE: _doc([], "the foe", creature_types=foe_creature_types),
            FIGHTER: _doc([_first_feature(bare)], "the fighter", foundation=foundation)}
    # The scripted duel die is fixed, so only the modifier can reorder the
    # turn order. The foe's id would otherwise win the initiative tie-break
    # ("fighter" sorts before "foe"), so it takes the higher Dexterity and
    # acts first: these tests need the foe's blow to land before the player.
    for ability in docs[SERVICE_FOE]["ability_scores_and_statistics"]["abilities"]:
        if ability["ability"] == "DEX":
            ability["score"] = 20
            ability["modifier"] = 5
    if ally:
        docs[SERVICE_ALLY] = _doc([], "the ally")
    for aid in ids:
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(docs[aid]))
    bundles = [compile_character(docs[aid], actor_id=aid,
                                   reaction_plan={"ask": True} if aid == FIGHTER else None)
                 for aid in ids]
    if prepare is not None:
        from combat.canonical import canonical_sha256
        prepare(bundles)
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(
        bundles, ids, team, where, arena, [SERVICE_FOE],
        [aid for aid in ids if aid != SERVICE_FOE],
        control_modes={SERVICE_FOE: "MANUAL", FIGHTER: "MANUAL",
                         **({SERVICE_ALLY: "MANUAL"} if ally else {})},
        match_seed=seed, display_name="A2R03 foundations",
        maximum_rounds=10)["match_id"]
    return combat, table, mid


def _engine(combat, mid):
    return combat._load_session(mid).engine


def _answer_for(prompt, answer=None):
    """One table answer to one rendered prompt: a real option id inside
    its bounds, or the prompt's own default. This is what a player at
    the table sends."""
    choice = prompt.get("choice") or {}
    legal = [row["id"] for row in choice.get("options") or []]
    if answer == "DECLINE":
        return {**prompt["context"], "selection": "DECLINE"}
    if not legal:
        return {**prompt["context"], "selection": "DECLINE" if answer == "DECLINE" else "USE"}
    if answer is None:
        if choice.get("allow_decline"):
            return {**prompt["context"], "selection": "DECLINE"}
        picked = (choice.get("preferred") or legal)[:int(choice.get("minimum") or 1)]
    else:
        picked = [answer if answer in legal else legal[0]]
    return {**prompt["context"], "selection": "USE", "option_ids": picked}


def _act(table, mid, candidate_id, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"],
                       table.state(mid)["last_sequence"], list(answers))


def _play(table, mid, candidate_id, answer=None, *, limit=24):
    """Commit one table action, answering every question it raises."""
    answers, prompts = [], []
    for _ in range(limit):
        result = _act(table, mid, candidate_id, answers)
        if result["status"] == "COMMITTED":
            return result, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompts.append(result["reaction"])
        answers.append(_answer_for(result["reaction"], answer))
    raise AssertionError("too many prompts")


def _candidate(table, mid, label, target=None):
    for group in table.state(mid)["menu"]["actions"]:
        if label not in group["label"]:
            continue
        for option in group["options"]:
            if target is None or target in (option.get("target_ids") or []):
                return option["candidate_id"]
    raise AssertionError(
        f"{label!r} is not on the menu: {[g['label'] for g in table.state(mid)['menu']['actions']]}")


def _until(table, mid, actor_id, *, answer=None, limit=160):
    """Drive the table until it is ``actor_id``'s menu. The foe is
    MANUAL and its Unarmed Strike is played for it (a bare
    character's own controller would rather move than strike, and
    these tests need its blow to land, to deal damage and to
    generate the Pulse a hit generates); the LOCAL_AUTO ally takes
    its own actions."""
    for _ in range(limit):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor_id:
            return menu
        if menu["actor_id"] == SERVICE_FOE:
            _play(table, mid, _candidate(table, mid, "Unarmed Strike",
                                          target=FIGHTER), answer=answer)
            _play(table, mid, table.state(mid)["menu"]["end_turn"], answer=answer)
        elif menu["actor_id"] == SERVICE_ALLY:
            _play(table, mid, menu["end_turn"], answer=answer)
        else:
            _play(table, mid, menu["end_turn"], answer=answer)
    raise AssertionError(f"{actor_id}'s menu never came")


# ================================================================== Ancient Desolate Sacred Body


def test_the_ancient_desolate_foundation_compiles_its_eight_features():
    """Saint-Body Frame, Golden Sea Guard, Saint-Body Rebuke, Refuse
    Heaven-Lock and Generate Golden Sea Pulse at Awakened; Refined:
    Golden Blood Root, Refined: Pressure Becomes Method and Perfected:
    Sacred Body Wake join at Perfected -- and the Frame's maximum Hit
    Point increase is twice the Proficiency Bonus, three times with
    Golden Blood Root."""
    awakened = _duel([FRAME], _sacred("Awakened"))
    rows = awakened.typed_passive_rows[ME] + awakened.typed_reaction_rows[ME]
    owned = {row.get("feature_id") for row in rows}
    assert {GENERATE, FRAME, GUARD, REBUKE, RESCUE} <= owned
    assert awakened.state.actors[ME].maximum_hp == 60 + 2 * 4

    perfected = _duel([FRAME], _sacred("Perfected"))
    rows = perfected.typed_passive_rows[ME] + perfected.typed_reaction_rows[ME]
    owned = {row.get("feature_id") for row in rows}
    assert {GENERATE, FRAME, GUARD, REBUKE, RESCUE, BLOOD, METHOD, WAKE} <= owned
    assert perfected.state.actors[ME].maximum_hp == 60 + 3 * 4


def test_a_won_hostile_physical_contest_generates_golden_sea_pulse():
    """Generate Golden Sea Pulse: a won Strength contested roll against a
    hostile creature generates a Pulse, and Pressure Becomes Method then
    offers the move (which the fighter takes)."""
    engine = _duel([GENERATE, METHOD], _sacred("Refined"))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(iter(engine.action_catalog.values()))
    spec = {"type": "contest_against", "harmful": True, "applies_to": "target",
            "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics",
                              "hazards": ["forced_movement"]},
            "target_check": {"kind": "check", "ability": "STR", "skill": "Athletics"},
            "on_success": [], "on_fail": []}
    script(engine, [2, 10])  # the foe's d20, then the fighter's (the target rolls first)
    from tests.test_lock9_granted_paths import request
    intent = request(engine)
    engine._active_intent = intent
    before = me.position
    run_effects(Context(engine, me, action, intent,
                          {"effects": [spec], "source": "test:contest"},
                          [foe], foe, {}), [spec])
    assert amount(engine, ME, "golden_sea_pulse") == 1
    moved = [e for e in engine.events
             if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME]
    assert len(moved) == 1 and me.position != before
    assert 0 < sum(e.payload["granted_cost_ft"] for e in moved) <= 10


def test_saint_body_frame_adds_the_proficiency_bonus_once_a_round_to_saves_and_checks():
    """Saint-Body Frame: +PB on a Strength or Constitution save or check
    against body pressure, once a round on one shared budget -- the save
    spends it, so the check that follows the same round goes without."""
    # The save half: the bonus turns a failed Constitution save against
    # poison pressure into a success.
    engine = _duel([FRAME], _sacred("Awakened"))
    script(engine, [10])
    save = force_save(engine, ME, "CON", dc=16, typed=True,
                        condition="poisoned")
    assert (save.payload or {}).get("success") is True
    # Once a round: the second save the same round goes without the bonus.
    engine.state.actors[ME].resources[PULSE] = 0  # isolate Frame from Refuse Heaven-Lock
    script(engine, [10])
    again = force_save(engine, ME, "CON", dc=16, typed=True,
                         condition="poisoned")
    assert (again.payload or {}).get("success") is False

    # The check half: the bonus turns a failed Strength check against
    # poison pressure into a success -- and it shares the save's budget.
    checked = _duel([FRAME], _sacred("Awakened"))
    me, foe = checked.state.actors[ME], checked.state.actors[FOE]
    action = next(iter(checked.action_catalog.values()))
    spec = {"type": "contest_against", "harmful": True, "applies_to": "target",
            "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics",
                              "hazards": ["poisoned"]},
            "target_check": {"kind": "dc", "dc": 12, "label": "the poison pressure"},
            "on_success": [], "on_fail": []}
    script(checked, [8])  # 8 + 2 = 10; the Frame's +4 reaches 14
    run_effects(Context(checked, me, action, None,
                          {"effects": [spec], "source": "test:frame"},
                          [foe], foe, {}), [spec])
    rolled = [e for e in checked.events
                if e.event_type == "CHECK_ROLLED" and e.actor_id == ME]
    assert rolled and rolled[-1].payload["success"] is True

    # The shared budget: a save first spends it, so the check after it
    # the same round fails without the bonus.
    shared = _duel([FRAME], _sacred("Awakened"))
    script(shared, [10])
    force_save(shared, ME, "CON", dc=14, typed=True,
                 condition="poisoned")  # spends the round's bonus
    shared.state.actors[ME].resources[PULSE] = 0  # isolate the shared Frame budget
    me, foe = shared.state.actors[ME], shared.state.actors[FOE]
    action = next(iter(shared.action_catalog.values()))
    script(shared, [8])  # 10 without the bonus: 8 + 2 < 12
    run_effects(Context(shared, me, action, None,
                          {"effects": [spec], "source": "test:frame"},
                          [foe], foe, {}), [spec])
    rolled = [e for e in shared.events
                if e.event_type == "CHECK_ROLLED" and e.actor_id == ME]
    assert rolled and rolled[-1].payload["success"] is False


def test_refuse_heaven_lock_spends_a_pulse_to_turn_a_failed_body_check_into_a_success():
    """Refuse Heaven-Lock: a failed Strength or Constitution ability
    check against body pressure may spend 1 Golden Sea Pulse to add
    PB + the Constitution modifier to it."""
    engine = _duel([RESCUE, GENERATE], _sacred("Awakened"))
    give(engine, ME, golden_sea_pulse=1)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    action = next(iter(engine.action_catalog.values()))
    spec = {"type": "contest_against", "harmful": True, "applies_to": "target",
            "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics",
                              "hazards": ["poisoned"]},
            "target_check": {"kind": "dc", "dc": 18, "label": "the poison pressure"},
            "on_success": [], "on_fail": []}
    script(engine, [8])  # 8 + 2 = 10 fails; the Lock's +4 +2 reaches 16
    run_effects(Context(engine, me, action, None,
                          {"effects": [spec], "source": "test:lock"},
                          [foe], foe, {}), [spec])
    assert [r for r in rewrites(engine)
              if r.source_definition_id == RESCUE]
    assert any(e.event_type == "RESOURCE_SPENT" and e.actor_id == ME
               and e.payload.get("resource_id") == PULSE for e in engine.events)
    rolled = [e for e in engine.events
                if e.event_type == "CHECK_ROLLED" and e.actor_id == ME]
    assert rolled and rolled[-1].payload["success"] is True


def test_golden_sea_guard_reduces_corruptive_damage_and_golden_blood_root_marks_the_source(
        tmp_path, monkeypatch):
    """Golden Sea Guard: hostile damage is reduced by twice the
    Proficiency Bonus + the Constitution modifier, and by another
    Proficiency Bonus when the damage or its rider comes from a
    corruptive or suppressive source (a demon's blow); Golden Blood
    Root then marks that source for Advantage on the fighter's next
    eligible save against it."""
    def prepare(bundles):
        owner = next(b for b in bundles if b["actor_id"] == FIGHTER)
        next(r for r in owner["actor_template"]["resources"] if r["resource_id"] == PULSE)["initial"] = 1
        foe = next(b for b in bundles if b["actor_id"] == SERVICE_FOE)
        strike = next(a for a in foe["action_catalog"] if a["display_name"] == "Unarmed Strike")
        strike["parameters"]["typed"]["weapon"]["fixed_damage"] = 20
        strike["parameters"]["expected_damage"] = 20
    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _sacred("Perfected"), SACRED_BARE,
        foe_creature_types=("Demon",), prepare=prepare)
    engine = _engine(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    before = fighter.current_hp
    # A prior Pulse pays the Guard on the first demon blow. A Pulse from an
    # earlier blow would expire if we ended the fighter's intervening turn.
    _until(table, mid, FIGHTER, answer="USE")
    engine = _engine(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    # A 20-damage blow leaves 6 after 2*PB + CON + corruptive PB = 14.
    # It would leave 10 if the corruptive rider were missing.
    assert before - fighter.current_hp == 6
    resolved = [e for e in engine.events
                  if e.event_type == "REACTION_RESOLVED"
                  and e.source_definition_id == GUARD]
    assert resolved
    assert resolved[-1].payload["reduction"] == 14
    # Golden Blood Root marked the demon: the fighter holds the
    # guard-advantage mark for its next save against that source.
    assert any(e.event_type == "CONDITION_APPLIED" and
               e.payload.get("condition_id") == "condition:typed.sacred_body_guard_advantage"
               for e in engine.events)
    # The fighter's next turn has now started, so the source-bound mark expired.
    assert not any(i.condition_id == "condition:typed.sacred_body_guard_advantage"
                   for i in fighter.conditions.values())


def test_sacred_body_wake_is_a_bonus_action_that_grants_temporary_hit_points_and_survives_the_reload(
        tmp_path, monkeypatch):
    """Perfected: Sacred Body Wake: a bonus action that spends 1
    Golden Sea Pulse (once per rest) to grant temporary Hit Points
    equal to the cultivation level + the Constitution modifier, and
    the one-minute Wake state -- both still there after a cold
    reload."""
    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _sacred("Perfected"), SACRED_BARE)
    engine = _engine(combat, mid)
    # The foe's first blow generates the Pulse the Wake spends.
    _until(table, mid, FIGHTER)
    engine = _engine(combat, mid)
    assert amount(engine, FIGHTER, "golden_sea_pulse") == 1
    wake = _candidate(table, mid, "Sacred Body Wake")
    _play(table, mid, wake)
    # Cold reload: the temporary Hit Points and the Wake state persist.
    engine = _engine(combat, mid)
    fighter = engine.state.actors[FIGHTER]
    assert fighter.temporary_hp == 10 + 2  # cultivation level + Constitution modifier
    assert any(i.condition_id == WAKE_CONDITION for i in fighter.conditions.values())
    # Once per rest: the Wake is gone from the menu after one use.
    assert not [group for group in table.state(mid)["menu"]["actions"]
                  if "Sacred Body Wake" in group["label"]]


def test_saint_body_rebuke_spends_a_pulse_to_add_damage_and_pushes_the_target(
        tmp_path, monkeypatch):
    """Saint-Body Rebuke: after hitting a creature within 5 feet
    with an unarmed strike, spend 1 Golden Sea Pulse for +PB + the
    Constitution modifier damage, then the chosen rider (here: push
    the target 5 feet, which it is no more than one size larger
    than the fighter)."""
    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _sacred("Perfected"), SACRED_BARE)
    engine = _engine(combat, mid)
    foe = engine.state.actors[SERVICE_FOE]
    # The foe's first blow generates the Pulse the Rebuke spends.
    _until(table, mid, FIGHTER)
    # The fighter picks the push rider, then strikes within 5 feet.
    setting = _candidate(table, mid, "Saint-Body Rebuke: Push the target 5 feet")
    _play(table, mid, setting)
    strike = _candidate(table, mid, "Unarmed Strike", target=SERVICE_FOE)
    _play(table, mid, strike, answer="push")
    engine = _engine(combat, mid)
    foe = engine.state.actors[SERVICE_FOE]
    # Unarmed Strike deals 1 + STR (2), plus Rebuke's PB + CON (6).
    dealt = [e for e in engine.events
               if e.event_type == "DAMAGE_COMMITTED"
               and SERVICE_FOE in (e.target_ids or ())]
    assert sum(int((e.payload or {}).get("hp_damage") or 0) for e in dealt) == 9
    # The push rider moved the foe 5 feet away from the fighter.
    fighter = engine.state.actors[FIGHTER]
    assert (foe.position.x, foe.position.y) != (fighter.position.x + 1, fighter.position.y)
    assert engine._distance_actor_to_actor(fighter, foe) > 5


# ================================================================== Beast-Echo Marrow


def test_the_beast_echo_foundation_compiles_its_features():
    engine = _duel([M_STRIKE], _marrow("Perfected"))
    rows = engine.typed_passive_rows[ME] + engine.typed_reaction_rows[ME]
    owned = {row.get("feature_id") for row in rows}
    assert {M_GENERATE, M_STRIKE, M_WITNESS, M_GUARD, M_COMPANION,
                M_MARROW, M_PREDATOR, M_STATE} <= owned


def test_generate_pack_echo_from_a_scope_hit_with_an_ally_near():
    """Generate Pack Echo: a Fixed Beast-Echo Scope hit (an unarmed
    strike) while an ally is within 30 feet of the fighter or the
    target generates a Pack Echo."""
    engine = _duel([M_GENERATE], _marrow("Perfected"), ally_mids=[])
    # The ally stands beside the fighter (within 30 ft of both).
    assert engine.grid.distance_ft(engine.state.actors[ALLY].position,
                                   engine.state.actors[ME].position) <= 30
    script(engine, [10, 4])  # the attack roll, then the damage die
    use(engine, "Unarmed Strike", target=FOE)
    assert amount(engine, ME, "pack_echo") == 1


def test_predator_answer_takes_temporary_hit_points_on_a_beast_aspected_hit():
    """Predator Answer: generating Pack Echo from a hit on a beast-
    aspected creature grants temporary Hit Points equal to the
    Proficiency Bonus, or a 5-foot move that does not provoke (the
    choice; the automatic answer takes the temporary Hit Points)."""
    engine = _duel([M_GENERATE, M_PREDATOR], _marrow("Perfected"))
    engine.state.actors[FOE].creature_types = ("Beast",)
    script(engine, [10, 4])
    use(engine, "Unarmed Strike", target=FOE)
    assert amount(engine, ME, "pack_echo") == 1  # the beast-aspected hit generated one
    assert engine.state.actors[ME].temporary_hp == 4  # Predator Answer's temporary Hit Points


def test_pack_marrow_strike_spends_an_echo_to_add_damage():
    """Pack-Marrow Strike: after a Fixed Beast-Echo Scope hit, spend
    1 Pack Echo to add PB damage of the hit's type."""
    engine = _duel([M_GENERATE, M_STRIKE], _marrow("Perfected"))
    give(engine, ME, pack_echo=1)
    script(engine, [10, 4])
    use(engine, "Unarmed Strike", target=FOE)
    assert amount(engine, ME, "pack_echo") == 0  # spent on the hit
    dealt = [e for e in engine.events
               if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert sum(int((e.payload or {}).get("hp_damage") or 0) for e in dealt) == 1 + 2 + 4


def test_pack_marrow_adds_another_proficiency_bonus_when_the_fighter_damaged_that_target():
    """Refined: Pack Marrow: the Strike's damage is another PB when the
    fighter already damaged the same target since the start of its last
    turn."""
    engine = _duel([M_GENERATE, M_STRIKE, M_MARROW], _marrow("Perfected"), ally_mids=[])
    give(engine, ME, pack_echo=2)
    script(engine, [10, 4])
    use(engine, "Unarmed Strike", target=FOE)  # the first hit damages the target
    script(engine, [10, 4])
    attack(engine, ALLY, FOE, bonus=8, source_id="action:test.natural_hit")
    dealt = [int((e.payload or {}).get("hp_damage") or 0) for e in engine.events
               if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert 8 in dealt  # PB + PB (Pack Marrow's another PB)


def test_beast_sense_witness_adds_the_proficiency_bonus_to_a_scope_save():
    """Beast-Sense Witness: spend 1 Pack Echo to add PB to a saving
    throw against a scope effect (a frightened save is in the Fixed
    Beast-Echo Scope's fear hazards)."""
    engine = _duel([M_WITNESS], _marrow("Perfected"))
    give(engine, ME, pack_echo=1)
    script(engine, [10, 10])  # the save, then the Witness's redrawn d20
    save = force_save(engine, ME, "WIS", dc=16, typed=True,
                        condition="frightened", forcer=FOE)
    assert [r for r in rewrites(engine)
              if r.source_definition_id == M_WITNESS]
    assert amount(engine, ME, "pack_echo") == 0


def test_marrow_pack_guard_reduces_damage_by_pb_and_the_cultivation_ability_modifier():
    """Marrow Pack Guard: when the fighter takes damage from a
    beast-aspected source, the reduction is PB + the cultivation ability
    modifier (the compiled reaction's PB plus this plug-in's modifier)."""
    engine = _duel([M_GUARD], _marrow("Perfected"))
    engine.state.actors[FOE].creature_types = ("Beast",)
    give(engine, ME, pack_echo=1)
    script(engine, [10, 4])
    attack(engine, FOE, ME, bonus=8, source_id="action:test.beast_blow")
    # The foe's 4+2 = 6 damage is reduced by PB (4) + CON mod (2) = 6.
    dealt = [int((e.payload or {}).get("hp_damage") or 0) for e in engine.events
               if e.event_type == "DAMAGE_COMMITTED" and ME in (e.target_ids or ())]
    assert dealt and dealt[-1] == 0
    assert amount(engine, ME, "pack_echo") == 0


def test_beast_echo_marrow_state_is_a_bonus_action_that_pairs_and_grants_its_modes():
    """Beast-Echo Marrow State: a bonus action (1 Pack Echo + 2 CP) that
    pairs the fighter with one ally within 60 feet for 1 minute; the pair
    has Advantage on saves against fear from beast-aspected sources, and
    the pair's Pack-Marrow Strike gains another PB once a round."""
    engine = _duel([M_STATE, M_STRIKE], _marrow("Perfected"), ally_mids=[])
    assert engine.state.actors[ALLY].position != engine.state.actors[ME].position
    engine.state.actors[FOE].creature_types = ("Beast",)
    give(engine, ME, pack_echo=1)
    # The bonus action pairs the fighter with the ally (the closest on offer).
    script(engine, [10])
    use(engine, "Beast-Echo Marrow State")
    assert any(i.condition_id == STATE_CONDITION
                 for i in engine.state.actors[ME].conditions.values())
    assert any(i.condition_id == STATE_CONDITION
                 for i in engine.state.actors[ALLY].conditions.values())
    # Advantage on a frightened save forced by the beast-aspected foe.
    # Check the standing Advantage with no Echo available for the separately
    # owned Witness. A successful DC-12 save also keeps Frightened from
    # altering the later Strike rolls; then restore the prior Echo fixture.
    held = engine.state.actors[ME].resources[ECHO]
    engine.state.actors[ME].resources[ECHO] = 0
    script(engine, [10, 10])
    save = force_save(engine, ME, "WIS", dc=12, typed=True,
                        condition="frightened", forcer=FOE)
    engine.state.actors[ME].resources[ECHO] = held
    assert (save.payload or {}).get("mode") == "ADVANTAGE"
    # The pair's Strike gains another PB once a round: the first hit adds
    # PB + PB, the second (the budget spent) only PB.
    give(engine, ME, pack_echo=1)  # a prior Echo for the isolated Strike phase
    script(engine, [10, 4])
    use(engine, "Unarmed Strike", target=FOE)
    # Supply a second action in this isolated same-round bonus-budget test.
    engine.state.actors[ME].action_available = True
    give(engine, ME, pack_echo=1)
    script(engine, [10, 4])
    use(engine, "Unarmed Strike", target=FOE)
    dealt = [int((e.payload or {}).get("hp_damage") or 0) for e in engine.events
               if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())]
    assert 8 in dealt and 4 in dealt


def test_companion_echo_witnesses_a_bonded_companion_and_rerolls_its_failed_save():
    """Companion Echo: Beast-Sense Witness spends on a bonded companion's
    scope roll for another PB, and a companion whose save still failed
    after the Witness may reroll it for psychic damage equal to the
    fighter's cultivation level."""
    engine = _duel([M_COMPANION, M_WITNESS], _marrow("Perfected"), ally_mids=[])
    # A bonded companion: a summoned creature of the fighter's own.
    companion = copy.deepcopy(engine.state.actors[ALLY])
    companion.entity_id = "actor:factory.a2r03-companion"
    companion.summon = {"owner": ME, "group": "test:a2r03-echo", "status": "present",
                          "commanded": False, "range_ft": 60, "command_range_ft": 60,
                          "family": None}
    engine.state.actors[companion.entity_id] = companion
    give(engine, ME, pack_echo=1)
    # The companion fails its frightened save (8 + 2 = 10 < 16); the
    # fighter's Companion Echo rerolls it (the redrawn 10 + 2 = 12... the
    # Witness's own PB first, then the reroll), and takes 10 psychic damage.
    script(engine, [8, 10])
    hp_before = engine.state.actors[ME].current_hp
    save = force_save(engine, companion.entity_id, "WIS", dc=20, typed=True,
                        condition="frightened", forcer=FOE)
    assert [r for r in rewrites(engine)
              if r.source_definition_id == M_COMPANION]
    assert engine.state.actors[ME].current_hp == hp_before - 10  # the reroll's price
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == M_COMPANION
               for e in engine.events)


# ================================================================== the table service, cold


def test_the_sacred_body_wake_menu_names_its_cost_in_player_text(tmp_path, monkeypatch):
    """The Wake's button names the ability, what it costs and what it
    does, for a player who knows only basic D&D (no internal ids)."""
    monkeypatch.setattr(DeterministicRollAuthority, "_die", _scripted_die)
    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _sacred("Perfected"), SACRED_BARE)
    engine = _engine(combat, mid)
    _until(table, mid, FIGHTER)  # the foe's first blow generates the Pulse
    labels = [group["label"] for group in table.state(mid)["menu"]["actions"]]
    wake = next(label for label in labels if "Sacred Body Wake" in label)
    assert "Sacred Body Wake" in wake
    help_text = json.dumps(table.state(mid)["menu"], default=str)
    assert "Golden Sea Pulse" in help_text  # the cost is named, not an id
    assert "temporary Hit Points" in help_text  # what it does


def test_the_beast_echo_marrow_state_pairs_and_persists_cold(tmp_path, monkeypatch):
    """Beast-Echo Marrow State through the table service: the bonus
    action's costs (1 Pack Echo, 2 CP) are paid, the pair is chosen,
    and both chosen creatures still hold the state after a cold reload."""
    monkeypatch.setattr(DeterministicRollAuthority, "_die", _scripted_die)
    combat, table, mid = _service_fight(
        tmp_path, monkeypatch, _marrow("Perfected"), MARROW_BARE, ally=True)
    engine = _engine(combat, mid)
    _until(table, mid, FIGHTER)
    # The fighter's own unarmed strike (with the ally near) generates the
    # Pack Echo the state spends.
    strike = _candidate(table, mid, "Unarmed Strike", target=SERVICE_FOE)
    _play(table, mid, strike)
    state = _candidate(table, mid, "Beast-Echo Marrow State")
    _play(table, mid, state, answer=SERVICE_ALLY)  # the pair: the ally
    engine = _engine(combat, mid)
    assert any(i.condition_id == STATE_CONDITION
                 for i in engine.state.actors[FIGHTER].conditions.values())
    assert any(i.condition_id == STATE_CONDITION
                 for i in engine.state.actors[SERVICE_ALLY].conditions.values())
    # The state cost the Pack Echo and 2 CP (Qi).
    assert amount(engine, FIGHTER, "pack_echo") == 0
    qi = engine.state.actors[FIGHTER].resources.get("resource:core.qi", 30)
    assert qi == 28
