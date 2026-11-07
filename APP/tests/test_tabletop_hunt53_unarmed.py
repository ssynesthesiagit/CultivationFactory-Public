"""Hunt 53 finding 2: every fighter's damaging Unarmed Strike -- 1 + Strength modifier Bludgeoning per hit, one strike per
attack of the Attack action -- committed at the table, reloaded, verified and replayed (combat/ext/basic_unarmed.py
and the shared unarmed_strike_weapon payload)."""

import json
import zipfile

import pytest

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop_service import TabletopService
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT
from tests.test_lock2_persistence import act

STRENGTH = 3  # +3: Strength counted twice would deal 7, not 4
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"  # 4 attacks per Attack action at CL 17


def _sheet(name: str, *, strength: int, features: list[str], armor_class: int) -> dict:
    abilities = [{"ability": a, "modifier": m, "score": 10 + 2 * m} for a, m in
                 (("STR", strength), ("DEX", 2), ("CON", 4), ("INT", 0), ("WIS", 0), ("CHA", 0))]
    stats = {**SHEET["ability_scores_and_statistics"], "abilities": json.dumps(abilities),
             "armor_class": json.dumps({"base_value": armor_class})}
    return {**SHEET, "identity": {**SHEET["identity"], "display_name": name}, "ability_scores_and_statistics": stats,
            "equipment": [], "path_and_subpath": {"path_record_ids": ["tianxia.path.body_refining"], "path_feature_record_ids": features},
            "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}


def _install(userdata, project_id: str, document: dict) -> None:
    folder = userdata / "portable_characters" / project_id
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))


@pytest.mark.parametrize("gate", [None, "target_requires_condition", "blocked_by_turn_flag", "requires_inside"])
def test_a_plain_fighter_commits_one_plus_strength_per_unarmed_hit_and_reloads(tmp_path, monkeypatch, gate):
    if gate:
        from combat import ext
        from combat.factory_compiler import compile_character
        from combat.gate2_runtime_models import ActionDefinition

        bundle = compile_character(_sheet("Plain Brawler", strength=STRENGTH, features=[EXTRA_ATTACK], armor_class=8),
                                   actor_id=FACTORY_ACTOR_PREFIX + "brawler")
        row = next(a for a in bundle["action_catalog"] if a["display_name"] == "Unarmed Strike")
        row["source_definition_id"] += "_conditional"
        row["display_name"] = "Conditional strike"
        row["parameters"]["expected_damage"] = 100
        row["parameters"]["typed"]["weapon"]["fixed_damage"] = 25
        mapping = row["parameters"]["typed"] if gate == "requires_inside" else row["parameters"]
        mapping[gate] = "condition:typed.burning" if gate == "target_requires_condition" else "unavailable"
        restricted = ActionDefinition.model_validate(row)
        functions = list(ext._HOOKS["compile_actions"])
        monkeypatch.setitem(ext._HOOKS, "compile_actions", [*functions, lambda info: [restricted]
                            if info["actor_id"] == restricted.owner_id else []])
    _install(tmp_path, "brawler", _sheet("Plain Brawler", strength=STRENGTH, features=[EXTRA_ATTACK], armor_class=8))
    _install(tmp_path, "post", _sheet("Training Post", strength=0, features=[], armor_class=5))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "Unarmed yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    left, right = FACTORY_ACTOR_PREFIX + "brawler", FACTORY_ACTOR_PREFIX + "post"
    match_id = combat.create_factory_match(
        project_ids=["brawler"], opponent_actor_ids=[right], control_modes={left: "MANUAL", right: "MANUAL"},
        arena_id="battlefield:map.unarmed-yard", match_seed="H53-PLAIN-UNARMED",
    )["match_id"]
    table = TabletopService(combat, tmp_path)
    while table.state(match_id)["menu"]["actor_id"] != left:
        assert act(table, match_id, "end")["status"] == "COMMITTED"

    catalog = combat._load_session(match_id).engine.action_catalog
    strikes = [a for a in catalog.values() if a.owner_id == left and a.display_name == "Unarmed Strike"]
    assert [a.source_definition_id.rsplit(".", 2)[-2:] for a in strikes] == [["natural", "unarmed_strike"]]
    strike_id = strikes[0].source_definition_id
    state = table.state(match_id)
    group = next(row for row in state["menu"]["actions"] if row["source_definition_id"] == strike_id)
    option = next(row for row in group["options"] if right in json.dumps(row))
    assert table.act(match_id, option["candidate_id"], state["menu"]["decision_id"], state["menu"]["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"

    loaded = CombatService(ROOT, tmp_path)
    assert loaded.verify(match_id)["status"] == "PASS"
    assert loaded.replay(match_id)["status"] == "PASS"
    events = loaded._load_session(match_id).engine.events
    attacks = [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == left
               and str((e.payload or {}).get("reason") or "").startswith(f"ATTACK:{strike_id}:")]
    assert len(attacks) == 4  # one Attack action: every attack of Extra Attack at CL 17
    hits = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == left and e.source_definition_id == strike_id]
    assert hits, "the seeded rolls land at least one strike on AC 5"
    for hit in hits:
        assert tuple(hit.target_ids) == (right,)
        assert hit.payload["damage_type"] == "BLUDGEONING"
        assert hit.payload["rolled_or_pending_damage"] == 1 + STRENGTH and hit.payload["hp_damage"] == 1 + STRENGTH
