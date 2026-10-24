"""GROW2 F2: review gaps, using synthetic installs and public shipped rules.

Factory characters use typed_reactions.compile_blocks, not the fixed CL5
portable proof adapter. Native Art sources need the shipped catalog chapter zip
documented in test_grow2_campaign; Art construction authority is synthetic.
No history reads, private fixtures, browsers, or live model transports.
"""
from copy import deepcopy

import pytest

from app.core import Settings
from combat import table_advance as ta
from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from combat.tabletop_service import TabletopService
from tests.h1_support import script, sheet as combat_sheet
from tests.test_grow2_campaign import (
    ART, INSIGHT, PID, ROOT, completion, digest, install, service, sheet,
    synthetic_art_authority,
)

QI_ARMOR = "tianxia.path.qi_cultivation.feature.qi_armor"
QI = "resource:core.qi"
ATTACKER, DEFENDER = "actor:factory.grow2-striker", "actor:factory.grow2-guard"


def end_turn(table, mid):
    state = table.state(mid)
    return table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], [])


@pytest.mark.parametrize("cl,cost", [(9, 2), (10, 1)])
def test_qi_armor_cl10_discount_survives_table_commit_and_reload(tmp_path, monkeypatch, cl, cost):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, attacker, target, spec, *args, **kwargs):
        natural = target.armor_class + 1 - spec["attack_bonus"]
        assert 1 < natural < 20
        script(engine, [natural, *([1] * 40)])
        return original(engine, attacker, target, spec, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", hit)
    bundles = [
        compile_character(combat_sheet(["INK_BASE_INK_LASH"], cl=cl), actor_id=ATTACKER),
        compile_character(combat_sheet([QI_ARMOR], cl=cl), actor_id=DEFENDER),
    ]
    [reaction] = [row for row in bundles[1]["typed_reactions"] if row["feature_id"] == QI_ARMOR]
    assert reaction["cost"] == cost and reaction["ac"] == 5 and reaction["ranged_only"]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ATTACKER, DEFENDER], {ATTACKER: "team:a", DEFENDER: "team:b"},
        {ATTACKER: {"x": 2, "y": 6}, DEFENDER: {"x": 8, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [ATTACKER], [DEFENDER], control_modes={ATTACKER: "MANUAL", DEFENDER: "MANUAL"},
        match_seed="GROW2-F2-ARMOR", display_name="Qi Armor cost boundary", maximum_rounds=20,
    )["match_id"]
    if table.state(mid)["menu"]["actor_id"] != ATTACKER:
        assert end_turn(table, mid)["status"] == "COMMITTED"
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    defender = engine.state.actors[DEFENDER]
    qi, hp = defender.resources[QI], defender.current_hp
    candidate = next(row for row in engine.legal_candidates()
                     if row.display_name.startswith("Ink Lash") and row.target_ids == (DEFENDER,))

    def submit(reactions):
        return table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"], reactions)

    answers = []
    for _ in range(3):
        result = submit(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt["context"]["reaction_source_id"] == "choice:needle.ink_lash_damage":
            # Main correctly asks the attacker to declare its printed damage
            # type before rolling; preserve that choice, then use Qi Armor.
            answer["option_ids"] = ["SLASHING"]
        else:
            assert prompt["reaction"] == "Qi Armor", prompt
        answers.append(answer)
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    defender = loaded.engine.state.actors[DEFENDER]
    assert defender.resources[QI] == qi - cost
    assert defender.current_hp == hp and not defender.reaction_available
    [modifier] = [row for row in defender.modifiers.values() if row.source_definition_id == QI_ARMOR]
    assert modifier.value == 5 and modifier.expires_on == "START_OF_SELF_NEXT_TURN"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("cl", [4, 8, 12, 16, 19])
@pytest.mark.parametrize("level_choice", ["unused", "ability_score_change", "cultivation_insight_acquisition"])
def test_campaign_insight_keeps_each_level_asi_opportunity_separate(tmp_path, cl, level_choice):
    base = sheet(cl=cl)
    block = base["spheres_and_talents"]
    scores = ta.current_scores(base)
    if level_choice != "unused":
        # Producer-shaped sealed selection, with duplicate views of one event.
        selection = {"choice_kind": level_choice, "event": {"event_id": "sealed-choice"},
                     **({"deltas": {"CON": 2}} if level_choice == "ability_score_change"
                        else {"insight_id": INSIGHT, "ability": "CON", "amount": 1})}
        base["advancement_history"] = {
            "canonical_allocations": [{"event_id": "sealed-choice", "target_cl": cl,
                                      "advancement_kind": level_choice}],
            "levels": [{"cl": cl, "earned_feature_occurrences": [
                {"selection": deepcopy(selection)}, {"selection": deepcopy(selection)}]}],
        }
        scores["CON"] += 2 if level_choice == "ability_score_change" else 1
        for row in base["ability_scores_and_statistics"]["abilities"]:
            row.update(score=scores[row["ability"]], modifier=ta.ability_modifier(scores[row["ability"]]))
        if level_choice == "cultivation_insight_acquisition":
            block["cultivation_insight_record_ids"] = [INSIGHT]
            block["cultivation_insight_occurrences"] = [
                {"insight_id": INSIGHT, "gained_at_cl": cl, "ability_change_applied": True,
                 "acquisition_source": "level_selection"}]

    package = install(tmp_path, source=base)
    sealed_hash = digest(package)
    s = service(tmp_path)
    before = s.advancement(PID)["ability_panel"]["level_increase"]
    assert before["cl"] == [4, 8, 12, 16, 19]
    assert before["recorded_cls"] == ([] if level_choice == "unused" else [cl])
    s.add_insight(PID, INSIGHT, note="A mentor's campaign reward")
    cold = service(tmp_path)
    projected = cold.combat._factory_owner_sheet(PID)
    assert ta.current_scores(projected) == scores
    occurrences = projected["spheres_and_talents"]["cultivation_insight_occurrences"]
    campaign = [row for row in occurrences if row["acquisition_source"] == "campaign"]
    assert len(campaign) == 1 and not campaign[0]["ability_change_applied"]
    if level_choice == "cultivation_insight_acquisition":
        assert len(occurrences) == 2 and occurrences[0]["ability_change_applied"]
    assert cold.advancement(PID)["ability_panel"]["level_increase"]["recorded_cls"] == before["recorded_cls"]

    entry = {"reason": "level_increase", "cl": cl, "changes": {"CON": 2}}
    if level_choice == "unused":
        cold.add_ability(PID, entry)
        scores["CON"] += 2
    else:
        with pytest.raises(TabletopError, match="already recorded"):
            cold.add_ability(PID, entry)
    cold = service(tmp_path)
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID)) == scores
    with pytest.raises(TabletopError, match="already recorded"):
        cold.add_ability(PID, entry)
    cold.remove_advancement(PID, "insight", "0")
    cold = service(tmp_path)
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID)) == scores
    assert cold.advancement(PID)["ability_panel"]["level_increase"]["recorded_cls"] == [cl]
    assert digest(package) == sealed_hash


