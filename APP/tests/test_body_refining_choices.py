"""Body Refining CL1 choices (hunt53 findings 1 and 3; L45), through real table actions with commit, reload, verify
and replay. Fixtures are synthetic sheets installed into the test's own data root.

Stomping Step (rules_text.json, tianxia.path.body_refining.feature.stomping_step): "Bonus Action. Take either the Dash
action or Disengage action." One action asks which (combat/ext/bodya_body_refining.py dash_or_disengage); Disengage
protects the rest of the turn's movement from Opportunity Attacks and ends with the turn; Thousand-Mile Legs follows
either choice.

Iron Fist (tianxia.path.body_refining.feature.iron_fist): "Your unarmed strike may deal Bludgeoning, Piercing, or
Slashing damage. Choose the damage type when you make the attack." A player-controlled owner is asked for every strike --
each attack of the Attack action, and a reaction counter that borrows the Iron Fist on an AI creature's turn; an AI
owner chooses automatically. Iron Meridian Body keeps adding Force (combat/ext/body_iron_fist.py). The attack ability is
the owner's 2026-09-30 ruling (highest of STR/DEX/CON unless the sheet records a choice; tests/test_attack_abilities.py).
"""
import copy
import json
import zipfile

import pytest

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.test_zones import ROOT, SHEET

IRON_FIST = "tianxia.path.body_refining.feature.iron_fist"
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"
STOMPING_STEP = "tianxia.path.body_refining.feature.stomping_step"
LEGS = "tianxia.subpath.body.sky_treading_tendon_school.feature.thousand_mile_legs"
STOMP_CHOICE = "choice:needle.dash_or_disengage"
SPHERE = "tianxia.sphere.iron_fist"
COUNTER_PALM = "TAL_IRON_FIST_COUNTER_PALM"
MERIDIAN = "TAL_IRON_FIST_IRON_MERIDIAN_BODY"
CHOICE = "choice:needle.iron_fist_damage_type"
FIST, FOE_PROJECT = "1f157000-0001", "1f157000-0002"  # portable-character ids (hex, like the Factory's)
ME, FOE = FACTORY_ACTOR_PREFIX + FIST, FACTORY_ACTOR_PREFIX + FOE_PROJECT


def sheet(*, path=(IRON_FIST,), talents=(), sphere=False, cl=5, ac=10, name="Iron Fist Tester"):
    out = copy.deepcopy(SHEET)
    out["identity"].update(display_name=name, cultivation_level=cl, proficiency_bonus=3 if cl < 9 else 4, path="Body Refining")
    stats = out["ability_scores_and_statistics"]
    stats["armor_class"]["base_value"] = ac
    stats["primary_resource"] = {"name": "Stamina", "maximum": 30}
    out["path_and_subpath"] = {"path_feature_record_ids": list(path)}
    out["spheres_and_talents"] = {"sphere_record_ids": [SPHERE] if (sphere or talents) else [],
                                 "learned_talent_record_ids": list(talents)}
    return out


def install(root, project, owner_sheet):
    folder = root / "portable_characters" / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(owner_sheet))


