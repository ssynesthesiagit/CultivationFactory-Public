"""Riders lane 2 (owner 2026-09-29: "i want everything we can automated, keep going until its only the non-combat ones left"):
combat abilities whose core ran but whose printed lines were still shown to the GM as riders.  Each line automated here is compiled
on a real character and run through the engine; each test fails on the typing the authority carried before (the line was a rider).

Overrides: authority/typed_mechanics/reviewed_final.d/riders_lane2.json (plus in-place edits of the other reviewed_final.d files
that already held the key); plug-ins: combat/ext/next_attack_damage.py; engine tweaks: combat/typed_reactions._resistance_ignored
(``if_marked`` / ``requires_condition``), combat/ext/menus.toggles (a Talent's own menu), combat/factory_compiler (Force for Iron
Meridian Body).  Saves are forced with the sheet's technique DC (50 / -40) and attacks always hit (foe AC -50).
"""

import importlib

import pytest

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from combat.typed_executor import mark_condition_id

A = importlib.import_module("tests.test_review_sw-athletics")  # the shared harness (hyphenated file name)
ME, FOE, ROOT = A.ME, A.FOE, A.ROOT
FAIL, PASS = A.FAIL, A.PASS
IRON_FIST = "tianxia.sphere.iron_fist"
STRIKE = "Unarmed Strike (Iron Fist)"
KIT = A.AXE_KIT

OPEN_HAND = "TAL_IRON_FIST_OPEN_HAND_DISARM"
COURT = "TAL_IRON_FIST_COURT_OF_ONE_HUNDRED_FORMS"
BREAKING = "TAL_IRON_FIST_BREAKING_KNUCKLE"

FLURRY = "TAL_IRON_FIST_IRON_FIST_FLURRY"
FLURRY_STRIKE = STRIKE + " + Iron Fist Flurry"


@pytest.mark.parametrize("first", [STRIKE, "Grapple", "Shove: Push 5 ft", "Shove: Prone", "miss"])
def test_flurry_requires_an_actual_attack_action_unarmed_strike(first):
    from combat.ext.iron_flurry import READY

    engine = _duel([FLURRY])
    assert FLURRY_STRIKE not in A._legal(engine)
    if first == "miss":
        engine.state.actors[FOE].armor_class = 1000
        first = STRIKE
    events = _strike(engine, first)
    assert engine.state.actors[ME].turn_flags[READY] == 1
    if first != "Shove: Push 5 ft":
        assert FLURRY_STRIKE in A._legal(engine)
    else:
        # The actual push moved the sole foe beyond this strike's reach.
        assert FLURRY_STRIKE not in A._legal(engine)
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 1
    if first == STRIKE:
        assert any(e.event_type == "ATTACK_ROLLED" for e in events)


def test_flurry_bonus_strike_is_one_attack_pays_focus_and_cannot_recur():
    sheet = A._sheet(IRON_FIST, [FLURRY], KIT, cl=20)
    sheet["path_and_subpath"]["path_feature_record_ids"] = ["tianxia.path.body_refining.feature.extra_attack"]
    bundle = compile_character(sheet, actor_id=ME)
    foe = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="FLURRY-EXTRA", typed_bundles=(bundle, foe),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].maximum_hp = engine.state.actors[FOE].current_hp = 1000
    basic = next(a for a in engine.action_catalog.values() if a.display_name == STRIKE)
    assert basic.parameters["typed"]["effects"][0]["count"] == 4
    _strike(engine)
    action = next(a for a in engine.action_catalog.values() if a.display_name == FLURRY_STRIKE)
    assert action.parameters["typed"]["effects"][0]["count"] == 1
    events = _strike(engine, FLURRY_STRIKE)
    assert len([e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME]) == 1
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 0
    assert not engine.state.actors[ME].bonus_action_available
    assert FLURRY_STRIKE not in A._legal(engine)


def test_flurry_readiness_expires_on_next_own_turn():
    from combat.ext.iron_flurry import READY

    engine = _duel([FLURRY])
    _strike(engine)
    _foe_turn(engine)
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    assert not engine.state.actors[ME].turn_flags.get(READY)
    assert FLURRY_STRIKE not in A._legal(engine)


def test_flurry_dodge_does_not_qualify():
    from combat.ext.iron_flurry import READY

    engine = _duel([FLURRY])
    A._use(engine, "Dodge", None)
    assert not engine.state.actors[ME].turn_flags.get(READY)
    assert FLURRY_STRIKE not in A._legal(engine)


def test_flurry_unowned_character_is_inert():
    from combat.ext.iron_flurry import READY

    engine = _duel([])
    _strike(engine)
    assert not engine.state.actors[ME].turn_flags.get(READY)
    assert all(not a.parameters.get("iron_flurry") for a in engine.action_catalog.values() if a.owner_id == ME)


def test_flurry_counter_palm_on_enemy_turn_does_not_take_attack_action():
    from combat.ext.iron_flurry import READY

    engine, asked = _court_run(active=False, talents=[FLURRY])
    events = _court_strike(engine)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events)
    assert not engine.state.actors[ME].turn_flags.get(READY)


def test_flurry_table_prerequisite_and_focus_survive_commit_reload(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.ext.iron_flurry import READY
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    me = compile_character(A._sheet(IRON_FIST, [FLURRY], KIT, cl=20), actor_id=ME)
    foe = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    for bundle in (me, foe):
        bundle["actor_template"].update(armor_class=0, maximum_hp=1000, speed_ft=0,
                                        initiative_bonus=100 if bundle is me else -100)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="FLURRY", typed_bundles=(me, foe),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)

    def candidates():
        return combat.decision(session.match_id)["context"]["legal_candidates"]

    def use(name):
        menu = table.state(session.match_id)["menu"]
        candidate = next(c for c in candidates() if c["display_name"] == name and c["target_ids"] == [FOE])
        return table.act(session.match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0)

    assert not any(c["display_name"] == FLURRY_STRIKE for c in candidates())
    assert use(STRIKE)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id).engine
    assert reloaded.state.actors[ME].turn_flags[READY] == 1
    assert reloaded.state.model_dump(mode="json") == combat._load_session(session.match_id).engine.state.model_dump(mode="json")
    result = use(FLURRY_STRIKE)
    assert result["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(session.match_id).engine
    assert reloaded.state.actors[ME].resources["resource:core.martial_focus"] == 0
    assert reloaded.state.model_dump(mode="json") == combat._load_session(session.match_id).engine.state.model_dump(mode="json")


def _court_run(*, active=True, decline=False, talents=None):
    from combat.gate2_runtime_models import ReactionDecision

    engine = _duel([*(talents if talents is not None else [COURT, BREAKING]), "TAL_IRON_FIST_COUNTER_PALM"], cl=12)
    if active:
        A._use(engine, "Court of One Hundred Forms", None)
        A._ready(engine)
    asked = []

    def provider(request):
        asked.append(request)
        options = (request.get("choice_trigger") or {}).get("needle_options") or []
        if not options:
            return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                    reaction_source_id=request["reaction_source_id"], selection="USE"), None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if decline else "USE",
                                option_ids=() if decline else (options[0],)), None

    engine._gate4_reaction_provider = provider
    return engine, asked


def _court_strike(engine):
    if engine.state.current_actor_id != FOE:
        _foe_turn(engine)
    engine.state.actors[FOE].action_available = True
    engine.state.actors[ME].armor_class = 1000
    engine.state.actors[ME].reaction_available = True
    engine.state.actors[ME].resources["resource:core.martial_focus"] = 1
    return _foe_attacks(engine)


def _court_requests(asked):
    return [r for r in asked if "Court of One Hundred Forms" in (r.get("choice_trigger") or {}).get("prompt", "")]


def test_court_extra_form_applies_once_per_turn_and_leaves_normal_form_available():
    from combat.ext.iron_forms import COURT_USED

    engine, asked = _court_run()
    events = _court_strike(engine)
    requests = _court_requests(asked)
    assert len(requests) == 1
    assert requests[0]["choice_trigger"]["needle_options"] == [BREAKING]
    assert "Counter Palm" in requests[0]["choice_trigger"]["prompt"]
    assert engine.state.actors[FOE].display_name in requests[0]["choice_trigger"]["prompt"]
    # Base strike + extra Breaking Knuckle + Centerline; the Court choice adds PB.
    assert sum(e.payload["hp_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME
               and not e.source_definition_id.endswith(".open_the_gate")) > 4
    assert isinstance(engine.state.actors[ME].turn_flags[COURT_USED], str)
    assert any(row.get("source_modifier") == BREAKING for action in engine.action_catalog.values()
               if action.owner_id == ME and action.display_name == STRIKE
               for row in action.parameters["typed"]["effects"][0]["on_hit"])
    _court_strike(engine)
    assert len(_court_requests(asked)) == 1
    engine.state.round_number += 1
    engine.state.actors[ME].turns_started += 1
    _court_strike(engine)
    assert len(_court_requests(asked)) == 2


@pytest.mark.parametrize("case", ["inactive", "no_form", "decline", "immune", "incapacitated", "expired"])
def test_court_extra_form_gates_and_decline(case):
    from combat.ext.iron_forms import COURT_ACTIVE, COURT_USED

    engine, asked = _court_run(active=case != "inactive", talents=[COURT] if case == "no_form" else None,
                              decline=case == "decline")
    if case == "immune":
        engine._add_modifier(engine.state.actors[FOE], "test:immune", "damage_immunity", "ADD", "BLUDGEONING", "SELF", expires_on="UNTIL_REMOVED")
    if case == "incapacitated":
        _incapacitate(engine)
        assert not any(c.condition_id == COURT_ACTIVE for c in engine.state.actors[ME].conditions.values())
        engine._remove_condition(engine.state.actors[ME], "condition:incapacitated", "test:recover")
    if case == "expired":
        from combat.ext.effect_durations import sweep
        engine.state.round_number += 10
        sweep(engine, engine.state.actors[ME], "START_OF_TURN")
        assert not any(c.condition_id == COURT_ACTIVE for c in engine.state.actors[ME].conditions.values())
    _court_strike(engine)
    assert len(_court_requests(asked)) == (1 if case == "decline" else 0)
    assert COURT_USED not in engine.state.actors[ME].turn_flags
    if case == "decline":
        A._ready(engine)
        _court_strike(engine)
        assert len(_court_requests(asked)) == 2  # declining did not consume the extra Form


@pytest.mark.parametrize("form", ["TAL_IRON_FIST_RISING_KNEE", "TAL_IRON_FIST_ELBOW_IN_THE_DOOR"])
def test_court_uses_shared_eligible_forms(form):
    engine, asked = _court_run(talents=[COURT, form])
    if form.endswith("RISING_KNEE"):
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.grappled", "test:grapple", ME,
                                expires_on="UNTIL_REMOVED")
    _court_strike(engine)
    assert _court_requests(asked)[0]["choice_trigger"]["needle_options"] == [form]
    if form.endswith("ELBOW_IN_THE_DOOR"):
        assert len([r for r in asked if r["reaction_source_id"] == "choice:needle.iron_elbow"]) == 1


def test_court_extra_form_is_available_on_another_actors_turn():
    from combat.ext.iron_forms import COURT_USED

    engine, asked = _court_run(talents=[COURT, BREAKING, "TAL_IRON_FIST_COUNTER_PALM"])
    _court_strike(engine)
    assert len(_court_requests(asked)) == 1
    A._ready(engine)
    _strike(engine)  # ordinary already-attached Breaking Knuckle is not duplicated
    _foe_turn(engine)
    engine.state.actors[ME].armor_class = 1000
    engine.state.actors[ME].resources["resource:core.martial_focus"] = 1
    engine._gate4_reaction_provider = None  # automatic actors pick eligible Forms
    events = _foe_attacks(engine)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ME for e in events)
    assert f":{FOE}:" in engine.state.actors[ME].turn_flags[COURT_USED]


def _court_table(tmp_path):
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    me = compile_character(A._sheet(IRON_FIST, [COURT, BREAKING, "TAL_IRON_FIST_COUNTER_PALM",
                                              "tianxia.talent.pressure_points.patient_hand"], KIT, cl=12), actor_id=ME,
                           reaction_plan={"ask": True})
    foe = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    for bundle in (me, foe):
        bundle["actor_template"].update(armor_class=1000 if bundle is me else 0, maximum_hp=400,
                                        speed_ft=0, initiative_bonus=100 if bundle is me else -100)
        if bundle is foe:
            bundle["action_catalog"] = [a for a in bundle["action_catalog"] if (a.get("range_ft") or 5) <= 5]
            retained = {a["source_definition_id"] for a in bundle["action_catalog"]}
            bundle["actor_template"]["action_ids"] = [aid for aid in bundle["actor_template"]["action_ids"] if aid in retained]
        for action in bundle["action_catalog"]:
            if action["display_name"] == STRIKE:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="COURT-FORMS", typed_bundles=(me, foe),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    table = TabletopService(combat, tmp_path)
    menu = table.state(session.match_id)["menu"]
    candidate = next(c for c in combat.decision(session.match_id)["context"]["legal_candidates"]
                     if c["display_name"] == "Court of One Hundred Forms")
    result = table.act(session.match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "COMMITTED"
    # Patient Hand's actual Dodge regain replenishes the Focus spent on Court,
    # so Counter Palm can pay its separate cost on the following enemy turn.
    menu = table.state(session.match_id)["menu"]
    candidate = next(c for c in combat.decision(session.match_id)["context"]["legal_candidates"]
                     if c["source_definition_id"] == "system:combat.dodge")
    result = table.act(session.match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "choice:needle.iron_court_dodge"
    # These existing regressions isolate Counter Palm on the following turn;
    # decline Court's newly implemented, independently tested Dodge strike.
    decline = {**result["reaction"]["context"], "selection": "DECLINE", "option_ids": []}
    assert table.act(session.match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [decline])["status"] == "COMMITTED"
    menu = table.state(session.match_id)["menu"]
    assert table.act(session.match_id, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    return combat, table, session.match_id


def test_court_table_extra_form_choice_rolls_back_and_persists_limit_and_duration(tmp_path):
    from combat.ext.iron_forms import COURT_ACTIVE, COURT_USED
    from combat.gate5_service import CombatService

    combat, table, match_id = _court_table(tmp_path)
    menu = table.state(match_id)["menu"]
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                     if c["display_name"].startswith("Fu (Short Axe) attack") and c["target_ids"] == [ME]
                     and "#" not in c["source_definition_id"])
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0)
    assert result["status"] == "REACTION_REQUIRED"
    counter = {**result["reaction"]["context"], "selection": "USE"}
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [counter])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Court of One Hundred Forms" in prompt["moment"] and "Counter Palm" in prompt["moment"]
    assert [o["id"] for o in prompt["choice"]["options"]] == [BREAKING]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": [BREAKING]}
    result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [counter, answer])
    assert result["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    assert reloaded.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")
    assert isinstance(reloaded.state.actors[ME].turn_flags[COURT_USED], str)
    marker = next(c for c in reloaded.state.actors[ME].conditions.values() if c.condition_id == COURT_ACTIVE)
    assert marker.expires_on.startswith("START_OF_SLOT_AT:")


def test_court_manual_owner_is_asked_on_ai_turn(tmp_path):
    combat, table, match_id = _court_table(tmp_path)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "MANUAL"})
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    assert result["status"] == "REACTION_REQUIRED"
    counter = {**result["reaction"]["context"], "selection": "USE"}
    result = table.auto_step(match_id, 0, [counter])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Court of One Hundred Forms" in prompt["moment"] and "Counter Palm" in prompt["moment"]
    assert prompt["context"]["reactor_id"] == ME
    answer = {**prompt["context"], "selection": "USE", "option_ids": [BREAKING]}
    assert table.auto_step(match_id, 0, [counter, answer])["status"] != "REACTION_REQUIRED"


def test_court_ai_owner_decides_automatically_on_ai_turn(tmp_path):
    from combat.ext.iron_forms import COURT_USED

    combat, table, match_id = _court_table(tmp_path)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "LOCAL_AUTO"})
    combat._write_metadata(match_id, metadata)
    assert table.auto_step(match_id, 0)["status"] != "REACTION_REQUIRED"
    assert COURT_USED in combat._load_session(match_id).engine.state.actors[ME].turn_flags


def test_court_extra_and_counter_normal_form_are_distinct_and_both_resolve():
    from combat.ext.iron_forms import RISING

    engine, asked = _court_run(talents=[COURT, BREAKING, RISING])
    _open(engine)
    engine._apply_condition(engine.state.actors[FOE], "condition:typed.grappled", "test:grapple", ME,
                            expires_on="UNTIL_REMOVED")
    events = _court_strike(engine)
    requests = [r for r in asked if r["reaction_source_id"] == "choice:needle.iron_forms"]
    assert len(requests) == 2
    assert requests[0]["choice_trigger"]["needle_options"] == [BREAKING, RISING]
    assert requests[1]["choice_trigger"]["needle_options"] == [RISING]
    damages = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == ME
               and not e.source_definition_id.endswith(".open_the_gate")]
    assert len(damages) == 3  # strike, extra Breaking Knuckle, normal Rising Knee
    assert any(m.target_field == "speed_ft" and m.value == -10 for m in engine.state.actors[FOE].modifiers.values())


def test_court_does_not_repeat_a_form_already_attached_to_an_ordinary_strike():
    engine, asked = _court_run()
    events = _strike(engine)
    assert not _court_requests(asked)
    assert sum(e.payload["hp_damage"] == 4 for e in events if e.event_type == "DAMAGE_COMMITTED"
               and not e.source_definition_id.endswith(".open_the_gate")) == 1


