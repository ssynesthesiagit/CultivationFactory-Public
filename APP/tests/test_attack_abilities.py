"""Owner 2026-09-30: one printed attack ability for attack, damage and sphere DCs."""
import copy
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop import auto_buttons, sheet_summary
from combat.tabletop_service import TabletopService
from tests.test_iron_fist import ROOT
from tests.test_zones import SHEET

BODY = "tianxia.path.body_refining.feature.iron_fist"
SPHERE = "tianxia.sphere.iron_fist"
TRAINING = "TAL_IRON_FIST_IRON_FIST_TRAINING"


def sheet(strength=8, dexterity=19, constitution=16, choice=None, training=True):
    out = copy.deepcopy(SHEET)
    out["identity"]["display_name"] = "Ability test fighter"
    out["identity"]["key_ability"] = "CON"
    out["path_and_subpath"] = {"path_feature_record_ids": [BODY]}
    out["spheres_and_talents"] = {"sphere_record_ids": [SPHERE] if training else [],
                                 "learned_talent_record_ids": [TRAINING, "TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE"] if training else []}
    for row in out["ability_scores_and_statistics"]["abilities"]:
        score = {"STR": strength, "DEX": dexterity, "CON": constitution}.get(row["ability"], 10)
        row.update(score=score, modifier=(score - 10) // 2)
    if choice:
        out["combat_ability_choices"] = {SPHERE: choice}
    return out


def natural(bundle):
    return next(a for a in bundle["action_catalog"] if ".natural." in a["source_definition_id"] and "#" not in a["source_definition_id"])


def commit_manual_with_iron_fist_choices(table, match, candidate, after):
    """Answer Iron Fist's printed per-strike damage-type prompt (hunt53/L45) with Bludgeoning, the type these
    tests' strikes dealt before the choice existed; any other prompt fails the test."""
    answers = []
    for _ in range(12):
        result = table.act(match, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, after, answers)
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.iron_fist_damage_type", prompt["context"]
        options = [row["id"] for row in prompt["choice"]["options"]]
        assert options[:3] == ["BLUDGEONING", "PIERCING", "SLASHING"], options
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["BLUDGEONING"]})
    raise AssertionError("Iron Fist attack exceeded the bounded sequence of printed choices")


@pytest.mark.parametrize("strength,choice,ability,bonus", [(8, None, "DEX", 4), (20, None, "STR", 5), (8, "STR", "STR", -1)])
def test_natural_attack_and_iron_fist_dcs_share_the_selected_ability(strength, choice, ability, bonus):
    bundle = compile_character(sheet(strength=strength, choice=choice), actor_id="actor:factory.ability")
    typed = natural(bundle)["parameters"]["typed"]
    assert typed["weapon"]["ability"] == ability
    assert typed["numbers"]["attack_bonus"] == 4 + bonus
    assert typed["weapon"]["damage"]["modifier"] == bonus
    for action in bundle["action_catalog"]:
        data = action["parameters"].get("typed") or {}
        if data.get("unarmed_option") or data.get("source") == "TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE":
            assert data["numbers"]["save_dc"] == 12 + bonus


@pytest.mark.parametrize("strength,dexterity,constitution,ability,bonus", [
    (8, 19, 16, "DEX", 4),
    (20, 19, 16, "STR", 5),
    (8, 19, 20, "CON", 5),
])
def test_body_only_selects_the_highest_of_all_three_printed_abilities(
        strength, dexterity, constitution, ability, bonus):
    owner_sheet = sheet(strength=strength, dexterity=dexterity, constitution=constitution, training=False)
    typed = natural(compile_character(owner_sheet, actor_id="actor:factory.ability"))["parameters"]["typed"]
    assert typed["weapon"]["ability"] == ability
    assert typed["numbers"]["attack_bonus"] == 4 + bonus
    assert typed["weapon"]["damage"]["modifier"] == bonus


