"""Lane H1: a d20 rewrite made by a shipped ability survives the real table boundary: preview clone, commit, reload from disk, replay
(the ability is Broken Gourd Recovery; the save is forced by a synthetic Ready so both sides own it)."""

import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.prepared_actions import SOURCE
from tests.test_factory_combat_compiler import SHEET
from tests.test_factory_live_match import ROOT
from tests.test_lock_choices import install
from tests.test_lock2_persistence import act

BROKEN_GOURD = "TAL_DRUNKEN_STYLE_BROKEN_GOURD_RECOVERY"


def _sheet_with_the_ability():
    sheet = json.loads(json.dumps(SHEET))
    block = sheet["spheres_and_talents"]
    block["sphere_record_ids"] = [*block["sphere_record_ids"], "tianxia.sphere.drunken_style"]
    block["learned_talent_record_ids"] = [*block["learned_talent_record_ids"], BROKEN_GOURD]
    return sheet


def test_broken_gourd_reroll_survives_preview_commit_reload_and_replay(monkeypatch, tmp_path):
    for side in ("left", "right"):
        folder = tmp_path / "portable_characters" / side
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(_sheet_with_the_ability()))
    install(monkeypatch, "prepare_options", lambda *a: [{"option_id": "save", "source_id": "test:save", "label": "Save on hold", "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *a: True)

    def resolve(engine, actor, option, event, intent):
        engine._commit_damage(actor, actor.maximum_hp // 2, "UNTYPED", option["source_id"], actor.entity_id, None, reaction_depth=0)   # hurt: the reroll is worth it
        roll = engine._roll_save(actor, "DEX", 60, "test:effect")
        engine._append_event("GM_RIDER", option["source_id"], actor_id=actor.entity_id, payload={"rider": f"save total {roll.total}"})
        return True

    install(monkeypatch, "prepared_action", resolve)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "H1 yard", "width_squares": 12, "height_squares": 8, "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    modes = {FACTORY_ACTOR_PREFIX + side: "MANUAL" for side in ("left", "right")}
    view = combat.create_factory_match(project_ids=["left"], opponent_actor_ids=[FACTORY_ACTOR_PREFIX + "right"], control_modes=modes,
                                       arena_id="battlefield:map.h1-yard", match_seed="H1-TABLE")
    mid = view["match_id"]
    table = TabletopService(combat, tmp_path)
    actor_id = table.state(mid)["menu"]["actor_id"]
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    first = act(table, mid, "system:combat.hold_position")
    assert first["status"] == "REACTION_REQUIRED"
    state, menu = first["state"], first["state"]["menu"]
    answer = {**first["reaction"]["context"], "selection": "USE"}
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    assert table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rewrites = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN"]
    assert len(rewrites) == 1 and rewrites[0].source_definition_id == BROKEN_GOURD and rewrites[0].actor_id == actor_id
    assert loaded.engine.state.actors[actor_id].resources["resource:core.martial_focus"] == 0
    assert loaded.mechanical.replay()["status"] == "PASS"
