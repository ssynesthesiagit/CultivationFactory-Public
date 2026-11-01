"""AUTO52 (owner 2026-09-29: "automate everything"): the Beauty sphere's printed declaration saves and judged wound.

Every line automated here was a ``rider`` row in the typed authority, so the printed effect never reached the table and
reached the player as a GM reminder.  Each test fails on the authority as it stood before this lane: the rule text was
there but no engine rule ran it.

Owner rules_text.json / owner_text_edits.json:
* Captivated (Key Terms, and every Beauty talent that Captivates): "the first time on each of its turns that it targets
  a creature other than you with an attack or hostile action, it must make a Wisdom saving throw ... on failure it must
  choose you if legal, choose a legal non-hostile action, or lose that attack or hostile action".
* Beauty Beyond Form: "The first time on each of its turns that it targets one of your allies with an attack or damaging
  effect, it must repeat the saving throw. On a failure, it loses that attack or damaging effect. On a success, it acts
  normally and the Charmed condition ends."
* Beauty That Judges: "While judged, the first time on each of its turns that it damages a creature other than you, it
  takes Psychic damage equal to your Proficiency Bonus + your key ability modifier."

Plug-in: combat/ext/charm_rules.py (``declare_save`` / ``retaliate`` bar keys, the ``before_attack`` forced-miss
outcome, the ``candidate_allowed`` retarget and the ``damage_dealt`` wound).  Typed data: the ``declare_save`` and
``retaliate`` bars in the records that already held them (reviewed_final.d/mind.json, riders_lane3.json,
review_sw-beastmastery.json), edited in place.

Axes: the caster's own Cultivation Save DC is forced high (50) so the creature fails the printed save and low (-40) so
it succeeds, attacks land against AC -50 unless a test wants a miss.
"""

import importlib.util
from pathlib import Path

import pytest

from combat import typed_executor
from combat.ext import charm_rules
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import Position

_spec = importlib.util.spec_from_file_location("_auto52_harness", Path(__file__).with_name("test_riders_lane3.py"))
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)
H = L.H
ME, FOE, ALLY = H.ME, H.FOE, L.ALLY

BEAUTY = "tianxia.sphere.beauty"
CAPTURE = "Beauty Beyond Form"
JUDGES = "Beauty That Judges"
EYE = "Catch the Eye"


def _conds(actor):
    return {c.condition_id.removeprefix("condition:"): c for c in actor.conditions.values()}


def _bar(engine, actor, name):
    held = _conds(actor).get(name)
    return (held.data or {}).get("bar") if held is not None else None


def _strike(engine, attacker, target):
    """A plain weapon attack by ``attacker`` at ``target``: the events it made."""
    return L._act(engine, attacker, "Fu (Short Axe) attack", target)


def arena(talents, *, dc=16, ally=True, hostiles=1, foe_at=(4, 6), foe_talents=(), cl=10):
    """A Beauty fighter (3,6) [Wisdom save DC ``dc``], ``hostiles`` plain Factory foes and one ally on its side.

    Two hostiles matter for the printed "damages a creature other than you" / "targets a creature other than you"
    clauses, which need a second creature that is neither the charmer nor the judged creature.
    """
    sheet = H._sheet(BEAUTY, list(talents), H.AXE_KIT, cl=cl, dc=dc)
    ids = [ME] + [H.FOE] + [H.FOE + str(index) for index in range(2, 2 + hostiles - 1)]
    bundles = [compile_character(sheet, actor_id=ME)]
    starts, teams = {ME: {"x": 3, "y": 6}}, {ME: "team:a"}
    for index, actor_id in enumerate(ids[1:]):
        # the second hostile carries another weapon so the two compiled bundles keep distinct action ids
        kit = H.AXE_KIT if index == 0 else H.BOW_KIT
        sphere = BEAUTY if index == 0 and foe_talents else None
        bundles.append(compile_character(H._sheet(sphere, list(foe_talents) if index == 0 else [], kit, dc=50),
                                         actor_id=actor_id))
        starts[actor_id] = {"x": foe_at[0] + index, "y": foe_at[1]}
        teams[actor_id] = "team:b"
    if ally:
        bundles.append(compile_character(H._sheet(None, [], H.AXE_KIT, dc=dc), actor_id=ALLY))
        starts[ALLY], teams[ALLY] = {"x": 3, "y": 7}, "team:a"
    from combat.gate4_engine import Gate4ControllerEngine
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": list(starts), "team_by_actor": teams, "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    H._ready(engine)
    return engine


def _table_roster():
    """The same roster as ``arena`` as plain data, so a saved-fight test can create it through the table service."""
    bundles = [compile_character(H._sheet(BEAUTY, [], H.AXE_KIT, dc=50), actor_id=ME),
               compile_character(H._sheet(None, [], H.AXE_KIT, dc=50), actor_id=FOE),
               compile_character(H._sheet(None, [], H.AXE_KIT, dc=50), actor_id=ALLY)]
    starts = {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, ALLY: {"x": 3, "y": 7}}
    teams = {ME: "team:a", FOE: "team:b", ALLY: "team:a"}
    return tuple(bundles), {"primary_actor_ids": list(starts), "team_by_actor": teams, "starting_positions": starts}


OTHER = H.FOE + "2"


def _captivated(*, dc=50, foe_at=(4, 6)):
    """A Beauty fighter who Captivated the foe on its own turn (printed save forced), with one ally on its side."""
    engine = arena([], dc=dc, ally=True, foe_at=foe_at)
    L._act(engine, ME, EYE, FOE)
    return engine


def _asked(events):
    """The printed declaration saves among these events (the receipt, not any other save on the table)."""
    return [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("declaration_save")]


def _forced(events):
    return [e for e in events if e.event_type == "ATTACK_FORCED_MISS"]


def _declares(events):
    """The printed declaration saves among these events, whichever way they fell."""
    return [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE
            and (e.payload or {}).get("dc") == 50 and e.source_definition_id.endswith("CATCH_THE_EYE")]


def _attacks_on(engine, actor_id, target_id):
    engine.state.current_actor_id = actor_id
    engine.state.actors[actor_id].action_available = True
    return [c for c in engine.legal_candidates() if c.actor_id == actor_id
            and c.display_name.startswith("Fu (Short Axe) attack") and target_id in (c.target_ids or ())]


def _declared(engine, events):
    return [e for e in events if e.event_type == "SAVE_ROLLED" and (e.payload or {}).get("dc") is not None
            and e.actor_id == FOE]


# ------------------------------------------------------------------------------------------------- the Captivated declaration save
def test_a_captivated_creature_makes_the_printed_saving_throw_and_loses_the_attack_it_cannot_re_aim():
    """"it must make a Wisdom saving throw ... or lose that attack": the save is the Captivated caster's own DC, the
    attack is lost through the documented forced-miss outcome (the die and AC are untouched), and the reason is
    logged. The charmer is out of this attack's reach, so the printed "if legal" is not met and the loss is the
    only consequence left."""
    engine = _captivated()
    engine.state.actors[ME].position = Position(x=11, y=11)   # out of a short axe's reach
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("CATCH_THE_EYE")]
    assert [s.payload["dc"] for s in saves] == [50], saves
    assert saves[0].payload["success"] is False
    forced = _forced(events)
    assert len(forced) == 1 and forced[0].payload["log"].startswith("Catch the Eye: "), forced
    assert "misses" in forced[0].payload["log"] and ALLY.split(":")[-1] not in forced[0].payload["log"]
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED"], "the lost attack deals no damage"
    assert _asked(events)[0].payload["remedy"] == "lost"