def assert_one_campaign_entry(projected):
    block = projected["spheres_and_talents"]
    assert block["cultivation_insight_record_ids"].count(INSIGHT) == 1
    assert [row["insight_id"] for row in block["cultivation_insight_occurrences"]] == [INSIGHT]
    assert len(projected["immortal_arts"]) == 1
    assert projected["immortal_arts"][0]["name"] == ART["name"]
    sections = projected["selected_record_sections"]
    assert [row["record_id"] for row in sections["insights"]] == [INSIGHT]
    assert len([row for row in sections["other"] if row.get("subsection") == "Immortal Art"]) == 1


def test_http_and_factory_independently_overlay_once_across_repeated_cold_reads(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.api import create_app

    package = install(tmp_path)
    sealed_hash = digest(package)
    s = service(tmp_path)
    s.add_insight(PID, INSIGHT, note="Quest")
    preview = s.immortal_art(PID, ART)
    s.immortal_art(PID, ART, note="Retreat", proof=completion(preview), save=True)
    raw = sheet()
    original = deepcopy(raw)
    # Reuse the same cached snapshot, even aliasing both views. An accidental
    # in-place overlay or response cache mutation accumulates on the next GET.
    cached = {"owner_character_sheet": raw, "display_owner_character_sheet": raw,
              "sections": {"abilities_statistics": {"data": raw["ability_scores_and_statistics"]}}}
    for _ in range(2):
        app = create_app(Settings.from_env(ROOT, tmp_path))
        monkeypatch.setattr(app.state.character_sheets, "sheet", lambda _: dict(cached))
        monkeypatch.setattr(app.state.character_creation, "recovery", lambda _: {})
        with TestClient(app) as client:
            for _ in range(2):
                response = client.get(f"/api/characters/{PID}/sheet")
                assert response.status_code == 200, response.text
                view = response.json()
                for key in ("owner_character_sheet", "display_owner_character_sheet"):
                    assert_one_campaign_entry(view[key])
                    assert ta.current_scores(view[key]) == ta.current_scores(original)
                factory = service(tmp_path).combat._factory_owner_sheet(PID)
                assert_one_campaign_entry(factory)
                compiled = compile_character(factory, actor_id="actor:factory.grow2-review")
                assert [row["id"] for row in compiled["diagnostics"]["insights"]] == [INSIGHT]
                assert raw == original
    assert digest(package) == sealed_hash