def test_court_choice_pause_from_hammer_followup_is_not_swallowed():
    engine, asked = _court_run(talents=[COURT, BREAKING, "TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM",
                                       "TAL_IRON_FIST_SKY_SHATTERING_AXE_KICK"])
    A._use(engine, "Choose Hammer-and-Anvil Rhythm: Extend Opening", None)
    _strike(engine)  # normal attached Breaking Knuckle; Court cannot repeat it
    A._ready(engine)
    engine.state.actors[ME].resources["resource:core.martial_focus"] = 1

    def paused(request):
        if "Court of One Hundred Forms" in (request.get("choice_trigger") or {}).get("prompt", ""):
            raise RuntimeError("court-choice-pause")
        return None, None

    engine._gate4_reaction_provider = paused
    with pytest.raises(RuntimeError, match="court-choice-pause"):
        A._use(engine, "Sky-Shattering Axe Kick", FOE)


def _open_hand_run(*, owns=True, decline=False, skill="Athletics", lose=False, miss=False, immune=False,
                   two_handed=False, size=None, transferred=False, defending_bonus=None):
    from combat.gate2_runtime_models import ReactionDecision
    engine = _duel([OPEN_HAND] if owns else [])
    foe = engine.state.actors[FOE]
    foe.skills.update({"Athletics": 100 if lose else -100, "Acrobatics": 100 if lose else -100})
    if defending_bonus is not None:
        foe.skills.update({"Athletics": defending_bonus, "Acrobatics": defending_bonus})
    if miss:
        foe.armor_class = 1000
    if immune:
        engine._add_modifier(foe, "test:immune", "damage_immunity", "ADD", "BLUDGEONING", "SELF", expires_on="UNTIL_REMOVED")
    from combat.ext.iron_open_hand import held_weapons
    weapons = held_weapons(engine, foe)
    weapon = next(iter(weapons))
    if two_handed:
        engine.action_catalog[weapon].parameters["typed"]["weapon"]["properties"] = ["Two-Handed"]
    if size:
        creature = foe if size > 0 else engine.state.actors[ME]
        fp = engine._footprint(creature)
        engine.actor_footprints[creature.entity_id] = type(fp).rectangle(abs(size), abs(size),
            footprint_id=fp.footprint_id, source_definition_id=fp.source_definition_id)
        if size < 0:
            creature.position = creature.position.model_copy(update={"x": 2})
    if transferred:
        owner_weapon = next(iter(held_weapons(engine, engine.state.actors[ME])))
        engine._apply_condition(engine.state.actors[ME], "condition:typed.disarmed", "test:taken", FOE,
                                expires_on="UNTIL_REMOVED", data={"disables_action": owner_weapon, "held_by": FOE})
        weapon = owner_weapon
    asked = []

    def provider(request):
        asked.append(request)
        defending = request["reaction_source_id"].endswith("Choose defending skill")
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if decline and not defending else "USE",
                                option_ids=() if decline and not defending else (skill if defending else weapon,)), None

    engine._gate4_reaction_provider = provider
    events = _strike(engine)
    return engine, events, asked, weapon


@pytest.mark.parametrize("skill", ["Athletics", "Acrobatics"])
def test_open_hand_second_attack_contests_targets_chosen_skill_and_drops_exact_weapon(skill):
    engine, events, asked, weapon = _open_hand_run(skill=skill)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == OPEN_HAND]
    assert len(checks) == 1 and checks[0].payload["against"] == skill
    assert checks[0].payload["success"]
    assert asked[1]["reactor_id"] == FOE
    assert "Open-Hand Disarm" in asked[1]["choice_trigger"]["prompt"]
    assert STRIKE in asked[1]["choice_trigger"]["prompt"]
    state = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith("disarmed"))
    assert state.data == {"disables_action": weapon, "dropped_at": {"x": 4, "y": 6}}
    assert any(c.condition_id == mark_condition_id("Opened", ME) for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.source_definition_id.endswith(".open_the_gate") for e in events)
    assert not engine.state.actors[ME].turn_flags.get("open_the_gate")


def test_open_hand_lost_contest_still_forgoes_gate_without_disarming():
    engine, events, _, _ = _open_hand_run(lose=True)
    assert not next(e for e in events if e.event_type == "CHECK_ROLLED").payload["success"]
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.source_definition_id.endswith(".open_the_gate") for e in events)


@pytest.mark.parametrize("case", ["decline", "unowned", "miss"])
def test_open_hand_negative_controls_preserve_ordinary_gate(case):
    engine, events, asked, _ = _open_hand_run(owns=case != "unowned", decline=case == "decline", miss=case == "miss")
    assert not any(e.source_definition_id == OPEN_HAND and e.event_type == "CHECK_ROLLED" for e in events)
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())
    if case != "miss":
        assert any(e.source_definition_id.endswith(".open_the_gate") for e in events)
    if case in ("miss", "unowned"):
        assert not asked


def test_open_hand_hit_qualifies_without_damage_and_drop_survives_weapon_pickup():
    engine, events, _, weapon = _open_hand_run(immune=True)
    assert any(e.source_definition_id == OPEN_HAND and e.payload.get("success") for e in events)
    assert not any(c.condition_id == mark_condition_id("Opened", ME) for c in engine.state.actors[FOE].conditions.values())
    _foe_turn(engine)
    pickup = engine.action_catalog[weapon + ".pickup"].display_name
    candidate = next(c for c in engine.legal_candidates() if c.display_name == pickup)
    engine.execute_intent(ActionIntent(intent_id="open-hand-pickup", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=FOE, target_ids=candidate.target_ids))
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("two_handed,size,expected_actor,expected_target", [
    (True, None, "DISADVANTAGE", "NORMAL"), (False, 2, "NORMAL", "ADVANTAGE"),
    (False, -2, "NORMAL", "DISADVANTAGE")])
def test_open_hand_hand_and_size_modes_apply_only_to_contest(two_handed, size, expected_actor, expected_target):
    _, events, _, _ = _open_hand_run(two_handed=two_handed, size=size)
    check = next(e for e in events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == OPEN_HAND)
    assert check.payload["actor"]["mode"] == expected_actor
    assert check.payload["target"]["mode"] == expected_target
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == "NORMAL"


def test_open_hand_transferred_weapon_returns_to_ground_under_original_owner():
    engine, _, _, weapon = _open_hand_run(transferred=True)
    dropped = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id.endswith("disarmed"))
    assert dropped.data == {"disables_action": weapon, "dropped_at": {"x": 4, "y": 6}}
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())


def test_open_hand_tie_keeps_the_weapon_held():
    _, events, _, _ = _open_hand_run()
    previous = next(e.payload for e in events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == OPEN_HAND)
    bonus = previous["modified_total"] - previous["target"]["natural_result"]
    engine, events, _, _ = _open_hand_run(defending_bonus=bonus)
    check = next(e.payload for e in events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == OPEN_HAND)
    assert check["modified_total"] == check["target"]["total"]
    assert not check["success"]
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())


def test_open_hand_forgo_does_not_leak_to_a_subsequent_hit():
    engine, _, _, _ = _open_hand_run()
    A._ready(engine)
    events = _strike(engine)
    assert any(e.source_definition_id.endswith(".open_the_gate") for e in events)


def _open_hand_table(tmp_path, *, attacker=ME):
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    bundles = []
    for actor in (ME, FOE):
        sheet = A._sheet(IRON_FIST if actor == attacker else None, [OPEN_HAND] if actor == attacker else [], KIT)
        sheet["ability_scores_and_statistics"]["skills"] = [{"skill": name, "bonus": -100}
                                                           for name in ("Athletics", "Acrobatics")]
        bundle = compile_character(sheet, actor_id=actor, reaction_plan={"ask": True})
        bundle["actor_template"].update(armor_class=0, maximum_hp=400, speed_ft=0,
                                        initiative_bonus=100 if actor == attacker else -100)
        for action in bundle["action_catalog"]:
            if action["display_name"] == STRIKE:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
                damage = action["parameters"]["typed"]["weapon"]["damage"]
                # Supply the actual damage expectation in this trigger fixture:
                # inherited generic maneuver compilation leaves its score zero.
                action["parameters"]["expected_damage"] = damage["count"] * (damage["sides"] + 1) // 2 + damage["modifier"]
        if actor == attacker:
            # Force the relevant triggering action in this AI/table fixture;
            # a higher-scoring axe attack cannot exercise an unarmed-hit rider.
            bundle["action_catalog"] = [a for a in bundle["action_catalog"] if ".weapon." not in a["source_definition_id"]]
            retained = {a["source_definition_id"] for a in bundle["action_catalog"]}
            bundle["actor_template"]["action_ids"] = [aid for aid in bundle["actor_template"]["action_ids"] if aid in retained]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="OPEN-HAND", typed_bundles=tuple(bundles),
                                              roster_setup={"primary_actor_ids": [ME, FOE],
                                                            "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                            "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    return combat, TabletopService(combat, tmp_path), session.match_id


def test_open_hand_table_both_player_choices_rollback_and_drop_reload(tmp_path):
    from combat.gate5_service import CombatService

    combat, table, match_id = _open_hand_table(tmp_path)
    menu = table.state(match_id)["menu"]
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"] if c["display_name"] == STRIKE)
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")

    def act(answers):
        return table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)

    result = act([])
    assert result["status"] == "REACTION_REQUIRED"
    first = result["reaction"]
    assert first["context"]["reactor_id"] == ME
    weapon = [o["id"] for o in first["choice"]["options"]][0]
    answer = {**first["context"], "selection": "USE", "option_ids": [weapon]}
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    result = act([answer])
    assert result["status"] == "REACTION_REQUIRED"
    second = result["reaction"]
    assert second["context"]["reactor_id"] == FOE
    assert [o["id"] for o in second["choice"]["options"]] == ["Athletics", "Acrobatics"]
    assert "Open-Hand Disarm" in second["moment"] and STRIKE in second["moment"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    defend = {**second["context"], "selection": "USE", "option_ids": ["Acrobatics"]}
    assert act([answer, defend])["status"] == "COMMITTED"
    engine = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    state = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith("disarmed"))
    assert state.data == {"disables_action": weapon, "dropped_at": {"x": 4, "y": 6}}
    assert engine.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")


def test_open_hand_manual_defender_is_asked_on_ai_attack_turn(tmp_path):
    combat, table, match_id = _open_hand_table(tmp_path, attacker=FOE)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "MANUAL"})
    combat._write_metadata(match_id, metadata)
    # The attacker chooses automatically; only the manual defender answers.
    result = table.auto_step(match_id, 0)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == ME
    assert [o["id"] for o in prompt["choice"]["options"]] == ["Athletics", "Acrobatics"]
    assert "Open-Hand Disarm" in prompt["moment"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["Athletics"]}
    assert table.auto_step(match_id, 0, [answer])["status"] != "REACTION_REQUIRED"


def test_open_hand_ai_defender_chooses_automatically(tmp_path):
    combat, table, match_id = _open_hand_table(tmp_path)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "LOCAL_AUTO"})
    combat._write_metadata(match_id, metadata)
    assert table.auto_step(match_id, 0)["status"] != "REACTION_REQUIRED"
    assert any(c.condition_id.endswith("disarmed") for c in combat._load_session(match_id).engine.state.actors[FOE].conditions.values())


def _counter_form_run(*, form="TAL_IRON_FIST_BREAKING_KNUCKLE", decline=False, grapple=False, opened=False,
                      owns=True, focus=1, miss=False, immune=False, bell_option=None):
    from combat.gate2_runtime_models import ReactionDecision
    engine = _duel((["TAL_IRON_FIST_COUNTER_PALM"] if owns else []) + [form]
                   + ([BELL] if bell_option else []), dc=FAIL)
    _foe_turn(engine)
    engine.state.actors[ME].armor_class = 1000
    engine.state.actors[ME].resources["resource:core.martial_focus"] = focus
    if miss:
        engine.state.actors[FOE].armor_class = 1000
    if immune:
        engine._add_modifier(engine.state.actors[FOE], "test:immunity", "damage_immunity", "ADD", "BLUDGEONING",
                             "SELF", expires_on="UNTIL_REMOVED")
    if opened:
        _open(engine)
    if grapple:
        engine._apply_condition(engine.state.actors[FOE], "condition:typed.grappled", "test:grapple", ME,
                                expires_on="UNTIL_REMOVED")
    asked = []

    def provider(request):
        asked.append(request)
        is_form = request["reaction_source_id"] == "choice:needle.iron_forms"
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if is_form and decline else "USE",
                                option_ids=(form,) if is_form and not decline else
                                (bell_option,) if request["reaction_source_id"] == "choice:needle.iron_bell" else
                                (request["legal_option_ids"][0],) if request["reaction_source_id"] == "choice:needle.iron_elbow" else ()), None

    engine._gate4_reaction_provider = provider
    _foe_attacks(engine)
    return engine, [r for r in asked if r["reaction_source_id"] in ("choice:needle.iron_forms", "choice:needle.iron_bell")]


ELBOW = "TAL_IRON_FIST_ELBOW_IN_THE_DOOR"


def test_counter_palm_elbow_selects_shared_space_for_only_the_damaged_target():
    from combat import zones
    from combat.ext import placed

    engine, asked = _counter_form_run(form=ELBOW)
    assert asked and asked[0]["legal_option_ids"] == [ELBOW]
    assert placed.of(engine, "iron_elbow")
    zone, = placed.of(engine, "iron_elbow")
    assert zone.affected_cells[0].model_dump() == {"x": 3, "y": 5}
    assert zones.difficult_cells(engine, engine.state.actors[FOE]) == {(3, 5)}
    assert zones.difficult_cells(engine, engine.state.actors[ME]) == set()
    _foe_turn(engine)
    assert placed.of(engine, "iron_elbow")
    engine.state.current_actor_id = ME
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine._system_start_turn()
    assert not placed.of(engine, "iron_elbow")


@pytest.mark.parametrize("case", ["decline", "immune", "miss", "not_owned"])
def test_counter_palm_elbow_negative_controls(case):
    from combat.ext import placed

    engine, _ = _counter_form_run(form=ELBOW, decline=case == "decline", immune=case == "immune",
                                 miss=case == "miss", owns=case != "not_owned")
    assert not placed.of(engine, "iron_elbow")


def test_elbow_ordinary_form_uses_same_terrain_and_actual_path_cost():
    from combat import zones
    from combat.ext import placed
    engine = _duel([ELBOW])
    action = next(a for a in engine.action_catalog.values() if a.display_name == STRIKE)
    A._use(engine, action.display_name, FOE)
    assert placed.of(engine, "iron_elbow")
    zone, = placed.of(engine, "iron_elbow")
    cell = zone.affected_cells[0]
    _foe_turn(engine)
    candidates = engine.legal_candidates()
    step = next(c for c in candidates if c.destination == cell and c.display_name.startswith("Move"))
    # The canonical path takes two steps around the occupied corner: 5 + 10.
    assert len(step.canonical_path) == 3
    assert step.movement_cost_ft == 15
    engine.execute_intent(ActionIntent(intent_id="elbow-move", decision_id=step.decision_id,
                                      candidate_id=step.candidate_id, state_version=step.state_version,
                                      actor_id=FOE, destination=cell))
    assert engine.state.actors[FOE].position == cell
    # A distinct overlapping area must retain its ordinary policy for the striker.
    placed.place(engine, engine.state.actors[FOE], source=action.source_definition_id, tag="test_overlap",
                 cells=[cell], name="Other terrain", difficult="all")
    assert zones.difficult_cells(engine, engine.state.actors[ME]) == {(cell.x, cell.y)}


def test_elbow_legal_shared_cells_use_footprints_and_map_bounds():
    from combat.ext.iron_elbow import shared_spaces

    engine = _duel([ELBOW])
    cells = shared_spaces(engine, engine.state.actors[ME], engine.state.actors[FOE])
    assert (3, 6) not in cells and (4, 6) not in cells
    engine.grid.blocked.add(cells[0])
    assert cells[0] not in shared_spaces(engine, engine.state.actors[ME], engine.state.actors[FOE])