def table_fight(root, me_sheet, foe_sheet, *, me_mode="MANUAL", seed="IRON-TYPE", ask_me=False):
    install(root, FIST, me_sheet)
    install(root, FOE_PROJECT, foe_sheet)
    if ask_me:  # the sheet's Reactions setting "Ask me": the player answers its reactions on other creatures' turns
        ButtonStore(root / "tabletop_buttons").save_reactions(FIST, {"mode": "ask"}, set())
    combat = CombatService(ROOT, root)
    combat.tabletop_maps.save({"display_name": "Iron court", "width_squares": 10, "height_squares": 10,
                               "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}, "walls": []})
    view = combat.create_factory_match(project_ids=[FIST], opponent_actor_ids=[FOE], control_modes={ME: me_mode, FOE: "LOCAL_AUTO"},
                                       arena_id="battlefield:map.iron-court", match_seed=seed)
    return combat, TabletopService(combat, root), view["match_id"]


def until_my_turn(combat, mid):
    for _ in range(12):
        if combat._load_session(mid).engine.state.current_actor_id == ME:
            return
        combat.local_step(mid)
    raise AssertionError("the Iron Fist fighter never got a turn")


def act(table, mid, candidate_id, menu, answer):
    """Commit one table action; ``answer(prompt)`` returns the option ids for each prompt (None declines)."""
    answers, prompts = [], []
    for _ in range(12):
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        picked = answer(prompt)
        answers.append({**prompt["context"], "selection": "DECLINE" if picked is None else "USE", "option_ids": list(picked or [])})
    raise AssertionError("more prompts than one action can ask")


def options(prompt):
    return [row["id"] for row in (prompt.get("choice") or {}).get("options") or []]


def committed(engine, start, actor, source=None):
    return [e for e in engine.events[start:] if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == actor
            and (source is None or e.source_definition_id == source)]


def reload_and_replay(root, combat, mid):
    fresh = CombatService(ROOT, root)
    session = fresh._load_session(mid)
    assert session.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    assert TabletopService(fresh, root).events(mid, 0) == TabletopService(combat, root).events(mid, 0)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return session.engine


@pytest.mark.parametrize("talents,offered", [((), ["BLUDGEONING", "PIERCING", "SLASHING"]),
                                             ((MERIDIAN,), ["BLUDGEONING", "PIERCING", "SLASHING", "FORCE"])],
                         ids=["iron-fist", "with-iron-meridian-body"])
def test_each_strike_of_the_attack_action_asks_its_own_damage_type(tmp_path, talents, offered):
    combat, table, mid = table_fight(tmp_path, sheet(path=(IRON_FIST, EXTRA_ATTACK), talents=talents, cl=10 if talents else 5),
                                     sheet(path=(), ac=1, name="Target Dummy"))
    until_my_turn(combat, mid)
    engine = combat._load_session(mid).engine
    strike = next(c for c in engine.legal_candidates()
                  if c.source_definition_id.endswith(".natural.iron_fist") and FOE in c.target_ids)
    count = engine.action_catalog[strike.source_definition_id].parameters["typed"]["effects"][0]["count"]
    assert count == 2  # Extra Attack: the per-strike choice must be asked twice
    start = len(engine.events)
    picks = iter(["PIERCING", "SLASHING"])
    prompts = act(table, mid, strike.candidate_id, table.state(mid)["menu"], lambda prompt: [next(picks)])
    assert [p["context"]["reaction_source_id"] for p in prompts] == [CHOICE, CHOICE]
    assert all(options(p) == offered for p in prompts)
    text = json.dumps(prompts)
    assert "Iron Fist" in text and "Target Dummy" in text and "attack 1 of 2" in text and "attack 2 of 2" in text
    engine = reload_and_replay(tmp_path, combat, mid)
    hits = committed(engine, start, ME, strike.source_definition_id)
    assert [e.payload["damage_type"] for e in hits] == ["PIERCING", "SLASHING"]


def test_borrowed_iron_fist_counter_asks_the_manual_owner_on_an_ai_turn(tmp_path):
    combat, table, mid = table_fight(tmp_path, sheet(talents=(COUNTER_PALM,), ac=40),
                                     sheet(ac=1, name="Raging Brawler"), seed="IRON-COUNTER", ask_me=True)
    start, prompts = len(combat._load_session(mid).engine.events), []
    for _ in range(30):
        engine = combat._load_session(mid).engine
        if committed(engine, start, ME, COUNTER_PALM) or engine.state.terminal_result is not None:
            break
        if engine.state.current_actor_id == ME:
            menu = table.state(mid)["menu"]
            act(table, mid, menu["end_turn"], menu, lambda prompt: None)
            continue
        answers = []
        for _ in range(8):
            result = table.auto_step(mid, 0, answers)
            if result["status"] != "REACTION_REQUIRED":
                break
            prompt = result["reaction"]
            prompts.append(prompt)
            picked = ["SLASHING"] if prompt["context"]["reaction_source_id"] == CHOICE else options(prompt)[:1] or None
            answers.append({**prompt["context"], "selection": "USE", "option_ids": list(picked or [])})
    engine = reload_and_replay(tmp_path, combat, mid)
    counters = committed(engine, start, ME, COUNTER_PALM)
    assert counters and {e.payload["damage_type"] for e in counters} == {"SLASHING"}
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    assert asked and asked[0]["context"]["reactor_id"] == ME and options(asked[0]) == ["BLUDGEONING", "PIERCING", "SLASHING"]
    assert "Counter Palm" in json.dumps(asked[0]) and "Raging Brawler" in json.dumps(asked[0])


def test_ai_owner_chooses_the_counter_damage_type_without_asking(tmp_path):
    combat, table, mid = table_fight(tmp_path, sheet(talents=(COUNTER_PALM,), ac=40),
                                     sheet(ac=1, name="Raging Brawler"), me_mode="LOCAL_AUTO", seed="IRON-COUNTER", ask_me=True)
    start = len(combat._load_session(mid).engine.events)
    for _ in range(30):
        engine = combat._load_session(mid).engine
        if committed(engine, start, ME, COUNTER_PALM) or engine.state.terminal_result is not None:
            break
        assert table.auto_step(mid, 0, [])["status"] != "REACTION_REQUIRED"
    engine = reload_and_replay(tmp_path, combat, mid)
    counters = committed(engine, start, ME, COUNTER_PALM)
    assert counters and {e.payload["damage_type"] for e in counters} == {"BLUDGEONING"}  # nothing resists: the first listed


def test_an_unarmed_strike_without_the_iron_fist_feature_asks_nothing(tmp_path):
    combat, table, mid = table_fight(tmp_path, sheet(path=(), talents=("TAL_IRON_FIST_IRON_FIST_TRAINING",)),
                                     sheet(path=(), ac=1, name="Target Dummy"))
    until_my_turn(combat, mid)
    engine = combat._load_session(mid).engine
    strike = next(c for c in engine.legal_candidates() if ".natural." in c.source_definition_id and FOE in c.target_ids)
    prompts = act(table, mid, strike.candidate_id, table.state(mid)["menu"], lambda prompt: options(prompt)[:1])
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == CHOICE]
    reload_and_replay(tmp_path, combat, mid)


# ------------------------------------------------------------------------------------------------ Stomping Step
def stomp(table, combat, mid, choice):
    engine = combat._load_session(mid).engine
    [candidate] = [c for c in engine.legal_candidates() if c.display_name == "Stomping Step" and c.actor_id == ME]
    prompts = act(table, mid, candidate.candidate_id, table.state(mid)["menu"], lambda prompt: [choice])
    assert [p["context"]["reaction_source_id"] for p in prompts] == [STOMP_CHOICE]
    assert options(prompts[0]) == ["dash", "disengage"]
    labels = [row["label"] for row in prompts[0]["choice"]["options"]]
    assert labels[0].startswith("Dash: ") and labels[1].startswith("Disengage: ") and "Opportunity Attacks" in labels[1]
    return combat._load_session(mid).engine


def move_away(table, combat, mid):
    """Commit a real table move to a reachable cell more than 5 feet from the foe; the events it added."""
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    away = [c for c in engine.legal_candidates() if c.actor_id == ME and c.destination is not None and c.display_name.startswith("Move")
            and max(abs(c.destination.x - foe.position.x), abs(c.destination.y - foe.position.y)) >= 3]
    assert away, "no cell away from the foe is reachable"
    candidate = max(away, key=lambda c: (abs(c.destination.x - foe.position.x) + abs(c.destination.y - foe.position.y), c.candidate_id))
    start = len(engine.events)
    act(table, mid, candidate.candidate_id, table.state(mid)["menu"], lambda prompt: options(prompt)[:1])
    return combat._load_session(mid).engine.events[start:]


def opportunity_attacks(events):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE and "opportunity" in e.source_definition_id]