@pytest.mark.parametrize("choice,bonus", [("STR", -1), ("DEX", 4), ("CON", 3)])
def test_body_only_recorded_choice_wins(choice, bonus):
    owner_sheet = sheet(training=False)
    owner_sheet["combat_ability_choices"] = {BODY: choice}
    typed = natural(compile_character(owner_sheet, actor_id="actor:factory.ability"))["parameters"]["typed"]
    assert typed["weapon"]["ability"] == choice
    assert typed["numbers"]["attack_bonus"] == 4 + bonus
    assert typed["weapon"]["damage"]["modifier"] == bonus


def test_constitution_remains_a_legal_body_attack_option_but_not_a_sphere_dc_option():
    typed = natural(compile_character(sheet(constitution=20, choice="CON"), actor_id="actor:factory.ability"))["parameters"]["typed"]
    assert typed["weapon"]["ability"] == "CON"
    assert typed["numbers"]["attack_bonus"] == 9
    assert typed["numbers"]["save_dc"] == 16


@pytest.mark.parametrize("choice,ability,bonus", [(None, "DEX", 4), ("STR", "STR", -1)])
def test_finesse_obeys_the_same_default_and_recorded_choice(choice, ability, bonus):
    owner_sheet = sheet(training=False)
    weapon = "tianxia.mortal.weapon.bi_shou"
    owner_sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon}]}}]
    if choice:
        owner_sheet["combat_ability_choices"] = {weapon: choice}
    bundle = compile_character(owner_sheet, actor_id="actor:factory.ability")
    typed = next(a["parameters"]["typed"] for a in bundle["action_catalog"]
                 if a["parameters"].get("typed", {}).get("source") == weapon)
    assert typed["weapon"]["ability"] == ability
    assert typed["weapon"]["damage"]["modifier"] == bonus


def test_hidden_strike_runtime_damage_names_its_owner():
    from combat.ext.tabik_ninpo import hidden_strike
    from combat.history_feed import format_history_feed
    from combat.typed_executor import Context
    from tests.test_auto_tabik import _ninja, ME, AN

    engine, _ = _ninja()
    actor, foe = engine.state.actors[ME], engine.state.actors[AN]
    actor.turn_flags["shadow_stepped"] = True
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get("typed", {}).get("weapon"))
    ctx = Context(engine, actor, action, None, action.parameters["typed"], [foe], foe, {})
    hidden_strike(ctx, foe, "weapon")
    events = [e.model_dump(mode="json") for e in engine.events if e.event_type == "DAMAGE_ROLLED"]
    feed = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={ME: "Fighter"}, definition_names={})
    assert any("Hidden Strike: 2d6 extra" in row["summary"] for row in feed)


def test_nullifying_strike_compiles_a_named_extra_damage_rider():
    owner_sheet = sheet()
    owner_sheet["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_VOID_NULLIFYING_STRIKE")
    bundle = compile_character(owner_sheet, actor_id="actor:factory.ability")

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    rows = [r for r in walk(bundle["action_catalog"]) if r.get("damage_label") == "Nullifying Strike"]
    assert rows and any(r.get("dice", {}).get("count") == 2 and r["dice"]["sides"] == 6 for r in rows)


def install(tmp_path, project, owner_sheet):
    folder = tmp_path / "portable_characters" / project
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(owner_sheet))




def table_fixture(tmp_path, owner_sheet):
    install(tmp_path, "ability", owner_sheet)
    foe_sheet = sheet(training=False)
    foe_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    install(tmp_path, "foe", foe_sheet)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Ability court", "width_squares": 10, "height_squares": 10,
                              "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}, "walls": []})
    actor, foe = FACTORY_ACTOR_PREFIX + "ability", FACTORY_ACTOR_PREFIX + "foe"
    view = combat.create_factory_match(project_ids=["ability"], opponent_actor_ids=[foe],
                                       control_modes={actor: "MANUAL", foe: "LOCAL_AUTO"},
                                       arena_id="battlefield:map.ability-court", match_seed="ABILITY-DEX")
    match = view["match_id"]
    for _ in range(12):
        if combat._load_session(match).engine.state.current_actor_id == actor:
            break
        combat.local_step(match)
    assert combat._load_session(match).engine.state.current_actor_id == actor
    return combat, TabletopService(combat, tmp_path), match, actor, foe