def test_counter_palm_elbow_table_choices_rollback_commit_and_reload(tmp_path):
    from combat.gate5_service import CombatService
    from combat.ext import placed
    from combat import zones

    combat, table, match_id = _empty_palm_table(tmp_path, counter=True, counter_form=ELBOW)
    menu = table.state(match_id)["menu"]
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                     if c["display_name"].startswith("Fu (Short Axe) attack") and c["target_ids"] == [ME]
                     and "#" not in c["source_definition_id"])
    def act(answers):
        return table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    result = act([])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert [o["id"] for o in prompt["choice"]["options"]] == [ELBOW]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": [ELBOW]}
    result = act([answer])
    assert result["status"] == "REACTION_REQUIRED"
    space = result["reaction"]
    assert "Elbow in the Door" in space["moment"]
    assert "Counter Palm" in space["moment"]
    cell = [o["id"] for o in space["choice"]["options"]][0]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    chosen = {**space["context"], "selection": "USE", "option_ids": [cell]}
    result = act([answer, chosen])
    assert result["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    zone, = placed.of(reloaded, "iron_elbow")
    assert zone.trigger_profile["difficult_target_ids"] == [FOE]
    assert zones.difficult_cells(reloaded, reloaded.state.actors[FOE]) == {tuple(map(int, cell.split(",")))}
    assert zones.difficult_cells(reloaded, reloaded.state.actors[ME]) == set()
    assert reloaded.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")


def test_counter_palm_offers_owned_breaking_knuckle_after_damaging_hit():
    engine, asked = _counter_form_run(opened=True)
    assert asked and asked[0]["legal_option_ids"] == ["TAL_IRON_FIST_BREAKING_KNUCKLE"]
    assert "Counter Palm" in asked[0]["choice_trigger"]["prompt"]
    condition = next(c for c in engine.state.actors[FOE].conditions.values()
                     if c.condition_id.endswith("concentration_mode"))
    assert condition.expires_on == "END_OF_SOURCE_TURN_AT:2"
    assert condition.data["rule"]["next"] is True
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 0
    engine._expire_typed_for_checkpoint("END_OF_TURN", FOE)
    assert condition.instance_id in engine.state.actors[FOE].conditions
    engine.state.current_actor_id = ME
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine._system_start_turn()
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert condition.instance_id not in engine.state.actors[FOE].conditions


def test_counter_palm_new_opening_does_not_count_as_already_opened():
    engine, asked = _counter_form_run()
    assert asked
    assert not any(c.condition_id.endswith("concentration_mode") for c in engine.state.actors[FOE].conditions.values())


def test_counter_palm_form_can_be_declined():
    engine, asked = _counter_form_run(opened=True, decline=True)
    assert asked
    assert not any(c.condition_id.endswith("concentration_mode") for c in engine.state.actors[FOE].conditions.values())
    used, _ = _counter_form_run(opened=True)
    assert engine.state.actors[FOE].current_hp - used.state.actors[FOE].current_hp == int(used.state.actors[ME].proficiency_bonus)


@pytest.mark.parametrize("case", ["not_owned", "no_focus", "miss"])
def test_counter_palm_form_is_inert_without_a_paid_owned_hit(case):
    engine, asked = _counter_form_run(owns=case != "not_owned", focus=0 if case == "no_focus" else 1,
                                     miss=case == "miss", opened=True)
    assert not asked
    assert not any(c.condition_id.endswith("concentration_mode") for c in engine.state.actors[FOE].conditions.values())


def test_counter_palm_damage_forms_require_actual_damage():
    engine, asked = _counter_form_run(immune=True, opened=True)
    assert not asked
    assert engine.state.actors[FOE].current_hp == 400
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 0


def test_counter_palm_rising_knee_requires_a_grapple():
    engine, asked = _counter_form_run(form="TAL_IRON_FIST_RISING_KNEE")
    assert not asked
    engine, asked = _counter_form_run(form="TAL_IRON_FIST_RISING_KNEE", grapple=True, opened=True)
    assert asked
    assert any(m.target_field == "speed_ft" and m.value == -10 for m in engine.state.actors[FOE].modifiers.values())


def _empty_palm_engine(*, owns=True, focus=1, miss=False):
    talents = ["TAL_IRON_FIST_IRON_FOREARM_GUARD"] + (["TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE"] if owns else [])
    engine = _duel(talents)
    _foe_turn(engine)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.maximum_hp = me.current_hp = 400
    me.resources["resource:core.martial_focus"] = focus
    foe.armor_class = 1000 if miss else -50
    weapon = next(engine.action_catalog[aid] for aid in foe.action_ids
                  if engine.action_catalog[aid].display_name.startswith("Fu (Short Axe) attack") and "#" not in aid)
    typed = weapon.parameters["typed"]
    typed["numbers"]["attack_bonus"] = 100
    typed["weapon"]["fixed_damage"] = 40
    for row in typed["effects"]:
        if row.get("type") == "attack":
            row["count"] = 1
    return engine, weapon


def _empty_palm_attack(engine, weapon, option, *, decline=False):
    from combat.gate2_runtime_models import ReactionDecision
    asked = []

    def provider(request):
        asked.append(request)
        choices = request.get("legal_option_ids") or []
        pick = option if option in choices else "5,6" if "5,6" in choices else choices[0] if choices else None
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"],
                                selection="DECLINE" if decline and "Expend Martial Focus" in request["reaction_source_id"] else "USE",
                                option_ids=() if decline and "Expend Martial Focus" in request["reaction_source_id"] else (pick,) if pick else ()), None

    engine._gate4_reaction_provider = provider
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == weapon.source_definition_id and c.target_ids == (ME,))
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="empty-palm-trigger", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=FOE, target_ids=(ME,)))
    return engine.events[start:], asked


def test_empty_palm_opened_choice_rolls_spends_focus_and_does_not_deal_strike_damage():
    engine, weapon = _empty_palm_engine()
    foe_hp = engine.state.actors[FOE].current_hp
    events, asked = _empty_palm_attack(engine, weapon, "Make Opened")
    assert _bears(engine, FOE, "Opened")
    assert engine.state.actors[FOE].current_hp == foe_hp
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 0
    roll = next(e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == ME)
    assert roll.source_definition_id == "TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE"
    assert any(set(r.get("legal_option_ids") or []) == {"Disarm", "Reduce damage by 2d8", "Make Opened"} for r in asked)
    assert all("Empty Palm Stops the Blade" in r.get("choice_trigger", {}).get("prompt", "")
               for r in asked if r.get("extension_choice"))


def test_empty_palm_damage_choice_is_only_2d8_extra_reduction():
    engine, weapon = _empty_palm_engine()
    events, _ = _empty_palm_attack(engine, weapon, "Reduce damage by 2d8")
    base, base_weapon = _empty_palm_engine()
    _empty_palm_attack(base, base_weapon, "Make Opened", decline=True)
    rolls = [r for r in engine.rolls if r.reason.endswith(":reduction")]
    assert len(rolls) == 1
    assert engine.state.actors[ME].current_hp - base.state.actors[ME].current_hp == rolls[0].total
    assert not _bears(engine, FOE, "Opened")
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())


def test_empty_palm_disarms_exact_triggering_weapon_to_selected_adjacent_cell():
    engine, weapon = _empty_palm_engine()
    events, asked = _empty_palm_attack(engine, weapon, "Disarm")
    dropped = next((c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith("disarmed")), None)
    assert dropped is not None
    assert dropped.data["disables_action"] == weapon.source_definition_id
    assert dropped.data["dropped_at"] == {"x": 5, "y": 6}
    assert dropped.expires_on == "UNTIL_REMOVED"
    assert not _bears(engine, FOE, "Opened")
    A._ready(engine)
    assert not any(c.source_definition_id == weapon.source_definition_id for c in engine.legal_candidates())
    assert any("Disarm adjacent space" in r["reaction_source_id"] for r in asked)


@pytest.mark.parametrize("case", ["miss", "decline", "no_focus", "not_owned"])
def test_empty_palm_failure_decline_and_ownership_are_inert(case):
    engine, weapon = _empty_palm_engine(owns=case != "not_owned", focus=0 if case == "no_focus" else 1, miss=case == "miss")
    events, asked = _empty_palm_attack(engine, weapon, "Make Opened", decline=case == "decline")
    assert not _bears(engine, FOE, "Opened")
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == (0 if case in ("miss", "no_focus") else 1)
    if case in ("no_focus", "not_owned"):
        assert not any("empty_palm" in r["reaction_source_id"] for r in asked)
    assert not any("Choose one on hit" in r["reaction_source_id"] for r in asked)


def _empty_palm_table(tmp_path, *, ask=False, counter=False, counter_form="TAL_IRON_FIST_BREAKING_KNUCKLE", bell=False,
                      foe_melee_only=False):
    from combat.canonical import canonical_sha256
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    talents = (["TAL_IRON_FIST_COUNTER_PALM", counter_form] if counter else
               ["TAL_IRON_FIST_IRON_FOREARM_GUARD", "TAL_IRON_FIST_EMPTY_PALM_STOPS_THE_BLADE"])
    if bell:
        talents.append(BELL)
    me = compile_character(A._sheet(IRON_FIST, talents, KIT),
                           actor_id=ME, reaction_plan={"ask": True} if ask else None)
    foe = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    for bundle in (me, foe):
        bundle["actor_template"].update(armor_class=1000 if counter and bundle is me else 0, maximum_hp=400, speed_ft=0,
                                        initiative_bonus=100 if bundle is foe else -100)
        if bundle is foe:
            if foe_melee_only:
                bundle["action_catalog"] = [a for a in bundle["action_catalog"] if (a.get("range_ft") or 5) <= 5]
                retained = {a["source_definition_id"] for a in bundle["action_catalog"]}
                bundle["actor_template"]["action_ids"] = [aid for aid in bundle["actor_template"]["action_ids"] if aid in retained]
            for action in bundle["action_catalog"]:
                if action["display_name"].startswith("Fu (Short Axe) attack"):
                    typed = action["parameters"]["typed"]
                    typed["numbers"]["attack_bonus"] = 100
                    typed["weapon"]["fixed_damage"] = 40
                    for row in typed["effects"]:
                        if row.get("type") == "attack":
                            row["count"] = 1
        elif counter:
            for action in bundle["action_catalog"]:
                if action["display_name"] == STRIKE:
                    action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="RIDERS2", typed_bundles=(me, foe),
                                              roster_setup={"primary_actor_ids": [ME, FOE],
                                                            "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                            "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    return combat, TabletopService(combat, tmp_path), session.match_id


@pytest.mark.parametrize("option", ["Make Opened", "Disarm"])
def test_empty_palm_table_prompts_and_commit_reload_preserve_chosen_result(tmp_path, option):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    combat, table, match_id = _empty_palm_table(tmp_path)
    menu = table.state(match_id)["menu"]
    assert menu["actor_id"] == FOE
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                     if c["display_name"].startswith("Fu (Short Axe) attack") and c["target_ids"] == [ME]
                     and "#" not in c["source_definition_id"])
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    answers = []
    prompts = []
    for _ in range(5):
        result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        picked = option if option in options else "5,6" if "5,6" in options else options[0] if options else None
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [picked] if picked else []})
    assert result["status"] == "COMMITTED"
    assert len(prompts) == (3 if option == "Disarm" else 2)
    assert all("Empty Palm Stops the Blade" in p["moment"] and "Fu (Short Axe)" in p["moment"] for p in prompts)
    fresh = CombatService(ROOT, tmp_path)
    reloaded = fresh._load_session(match_id).engine
    if option == "Make Opened":
        assert _bears(reloaded, FOE, "Opened")
        mark = next(c for c in reloaded.state.actors[FOE].conditions.values() if "mark.opened" in c.condition_id)
        assert mark.expires_on == "END_OF_MARKER_NEXT_TURN"
    else:
        dropped = next(c for c in reloaded.state.actors[FOE].conditions.values() if c.condition_id.endswith("disarmed"))
        assert dropped.data == {"disables_action": candidate["source_definition_id"], "dropped_at": {"x": 5, "y": 6}}
        assert dropped.expires_on == "UNTIL_REMOVED"
        assert TabletopService(fresh, tmp_path).state(match_id)["items"]


@pytest.mark.parametrize("primed", [False, True])
def test_counter_palm_table_form_prompt_commits_and_reloads_damage(tmp_path, primed):
    from combat.gate5_service import CombatService

    combat, table, match_id = _empty_palm_table(tmp_path, counter=True)
    if primed:
        # Open the opponent through a real preceding player turn, then Counter
        # Palm on its next turn. No saved-state injection bypasses persistence.
        def take(source):
            view = table.state(match_id)["menu"]
            candidates = combat.decision(match_id)["context"]["legal_candidates"]
            picked = next(c for c in candidates if c["display_name"].lower() == source.lower())
            assert table.act(match_id, picked["candidate_id"], view["decision_id"], view["state_version"], 0)["status"] == "COMMITTED"

        take("End Turn")
        take(STRIKE)
        take("End Turn")
    menu = table.state(match_id)["menu"]
    candidate = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                     if c["display_name"].startswith("Fu (Short Axe) attack") and c["target_ids"] == [ME]
                     and "#" not in c["source_definition_id"])
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [])
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert [o["id"] for o in prompt["choice"]["options"]] == ["TAL_IRON_FIST_BREAKING_KNUCKLE"]
    assert "Counter Palm" in prompt["moment"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["TAL_IRON_FIST_BREAKING_KNUCKLE"]}
    result = table.act(match_id, candidate["candidate_id"], menu["decision_id"], menu["state_version"], 0, [answer])
    assert result["status"] == "COMMITTED"
    committed = combat._load_session(match_id).engine.state.model_dump(mode="json")
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id).engine.state.model_dump(mode="json")
    assert reloaded == committed
    assert reloaded["actors"][FOE]["current_hp"] < 400
    assert reloaded["actors"][ME]["resources"]["resource:core.martial_focus"] == 0
    if primed:
        conditions = reloaded["actors"][FOE]["conditions"].values()
        mode = next(c for c in conditions if c["condition_id"].endswith("concentration_mode"))
        assert mode["data"]["rule"]["next"] is True
        assert mode["expires_on"] == "END_OF_SOURCE_TURN_AT:2"


@pytest.mark.parametrize("form", ["TAL_IRON_FIST_BREAKING_KNUCKLE", ELBOW])
def test_counter_palm_manual_ask_on_ai_turn_then_automatic_form_for_ai(tmp_path, form):
    combat, table, match_id = _empty_palm_table(tmp_path, counter=True, ask=True, counter_form=form)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "MANUAL"})
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reaction_source_id"] == "reaction:typed.TAL_IRON_FIST_COUNTER_PALM"
    answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": []}
    result = table.auto_step(match_id, 0, [answer])
    assert result["status"] == "REACTION_REQUIRED"
    assert "Counter Palm" in result["reaction"]["moment"]
    assert [o["id"] for o in result["reaction"]["choice"]["options"]] == [form]
    metadata["participant_control_modes"][ME] = "LOCAL_AUTO"
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    assert result["status"] != "REACTION_REQUIRED"
    assert combat._load_session(match_id).engine.state.actors[FOE].current_hp < 400


def test_empty_palm_prompts_player_on_ai_turn_and_ai_defender_chooses_automatically(tmp_path):
    combat, table, match_id = _empty_palm_table(tmp_path, ask=True)
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: "MANUAL"})
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == ME
    assert result["reaction"]["context"]["reaction_source_id"] == "reaction:typed.TAL_IRON_FIST_IRON_FOREARM_GUARD"
    answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": []}
    result = table.auto_step(match_id, 0, [answer])
    assert result["status"] == "REACTION_REQUIRED"
    assert "Empty Palm Stops the Blade" in result["reaction"]["moment"]
    # The same unresolved AI turn now gives control of the defender to the AI.
    metadata["participant_control_modes"][ME] = "LOCAL_AUTO"
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    assert result["status"] != "REACTION_REQUIRED"
    loaded = combat._load_session(match_id).engine
    assert loaded.state.actors[ME].resources["resource:core.martial_focus"] == 0
    assert any(c.condition_id.endswith("disarmed") for c in loaded.state.actors[FOE].conditions.values())


def test_empty_palm_opened_expires_at_end_of_defenders_next_turn():
    engine, weapon = _empty_palm_engine()
    _empty_palm_attack(engine, weapon, "Make Opened")
    engine.end_turn()
    assert _bears(engine, FOE, "Opened")
    assert engine.state.current_actor_id == ME
    assert _bears(engine, FOE, "Opened")
    engine.end_turn()
    assert not _bears(engine, FOE, "Opened")


@pytest.mark.parametrize("packet", ["zero", "ranged", "unarmed", "cultivation"])
def test_empty_palm_requires_actual_melee_weapon_damage_reduction(packet):
    engine, weapon = _empty_palm_engine()
    typed = weapon.parameters["typed"]
    if packet == "zero":
        engine._add_modifier(engine.state.actors[ME], "test:immune", "damage_immunity", "SET",
                             typed["weapon"]["damage_type"], "SELF", expires_on="UNTIL_REMOVED")
    elif packet == "ranged":
        typed["range_ft"] = 20
    else:
        next(e for e in typed["effects"] if e.get("type") == "attack")["attack_kind"] = packet
    _, asked = _empty_palm_attack(engine, weapon, "Make Opened")
    assert not any("empty_palm" in r["reaction_source_id"] for r in asked)
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 1


def test_empty_palm_disarms_a_taken_weapon_back_to_ground_for_original_owner():
    engine, weapon = _empty_palm_engine()
    me = engine.state.actors[ME]
    original = next(aid for aid in me.action_ids if ".weapon.fu" in aid and "#" not in aid and not aid.endswith(".pickup"))
    weapon.parameters["requires_held_weapon"] = original
    engine._apply_condition(me, "condition:typed.disarmed", "test:taken", FOE, expires_on="UNTIL_REMOVED",
                            data={"disables_action": original, "held_by": FOE})
    _empty_palm_attack(engine, weapon, "Disarm")
    returned = next(c for c in me.conditions.values() if c.data.get("disables_action") == original)
    assert returned.data == {"disables_action": original, "dropped_at": {"x": 5, "y": 6}}
    assert not any(c.condition_id.endswith("disarmed") for c in engine.state.actors[FOE].conditions.values())


