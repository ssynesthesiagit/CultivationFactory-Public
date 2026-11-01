"""Table-level regression for damage absorbed by Temporary HP at 0 Hit Points."""

import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_c2_review import auto_send
from tests.legacy_fight_support import legacy_zero_hp

ME, ALLY, FOE, SPARE = (f"actor:factory.h41-{name}" for name in ("owner", "ally", "foe", "spare"))


def _table(tmp_path):
    ids = (ME, ALLY, FOE, SPARE)
    docs = [
        sheet(["TAL_BERSERKER_DEATHLESS"]),
        sheet(["LIFE_BASE_BORROWED_BREATH"]),
        sheet([]),
        sheet([]),
    ]
    for index, (actor_id, doc) in enumerate(zip(ids, docs)):
        doc["identity"]["display_name"] = ("Owner", "Ally", "Foe", "Spare")[index]
        doc["ability_scores_and_statistics"]["initiative"] = {"bonus": [100, -50, 50, -100][index]}
        doc["ability_scores_and_statistics"]["hit_points"] = {"maximum": 4 if index == 0 else 500}
        doc["ability_scores_and_statistics"]["armor_class"] = {"base_value": 1}
        if index == 3:
            # Nearby hits on Unconscious creatures now double damage dice. Keep
            # this fixture's critical dagger hit within Borrowed Breath's 4 HP.
            for ability in doc["ability_scores_and_statistics"]["abilities"]:
                ability.update(score=10, modifier=0)
        weapon = "tianxia.mortal.weapon.bi_shou" if index == 3 else "tianxia.mortal.weapon.fu"
        doc["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon, "quantity": 1}]}}]
        folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True} if actor_id == ME else None)
               for doc, actor_id in zip(docs, ids)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    match_id = combat._finish_factory_match(
        bundles, list(ids), {ME: "team:a", ALLY: "team:a", FOE: "team:b", SPARE: "team:b"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, SPARE: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, SPARE],
        control_modes={ME: "MANUAL", ALLY: "LOCAL_AUTO", FOE: "LOCAL_AUTO", SPARE: "LOCAL_AUTO"},
        match_seed="H41-CHOICES", display_name="Stable Temporary HP regression", maximum_rounds=5,
    )["match_id"]
    return combat, table, match_id


def _send(table, match_id, candidate_id, answers=()):
    state = table.state(match_id)
    menu = state["menu"]
    return table.act(match_id, candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], list(answers))


def test_damage_absorbed_by_temp_hp_at_zero_ends_stable_and_replays(tmp_path, legacy_zero_hp):
    from combat.ext.life_state import RECORD

    combat, table, match_id = _table(tmp_path)
    assert _send(table, match_id, table.state(match_id)["menu"]["end_turn"])["status"] == "COMMITTED"

    def attack_id():
        engine = combat._load_session(match_id).engine
        return next(c.candidate_id for c in engine.legal_candidates()
                    if "attack" in c.display_name.lower() and ME in c.target_ids)

    assert auto_send(combat, table, match_id, attack_id())["status"] == "COMMITTED"
    assert combat._load_session(match_id).engine.state.actors[ME].life_state == "DYING"
    assert _send(table, match_id, table.state(match_id)["menu"]["end_turn"])["status"] == "COMMITTED"
    breath = next(c.candidate_id for c in combat._load_session(match_id).engine.legal_candidates()
                  if c.display_name == "Borrowed Breath" and ME in c.target_ids)
    assert auto_send(combat, table, match_id, breath)["status"] == "COMMITTED"
    stable = combat._load_session(match_id).engine.state.actors[ME]
    assert stable.life_state == "STABLE" and stable.current_hp == 0 and stable.temporary_hp == 4
    assert _send(table, match_id, table.state(match_id)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert table.state(match_id)["menu"]["actor_id"] == SPARE
    assert auto_send(combat, table, match_id, attack_id())["status"] == "COMMITTED"

    session = combat._load_session(match_id)
    target = session.engine.state.actors[ME]
    damage = [event for event in session.engine.events if event.event_type == "DAMAGE_COMMITTED" and ME in event.target_ids][-1]
    assert damage.payload["temporary_hp_absorbed"] > 0 and damage.payload["hp_damage"] == 0
    assert target.life_state == "DYING", "damage absorbed by Temporary HP still ends Stable at 0 HP"
    assert (target.turn_flags.get(RECORD) or {}).get("bad") == 2

    fresh = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert fresh.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
