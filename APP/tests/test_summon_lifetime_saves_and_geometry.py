"""Table level regressions for summon lifetime, owner saves and data driven size."""

import json
import zipfile

from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.test_summons import _sheet
from tests.h1_support import ROOT

OWNER = FACTORY_ACTOR_PREFIX + "h64-owner"
FOE = FACTORY_ACTOR_PREFIX + "h64-foe"
BONE = "tianxia.subpath.body.bone_monarch.feature.bone_guard_manifestation"
PAPER = "tianxia.subpath.qi.paper_cultivator.feature.paper_dragon"
SPECTER = "tianxia.tradition.spirit.soul_warden_necromancer.feature.raise_specter"


def _fight(tmp_path, source, *, battlefield=None):
    documents = {}
    for project, talent in (("h64-owner", source), ("h64-foe", None)):
        document = _sheet([talent] if talent else [])
        document["identity"]["display_name"] = project
        if project == "h64-owner" and source == BONE:
            document["identity"]["path"] = "Body Refining"
            document["ability_scores_and_statistics"]["primary_resource"] = {"name": "Stamina", "maximum": 30}
        if project == "h64-owner" and source == SPECTER:
            document["identity"]["path"] = "Spirit Awakening"
            document["ability_scores_and_statistics"]["primary_resource"] = {"name": "Resonance", "maximum": 30}
            for index, row in enumerate(document["ability_scores_and_statistics"]["abilities"]):
                row.update(score=16 + index * 2, modifier=3 + index)
        folder = tmp_path / "portable_characters" / project
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        documents[project] = document
    combat = CombatService(ROOT, tmp_path)
    if source == SPECTER or battlefield is not None:
        from combat.factory_compiler import compile_character
        bundles = [compile_character(documents[pid], actor_id=aid) for pid, aid in (("h64-owner", OWNER), ("h64-foe", FOE))]
        if source == SPECTER:
            # Synthetic custody input: this owner brings one Soul Fragment.
            for resource in bundles[0]["actor_template"]["resources"]:
                if resource["resource_id"] == "resource:named.soul_fragment":
                    resource["initial"] = 1
        from tests.test_r6_6_8_footprint_mechanics_e2 import _grid_document
        # Preserve the historical base geometry instead of depending on catalog order.
        arena = {**combat.factory_arenas(include_retired=True)["battlefield:factory_mist_courtyard"], **(battlefield or _grid_document()),
                 "stable_id": "battlefield:summon-regression", "display_name": "Summon regression"}
        view = combat._finish_factory_match(bundles, [OWNER, FOE], {OWNER: "team:a", FOE: "team:b"},
            {OWNER: {"x": 0, "y": 0}, FOE: {"x": 6, "y": 6}}, arena, [OWNER], [FOE],
            control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed="H64-SUMMON-TABLE",
            display_name="Summon regression", maximum_rounds=20)
    else:
        view = combat.create_factory_match(project_ids=["h64-owner"], opponent_actor_ids=[FOE],
            control_modes={OWNER: "MANUAL", FOE: "MANUAL"}, match_seed="H64-SUMMON-TABLE")
    return combat, TabletopService(combat, tmp_path), view["match_id"]