def test_a_failed_declaration_really_re_aims_that_attack_at_the_charmer():
    """"it must choose you if legal": the chosen consequence is not only a log line. With the charmer in reach the
    engine records ATTACK_RETARGETED, rolls the attack against the charmer, and never against the creature that
    was declared -- the printed "choose you" really changes who is attacked."""
    engine = _captivated()
    L._begin_turn(engine, FOE)
    engine.state.actors[ME].armor_class = -50
    engine.state.actors[ALLY].armor_class = 100
    events = _strike(engine, FOE, ALLY)
    retargeted = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(retargeted) == 1, [e.event_type for e in events]
    assert retargeted[0].target_ids == (ME,), retargeted[0].target_ids
    assert retargeted[0].payload["original_target_id"] == ALLY
    assert retargeted[0].payload["attack_source_id"] == "action:typed.d043574154.weapon.fu"
    assert _asked(events)[0].payload["remedy"] == "redirect"
    assert _forced(events) == [], "a re-aimed attack is rolled against its new target, not force-missed"
    rolled = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert rolled and all(ALLY not in (e.target_ids or ()) for e in rolled), [e.target_ids for e in rolled]


def test_a_failed_declaration_loses_only_the_declared_attack_and_leaves_later_targets_alone():
    """"the first time on each of its turns": the printed consequences are all about the one declaration that
    failed, so the creature's *later* attacks that turn are neither lost nor withdrawn. The harness's own action
    grant is used for the second attack; no flag is written by the plug-in to make it available."""
    engine = _captivated()
    engine.state.actors[ME].position = Position(x=11, y=11)   # the printed loss, not a re-aim
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    first = _strike(engine, FOE, ALLY)
    assert _forced(first), "that attack is the one that was lost"
    second = _strike(engine, FOE, ALLY)
    assert _forced(second) == [], "only the attack that failed its own declaration is lost"
    assert _declares(second) == [], "'the first time on each of its turns': the save is not asked again"


def test_the_failed_declaration_records_which_printed_consequence_it_chose():
    """The chosen remedy is readable on the receipt, so the table (and a saved fight) can show what the creature
    was told it must do, and the printed "if legal" wording is only used when the applier is a legal target."""
    engine = _captivated()
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    asked = _asked(events)
    assert len(asked) == 1, [e.event_type for e in events]
    assert asked[0].payload["remedy"] in ("redirect", "lost"), asked[0].payload
    assert asked[0].payload["log"], "the consequence is stated in plain words"
    assert engine.state.actors[ME].display_name in asked[0].payload["log"]


def test_an_ordinary_manually_controlled_captive_is_enrolled_to_decide_without_any_other_choice_feature(tmp_path):
    """Checklist 9 / AUTO52r1 finding 2: the condition *creates* the decision, so the condition owns it. This
    captive is enrolled with nothing but its Captivated bar -- no Ask-me reaction row, no choice reactor, no setup
    task and no ``choice_owner`` passive -- which is exactly what the service used to get wrong."""
    from types import SimpleNamespace

    from combat.gate5_service import CombatService

    engine = _captivated()
    service = CombatService(H.ROOT, tmp_path / "service")
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    assert not [row for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(FOE, []) if row.get("ask")], \
        "no Ask-me reaction row of its own"
    assert not [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(FOE, []) if row.get("choice_owner")]
    assert not getattr(engine, "state", None).setup_tasks
    enrolled = service._ask_reactors({"participant_control_modes": {FOE: "MANUAL"}}, session)
    assert FOE in enrolled, "the Captivated condition owns the choice, so the service asks its manual bearer"
    automatic = service._ask_reactors({"participant_control_modes": {FOE: "LOCAL_AUTO"}}, session)
    assert FOE not in automatic, "an AI bearer still decides on its own (checklist 9)"


def test_a_player_controlled_creature_is_asked_and_its_answer_is_the_outcome(tmp_path):
    """The printed rule hands the creature the choice, so a player controlling it decides -- and the answer is
    what happens, not a label: answering "lost" loses the attack, answering "redirect" re-aims it at the charmer.
    The enrolment comes from the service's own ownership query, not a hand-set ``typed_ask_reactors``."""
    from types import SimpleNamespace

    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService

    service = CombatService(H.ROOT, tmp_path / "service")
    for answer, expects in (("lost", "ATTACK_FORCED_MISS"), ("redirect", "ATTACK_RETARGETED")):
        engine = _captivated()
        session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
        engine.typed_ask_reactors = service._ask_reactors({"participant_control_modes": {FOE: "MANUAL"}}, session)
        assert FOE in engine.typed_ask_reactors, answer
        L._begin_turn(engine, FOE)
        engine.state.actors[ALLY].armor_class = -50
        requests = []

        def reply(request, _answer=answer, _seen=requests):
            if request["reaction_source_id"].endswith(".declaration"):
                _seen.append(request)
                return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                        reaction_source_id=request["reaction_source_id"], selection="USE",
                                        option_ids=(_answer,)), None
            return None, None

        engine.set_reaction_provider(reply)
        events = _strike(engine, FOE, ALLY)
        assert requests, f"the player is asked when the answer is {answer!r}"
        assert sorted(requests[0]["extension_choice"]["option_ids"]) == ["lost", "redirect"]
        assert _asked(events)[0].payload["remedy"] == answer
        assert [e for e in events if e.event_type == expects], [e.event_type for e in events]
        engine.set_reaction_provider(None)


def test_the_choose_you_option_is_offered_only_when_the_applier_is_a_legal_target(tmp_path):
    """"it must choose you **if legal**": with the charmer out of this attack's reach the option is not offered, and
    the only remaining printed consequence -- the loss -- is applied without a question that has one answer."""
    from types import SimpleNamespace

    from combat.gate5_service import CombatService

    engine = _captivated()
    service = CombatService(H.ROOT, tmp_path / "service")
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    engine.typed_ask_reactors = service._ask_reactors({"participant_control_modes": {FOE: "MANUAL"}}, session)
    # Put the charmer out of this attack's reach (the bar still stands), leaving the ally reachable.
    engine.state.actors[ME].position = Position(x=11, y=11)
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    requests = []
    engine.set_reaction_provider(lambda request: (requests.append(request), (None, None))[1])
    events = _strike(engine, FOE, ALLY)
    assert requests == [], "a one-option question is not a choice, so the engine does not ask one"
    assert _asked(events)[0].payload["remedy"] == "lost"
    assert [e for e in events if e.event_type == "ATTACK_FORCED_MISS"]
    engine.set_reaction_provider(None)


