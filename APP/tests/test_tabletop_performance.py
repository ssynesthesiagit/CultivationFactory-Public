"""Request caching preserves editable rules and independent table previews."""
import json
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import typed_executor
from combat.tabletop_service import _one_at_a_time
from combat.tabletop_service import TabletopService
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat import zones


def test_nested_table_requests_check_rules_once_and_refresh_next_request(tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"defaults": {"area_targets": "all"}}))
    monkeypatch.setattr(typed_executor, "RULES_PATH", path)
    monkeypatch.setattr(typed_executor, "_RULES_CACHE", {"mtime": None, "data": None})
    stat = Path.stat
    checks = []

    def counted(self, *args, **kwargs):
        if self == path:
            checks.append(self)
        return stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counted)

    class Table:
        @_one_at_a_time
        def nested(self, match_id):
            return typed_executor.rules()

        @_one_at_a_time
        def request(self, match_id):
            before = self.nested(match_id)
            path.write_text(json.dumps({"defaults": {"area_targets": "all_creatures"}}))
            assert all(typed_executor.rules() is before for _ in range(1000))
            assert self.nested(match_id) is before
            return before

    table = Table()
    assert table.request("test")["defaults"]["area_targets"] == "all"
    assert len(checks) == 1
    assert table.nested("test")["defaults"]["area_targets"] == "all_creatures"
    assert len(checks) == 2


def test_rules_snapshot_restores_context_after_error(tmp_path, monkeypatch):
    path = tmp_path / "rules.json"
    path.write_text('{"version": 1}')
    monkeypatch.setattr(typed_executor, "RULES_PATH", path)
    monkeypatch.setattr(typed_executor, "_RULES_CACHE", {"mtime": None, "data": None})
    with pytest.raises(RuntimeError), typed_executor.rules_snapshot():
        assert typed_executor.rules()["version"] == 1
        raise RuntimeError("abort")
    path.write_text('{"version": 222}')
    assert typed_executor.rules()["version"] == 222


def _preview_fixture(area):
    actor = SimpleNamespace(position=Position(x=2, y=4), conditions={})
    grid = SquareGrid({"width_squares": 12, "height_squares": 10, "square_size_ft": 5,
                       "starting_positions": {}, "terrain_regions": []})
    engine = SimpleNamespace(grid=grid, state=SimpleNamespace(actors={"caster": actor}),
                             action_catalog={"cast": SimpleNamespace(parameters={"typed": {"area": area}})})
    menu = {"actor_id": "caster", "actions": [{"source_definition_id": "cast", "options": [
        {"destination": {"x": 5, "y": 4}, "area": {"affected_cells": []}},
        {"destination": {"x": 5, "y": 4}, "area": {"affected_cells": []}},
    ]}]}
    return engine, actor, menu


@pytest.mark.parametrize("shape", ["sphere", "cylinder", "emanation", "cube", "square", "line", "cone", "wall", "spreads"])
def test_area_preview_cache_matches_geometry_and_invalidates(shape, monkeypatch):
    area = {"shape": "sphere" if shape == "spreads" else shape, "size_ft": 15,
            "width_ft": 10, "thick_ft": 10, "spreads": shape == "spreads"}
    engine, actor, template = _preview_fixture(area)
    original = zones.wall_cells_for if shape == "wall" else typed_executor.area_cells
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(zones if shape == "wall" else typed_executor,
                        "wall_cells_for" if shape == "wall" else "area_cells", counted)
    cache = OrderedDict()

    def check():
        menu = deepcopy(template)
        TabletopService._round_areas(menu, engine, cache)
        aim = Position(x=5, y=4)
        cells = original(engine, actor, aim, 15, 10) if shape == "wall" else original(engine, actor.position, aim, area)
        expected = [{"x": cell.x, "y": cell.y} for cell in cells]
        options = menu["actions"][0]["options"]
        assert options[0]["area"]["affected_cells"] == expected
        assert options[1]["area"]["affected_cells"] == expected
        options[0]["area"]["affected_cells"][0]["x"] = -999
        assert options[1]["area"]["affected_cells"] == expected

    check()
    check()
    assert len(calls) == 1  # identical aims and subsequent state reads share geometry
    engine.grid.blocked.add((6, 4))
    check()
    assert len(calls) == 2
    actor.position = Position(x=3, y=3)
    check()
    assert len(calls) == 3
    engine.grid.width = 11
    check()
    assert len(calls) == 4
    area["size_ft"] = 20
    menu = deepcopy(template)
    TabletopService._round_areas(menu, engine, cache)
    assert len(calls) == 5
    if shape == "wall":
        actor.conditions["plan"] = SimpleNamespace(condition_id=zones.WALL_PLAN, data={"points": [[5, 6], [8, 6]]})
        menu = deepcopy(template)
        TabletopService._round_areas(menu, engine, cache)
        expected = original(engine, actor, Position(x=5, y=4), 20, 10)
        assert menu["actions"][0]["options"][0]["area"]["affected_cells"] == [{"x": c.x, "y": c.y} for c in expected]
        assert len(calls) == 6