def test_table_reaction_dialog_returns_bounded_option_ids_and_restores_legacy_buttons():
    import json
    import shutil
    import subprocess

    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    functions = source[source.index("function decisionText(prompt) {"):source.index("async function withReactions(send) {")]
    # Execute round17's actual choice and legacy dialog functions. This models
    # bounded checkbox selection and cancel, without claiming rendered UI QA.
    script = r'''
      const buttons=['USE','DECLINE'].map(answer=>({dataset:{answer},hidden:false}));
      let picked=[];
      const text={innerHTML:''};
      const dialog={querySelectorAll:selector=>selector==='[data-answer]'?buttons:
        selector.includes('input:checked')?picked:[],
        addEventListener:(_,fn)=>dialog.cancel=fn,removeEventListener:()=>{},close:()=>{},showModal:()=>{}};
      const $=selector=>selector==='#ttReaction'?dialog:text;
      const escapeHtml=value=>String(value);
      const toast=()=>{};
      const app={matchId:'test'};
      const closeChoice=()=>{};
      FUNCTIONS
      let resolved=false;
      const choice=askReaction({reactor:'Player',reaction:'Choice',moment:'Choose two',
        choice:{options:['A','B','C'].map(id=>({id,label:id})),minimum:2,maximum:2,allow_decline:false,preferred:[]}});
      choice.then(()=>resolved=true);
      picked=[{value:'A'},{value:'B'},{value:'C'}];
      buttons[0].onclick(); dialog.cancel({preventDefault(){}});
      await Promise.resolve();
      if(resolved) throw Error('accepted illegal selection or cancel');
      picked=[{value:'B'},{value:'C'}]; buttons[0].onclick();
      const answer=await choice;
      if(JSON.stringify(answer)!==JSON.stringify({selection:'USE',option_ids:['B','C']})) throw Error('lost options');
      if(buttons.some(b=>b.hidden)) throw Error('buttons not restored');
      const legacy=askReaction({reactor:'Player',reaction:'Guard',moment:'hit'});
      buttons[1].onclick();
      if(await legacy!=='DECLINE') throw Error('legacy decline');
      console.log('PASS');
    '''.replace("FUNCTIONS", functions)
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PASS"