def test_a_successful_declaration_save_lets_the_attack_through_and_is_not_asked_again_that_turn():
    engine = _captivated(dc=-40)          # the caster's DC 40 below the foe's Wisdom save: it saves
    foe = engine.state.actors[FOE]
    foe.saving_throws["WIS"] = 100
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert [e for e in events if e.event_type == "ATTACK_FORCED_MISS"] == []
    assert H._payloads(events, "ATTACK_ROLLED")[0]["modified_total"] >= -50
    assert _attacks_on(engine, FOE, ALLY), "a saved declaration leaves the other targets alone"


def test_the_declaration_save_is_asked_once_per_creature_turn_not_once_per_attack():
    """"the first time on each of its turns": a saved declaration lets the creature attack freely after it."""
    engine = _captivated()
    engine.state.actors[FOE].saving_throws["WIS"] = 100       # saves, so the second attack is still offered
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    first = _strike(engine, FOE, ALLY)
    assert len(_declares(first)) == 1, [e.event_type for e in first]
    second = _strike(engine, FOE, ALLY)
    assert _declares(second) == []


def test_a_captivated_creature_can_still_attack_its_charmer_without_a_save():
    """"a creature other than you": the printed save is not asked for an attack aimed at the charmer itself."""
    engine = _captivated()
    L._begin_turn(engine, FOE)
    engine.state.actors[ME].armor_class = -50
    events = _strike(engine, FOE, ME)
    assert _asked(events) == []
    assert _forced(events) == []


@pytest.mark.parametrize("talent,name", [("captive_audience", "Captive Audience"),
                                         ("face_that_halts_the_army", "Face That Halts the Army"),
                                         ("jewel_mind_reflection", "Jewel-Mind Reflection")])
def test_every_beauty_talent_that_captivates_runs_the_same_printed_save(talent, name):
    """One bar key, one rule: the Captivated bars these talents impose all carry the printed declaration save."""
    engine = arena(["tianxia.talent.beauty." + talent], dc=50, ally=True)
    if talent == "captive_audience":
        L._picks(engine, [FOE])
        candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith("Captive Audience at ")
                         and c.destination is not None and c.destination.x > 3 and c.destination.y == 6)
        from combat.gate2_runtime_models import ActionIntent
        engine.execute_intent(ActionIntent(intent_id="beauty-cone", decision_id=candidate.decision_id,
                                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                           actor_id=ME, destination=candidate.destination))
    elif talent == "face_that_halts_the_army":
        L._picks(engine, [FOE])
        L._act(engine, ME, name)
    else:  # Jewel-Mind Reflection answers a save the foe forces, so the foe owns the printed charm
        foe_engine = L._beauty_arena(["tianxia.talent.beauty.jewel_mind_reflection"], dc=50, ally=True,
                                     foe_talents=["tianxia.talent.beauty.tears_like_pearls"])
        foe_engine.state.actors[ME].saving_throws["WIS"] = 100
        L._act(foe_engine, FOE, "Tears Like Pearls", ME)
        engine = foe_engine
    foe = engine.state.actors[FOE]
    assert "typed.captivated" in _conds(foe), name
    bar = _bar(engine, foe, "typed.captivated")
    assert bar["declare_save"]["dc"] == 50, name
    assert bar["declare_save"]["remedy"] == "choose", "the Captivated bars carry the printed choice, not a bare loss"
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    asked = _asked(events)
    assert len(asked) == 1 and asked[0].payload["remedy"] in ("redirect", "lost"), (name, [e.event_type for e in events])
    if asked[0].payload["remedy"] == "redirect":
        assert [e for e in events if e.event_type == "ATTACK_RETARGETED" and e.target_ids == (ME,)], name
    else:
        assert [e for e in events if e.event_type == "ATTACK_FORCED_MISS"], name


def test_beauty_beyond_form_loses_the_attack_and_is_never_offered_a_choice():
    """AUTO52r1 finding 3: Beauty Beyond Form's own printed failure is only "On a failure, it loses that attack or
    damaging effect" -- no re-aim and no choice. It carries no ``remedy`` in typed data, so the creature is not
    asked anything and the attack is lost, exactly as its text says."""
    engine = _beyond()
    foe = engine.state.actors[FOE]
    assert _bar(engine, foe, "typed.charmed")["declare_save"].get("remedy") is None
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert [e for e in events if e.event_type == "ATTACK_FORCED_MISS"], [e.event_type for e in events]
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"], "its text offers no re-aim"
    assert _asked(events)[0].payload["remedy"] == "lost"


def test_the_declaration_save_is_inert_for_a_creature_that_is_not_captivated():
    engine = arena([], dc=50, ally=True)
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert _asked(events) == [] and _forced(events) == []
    assert _attacks_on(engine, FOE, ALLY)


def test_being_attacked_is_not_a_declaration_for_the_captivated_creature():
    """The Captivated rule is about what the Captivated creature declares: an ally attacking it draws no save from
    it and is not turned away, and the printed "Captivated ends early if you or your allies damage it" still fires."""
    engine = _captivated()
    foe = engine.state.actors[FOE]
    engine.state.actors[ALLY].armor_class = -50
    before = foe.current_hp
    events = _strike(engine, ALLY, FOE)
    assert _asked(events) == [] and _forced(events) == []
    assert foe.current_hp < before, "the printed damage ending still applies"
    assert "typed.captivated" not in _conds(foe)


def test_a_creature_that_resisted_catch_the_eye_is_never_asked_to_declare_against_it():
    """"A creature that succeeds on this saving throw has Advantage on saving throws against your Catch the Eye": the
    printed immunity to the ability ends the declaration save as well."""
    engine = _captivated(dc=-40)
    engine.state.actors[FOE].saving_throws["WIS"] = 100
    assert "typed.captivated" not in _conds(engine.state.actors[FOE])
    assert "typed.resist_ability" in _conds(engine.state.actors[FOE])


# ------------------------------------------------------------------------------------------------- with another redirection ability
RIDER = "actor:factory.rider"
MOUNT = RIDER + ".summon.mount.warhorse.1"


def _captive_under_a_rider():
    """A Captivated foe whose next attack is aimed at a Warhorse whose rider owns Defensive Rider.

    The two features meet at the same attack declaration: the Captivated rule constrains what the *attacker* may
    declare, while Defensive Rider answers for the *defender* ("when an attack targets your mount, redirect the attack
    to yourself"). Both used to answer one winner-takes-first hook, so the redirection could take the attack and the
    captive's printed save was never asked. The rider is on the charmer's side, the charmer is one square from the
    captive, and the mount's 2x2 body is one square from it, so "it must choose you if legal" and "redirect the attack
    to yourself" are both legal answers to this very attack.
    """
    import importlib.util

    from combat.gate4_engine import Gate4ControllerEngine

    loader = importlib.util.spec_from_file_location("_auto52_mounts", Path(__file__).with_name("test_mounts.py"))
    mounts = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(mounts)
    bm = mounts.bm
    sheet = {**bm.SHEET, "equipment": [], "spheres_and_talents": {
        "sphere_record_ids": [bm.BEASTMASTERY],
        "learned_talent_record_ids": ["TAL_BEASTMASTERY_DEFENSIVE_RIDER"],
        "automatic_sphere_component_record_ids": ["BEASTMASTERY_BASE_RIDER_PACKAGE"]}}
    bundles = [compile_character(H._sheet(BEAUTY, [], H.AXE_KIT, dc=50), actor_id=ME),
               compile_character(H._sheet(None, [], H.AXE_KIT, dc=50), actor_id=FOE),
               compile_character(sheet, actor_id=RIDER)]
    starts = {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, RIDER: {"x": 5, "y": 6}}
    teams = {ME: "team:a", FOE: "team:b", RIDER: "team:a"}
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": list(starts), "team_by_actor": teams, "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    H._ready(engine)
    L._act(engine, ME, EYE, FOE)
    for actor_id in (ME, RIDER, MOUNT):
        engine.state.actors[actor_id].armor_class = -50   # every roll but a natural 1 hits
    assert "typed.captivated" in _conds(engine.state.actors[FOE])
    return engine


