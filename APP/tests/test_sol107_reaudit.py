"""SOL107: verified header corrections, and explicit lock-round range deferrals.

Table checks use preview/commit and reopen the on-disk match. Metadata-only
checks do not claim that incomplete summons or passive procedures are automated.
"""
import json

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat import zones
from tests.h1_support import ROOT, sheet
from tests.test_audit1_typed_data import CONDITIONAL_RANGES
from tests.test_r9i_fate_persistence import fixture, ALLY
from tests.test_r9i_karma_persistence import PLAYER, FOE, act, end_turn


M = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
QI = "tianxia.subpath.qi."
CONCENTRATION = {
    "TAL_WAX_CANDLE_PROCESSION": 10,
    "tianxia.talent.ink.painted_beast": 1,
    QI + "venomous_poison_cultivator.feature.myriad_venom_sovereign": 1,
    QI + "incense_cultivator.feature.foundational_incenses": 1,
    QI + "mirror_cultivator.feature.true_reflection": 1,
    QI + "nightmare_dream_qi_cultivator.feature.feast_of_sleeping_minds": 1,
}


@pytest.mark.parametrize("mid,minutes", CONCENTRATION.items())
def test_verified_concentration_duration(mid, minutes):
    assert M[mid]["duration"] == {"kind": "minutes", "amount": minutes, "concentration": True}


@pytest.mark.parametrize("mid", [k for k in CONCENTRATION if "true_reflection" not in k])
def test_concentration_survives_table_commit_reload(tmp_path, mid):
    combat, table, match = fixture(tmp_path, talent=mid)
    for _ in range(6):
        if table.state(match)["menu"]["actor_id"] == PLAYER:
            break
        end_turn(table, match)
    engine = combat._load_session(match).engine
    sources = {s for s, a in engine.action_catalog.items() if mid in s}
    candidates = [c for c in engine.legal_candidates() if c.source_definition_id in sources]
    assert candidates, mid
    result = act(table, match, candidates[0].candidate_id)
    assert result["status"] == "COMMITTED", result
    reopened = CombatService(ROOT, tmp_path)._load_session(match).engine
    owner = reopened.state.actors[PLAYER]
    assert owner.concentration is not None
    assert owner.concentration.source_definition_id in sources


@pytest.mark.parametrize("suffix", [
    "tea_sage_cultivator.feature.grandmaster_infusion",
    "storm_soul_cultivator.feature.lightning_reflexes",
    "yin_yang_cultivator.feature.balanced_flow",
])
def test_passive_is_free_and_subfeature_cost_stays_in_named_rider(suffix):
    row = M[QI + suffix]
    assert row["activation"]["economy"] == "passive"
    assert row["cost"] == []
    assert any("Cost" in r and "Qi" in r for r in row["riders"])


@pytest.mark.parametrize("suffix,limit", [
    ("heaven_defying_pill", "One successful Heaven-Defying Pill per year per alchemist unless a Secret Inheritance says otherwise."),
    ("resurrection_pill", "One successful Resurrection Pill per alchemist lifetime unless the campaign is intentionally mythic."),
    ("realm_ascension_pill", "Once per lifetime per alchemist and once per lifetime per consumer."),
])
def test_recipe_limits_preserve_the_printed_scope(suffix, limit):
    assert M["tianxia.talent.alchemy." + suffix]["use_limit"] == "text:" + limit


def test_counter_battery_limit_is_once_per_round():
    assert M[QI + "star_piercing_greatbow_cultivator.feature.celestial_firing_platform"]["use_limit"] == "once_per_round"


def test_kingdom_has_one_scene_use_counter():
    mid = QI + "venomous_poison_cultivator.feature.myriad_venom_sovereign"
    compiled = compile_character(sheet([mid]), actor_id=PLAYER)
    action = next(a for a in compiled["action_catalog"] if mid in a["source_definition_id"])
    assert any(r.startswith("resource:uses.") and n == 1 for r, n in action["costs"])


def test_surgeon_per_creature_limit_survives_table_commit_reload(tmp_path):
    mid = "tianxia.talent.thread.surgeon_s_stitch"
    combat, table, match = fixture(tmp_path, talent=mid)
    for _ in range(6):
        if table.state(match)["menu"]["actor_id"] == PLAYER:
            break
        end_turn(table, match)
    engine = combat._load_session(match).engine
    candidate = next(c for c in engine.legal_candidates()
                     if mid in c.source_definition_id and c.target_ids == (ALLY,))
    assert act(table, match, candidate.candidate_id)["status"] == "COMMITTED"
    reopened = CombatService(ROOT, tmp_path)._load_session(match).engine
    owner = reopened.state.actors[PLAYER]
    from combat.ext.target_limits import used_on
    counter = next(r for r in owner.resources if r.startswith("resource:uses.") and mid in r)
    assert used_on(owner, counter, ALLY)
    assert not used_on(owner, counter, PLAYER)


@pytest.mark.parametrize("mid", CONDITIONAL_RANGES)
def test_unimplemented_conditional_range_is_explicit_without_widening(mid):
    reach = M[mid]["range"]
    assert reach["kind"] == "touch" and reach["feet"] == 5
    assert reach["text"] == CONDITIONAL_RANGES[mid]
    assert "GM" in reach["gm_note"] and "touch only" in reach["gm_note"]


