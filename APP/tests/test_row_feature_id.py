"""Native source classifications retain feature identity through factory/table loading."""
import json
from pathlib import Path
import zipfile

import pytest

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("feature_id", [
    "tianxia.subpath.body.sumo.feature.rooted_stance",
    "tianxia.tradition.spirit.mudang.feature.possession_trance",
], ids=["rooted-stance", "possession-trance"])
def test_native_source_rows_have_feature_id_and_table_state_loads(tmp_path, feature_id):
    projects = ["row-owner", "row-foe"]
    actors = [FACTORY_ACTOR_PREFIX + project for project in projects]
    for project in projects:
        document = {
            "identity": {"display_name": project, "cultivation_level": 6,
                         "proficiency_bonus": 3, "key_ability": "WIS"},
            "ability_scores_and_statistics": {
                "abilities": [{"ability": ability, "score": 14, "modifier": 2}
                              for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
                "primary_resource": {"name": "Resonance", "maximum": 30},
                "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
                "speed": {"walking_ft": 30}, "technique_save_dc": 15,
                "technique_attack_bonus": 5,
            },
            "path_and_subpath": {
                "path_feature_record_ids": [feature_id] if project == projects[0] else [],
            },
        }
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))

    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({
        "display_name": "Row identity yard", "width_squares": 8, "height_squares": 8,
        "walls": [], "starts": {"team1": [[2, 3]], "team2": [[5, 3]]},
    })
    match_id = combat.create_factory_match(
        project_ids=[projects[0]], opponent_actor_ids=[actors[1]],
        control_modes={actor: "MANUAL" for actor in actors},
        arena_id="battlefield:map.row-identity-yard", match_seed="ROW-FEATURE-ID",
    )["match_id"]

    # Load from the persisted match rather than inspecting compiler output alone.
    combat = CombatService(ROOT, tmp_path)
    engine = combat._load_session(match_id).engine
    native_rows = [row for row in engine.typed_passive_rows[actors[0]]
                   if row.get("block") == "native_source_record"]
    assert len(native_rows) == 1
    missing = [(store, actor, row) for store in ("typed_reaction_rows", "typed_passive_rows")
               for actor, rows in getattr(engine, store).items() for row in rows
               if not row.get("feature_id")]
    assert missing == []
    assert native_rows[0]["feature_id"] == native_rows[0]["source_record_id"] == feature_id

    state = TabletopService(combat, tmp_path).state(match_id, include_menu=False)
    assert state["match_id"] == match_id