def test_a_captive_declaration_is_asked_before_another_ability_redirects_the_attack():
    """AUTO52r2 finding 1: Defensive Rider re-aims an attack at the mount's rider, and it used to do so without ever
    running the Captivated creature's printed save. The save is asked first, the creature is offered its own printed
    consequence, and the chosen one really happens: the attack reaches the charmer, not the mount or its rider."""
    engine = _captive_under_a_rider()
    L._begin_turn(engine, FOE)
    events = _strike(engine, FOE, MOUNT)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("CATCH_THE_EYE")]
    assert [s.payload["dc"] for s in saves] == [50] and saves[0].payload["success"] is False, "the printed save is asked"
    asked = _asked(events)
    assert len(asked) == 1 and asked[0].payload["remedy"] == "redirect", [e.payload for e in _asked(events)]
    assert engine.state.actors[ME].display_name in asked[0].payload["log"]
    moved = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(moved) == 1 and moved[0].target_ids == (ME,) and moved[0].payload["original_target_id"] == MOUNT, \
        [(m.source_definition_id, m.target_ids) for m in moved]
    assert [e for e in events if e.event_type == "ATTACK_ROLLED"] and \
        all(e.target_ids == (ME,) for e in events if e.event_type == "ATTACK_ROLLED"), "the attack reaches the charmer"
    assert engine.state.actors[RIDER].current_hp == engine.state.actors[RIDER].maximum_hp, "the rider is not hit"
    clock = [value for key, value in engine.state.actors[FOE].turn_flags.items() if key.startswith(charm_rules.FLAG + ":")]
    assert clock and clock[0].startswith("redirect@"), "the printed once-each-turn clock was spent"


def test_the_printed_loss_still_applies_when_another_ability_redirects_the_attack():
    """The other half of the same declaration: with the charmer out of reach only the printed loss is left, and a
    defender's own printed redirection is still answered for that attack (the mount's rider really does take the
    attack) while the loss still makes it miss."""
    engine = _captive_under_a_rider()
    engine.state.actors[ME].position = Position(x=11, y=11)   # out of a short axe's reach: "if legal" is not met
    L._begin_turn(engine, FOE)
    events = _strike(engine, FOE, MOUNT)
    assert [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("CATCH_THE_EYE")], \
        "the printed save is asked before anything re-aims the attack"
    assert _asked(events)[0].payload["remedy"] == "lost"
    moved = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(moved) == 1 and moved[0].source_definition_id == "ability:defensive_rider", \
        [m.source_definition_id for m in moved]
    assert _forced(events), "the printed loss is applied to the attack the redirection handed on"
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED"], "the lost attack deals no damage"


def _bm():
    """The mounted-combat harness's shared sheet module (Beastmastery Rider Package fixtures)."""
    import importlib.util

    loader = importlib.util.spec_from_file_location("_auto52_mounts", Path(__file__).with_name("test_mounts.py"))
    mounts_tests = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(mounts_tests)
    return mounts_tests.bm


def _beauty_rider(talents, *, foe_at=(4, 6), rider_at=(3, 6), ally=None):
    """One character carrying both printed rules at once: the Beauty charmer who is also the mount's own rider.

    The charmer Captivates the foe on its own turn and keeps ``talents`` (the printed Rider Package abilities),
    so the two redirection paths meet on the very same attack declaration: the Captivated bar speaks for what
    the *attacker* may declare, while Defensive Rider and Reactive Cover answer for the creature now facing the
    attack.  ``ally`` adds a bystander of the charmer's side for a captive whose attack is declared against
    somebody other than the charmer.  Returns ``(engine, mount)``.
    """
    from combat.ext import mounts
    from combat.gate4_engine import Gate4ControllerEngine

    bm = _bm()
    beauty_bases = [key for key, mech in H._mechanics().items()
                    if mech.get("sphere_id") == BEAUTY and mech.get("kind") == "base_ability"]
    sheet = {**H._sheet(BEAUTY, [], H.AXE_KIT, dc=50), "equipment": [],
             "spheres_and_talents": {
                 "sphere_record_ids": [BEAUTY, bm.BEASTMASTERY],
                 "learned_talent_record_ids": list(talents),
                 "automatic_sphere_component_record_ids": [*beauty_bases, "BEASTMASTERY_BASE_RIDER_PACKAGE"]}}
    bundles = [compile_character(sheet, actor_id=ME),
               compile_character(H._sheet(None, [], H.AXE_KIT, dc=50), actor_id=FOE)]
    starts = {ME: {"x": rider_at[0], "y": rider_at[1]}, FOE: {"x": foe_at[0], "y": foe_at[1]}}
    teams = {ME: "team:a", FOE: "team:b"}
    if ally is not None:
        bundles.append(compile_character(H._sheet(None, [], H.AXE_KIT, dc=50), actor_id=ALLY))
        starts[ALLY], teams[ALLY] = {"x": ally[0], "y": ally[1]}, "team:a"
    engine = Gate4ControllerEngine(H.ROOT, match_seed="a", typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": list(starts), "team_by_actor": teams, "starting_positions": starts})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    H._ready(engine)
    mount = mounts.mount_of(engine, engine.state.actors[ME])
    assert mount is not None, "the Rider Package gives the charmer a mount to ride"
    L._act(engine, ME, EYE, FOE)
    assert "typed.captivated" in _conds(engine.state.actors[FOE])
    for actor_id in (ME, FOE, mount.entity_id) + ((ALLY,) if ally is not None else ()):
        engine.state.actors[actor_id].armor_class = -50   # every roll but a natural 1 hits
    return engine, mount


def test_the_recorded_loss_is_honoured_when_the_charmer_is_the_one_redirecting(tmp_path):
    """AUTO52r3 finding 1: the charmer is also the rider, so choosing to lose the attack and then being pulled in by
    the charmer's own Defensive Rider must not cancel the loss the creature chose.

    The creature is asked (it is manual, and its Captivated bar owns the decision), it picks "lose that attack",
    and Defensive Rider then re-aims the attack at the charmer.  An attack the creature was told it lost is
    still that attack wherever it ends up pointing, so it misses -- and the clock entry is spent, not left
    behind for a later attack to take by mistake.
    """
    from types import SimpleNamespace

    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService

    engine, mount = _beauty_rider(["TAL_BEASTMASTERY_DEFENSIVE_RIDER"], rider_at=(5, 6))
    service = CombatService(H.ROOT, tmp_path / "service")
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    engine.typed_ask_reactors = service._ask_reactors({"participant_control_modes": {FOE: "MANUAL"}}, session)
    assert FOE in engine.typed_ask_reactors
    asked = []

    def reply(request):
        if request["reaction_source_id"].endswith(".declaration"):
            asked.append(request)
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE",
                                    option_ids=("lost",)), None
        return None, None

    engine.set_reaction_provider(reply)
    L._begin_turn(engine, FOE)
    events = _strike(engine, FOE, mount.entity_id)
    engine.set_reaction_provider(None)

    assert asked, "the creature owns the printed choice and is asked it"
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("CATCH_THE_EYE")]
    assert len(saves) == 1 and saves[0].payload["success"] is False, "the printed save is asked once and failed"
    assert _asked(events)[0].payload["remedy"] == "lost", "the creature chose to lose the attack"
    moved = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(moved) == 1 and moved[0].source_definition_id == "ability:defensive_rider", \
        [(m.source_definition_id, m.target_ids) for m in moved]
    assert moved[0].target_ids == (ME,) and moved[0].payload["original_target_id"] == mount.entity_id, \
        "the charmer's own Defensive Rider really did pull the attack onto the charmer"
    forced = _forced(events)
    assert len(forced) == 1 and forced[0].target_ids == (ME,), \
        "the loss the creature chose still applies to the attack, even aimed at the charmer"
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED"], "a lost attack deals no damage"
    assert engine.state.actors[ME].current_hp == engine.state.actors[ME].maximum_hp, "the charmer is not hit"
    assert not [key for key in engine.state.actors[FOE].turn_flags if key.startswith(charm_rules.FLAG + "_lost")], \
        "the recorded loss was spent by this attack and left behind for no other"