def test_area_preview_cache_is_bounded(monkeypatch):
    engine, actor, menu = _preview_fixture({"shape": "sphere", "size_ft": 15})
    monkeypatch.setattr(typed_executor, "area_cells", lambda *args: (actor.position,))
    menu["actions"][0]["options"] = [
        {"destination": {"x": x, "y": 4}, "area": {"affected_cells": []}} for x in range(4100)]
    cache = OrderedDict()
    TabletopService._round_areas(menu, engine, cache)
    assert len(cache) == 4096


def test_rules_snapshot_keeps_complete_legal_candidates_identical():
    from tests.test_darkness_and_stealth import _fight

    engine = _fight()
    before = [candidate.model_dump(mode="json") for candidate in engine.legal_candidates()]
    with typed_executor.rules_snapshot():
        after = [candidate.model_dump(mode="json") for candidate in engine.legal_candidates()]
    assert json.dumps(before) == json.dumps(after)


@pytest.mark.parametrize("mode,paused,active,current", [
    ("LIVE", False, True, "owner"), ("HISTORY", False, True, "owner"),
    ("LIVE", True, True, "owner"), ("LIVE", False, False, "owner"),
    ("LIVE", False, True, "other"),
])
@pytest.mark.parametrize("runtime", ["display", "runtime", "absent"])
def test_availability_index_preserves_alias_order_and_disabled_reasons(mode, paused, active, current, runtime):
    from combat.presentation import CombatPresentationProjector as Presenter
    from combat.gate2_runtime_models import CandidateKind

    definition = SimpleNamespace(action_definition_id="display", runtime_source_definition_id=runtime,
                                 reaction_parameters={"checkpoint": "after_hit"})
    candidates = tuple(SimpleNamespace(
        actor_id=actor, source_definition_id=source, candidate_id=f"candidate:{i}",
        target_ids=("target",) if i % 2 else (), destination=Position(x=i, y=1),
        option_ids=("b", "a"), kind=CandidateKind.ACTION,
    ) for i, (actor, source) in enumerate([
        ("owner", "runtime"), ("other", "display"), ("owner", "display"),
        ("owner", "runtime"), ("owner", "unrelated"), ("owner", "display"),
    ]))
    actor = {"entity_id": "owner", "active": active}
    expected = Presenter._availability(definition, actor, mode, paused, current, candidates)
    index = Presenter._candidate_index(candidates)

    class NoScan(tuple):
        def __iter__(self):
            raise AssertionError("indexed availability must not rescan all candidates")

    actual = Presenter._availability(definition, actor, mode, paused, current, NoScan(candidates), index)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    empty = Presenter._availability(definition, actor, mode, paused, current, (), {})
    assert empty.model_dump(mode="json") == Presenter._availability(
        definition, actor, mode, paused, current, ()).model_dump(mode="json")