@pytest.mark.parametrize("weapon,choice,ability,bonus,automatic", [
    ("gong_jian", None, "DEX", 4, False),
    ("gong_jian", "STR", "DEX", 4, False),  # illegal choice cannot change a bow
    ("fu", None, "STR", -1, False),
    ("bi_shou", None, "DEX", 4, False),
    ("bi_shou", "STR", "STR", -1, False),
    ("fei_biao", None, "STR", -1, False),
    ("tong_zhu", None, "DEX", 4, False),
    ("gong_jian", None, "DEX", 4, True),
    ("gong_jian", "STR", "DEX", 4, True),
])
def test_table_weapon_properties_use_one_ability_after_reload(tmp_path, weapon, choice, ability, bonus, automatic):
    owner_sheet = sheet(training=False)
    owner_sheet["path_and_subpath"] = {}
    item = "tianxia.mortal.weapon." + weapon
    owner_sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": item, "quantity": 1}]}}]
    if choice:
        owner_sheet["combat_ability_choices"] = {item: choice}
    combat, table, match, actor, foe = table_fixture(tmp_path, owner_sheet)
    if automatic:
        combat.set_controller_mode(match, actor_id=actor, controller_mode="LOCAL_AUTO")
    # The actual AI chooses its action; manual play chooses the weapon button.
    for _ in range(80):
        engine = combat._load_session(match).engine
        rolls = [e for e in engine.events if e.event_type == "ATTACK_ROLLED"
                 and e.actor_id == actor and ".weapon." + weapon in e.source_definition_id]
        if rolls:
            break
        if engine.state.current_actor_id != actor or automatic:
            result = table.auto_step(match, table.state(match)["last_sequence"], [])
        else:
            candidate = next((c for c in engine.legal_candidates()
                              if ".weapon." + weapon in c.source_definition_id
                              and not c.source_definition_id.endswith(".pickup") and foe in c.target_ids), None)
            if candidate is None:
                combat.local_step(match)
                continue
            result = table.act(match, candidate.candidate_id, candidate.decision_id,
                               candidate.state_version, table.state(match)["last_sequence"])
        assert result["status"] == "COMMITTED"
    assert rolls, "the table must commit an actual weapon attack"
    restored = CombatService(ROOT, tmp_path)._load_session(match)
    action = restored.engine.action_catalog[rolls[0].source_definition_id]
    typed = action.parameters["typed"]
    assert typed["weapon"]["ability"] == ability
    assert typed["weapon"]["damage"]["modifier"] == bonus
    assert all(e.payload["modifier"] == typed["numbers"]["attack_bonus"] for e in rolls)
    assert typed["numbers"]["attack_bonus"] == bonus + (4 if typed["proficient"] else 0)
    damage = [e for e in restored.engine.events if e.event_type == "DAMAGE_ROLLED"
              and e.source_definition_id == action.source_definition_id]
    if damage:
        assert all(e.payload["modifier"] == bonus for e in damage)
    assert restored.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("action_name", ["Grapple", "Shove: Prone", "One-Inch Heavenquake"])
@pytest.mark.parametrize("choice,dc", [(None, 16), ("STR", 11)])
def test_table_iron_fist_saves_commit_and_reload(tmp_path, action_name, choice, dc):
    combat, table, match, actor, foe = table_fixture(tmp_path, sheet(choice=choice))
    engine = combat._load_session(match).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == action_name and foe in c.target_ids)
    source = candidate.source_definition_id
    result = commit_manual_with_iron_fist_choices(table, match, candidate, 0)
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(match)
    saves = [e for e in session.engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == source]
    assert saves and all(e.payload["dc"] == dc for e in saves)
    assert session.engine.action_catalog[source].parameters["typed"]["numbers"]["save_dc"] == dc
    assert TabletopService(fresh, tmp_path).events(match, 0) == table.events(match, 0)
    assert session.mechanical.replay()["status"] == "PASS"


