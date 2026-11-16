"""Drawing Breath support and flight through committed tabletop fights."""
import json
import zipfile
from pathlib import Path

import pytest

from combat import falling, flight
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
from tests.test_walkable_roofs import roof_document, route, end_turn, gather

ROOT = Path(__file__).resolve().parents[1]
OWNER = FACTORY_ACTOR_PREFIX + "support-owner"
FOE = FACTORY_ACTOR_PREFIX + "support-foe"
WIND = "TAL_AIR_WIND_BORNE_BODY"
DRAW = "TAL_AIR_DRAWING_BREATH"


def fight(tmp_path, *, roof, fly=False, success=False):
    for project, ids, initiative in (
        ("support-owner", [DRAW], 100),
        ("support-foe", [WIND] if roof and not fly else [], -100),
    ):
        data = sheet(ids, cl=11, dc=1 if success else 60)
        stats = data["ability_scores_and_statistics"]
        stats["initiative"] = {"bonus": initiative}
        stats["armor_class"] = {"base_value": 0}
        stats["technique_attack_bonus"] = 100
        if project == "support-owner" and roof or project == "support-foe" and fly:
            stats["speed"]["flying_ft"] = 30
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(data))
    combat = CombatService(ROOT, tmp_path)
    if roof:
        document = roof_document(owner_start=(3, 3), foe_start=(9, 3))
    else:
        document = {"display_name": "Support ground", "width_squares": 20,
                    "height_squares": 12, "walls": [],
                    "starts": {"team1": [[3, 6]], "team2": [[8, 6]]}}
    saved = combat.tabletop_maps.save(document)
    mid = combat.create_factory_match(
        project_ids=["support-owner"], opponent_actor_ids=[FOE],
        control_modes={OWNER: "MANUAL", FOE: "MANUAL"},
        arena_id="battlefield:map." + saved["map_id"],
        match_seed="SW-AIR-0", maximum_rounds=5)["match_id"]
    table = TabletopService(combat, tmp_path)
    if roof:
        route(combat, table, mid, [(3, 3, 0), (3, 3, 1), (3, 3, 2), (2, 3, 2)], mode="fly")
        end_turn(combat, mid)
        if not fly:
            gather(combat, mid)
        route(combat, table, mid, [(9, 3, 0), (9, 3, 1), (9, 3, 2),
                                   (8, 3, 2), (7, 3, 2), (6, 3, 2), (5, 3, 2)], mode="fly")
        end_turn(combat, mid)
    return combat, table, mid


def pull(combat, table, mid):
    engine = combat._load_session(mid).engine
    target = engine.state.actors[FOE]
    before_hp, before_events = target.current_hp, len(engine.events)
    state = table.state(mid)
    assert state["menu"]["actor_id"] == OWNER
    group = next(g for g in state["menu"]["actions"]
                 if g["label"] == "Wind Lash: Cut + Drawing Breath")
    option = next(o for o in group["options"] if FOE in o["target_ids"])
    result = table.act(mid, option["candidate_id"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"])
    assert result["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    events = engine.events[before_events:]
    assert any(e.event_type == "SAVE_ROLLED" for e in events)
    return before_hp, events


def test_drawing_breath_stops_at_last_supported_roof_square(tmp_path):
    combat, table, mid = fight(tmp_path, roof=True)
    engine = combat._load_session(mid).engine
    target = engine.state.actors[FOE]
    assert not flight.profile(engine, target).speed_ft
    assert falling.supported(engine, target, Position(x=4, y=3, z=2))
    assert not falling.supported(engine, target, Position(x=3, y=3, z=2))
    hp, events = pull(combat, table, mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    target = fresh.state.actors[FOE]
    assert target.position == Position(x=4, y=3, z=2)
    assert not falling.required(fresh, target)
    assert not any(e.event_type == "MOVEMENT_COLLISION" or
                   e.source_definition_id == "system:combat.falling" for e in events)
    damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert len(damage) == 1
    assert target.current_hp == hp - int(damage[0].payload["reduced_to"])


def test_drawing_breath_pulls_a_flyer_the_full_distance_over_open_air(tmp_path):
    combat, table, mid = fight(tmp_path, roof=True, fly=True)
    pull(combat, table, mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    target = fresh.state.actors[FOE]
    assert flight.profile(fresh, target).speed_ft > 0
    assert target.position == Position(x=3, y=3, z=2)
    assert not falling.required(fresh, target)


@pytest.mark.parametrize("success,expected_x", [(False, 6), (True, 7)])
def test_drawing_breath_flat_ground_save_distances_survive_reload(tmp_path, success, expected_x):
    combat, table, mid = fight(tmp_path, roof=False, success=success)
    pull(combat, table, mid)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert fresh.state.actors[FOE].position == Position(x=expected_x, y=6)