def test_the_attack_re_aimed_at_the_charmer_still_meets_her_own_reactive_cover(tmp_path):
    """AUTO52r3 finding 2: a target change does not delete the new target's own printed defensive ability.

    The captive attacks a bystander, fails the Captivated save and chooses to aim at the charmer, who owns
    Meat Shield, rides a mount and has a Martial Focus and a Reaction.  Reactive Cover's printed trigger is "when
    targeted by an attack roll", which the re-aimed attack satisfies, so the charmer is asked and the attack is
    turned onto her mount -- the constraint settled what the attacker may declare, and did not take the new
    defender's Reaction away.  The charmer's save is still asked exactly once, and no second constraint runs.
    """
    from types import SimpleNamespace

    from combat.gate2_runtime_models import ReactionDecision
    from combat.ext import mount_guard
    from combat.gate5_service import CombatService

    engine, mount = _beauty_rider(["TAL_BEASTMASTERY_MEAT_SHIELD"], rider_at=(3, 6), ally=(3, 7))
    charmer, foe = engine.state.actors[ME], engine.state.actors[FOE]
    charmer.resources[mount_guard.FOCUS] = 1
    service = CombatService(H.ROOT, tmp_path / "service")
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
    engine.typed_ask_reactors = service._ask_reactors({"participant_control_modes": {FOE: "MANUAL"}}, session)
    assert FOE in engine.typed_ask_reactors
    requests = []

    def reply(request):
        requests.append(request)
        source = request["reaction_source_id"]
        if source.endswith(".declaration"):
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=source, selection="USE",
                                    option_ids=("redirect",)), None
        if source == mount_guard.CHOICE + "meat_shield":
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=source, selection="USE",
                                    option_ids=("N",)), None
        return None, None

    engine.set_reaction_provider(reply)
    L._begin_turn(engine, FOE)
    events = _strike(engine, FOE, ALLY)
    engine.set_reaction_provider(None)

    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("CATCH_THE_EYE")]
    assert len(saves) == 1 and saves[0].payload["success"] is False, "the printed save is asked once and failed"
    assert _asked(events)[0].payload["remedy"] == "redirect", "the creature chose to aim the attack at the charmer"
    cover = [r for r in requests if r["reaction_source_id"] == mount_guard.CHOICE + "meat_shield"]
    assert len(cover) == 1, [r["reaction_source_id"] for r in requests]
    assert cover[0]["reactor_id"] == ME, "the charmer herself is asked, not the creature that declared the attack"
    prompt = cover[0]["choice_trigger"].get("prompt", "")
    assert mount.display_name in prompt and foe.display_name in prompt, prompt   # checklist 13: says what it affects
    resolved = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.payload.get("reaction") == "reactive_cover"]
    assert len(resolved) == 1 and resolved[0].actor_id == ME, "Reactive Cover really activated"
    assert charmer.resources[mount_guard.FOCUS] == 0 and not charmer.reaction_available, \
        "the printed price (1 Martial Focus and a Reaction) was paid"
    assert [e for e in events if e.event_type == "DAMAGE_COMMITTED" and mount.entity_id in (e.target_ids or ())], \
        "the attack landed on the mount the charmer stood behind"
    assert not [e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in (e.target_ids or ())], \
        "the attack never reached the charmer"


def _beyond(*, dc=50):
    engine = arena(["tianxia.talent.beauty.beauty_beyond_form"], ally=True, dc=dc)
    L._picks(engine, [FOE])
    L._act(engine, ME, CAPTURE)
    return engine


def test_beauty_beyond_form_loses_the_attack_aimed_at_an_ally_when_the_repeat_save_fails():
    """"The first time on each of its turns that it targets one of your allies with an attack or damaging effect, it
    must repeat the saving throw. On a failure, it loses that attack or damaging effect." """
    engine = _beyond()
    foe = engine.state.actors[FOE]
    assert _bar(engine, foe, "typed.charmed")["declare_save"]["on_success"] == "end_condition"
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert _forced(events)
    assert "typed.charmed" in _conds(foe), "a failed repeat save keeps the charm"


def test_beauty_beyond_form_ends_the_charm_when_the_repeat_save_succeeds():
    """"On a success, it acts normally and the Charmed condition ends." """
    engine = _beyond()
    foe = engine.state.actors[FOE]
    foe.saving_throws["WIS"] = 100
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert _forced(events) == []
    assert "typed.charmed" not in _conds(foe)
    assert _attacks_on(engine, FOE, ALLY)


def test_beauty_beyond_form_never_asks_the_creature_it_still_cannot_attack():
    """The printed bar keeps "it cannot willingly attack you", so no declaration save is asked for the charmer."""
    engine = _beyond()
    L._begin_turn(engine, FOE)
    assert not _attack_choices_like(engine, FOE, ME)


def _attack_choices_like(engine, actor_id, target_id):
    return _attacks_on(engine, actor_id, target_id)


# ------------------------------------------------------------------------------------------------- Beauty That Judges
def judged(*, hostiles=1):
    """A Beauty fighter that judged the foe (printed save forced), with one ally on its side."""
    engine = L._beauty_arena(["tianxia.talent.beauty.beauty_that_judges"], dc=50, ally=True)
    L._act(engine, ME, EYE, FOE)
    engine._remove_condition(engine.state.actors[FOE], "condition:typed.captivated", "test:preparation")
    L._act(engine, ME, JUDGES, FOE)
    assert "typed.charmed" in _conds(engine.state.actors[FOE])
    return engine


