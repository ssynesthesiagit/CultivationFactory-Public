"""Offline PNG and persisted table coverage; never launches a browser."""
import copy
import hashlib
import io
import json
import math
import multiprocessing
from pathlib import Path
import queue
import threading
import time

import pytest
from PIL import Image

from agent_seats.snapshots import SnapshotRenderer, project_map, render_png
from tests.test_agent_seats import FakeProvider, raw_state, runner_for
from tests.test_hunt5_player_choices import fixture, FOE, PLAYER


@pytest.mark.parametrize("filled", [True, False])
@pytest.mark.parametrize("edge", [[8.2, 4], [7.72, 4.96]])
def test_circle_uses_table_center_radius_and_clips_visibility(filled, edge):
    from combat.tabletop import normalize_map, table_section
    source = table_section(normalize_map({
        "map_id": "circle-check", "name": "Circle check",
        "width_squares": 12, "height_squares": 8,
        "walls": [{"shape": "circle", "points": [[7, 4], edge],
                   "filled": filled, "blocks": "sight_and_movement"}],
    }))
    cells = [[x, y] for x in range(12) for y in range(8)]
    board = project_map(source, cells, 12, 8, [])
    points = [p for wall in board["walls"] for p in wall["points"]]
    assert points
    assert (min(x for x, y in points), max(x for x, y in points)) == (5800, 8200)
    assert (min(y for x, y in points), max(y for x, y in points)) == (2800, 5200)
    assert all(wall["filled"] is filled for wall in board["walls"])
    if not filled:
        assert all(abs(math.hypot(x - 7000, y - 4000) - 1200) < 3 for x, y in points)
    clipped = project_map(source, [[8, 4]], 12, 8, [])
    assert clipped["walls"]
    assert all(8000 <= x <= 9000 and 4000 <= y <= 5000
               for wall in clipped["walls"] for x, y in wall["points"])
    assert project_map(source, [[0, 0]], 12, 8, [])["walls"] == []


@pytest.mark.parametrize("size", [1, 2])
def test_real_table_tree_trunks_are_drawn_and_visibility_clipped(size):
    from combat.tabletop import normalize_map, rasterize, table_section
    document = normalize_map({
        "map_id": "tree-check", "name": "Tree check",
        "width_squares": 10, "height_squares": 8,
        "trees": [{"x": 2, "y": 3, "size": size, "seed": 77}],
    })
    source = table_section(document)
    trunks, _ = rasterize(document)
    cells = [[x, y] for x in range(10) for y in range(8)]
    board = project_map(source, cells, 10, 8, [])
    assert board["trees"] == [{"name": "Tree trunk: blocks movement and sight",
                               "cells": [list(c) for c in sorted(trunks)]}]
    partial = project_map(source, [[2, 3]], 10, 8, [])
    assert partial["trees"][0]["cells"] == [[2, 3]]
    assert project_map(source, [[0, 0]], 10, 8, [])["trees"] == []
    view = {"map": partial, "visible_cells": [[2, 3]], "fighter": "a", "actors": []}
    with Image.open(io.BytesIO(render_png(view))) as image:
        # Interior trunk paint, away from its label and grid; unseen neighbour stays dark.
        assert image.getpixel((217, 330)) == (109, 74, 45)
        assert image.getpixel((290, 330)) == (20, 27, 37)


def view_fixture():
    cells = [[x,y] for y in range(8) for x in range(10) if x < 7]
    board = project_map({"scale":100, "walls":[
        {"shape":"line", "points":[[650,0],[650,800]], "blocks":"sight"},
        {"shape":"rect", "points":[[100,100],[200,200]], "filled":True},
        {"shape":"circle", "points":[[300,100],[500,300]], "filled":False}],
        "terrain":[{"type":"DIFFICULT", "cells":[[1,3],[2,3],[9,3]]}]},cells,10,8,
        [{"trigger_profile":{"name":"Darkness","owner_id":"hidden-caster"},
          "affected_cells":[{"x":4,"y":4},{"x":9,"y":4}]}])
    return {"fighter":"a", "match_id":"fixture", "state_version":3,"visible_cells":cells,"map":board,
            "last_seen":[{"position":{"x":8,"y":4},"round":1}],
            "actors":[{"entity_id":"a","display_name":"Lin","team_id":"blue","position":{"x":2,"y":5},
                       "hit_points":{"current":18,"maximum":25}},
                      {"entity_id":"b","display_name":"Bo","team_id":"red","position":{"x":5,"y":5},
                       "hit_points":{"current":12,"maximum":20}}],"objects":[]}