def _act(table, match_id, source="end"):
    state = table.state(match_id)
    menu = state["menu"]
    if menu["manual"]:
        candidate = menu["end_turn"] if source == "end" else next(
            option["candidate_id"] for group in menu["actions"] if source in group["source_definition_id"]
            for option in group["options"])
        return table.act(match_id, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"])
    return table.auto_step(match_id, state["last_sequence"])


def _call_summon(combat, table, match_id, source):
    for _ in range(20):
        state = table.state(match_id)
        if state["menu"]["actor_id"] == OWNER:
            break
        _act(table, match_id)
    assert _act(table, match_id, source)["status"] == "COMMITTED"
    return combat._load_session(match_id)


def test_bone_guard_one_minute_expires_through_table_commit_reload_and_replay(tmp_path):
    combat, table, match_id = _fight(tmp_path, BONE)
    loaded = _call_summon(combat, table, match_id, BONE)
    guard = next(actor for actor in loaded.engine.state.actors.values() if actor.summon and actor.summon["group"] == "bone_guard")
    assert guard.summon["expires_on"].startswith("START_OF_SLOT_AT:")
    from combat.ext.effect_durations import parse_round
    deadline = parse_round(guard.summon["expires_on"])
    for _ in range(80):
        if not guard.active:
            break
        _act(table, match_id)
        loaded = CombatService(ROOT, tmp_path)._load_session(match_id)
        guard = loaded.engine.state.actors[guard.entity_id]
        clock = (loaded.engine.state.round_number, loaded.engine.state.current_slot_index)
        if clock < deadline:
            assert guard.active
    assert not guard.active and guard.summon["status"] == "dismissed"
    assert any(event.event_type == "SUMMON_DISMISSED" and event.payload.get("reason") == "DURATION_ENDED"
               for event in loaded.engine.events)
    dismissal = next(event for event in loaded.engine.events if event.event_type == "SUMMON_DISMISSED"
                     and event.payload.get("reason") == "DURATION_ENDED")
    assert sum(event.event_type == 'SUMMON_DISMISSED' and event.payload.get('reason') == 'DURATION_ENDED'
               for event in loaded.engine.events) == 1
    assert dismissal.payload["log"] == "Bone Guard's 1 minute is up; it disappears."
    # Native lifetime expiry runs at turn_boundary_start, before TURN_STARTED
    # and any gameplay of the deadline turn (the former rider expired after it).
    boundary = next(event for event in loaded.engine.events[dismissal.sequence:] if event.event_type == "TURN_STARTED")
    assert (boundary.payload["round"], boundary.payload["slot"]) == deadline
    from combat.history_feed import format_history_feed
    feed = format_history_feed([dismissal.model_dump(mode="json")], [], pre_state=None,
        post_state=loaded.engine.state.model_dump(mode="json"), actor_names={guard.entity_id: "Bone Guard"}, definition_names={})
    assert feed[0]["summary"] == "Bone Guard's 1 minute is up; it disappears."
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_bone_guard_owner_saves_survive_table_commit_reload_and_replay(tmp_path):
    combat, table, match_id = _fight(tmp_path, BONE)
    loaded = _call_summon(combat, table, match_id, BONE)
    guard = next(actor for actor in loaded.engine.state.actors.values() if actor.summon and actor.summon["group"] == "bone_guard")
    owner = loaded.engine.state.actors[OWNER]
    assert guard.saving_throws == owner.saving_throws
    assert CombatService(ROOT, tmp_path)._load_session(match_id).mechanical.replay()["status"] == "PASS"


def test_paper_dragon_large_footprint_survives_table_commit_reload_and_replay(tmp_path):
    combat, table, match_id = _fight(tmp_path, PAPER)
    loaded = _call_summon(combat, table, match_id, PAPER)
    dragon = next(actor for actor in loaded.engine.state.actors.values() if actor.summon and actor.summon["group"] == "paper_dragon")
    assert dragon.summon["size"] == "large"
    assert len(loaded.engine._actor_cells(dragon)) == 4
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    assert len(reloaded.engine._actor_cells(reloaded.engine.state.actors[dragon.entity_id])) == 4
    projected = next(a for a in table.state(match_id)["presentation"]["actors"] if a["entity_id"] == dragon.entity_id)
    assert len(projected["footprint"]["occupied_cells"]) == 4
    assert reloaded.mechanical.replay()["status"] == "PASS"




def test_predatory_specter_only_inherits_mental_saves_after_table_reload(tmp_path):
    combat, table, match_id = _fight(tmp_path, SPECTER)
    loaded = _call_summon(combat, table, match_id, SPECTER)
    specter = next(a for a in loaded.engine.state.actors.values() if a.summon and a.summon["group"] == "predatory_specter")
    owner = loaded.engine.state.actors[OWNER]
    for ability in ("INT", "WIS", "CHA"):
        assert specter.saving_throws[ability] == owner.saving_throws[ability]
    for ability in ("STR", "DEX", "CON"):
        assert specter.saving_throws[ability] != owner.saving_throws[ability]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_starting_rider_at_corner_shares_large_mount_space():
    from combat.gate2_engine import Gate2Engine
    from tests.test_mounts import rider_bundle, ME, MOUNT, FOE as MOUNT_FOE
    engine = Gate2Engine(ROOT, match_seed="CORNER-RIDER", typed_bundles=(rider_bundle(),),
        roster_setup={"primary_actor_ids": [ME, MOUNT_FOE], "team_by_actor": {ME: "team:a", MOUNT_FOE: "team:b"},
                      "starting_positions": {ME: {"x": 0, "y": 0}, MOUNT_FOE: {"x": 12, "y": 6}}})
    rider, mount = engine.state.actors[ME], engine.state.actors[MOUNT]
    assert mount.active and mount.summon["status"] == "present"
    assert (mount.position.x, mount.position.y) == (0, 0)
    assert set(engine._actor_cells(rider)) < set(engine._actor_cells(mount))
    from combat.ext.mounts import mount_of
    assert mount_of(engine, rider) is mount


def test_dragon_cannot_appear_when_only_fourth_square_is_blocked(tmp_path):
    from tests.test_r6_6_8_footprint_mechanics_e2 import _grid_document
    # Only (1, 0) would fit beside the owner, except its fourth cell (2, 1).
    free = {(0, 0), (1, 0), (2, 0), (1, 1), (6, 6)}
    arena = _grid_document(blocked=[(x, y) for y in range(7) for x in range(7) if (x, y) not in free])
    combat, table, match_id = _fight(tmp_path, PAPER, battlefield=arena)
    loaded = _call_summon(combat, table, match_id, PAPER)
    dragon = next(a for a in loaded.engine.state.actors.values() if a.summon and a.summon["group"] == "paper_dragon")
    assert not dragon.active and dragon.summon["status"] == "waiting"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_large_dragon_moves_with_full_footprint_and_uses_edge_reach_at_table(tmp_path):
    from tests.test_r6_6_8_footprint_mechanics_e2 import _grid_document
    from combat.gate2_runtime_models import CandidateKind
    combat, table, match_id = _fight(tmp_path, PAPER, battlefield=_grid_document(blocked=[(3, 2)]))
    loaded = _call_summon(combat, table, match_id, PAPER)
    dragon = next(a for a in loaded.engine.state.actors.values() if a.summon and a.summon["group"] == "paper_dragon")
    assert len(loaded.engine._actor_cells(dragon)) == 4
    _act(table, match_id, "command.paper_dragon")
    _act(table, match_id)
    state = table.state(match_id)
    assert state["menu"]["actor_id"] == dragon.entity_id
    engine = combat._load_session(match_id).engine
    moves = [c for c in engine.legal_candidates() if c.kind == CandidateKind.MOVE]
    assert moves
    assert not any(c.destination.x == 2 and c.destination.y == 1 for c in moves)
    # Move beside the foe with the dragon's right/bottom edge, not its anchor.
    candidate = next(c for c in moves if (c.destination.x, c.destination.y) == (4, 4))
    assert table.act(match_id, candidate.candidate_id, state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(match_id)
    engine = reloaded.engine
    dragon = engine.state.actors[dragon.entity_id]
    foe = engine.state.actors[FOE]
    assert engine.grid.distance_ft(dragon.position, foe.position) == 10
    assert engine._distance_actor_to_actor(dragon, foe) == 5
    assert any(c.target_ids == (FOE,) and ".attack" in c.source_definition_id for c in engine.legal_candidates())
    assert len(engine._actor_cells(dragon)) == 4
    assert reloaded.mechanical.replay()["status"] == "PASS"