def test_table_state_availability_matches_full_scan_after_commit_reload(tmp_path, monkeypatch):
    from combat.presentation import CombatPresentationProjector as Presenter
    from tests.test_r6_6_7_combat_presentation_architecture import _create_service_match

    combat, match_id = _create_service_match(tmp_path)
    table = TabletopService(combat, tmp_path / "UserData")
    original = Presenter._availability
    checks = []

    def compare(definition, actor, mode, paused, current, candidates, candidate_index=None):
        assert candidate_index is not None  # the real table must use the fast path
        actual = original(definition, actor, mode, paused, current, candidates, candidate_index)
        expected = original(definition, actor, mode, paused, current, candidates)
        assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
        checks.append(candidate_index)
        return actual

    monkeypatch.setattr(Presenter, "_availability", staticmethod(compare))
    state = table.state(match_id)
    first = checks[0]
    assert all(index is first for index in checks)
    checks.clear()
    result = table.auto_step(match_id, state["last_sequence"])
    assert result["status"] == "COMMITTED"
    assert checks and checks[0] is not first
    checks.clear()
    table.state(match_id)  # persisted engine reloaded, not a retained candidate index
    assert checks
    assert combat._load_session(match_id).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("manual", [False, True], ids=["ai", "manual"])
def test_cached_table_commits_have_identical_events_to_uncached_projection(tmp_path, monkeypatch, manual):
    """The presentation optimizations must preserve choices and saved combat events."""
    import shutil
    from contextlib import nullcontext

    from combat.gate5_service import CombatService
    from combat.presentation import CombatPresentationProjector as Presenter
    from tests.test_r6_6_7_combat_presentation_architecture import ROOT, _create_service_match

    combat, match_id = _create_service_match(tmp_path / "cached")
    if manual:
        for actor in combat.presentation(match_id)["actors"]:
            if actor["primary_combatant"]:
                combat.set_controller_mode(match_id, actor_id=actor["entity_id"], controller_mode="MANUAL")
    cached_user = tmp_path / "cached" / "UserData"
    reference_user = tmp_path / "reference" / "UserData"
    # Duplicate only this small synthetic saved match, preserving its IDs and seed.
    shutil.copytree(cached_user, reference_user)

    def play(service, userdata):
        table = TabletopService(service, userdata)
        state = table.state(match_id)
        states = [state]
        statuses = []
        for step in range(6):
            assert not state["presentation"]["terminal"]
            menu = state["menu"]
            if menu.get("manual"):
                # Exercise a player-selected engine candidate, then finish the turn.
                candidates = [move["candidate_id"] for move in menu["moves"]]
                candidate = candidates[0] if step % 2 == 0 and candidates else menu["end_turn"]
                result = table.act(match_id, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"])
            else:
                result = table.auto_step(match_id, state["last_sequence"])
            assert result["status"] == "COMMITTED"
            statuses.append(result["status"])
            # Each state call reloads the committed engine from disk.
            state = table.state(match_id)
            assert state == result["state"]
            states.append(state)
        session = service._load_session(match_id)
        assert session.mechanical.replay()["status"] == "PASS"
        events = json.dumps([event.model_dump(mode="json") for event in session.engine.events]).encode()
        return states, statuses, events

    actual = play(combat, cached_user)
    round_areas = TabletopService._round_areas
    with monkeypatch.context() as reference:
        # The pre-optimization paths remain available; disable all four caches.
        from combat import gate2_grid
        reference.setattr(gate2_grid, "radius_geometry", gate2_grid.scan_radius)
        reference.setattr(typed_executor, "rules_snapshot", nullcontext)
        reference.setattr(Presenter, "_candidate_index", staticmethod(lambda candidates: None))
        reference.setattr(TabletopService, "_round_areas", staticmethod(
            lambda menu, engine, cache=None: round_areas(menu, engine)))
        expected = play(CombatService(ROOT, reference_user), reference_user)
    assert actual == expected  # Includes exact serialized events, not only replay validity.