def test_png_is_deterministic_and_fast():
    view = view_fixture()
    start = time.perf_counter()
    png = render_png(view)
    elapsed = time.perf_counter()-start
    assert elapsed < .150
    assert hashlib.sha256(png).hexdigest() == "233dd664a6fedda66c0bb33ab89e98eb682f62eda01c3a96688328765b69dce7"
    assert png == render_png(copy.deepcopy(view))
    with Image.open(io.BytesIO(png)) as image:
        assert image.size == (768,768)
        assert image.format == "PNG"


def test_map_projection_has_no_unseen_cells_or_geometry():
    view = view_fixture()
    board = view["map"]
    assert board["terrain"][0]["cells"] == [[1,3],[2,3]]
    assert board["zones"][0]["cells"] == [{"x":4,"y":4}]
    assert board["zones"][0]["name"] == "Darkness"
    assert 'hidden-caster' not in json.dumps(board)
    assert all(0 <= x <= 7000 and 0 <= y <= 8000 for wall in board["walls"] for x,y in wall["points"])
    hidden = {"shape":"rect","points":[[800,100],[900,200]],"filled":True}
    assert project_map({"scale":100,"walls":[hidden]},view["visible_cells"],10,8,[])['walls'] == []


def test_cache_is_bounded_and_scoped_to_view_and_version(monkeypatch):
    import agent_seats.snapshots as snapshots
    calls = []
    monkeypatch.setattr(snapshots,"render_png",lambda view: calls.append(copy.deepcopy(view)) or b"png")
    renderer = SnapshotRenderer()
    view = view_fixture()
    assert renderer(view) == renderer(copy.deepcopy(view)) == b"png"
    assert len(calls) == 1
    view["state_version"] += 1
    renderer(view)
    view["fighter"] = "b"
    renderer(view)
    view["match_id"] = "other"
    renderer(view)
    view["visible_cells"] = []
    renderer(view)
    assert len(calls) == 5
    for version in range(20):
        view["state_version"] = version
        renderer(view)
    assert len(renderer._cache) == 16


@pytest.mark.parametrize("vision",[True,False])
def test_default_renderer_reaches_provider_on_each_turn(tmp_path, vision):
    combat,table,mid,*_ = fixture(tmp_path,"AIR_BASE_GATHER_CURRENT")
    from combat.gate4_controller import LocalDeterministicController
    combat.controller = LocalDeterministicController()
    images = []
    fake = FakeProvider()
    def provider(settings,prompt,png):
        images.append(png)
        return fake(settings,prompt,png)
    runner,_ = runner_for(tmp_path,table,provider)
    if not vision:
        def forbidden_renderer(view):
            pytest.fail("Text-only providers must not render images")
        runner.render_png = forbidden_renderer
    registry = json.loads(runner.registry.path.read_text())
    registry['providers'][0]['vision'] = vision
    runner.registry.path.write_text(json.dumps(registry))
    runner.set_seat(mid,FOE,"MODEL","fake")
    runner.set_seat(mid,PLAYER,"MODEL","fake")
    assert runner.drive(mid,max_steps=3) == 3
    assert len(images) == 3
    assert all(png.startswith(b'\x89PNG\r\n\x1a\n') if vision else png is None for png in images)
    assert combat._load_session(mid).verify()['status'] == 'PASS'