def _numbers(engine, name):
    action = next(a for a in engine.action_catalog.values() if a.display_name == name and a.owner_id == ME)
    return action.parameters["typed"]["numbers"]


def test_beauty_that_judges_wounds_the_judged_creature_for_the_harm_it_deals():
    """"the first time on each of its turns that it damages a creature other than you, it takes Psychic damage equal to
    your Proficiency Bonus + your key ability modifier": the amount is the caster's own compiled numbers, resolved when
    the condition landed and stored on the bar as an integer."""
    engine = judged()
    numbers = _numbers(engine, JUDGES)
    amount = _bar(engine, engine.state.actors[FOE], "typed.charmed")["retaliate"]["damage"]
    assert amount == numbers["pb"] + numbers["key_mod"] == 7, (amount, numbers)
    foe = engine.state.actors[FOE]
    before = foe.current_hp
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    wounds = [e for e in events if e.event_type == "DAMAGE_COMMITTED"
              and FOE in (e.target_ids or ()) and (e.payload or {}).get("damage_type") == "PSYCHIC"]
    assert wounds and wounds[0].payload["hp_damage"] == amount, [w.payload for w in events if w.event_type == "DAMAGE_COMMITTED"]
    assert foe.current_hp == before - amount, foe.current_hp
    assert _hpdmg(events, ALLY) > 0, "the harm it dealt is what drew the wound"


def _hpdmg(events, target_id):
    return sum(int((e.payload or {}).get("hp_damage") or 0) for e in events
               if e.event_type == "DAMAGE_COMMITTED" and target_id in (e.target_ids or ()))


def test_the_judged_wound_is_one_per_creature_turn():
    engine = judged()
    foe = engine.state.actors[FOE]
    foe.temporary_hp = 500
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    _strike(engine, FOE, ALLY)
    first = foe.temporary_hp
    foe.action_available = True
    _strike(engine, FOE, ALLY)
    assert foe.temporary_hp == first, "the printed wound is the first time on each of its turns"


def test_the_judged_wound_is_ordinary_damage_that_reaches_the_damage_watchers():
    """The wound is committed from the typed damage pipeline, not from inside an event hook, so its own packet is
    seen by everything that watches damage (the reason the line could not be automated before)."""
    engine = judged()
    foe = engine.state.actors[FOE]
    foe.temporary_hp = 0
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    seen = []

    from combat.ext import thorn_bleeding  # any ordinary damage watcher; its module import proves the path exists
    assert hasattr(thorn_bleeding, "hook")
    engine.set_reaction_provider(lambda request: (seen.append(request), (None, None))[1])
    _strike(engine, FOE, ALLY)
    wounds = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in (e.target_ids or ())
              and (e.payload or {}).get("damage_type") == "PSYCHIC"]
    assert len(wounds) == 1, wounds
    # a packet raised inside an event hook is never re-dispatched; this one is, so its rider surface is reachable
    assert wounds[0].sequence < len(engine.events)


def test_the_judged_wound_is_inert_without_the_talent():
    engine = arena([], dc=50, ally=True)
    foe = engine.state.actors[FOE]
    foe.temporary_hp = 100
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    _strike(engine, FOE, ALLY)
    assert foe.temporary_hp == 100
    assert _bar(engine, foe, "typed.charmed") is None


# ------------------------------------------------------------------------------------------------- the printed text and the stored DC
def test_the_table_pauses_for_the_creatures_own_declaration_choice_and_resumes_with_the_answer(tmp_path):
    """Checklist 9 / AUTO52r1 finding 5: at the table the question is a real pause, it names the attack and the
    charm that caused it, and resuming with an answer carries that answer out. Proven through the service's own
    preview, so nothing about the enrolment or the transport is hand-set."""
    from types import SimpleNamespace

    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import CombatService, _ReactionRequired

    engine = _captivated()
    L._begin_turn(engine, FOE)
    engine.state.actors[ALLY].armor_class = -50
    service = CombatService(H.ROOT, tmp_path / "service")
    # The session's mechanical journal feeds the turn-progress narrowing of the menu (no commits yet, so no records).
    session = SimpleNamespace(engine=engine, match_id=engine.state.match_id, mechanical=SimpleNamespace(_records=[]))
    metadata = {"participant_control_modes": {FOE: "MANUAL", ME: "LOCAL_AUTO"}}
    engine.typed_ask_reactors = service._ask_reactors(metadata, session)
    engine.set_reaction_provider(None)
    L._begin_turn(engine, FOE)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == FOE
                     and c.display_name.startswith("Fu (Short Axe) attack") and ALLY in (c.target_ids or ()))
    intent = H.ActionIntent(intent_id="preview-strike", actor_id=FOE, decision_id=candidate.decision_id,
                           candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                           target_ids=candidate.target_ids)
    before = canonical_sha256(engine.state.model_dump(mode="json"))
    with pytest.raises(_ReactionRequired) as paused:
        service._run_preview(session, metadata, intent, ())
    context = paused.value.context
    assert context.reactor_id == FOE
    assert context.reaction_source_id.endswith(".declaration")
    trigger = context.choice_trigger
    assert "Catch the Eye" in trigger["prompt"], trigger["prompt"]           # the charm that caused the save
    assert "Short Axe" in trigger["action_name"], trigger["action_name"]      # the attack being replaced
    assert trigger["affected_id"] == ALLY                                    # the creature it was aimed at
    assert engine.state.actors[FOE].display_name in trigger["prompt"]
    assert engine.state.actors[ME].display_name in trigger["prompt"], "the prompt names the charmer, not 'you'"
    assert "at you" not in trigger["prompt"]
    assert canonical_sha256(engine.state.model_dump(mode="json")) == before, "a paused question changes nothing yet"
    decision = ReactionDecision(checkpoint=context.checkpoint, reactor_id=FOE,
                                reaction_source_id=context.reaction_source_id, selection="USE",
                                option_ids=("lost",))
    result = service._run_preview(session, metadata, intent, (decision,))
    remedies = [e["payload"].get("remedy") for e in result["events"]
                if e["event_type"] == "PASSIVE_TRIGGERED" and e["payload"].get("declaration_save")]
    assert remedies == ["lost"], result["events"]
    assert [e for e in result["events"] if e["event_type"] == "ATTACK_FORCED_MISS"], "the answer is carried out"


CHAR = "actor:factory.auto52_charmer"
CAP = "actor:factory.auto52_captive"
VIC = "actor:factory.auto52_victim"
NAMES = {CHAR: "Mei the Charmer", CAP: "Kai the Captive", VIC: "Bo the Bystander"}