def test_stomping_step_disengage_protects_this_turn_s_retreat_and_ends_with_the_turn(tmp_path):
    combat, table, mid = table_fight(tmp_path, sheet(path=(STOMPING_STEP, IRON_FIST), cl=1, name="Stomping Tester"),
                                     sheet(ac=30, name="Iron Sentinel"), seed="STOMP-DISENGAGE")
    until_my_turn(combat, mid)
    speed = combat._load_session(mid).engine.state.actors[ME].movement_remaining_ft
    engine = stomp(table, combat, mid, "disengage")
    me = engine.state.actors[ME]
    assert me.turn_flags.get("disengaged") is True and me.movement_remaining_ft == speed and not me.bonus_action_available
    assert not opportunity_attacks(move_away(table, combat, mid))  # the Iron Sentinel was adjacent and kept its Reaction
    engine = reload_and_replay(tmp_path, combat, mid)
    assert engine.state.actors[FOE].reaction_available
    menu = table.state(mid)["menu"]
    act(table, mid, menu["end_turn"], menu, lambda prompt: None)
    until_my_turn(combat, mid)  # the AI Sentinel closes in and attacks
    engine = combat._load_session(mid).engine
    assert "disengaged" not in engine.state.actors[ME].turn_flags
    assert engine._distance_actor_to_actor(engine.state.actors[ME], engine.state.actors[FOE]) <= 5
    assert opportunity_attacks(move_away(table, combat, mid))  # next turn, leaving its reach provokes again
    reload_and_replay(tmp_path, combat, mid)


