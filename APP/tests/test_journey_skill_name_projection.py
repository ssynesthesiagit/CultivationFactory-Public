"""A cold Journey uses the same standard skill names as fight admission."""
import json
from zipfile import ZipFile

import pytest

from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatService
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet


@pytest.mark.parametrize(("attuned", "expected"), [(False, 7), (True, 8)])
def test_gm_journey_perception_uses_the_compiled_total_after_reload(tmp_path, attuned, expected):
    project = "a1b2c3d4"
    actor = FACTORY_ACTOR_PREFIX + project
    jade = {"name": "Brow-Jade of Serene Wisdom (+2)", "body_slot": "Face / Brow",
            "attunement_slots": 1, "ability_enhancement": {"ability": "WIS", "bonus": 2}}
    doc = sheet([], score=14)
    doc["ability_scores_and_statistics"]["skills"] = [{"skill": "perception", "bonus": 7}]
    doc["equipment"] = [{"starting_kit": {"items": [], "resolved_treasure_purchases": {"wondrous": [jade]}}}]
    package = tmp_path / "portable_characters" / project
    package.mkdir(parents=True)
    with ZipFile(package / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    ButtonStore(tmp_path / "tabletop_buttons").save_attunement(project, ["wondrous.0"] if attuned else [])

    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"map_id": "perception-check", "display_name": "Woodland trail",
        "width_squares": 10, "height_squares": 10, "objects": [], "starts": {"team1": [[2, 2]]}})
    journey = service.create_journey(project_ids=[project], arena_id="battlefield:map.perception-check",
                                     positions={actor: {"x": 2, "y": 2}}, base_paces={actor: 1800})
    jid = journey["journey_id"]
    requested = service.journey_world_fact(jid, journey["revision"], {
        "source": "journey:noncombat_check", "subject": actor, "kind": "request", "scope": "lookout",
        "value": {"purpose": "Watch the woodland trail", "ability": "WIS", "skill": "perception", "dc": 15,
                  "sect_context": 0, "role": "", "duty": "", "institution": "", "recovery": ""},
        "expires_at": journey["seconds"] + 60, "readers": [actor],
    })
    cold = CombatService(ROOT, tmp_path)
    rolled = cold.journey_act(jid, requested["revision"], actor, "check_start", {"scope": "lookout", "merit": 0})
    reloaded = CombatService(ROOT, tmp_path).journey_state(jid)
    assert reloaded == rolled
    [roll] = [event["roll"] for event in reloaded["events"] if event["kind"] == "JOURNEY_CHECK_ROLLED"]
    assert roll["total"] - roll["natural_result"] == expected
