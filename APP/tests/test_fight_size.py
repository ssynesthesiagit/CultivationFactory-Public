from __future__ import annotations

import statistics
import time
import json
import types
import zipfile
from pathlib import Path

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from app.api import create_app
from app.models import CombatFactoryMatchRequest
from app.core import Settings
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.test_factory_live_match import ROOT, _install
from tests.retired_arena_support import HistoricalArenaWriter


def _geometry_copies(data):
    """New HTTP fights use owner copies, never reserved retired arena ids."""
    store = CombatService(ROOT, data).tabletop_maps
    for source, name in (("builtin-mist-courtyard", "Fixture courtyard"),
                         ("builtin-pillar-arena", "Fixture ring")):
        document = json.loads((FIXTURES / f"{source}.json").read_text())
        store.save({**document, "map_id": name.lower().replace(" ", "-"), "display_name": name})


def _timed_steps(service: CombatService, match_id: str, count: int) -> list[float]:
    timings = []
    for _ in range(count):
        started = time.perf_counter()
        service.local_step(match_id)
        timings.append(time.perf_counter() - started)
    return timings


def test_factory_request_schema_accepts_ten_each_rejects_eleven_and_runs_10v10_ai(tmp_path: Path):
    data = tmp_path / "UserData"
    left = [f"side1-{i}" for i in range(10)]
    right = [f"side2-{i}" for i in range(10)]
    for project_id in left + right:
        _install(data, project_id)
    _geometry_copies(data)

    payload = {
        "project_ids": left,
        "opponent_actor_ids": [FACTORY_ACTOR_PREFIX + project_id for project_id in right],
        "control_modes": {FACTORY_ACTOR_PREFIX + pid: "LOCAL_AUTO" for pid in left + right},
        "arena_id": "battlefield:map.fixture-courtyard",
        "match_seed": "L67B-10V10",
    }
    request = CombatFactoryMatchRequest.model_validate(payload)
    for field, values in (("project_ids", left + ["extra"]),
                          ("opponent_actor_ids", payload["opponent_actor_ids"] + [FACTORY_ACTOR_PREFIX + "extra"])):
        with pytest.raises(ValidationError) as rejected:
            CombatFactoryMatchRequest.model_validate({**payload, field: values})
        assert any(issue["loc"] == (field,) and issue["type"] == "too_long"
                   for issue in rejected.value.errors())

    app = create_app(Settings.from_env(ROOT, data))
    with TestClient(app) as client:
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        for field, values in (("project_ids", left + ["extra"]),
                              ("opponent_actor_ids", payload["opponent_actor_ids"] + [FACTORY_ACTOR_PREFIX + "extra"])):
            response = client.post("/api/combat/factory-matches", json={**payload, field: values}, headers=headers)
            assert response.status_code == 422
        response = client.post("/api/combat/factory-matches", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        created = response.json()
    service = CombatService(ROOT, data)
    match_id = created["match_id"]
    view = service.get_match(match_id)
    actors = view["state"]["actors"]
    assert len(actors) == 20
    arenas = service.factory_arenas()

    def assert_legal_positions(match_view, arena_id):
        grid = SquareGrid(arenas[arena_id])
        seen = set()
        engine = CombatService(ROOT, data)._load_session(match_view["match_id"]).engine
        rows = match_view["state"]["actors"]
        assert len(rows) == 20
        for actor in rows:
            pos = Position.model_validate(actor["position"])
            footprint = engine._footprint(actor["entity_id"])
            assert grid.placement_legal(pos, footprint=footprint, occupied_cells=seen)
            cells = set(grid.footprint_cells(pos, footprint))
            assert not cells & grid.qi_hazard
            seen.update(cells)

    assert_legal_positions(view, "battlefield:map.fixture-courtyard")
    # Exercise each available battlefield and owner geometry copy with the
    # same 20-fighter roster; extra start cells must not cause missing spawns.
    for arena_id in sorted(key for key in arenas if key != "battlefield:map.fixture-courtyard"):
        other_request = request.model_copy(update={"arena_id": arena_id, "match_seed": f"L67B-10V10-{arena_id}"})
        other = service.create_factory_match(**other_request.model_dump())
        assert_legal_positions(other, arena_id)

    print("L67B progress: sampling 10v10 AI turns", flush=True)
    ten_steps = _timed_steps(service, match_id, 2)
    assert CombatService(ROOT, data).get_match(match_id)["state"] == service.get_match(match_id)["state"]
    small_left, small_right = [f"small-a-{i}" for i in range(3)], [f"small-b-{i}" for i in range(3)]
    for project_id in small_left + small_right:
        _install(data, project_id)
    small = service.create_factory_match(
        project_ids=small_left,
        opponent_actor_ids=[FACTORY_ACTOR_PREFIX + pid for pid in small_right],
        control_modes={FACTORY_ACTOR_PREFIX + pid: "LOCAL_AUTO" for pid in small_left + small_right},
        arena_id="battlefield:map.fixture-courtyard", match_seed="L67B-3V3",
    )
    print("L67B progress: sampling 3v3 AI turns", flush=True)
    three_steps = _timed_steps(service, small["match_id"], 2)
    ten_avg, three_avg = statistics.mean(ten_steps), statistics.mean(three_steps)
    timing = (f"10v10 {ten_avg:.3f}s/decision; {ten_avg * 20:.1f}s estimated 20-decision round; "
              f"3v3 {three_avg:.3f}s/decision; {three_avg * 6:.1f}s estimated 6-decision round")
    (tmp_path / "ai-timing.txt").write_text(timing, encoding="utf-8")
    print(f"L67B AI timing: {timing}", flush=True)


def test_overflow_placement_respects_large_footprint_hazards_and_front_line(tmp_path: Path):
    service = CombatService(ROOT, tmp_path)
    arena = service.factory_arenas(include_retired=True)["battlefield:factory_mist_courtyard"]
    grid = SquareGrid(arena)
    spots = [(1, 8), (1, 10), (2, 6), (2, 12)]
    taken = {(x + dx, y + dy) for x, y in spots for dx in range(1) for dy in range(1)}
    spot = service._free_spot(grid, None, taken, footprint=2, team_spots=spots, side="west", front_x=2)
    assert spot is not None
    x, y = spot
    cells = {(x + dx, y + dy) for dx in range(2) for dy in range(2)}
    assert all(0 <= cx < grid.width and 0 <= cy < grid.height for cx, cy in cells)
    assert not cells & grid.blocked and not cells & grid.qi_hazard and not cells & taken
    assert x + 1 <= 2


def _set_owner_size(data, pid, size):
    from tests.test_factory_combat_compiler import SHEET
    sheet = {**SHEET, "identity": {**SHEET["identity"], "size": size}}
    with zipfile.ZipFile(data / "portable_characters" / pid / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))