def _diagnosis_engine(*, target_dc=-40):
    sheet = A._sheet(IRON_FIST, ["TAL_IRON_FIST_EIGHT_GATE_DIAGNOSIS"], KIT)
    sheet["ability_scores_and_statistics"]["skills"] = [{"skill": "Medicine", "bonus": 12}, {"skill": "Investigation", "bonus": 9}]
    sheet["ability_scores_and_statistics"]["technique_attack_bonus"] = 123  # not a Cultivation Check bonus
    me = compile_character(sheet, actor_id=ME)
    foe = compile_character(A._sheet(None, [], KIT, dc=target_dc), actor_id=FOE)
    ally = compile_character(A._sheet(None, [], KIT, dc=target_dc), actor_id=ALLY)
    engine = Gate4ControllerEngine(ROOT, match_seed="DIAGNOSIS", typed_bundles=(me, foe, ally),
                                   roster_setup={"primary_actor_ids": [ME, FOE, ALLY],
                                                 "team_by_actor": {ME: "team:a", FOE: "team:b", ALLY: "team:a"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, ALLY: {"x": 2, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor in engine.state.actors.values():
        actor.maximum_hp = actor.current_hp = 400
        actor.armor_class = -50
    A._ready(engine)
    return engine


def _diagnose(engine, *, check="Wisdom (Medicine)", facts=("Bloodied", "Weakest physical save"), target=FOE):
    asked = _answer_options(engine, lambda r: [target] if r["reaction_source_id"].endswith("Diagnosis creature")
                            else [check] if r["reaction_source_id"].endswith("Diagnosis check")
                            else list(facts) if r["reaction_source_id"].endswith("Diagnosis information")
                            else r["legal_option_ids"][:1])
    return A._use(engine, "Eight-Gate Diagnosis", ME), asked


@pytest.mark.parametrize("label,bonus", [("Wisdom (Medicine)", 12), ("Intelligence (Investigation)", 9), ("Cultivation Check", 7)])
def test_eight_gate_diagnosis_rolls_one_chosen_check_against_target_dc(label, bonus):
    engine = _diagnosis_engine()
    events, asked = _diagnose(engine, check=label)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert len(checks) == 1
    assert checks[0].payload["actor"]["modifier"] == bonus
    assert checks[0].payload["skill"] == label and checks[0].payload["dc"] == -40
    assert not engine.state.actors[ME].action_available
    assert any(r["extension_choice"]["maximum_selections"] == 2 and r["extension_choice"]["minimum_selections"] == 2 for r in asked)


def test_eight_gate_diagnosis_reveals_bloodied_boundary_and_tied_weakest_saves():
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    foe.current_hp = 200  # half HP is Bloodied
    foe.saving_throws.update(STR=9, DEX=-2, CON=-2)
    events, _ = _diagnose(engine)
    answers = [e.payload["text"] for e in events if e.event_type == "PASSIVE_TRIGGERED" and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert len(answers) == 2 and any("is Bloodied" in s for s in answers)
    assert any("DEX, CON (tied)" in s for s in answers)
    A._ready(engine)
    foe.current_hp = 201
    events, _ = _diagnose(engine)
    assert any("is not Bloodied" in e.payload.get("text", "") for e in events)


def test_eight_gate_diagnosis_failure_reveals_nothing_and_grants_no_window():
    engine = _diagnosis_engine(target_dc=100)
    events, asked = _diagnose(engine)
    assert any(e.event_type == "CHECK_ROLLED" and not e.payload["success"] for e in events)
    assert not any("Diagnosis information" in r["reaction_source_id"] for r in asked)
    assert not any(c.condition_id.startswith("condition:typed.iron_diagnosis.") for c in engine.state.actors[ME].conditions.values())


def test_eight_gate_diagnosis_answers_resistance_immunity_and_enhancement_from_real_state():
    """The three facts the table really tracks are answered, not sent to the GM (AUTO118)."""
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine._add_modifier(foe, "test:stone_skin", "damage_resistance", "ADD", "FORCE", "SELF", expires_on=None)
    events, _ = _diagnose(engine, facts=("Resistances", "Immunities"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert len(texts) == 2
    assert any("Resistance to Force damage" in s for s in texts), texts
    # A negative the table cannot support stays a GM answer, never "has none" (AUTO118r1f1).
    assert any("cannot show any immunity to Prone, Grappled, Stunned or forced movement" in s for s in texts), texts
    riders = [e.payload for e in events if e.event_type == "GM_RIDER"
              and "GM reveal whether it is immune to Prone" in str((e.payload or {}).get("rider", ""))]
    assert len(riders) == 1, riders
    # The successful diagnosis still grants its printed Unarmed Strike window.
    assert any(c.condition_id.startswith("condition:typed.iron_diagnosis.") for c in engine.state.actors[ME].conditions.values())


def test_eight_gate_diagnosis_names_condition_immunity_and_keeps_unknown_enhancement_for_gm():
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine._add_modifier(foe, "test:steady", "condition_immunity", "ADD", "prone", "SELF", expires_on=None)
    events, _ = _diagnose(engine, facts=("Immunities", "Bodily or martial enhancement"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert any("is immune to Prone" in s for s in texts), texts
    assert any("cannot show any ongoing bodily or martial enhancement" in s for s in texts), texts


def test_eight_gate_diagnosis_reports_only_the_damage_types_that_are_resisted():
    """Piercing-only Resistance does not become nonmagical physical Resistance (AUTO118r1f1 finding 3)."""
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine._add_modifier(foe, "test:thorns", "damage_resistance", "ADD", "PIERCING", "SELF", expires_on=None)
    events, _ = _diagnose(engine, facts=("Resistances", "Bloodied"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    answer = next(s for s in texts if "Resistance" in s)
    assert "Piercing damage" in answer, answer
    for invented in ("Bludgeoning", "Slashing", "nonmagical physical damage ("):
        assert invented not in answer, answer


def test_eight_gate_diagnosis_does_not_call_a_condition_immunity_forced_movement_immunity():
    """Grappled immunity is not immunity to a push; the push still moves the creature (AUTO118r1f1 finding 3)."""
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine._add_modifier(foe, "test:hold", "condition_immunity", "ADD", "grappled", "SELF", expires_on=None)
    events, _ = _diagnose(engine, facts=("Immunities", "Bloodied"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    answer = next(s for s in texts if "immune" in s)
    assert "is immune to Grappled" in answer, answer
    assert "immune to being pushed" not in answer and "immune to forced movement" not in answer, answer
    assert "is a separate question; the GM answers it" in answer, answer
    assert [e.payload for e in events if e.event_type == "GM_RIDER"
            and "GM reveal whether Factory character is immune to forced movement" in str((e.payload or {}).get("rider", ""))]
    # The same creature is still pushed: that immunity list is not what the movement hooks read.
    from combat.gate2_runtime_models import ActionIntent
    A._ready(engine)
    from tests.h1_support import script
    script(engine, [1])  # the target's Strength save against the shove fails, so the push happens
    before = foe.position.model_copy()
    shove = next(c for c in engine.legal_candidates() if c.display_name == "Shove: Push 5 ft")
    engine.execute_intent(ActionIntent(intent_id="push", decision_id=shove.decision_id, candidate_id=shove.candidate_id,
                                       state_version=shove.state_version, actor_id=ME, target_ids=shove.target_ids,
                                       destination=shove.destination))
    assert foe.position != before, (before, foe.position)


def test_eight_gate_diagnosis_reads_a_compiled_passive_defense_row():
    """A passive resistance row the engine really applies is reported, not missed (AUTO118r1f1 finding 2).

    Deep S's Embrace is a compiled ``defense`` block row: Resistance to Fire damage, from Hell-Tempered-style
    passive blocks. The question here is whether the diagnosis reads that row at all.
    """
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine.typed_passive_rows[FOE] = [{"feature_id": "fixture:hell_tempered", "block": "defense", "kind": "resistance",
                                       "damage_types": ["FORCE"]}]
    events, _ = _diagnose(engine, facts=("Resistances", "Bloodied"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert any("Resistance to Force damage" in s for s in texts), texts


def test_eight_gate_diagnosis_reads_a_condition_rules_immunity():
    """A condition's own rule granting immunity is read, not missed (AUTO118r1f1 finding 2)."""
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, "condition:typed.save_against", "test:rule", ME, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"rule": {"condition_immunities": ["stunned"]}, "label": "Stunned ward"})
    events, _ = _diagnose(engine, facts=("Immunities", "Bloodied"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert any("is immune to Stunned" in s for s in texts), texts


def test_eight_gate_diagnosis_names_a_source_conditioned_passive_defense_with_its_qualification():
    """A weapon-only defense is not reported as general Resistance."""
    engine = _diagnosis_engine()
    foe = engine.state.actors[FOE]
    engine.typed_passive_rows[FOE] = [{"feature_id": "fixture:liquid_body", "block": "defense", "kind": "resistance",
                                       "damage_types": ["BLUDGEONING", "PIERCING", "SLASHING"], "attack_kinds": ["weapon"]}]
    events, _ = _diagnose(engine, facts=("Resistances", "Bloodied"))
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert any("Resistance to nonmagical weapon attack Bludgeoning, Piercing and Slashing damage" in s for s in texts), texts
    assert not any("Resistance to Bludgeoning" in s for s in texts), texts


def test_eight_gate_diagnosis_preserves_unrepresented_information_as_selected_gm_choices():
    """A fact the table cannot see stays a selected GM choice rather than an invented answer."""
    engine = _diagnosis_engine()
    events, _ = _diagnose(engine, facts=("Immunities", "Bodily or martial enhancement"))
    # Nothing on this bare creature supports either answer, so both stay the GM's (AUTO118r1f1) and the
    # player is told the table cannot see them.
    asked = [e.payload.get("rider", "") for e in events if e.event_type == "GM_RIDER"]
    assert any("GM reveal whether it is immune to Prone, Grappled, Stunned or forced movement" in s for s in asked), asked
    assert any("GM reveal whether it is maintaining an ongoing bodily or martial enhancement" in s for s in asked), asked
    texts = [e.payload.get("text", "") for e in events if e.event_type == "PASSIVE_TRIGGERED"
             and "Eight-Gate Diagnosis:" in e.payload.get("text", "")]
    assert len(texts) == 2 and all("cannot show" in s for s in texts), texts
    assert not any("no represented" in s for s in texts), texts
    assert any(c.condition_id.startswith("condition:typed.iron_diagnosis.") for c in engine.state.actors[ME].conditions.values())


def test_eight_gate_diagnosis_advantage_waits_for_target_unarmed_roll_and_miss_consumes():
    engine = _diagnosis_engine()
    _diagnose(engine)
    A._ready(engine)
    weapon = next(n for n in A._legal(engine) if n.startswith("Fu (Short Axe) attack") and ":" not in n)
    _use_on(engine, weapon, FOE)
    assert any(c.condition_id.endswith(FOE) for c in engine.state.actors[ME].conditions.values())
    # An Unarmed Strike against another creature does not spend this target's window.
    engine.state.actors[ALLY].team_id = "team:b"
    A._ready(engine)
    _use_on(engine, STRIKE, ALLY)
    assert any(c.condition_id.endswith(FOE) for c in engine.state.actors[ME].conditions.values())
    engine.state.actors[FOE].armor_class = 1000
    A._ready(engine)
    events = _strike(engine)
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == "ADVANTAGE"
    assert not any(c.condition_id.startswith("condition:typed.iron_diagnosis.") for c in engine.state.actors[ME].conditions.values())
    A._ready(engine)
    events = _strike(engine)
    assert next(e for e in events if e.event_type == "ATTACK_ROLLED").payload["mode"] == "NORMAL"


def test_eight_gate_diagnosis_supports_ally_targets_and_expires_after_users_next_turn():
    engine = _diagnosis_engine()
    events, _ = _diagnose(engine, target=ALLY)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert checks and checks[0].target_ids == (ALLY,)
    me = engine.state.actors[ME]
    assert any(c.condition_id.endswith(ALLY) for c in me.conditions.values())
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert any(c.condition_id.endswith(ALLY) for c in me.conditions.values())
    engine._system_start_turn()
    engine._expire_typed_for_checkpoint("END_OF_TURN", ME)
    assert not any(c.condition_id.startswith("condition:typed.iron_diagnosis.") for c in me.conditions.values())


def test_eight_gate_diagnosis_enforces_thirty_foot_range_and_hidden_target_perception():
    engine = _diagnosis_engine()
    from combat.gate2_runtime_models import Position
    foe = engine.state.actors[FOE]
    foe.position = Position(x=10, y=6)  # 35 feet
    _, asked = _diagnose(engine, target=ME)
    assert asked
    assert FOE not in next(r["legal_option_ids"] for r in asked if r["reaction_source_id"].endswith("Diagnosis creature"))
    A._ready(engine)
    foe.position = Position(x=9, y=6)  # 30 feet
    _, asked = _diagnose(engine, target=ME)
    assert FOE in next(r["legal_option_ids"] for r in asked if r["reaction_source_id"].endswith("Diagnosis creature"))
    A._ready(engine)
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
    _, asked = _diagnose(engine, target=ME)
    assert FOE not in next(r["legal_option_ids"] for r in asked if r["reaction_source_id"].endswith("Diagnosis creature"))


def test_eight_gate_diagnosis_can_study_a_hostile_charmer_without_a_harmful_target_gate():
    engine = _diagnosis_engine()
    engine._apply_condition(engine.state.actors[ME], "condition:typed.charmed", "test:charmed", FOE, expires_on="UNTIL_REMOVED")
    events, _ = _diagnose(engine)
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert checks and checks[0].target_ids == (FOE,)


def test_eight_gate_diagnosis_cultivation_check_uses_key_ability_check_modes():
    engine = _diagnosis_engine()
    engine._apply_condition(engine.state.actors[ME], "condition:typed.check_mode", "test:check_mode", ME,
                            expires_on="UNTIL_REMOVED", data={"rule": {"check_mode": {"STR": "DISADVANTAGE"}}})
    events, _ = _diagnose(engine, check="Cultivation Check")
    checks = [e for e in events if e.event_type == "CHECK_ROLLED"]
    assert checks and checks[0].payload["actor"]["mode"] == "DISADVANTAGE"


def test_tiger_crane_tiger_increases_only_the_next_maneuver_dc():
    engine = _duel(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"])
    _answer_options(engine, lambda r: ["Tiger"] if "Tiger-Crane" in r["reaction_source_id"] else r["legal_option_ids"][:1])
    _strike(engine)
    me = engine.state.actors[ME]
    assert any(c.condition_id == "condition:typed.iron_tiger" for c in me.conditions.values())
    assert not any(c.condition_id == "condition:typed.iron_crane" for c in me.conditions.values())
    A._ready(engine)
    events = A._use(engine, "Shove: Prone", FOE)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves and saves[0].payload["dc"] == 18
    assert not any(c.condition_id == "condition:typed.iron_tiger" for c in me.conditions.values())
    A._ready(engine)
    events = A._use(engine, "Grapple", FOE)
    assert next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE).payload["dc"] == 15


def test_tiger_crane_crane_waits_for_next_strike_and_exempts_only_original_target():
    engine = _trio(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"], sphere=IRON_FIST, ally_at=(2, 5))
    other = engine.state.actors[ALLY]
    other.team_id = "team:b"
    _answer_options(engine, lambda r: ["Crane"] if "Tiger-Crane" in r["reaction_source_id"]
                    else ["cell:2,7"] if r["reaction_source_id"].endswith("iron_fist_step")
                    else r["legal_option_ids"][:1])
    me = engine.state.actors[ME]
    before, movement = me.position, me.movement_remaining_ft
    _use_on(engine, STRIKE, FOE)
    assert me.position == before
    assert any(c.condition_id == "condition:typed.iron_crane" for c in me.conditions.values())
    A._ready(engine)
    events = _use_on(engine, STRIKE, FOE)
    assert (me.position.x, me.position.y) == (2, 7)
    assert me.movement_remaining_ft == movement
    assert engine.state.actors[FOE].reaction_available
    assert not other.reaction_available
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY for e in events)
    assert not any(c.condition_id in ("condition:typed.iron_tiger", "condition:typed.iron_crane") for c in me.conditions.values())


def test_tiger_crane_uses_prestrike_opening_and_does_not_rearm_in_same_turn():
    engine = _duel(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"])
    _open(engine)
    _strike(engine)
    me = engine.state.actors[ME]
    assert {"typed.iron_tiger", "typed.iron_crane"} <= A._conditions(me)
    A._ready(engine)
    A._use(engine, "Grapple", FOE)
    _answer_options(engine, lambda r: [])
    A._ready(engine)
    _strike(engine)
    assert not any(c.condition_id in ("condition:typed.iron_tiger", "condition:typed.iron_crane") for c in me.conditions.values())


def test_tiger_crane_pending_benefits_expire_at_turn_end():
    engine = _duel(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"])
    _open(engine)
    _strike(engine)
    assert "typed.iron_tiger" in A._conditions(engine.state.actors[ME])
    engine._append_event("TURN_ENDED", "test:end", actor_id=ME)
    assert not any(c.condition_id in ("condition:typed.iron_tiger", "condition:typed.iron_crane")
                   for c in engine.state.actors[ME].conditions.values())


def test_tiger_crane_missed_strike_does_not_arm_benefits():
    engine = _duel(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION"])
    engine.state.actors[FOE].armor_class = 100
    _strike(engine)
    assert not any(c.condition_id in ("condition:typed.iron_tiger", "condition:typed.iron_crane")
                   for c in engine.state.actors[ME].conditions.values())


def test_tiger_crane_tiger_preserves_flowing_combinations_marked_save_disadvantage():
    engine = _duel(["TAL_IRON_FIST_TIGER_CRANE_ALTERNATION", "TAL_IRON_FIST_FLOWING_COMBINATION"])
    # Arm Tiger on the first hit, declining the optional Flowing follow-up.
    _answer_options(engine, lambda r: [] if r["reaction_source_id"].endswith("flowing_combination")
                    else ["Tiger"] if "Tiger-Crane" in r["reaction_source_id"] else r["legal_option_ids"][:1])
    _strike(engine)
    _open(engine)
    _answer_options(engine, lambda r: (["Shove: Prone"] if "Shove: Prone" in r["legal_option_ids"] else [])
                    if r["reaction_source_id"].endswith("flowing_combination")
                    else r["legal_option_ids"][:1])
    A._ready(engine)
    events = _strike(engine)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["dc"] == 18 and save.payload["mode"] == "DISADVANTAGE"


def _answer_options(engine, select):
    from combat.gate2_runtime_models import ReactionDecision
    asked = []

    def provider(request):
        asked.append(request)
        options = select(request) if request.get("extension_choice") else []
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="USE",
                                option_ids=tuple(options)), None

    engine._gate4_reaction_provider = provider
    return asked


def test_falling_leaf_sweep_offers_real_secondary_targets_including_an_ally():
    engine = _trio(["TAL_IRON_FIST_FALLING_LEAF_SWEEP"], sphere=IRON_FIST, dc=FAIL, ally_at=(4, 7))
    for actor in engine.state.actors.values():
        actor.saving_throws.update(STR=-100, DEX=-100)
    asked = _answer_options(engine, lambda req: [ALLY] if "Sweep" in req["reaction_source_id"] else req["legal_option_ids"][:1])
    A._use(engine, "Shove: Prone", FOE)
    assert "typed.prone" in A._conditions(engine.state.actors[ALLY])
    assert not _bears(engine, ALLY, "Opened")
    assert any(ALLY in r.get("legal_option_ids", []) and ME in r.get("legal_option_ids", []) for r in asked)


def test_falling_leaf_sweep_opened_target_offers_two_picks_with_independent_saves():
    engine = _trio(["TAL_IRON_FIST_FALLING_LEAF_SWEEP"], sphere=IRON_FIST, dc=FAIL, ally_at=(4, 7))
    for actor in engine.state.actors.values():
        actor.saving_throws.update(STR=-100, DEX=-100)
    _open(engine)
    asked = _answer_options(engine, lambda req: [ME, ALLY] if "Sweep" in req["reaction_source_id"] else req["legal_option_ids"][:1])
    A._use(engine, "Shove: Prone", FOE)
    assert {"typed.prone"} <= A._conditions(engine.state.actors[ME]) & A._conditions(engine.state.actors[ALLY])
    assert any(r.get("extension_choice", {}).get("maximum_selections") == 2 for r in asked)


def test_hammer_and_anvil_can_reapply_open_the_gate_without_extra_focus_recovery():
    engine = _duel(["TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM"])
    me = engine.state.actors[ME]
    A._use(engine, "Choose Hammer-and-Anvil Rhythm: Reapply Open the Gate", None)
    me.resources["resource:core.martial_focus"] = 0
    _strike(engine)
    A._ready(engine)
    events = _strike(engine)
    assert len([e for e in events if str(e.source_definition_id).endswith(".open_the_gate") and e.event_type == "DAMAGE_COMMITTED"]) == 1
    assert me.resources["resource:core.martial_focus"] == 0
    A._ready(engine)
    events = _strike(engine)
    assert not any(str(e.source_definition_id).endswith(".open_the_gate") and e.event_type == "DAMAGE_COMMITTED" for e in events)


def test_hammer_and_anvil_can_extend_opening_without_selecting_focus_recovery():
    engine = _duel(["TAL_IRON_FIST_HAMMER_AND_ANVIL_RHYTHM"])
    A._use(engine, "Choose Hammer-and-Anvil Rhythm: Extend Opening", None)
    engine._spend_resource(engine.state.actors[ME], "resource:core.martial_focus", 1, "test:no-focus")
    _strike(engine)
    A._ready(engine)
    events = _strike(engine)
    marks = [e for e in events if e.event_type == "CONDITION_APPLIED" and "typed.mark.opened" in e.payload.get("condition_id", "")]
    assert len(marks) == 2  # the explicit extension, then this strike's ordinary Opening
    assert engine.state.actors[ME].resources["resource:core.martial_focus"] == 0
    held = next(c for c in engine.state.actors[FOE].conditions.values() if "typed.mark.opened" in c.condition_id)
    assert held.expires_on == "END_OF_MARKER_NEXT_TURN"


def test_meridian_lock_offers_two_seals_and_body_locked_as_distinct_choices():
    """Merge 6592dcfa (attack-ability) uses the strike's DC, not the sheet DC."""
    from combat import concentration
    talents = ["TAL_IRON_FIST_MERIDIAN_SEALING_PALM", "TAL_IRON_FIST_MERIDIAN_LOCK"]
    engine = _duel(talents, dc=FAIL)
    engine.state.actors[FOE].saving_throws["CON"] = -100
    _open(engine)
    asked = _answer_options(engine, lambda req: ["Leg Seal", "Breath Seal"] if "Palm seals" in req["reaction_source_id"] else req["legal_option_ids"][:1])
    name = next(n for n in A._legal(engine) if n.startswith(STRIKE) and "Meridian-Sealing Palm" in n)
    events = _strike(engine, name)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["dc"] == 15 and not save.payload["success"]
    foe = engine.state.actors[FOE]
    assert engine._effective_speed(foe) == 15 and not foe.reaction_available
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE"
    assert concentration.save_mode(engine, foe) is None  # Breath Seal consumes only the next save
    assert any(r.get("extension_choice", {}).get("maximum_selections") == 2 for r in asked)

    engine = _duel(talents, dc=FAIL)
    engine.state.actors[FOE].saving_throws["CON"] = -100
    _open(engine)
    A._use(engine, "Choose Meridian Lock: Body-Locked", None)
    _answer_options(engine, lambda req: ["Voice Seal"] if "Palm seals" in req["reaction_source_id"] else req["legal_option_ids"][:1])
    A._ready(engine)
    events = _strike(engine, name)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["dc"] == 15 and not save.payload["success"]
    foe = engine.state.actors[FOE]
    assert engine._effective_speed(foe) == 0 and "typed.silenced" in A._conditions(foe)
    from combat.typed_executor import condition_rules
    assert any(r.get("save_against", {}).get("mode") == "DISADVANTAGE" and "DEX" in r["save_against"].get("abilities", [])
               for r in condition_rules(foe))
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload) for e in engine.events)


def test_meridian_lock_successful_save_does_not_offer_or_apply_seals():
    """A real successful save at merge 6592dcfa's attack DC bypasses seal choices."""
    engine = _duel(["TAL_IRON_FIST_MERIDIAN_SEALING_PALM", "TAL_IRON_FIST_MERIDIAN_LOCK"], dc=FAIL)
    foe = engine.state.actors[FOE]
    foe.saving_throws["CON"] = 100
    _open(engine)
    asked = _answer_options(engine, lambda req: req["legal_option_ids"][:1])
    name = next(n for n in A._legal(engine) if n.startswith(STRIKE) and "Meridian-Sealing Palm" in n)
    events = _strike(engine, name)
    save = next(e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE)
    assert save.payload["dc"] == 15 and save.payload["success"]
    assert not any("Palm seals" in req["reaction_source_id"] for req in asked)
    assert engine._effective_speed(foe) == 30 and foe.reaction_available
    assert "typed.silenced" not in A._conditions(foe)
    assert "typed.no_opportunity_attacks" in A._conditions(foe)


def test_heaven_seizing_body_clinch_does_not_slow_its_owner():
    engine = _duel(["TAL_IRON_FIST_DRAGON_STEP_CLINCH", "TAL_IRON_FIST_HEAVEN_SEIZING_CLINCH"], dc=FAIL)
    A._use(engine, "Dragon-Step Clinch: Maintain", None)
    assert engine._effective_speed(engine.state.actors[ME]) == 30


def test_heaven_seizing_clinch_can_grapple_a_creature_two_sizes_larger():
    from combat.footprints import ActorFootprintDefinition
    engine = _duel(["TAL_IRON_FIST_DRAGON_STEP_CLINCH", "TAL_IRON_FIST_HEAVEN_SEIZING_CLINCH"], dc=FAIL)
    engine.actor_footprints[FOE] = ActorFootprintDefinition.rectangle(footprint_id="test:huge", source_definition_id="test:huge",
                                                                   width_cells=3, height_cells=3)
    engine.state.actors[FOE].saving_throws.update(STR=-100, DEX=-100)
    A._use(engine, "Dragon-Step Clinch: Maintain", None)
    A._use(engine, "Grapple", FOE)
    assert "typed.grappled" in A._conditions(engine.state.actors[FOE])
    plain = _duel(["TAL_IRON_FIST_DRAGON_STEP_CLINCH", "TAL_IRON_FIST_HEAVEN_SEIZING_CLINCH"], dc=FAIL)
    plain.actor_footprints[FOE] = engine.actor_footprints[FOE]
    plain.state.actors[FOE].saving_throws.update(STR=-100, DEX=-100)
    A._use(plain, "Grapple", FOE)
    assert "typed.grappled" not in A._conditions(plain.state.actors[FOE])


def test_flowing_combination_is_an_immediate_free_followup_against_the_hit_target():
    engine = _duel(["TAL_IRON_FIST_FLOWING_COMBINATION"])
    foe, me = engine.state.actors[FOE], engine.state.actors[ME]
    foe.saving_throws.update(STR=-100, DEX=-100)
    asked = _answer_options(engine, lambda req: ["Shove: Prone"] if req["reaction_source_id"].endswith("flowing_combination") else req["legal_option_ids"][:1])
    assert not any("Flowing Combination" in n for n in A._legal(engine))  # no unrelated bonus-action variant
    _open(engine)
    _strike(engine)
    assert "typed.prone" in A._conditions(foe) and me.bonus_action_available
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves[-1].payload["mode"] == "DISADVANTAGE"
    count = len(asked)
    A._ready(engine)
    _strike(engine)
    assert len(asked) == count  # once per turn


def test_rooting_stance_focus_doubles_forced_movement_reduction_and_is_optional():
    from combat.typed_executor import Context, run_effects
    for decline, expected in [(False, 10), (True, 5)]:
        engine = _duel(["TAL_IRON_FIST_ROOTING_STANCE"], foe_at=(3, 5))
        me, foe = engine.state.actors[ME], engine.state.actors[FOE]
        if decline:
            from combat.gate2_runtime_models import ReactionDecision
            engine._gate4_reaction_provider = lambda r: (ReactionDecision(
                checkpoint=r["checkpoint"], reactor_id=r["reactor_id"], reaction_source_id=r["reaction_source_id"], selection="DECLINE"), None)
        A._use(engine, "Rooting Stance", None)
        focus = me.resources["resource:core.martial_focus"]
        assert focus == (1 if decline else 0)
        held = next(c for c in me.conditions.values() if c.condition_id == "condition:typed.iron_rooting")
        assert held.data["reduction"] == expected
        action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE)
        before = me.position
        ctx = Context(engine, foe, action, None, {"numbers": {"save_dc": 15}}, [me], me, {})
        run_effects(ctx, [{"type": "forced_movement", "distance_ft": 15, "direction": "away"}])
        assert engine.grid.distance_ft(before, me.position) == 15 - expected


def test_rooting_miss_step_moves_now_without_spending_reaction_or_movement():
    engine = _duel(["TAL_IRON_FIST_ROOTING_STANCE"])
    A._use(engine, "Rooting Stance", None)
    me, foe = engine.state.actors[ME], _foe_turn(engine)
    me.armor_class = 100
    before, movement = me.position, me.movement_remaining_ft
    asked = _answer_options(engine, lambda r: ["cell:3,7"] if r["reaction_source_id"].endswith("iron_fist_step") else r["legal_option_ids"][:1])
    events = _foe_attacks(engine)
    assert me.position != before and me.movement_remaining_ft == movement and me.reaction_available
    assert any(r["reactor_id"] == ME for r in asked)
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload) for e in events)


def test_rooting_step_exempts_only_the_creature_that_missed():
    engine = _trio(["TAL_IRON_FIST_ROOTING_STANCE"], sphere=IRON_FIST, ally_at=(2, 5))
    other = engine.state.actors[ALLY]
    other.team_id = "team:b"
    A._use(engine, "Rooting Stance", None)
    _foe_turn(engine)
    me = engine.state.actors[ME]
    me.armor_class = 100
    _answer_options(engine, lambda r: ["cell:2,7"] if r["reaction_source_id"].endswith("iron_fist_step") else r["legal_option_ids"][:1])
    events = _foe_attacks(engine)
    assert (me.position.x, me.position.y) == (2, 7)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == ALLY for e in events), "the other creature's OA still runs"
    assert not other.reaction_available
    assert len([e for e in events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME]) == 1
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload) for e in events)


def test_world_tempering_reduces_forced_movement_by_fifteen_only_while_focused():
    from combat.typed_executor import Context, run_effects
    for focused, expected in [(True, 5), (False, 20)]:
        engine = _duel(["TAL_IRON_FIST_WORLD_TEMPERING_BODY"], cl=15, foe_at=(3, 5))
        me, foe = engine.state.actors[ME], engine.state.actors[FOE]
        if not focused:
            engine._spend_resource(me, "resource:core.martial_focus", 1, "test:no-focus")
        action = next(a for a in engine.action_catalog.values() if a.owner_id == FOE)
        ctx = Context(engine, foe, action, None, {"numbers": {}}, [me], me, {})
        before = me.position
        run_effects(ctx, [{"type": "forced_movement", "distance_ft": 20, "direction": "away"}])
        assert engine.grid.distance_ft(before, me.position) == expected


def test_wrist_trap_keeps_attacks_against_its_owner_normal_and_denies_only_that_weapons_oa():
    from combat.ext import any_false
    engine = _trio(["TAL_IRON_FIST_WRIST_TRAPPING_HAND"], sphere=IRON_FIST, dc=FAIL, ally_at=(4, 7))
    me, foe, ally = (engine.state.actors[x] for x in (ME, FOE, ALLY))
    foe.saving_throws.update(STR=-100, DEX=-100)
    _open(engine)
    A._use(engine, "Grapple", FOE)
    assert "typed.iron_wrist" in A._conditions(foe) and foe.reaction_available
    _foe_turn(engine)
    me.armor_class = ally.armor_class = -50
    events = _foe_attacks(engine)
    own_roll = next(e for e in events if e.event_type == "ATTACK_ROLLED")
    assert own_roll.payload["mode"] == "NORMAL"
    foe.action_available = True
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ALLY in (c.target_ids or ())
                     and ".weapon." in c.source_definition_id and "#" not in c.source_definition_id)
    start = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id="wrist-other", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=FOE, target_ids=candidate.target_ids))
    other_roll = next(e for e in engine.events[start:] if e.event_type == "ATTACK_ROLLED")
    assert other_roll.payload["mode"] == "DISADVANTAGE"
    assert any_false("opportunity_allowed", engine, foe, me)
    for held in list(foe.conditions.values()):
        if held.condition_id == "condition:typed.iron_wrist":
            assert held.data["weapon_source"] == "tianxia.mortal.weapon.fu"


def test_nine_bell_opened_first_save_is_disadvantaged_and_target_chooses_seal_to_end():
    """Force the failed branch at the native attack DC (merge 6592dcfa)."""
    from combat.ext.afflictions import repeat_one

    engine = _duel(["TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM"], cl=15, dc=FAIL)
    engine.state.actors[FOE].saving_throws["CON"] = -100
    _open(engine)
    A._use(engine, "Nine-Bell Meridian Palm", FOE)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves and saves[-1].payload.get("mode") == "DISADVANTAGE"
    assert saves[-1].payload["dc"] == 15 and not saves[-1].payload["success"]
    foe = engine.state.actors[FOE]
    seal = next(c for c in foe.conditions.values() if c.condition_id.endswith("typed.affliction"))
    assert seal.data["repeat_one_choice"]
    from combat import concentration
    assert concentration.save_mode(engine, foe) == "DISADVANTAGE"
    assert concentration.save_mode(engine, foe) is None
    # A successful actual repeat roll; transport still identifies the sealed target as chooser.
    foe.saving_throws["CON"] = 100
    engine._active_intent = ActionIntent(intent_id="repeat-test", decision_id="repeat-test", candidate_id="repeat-test",
                                         state_version=engine.state.state_version, actor_id=FOE)
    asked = _answer_options(engine, lambda req: ["Voice Seal"])
    repeat_one(engine, foe)
    remaining = next(c for c in foe.conditions.values() if c.condition_id.endswith("typed.affliction"))
    assert remaining.data["picks"] == ["Leg Seal", "Breath Seal"] and "typed.silenced" not in A._conditions(foe)
    assert asked[0]["reactor_id"] == FOE
    assert concentration.save_mode(engine, foe) is None  # removing Voice never rearms the used Breath save
    plain = _duel(["TAL_IRON_FIST_NINE_BELL_MERIDIAN_PALM"], cl=15, dc=FAIL)
    plain.state.actors[FOE].saving_throws["CON"] = -100
    A._use(plain, "Nine-Bell Meridian Palm", FOE)
    saves = [e for e in plain.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert saves[-1].payload["mode"] == "NORMAL"  # the mark created by this hit is too late
    assert saves[-1].payload["dc"] == 15 and not saves[-1].payload["success"]


# ------------------------------------------------------------------------------------------------------- harness


def _bundle(talents, *, cl=10, dc=16, sphere=IRON_FIST):
    return A._bundle(sphere, talents, KIT, cl=cl, dc=dc)


def _duel(talents, *, cl=10, dc=16, sphere=IRON_FIST, foe_at=(4, 6)):
    """The character against a real (typed) foe, so the foe's own defenses run; the foe cannot be missed."""
    me_bundle = _bundle(talents, cl=cl, dc=dc, sphere=sphere)
    foe_bundle = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="RIDERS2", typed_bundles=(me_bundle, foe_bundle),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].maximum_hp = engine.state.actors[FOE].current_hp = 400
    A._ready(engine)
    return engine


def _open(engine, target=FOE):
    engine._apply_condition(engine.state.actors[target], mark_condition_id("Opened", ME), "test:opened", ME, expires_on="UNTIL_REMOVED")


def _strike(engine, name=STRIKE, target=FOE):
    return A._use(engine, name, target)


def _foe_turn(engine):
    """Start the foe's turn (the foe attacks me from here)."""
    engine.state.current_slot_index = engine.state.initiative_order.index(FOE)
    engine.state.current_actor_id = FOE
    engine._system_start_turn()
    foe = engine.state.actors[FOE]
    foe.action_available, foe.reaction_available = True, True
    engine.state.actors[ME].armor_class = -50
    return foe


def _foe_attacks(engine):
    attack = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ME in (c.target_ids or ()) and ".weapon." in c.source_definition_id
                  and (engine.action_catalog[c.source_definition_id].range_ft or 5) <= 5)
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"foe-{before}", decision_id=attack.decision_id, candidate_id=attack.candidate_id,
                                       state_version=attack.state_version, actor_id=FOE, target_ids=attack.target_ids))
    return engine.events[before:]


def _resist(engine, actor_id, *kinds):
    for kind in kinds:
        engine._add_modifier(engine.state.actors[actor_id], "test:resistance", "damage_resistance", "ADD", kind, "SELF", expires_on=None)


def _committed(events, actor_id=None):
    return [(p["rolled_or_pending_damage"], p["reduced_to"], p["damage_type"]) for e in events if e.event_type == "DAMAGE_COMMITTED"
            for p in [e.payload or {}] if actor_id is None or actor_id in (e.target_ids or ())]


def _pick(engine, option):
    A._use(engine, f"Choose Bell-Ringing Body Shot: {option}", None)
    A._ready(engine)


BELL = "TAL_IRON_FIST_BELL_RINGING_BODY_SHOT"
NEXT = "typed.next_attack_damage"


@pytest.mark.parametrize("option,condition", [("Blind spot", "typed.check_mode"),
                                              ("No Dash", "typed.no_dash"),
                                              ("Softened blows", NEXT)])
def test_counter_bell_is_a_separate_meridian_choice_and_runs_each_option(option, condition):
    engine, asked = _counter_form_run(opened=True, bell_option=option)
    bell, form = asked
    assert bell["reaction_source_id"] == "choice:needle.iron_bell"
    assert bell["legal_option_ids"] == ["Blind spot", "No Dash", "Softened blows"]
    assert "Bell-Ringing Body Shot" in bell["choice_trigger"]["prompt"]
    assert "Counter Palm" in bell["choice_trigger"]["prompt"]
    assert engine.state.actors[FOE].display_name in bell["choice_trigger"]["prompt"]
    assert form["legal_option_ids"] == ["TAL_IRON_FIST_BREAKING_KNUCKLE"]
    conditions = A._conditions(engine.state.actors[FOE])
    assert conditions & {"typed.check_mode", "typed.no_dash", NEXT} == {condition}
    held = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith(condition))
    if option == "Softened blows":
        assert held.data["amount"] == 2 * engine.state.actors[ME].proficiency_bonus
        engine.state.actors[FOE].action_available = True
        engine.state.actors[ME].armor_class = -50
        rolled, reduced, _ = _committed(_foe_attacks(engine), ME)[0]
        assert reduced == max(0, rolled - int(held.data["amount"]))
        assert NEXT not in A._conditions(engine.state.actors[FOE])
    elif option == "Blind spot":
        from combat.typed_executor import check_mode
        assert check_mode(engine.state.actors[FOE], "WIS", "Perception") == "DISADVANTAGE"
        assert check_mode(engine.state.actors[FOE], "WIS", "Insight") == "NORMAL"
    else:
        engine.state.actors[FOE].action_available = True
        assert not any(c.source_definition_id == "system:combat.dash" for c in engine.legal_candidates())
        engine._remove_condition(engine.state.actors[FOE], "condition:typed.no_dash", "test:remove")
        assert any(c.source_definition_id == "system:combat.dash" for c in engine.legal_candidates())
    # Bell's chosen rider does not consume the separately offered Form.
    assert any(c.condition_id.endswith("concentration_mode") for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("case", ["new_opening", "miss", "no_focus", "unowned"])
def test_counter_bell_negative_controls(case):
    engine, asked = _counter_form_run(opened=case != "new_opening", bell_option="No Dash",
                                     miss=case == "miss", focus=0 if case == "no_focus" else 1,
                                     owns=case != "unowned")
    assert not any(r["reaction_source_id"] == "choice:needle.iron_bell" for r in asked)
    assert "typed.no_dash" not in A._conditions(engine.state.actors[FOE])


def test_counter_bell_hit_needs_no_damage_and_can_run_when_form_is_declined():
    engine, asked = _counter_form_run(opened=True, immune=True, bell_option="No Dash")
    assert [r["reaction_source_id"] for r in asked] == ["choice:needle.iron_bell"]
    assert engine.state.actors[FOE].current_hp == 400
    assert "typed.no_dash" in A._conditions(engine.state.actors[FOE])
    engine, asked = _counter_form_run(opened=True, decline=True, bell_option="No Dash")
    assert len(asked) == 2
    assert "typed.no_dash" in A._conditions(engine.state.actors[FOE])
    assert not any(c.condition_id.endswith("concentration_mode") for c in engine.state.actors[FOE].conditions.values())


@pytest.mark.parametrize("option", ["Blind spot", "No Dash", "Softened blows"])
def test_counter_bell_expires_at_printed_off_turn_deadline(option):
    engine, _ = _counter_form_run(opened=True, bell_option=option)
    name = {"Blind spot": "typed.check_mode", "No Dash": "typed.no_dash", "Softened blows": NEXT}[option]
    # Counter Palm was taken on the holder's current turn. End of its *next*
    # turn is later; Blind spot instead ends at the striker's very next start.
    engine.end_turn()
    assert engine.state.current_actor_id == ME
    assert (name in A._conditions(engine.state.actors[FOE])) == (option != "Blind spot")
    engine.end_turn()
    assert name in A._conditions(engine.state.actors[FOE]) or option == "Blind spot"
    engine.end_turn()
    assert name not in A._conditions(engine.state.actors[FOE])


@pytest.mark.parametrize("option", ["Blind spot", "No Dash", "Softened blows"])
def test_counter_bell_table_choice_rollback_commit_and_reload(tmp_path, option):
    from combat.gate5_service import CombatService

    combat, table, match_id = _empty_palm_table(tmp_path, counter=True, bell=True)
    # Prime Opened through an actual player strike and commit before the
    # reaction turn. The ordinary Bell preset cannot trigger on a new opening.
    for name in ("End Turn", STRIKE, "End Turn"):
        menu = table.state(match_id)["menu"]
        picked = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                      if c["display_name"].lower() == name.lower())
        assert table.act(match_id, picked["candidate_id"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    menu = table.state(match_id)["menu"]
    picked = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                  if c["display_name"].startswith("Fu (Short Axe) attack") and c["target_ids"] == [ME]
                  and "#" not in c["source_definition_id"])
    before = combat._load_session(match_id).engine.state.model_dump(mode="json")
    def act(answers):
        return table.act(match_id, picked["candidate_id"], menu["decision_id"], menu["state_version"], 0, answers)
    first = act([])
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]
    assert prompt["context"]["reaction_source_id"] == "choice:needle.iron_bell"
    assert "Bell-Ringing Body Shot" in prompt["moment"] and "Counter Palm" in prompt["moment"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE", "option_ids": [option]}
    second = act([answer])
    assert second["status"] == "REACTION_REQUIRED"
    form = second["reaction"]
    assert [o["id"] for o in form["choice"]["options"]] == ["TAL_IRON_FIST_BREAKING_KNUCKLE"]
    assert combat._load_session(match_id).engine.state.model_dump(mode="json") == before
    decline = {**form["context"], "selection": "DECLINE", "option_ids": []}
    assert act([answer, decline])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id).engine
    assert reloaded.state.model_dump(mode="json") == combat._load_session(match_id).engine.state.model_dump(mode="json")
    name = {"Blind spot": "typed.check_mode", "No Dash": "typed.no_dash", "Softened blows": NEXT}[option]
    assert name in A._conditions(reloaded.state.actors[FOE])
    assert not any(c.condition_id.endswith("concentration_mode") for c in reloaded.state.actors[FOE].conditions.values())


# ------------------------------------------------------------------------------------------------------- Iron Fist


@pytest.mark.parametrize("control", ["MANUAL", "LOCAL_AUTO"])
def test_counter_bell_manual_ask_on_ai_turn_and_automatic_ai_choice(tmp_path, control):
    combat, table, match_id = _empty_palm_table(tmp_path, counter=True, bell=True, ask=True, foe_melee_only=True)
    for name in ("End Turn", STRIKE, "End Turn"):
        menu = table.state(match_id)["menu"]
        picked = next(c for c in combat.decision(match_id)["context"]["legal_candidates"]
                      if c["display_name"].lower() == name.lower())
        assert table.act(match_id, picked["candidate_id"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    metadata = combat._read_metadata(match_id)
    metadata["participant_control_modes"].update({FOE: "LOCAL_AUTO", ME: control})
    combat._write_metadata(match_id, metadata)
    result = table.auto_step(match_id, 0)
    if control == "MANUAL":
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "reaction:typed.TAL_IRON_FIST_COUNTER_PALM"
        answers = [{**prompt["context"], "selection": "USE", "option_ids": []}]
        result = table.auto_step(match_id, 0, answers)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.iron_bell"
        assert "Bell-Ringing Body Shot" in prompt["moment"] and "Counter Palm" in prompt["moment"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["No Dash"]})
        result = table.auto_step(match_id, 0, answers)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.iron_forms"
        answers.append({**prompt["context"], "selection": "DECLINE", "option_ids": []})
        result = table.auto_step(match_id, 0, answers)
    assert result["status"] != "REACTION_REQUIRED"
    loaded = combat._load_session(match_id).engine
    assert ("typed.no_dash" if control == "MANUAL" else NEXT) in A._conditions(loaded.state.actors[FOE])


def test_bell_ringing_body_shot_is_a_choose_one_that_runs_on_an_opened_target():
    """"When you hit an Opened creature ... choose one:" Perception Disadvantage / cannot Dash / next attack roll deals twice PB less:
    the first was the only one typed (and never ran from the passive); the others were GM lines."""
    names = {row["display_name"] for row in _bundle([BELL])["action_catalog"]}
    assert {f"Choose Bell-Ringing Body Shot: {option}" for option in ("Blind spot", "No Dash", "Softened blows")} <= names
    engine = _duel([BELL])
    _strike(engine)  # the foe is not Opened: no effect
    assert not (A._conditions(engine.state.actors[FOE]) & {NEXT, "typed.no_dash"})
    A._ready(engine)
    _open(engine)
    _pick(engine, "No Dash")
    _strike(engine)
    assert "typed.no_dash" in A._conditions(engine.state.actors[FOE]) and NEXT not in A._conditions(engine.state.actors[FOE])


def test_bell_ringing_softened_blows_cuts_the_next_attack_roll_by_twice_pb_once():
    engine = _duel([BELL])
    _open(engine)
    _strike(engine)  # default pick: the next-attack-roll option
    foe_cond = A._conditions(engine.state.actors[FOE])
    assert NEXT in foe_cond
    held = next(c for c in engine.state.actors[FOE].conditions.values() if c.condition_id.endswith(NEXT))
    assert held.data["amount"] == 8  # PB 4 -> twice PB
    foe = _foe_turn(engine)
    first = _committed(_foe_attacks(engine), ME)
    assert first, "the foe's attack landed"
    rolled, reduced, _ = first[0]
    assert reduced == max(0, rolled - 8), first
    assert NEXT not in A._conditions(foe)  # used up by that attack roll
    foe.action_available = True
    second = _committed(_foe_attacks(engine), ME)
    assert second and second[0][1] == second[0][0]  # only the next attack roll is softened


def test_bell_ringing_softened_blows_is_spent_by_a_missed_attack():
    engine = _duel([BELL])
    _open(engine)
    _strike(engine)
    assert NEXT in A._conditions(engine.state.actors[FOE])
    foe = _foe_turn(engine)
    engine.state.actors[ME].armor_class = 50  # the foe misses
    _foe_attacks(engine)
    assert NEXT not in A._conditions(foe)
    engine.state.actors[ME].armor_class = -50
    foe.action_available = True
    later = _committed(_foe_attacks(engine), ME)
    assert later and later[0][1] == later[0][0]


def test_one_inch_heavenquake_ignores_bludgeoning_and_force_resistance_on_an_opened_target_only():
    """"If the target was already Opened, the attack ignores Resistance to Bludgeoning and Force damage": a rider before; the
    foe's Resistance halved every packet."""
    key = "TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE"
    opened, plain = _duel([key], cl=10), _duel([key], cl=10)
    for engine in (opened, plain):
        _resist(engine, FOE, "BLUDGEONING", "FORCE")
    _open(opened)
    hit_opened = _committed(A._use(opened, "One-Inch Heavenquake", FOE), FOE)
    hit_plain = _committed(A._use(plain, "One-Inch Heavenquake", FOE), FOE)
    assert hit_opened and all(rolled == reduced for rolled, reduced, _ in hit_opened), hit_opened
    assert hit_plain and all(reduced < rolled for rolled, reduced, _ in hit_plain if rolled > 1), hit_plain


def test_iron_meridian_body_lets_the_unarmed_strike_deal_force():
    """"Your Unarmed Strikes may deal Bludgeoning or Force damage, chosen when you hit": the strike's damage types were Bludgeoning only."""
    plain, meridian = _bundle([]), _bundle(["TAL_IRON_FIST_IRON_MERIDIAN_BODY"], cl=10)
    row = lambda bundle: next(r for r in bundle["action_catalog"] if r["display_name"] == STRIKE)["parameters"]["typed"]["weapon"]  # noqa: E731
    assert row(plain).get("damage_types", ["BLUDGEONING"]) == ["BLUDGEONING"]
    assert row(meridian)["damage_types"] == ["BLUDGEONING", "FORCE"]
    # a Bludgeoning-resistant foe takes the Force instead
    engine = _duel(["TAL_IRON_FIST_IRON_MERIDIAN_BODY"])
    _resist(engine, FOE, "BLUDGEONING")
    hits = _committed(_strike(engine), FOE)
    assert hits and hits[0][2] == "FORCE" and hits[0][0] == hits[0][1]


def test_sovereign_iron_body_makes_the_unarmed_strike_ignore_bludgeoning_and_force_resistance_while_it_lasts():
    key = "TAL_IRON_FIST_SOVEREIGN_IRON_BODY_INCARNATION"
    engine = _duel([key], cl=15)
    _resist(engine, FOE, "BLUDGEONING", "FORCE")
    before = _committed(_strike(engine), FOE)
    assert before and all(reduced < rolled for rolled, reduced, _ in before if rolled > 1)
    A._ready(engine)
    A._use(engine, "Sovereign Iron-Body Incarnation", None)
    assert "typed.sovereign_iron_body" in A._conditions(A._me(engine))
    A._ready(engine)
    after = _committed(_strike(engine), FOE)
    assert after and all(reduced == rolled for rolled, reduced, _ in after), after


def test_lane_two_iron_fist_entries_have_no_echo_riders_left():
    """Riders that only repeated typed text (or a typing note) are gone; the lines the table still cannot run are kept."""
    import json

    from combat import factory_compiler

    mechanics = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]
    for key in ("TAL_IRON_FIST_BELL_RINGING_BODY_SHOT", "TAL_IRON_FIST_RISING_KNEE",
                "TAL_IRON_FIST_IRON_FOREARM_GUARD", "TAL_IRON_FIST_BODY_CONDITIONING"):
        assert mechanics[key]["coverage"] == "FULL", key
    # Thousand-Hand War Body's FULL claim was stale: its cross-fight Long Rest use receipt is genuinely
    # absent, so AUTO47 corrected the row to CORE_WITH_RIDERS rather than leaving the claim standing.
    assert mechanics["TAL_IRON_FIST_THOUSAND_HAND_WAR_BODY"]["coverage"] == "CORE_WITH_RIDERS"
    assert any("Long Rest" in rider for rider in mechanics["TAL_IRON_FIST_THOUSAND_HAND_WAR_BODY"]["riders"])
    assert any("Opened, standing from Prone" in rider for rider in mechanics["TAL_IRON_FIST_SWEEPING_KICK"]["riders"])
    assert not any("Body 2026-09-29" in rider or "Owner 2026-09-28" in rider for rider in mechanics["TAL_IRON_FIST_DRAGON_STEP_CLINCH"]["riders"])


def _incapacitate(engine, actor_id=ME):
    engine._apply_condition(engine.state.actors[actor_id], "condition:incapacitated", "test:stun", FOE, expires_on="UNTIL_REMOVED")


def test_a_martial_domain_ends_when_its_user_becomes_incapacitated():
    """"Court of One Hundred Forms ends early if you become Incapacitated": a GM line before; now the area comes off with it."""
    engine = _duel(["TAL_IRON_FIST_COURT_OF_ONE_HUNDRED_FORMS"], cl=12)
    A._use(engine, "Court of One Hundred Forms", None)
    assert any(zone.active for zone in engine.state.zones.values())
    assert any(c.condition_id.startswith("condition:typed.ends_if_incapacitated.") for c in A._me(engine).conditions.values())
    assert any(c.condition_id == "condition:typed.state.court_one_hundred_forms"
               for c in A._me(engine).conditions.values())
    _incapacitate(engine)
    assert not any(zone.active for zone in engine.state.zones.values())
    assert not any(c.condition_id.startswith("condition:typed.ends_if_incapacitated.") for c in A._me(engine).conditions.values())
    assert not any(c.condition_id == "condition:typed.state.court_one_hundred_forms"
                   for c in A._me(engine).conditions.values())


def test_sovereign_iron_body_ends_when_its_user_becomes_incapacitated_and_its_resistance_ignoring_goes_with_it():
    engine = _duel(["TAL_IRON_FIST_SOVEREIGN_IRON_BODY_INCARNATION"], cl=15)
    A._use(engine, "Sovereign Iron-Body Incarnation", None)
    assert "typed.sovereign_iron_body" in A._conditions(A._me(engine))
    _incapacitate(engine)
    assert "typed.sovereign_iron_body" not in A._conditions(A._me(engine))
    _resist(engine, FOE, "BLUDGEONING", "FORCE")
    A._ready(engine)
    engine.state.actors[ME].conditions.clear()  # the stun itself, so the strike can be made
    hits = _committed(_strike(engine), FOE)
    assert hits and all(reduced < rolled for rolled, reduced, _ in hits if rolled > 1), hits


# ------------------------------------------------------------------------------------------------------- Yang

YANG = "tianxia.sphere.yang"
ALLY = "actor:factory.ally"
KINDLED, OVERKINDLED = "Kindled Mark", "Overkindled Mark"


def _trio(talents, *, cl=10, dc=16, sphere=YANG, foe_at=(4, 6), ally_at=(2, 6)):
    """The character, a plain ally and a plain (typed) foe that cannot be missed, on a grid with the ally beside the character."""
    me_bundle = _bundle(talents, cl=cl, dc=dc, sphere=sphere)
    foe_bundle = compile_character(A._sheet(None, [], KIT), actor_id=FOE)
    ally_bundle = compile_character(A._sheet(None, [], KIT), actor_id=ALLY)
    engine = Gate4ControllerEngine(ROOT, match_seed="RIDERS2", typed_bundles=(me_bundle, ally_bundle, foe_bundle),
                                   roster_setup={"primary_actor_ids": [ME, ALLY, FOE],
                                                 "team_by_actor": {ME: "team:a", ALLY: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, ALLY: {"x": ally_at[0], "y": ally_at[1]},
                                                                        FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].maximum_hp = engine.state.actors[FOE].current_hp = 400
    A._ready(engine)
    return engine


def _use_on(engine, name, target):
    """The legal candidate of that name aimed at ``target`` (the shared harness takes the first one)."""
    matches = [c for c in engine.legal_candidates() if c.display_name == name and target in (c.target_ids or ())]
    assert matches, f"{name!r} cannot be aimed at {target}; legal: {sorted((c.display_name, c.target_ids) for c in engine.legal_candidates())}"
    candidate, before = matches[0], len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"u-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return engine.events[before:]


def _mark(engine, name, bearer, owner=ME):
    engine._apply_condition(engine.state.actors[bearer], mark_condition_id(name, owner), "test:mark", owner, expires_on="UNTIL_REMOVED")


def _bears(engine, bearer, name, owner=ME):
    from combat.typed_executor import bears_mark

    return bears_mark(engine.state.actors[bearer], owner, name)


def test_kindle_the_rising_may_mark_a_willing_creature_within_sixty_feet():
    """"Choose yourself or one willing creature ... within 60 feet. The target gains one Kindled Mark": the ability was self-only
    (the willing-creature choice was a GM line)."""
    engine = _trio([])
    rows = {row["display_name"]: row for row in _bundle([], sphere=YANG)["action_catalog"]}
    assert rows["Kindle the Rising"]["target_kind"] == "ALLY_OR_SELF" and rows["Kindle the Rising"]["range_ft"] == 60
    _use_on(engine, "Kindle the Rising", ALLY)
    assert _bears(engine, ALLY, KINDLED) and not _bears(engine, ME, KINDLED)
    A._ready(engine)
    _use_on(engine, "Kindle the Rising", ME)
    assert _bears(engine, ME, KINDLED)


def test_force_the_rising_also_answers_a_creature_that_moves_heals_or_spends_cp():
    """Force the Rising's printed triggers include a creature that "regains Hit Points ..., spends CP ..., or moves at least 10 feet
    during its turn": only "hits with an attack" was runnable (the rest was a GM line)."""
    from combat import typed_reactions

    engine = _trio([])
    foe, me = engine.state.actors[FOE], engine.state.actors[ME]
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=5)  # too short
    assert not _bears(engine, FOE, OVERKINDLED) and me.reaction_available
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=15)
    assert _bears(engine, FOE, OVERKINDLED) and not me.reaction_available
    for how in ("healed",):
        engine._remove_condition(foe, mark_condition_id(OVERKINDLED, ME), "test")
        A._ready(engine)
        if how == "healed":
            typed_reactions.on_creature_event(engine, foe, "healed")
        assert _bears(engine, FOE, OVERKINDLED), how
    engine._remove_condition(foe, mark_condition_id(OVERKINDLED, ME), "test")
    A._ready(engine)
    typed_reactions.on_creature_event(engine, engine.state.actors[ALLY], "moved", moved_ft=20)  # an ally's walk is not answered
    assert not _bears(engine, ALLY, OVERKINDLED)
    paid = _yang_duel([], foe_talents=["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    _foe_uses(paid, "Kindle the Rising")
    assert not _bears(paid, FOE, OVERKINDLED)  # it spent no CP
    _foe_uses(paid, "Completing Flame Mantle")
    assert _bears(paid, FOE, OVERKINDLED)


def _save_forcer(engine, effect_rows, *, dc=50):
    """Make the foe force a save on ``ALLY`` or ME with the given failed-save rows (through the engine's own save block)."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.typed_executor import Context, block_save

    foe = engine.state.actors[FOE]
    action = ActionDefinition(source_definition_id="action:test.force", display_name="Forced save", owner_id=FOE, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", parameters={"typed": {"effects": [], "numbers": {"save_dc": dc}}})

    def run(subject_id):
        subject = engine.state.actors[subject_id]
        ctx = Context(engine, foe, action, None, {"effects": [], "numbers": {"save_dc": dc, "pb": 4, "cl": 10}}, [subject], subject, {})
        block_save(ctx, {"type": "save", "ability": "wis", "on_fail": effect_rows, "on_success": []})
    return run


def test_complete_breath_adds_pb_and_key_modifier_when_the_marked_subject_regains_hit_points():
    """"Complete Breath. Trigger: the marked subject regains Hit Points ... Increase the amount gained by your Proficiency Bonus + your Key
    Ability modifier": the response did not exist (a rider: 'Other Kindled Responses are not automated yet')."""
    from combat import typed_reactions

    names = {row["feature_id"] for row in _bundle([], sphere=YANG)["typed_reactions"]}
    assert "TAL_YANG_KINDLED_RESPONSES#complete_breath" in names
    engine = _trio([])
    ally = engine.state.actors[ALLY]
    ally.maximum_hp, ally.current_hp = 80, 20
    _mark(engine, KINDLED, ALLY)
    typed_reactions.on_creature_event(engine, ally, "healed")
    assert ally.current_hp == 20 + 4 + 3, ally.current_hp  # PB 4 + key modifier 3 (the sheet's STR 16)
    assert not _bears(engine, ALLY, KINDLED)  # the mark is spent
    ally.current_hp = 20
    typed_reactions.on_creature_event(engine, ally, "healed")
    assert ally.current_hp == 20  # no mark, no response


def test_complete_resolve_adds_a_die_to_the_marked_subjects_save_against_a_control_effect():
    """"Complete Resolve. Trigger: the marked subject makes a saving throw against an effect that would reduce its Speed, prevent Reactions,
    impose Frightened, Paralyzed, Restrained, Stunned ... Add 1d4 to the saving throw": a rider before."""
    engine = _trio([])
    _mark(engine, KINDLED, ALLY)
    force = _save_forcer(engine, [{"type": "condition", "condition": "restrained", "applies_to": "target", "evidence": "Restrained"}])
    force(ALLY)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and "complete_resolve" in (e.source_definition_id or "")]
    assert len(resolved) == 1 and not _bears(engine, ALLY, KINDLED)
    assert 1 <= resolved[0].payload["bonus"] <= 4, resolved[0].payload
    # a save against plain damage is not a control effect: the mark is kept
    _mark(engine, KINDLED, ALLY)
    engine.state.round_number += 1
    _save_forcer(engine, [{"type": "damage", "applies_to": "target", "flat": 3, "damage_types": ["fire"], "evidence": "3 fire"}])(ALLY)
    assert _bears(engine, ALLY, KINDLED)
    # a Speed cut and a denied Reaction count as control effects
    for rows in ([{"type": "speed", "applies_to": "target", "flat": -10, "evidence": "Speed reduced"}],
                 [{"type": "reaction_denied", "applies_to": "target", "evidence": "cannot take Reactions"}]):
        engine.state.round_number += 1
        _mark(engine, KINDLED, ALLY)
        _save_forcer(engine, rows)(ALLY)
        assert not _bears(engine, ALLY, KINDLED), rows


def test_overcommit_step_takes_the_reactions_of_an_overkindled_creature_that_moves_ten_feet():
    """"Overcommit Step. Trigger: the marked subject moves at least 10 feet ... it cannot take Reactions until the start of its next turn"."""
    from combat import typed_reactions

    engine = _trio([])
    foe = engine.state.actors[FOE]
    engine.state.actors[ME].reaction_available = False  # Force the Rising would mark it afresh: keep this about the response alone
    _mark(engine, OVERKINDLED, FOE)
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=5)
    assert _bears(engine, FOE, OVERKINDLED)  # too short
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=10)
    assert not _bears(engine, FOE, OVERKINDLED) and "typed.reaction_denied" in A._conditions(foe) and not foe.reaction_available


def test_overgrown_recovery_raises_the_first_damage_roll_against_a_healed_overkindled_creature_by_pb():
    """"Overgrown Recovery. Trigger: the marked subject regains Hit Points ... the first damage roll against that subject gains a bonus equal
    to your Proficiency Bonus": not automated."""
    from combat import typed_reactions

    engine = _duel([], sphere=YANG)
    foe = engine.state.actors[FOE]
    foe.current_hp = 300
    engine.state.actors[ME].reaction_available = False  # Force the Rising would mark it afresh
    _mark(engine, OVERKINDLED, FOE)
    typed_reactions.on_creature_event(engine, foe, "healed")
    assert not _bears(engine, FOE, OVERKINDLED) and "typed.damage_taken_bonus" in A._conditions(foe)
    plain = _duel([], sphere=YANG)
    plain_foe = plain.state.actors[FOE]
    plain_foe.current_hp = 300
    rolls = []
    for eng, target in ((engine, foe), (plain, plain_foe)):
        A._ready(eng)
        hits = _committed(A._use(eng, "Rising Thread", FOE), FOE)
        if eng is engine:
            assert hits[0][1] == hits[0][0] + 4, hits  # exactly PB, before any defense
        rolls.append(sum(reduced for _, reduced, _ in hits))
    assert "typed.damage_taken_bonus" not in A._conditions(foe)  # used up by that damage
    assert rolls[0] >= 4 and rolls[0] - rolls[1] <= 4 + 12  # a bonus of PB 4 on top of the roll (the dice differ)


def test_force_the_rising_marks_after_the_event_so_a_response_cannot_spend_the_new_mark():
    """Force the Rising applies its mark "after the triggering event resolves": a creature that moves, unmarked, is marked by the reaction
    and Overcommit Step (which spends a mark of the same event) does not take it."""
    from combat import typed_reactions

    engine = _trio([])
    foe = engine.state.actors[FOE]
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=15)
    assert _bears(engine, FOE, OVERKINDLED) and "typed.reaction_denied" not in A._conditions(foe)