@pytest.mark.parametrize("choice", ["dash", "disengage"])
def test_thousand_mile_legs_follows_either_stomping_step_choice(tmp_path, choice):
    combat, table, mid = table_fight(tmp_path, sheet(path=(STOMPING_STEP, IRON_FIST, LEGS), cl=3, name="Stomping Tester"),
                                     sheet(ac=30, name="Iron Sentinel"), seed="STOMP-LEGS")
    until_my_turn(combat, mid)
    before = combat._load_session(mid).engine.state.actors[ME]
    assert combat._load_session(mid).engine._effective_speed(before) == 40  # Thousand-Mile Legs: +10 feet
    stomp(table, combat, mid, choice)
    engine = reload_and_replay(tmp_path, combat, mid)
    me = engine.state.actors[ME]
    assert any(c.condition_id == "condition:typed.ignore_difficult" for c in me.conditions.values())
    assert me.movement_remaining_ft == before.movement_remaining_ft + (40 if choice == "dash" else 0)
    assert bool(me.turn_flags.get("disengaged")) == (choice == "disengage")


@pytest.mark.parametrize("foe_at,expected", [((4, 6), "disengage"), ((12, 6), "dash")], ids=["adjacent", "far"])
def test_an_unanswered_stomping_step_disengages_next_to_a_foe_and_dashes_otherwise(foe_at, expected):
    """The automatic pick an AI fighter (or a fight nobody answers) makes."""
    from tests.test_riders_c7 import FOE as C7_FOE, ME as C7_ME, _typed_foe, bundle, fight, use

    engine = fight(bundle([STOMPING_STEP]), foe=_typed_foe(), foe_at=foe_at)
    assert engine.state.actors[C7_FOE].active
    me = engine.state.actors[C7_ME]
    speed = me.movement_remaining_ft
    use(engine, "Stomping Step")
    assert bool(me.turn_flags.get("disengaged")) == (expected == "disengage")
    assert me.movement_remaining_ft == speed + (engine._effective_speed(me) if expected == "dash" else 0)


def test_a_barred_dash_leaves_stomping_step_s_disengage_without_a_question():
    """Clinging Seal's no_dash (combat/rules/typed_conditions.json): only Disengage is left, so nothing is asked."""
    from tests.test_riders_c7 import ME as C7_ME, _typed_foe, bundle, fight, use

    engine = fight(bundle([STOMPING_STEP]), foe=_typed_foe(), foe_at=(12, 6))
    asked = []
    engine.set_reaction_provider(lambda request: (asked.append(request["reaction_source_id"]), (None, None))[1])
    me = engine.state.actors[C7_ME]
    engine._apply_condition(me, "condition:typed.no_dash", "test:clinging_seal", C7_ME, expires_on="UNTIL_REMOVED")
    speed = me.movement_remaining_ft
    use(engine, "Stomping Step")
    assert STOMP_CHOICE not in asked
    assert me.turn_flags.get("disengaged") is True and me.movement_remaining_ft == speed