def test_gargantuan_overflow_refuses_mist_courtyard_without_engine_fallback(tmp_path):
    payload = {**_roster(tmp_path), "arena_id": "battlefield:map.fixture-courtyard"}
    _set_owner_size(tmp_path, "west-9", "Gargantuan")
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"] == "Not enough room on Fixture courtyard for 10 fighters on Team 1"
    assert not list(CombatService(ROOT, tmp_path).matches_root.iterdir())


def test_real_large_sheet_reserves_space_and_records_inherited_runtime_footprint(tmp_path):
    payload = {**_roster(tmp_path, 2), "arena_id": "battlefield:map.fixture-ring"}
    _set_owner_size(tmp_path, "west-0", "Large")
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
        assert response.status_code == 200, response.text
    service = CombatService(ROOT, tmp_path)
    aid = FACTORY_ACTOR_PREFIX + "west-0"
    assert service._actor_footprint_size(aid) == 2
    engine = service._load_session(response.json()["match_id"]).engine
    anchor = engine.state.actors[aid].position
    reserved = {(anchor.x + dx, anchor.y + dy) for dx in range(2) for dy in range(2)}
    assert not reserved & engine.grid.blocked and not reserved & engine.grid.qi_hazard
    assert all((actor.position.x, actor.position.y) not in reserved for actor in engine.state.actors.values() if actor.entity_id != aid)
    # General Factory runtime size authority predates this lane and is locked:
    # the saved engine still uses 1x1. Do not claim setup reservation fixes it.
    assert engine._footprint(aid).width_cells == 1
    service.local_step(response.json()["match_id"])
    restored = CombatService(ROOT, tmp_path)
    assert restored.get_match(response.json()["match_id"])["state"] == service.get_match(response.json()["match_id"])["state"]
    _legal_runtime(restored, response.json()["match_id"], 4)


FIXTURES = Path(__file__).parent / "fixtures" / "fight_size"
MAPS = sorted(FIXTURES.glob("builtin-*.json"))


def _roster(data, count=10):
    _geometry_copies(data)
    left = [f"west-{i}" for i in range(count)]
    right = [f"east-{i}" for i in range(count)]
    for pid in left + right:
        _install(data, pid)
    return {"project_ids": left, "opponent_actor_ids": [FACTORY_ACTOR_PREFIX + pid for pid in right],
            "match_seed": "FIGHT-SIZE-REGRESSION"}


def _post(client, payload):
    headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
    return client.post("/api/combat/factory-matches", json=payload, headers=headers)