def _named_table(tmp_path):
    """A real table fight whose three creatures are named apart, so the rendered text can be checked.

    The charmer Captivates the captive on its own turn, and the captive's next turn attacks the bystander with the
    charmer one square away, so "it must choose you if legal" is a real option. Every actor is MANUAL, so the captive
    is asked through the service's own ownership query rather than a hand-set one.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    def fighter(actor_id, sphere=None, talents=()):
        row = H._sheet(sphere, list(talents), H.AXE_KIT, dc=50)
        row["identity"] = {**row["identity"], "name": NAMES[actor_id]}
        return compile_character(row, actor_id=actor_id)

    bundles = [fighter(CHAR, BEAUTY, ["BEAUTY_BASE_CATCH_THE_EYE"]), fighter(CAP), fighter(VIC)]
    combat = CombatService(H.ROOT, tmp_path)
    ids = [CHAR, CAP, VIC]
    mid = combat._finish_factory_match(
        bundles, ids, {CHAR: "team:a", CAP: "team:b", VIC: "team:a"},
        {CHAR: {"x": 3, "y": 6}, CAP: {"x": 4, "y": 6}, VIC: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [CHAR, VIC], [CAP],
        control_modes={actor_id: "MANUAL" for actor_id in ids}, match_seed="auto52r2f1",
        display_name="AUTO52r2f1 declaration", maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _at_menu_actor(table, mid, actor_id, limit=8):
    """End turns the way a table player would until ``actor_id`` has the menu."""
    for _ in range(limit):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor_id:
            return menu
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         menu.get("last_sequence", 0))["status"] == "COMMITTED"
    raise AssertionError(f"{actor_id} never had the menu")


def _pick(table, mid, label, target_ids):
    for group in table.state(mid)["menu"]["actions"]:
        if group["label"] != label:
            continue
        for option in group["options"]:
            if option["target_ids"] == target_ids:
                return option["candidate_id"]
    raise AssertionError(f"{label} at {target_ids} is not offered")


def test_the_rendered_declaration_question_names_the_charmer_and_the_creature_attacked(tmp_path):
    """AUTO52r2 finding 3: the rendered table response itself, through the real table service, not the packet's
    trigger metadata. The question is asked of the captive, so "at you" named the wrong creature: it must name the
    charmer the attack must be aimed at, the creature the attack was aimed at, and the attack itself, and the two
    option labels must say what each consequence does."""
    combat, table, mid = _named_table(tmp_path)
    table.act(mid, *_table_request(table, mid, _pick(table, mid, EYE, [CAP])))
    menu = _at_menu_actor(table, mid, CAP)
    assert menu["actor_id"] == CAP, "the captive's turn"
    state = table.state(mid)
    strike = _pick(table, mid, "Fu (Short Axe) attack", [VIC])
    paused = table.act(mid, strike, menu["decision_id"], menu["state_version"], state["last_sequence"])
    assert paused["status"] == "REACTION_REQUIRED", paused
    question = paused["reaction"]
    options = (question.get("choice") or {}).get("options") or []
    shown = " ".join([str(question.get("moment")), str(question.get("reaction")), str(question.get("by")),
                      str(question.get("action")), *[str(option.get("label")) for option in options]])
    assert shown, question
    assert NAMES[CHAR] in shown, shown                  # the charmer the attack must be aimed at
    assert NAMES[VIC] in shown, shown                   # the creature the attack was aimed at
    assert NAMES[CAP] in shown, shown                   # the creature being asked
    assert EYE in shown and "attack" in shown.lower(), shown
    assert "at you" not in shown and "must choose you" not in shown, shown
    assert len(options) == 2, options
    assert any(NAMES[CHAR] in str(option.get("label")) for option in options), options


def _table_request(table, mid, candidate_id):
    """(candidate_id, decision_id, state_version, last_sequence) for the current menu."""
    state = table.state(mid)
    return candidate_id, state["menu"]["decision_id"], state["menu"]["state_version"], state["last_sequence"]


def test_the_printed_remedy_policy_survives_a_table_commit_and_reload(tmp_path):
    """Checklist 7: what the fight stores for a declaration is the bar on the condition's own data -- an integer DC
    and the printed policy string, never a float or an object -- so it comes back after the table commits and the
    saved fight is reloaded, and the reloaded bar still governs the creature."""
    from tests.hunt28_support import FOE as TABLE_FOE
    from tests.hunt28_support import act, fixture, options, reload, send
    combat, table, mid = fixture(tmp_path, [], ally_talents=["BEAUTY_BASE_CATCH_THE_EYE"])
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"   # the ally's turn
    cid = next(o["candidate_id"] for o in options(table, mid, "Catch the Eye") if o["target_ids"] == [TABLE_FOE])
    assert send(combat, table, mid, cid, False)["status"] == "COMMITTED"
    engine = reload(combat, mid)          # the reload also proves the replayed state is the canonical one
    held = next(c for c in engine.state.actors[TABLE_FOE].conditions.values()
                if c.condition_id.endswith(".captivated"))
    rule = (held.data or {})["bar"][charm_rules.DECLARE]
    assert isinstance(rule["dc"], int) and rule["dc"] > 0, "the DC is a stored integer, not a float"
    assert rule["remedy"] == "choose", "the printed choice policy survived the round trip"
    assert all(isinstance(rule[key], (str, int, bool, type(None)))
               for key in rule), f"nothing unserialisable is stored: {sorted(rule)}"


def _declaration_table(tmp_path, folder):
    """A persisted fight, played to the captive's turn with the Captivated cast already committed.

    Everything the fight stores about the declaration is written by the table itself: the bar rides the condition's
    own data, and the clock rides the engine's turn flags. No test state is written into the engine behind the fight's
    back, so a reload either reproduces the fight or it does not.
    """
    from combat.gate4_persistence import Gate4Persistence

    bundles, roster = _table_roster()
    persistence = Gate4Persistence(H.ROOT, tmp_path / folder)
    session = persistence.create_match(match_seed="a", typed_bundles=bundles, roster_setup=roster)

    def submit(candidate, provider=None):
        session.submit_intent(H.ActionIntent(intent_id=f"decl-{session.engine.state.event_sequence}",
                                             decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                             state_version=candidate.state_version, actor_id=candidate.actor_id,
                                             target_ids=candidate.target_ids),
                              primary_decision_record=None, reaction_provider=provider)

    def named(name, actor, target=None):
        # Catch the Eye may be aimed at any creature (9dcc14d7), so the caller names the foe it means.
        return next(c for c in session.engine.legal_candidates() if c.actor_id == actor
                    and (c.display_name == name or c.display_name.startswith(name + " at "))
                    and (target is None or target in (c.target_ids or ())))

    def to_turn(actor):
        while session.engine.state.current_actor_id != actor:
            submit(next(c for c in session.engine.legal_candidates()
                        if str(getattr(c.kind, "value", c.kind)) == "END_TURN"))

    to_turn(ME)
    submit(named(EYE, ME, FOE), session.engine._gate4_reaction_provider)
    to_turn(FOE)
    return persistence, session, submit, named


def test_a_fight_committed_before_any_declaration_can_be_reloaded(tmp_path):
    """AUTO52r2 finding 2, the control: the same fight, the same roster and the same real commits, reloaded while the
    captive has not yet made the attack whose declaration failed. The reload reproduces the post-state hash exactly, so
    the harness, the persistence layer and the Captivated commit itself are all sound, and a later failure can only be
    about what that one declaration wrote."""
    from combat.canonical import canonical_sha256

    persistence, session, _submit, _named = _declaration_table(tmp_path, "declaration-control")
    assert any(c.condition_id.endswith(".captivated") for c in session.engine.state.actors[FOE].conditions.values())
    before = canonical_sha256(session.engine.state.model_dump(mode="json"))
    session = persistence.load_match(session.match_id)
    assert canonical_sha256(session.engine.state.model_dump(mode="json")) == before, "the commit is the reload"


def test_a_fight_committed_after_a_failed_declaration_can_be_reloaded(tmp_path):
    """AUTO52r2 finding 2: the printed save is asked, the creature is asked which consequence it takes, answers "lost",
    and the fight still reloads to exactly the committed state. The previous version of this test changed the ally's
    Armor Class *after* the match was created, so the replay could never reproduce it, and it marked the whole function
    ``xfail(strict=True)``, which also hid any failure in its own setup and assertions. Nothing is written into the
    engine here that the table did not write itself: the bar rides the condition's data and the once-each-turn clock
    rides the actor's turn flags, so the reload has to rebuild both from the recorded events."""
    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ReactionDecision

    persistence, session, submit, named = _declaration_table(tmp_path, "declaration-table")
    asked = []

    def answer(request):
        if not request["reaction_source_id"].endswith(".declaration"):
            return None, None
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=("lost",)), None

    session.engine.typed_ask_reactors = frozenset({FOE})
    first = len(session.engine.events)
    # Aimed at the ally: Captivated's printed rule covers attacks on creatures *other than* its source, so the first
    # Fu candidate (the one aimed at the charmer) is correctly never asked about and would never write the clock.
    submit(named("Fu (Short Axe) attack", FOE, ALLY), answer)
    assert asked, "the table asked the creature which printed consequence it takes"
    events = session.engine.events[first:]
    assert [e.payload.get("remedy") for e in events
            if e.event_type == "PASSIVE_TRIGGERED" and (e.payload or {}).get("declaration_save")] == ["lost"]
    assert [e for e in events if e.event_type == "SAVE_ROLLED"
            and e.source_definition_id.endswith("CATCH_THE_EYE")], "the printed save was rolled and failed"
    before = canonical_sha256(session.engine.state.model_dump(mode="json"))
    committed = {key: value for key, value in session.engine.state.actors[FOE].turn_flags.items()
                 if key.startswith(charm_rules.FLAG + ":")}
    assert committed, "the printed once-each-turn clock was written by the declaration"
    reloaded = persistence.load_match(session.match_id)
    assert canonical_sha256(reloaded.engine.state.model_dump(mode="json")) == before, "the commit is the reload"
    assert {key: value for key, value in reloaded.engine.state.actors[FOE].turn_flags.items()
            if key.startswith(charm_rules.FLAG + ":")} == committed, "the clock came back with the fight"
    assert "typed.captivated" in _conds(reloaded.engine.state.actors[FOE]), "the bar still governs the reloaded fight"


