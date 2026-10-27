"""Real sheets -> compiler -> legal actions -> engine, compiled from the current typed authority."""
import json

import pytest

import combat.factory_compiler as compiler
from combat.factory_compiler import compile_character
from combat.typed_executor import Context, block_healing, block_save
from combat.ext.mind_hidden_eye import FOCUS, mark_analyzed
from combat.ext.riders14_eye import ATTEMPTS, POISON, RIVAL
from test_auto_lane1 import ME, AN, ROOT, _engine, _payloads, _ready, _sheet, _use

PREFIX = "TAL_THE_HIDDEN_EYE_"
BASE = PREFIX + "BASE_SPHERE_FEATURES"
# Every lane-14 mechanic the riders in this module and test_r14_review_fixes.py compile from.
LANE14_MECHANICS = tuple(PREFIX + name for name in (
    "ADROIT_FOCUS", "ASSAULT_ANALYSIS", "BASE_SPHERE_FEATURES", "COOPERATIVE_PERCEPTION",
    "COURT_OF_THE_HIDDEN_EYE", "DEADLY_STRIKE", "DISCERN_ILLUSIONS", "EXPLOIT_WEAKNESS",
    "FAR_SIGHT_ANALYSIS", "FOLKLORIST", "GREATER_STALKER", "HIDDEN_FOCUS", "INIMICAL_GAZE",
    "MODIFY_CHARACTERISTICS", "PERSISTENT_ANALYSIS", "PROGNOSIS", "RAPID_ANALYSIS",
    "SABOTAGE_MOBILITY", "SHIFTY_POISONER", "SOVEREIGN_HIDDEN_EYE_INCARNATION", "THOROUGH_ANALYSIS",
    "THOUSAND_LANTERN_SWEEP", "UNCANNY_STALKER", "VANISH_BETWEEN_HEARTBEATS", "WORTHY_OPPONENT"))


def test_lane14_mechanics_are_bound_in_the_current_typed_authority():
    # Replaces the old R14_OLD run against git history (793a9a89, before lane 14 existed). That run proved the riders
    # need typed rows the base authority lacks; asserting the rows exist with their kind and sphere proves the same
    # dependency here, and the riders below prove the engine reads them.
    mechanics = json.loads(compiler.TYPED_AUTHORITY.read_text())["mechanics"]
    for mechanic_id in LANE14_MECHANICS:
        entry = mechanics.get(mechanic_id)
        assert entry is not None, mechanic_id
        assert entry["kind"] in {"talent", "base_ability"}, mechanic_id
        assert entry["sphere_id"] == "tianxia.sphere.the_hidden_eye", mechanic_id