@pytest.mark.parametrize("arena_id", ["battlefield:map.fixture-ring", "battlefield:map.fixture-courtyard"])
def test_new_fights_on_fixture_copies_commit_reload_and_replay(tmp_path, arena_id):
    """HTTP setup fixtures remain usable through the real service without sockets."""
    from combat.tabletop_service import TabletopService

    service = CombatService(ROOT, tmp_path)
    payload = {**_roster(tmp_path, 2), "arena_id": arena_id, "maximum_rounds": 2}
    mid = service.create_factory_match(**payload)["match_id"]
    assert service.get_match(mid)["metadata"]["battlefield_id"] == arena_id
    table = TabletopService(service, tmp_path)
    state = table.state(mid)
    assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)
    assert reloaded._load_session(mid).verify()["status"] == reloaded.replay(mid)["status"] == "PASS"


def _legal_runtime(service, match_id, expected):
    engine = service._load_session(match_id).engine
    assert len(engine.state.actors) == expected
    occupied = set()
    for actor in engine.state.actors.values():
        footprint = engine._footprint(actor)
        assert engine.grid.placement_legal(actor.position, footprint=footprint, occupied_cells=occupied)
        cells = set(engine.grid.footprint_cells(actor.position, footprint))
        assert not cells & engine.grid.qi_hazard
        occupied.update(cells)
    return engine.state.model_dump(mode="json")


def test_ten_per_side_table_http_step_commits_and_reloads(tmp_path):
    from combat.tabletop_service import TabletopService
    payload = {**_roster(tmp_path), "arena_id": "battlefield:map.fixture-courtyard"}
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
        assert response.status_code == 200, response.text
        match_id = response.json()["match_id"]
        state = client.get(f"/api/tabletop/matches/{match_id}/state")
        assert state.status_code == 200, state.text
        assert len(state.json()["presentation"]["actors"]) == 20
        headers = {"x-foundry-token": client.get("/api/session").json()["token"]}
        step = client.post(f"/api/tabletop/matches/{match_id}/auto-step", json={"after": state.json()["last_sequence"]}, headers=headers)
        assert step.status_code == 200, step.text
        expected = step.json()["state"]
    service = CombatService(ROOT, tmp_path)
    restored = TabletopService(service, tmp_path).state(match_id)
    assert restored["presentation"]["actors"] == expected["presentation"]["actors"]
    assert restored["last_sequence"] == expected["last_sequence"]
    _legal_runtime(service, match_id, 20)


@pytest.mark.parametrize("map_path", MAPS, ids=lambda path: path.stem)
def test_ten_per_side_on_shipped_editor_maps_http_commit_reload(tmp_path, map_path):
    # Exact JSON from feat/arenas-more; exercise the real map conversion/store,
    # not an AST placement helper or copied production checkout.
    maps = tmp_path / "combat_maps"
    maps.mkdir()
    # Historical map fixtures still test their original geometry as owner copies;
    # a reserved retired built-in id must no longer start a new fight.
    document = json.loads(map_path.read_text())
    document["map_id"] = "fixture-" + map_path.stem
    (maps / (document["map_id"] + ".json")).write_text(json.dumps(document))
    payload = {**_roster(tmp_path), "arena_id": "battlefield:map." + document["map_id"]}
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
        assert response.status_code == 200, response.text
    match_id = response.json()["match_id"]
    service = CombatService(ROOT, tmp_path)
    _legal_runtime(service, match_id, 20)
    service.local_step(match_id)  # a real decision and persistence COMMIT
    expected = service.get_match(match_id)["state"]
    restored = CombatService(ROOT, tmp_path)
    assert restored.get_match(match_id)["state"] == expected
    _legal_runtime(restored, match_id, 20)


@pytest.mark.parametrize("team", [1, 2])
@pytest.mark.parametrize("editor", [False, True], ids=["classic", "editor"])
def test_no_room_refuses_http_before_match_persistence(tmp_path, monkeypatch, team, editor):
    service = CombatService(ROOT, tmp_path)
    arena = json.loads(json.dumps(service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]))
    arena["display_name"] = "Crowded Court"
    # One legal printed spot on the crowded side; the second fighter must fail.
    arena["width_squares"], arena["height_squares"] = 14, 14
    crowded_x = 1 if team == 1 else 12
    arena["starting_positions"] = {"west": {"x": 1, "y": 5}, "east": {"x": 12, "y": 5}}
    arena["terrain_regions"] = [{"region_id": "crowded", "terrain_type": "BLOCKED", "movement_cost": 0,
                                 "description": "Wall", "cells": [{"x": crowded_x, "y": y} for y in range(14) if y != 5]
                                 + [{"x": x, "y": y} for x in ([0] if team == 1 else [13]) for y in range(14)]}]
    if editor:
        arena["team_starts"] = {"team1": [{"x": 1, "y": 5}], "team2": [{"x": 12, "y": 5}]}
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self: {arena["stable_id"]: arena})
    payload = {**_roster(tmp_path), "arena_id": arena["stable_id"]}
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["message"] == f"Not enough room on Crowded Court for 10 fighters on Team {team}"
    assert not list(service.matches_root.iterdir()), "Rejected setup must not create a partial saved fight"