def test_table_nullifying_strike_damage_name_survives_commit_reload(tmp_path):
    owner_sheet = sheet()
    owner_sheet["spheres_and_talents"]["learned_talent_record_ids"].append("TAL_VOID_NULLIFYING_STRIKE")
    combat, table, match, actor, foe = table_fixture(tmp_path, owner_sheet)
    engine = combat._load_session(match).engine
    candidate = next(c for c in engine.legal_candidates()
                     if "Nullifying Strike: Speed" in c.display_name and foe in c.target_ids)
    result = commit_manual_with_iron_fist_choices(table, match, candidate, 0)
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(match)
    named = [e for e in session.engine.events if e.event_type == "DAMAGE_ROLLED"
             and e.payload.get("damage_label") == "Nullifying Strike"]
    assert len(named) == 1 and named[0].payload["expression"] == "2d6+0"
    feed = TabletopService(fresh, tmp_path).events(match, 0)
    assert any("Nullifying Strike: 2d6 extra" in row["summary"] for row in feed["events"])
    assert feed == table.events(match, 0)
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("training", [True, False], ids=["sphere-and-body", "body-only"])
def test_table_rolls_sheet_and_commit_reload_agree(tmp_path, training):
    owner_sheet = sheet(training=training)
    install(tmp_path, "ability", owner_sheet)
    install(tmp_path, "foe", sheet(training=False))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Ability court", "width_squares": 10, "height_squares": 10,
                              "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}, "walls": []})
    actor = FACTORY_ACTOR_PREFIX + "ability"
    view = combat.create_factory_match(project_ids=["ability"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "foe"],
                                       control_modes={actor: "MANUAL", FACTORY_ACTOR_PREFIX + "foe": "LOCAL_AUTO"},
                                       arena_id="battlefield:map.ability-court", match_seed="ABILITY-DEX")
    match = view["match_id"]
    table = TabletopService(combat, tmp_path)
    # Advance whichever fighter won initiative; all changes go through commits.
    for attempt in range(12):
        engine = combat._load_session(match).engine
        if engine.state.current_actor_id != actor:
            combat.local_step(match)
            continue
        strike = next(c for c in engine.legal_candidates() if "Iron Fist" in c.display_name and ".natural." in c.source_definition_id)
        commit_manual_with_iron_fist_choices(table, match, strike, 0)
        feed = table.events(match, 0)
        damage = [r for r in feed["dice"] if r["actor_id"] == actor and r["kind"] == "damage"]
        if damage:
            break
        combat.local_step(match)
    assert damage and damage[0]["modifier"] == 4
    assert any(r["actor_id"] == actor and r["kind"] == "attack" and r["modifier"] == 8 for r in feed["dice"])
    assert any("modifier +4 (Dexterity)" in r["summary"] for r in feed["events"])
    restored = CombatService(ROOT, tmp_path)._load_session(match).engine
    action = next(a for a in restored.action_catalog.values() if a.owner_id == actor and ".natural." in a.source_definition_id)
    assert action.parameters["typed"]["weapon"]["ability"] == "DEX"
    assert action.parameters["typed"]["numbers"]["attack_bonus"] == 8
    # The sheet's attack buttons are generated from that same frozen bundle.
    bundle = compile_character(owner_sheet, actor_id=actor)
    buttons = auto_buttons(bundle, sheet_summary(owner_sheet))
    button = next(b for b in buttons if b["combat"] and b["combat"]["source_definition_id"] == natural(bundle)["source_definition_id"])
    assert button["roll"]["expression"] == "1d20+8"
    assert "+4" in button["detail"]["damage"]