def test_overexpose_and_the_exposed_condition_take_the_benefit_of_hidden_and_invisible_away_from_the_marker():
    """"Overexpose. Trigger: the marked subject becomes Hidden or Invisible ... until the start of your next turn the subject cannot benefit
    from being Hidden or Invisible against you": a rider before.  Force the Rising also answers a creature that becomes Hidden."""
    engine = _trio([])
    foe = engine.state.actors[FOE]
    me = engine.state.actors[ME]
    _mark(engine, OVERKINDLED, FOE)
    me.reaction_available = False
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
    assert not _bears(engine, FOE, OVERKINDLED)  # spent by Overexpose
    held = [c for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.exposed")]
    assert len(held) == 1 and held[0].source_actor_id == ME
    from combat import senses

    invisible_ids = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    assert senses.masked_conditions(engine, me, foe).get(FOE) >= invisible_ids  # the marker is not fooled ...
    assert not (senses.masked_conditions(engine, engine.state.actors[ALLY], foe).get(FOE) or set()) & invisible_ids  # ... its ally still is
    # Force the Rising: an unmarked creature that becomes Hidden gets the mark from the reaction
    other = _trio([])
    other_me, other_foe = other.state.actors[ME], other.state.actors[FOE]
    other._apply_condition(other_foe, "condition:typed.hidden", "test:hidden", FOE, expires_on="UNTIL_REMOVED")
    assert _bears(other, FOE, OVERKINDLED) and not other_me.reaction_available


def _footprint(engine, actor_id, cells):
    from combat.footprints import ActorFootprintDefinition

    engine.actor_footprints[actor_id] = ActorFootprintDefinition.rectangle(cells, cells, footprint_id=f"footprint:test.{cells}x{cells}",
                                                                          source_definition_id="test:size")


def _complete_force_hit(engine):
    """A hit by the (Kindled) user on the foe: Complete Force spends the mark, and Force Completion rides it."""
    A._ready(engine)
    return A._use(engine, "Fu (Short Axe) attack", FOE)


def test_force_completion_pushes_a_target_no_more_than_one_size_larger_with_no_save_and_charges_its_cp():
    """"Force Completion (Cost: 2 CP): ... Push that target up to 10 feet directly away from the source of the damage. If the target is more than
    one size larger than the source, it makes a Strength saving throw": the push was attached to Complete Force for nothing, saved or not, and
    the 2 CP were never paid (a rider said GM adjudicates size)."""
    engine = _duel(["TAL_YANG_FORCE_COMPLETION"], sphere=YANG, dc=-40)  # the foe would pass every save
    _mark(engine, KINDLED, ME)
    foe = engine.state.actors[FOE]
    before, stamina = foe.position.x, engine.state.actors[ME].resources["resource:core.stamina"]
    _complete_force_hit(engine)
    assert foe.position.x - before == 2, (before, foe.position)  # 10 feet, away from the user: no save for a creature of its size
    assert engine.state.actors[ME].resources["resource:core.stamina"] == stamina - 2
    assert not _bears(engine, ME, KINDLED)
    # a creature more than one size larger saves (here it always does): not pushed, but the CP were paid
    big = _duel(["TAL_YANG_FORCE_COMPLETION"], sphere=YANG, dc=-40)
    _footprint(big, FOE, 4)  # Gargantuan beside a Medium user
    _mark(big, KINDLED, ME)
    start = big.state.actors[FOE].position.x
    _complete_force_hit(big)
    assert big.state.actors[FOE].position.x == start
    assert big.state.actors[ME].resources["resource:core.stamina"] == stamina - 2
    # a user who cannot pay the CP gets Complete Force without the push
    poor = _duel(["TAL_YANG_FORCE_COMPLETION"], sphere=YANG, dc=-40)
    poor.state.actors[ME].resources["resource:core.stamina"] = 1
    _mark(poor, KINDLED, ME)
    start = poor.state.actors[FOE].position.x
    _complete_force_hit(poor)
    assert poor.state.actors[FOE].position.x == start and poor.state.actors[ME].resources["resource:core.stamina"] == 1


def _yang_duel(talents, *, foe_talents=(), cl=10, dc=16):
    """The character against a Yang foe of its own (so the foe has a technique to use), the foe unable to be missed."""
    me_bundle = _bundle(talents, cl=cl, dc=dc, sphere=YANG)
    foe_bundle = A._bundle(YANG, list(foe_talents), KIT, cl=cl, dc=dc, actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed="RIDERS2", typed_bundles=(me_bundle, foe_bundle),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = -50
    engine.state.actors[FOE].maximum_hp = engine.state.actors[FOE].current_hp = 400
    A._ready(engine)
    return engine


def _foe_uses(engine, name, target=FOE):
    """The foe takes its turn's Bonus Action (or Action) on ``name``."""
    foe = engine.state.actors[FOE]
    engine.state.current_actor_id = FOE
    foe.action_available = foe.bonus_action_available = foe.reaction_available = True
    matches = [c for c in engine.legal_candidates() if c.actor_id == FOE and c.display_name == name and target in (c.target_ids or (target,))]
    assert matches, f"{name!r} is not legal for the foe: {sorted({c.display_name for c in engine.legal_candidates() if c.actor_id == FOE})}"
    candidate, before = matches[0], len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"foe-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=FOE, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    engine.state.current_actor_id = ME
    return engine.events[before:]


def test_overstrain_technique_marks_a_creature_that_repeats_the_same_technique():
    """"Overstrain Technique. Trigger: the marked subject ... uses a named cultivation technique. If the subject uses the same ... ability again
    before the end of its next turn, it gains a Rising Mark immediately after the repeated ability resolves": listed as not automated."""
    engine = _yang_duel([])
    me = engine.state.actors[ME]
    _mark(engine, OVERKINDLED, FOE)
    me.reaction_available = False  # Force the Rising would mark it afresh
    _foe_uses(engine, "Kindle the Rising")
    assert not _bears(engine, FOE, OVERKINDLED)  # the response spent the mark on the first use
    assert [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.overstrain"]
    _foe_uses(engine, "Kindle the Rising")  # the same technique again: it gains a Rising Mark
    assert _bears(engine, FOE, OVERKINDLED)
    assert not [c for c in engine.state.actors[FOE].conditions.values() if c.condition_id == "condition:typed.overstrain"]
    # a different technique does not count
    other = _yang_duel([])
    other.state.actors[ME].reaction_available = False
    _mark(other, OVERKINDLED, FOE)
    _foe_uses(other, "Kindle the Rising")
    _foe_uses(other, "Rising Thread", ME)
    assert not _bears(other, FOE, OVERKINDLED)


def test_radiant_overpressure_rides_the_overkindled_responses_and_charges_its_cp():
    """"Radiant Overpressure (Cost: 2 CP): ... cannot benefit from the Invisible condition against any creature that can
    see the light": blocked riders (a resource that was not one) before; now exposure riding the responses, paid when they fire."""
    from combat import senses, typed_reactions

    engine = _duel(["TAL_YANG_RADIANT_OVERPRESSURE"], sphere=YANG)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.reaction_available = False
    stamina = me.resources["resource:core.stamina"]
    _mark(engine, OVERKINDLED, FOE)
    engine._apply_condition(foe, "condition:typed.hidden", "test:hidden", FOE, expires_on="UNTIL_REMOVED")  # Overexpose answers it
    exposed = sorted(c.data["benefits"] + "/" + c.data["against"] for c in foe.conditions.values() if c.condition_id.startswith("condition:typed.exposed"))
    assert exposed == ["hidden_or_invisible/you", "invisible/anyone"], exposed
    assert me.resources["resource:core.stamina"] == stamina - 2
    hidden_ids = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.hidden"}
    assert senses.masked_conditions(engine, me, foe).get(FOE) >= hidden_ids
    # Radiant Overpressure's loss of Invisible is against anyone
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
    _mark(engine, OVERKINDLED, FOE)
    engine.state.round_number += 1
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=20)  # Overcommit Step
    invisible_ids = {iid for iid, c in foe.conditions.items() if c.condition_id == "condition:typed.invisible"}
    assert "typed.reaction_denied" in A._conditions(foe)
    assert invisible_ids <= (senses.masked_conditions(engine, engine.state.actors[ME], foe).get(FOE) or set())


def test_meridian_overcompletion_makes_a_constitution_save_on_overstrain_and_charges_4_cp():
    """"Meridian Overcompletion (Cost: 4 CP) ... The target makes a Constitution saving throw. On a failed save ... takes 4d8 ... and cannot take
    Reactions": BLOCKED before (a rider said the mark could not be spent)."""
    failing = _yang_duel(["TAL_YANG_MERIDIAN_OVERCOMPLETION"], dc=50)
    me, foe = failing.state.actors[ME], failing.state.actors[FOE]
    me.reaction_available = False
    stamina, hp = me.resources["resource:core.stamina"], foe.current_hp
    _mark(failing, OVERKINDLED, FOE)
    _foe_uses(failing, "Kindle the Rising")
    assert me.resources["resource:core.stamina"] == stamina - 4
    assert foe.current_hp < hp and "typed.reaction_denied" in A._conditions(foe)
    passing = _yang_duel(["TAL_YANG_MERIDIAN_OVERCOMPLETION"], dc=-40)
    passing.state.actors[ME].reaction_available = False
    _mark(passing, OVERKINDLED, FOE)
    hp = passing.state.actors[FOE].current_hp
    _foe_uses(passing, "Kindle the Rising")
    assert passing.state.actors[FOE].current_hp < hp and "typed.reaction_denied" not in A._conditions(passing.state.actors[FOE])  # half damage, no other effect


def test_rising_marks_are_one_kind_one_per_subject_and_share_the_limit():
    """"You can maintain a number of Rising Marks equal to your Proficiency Bonus. A creature ... can have only one Rising Mark from you at a
    time": Kindled and Overkindled were separate marks (a subject could carry both, and the limit counted each on its own)."""
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.typed_executor import Context, block_mark

    engine = _trio([])
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    action = ActionDefinition(source_definition_id="action:test.mark", display_name="Mark", owner_id=ME, economy=EconomyKind.ACTION,
                              resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", parameters={"typed": {"effects": [], "numbers": {"pb": 4}}})

    def place(name, subject):
        block_mark(Context(engine, me, action, None, {"effects": [], "numbers": {"pb": 4}}, [subject], subject, {}), {"type": "mark", "mark": name, "applies_to": "target"})

    place(KINDLED, foe)
    place(OVERKINDLED, foe)
    assert _bears(engine, FOE, OVERKINDLED) and not _bears(engine, FOE, KINDLED)  # one Rising Mark from you at a time
    # the limit counts both kinds together: with a limit of 2, a third mark ends the oldest
    caps = next(row for row in engine.typed_passive_rows[ME] if row.get("block") == "mark_caps")["caps"]
    caps[KINDLED.lower()] = caps[OVERKINDLED.lower()] = 2
    place(KINDLED, me)
    place(KINDLED, engine.state.actors[ALLY])
    assert not _bears(engine, FOE, OVERKINDLED) and _bears(engine, ME, KINDLED) and _bears(engine, ALLY, KINDLED)  # the foe's, the oldest, ended


def test_paid_reaction_rider_can_be_declined_without_spending_cp_or_losing_the_base_response():
    from combat.gate2_runtime_models import ReactionDecision

    engine = _duel(["TAL_YANG_FORCE_COMPLETION"], sphere=YANG, dc=-40)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    asked = []

    def decline(request):
        assert request["reaction_source_id"].startswith("choice:paid_option.")
        asked.append(request)
        return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                                reaction_source_id=request["reaction_source_id"], selection="DECLINE"), None

    engine._gate4_reaction_provider = decline
    _mark(engine, KINDLED, ME)
    stamina, start = me.resources["resource:core.stamina"], foe.position
    events = _complete_force_hit(engine)
    assert asked and not _bears(engine, ME, KINDLED)  # Complete Force still ran
    assert me.resources["resource:core.stamina"] == stamina and foe.position == start
    assert not any(e.event_type == "GM_RIDER" and "could not run" in str(e.payload) for e in events)


def test_radiant_overpressure_invisible_benefit_depends_on_the_observers_sight():
    from combat import typed_reactions

    engine = _trio(["TAL_YANG_RADIANT_OVERPRESSURE"])
    me, ally, foe = (engine.state.actors[x] for x in (ME, ALLY, FOE))
    me.reaction_available = False
    _mark(engine, OVERKINDLED, FOE)
    typed_reactions.on_creature_event(engine, foe, "moved", moved_ft=10)
    # Apply Invisible after this round's response so the exposure remains the one from Overcommit Step.
    engine._apply_condition(foe, "condition:typed.invisible", "test:invisible", FOE, expires_on="UNTIL_REMOVED")
    assert engine._attack_mode(ally, foe) == "NORMAL"
    engine._apply_condition(ally, "condition:typed.blinded", "test:blind", FOE, expires_on="UNTIL_REMOVED")
    assert engine._attack_mode(ally, foe) == "DISADVANTAGE"
    engine._remove_condition(ally, "condition:typed.blinded", "test:recovered")
    original = engine._line_of_sight_actor_to_actor
    engine._line_of_sight_actor_to_actor = lambda viewer, seen: False if viewer.entity_id == ALLY else original(viewer, seen)
    assert engine._attack_mode(ally, foe) == "DISADVANTAGE"  # opaque cover blocks the emitted light


def test_force_the_rising_waits_until_the_paid_technique_finishes_and_cannot_feed_overstrain_on_that_use():
    engine = _yang_duel([], foe_talents=["TAL_YANG_KINDLE_THE_WOUNDED_BREATH"])
    engine.state.actors[FOE].current_hp = 300
    events = _foe_uses(engine, "Kindle the Wounded Breath")
    foe = engine.state.actors[FOE]
    assert _bears(engine, FOE, OVERKINDLED)
    assert not any(c.condition_id == "condition:typed.overstrain" for c in foe.conditions.values())
    assert not any(c.condition_id.startswith("condition:typed.after_technique.") for c in foe.conditions.values())
    mark_event = next(i for i, e in enumerate(events) if e.event_type == "CONDITION_APPLIED" and
                      (e.payload or {}).get("condition_id") == mark_condition_id(OVERKINDLED, ME))
    assert any(e.event_type == "HEALING_APPLIED" for e in events[:mark_event])


def test_meridian_overcompletion_waits_until_the_triggering_technique_resolves():
    engine = _yang_duel(["TAL_YANG_MERIDIAN_OVERCOMPLETION"], foe_talents=["TAL_YANG_KINDLE_THE_WOUNDED_BREATH"], dc=50)
    engine.state.actors[ME].reaction_available = False
    engine.state.actors[FOE].current_hp = 300
    _mark(engine, OVERKINDLED, FOE)
    events = _foe_uses(engine, "Kindle the Wounded Breath")
    zone = next(i for i, e in enumerate(events) if e.event_type == "HEALING_APPLIED")
    damage = next(i for i, e in enumerate(events) if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids)
    assert zone < damage


def test_overstrain_repeated_technique_mark_uses_the_ordinary_yang_expiry():
    from combat.typed_executor import expire_marks

    engine = _yang_duel([])
    engine.state.actors[ME].reaction_available = False
    _mark(engine, OVERKINDLED, FOE)
    _foe_uses(engine, "Kindle the Rising")
    _foe_uses(engine, "Kindle the Rising")
    assert _bears(engine, FOE, OVERKINDLED)
    me = engine.state.actors[ME]
    expire_marks(engine)
    assert _bears(engine, FOE, OVERKINDLED)  # this turn is still the application turn
    me.turns_started += 1
    engine.state.current_actor_id = FOE  # the marker's following turn has ended
    expire_marks(engine)
    assert not _bears(engine, FOE, OVERKINDLED)


def test_complete_breath_increases_a_temporary_hp_grant_without_healing_real_hp():
    engine = _trio([])
    ally = engine.state.actors[ALLY]
    ally.current_hp = 20
    _mark(engine, KINDLED, ALLY)
    engine._grant_temp_hp(ally, 5, "test:temporary_hp", ME)
    assert ally.temporary_hp == 12 and ally.current_hp == 20  # 5 + PB 4 + key 3
    assert not _bears(engine, ALLY, KINDLED)
    engine.state.round_number += 1
    _mark(engine, KINDLED, ALLY)
    engine._grant_temp_hp(ally, 3, "test:smaller_grant", ME)
    assert _bears(engine, ALLY, KINDLED) and ally.temporary_hp == 12  # no actual gain


def test_overgrown_recovery_also_answers_temporary_hp_and_restored_cp_but_not_focus():
    for source in ("temporary_hp", "cp"):
        engine = _duel([], sphere=YANG)
        foe, me = engine.state.actors[FOE], engine.state.actors[ME]
        me.reaction_available = False
        _mark(engine, OVERKINDLED, FOE)
        if source == "temporary_hp":
            engine._grant_temp_hp(foe, 5, "test:temp_hp", FOE)
        else:
            foe.resources["resource:core.martial_focus"] = 0
            engine._gain_resource(foe, "resource:core.martial_focus", 1, "test:focus")
            assert _bears(engine, FOE, OVERKINDLED)
            foe.resources["resource:core.stamina"] -= 3
            engine._gain_resource(foe, "resource:core.stamina", 3, "test:cp")
        assert not _bears(engine, FOE, OVERKINDLED)
        assert "typed.damage_taken_bonus" in A._conditions(foe)


def test_force_the_rising_answers_a_temporary_hp_gain_after_overgrown_recovery_gets_its_chance():
    engine = _duel([], sphere=YANG)
    foe = engine.state.actors[FOE]
    engine._grant_temp_hp(foe, 5, "test:temporary_hp", FOE)
    assert _bears(engine, FOE, OVERKINDLED)
    assert "typed.damage_taken_bonus" not in A._conditions(foe)  # the new mark cannot be spent on the same grant


def test_force_the_rising_does_not_treat_spent_focus_as_spent_cp():
    from combat import typed_reactions

    engine = _yang_duel([])
    foe = engine.state.actors[FOE]
    typed_reactions.on_technique_start(engine, foe, [], {"numbers": {"_cost": 1, "_cp_cost": 0}, "effects": []}, None)
    assert not _bears(engine, FOE, OVERKINDLED) and engine.state.actors[ME].reaction_available


def test_split_rider_overrides_are_bound_to_the_parents_printed_rules_text():
    import hashlib
    import json

    from combat import factory_compiler

    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_bytes())["mechanics"]
    source = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())
    overrides = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/riders_lane2.json").read_bytes())["mechanics"]
    keys = [key for key in overrides if key.startswith("TAL_YANG_") and "#" in key]
    assert len(keys) == 8
    for key in keys:
        assert overrides[key]["text_sha256"] == hashlib.sha256(source[authority[key]["split_of"]].encode()).hexdigest()
        assert authority[key]["typing_status"] == "reviewed_final"


def test_overgrown_recovery_waits_for_rolled_damage_and_is_spent_even_by_an_immune_damage_roll():
    from combat import typed_reactions

    engine = _duel([], sphere=YANG)
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    me.reaction_available = False
    _mark(engine, OVERKINDLED, FOE)
    typed_reactions.on_creature_event(engine, foe, "healed")
    before = foe.current_hp
    engine._commit_damage(foe, 3, "FIRE", "test:fixed_damage", ME, None, reaction_depth=0)
    assert foe.current_hp == before - 3 and "typed.damage_taken_bonus" in A._conditions(foe)
    for kind in ("FIRE", "RADIANT", "FORCE"):
        engine._add_modifier(foe, "test:immunity", "damage_immunity", "ADD", kind, "SELF", expires_on=None)
    before = foe.current_hp
    A._use(engine, "Rising Thread", FOE)
    assert foe.current_hp == before
    assert "typed.damage_taken_bonus" not in A._conditions(foe)
    assert "typed.damage_taken_bonus.pending" not in A._conditions(foe)