@pytest.mark.parametrize("reverse", [False, True])
def test_unequal_start_counts_keep_overflow_behind_own_front(tmp_path, monkeypatch, reverse):
    service = CombatService(ROOT, tmp_path)
    arena = json.loads(json.dumps(service.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]))
    arena["width_squares"], arena["height_squares"] = 16, 16
    arena["terrain_regions"] = []
    x1, x2 = (10, 4) if reverse else (4, 10)
    arena["team_starts"] = {"team1": [{"x": x1, "y": y} for y in (5, 7, 9)],
                            "team2": [{"x": x2, "y": 5}]}
    monkeypatch.setattr(CombatService, "factory_arenas", lambda self: {arena["stable_id"]: arena})
    payload = {**_roster(tmp_path, 4), "arena_id": arena["stable_id"]}
    with TestClient(create_app(Settings.from_env(ROOT, tmp_path))) as client:
        response = _post(client, payload)
        assert response.status_code == 200, response.text
    actors = response.json()["state"]["actors"]
    for actor in actors:
        is_left = actor["entity_id"].startswith(FACTORY_ACTOR_PREFIX + "west")
        front = x1 if is_left else x2
        west = (not reverse) if is_left else reverse
        assert actor["position"]["x"] <= front if west else actor["position"]["x"] >= front
    _legal_runtime(CombatService(ROOT, tmp_path), response.json()["match_id"], 8)


@pytest.mark.parametrize("arena_id", ["battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"])
@pytest.mark.parametrize("count", [1, 3])
def test_classic_small_ai_replays_are_byte_identical_to_original_setup(tmp_path, arena_id, count):
    import combat.gate5_service as module
    namespace = dict(vars(module))
    exec(compile((FIXTURES / "legacy_setup.py.txt").read_text(), "legacy_setup.py.txt", "exec"), namespace)

    def replay(folder, legacy):
        payload = {**_roster(folder, count), "arena_id": arena_id, "maximum_rounds": 2}
        service = HistoricalArenaWriter(ROOT, folder)
        if legacy:
            service.create_factory_match = types.MethodType(namespace["create_factory_match"], service)
            service._free_spot = namespace["_free_spot"].__func__
        view = service.create_factory_match(**payload)
        match_id = view["match_id"]
        frames = [view["state"]]
        for _ in range(150):
            if service.get_match(match_id)["state"].get("terminal_result"):
                break
            service.local_step(match_id)
            current = service.get_match(match_id)
            frames.append({"state": current["state"], "events": current["recent_events"]})
        assert service.get_match(match_id)["state"]["terminal_result"]
        # Canonical JSON bytes of every state/event frame, not timestamps in
        # unrelated metadata; both complete two-round seeded AI replays.
        return json.dumps(frames, sort_keys=True, separators=(",", ":")).encode()

    assert replay(tmp_path / "original", True) == replay(tmp_path / "fixed", False)


@pytest.mark.parametrize("arena_id", ["battlefield:factory_pillar_arena", "battlefield:factory_mist_courtyard"])
def test_classic_fixture_opponent_keeps_original_far_side_start(tmp_path, arena_id):
    """One Factory fighter against a built-in rival still starts where the
    pre-lane setup put it, on both classic arenas. Each arena seats fighters
    differently: Mist Courtyard prints per-team starts, Pillar Arena hands out
    its spare example starts farthest-from-foe first."""
    from combat.gate2_runtime_content import AN
    _install(tmp_path, "hero")
    service = HistoricalArenaWriter(ROOT, tmp_path)
    arena = service.factory_arenas()[arena_id]
    grid = SquareGrid(arena)
    printed = arena.get("team_starts")
    if printed:
        first = printed["team1"][0]
        expected = {"x": int(first["x"]), "y": int(first["y"])}
    else:
        foe = grid.starting_positions.get(AN)
        spare = [grid.starting_positions[aid] for aid in sorted(grid.starting_positions) if aid != AN]
        if foe is not None:
            spare.sort(key=lambda spot: -(abs(spot.x - foe.x) + abs(spot.y - foe.y)))
        else:
            spare.sort(key=lambda spot: (spot.x, spot.y))
        expected = spare[0].model_dump(mode="json")
    view = service.create_factory_match(project_ids=["hero"], opponent_actor_ids=[AN],
                                       arena_id=arena_id, match_seed="FARTHEST-START")
    actor = next(row for row in view["state"]["actors"] if row["entity_id"] == FACTORY_ACTOR_PREFIX + "hero")
    assert actor["position"] == expected
