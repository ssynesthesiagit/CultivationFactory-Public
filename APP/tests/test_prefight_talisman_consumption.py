"""Pre-fight formula casts use the same activation hooks as table casts."""

import json
import zipfile
from pathlib import Path

from combat.ext import talismans
from combat.gate2_runtime_content import AN
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_auto_lane1 import _sheet

ROOT = Path(__file__).resolve().parents[1]
WARDING = "tianxia.talent.talismans.warding_talisman"


def test_prefight_ward_spends_a_talisman_through_table_commit_and_reload(tmp_path):
    sheet = _sheet(WARDING, cl=5)
    folder = tmp_path / "portable_characters" / "warder"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))

    combat = CombatService(ROOT, tmp_path)
    options = combat.factory_prefight_options("warder")
    ward = next(row for row in options["options"] if row["name"] == "Warding Talisman: Dexterity")
    actor_id = FACTORY_ACTOR_PREFIX + "warder"
    match_id = combat.create_factory_match(
        project_ids=["warder"], opponent_actor_ids=[AN], control_modes={actor_id: "MANUAL", AN: "MANUAL"},
        prefight={actor_id: [ward["action_id"]]}, match_seed="L4-WARD-CONSUMPTION",
    )["match_id"]

    before = combat._load_session(match_id)
    actor = before.engine.state.actors[actor_id]
    assert actor.resources[talismans.PREPARED] == next(
        row["initial"] for row in before.engine.typed_bundle_documents[0]["actor_template"]["resources"]
        if row["resource_id"] == talismans.PREPARED
    ) - 1
    assert actor.resources[talismans.EMERGENCY] == 0
    assert any(row.condition_id == "condition:typed.save_bonus" for row in actor.conditions.values())

    table = TabletopService(combat, tmp_path)
    state = table.state(match_id)
    menu = state["menu"]
    hold = next(row for row in menu["actions"] if row["source_definition_id"] == "system:combat.hold_position")
    result = table.act(match_id, hold["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                       state["last_sequence"])
    assert result["status"] == "COMMITTED"

    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    reloaded_actor = reloaded.engine.state.actors[actor_id]
    assert reloaded_actor.resources[talismans.PREPARED] == actor.resources[talismans.PREPARED]
    assert reloaded_actor.resources[talismans.EMERGENCY] == 0
    assert reloaded.mechanical.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