def bundle(*talents, cl=1, scores=None, actor_id=ME):
    sheet = _sheet(BASE, cl=cl, dc=50)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = list(talents)
    # Both weapons start readied, as this character's saved loadout says: the starting loadout
    # (combat/starting_loadout.py) keeps only a primary plus a Light/Paired or explicitly chosen
    # companion, and these regressions attack with the Fei Biao on the first turn.
    sheet["equipment"] = [{"starting_kit": {"items": [
        {"item_id": "tianxia.mortal.weapon.fei_biao", "name": "Fei Biao", "quantity": 1, "wielded": True},
        {"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1, "wielded": True}]}}]
    if scores:
        sheet["ability_scores_and_statistics"]["abilities"] = [
            {"ability": k, "score": 10 + 2 * v, "modifier": v} for k, v in scores.items()]
    return compile_character(sheet, actor_id=actor_id)


def attack(engine, name="Fei Biao (Flying Dart) attack"):
    _ready(engine)
    return _use(engine, name, AN)


def mark(engine):
    mark_analyzed(engine, engine.state.actors[ME], engine.state.actors[AN], "test:analyzed")


def test_unaffected_actor_gets_no_eye_attack_bonus_or_mutation():
    from combat import ext

    engine = _engine(bundle())
    actor = engine.state.actors[AN]
    action = next(iter(engine.action_catalog.values()))
    ctx = Context(engine, actor, action, None, {}, [actor], actor, {})
    before = engine.export().canonical_state_sha256, len(engine.events)
    assert ext.run("attack_bonus", ctx, actor) == []
    assert (engine.export().canonical_state_sha256, len(engine.events)) == before


@pytest.mark.parametrize("name", ["Armor Class", "Walking Speed", "CON saving throw", "PIERCING Resistance", "blindsight Sense"])
def test_modify_characteristics_critical_chooses_one_learned_stat_and_spends_focus(name):
    from combat.ext.riders14_research import KNOWN, MODIFIED
    from test_auto_lane4 import _script

    e = _engine(bundle(PREFIX + "MODIFY_CHARACTERISTICS"))
    mark(e)
    me, foe = e.state.actors[ME], e.state.actors[AN]
    if name.endswith(" Sense"):
        e._apply_condition(foe, "condition:typed.sense", "test:sense", AN, expires_on="UNTIL_REMOVED",
                           data={"sense": "blindsight", "range_ft": 30})
    e._apply_condition(me, KNOWN, "test:learned", ME, expires_on="UNTIL_REMOVED",
                       data={"target_id": AN, "name": name, "value": 10})
    # Native Modify Characteristics has one optional prompt. Explicitly choose
    # the learned fact rather than relying on the old rider's automatic spend.
    from combat.gate2_runtime_models import ReactionDecision
    def choose(request):
        selected = request["reaction_source_id"] == "choice:needle.modify_maximum"
        return ReactionDecision(**{k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")},
                                selection="USE" if selected else "DECLINE",
                                option_ids=(name,) if selected else ()), None
    e.set_reaction_provider(choose)
    _script(e, [20, 1, 1])
    events = attack(e)
    assert _payloads(events, "DAMAGE_ROLLED")[0]["critical"]
    assert me.resources[FOCUS] == 0
    if name == "Armor Class":
        assert [m.value for m in foe.modifiers.values() if m.target_field == "armor_class"] == [-2]
    elif name == "Walking Speed":
        assert e._effective_speed(foe) == 20
    elif name == "CON saving throw":
        assert any(c.condition_id == MODIFIED for c in foe.conditions.values())
        action = next(iter(e.action_catalog.values()))
        before = len(e.events)
        block_save(Context(e, me, action, None, {"numbers": {"save_dc": 50}}, [foe], foe),
                   {"type": "save", "ability": "con", "on_fail": [], "on_success": []})
        # Rider lane C14: the penalty now rides the all-source save_bonus seam (the roll's modifier, -2), so typed and legacy
        # saves agree; it used to be the typed save hook's DC shift (DC 52), the same odds.
        rolled = _payloads(e.events[before:], "SAVE_ROLLED")[0]
        assert rolled["dc"] == 50 and rolled["modifier"] == int(foe.saving_throws["CON"]) - 2
    elif name.endswith(" Resistance"):
        assert [m.value for m in foe.modifiers.values() if m.target_field == "resistance_suppressed"] == ["PIERCING"]
    else:
        from combat.senses import of

        assert of(e, foe)["blindsight"]["range_ft"] == 20
    assert not [m for m in foe.modifiers.values() if m.target_field in ("armor_class", "speed")
                and ((m.target_field == "armor_class") != (name == "Armor Class"))]


def test_analyze_records_selected_characteristics_and_thorough_adds_half_pb():
    from combat.ext.riders14_research import KNOWN

    e = _engine(bundle(PREFIX + "THOROUGH_ANALYSIS", scores={"INT": 30}))
    events = _use(e, "Analyze", AN)
    assert any(p["success"] for p in _payloads(events, "CHECK_ROLLED"))
    learned = [c for c in e.state.actors[ME].conditions.values() if c.condition_id == KNOWN]
    assert len(learned) == 3
    assert [c.data["name"] for c in learned] == ["Armor Class", "Walking Speed", "STR saving throw"]


def test_folklorist_margin_and_court_add_one_characteristic_each():
    from combat.ext.riders14_research import KNOWN

    e = _engine(bundle(PREFIX + "FOLKLORIST", PREFIX + "COURT_OF_THE_HIDDEN_EYE", scores={"INT": 30}))
    _use(e, "Court of the Hidden Eye")
    _ready(e)
    _use(e, "Analyze", AN)
    assert len([c for c in e.state.actors[ME].conditions.values() if c.condition_id == KNOWN]) == 3


def test_lantern_sweep_searches_creature_and_distant_trap_with_one_roll():
    from combat.ext import placed
    from combat.gate2_runtime_models import Position
    from combat.stealth import hidden

    e = _engine(bundle(PREFIX + "THOUSAND_LANTERN_SWEEP", scores={"WIS": 30}))
    foe = e.state.actors[AN]
    e._apply_condition(foe, "condition:typed.hidden", "test:hidden", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 25})
    trap = placed.place(e, foe, source="test:trap", tag="trap", cells=Position(x=17, y=6), name="Concealed trap", numbers={"save_dc": 25})
    before = e.roller.counter
    events = _use(e, "Thousand-Lantern Sweep")
    assert e.roller.counter == before + 1
    assert hidden(foe) is None
    assert ME in placed.data(trap)["aware"]
    rolls = [p["actor"]["counter_start"] for p in _payloads(events, "CHECK_ROLLED")]
    assert len(rolls) == 3 and len(set(rolls)) == 1


def test_cooperative_perception_shares_triggering_check_within_range_and_both_senses():
    from combat.ext.eye_common import passive_perception
    from combat.gate2_runtime_models import Position

    ally = "actor:lane14.ally"
    e = _engine(bundle(PREFIX + "COOPERATIVE_PERCEPTION", scores={"WIS": 30}), allies=(bundle(actor_id=ally),))
    e._apply_condition(e.state.actors[AN], "condition:typed.hidden", "test:hidden", AN,
                       expires_on="UNTIL_REMOVED", data={"stealth_total": 25})
    events = _use(e, "Search")
    total = _payloads(events, "CHECK_ROLLED")[0]["actor"]["total"]
    assert e.state.actors[ME].resources[FOCUS] == 0
    assert passive_perception(e, e.state.actors[ally], e.state.actors[AN]) == total
    e.state.actors[ally].position = Position(x=19, y=6)
    assert passive_perception(e, e.state.actors[ally], e.state.actors[AN]) == 12


def test_uncanny_with_rapid_can_analyze_as_reaction_before_attack(monkeypatch):
    from combat.ext import needle

    e = _engine(bundle(PREFIX + "UNCANNY_STALKER", PREFIX + "RAPID_ANALYSIS", PREFIX + "PERSISTENT_ANALYSIS",
                      PREFIX + "GREATER_STALKER", scores={"INT": 30}))
    e._apply_condition(e.state.actors[ME], "condition:typed.invisible", "test:invisible", ME, expires_on="UNTIL_REMOVED")
    original = needle.ask
    def choose(*args, **kwargs):
        return ["analyze"] if args[4] == needle.CHOICE + "eye_uncanny" else original(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", choose)
    events = attack(e)
    reaction = next(i for i, x in enumerate(events) if x.event_type == "REACTION_RESOLVED" and x.source_definition_id == "reaction:eye.uncanny")
    rolled = next(i for i, x in enumerate(events) if x.event_type == "ATTACK_ROLLED")
    assert reaction < rolled
    assert not e.state.actors[ME].reaction_available and e.state.actors[ME].resources[FOCUS] == 0


def test_uncanny_entry_nested_analyze_counts_and_learns_once(monkeypatch):
    from combat.ext import needle
    from combat.ext.riders14_research import KNOWN
    from combat.gate2_runtime_models import ActionIntent
    from test_auto_lane4 import _script

    e = _engine(bundle(PREFIX + "UNCANNY_STALKER", PREFIX + "RAPID_ANALYSIS", PREFIX + "PERSISTENT_ANALYSIS",
                      PREFIX + "GREATER_STALKER", scores={"INT": 30}))
    actor = e.state.actors[ME]
    previous = sum(int(c.data["used"]) for c in actor.conditions.values() if c.condition_id == ATTEMPTS)
    e._apply_condition(actor, "condition:typed.invisible", "test:hidden", ME, expires_on="UNTIL_REMOVED")
    original = needle.ask

    def choose(*args, **kwargs):
        return ["analyze"] if args[4] == needle.CHOICE + "eye_uncanny" else original(*args, **kwargs)

    monkeypatch.setattr(needle, "ask", choose)
    candidate = e.legal_candidates()[0]
    e._active_intent = ActionIntent(intent_id="test:entry", decision_id=candidate.decision_id,
                                   candidate_id=candidate.candidate_id, actor_id=AN, state_version=candidate.state_version)
    _script(e, [19])
    e._append_event("MOVEMENT_COMMITTED", "test:entry", actor_id=AN,
                    payload={"path": [{"x": 25, "y": 6}, e.state.actors[AN].position.model_dump(mode="json")]})
    assert [c.data["used"] for c in actor.conditions.values() if c.condition_id == ATTEMPTS] == [previous + 1]
    assert len([c for c in actor.conditions.values() if c.condition_id == KNOWN]) == 1


@pytest.mark.parametrize("use", [False, True])
def test_cooperative_stealth_optional_use_consumes_exact_instance(monkeypatch, use):
    from combat.ext import needle
    from combat.ext.eye_coordination import COOP_STEALTH_TAG, cooperative_stealth_override

    ally = "actor:lane14.cooperative"
    e = _engine(bundle(), allies=(bundle(actor_id=ally),))
    recipient = e.state.actors[ally]
    for owner, total in ((AN, 20), (ME, 30)):
        e._apply_condition(recipient, COOP_STEALTH_TAG, "test:shared", owner,
                           expires_on="START_OF_SOURCE_NEXT_TURN", data={"total": total})
    monkeypatch.setattr(needle, "ask", lambda *args, **kwargs: ["shared_total"] if use else [])
    assert cooperative_stealth_override(e, recipient) == (30 if use else None)
    remaining = [c for c in recipient.conditions.values() if c.condition_id == COOP_STEALTH_TAG]
    assert {c.source_actor_id for c in remaining} == ({AN} if use else {ME, AN})


def test_inimical_gaze_analyzes_a_visible_ally_as_well_as_enemy_with_one_roll():
    from combat.ext.mind_hidden_eye import analyzed_by

    ally = "actor:lane14.ally"
    e = _engine(bundle(PREFIX + "INIMICAL_GAZE", PREFIX + "PERSISTENT_ANALYSIS", scores={"INT": 30}),
                allies=(bundle(actor_id=ally),))
    before = e.roller.counter
    events = _use(e, "Inimical Gaze")
    assert e.roller.counter == before + 1
    assert analyzed_by(e.state.actors[ally], ME)
    assert analyzed_by(e.state.actors[AN], ME)
    assert len(_payloads(events, "CHECK_ROLLED")) == 2


def test_far_sight_extends_action_and_gaze():
    from combat.ext.eye_gaze import _in_gaze

    e = _engine(bundle(PREFIX + "FAR_SIGHT_ANALYSIS", PREFIX + "INIMICAL_GAZE"))
    analyze = next(a for a in e.action_catalog.values() if a.display_name == "Analyze")
    assert analyze.range_ft == 120
    e.state.actors[AN].position = e.state.actors[AN].position.model_copy(update={"x": 19})
    assert e._distance_actor_to_actor(e.state.actors[ME], e.state.actors[AN]) > 60
    assert e.state.actors[AN] in _in_gaze(e, e.state.actors[ME])
    events = _use(e, "Analyze", AN)
    assert _payloads(events, "CHECK_ROLLED")


@pytest.mark.parametrize("persistent,limit", [(False, 1), (True, 4)])
def test_analyze_attempt_limit_includes_failed_checks(persistent, limit):
    e = _engine(bundle(*([PREFIX + "PERSISTENT_ANALYSIS"] if persistent else [])))
    for _ in range(limit):
        _ready(e)
        e._gain_resource(e.state.actors[ME], FOCUS, 1, "test:focus")
        events = _use(e, "Analyze", AN)
        assert _payloads(events, "CHECK_ROLLED")
    _ready(e)
    e._gain_resource(e.state.actors[ME], FOCUS, 1, "test:focus")
    assert not [c for c in e.legal_candidates() if c.display_name == "Analyze"]
    assert [c.data["used"] for c in e.state.actors[ME].conditions.values() if c.condition_id == ATTEMPTS] == [limit]


@pytest.mark.parametrize("analyzed,accept", [(False, True), (True, True), (True, False)])
def test_assault_analysis_replaces_ability_on_attack_and_damage_only_against_analyzed(analyzed, accept):
    """fix/hunt21 (merge 2ff7e2dd) releases each thrown dart; compare fresh fights.

    This non-Finesse, nonproficient thrown dart uses STR +1 normally.
    Assault Analysis optionally replaces it with the sphere key ability, CON +5.
    """
    from combat.gate2_runtime_models import ReactionDecision
    from test_auto_lane4 import _script

    e = _engine(bundle(PREFIX + "ASSAULT_ANALYSIS", scores={"STR": 1, "DEX": 2, "CON": 5, "INT": 0, "WIS": 0, "CHA": 0}))
    asked = []

    def answer(request):
        assault = request["reaction_source_id"] == "choice:needle.eye_assault"
        if assault:
            assert request["reactor_id"] == ME
            assert list(request["legal_option_ids"]) == ["substitute"]
            asked.append(request)
        use = assault and accept
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="USE" if use else "DECLINE",
                                option_ids=("substitute",) if use else ()), None

    e.set_reaction_provider(answer)
    if analyzed:
        mark(e)
    _script(e, [19, 19, 1])  # Adjacent ranged attack rolls twice; then one point of damage.
    before_hp = e.state.actors[AN].current_hp
    events = attack(e, "Fei Biao (Flying Dart) thrown")
    rolls = _payloads(events, "ATTACK_ROLLED")
    damage = _payloads(events, "DAMAGE_ROLLED")
    modifier = 5 if analyzed and accept else 1
    assert len(rolls) == len(damage) == 1
    assert rolls[0]["modifier"] == modifier
    assert damage[0]["expression"] == f"1d4+{modifier}"
    assert damage[0]["critical"] is False
    assert e.state.actors[AN].current_hp == before_hp - (1 + modifier)
    assert len(asked) == int(analyzed)
    # Do not restore possession just to let a test throw the same physical dart twice.
    _ready(e)
    assert not any(c.display_name == "Fei Biao (Flying Dart) thrown" for c in e.legal_candidates())


def test_greater_stalker_applies_deadly_strike_while_invisible():
    e = _engine(bundle(PREFIX + "GREATER_STALKER", PREFIX + "DEADLY_STRIKE", PREFIX + "HIDDEN_FOCUS"))
    e._apply_condition(e.state.actors[ME], "condition:typed.invisible", "test:invisible", ME, expires_on="UNTIL_REMOVED")
    events = attack(e)
    assert any("deadly_strike" in x.source_definition_id for x in events if x.event_type == "DAMAGE_COMMITTED")
    e._spend_resource(e.state.actors[ME], FOCUS, 1, "test:spent")
    _ready(e)
    _use(e, "Hidden Focus: Regain Martial Focus")
    assert e.state.actors[ME].resources[FOCUS] == 1


def test_sabotage_mobility_forces_save_once_per_round_and_reduces_speed():
    e = _engine(bundle(PREFIX + "SABOTAGE_MOBILITY"))
    mark(e)
    events = attack(e)
    assert len(_payloads(events, "SAVE_ROLLED")) == 1
    assert e._effective_speed(e.state.actors[AN]) == 20
    assert not _payloads(attack(e), "SAVE_ROLLED")


def test_prognosis_attack_prevents_healing_after_failed_save():
    e = _engine(bundle(PREFIX + "PROGNOSIS"))
    mark(e)
    assert _payloads(attack(e), "SAVE_ROLLED")
    foe = e.state.actors[AN]
    hp = foe.current_hp
    action = next(iter(e.action_catalog.values()))
    block_healing(Context(e, foe, action, None, {"numbers": {}}, [foe], foe), {"type": "healing", "flat": 10})
    assert foe.current_hp == hp


def test_shifty_poisoner_marks_before_attack_and_disadvantages_poison_save():
    e = _engine(bundle(PREFIX + "SHIFTY_POISONER"))
    e._apply_condition(e.state.actors[ME], "condition:typed.hidden", "test:hidden", ME, expires_on="UNTIL_REMOVED", data={"stealth_total": 40})
    attack(e)
    assert any(c.condition_id == POISON for c in e.state.actors[AN].conditions.values())
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    block_save(Context(e, e.state.actors[ME], action, None, {"numbers": {"save_dc": 50}}, [e.state.actors[AN]], e.state.actors[AN]),
               {"type": "save", "ability": "con", "on_fail": [{"type": "condition", "condition": "poisoned"}]})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "DISADVANTAGE"


def test_worthy_opponent_requires_successful_analysis_and_locks_living_rival():
    e = _engine(bundle(PREFIX + "WORTHY_OPPONENT", scores={a: 30 if a == "INT" else 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}))
    assert not [c for c in e.state.actors[ME].conditions.values() if c.condition_id == RIVAL]
    _use(e, "Analyze", AN)
    assert [c.data["target_id"] for c in e.state.actors[ME].conditions.values() if c.condition_id == RIVAL] == [AN]
    assert not [c for c in e.legal_candidates() if c.display_name == "Worthy Opponent: Designate rival"]


def test_analyze_chooses_one_approach_and_uses_skill_bonus():
    e = _engine(bundle())
    before = len(e.events)
    _use(e, "Analyze", AN)
    checks = [x for x in e.events[before:] if x.event_type == "CHECK_ROLLED" and x.payload.get("actor", {}).get("reason", "").startswith("CHECK:analyze:")]
    assert len(checks) == 1
    assert len([x for x in e.events[before:] if x.event_type == "DICE_ROLLED" and "analyze" in str(x.payload)]) <= 1
    assert checks[0].payload["actor"]["reason"] == "CHECK:analyze:investigation"
    assert checks[0].payload["skill"] == "Investigation"
    # The selected check starts immediately after initiative, and the following
    # action must start at its end: the old implementation secretly drew a second d20.
    next_events = attack(e)
    assert _payloads(next_events, "ATTACK_ROLLED")[0]["counter_start"] == checks[0].payload["actor"]["counter_end"]


@pytest.mark.parametrize("talent,approach,ability", [("FOLKLORIST", "history", "INT"),
    ("SOCIAL_ENGINEERING", "deception", "CHA"), ("biological_insight", "nature", "INT")])
def test_additional_approaches_use_their_actual_ability(talent, approach, ability):
    mid = "tianxia.talent.the_hidden_eye.biological_insight" if talent == "biological_insight" else PREFIX + talent
    scores = {a: 0 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    scores[ability] = 5
    if approach in ("history", "nature"):
        # Make the named skill better than Investigation using the character's skill record.
        sheet = _sheet(BASE, cl=1, dc=50)
        sheet["spheres_and_talents"]["learned_talent_record_ids"] = [mid]
        sheet["ability_scores_and_statistics"]["skills"] = [{"skill": approach.title(), "bonus": 25}]
        b = compile_character(sheet, actor_id=ME)
    else:
        b = bundle(mid, scores=scores)
    e = _engine(b)
    events = _use(e, "Analyze", AN)
    check = next(x for x in _payloads(events, "CHECK_ROLLED") if x.get("actor", {}).get("reason", "").startswith("CHECK:analyze:"))
    assert check["actor"]["reason"] == f"CHECK:analyze:{approach}"
    assert check["skill"] == approach.title()


def test_court_enables_free_bonus_analyze_and_bonus_search_only_while_active():
    e = _engine(bundle(PREFIX + "COURT_OF_THE_HIDDEN_EYE"))
    assert not [c for c in e.legal_candidates() if c.display_name.startswith("Court:")]
    _use(e, "Court of the Hidden Eye")
    _ready(e)
    focus = e.state.actors[ME].resources[FOCUS]
    assert _payloads(_use(e, "Court: Analyze", AN), "CHECK_ROLLED")
    assert e.state.actors[ME].resources[FOCUS] == focus
    assert not e.state.actors[ME].bonus_action_available
    _ready(e)
    e._apply_condition(e.state.actors[AN], "condition:typed.hidden", "test:foe", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 5})
    assert _payloads(_use(e, "Court: Search"), "CHECK_ROLLED")


def test_court_passive_perception_bonus_requires_chosen_ally_within_domain():
    from combat.ext.eye_common import passive_perception

    ally = "actor:lane14.ally"
    e = _engine(bundle(PREFIX + "COURT_OF_THE_HIDDEN_EYE"), allies=(bundle(actor_id=ally),))
    normal = passive_perception(e, e.state.actors[ally])
    _use(e, "Court of the Hidden Eye")
    assert passive_perception(e, e.state.actors[ally]) == normal + 2
    e.state.actors[ally].position = e.state.actors[ally].position.model_copy(update={"x": 19})
    assert passive_perception(e, e.state.actors[ally]) == normal


def test_sovereign_incarnation_restores_focus_and_automatically_analyzes():
    from combat.ext.riders14_eye import INCARNATION
    from combat.ext.mind_hidden_eye import analyzed_by
    from combat import senses

    e = _engine(bundle(PREFIX + "SOVEREIGN_HIDDEN_EYE_INCARNATION"))
    _use(e, "Sovereign Hidden Eye Incarnation")
    assert any(c.condition_id == INCARNATION for c in e.state.actors[ME].conditions.values())
    assert senses.of(e, e.state.actors[ME])["blindsight"]["range_ft"] == 30
    e._spend_resource(e.state.actors[ME], FOCUS, 1, "test:spent")
    _ready(e)
    e._system_start_turn()
    assert e.state.actors[ME].resources[FOCUS] == 1
    assert analyzed_by(e.state.actors[AN], ME)
    e.state.actors[AN].position = e.state.actors[AN].position.model_copy(update={"x": 12})
    e._apply_condition(e.state.actors[AN], "condition:typed.hidden", "test:foe", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 5})
    _ready(e)
    assert _payloads(_use(e, "Search"), "CHECK_ROLLED")[0]["actor"]["mode"] == "ADVANTAGE"


def test_discern_tells_cancels_enemy_advantage_without_imposing_disadvantage():
    from combat.gate2_runtime_models import ActionIntent

    defender = "actor:lane14.defender"
    e = _engine(bundle(), allies=(bundle("tianxia.talent.the_hidden_eye.discern_tells", actor_id=defender),))
    e.state.actors[defender].team_id = "team:b"
    e.state.actors[defender].armor_class = -50
    mark_analyzed(e, e.state.actors[defender], e.state.actors[ME], "test:analyzed")
    e._add_modifier(e.state.actors[ME], "test:advantage", "attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
    candidate = next(c for c in e.legal_candidates() if c.display_name == "Fei Biao (Flying Dart) attack" and defender in c.target_ids)
    before = len(e.events)
    e.execute_intent(ActionIntent(intent_id="tell-attack", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
    assert _payloads(e.events[before:], "ATTACK_ROLLED")[0]["mode"] == "NORMAL"


def test_surface_thoughts_save_advantage_is_scoped_to_analyzed_target():
    mid = "tianxia.talent.the_hidden_eye.detect_surface_thoughts"
    e = _engine(bundle(mid))
    assert not [c for c in e.legal_candidates() if c.display_name == "Detect Surface Thoughts"]
    mark(e)
    _use(e, "Detect Surface Thoughts", AN)
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    block_save(Context(e, e.state.actors[AN], action, None, {"numbers": {"save_dc": 50}}, [e.state.actors[ME]], e.state.actors[ME]),
               {"type": "save", "ability": "wis", "on_fail": []})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("case,expected", [
    ("reading", "ADVANTAGE"), ("other_target", "NORMAL"),
    ("no_reading", "NORMAL"), ("expired", "NORMAL"), ("disadvantage", "NORMAL")])
def test_surface_thoughts_single_target_analyze_checks(case, expected):
    from combat.ext.riders14_eye import THOUGHTS

    ally = "actor:r14.other_target"
    e = _engine(bundle("tianxia.talent.the_hidden_eye.detect_surface_thoughts"),
                allies=(bundle(actor_id=ally),))
    e.state.actors[ally].team_id = e.state.actors[AN].team_id
    mark(e)
    if case != "no_reading":
        _use(e, "Detect Surface Thoughts", AN)
    if case == "expired":
        e._system_start_turn()
        assert not [c for c in e.state.actors[ME].conditions.values() if c.condition_id == THOUGHTS]
    if case == "disadvantage":
        e._apply_condition(e.state.actors[ME], "condition:typed.check_mode", "test:disadvantage", ME,
                           expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
    _ready(e)
    from combat.gate2_runtime_models import ActionIntent

    target_id = ally if case == "other_target" else AN
    candidate = next(c for c in e.legal_candidates() if c.display_name == "Analyze" and c.target_ids == (target_id,))
    before = len(e.events)
    e.execute_intent(ActionIntent(intent_id="reading-analyze", decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids))
    events = e.events[before:]
    assert _payloads(events, "CHECK_ROLLED")[0]["actor"]["mode"] == expected


def test_modify_saving_throw_never_installs_a_runtime_wrapper():
    e = _engine(bundle(PREFIX + "MODIFY_CHARACTERISTICS"))
    # The engine itself installs its authorized d20 checkpoint recorder.
    assert "riders14" not in e._roll_save.__func__.__module__
    assert "_riders14_modified_saves" not in e.__dict__


@pytest.mark.parametrize("disadvantage,expected", [(False, "ADVANTAGE"), (True, "NORMAL")])
def test_surface_thoughts_advantages_real_scoundrel_action_check(disadvantage, expected):
    sheet = _sheet(BASE, cl=1)
    sheet["spheres_and_talents"]["sphere_record_ids"].append("tianxia.sphere.scoundrel")
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [
        "tianxia.talent.the_hidden_eye.detect_surface_thoughts", "TAL_SCOUNDREL_DIRTY_TRICK"]
    e = _engine(compile_character(sheet, actor_id=ME))
    mark(e)
    _use(e, "Detect Surface Thoughts", AN)
    _ready(e)
    if disadvantage:
        from combat.ext.tabik_scoundrel import EXPLOITED

        e._apply_condition(e.state.actors[ME], "condition:typed.check_mode", "test:disadvantage", ME,
                           expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
        e._apply_condition(e.state.actors[AN], EXPLOITED, "test:exploit", ME, expires_on="UNTIL_REMOVED")
    events = _use(e, "DIRTY TRICK: Low Sweep", AN)
    roll = _payloads(events, "CHECK_ROLLED")[0]
    assert roll["actor"]["mode"] == expected
    assert roll["target"]["mode"] == "NORMAL"


@pytest.mark.parametrize("source_is_read,expected", [(True, "ADVANTAGE"), (False, "NORMAL")])
def test_surface_thoughts_forced_skill_check_uses_effect_owner(source_is_read, expected):
    from combat.ext.tabik_dark import skill_check

    ally = "actor:r14.skill_source"
    e = _engine(bundle("tianxia.talent.the_hidden_eye.detect_surface_thoughts"), allies=(bundle(actor_id=ally),))
    mark(e)
    _use(e, "Detect Surface Thoughts", AN)
    source = e.state.actors[AN if source_is_read else ally]
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    skill_check(Context(e, source, action, None, {"numbers": {"save_dc": 50}}, [e.state.actors[ME]], e.state.actors[ME]),
                {"type": "skill_check", "ability": "DEX", "skill": "Acrobatics"})
    assert _payloads(e.events[before:], "CHECK_ROLLED")[0]["actor"]["mode"] == expected


@pytest.mark.parametrize("case,ability,skill,expected", [
    ("analyzed", "WIS", "Insight", "ADVANTAGE"),
    ("disadvantage", "WIS", "Insight", "NORMAL"),
    ("other_source", "WIS", "Insight", "NORMAL"),
    ("other_analyzer", "WIS", "Insight", "NORMAL"),
    ("removed", "WIS", "Insight", "NORMAL"),
    ("unowned", "WIS", "Insight", "NORMAL"),
    ("analyzed", "INT", "Insight", "NORMAL"),
    ("analyzed", "WIS", "Perception", "NORMAL"),
])
def test_discern_tells_source_owned_insight_check(case, ability, skill, expected):
    from combat.ext.tabik_dark import skill_check
    from combat.ext.condition_events import drop_condition
    from combat.ext.mind_hidden_eye import ANALYZED

    ally = "actor:r14.insight_source"
    talents = () if case == "unowned" else ("tianxia.talent.the_hidden_eye.discern_tells",)
    e = _engine(bundle(*talents), allies=(bundle(actor_id=ally),))
    me, foe = e.state.actors[ME], e.state.actors[AN]
    analyzer = e.state.actors[ally] if case == "other_analyzer" else me
    mark_analyzed(e, analyzer, foe, "test:analyzed")
    if case == "removed":
        for iid, condition in list(foe.conditions.items()):
            if condition.condition_id == ANALYZED:
                drop_condition(e, foe, iid, "test:removed")
    if case == "disadvantage":
        e._apply_condition(me, "condition:typed.check_mode", "test:disadvantage", ME,
                           expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
    source = e.state.actors[ally] if case == "other_source" else foe
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    # Effect-level execution: no Insight action or DC is added to the rules.
    skill_check(Context(e, source, action, None, {"numbers": {"save_dc": 50}}, [me], me),
                {"type": "skill_check", "ability": ability, "skill": skill})
    assert _payloads(e.events[before:], "CHECK_ROLLED")[0]["actor"]["mode"] == expected


def test_discern_tells_does_not_guess_missing_check_target():
    from combat.typed_executor import check_mode

    e = _engine(bundle("tianxia.talent.the_hidden_eye.discern_tells"))
    mark(e)
    assert check_mode(e.state.actors[ME], "WIS", "Insight", engine=e) == "NORMAL"


def test_modify_saving_throw_reduces_a_legacy_save_bonus_by_two():
    # Rider lane C14: the all-source save_bonus seam now carries the penalty to legacy (non-typed) saves. The printed rule is
    # "Reduce that saving throw bonus by 2", so the roll's modifier drops by 2 (this test previously expected DC 52 as a
    # strict xfail awaiting the seam; the DC is left alone, as save_bonus's contract says).
    from combat.ext.riders14_research import MODIFIED

    e = _engine(bundle(PREFIX + "MODIFY_CHARACTERISTICS"))
    plain = _payloads((e._roll_save(e.state.actors[AN], "CON", 50, "test:legacy_save"), e.events)[1][-3:], "SAVE_ROLLED")[-1]
    e._apply_condition(e.state.actors[AN], MODIFIED, "test:modified_save", ME,
                       expires_on="UNTIL_REMOVED", data={"ability": "CON", "penalty": 2})
    before = len(e.events)
    e._roll_save(e.state.actors[AN], "CON", 50, "test:legacy_save")
    rolled = _payloads(e.events[before:], "SAVE_ROLLED")[0]
    assert rolled["dc"] == 50 and rolled["modifier"] == plain["modifier"] - 2


def test_discern_illusions_advantages_only_illusion_saves_while_focused():
    e = _engine(bundle(PREFIX + "DISCERN_ILLUSIONS"))
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    block_save(Context(e, e.state.actors[AN], action, None,
        {"source": "TAL_ILLUSION_GLAMER", "numbers": {"save_dc": 50}}, [e.state.actors[ME]], e.state.actors[ME]),
        {"type": "save", "ability": "wis", "on_fail": []})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"


@pytest.mark.parametrize("case,ability,skill,expected", [
    ("focused", "INT", "Investigation", "ADVANTAGE"),
    ("disadvantage", "INT", "Investigation", "NORMAL"),
    ("multiple_sources", "INT", "Investigation", "NORMAL"),
    ("unfocused", "INT", "Investigation", "NORMAL"),
    ("unowned", "INT", "Investigation", "NORMAL"),
    ("other_effect", "INT", "Investigation", "NORMAL"),
    ("no_provenance", "INT", "Investigation", "NORMAL"),
    ("focused", "WIS", "Investigation", "NORMAL"),
    ("focused", "INT", "Arcana", "NORMAL"),
])
def test_discern_illusions_qualified_effect_investigation(case, ability, skill, expected):
    from combat.ext.tabik_dark import skill_check

    talents = () if case == "unowned" else (PREFIX + "DISCERN_ILLUSIONS",)
    e = _engine(bundle(*talents))
    me = e.state.actors[ME]
    if case == "unfocused":
        e._spend_resource(me, FOCUS, 1, "test:unfocused")
    if case in ("disadvantage", "multiple_sources"):
        e._apply_condition(me, "condition:typed.check_mode", "test:disadvantage", ME,
                           expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"ALL": "DISADVANTAGE"}}})
    if case == "multiple_sources":
        from combat.ext.riders14_eye import THOUGHTS

        e._apply_condition(me, THOUGHTS, "test:reading", ME, expires_on="START_OF_SOURCE_NEXT_TURN",
                           data={"target_id": AN})
    typed = {"sphere_id": "tianxia.sphere.illusion", "numbers": {"save_dc": 50}}
    if case == "other_effect":
        typed["sphere_id"] = "tianxia.sphere.dark"
    elif case == "no_provenance":
        del typed["sphere_id"]
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    # Existing effect executor with explicit Illusion provenance, not a new Study action.
    skill_check(Context(e, e.state.actors[AN], action, None, typed, [me], me),
                {"type": "skill_check", "ability": ability, "skill": skill})
    assert _payloads(e.events[before:], "CHECK_ROLLED")[0]["actor"]["mode"] == expected


def test_discern_illusions_shared_investigation_benefit_expires():
    from combat.ext.tabik_dark import skill_check

    ally = "actor:r14.illusion_ally"
    e = _engine(bundle(PREFIX + "DISCERN_ILLUSIONS"), allies=(bundle(actor_id=ally),))
    _use(e, "Discern Illusions: Share")
    assert e.state.actors[ME].resources[FOCUS] == 0
    action = next(iter(e.action_catalog.values()))
    ctx = Context(e, e.state.actors[AN], action, None,
                  {"source": "TAL_ILLUSION_GLAMER", "numbers": {"save_dc": 50}},
                  [e.state.actors[ally]], e.state.actors[ally])
    eff = {"type": "skill_check", "ability": "INT", "skill": "Investigation"}
    for expected in ("ADVANTAGE", "NORMAL"):
        before = len(e.events)
        skill_check(ctx, eff)
        assert _payloads(e.events[before:], "CHECK_ROLLED")[0]["actor"]["mode"] == expected
        e.state.round_number += 2
        e._system_start_turn()


def test_discern_illusions_does_not_advantage_analyze_of_illusion_caster():
    from combat.typed_executor import check_mode

    e = _engine(bundle(PREFIX + "DISCERN_ILLUSIONS"))
    assert check_mode(e.state.actors[ME], "INT", "Investigation", engine=e,
                      against_creature=e.state.actors[AN]) == "NORMAL"


def test_discern_illusions_can_share_save_benefit_for_key_modifier_rounds():
    ally = "actor:lane14.ally"
    e = _engine(bundle(PREFIX + "DISCERN_ILLUSIONS"), allies=(bundle(actor_id=ally),))
    _use(e, "Discern Illusions: Share")
    assert e.state.actors[ME].resources[FOCUS] == 0
    action = next(iter(e.action_catalog.values()))
    before = len(e.events)
    block_save(Context(e, e.state.actors[AN], action, None,
        {"source": "TAL_ILLUSION_GLAMER", "numbers": {"save_dc": 50}}, [e.state.actors[ally]], e.state.actors[ally]),
        {"type": "save", "ability": "wis", "on_fail": []})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"
    e.state.round_number += 2
    e._system_start_turn()
    assert not [c for c in e.state.actors[ally].conditions.values() if c.condition_id == "condition:typed.eye_discern_illusions"]


def test_prognosis_discrete_healing_adds_pb_and_grants_next_save_only_once():
    e = _engine(bundle(PREFIX + "PROGNOSIS"))
    mark(e)
    foe = e.state.actors[AN]
    foe.current_hp = 10
    # Use a real compiled healing action as the source, without attacking the target.
    heal_bundle = compile_character(_sheet("LIFE_BASE_MEND_THE_PULSE", cl=1, dc=50), actor_id=ME)
    heal_row = next(r for r in heal_bundle["action_catalog"] if r["parameters"].get("typed", {}).get("source") == "LIFE_BASE_MEND_THE_PULSE")
    from combat.gate2_runtime_models import ActionDefinition
    action = ActionDefinition.model_validate(heal_row)
    e.action_catalog[action.source_definition_id] = action
    before = len(e.events)
    block_healing(Context(e, e.state.actors[ME], action, None, {"numbers": {}}, [foe], foe), {"type": "healing", "flat": 5, "applies_to": "target"})
    assert foe.current_hp == 19  # five discrete healing + PB 4
    assert len(_payloads(e.events[before:], "HEALING_APPLIED")) == 2
    before = len(e.events)
    block_healing(Context(e, e.state.actors[ME], action, None, {"numbers": {}}, [foe], foe), {"type": "healing", "flat": 5, "applies_to": "target"})
    assert foe.current_hp == 24 and len(_payloads(e.events[before:], "HEALING_APPLIED")) == 1
    assert len([c for c in foe.conditions.values() if c.source_definition_id == "passive:eye.prognosis"
                and c.condition_id == "condition:typed.save_against"]) == 1
    before = len(e.events)
    block_save(Context(e, e.state.actors[ME], action, None, {"numbers": {"save_dc": 50}}, [foe], foe),
               {"type": "save", "ability": "wis", "on_fail": []})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "ADVANTAGE"
    before = len(e.events)
    block_save(Context(e, e.state.actors[ME], action, None, {"numbers": {"save_dc": 50}}, [foe], foe),
               {"type": "save", "ability": "wis", "on_fail": []})
    assert _payloads(e.events[before:], "SAVE_ROLLED")[0]["mode"] == "NORMAL"


def _prognosis_healing_context(engine, healer_id=ME):
    from combat.gate2_runtime_models import ActionDefinition

    heal_bundle = compile_character(_sheet("LIFE_BASE_MEND_THE_PULSE", cl=1, dc=50), actor_id=healer_id)
    row = next(r for r in heal_bundle["action_catalog"]
               if r["parameters"].get("typed", {}).get("source") == "LIFE_BASE_MEND_THE_PULSE")
    action = ActionDefinition.model_validate(row)
    engine.action_catalog[action.source_definition_id] = action
    target = engine.state.actors[AN]
    return Context(engine, engine.state.actors[healer_id], action, None,
                   {"numbers": {"save_dc": 50}}, [target], target)


def _prognosis_save_mode(ctx):
    before = len(ctx.engine.events)
    block_save(ctx, {"type": "save", "ability": "wis", "on_fail": []})
    return _payloads(ctx.engine.events[before:], "SAVE_ROLLED")[0]["mode"]


def test_prognosis_other_healer_then_eye_grants_save_without_extra_pb():
    healer = "actor:r14.other_healer"
    e = _engine(bundle(PREFIX + "PROGNOSIS"), allies=(bundle(actor_id=healer),))
    mark(e)
    target = e.state.actors[AN]
    target.current_hp = 10
    effect = {"type": "healing", "flat": 5, "applies_to": "target"}
    other_ctx = _prognosis_healing_context(e, healer)
    block_healing(other_ctx, effect)
    assert target.current_hp == 19
    assert _prognosis_save_mode(other_ctx) == "NORMAL"
    eye_ctx = _prognosis_healing_context(e)
    before = len(e.events)
    block_healing(eye_ctx, effect)
    assert target.current_hp == 24
    assert len(_payloads(e.events[before:], "HEALING_APPLIED")) == 1
    assert _prognosis_save_mode(eye_ctx) == "ADVANTAGE"
    assert _prognosis_save_mode(eye_ctx) == "NORMAL"


def test_prognosis_heal_save_heal_save_renews_grant_in_same_turn():
    e = _engine(bundle(PREFIX + "PROGNOSIS"))
    mark(e)
    target = e.state.actors[AN]
    target.current_hp = 10
    ctx = _prognosis_healing_context(e)
    effect = {"type": "healing", "flat": 5, "applies_to": "target"}
    turn = (e.state.round_number, e.state.current_actor_id)
    for expected_hp in (19, 24):
        block_healing(ctx, effect)
        assert target.current_hp == expected_hp
        grants = [c for c in target.conditions.values() if c.source_definition_id == "passive:eye.prognosis"
                  and c.condition_id == "condition:typed.save_against"]
        assert len(grants) == 1
        assert grants[0].source_actor_id == ME
        assert grants[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
        assert _prognosis_save_mode(ctx) == "ADVANTAGE"
        assert _prognosis_save_mode(ctx) == "NORMAL"
    assert (e.state.round_number, e.state.current_actor_id) == turn


def test_deadly_strike_spends_focus_before_the_first_attack_roll_even_on_miss():
    e = _engine(bundle(PREFIX + "DEADLY_STRIKE"))
    _use(e, "Deadly Strike: first hidden attack: spend Martial Focus before rolling; on hit, +PBd6 instead of +PB")
    e._apply_condition(e.state.actors[ME], "condition:typed.hidden", "test:hidden", ME, expires_on="UNTIL_REMOVED", data={"stealth_total": 40})
    e.state.actors[AN].armor_class = 100
    events = attack(e)
    spent = [i for i, x in enumerate(events) if x.event_type == "RESOURCE_SPENT" and x.payload.get("resource_id") == FOCUS]
    rolled = [i for i, x in enumerate(events) if x.event_type == "ATTACK_ROLLED"]
    assert spent and rolled and spent[0] < rolled[0]
    assert e.state.actors[ME].resources[FOCUS] == 0


def test_adroit_focus_offers_reaction_when_analyzed_creature_drops():
    e = _engine(bundle(PREFIX + "ADROIT_FOCUS"))
    mark(e)
    e._spend_resource(e.state.actors[ME], FOCUS, 1, "test:spent")
    e.state.actors[AN].current_hp = 1
    events = attack(e)
    assert any(x.event_type == "REACTION_RESOLVED" and x.source_definition_id == "reaction:eye.adroit_focus" for x in events)
    assert not e.state.actors[ME].reaction_available
    assert e.state.actors[ME].resources[FOCUS] == 1


def test_uncanny_bonus_analyze_requires_stalker_concealment():
    e = _engine(bundle(PREFIX + "UNCANNY_STALKER"))
    assert next(a for a in e.action_catalog.values() if a.display_name == "Analyze").economy.value == "ACTION"
    assert not [c for c in e.legal_candidates() if c.display_name == "Uncanny Stalker: Analyze"]
    e._apply_condition(e.state.actors[ME], "condition:typed.hidden", "test:hidden", ME, expires_on="UNTIL_REMOVED", data={"stealth_total": 40})
    events = _use(e, "Uncanny Stalker: Analyze", AN)
    assert _payloads(events, "CHECK_ROLLED")
    assert e.state.actors[ME].action_available and not e.state.actors[ME].bonus_action_available


@pytest.mark.parametrize("talent,name", [("FAST_STEALTH", "Fast Stealth: Hide"), ("SUDDEN_ACUITY", "Sudden Acuity: Search")])
def test_hide_and_search_bonus_action_alternatives(talent, name):
    from combat import stealth

    e = _engine(bundle(PREFIX + talent, scores={a: 30 if a == "DEX" else 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}))
    if talent == "FAST_STEALTH":
        # Heavy obscurement permits the normal Hide action.
        from combat import zones
        action = next(iter(e.action_catalog.values()))
        zones.create(Context(e, e.state.actors[ME], action, None, {"numbers": {}}, [], None),
                     {"shape": "sphere", "size_ft": 10, "obscured": "heavy", "centered_on_self": True,
                      "duration": {"kind": "minutes", "amount": 1}})
    else:
        e._apply_condition(e.state.actors[AN], stealth.HIDDEN, "test:foe", AN, expires_on="UNTIL_REMOVED", data={"stealth_total": 5})
    events = _use(e, name)
    assert _payloads(events, "CHECK_ROLLED")
    assert e.state.actors[ME].action_available and not e.state.actors[ME].bonus_action_available


@pytest.mark.parametrize("move", [False, True])
def test_vanish_reaction_runs_hide_after_missed_weapon_attack(monkeypatch, move):
    from combat.gate2_runtime_models import ActionIntent, Position
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.ext import needle

    original = needle.ask
    def choose(*args, **kwargs):
        return [needle._cell_id(Position(x=3, y=7))] if move and args[4] == needle.CHOICE + "eye_vanish" else original(*args, **kwargs)
    monkeypatch.setattr(needle, "ask", choose)

    enemy = "actor:lane14.enemy"
    mine = bundle(PREFIX + "VANISH_BETWEEN_HEARTBEATS", scores={a: 30 if a == "DEX" else 2 for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")})
    foe = bundle(actor_id=enemy)
    e = Gate4ControllerEngine(ROOT, match_seed="LANE1", typed_bundles=(mine, foe),
        roster_setup={"primary_actor_ids": [ME, enemy], "team_by_actor": {ME: "team:a", enemy: "team:b"},
        "starting_positions": {ME: {"x": 3, "y": 6}, enemy: {"x": 4, "y": 6}}})
    e.state.current_slot_index = e.state.initiative_order.index(enemy)
    e.state.current_actor_id = enemy
    e._system_start_turn()
    e.state.actors[ME].armor_class = 100
    c = next(c for c in e.legal_candidates() if c.display_name == "Fu (Short Axe) attack")
    before = len(e.events)
    e.execute_intent(ActionIntent(intent_id="vanish-attack", decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=enemy, target_ids=(ME,)))
    events = e.events[before:]
    assert any(x.event_type == "CHECK_ROLLED" and x.payload.get("check") == "Stealth" for x in events)
    assert any(c.condition_id == "condition:typed.hidden" for c in e.state.actors[ME].conditions.values())
    assert not e.state.actors[ME].reaction_available
    assert e.state.actors[ME].resources[FOCUS] == 0
    if move:
        assert e.state.actors[ME].position == Position(x=3, y=7)
        assert any(x.event_type == "MOVEMENT_COMMITTED" and x.actor_id == ME for x in events)
        assert len(_payloads(events, "ATTACK_ROLLED")) == 1  # no opportunity attack