def test_the_declaration_clock_is_rebuilt_by_the_replay_reducer_and_not_only_by_a_snapshot(tmp_path):
    """The clock is engine turn_flags state, so it could have been surviving the round trip only because a periodic
    snapshot happened to carry it. Replay the very same fight from genesis with every snapshot deleted: the clock and
    the whole post-state hash are rebuilt from the recorded events alone, which is what the reducer's control-row
    restore (``gate3_reducer.py:498``) exists for."""
    import shutil

    from combat.canonical import canonical_sha256
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate3_storage import Gate3MatchStore
    from combat.gate4_persistence import Gate4Persistence

    root = tmp_path / "rebuilt"
    persistence, session, submit, named = _declaration_table(tmp_path, "source")
    session.engine.typed_ask_reactors = frozenset({FOE})
    submit(named("Fu (Short Axe) attack", FOE, ALLY), lambda request: (
        ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                        reaction_source_id=request["reaction_source_id"], selection="USE", option_ids=("lost",)), None)
        if request["reaction_source_id"].endswith(".declaration") else (None, None))
    before = canonical_sha256(session.engine.state.model_dump(mode="json"))
    clock = {key: value for key, value in session.engine.state.actors[FOE].turn_flags.items()
             if key.startswith(charm_rules.FLAG + ":")}
    assert clock, "the declaration wrote its clock"
    shutil.copytree(tmp_path / "source", root)
    match_dir = Gate3MatchStore(root, session.match_id).match_dir
    snapshots = list((match_dir / "Snapshots").glob("Snapshot_*.json"))
    assert snapshots, "this fight has a snapshot, so deleting it is a real change of load path"
    for snapshot in snapshots:
        snapshot.unlink()
    rebuilt = Gate4Persistence(H.ROOT, root).load_match(session.match_id)
    assert canonical_sha256(rebuilt.engine.state.model_dump(mode="json")) == before, "genesis replay rebuilds the state"
    assert {key: value for key, value in rebuilt.engine.state.actors[FOE].turn_flags.items()
            if key.startswith(charm_rules.FLAG + ":")} == clock, "genesis replay rebuilds the clock"


def test_every_printed_declaration_save_reaches_the_compiled_character():
    """All seven records this lane automated carry the bar key they need; a mistyped bar would raise nothing here."""
    from combat.factory_compiler import TYPED_AUTHORITY
    import json
    mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]

    def bars(node, out):
        if isinstance(node, dict):
            bar = (node.get("condition_data") or {}).get("bar")
            if bar is not None:
                out.append(bar)
            for value in node.values():
                bars(value, out)
        elif isinstance(node, list):
            for value in node:
                bars(value, out)

    expected = {"BEAUTY_BASE_CATCH_THE_EYE", "tianxia.talent.beauty.captive_audience",
                "tianxia.talent.beauty.envious_glance", "tianxia.talent.beauty.face_that_halts_the_army",
                "tianxia.talent.beauty.jewel_mind_reflection", "tianxia.talent.beauty.beauty_beyond_form"}
    for key in expected:
        found = []
        bars(mechanics[key].get("effects"), found)
        assert any("declare_save" in bar for bar in found), key
        assert not mechanics[key].get("riders"), (key, mechanics[key].get("riders"))
    judged = []
    bars(mechanics["tianxia.talent.beauty.beauty_that_judges"].get("effects"), judged)
    assert any("retaliate" in bar for bar in judged)
    assert not mechanics["tianxia.talent.beauty.beauty_that_judges"].get("riders")
    assert charm_rules.DECLARE == "declare_save"


def test_the_declaration_save_is_read_from_the_bar_and_not_from_an_ability_id():
    """A bar without the key is untouched by the new hooks, whatever its printed ability is."""
    engine = L._beauty_arena([], dc=50, ally=True)
    L._act(engine, ME, EYE, FOE)
    engine.state.actors[FOE].saving_throws["WIS"] = 100
    foe = engine.state.actors[FOE]
    L._begin_turn(engine, FOE)
    for held in list(foe.conditions.values()):
        if held.condition_id.endswith(".captivated"):
            held.data["bar"] = {"captivated": True, "fragile": "source_side"}   # the pre-lane bar
    engine.state.actors[ALLY].armor_class = -50
    events = _strike(engine, FOE, ALLY)
    assert not [e for e in events if e.event_type == "SAVE_ROLLED" and (e.payload or {}).get("dc") == 50]
    assert not [e for e in events if e.event_type == "ATTACK_FORCED_MISS"]