def test_sight_memory_survives_reload_without_hidden_current_state(tmp_path, monkeypatch):
    from combat import senses
    combat,table,mid,*_ = fixture(tmp_path,"AIR_BASE_GATHER_CURRENT")
    runner,_ = runner_for(tmp_path,table)
    state = raw_state(runner,mid)
    session = combat._load_session(mid)
    runner.own_view(mid,state,FOE,session)
    observed_round = session.engine.state.round_number
    before = next(a for a in state['presentation']['actors'] if a['entity_id'] == PLAYER)['position']
    menu = state['menu']
    assert table.act(mid,menu['end_turn'],menu['decision_id'],menu['state_version'],0)['status'] == 'COMMITTED'
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    table = TabletopService(CombatService(ROOT,tmp_path),tmp_path)
    reopened,_ = runner_for(tmp_path,table)
    state = raw_state(reopened,mid)
    session = table.combat._load_session(mid)
    monkeypatch.setattr(senses,'perception',lambda *args: {'cells':[[0,0]],'creatures':[FOE]})
    altered = copy.deepcopy(state)
    hidden = next(a for a in altered['presentation']['actors'] if a['entity_id'] == PLAYER)
    hidden['position'] = {'x':99,'y':99}
    hidden['display_name'] = 'SECRET'
    hidden['hit_points']['current'] = 999
    view,_ = reopened.own_view(mid,altered,FOE,session)
    assert [a['entity_id'] for a in view['actors']] == [FOE]
    assert view['last_seen'] == [{'position':before,'round':observed_round,'hostile':1}]
    assert 'SECRET' not in json.dumps(view)
    original_png = render_png(view)
    hidden['position'] = {'x':100,'y':100}
    again,_ = reopened.own_view(mid,altered,FOE,session)
    assert render_png(again) == original_png


def test_observed_defeat_removes_hostile_search_memory_after_reload(tmp_path, monkeypatch):
    from combat import senses
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    runner, _ = runner_for(tmp_path, table)
    state = raw_state(runner, mid)
    session = combat._load_session(mid)
    monkeypatch.setattr(senses, "perception", lambda *args: {"cells": [[0, 0]], "creatures": [FOE, PLAYER]})
    runner.own_view(mid, state, FOE, session)
    path = table._match_dir(mid) / "Agent_Sight.json"
    assert json.loads(path.read_text())[FOE][PLAYER]["hostile"] == 1
    observed = copy.deepcopy(state)
    next(a for a in observed["presentation"]["actors"] if a["entity_id"] == PLAYER)["active"] = False
    view, known = runner.own_view(mid, observed, FOE, session)
    assert PLAYER in known and any(a["entity_id"] == PLAYER and a["active"] is False for a in view["actors"])
    assert PLAYER not in json.loads(path.read_text())[FOE]
    reopened, _ = runner_for(tmp_path, TabletopService(CombatService(ROOT, tmp_path), tmp_path))
    monkeypatch.setattr(senses, "perception", lambda *args: {"cells": [[0, 0]], "creatures": [FOE]})
    # Hidden current data still says active; it must not resurrect observed defeat.
    view, _ = reopened.own_view(mid, state, FOE, reopened.table.combat._load_session(mid))
    assert view["last_seen"] == []
    assert PLAYER not in json.loads(path.read_text())[FOE]