def test_no_added_duplicate_reviews():
    directory = ROOT / "authority/typed_mechanics/reviewed_final.d"
    others = {mid for path in directory.glob("*.json") if path.name != "sol107.json"
              for mid in json.loads(path.read_text()).get("mechanics", {})}
    assert not (others & json.loads((directory / "sol107.json").read_text())["mechanics"].keys())


@pytest.mark.parametrize("label,shape,size", [("15-foot square", "square", 15), ("10-foot radius", "sphere", 10)])
def test_silk_web_shape_survives_table_commit_reload(tmp_path, label, shape, size):
    mid = "TAL_THREAD_SILK_WEB_FIELD"
    combat, table, match = fixture(tmp_path, talent=mid)
    while table.state(match)["menu"]["actor_id"] != PLAYER:
        end_turn(table, match)
    engine = combat._load_session(match).engine
    candidate = next(c for c in engine.legal_candidates() if mid in c.source_definition_id
                     and label in c.display_name and (c.destination.x, c.destination.y) == (5, 6))
    action = engine.action_catalog[candidate.source_definition_id]
    assert action.parameters["typed"]["area"] == {"shape": shape, "size_ft": size}
    assert act(table, match, candidate.candidate_id)["status"] == "COMMITTED"
    reopened = CombatService(ROOT, tmp_path)._load_session(match)
    web = next(z for z in zones.typed_zones(reopened.engine) if z.source_definition_id == candidate.source_definition_id)
    expected = ({(4, 5), (5, 5), (6, 5), (4, 6), (5, 6), (6, 6), (4, 7), (5, 7), (6, 7)}
                if shape == "square" else
                {(5, 4), (4, 5), (5, 5), (6, 5), (3, 6), (4, 6), (5, 6), (6, 6),
                 (7, 6), (4, 7), (5, 7), (6, 7), (5, 8)})
    assert {(cell.x, cell.y) for cell in web.affected_cells} == expected
    assert reopened.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("label,rider", [
    ("Push Away", "you are pushed 20 feet away from the line"),
    ("Fall Prone", "you fall prone (lying down until you stand up)"),
    ("Deny Reactions", "you cannot take reactions until the start of the spear user's next turn"),
])
@pytest.mark.parametrize("target_mode,selected,expected_modifier", [
    ("MANUAL", "STR", 12), ("MANUAL", "DEX", -3), ("LOCAL_AUTO", None, 12),
])
def test_spear_defender_chooses_strength_or_dexterity_at_table(
        tmp_path, target_mode, selected, expected_modifier, label, rider):
    mid = "TAL_SPEAR_ONE_SPEAR_PIERCES_THE_ARMY"
    # Distinct modifiers are part of the saved input bundles, not an in-memory
    # edit that disappears when the table service reloads the match.
    from combat.tabletop_service import TabletopService
    owner_sheet = sheet([mid], cl=15)
    owner_sheet["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 80
    owner = compile_character(owner_sheet, actor_id=PLAYER)
    foe = compile_character(sheet([], cl=15), actor_id=FOE)
    owner["actor_template"]["display_name"] = "Spear user"
    foe["actor_template"]["display_name"] = "Defender"
    foe["actor_template"]["saving_throws"].update(STR=12, DEX=-3)
    combat = CombatService(ROOT, tmp_path)
    match = combat._finish_factory_match(
        [owner, foe], [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="SOL107-SPEAR",
        display_name="Spear save choices", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(match)["menu"]["actor_id"] != PLAYER:
        end_turn(table, match)
    combat.set_controller_mode(match, actor_id=FOE, controller_mode=target_mode)
    engine = combat._load_session(match).engine
    foe_at = engine.state.actors[FOE].position
    candidate = next(c for c in engine.legal_candidates() if mid in c.source_definition_id
                     and label in c.display_name and c.destination == foe_at)
    result = act(table, match, candidate.candidate_id)
    answers, asked_foe = [], False
    for _ in range(8):
        if result["status"] != "REACTION_REQUIRED":
            break
        prompt = result["reaction"]
        assert {o["id"] for o in prompt["choice"]["options"]} == {"STR", "DEX"}
        asked_foe |= prompt["context"]["reactor_id"] == FOE
        text = prompt["moment"]
        assert "One Spear Pierces the Army" in text
        assert engine.state.actors[prompt["context"]["reactor_id"]].display_name in text
        assert engine.action_catalog[candidate.source_definition_id].display_name in text
        assert "choice costs no action or resource" in text
        assert "On failure, you take 10d10 Piercing or Force damage" in text
        assert rider in text
        assert "On success, you take half damage and move 5 feet away from the line" in text
        answer = {**prompt["context"], "selection": "USE", "option_ids": [selected or "DEX"]}
        answers.append(answer)
        combat = CombatService(ROOT, tmp_path)
        result = act(TabletopService(combat, tmp_path), match, candidate.candidate_id, answers)
    assert asked_foe == (target_mode == "MANUAL")
    assert result["status"] == "COMMITTED", result
    reopened = CombatService(ROOT, tmp_path)._load_session(match)
    saves = [e for e in reopened.engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(saves) == 1
    assert saves[0].payload["modifier"] == expected_modifier
    assert reopened.mechanical.replay()["status"] == "PASS"