@pytest.mark.parametrize("workers", ["threads", "processes"])
def test_independent_runners_serialize_sight_memory_and_reload(tmp_path, monkeypatch, workers):
    """Pause one read while another runner tries to update the same real fight."""
    from combat import senses
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT

    if workers == "processes" and "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("Cross-process lock regression requires POSIX fork")
    combat, table, mid, *_ = fixture(tmp_path, "AIR_BASE_GATHER_CURRENT")
    first, _ = runner_for(tmp_path, table)
    other_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    second, _ = runner_for(tmp_path, other_table)
    state = raw_state(first, mid)
    sessions = [combat._load_session(mid), other_table.combat._load_session(mid)]
    path = table._match_dir(mid) / "Agent_Sight.json"
    path.write_text("{}\n", encoding="utf-8")
    context = multiprocessing.get_context("fork") if workers == "processes" else threading
    reading, release, competing_read, attempting, second_done = (context.Event() for _ in range(5))
    results = multiprocessing.get_context("fork").Queue() if workers == "processes" else queue.Queue()
    original_read = Path.read_text

    def paused_read(self, *args, **kwargs):
        text = original_read(self, *args, **kwargs)
        if self == path:
            if threading.current_thread().name == "sight-first":
                reading.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release the sight reader")
            elif threading.current_thread().name == "sight-second":
                competing_read.set()
        return text

    monkeypatch.setattr(Path, "read_text", paused_read)

    def update(label, runner, actor_id, session):
        threading.current_thread().name = label
        try:
            if label == "sight-second":
                attempting.set()
            runner.own_view(mid, state, actor_id, session)
            results.put(None)
        except Exception as exc:
            results.put(type(exc).__name__)
        finally:
            if label == "sight-second":
                second_done.set()

    worker_type = context.Process if workers == "processes" else context.Thread
    jobs = [worker_type(target=update, args=("sight-first", first, FOE, sessions[0])),
            worker_type(target=update, args=("sight-second", second, PLAYER, sessions[1]))]
    started = []
    try:
        jobs[0].start()
        started.append(jobs[0])
        assert reading.wait(5), "First runner never reached the sight-memory read"
        jobs[1].start()
        started.append(jobs[1])
        if workers == "processes":
            print("Task-owned sight worker PIDs:", [job.pid for job in started])
        assert attempting.wait(5), "Second runner never attempted its update"
        overlapped = competing_read.wait(.3)
        if overlapped:
            assert second_done.wait(5), "Concurrent runner did not finish its update"
    finally:
        release.set()
        for job in started:
            job.join(5)
        for job in started:
            if workers == "processes" and job.is_alive():
                job.terminate()  # Only this test's explicitly started child.
                job.join(5)
    assert all(not job.is_alive() for job in started)
    assert [results.get(timeout=2) for _ in started] == [None, None]
    memory = json.loads(path.read_text())
    assert set(memory) == {FOE, PLAYER}, "An independent runner lost another observer's memory"
    assert not overlapped, "The second runner read before the first update finished"
    if workers == "processes":
        results.close()
        results.join_thread()

    menu = state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    reopened_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    reopened, _ = runner_for(tmp_path, reopened_table)
    reloaded = raw_state(reopened, mid)
    session = reopened_table.combat._load_session(mid)
    # Both observers now see only themselves: prior observations must survive,
    # without exposing the other creature's current state to either observer.
    monkeypatch.setattr(senses, "perception", lambda engine, actor: {
        "cells": [[0, 0]], "creatures": [actor.entity_id]})
    for observer, hidden in [(FOE, PLAYER), (PLAYER, FOE)]:
        view, _ = reopened.own_view(mid, reloaded, observer, session)
        assert [a["entity_id"] for a in view["actors"]] == [observer]
        assert view["last_seen"] == [memory[observer][hidden]]


def test_default_png_is_sent_for_an_off_turn_reaction(tmp_path):
    combat,table,mid,cid,_ = fixture(tmp_path,"TAL_FENCING_FOOTWORK")
    images = []
    fake = FakeProvider()
    def provider(settings,prompt,png):
        images.append(png)
        return fake(settings,prompt,png)
    runner,_ = runner_for(tmp_path,table,provider)
    registry = json.loads(runner.registry.path.read_text())
    registry['providers'][0]['vision'] = True
    runner.registry.path.write_text(json.dumps(registry))
    runner.set_seat(mid,PLAYER,"MODEL","fake")
    menu = table.state(mid)['menu']
    assert table.act(mid,cid,menu['decision_id'],menu['state_version'],0)['status'] == 'MODEL_DECIDING'
    assert runner.drive(mid,max_steps=1) == 1
    assert len(images) == 1 and images[0].startswith(b'\x89PNG\r\n\x1a\n')
    assert raw_state(runner,mid)['pending_action'] is None
