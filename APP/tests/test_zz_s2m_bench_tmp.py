"""TEMPORARY SPEEDREUSE2M timing bench. Never committed; deleted before the lane finishes.

Builds one synthetic 10-creature fight (5 v 5 Factory fighters, two of them summoners whose creature
waits off the map until called; never owner data) and times TabletopService.state() for a browser poll:

  uncached  CF_TABLE_STATE_REUSE=0 -- every poll rebuilds, which is what main does
  cached    reuse on               -- first poll builds, later polls reuse the unchanged build

Both are measured in one process on the same fight, after the same warm-up, so the difference is the
reuse layer alone. It also asserts that a reused answer is byte-identical to a fresh build at 10-creature
scale (the unit test proves this for a two-actor fight).
"""
import json
import os
import time
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
PREFIX = "actor:factory."


def _size(value):
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


@pytest.fixture(scope="module")
def bench_fight(tmp_path_factory):
    data = tmp_path_factory.mktemp("s2m-bench")
    cwd = os.getcwd()
    sys_path = list(os.sys.path)
    try:
        os.sys.path.insert(0, str(APP))
        os.chdir(APP)
        from combat.gate5_service import CombatService
        from tests.test_fight_size import _geometry_copies
        from tests.test_factory_live_match import _install, ROOT
        from tests.test_summons import _sheet

        _geometry_copies(data)
        left, right = [f"west-{i}" for i in range(5)], [f"east-{i}" for i in range(5)]
        summoners = {"west-0": "TAL_DEATH_GHOST_LANTERN", "east-0": "tianxia.talent.ink.painted_beast"}
        import zipfile

        for pid in left + right:
            if pid in summoners:
                sheet = _sheet([summoners[pid]])
                sheet["identity"]["display_name"] = pid
                folder = data / "portable_characters" / pid
                folder.mkdir(parents=True)
                with zipfile.ZipFile(folder / "current.zip", "w") as archive:
                    archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
            else:
                _install(data, pid)
        combat = CombatService(ROOT, data)
        view = combat.create_factory_match(
            project_ids=left, opponent_actor_ids=[PREFIX + pid for pid in right],
            control_modes={PREFIX + pid: "MANUAL" for pid in left + right},
            arena_id="battlefield:map.fixture-courtyard", match_seed="SPEEDREUSE2M-SYNTHETIC-10")
        engine = combat._load_session(view["match_id"]).engine
        actors = list(engine.state.actors.values())
        info = {"match_id": view["match_id"], "viewer": engine.state.current_actor_id,
                "actors": len(actors), "in_play": sum(1 for a in actors if a.active),
                "waiting": sorted(a.entity_id for a in actors if a.summon and a.summon.get("status") == "waiting")}
        yield data, info
    finally:
        os.chdir(cwd)
        os.sys.path[:] = sys_path


def test_state_timing_bench(bench_fight):
    data, info = bench_fight
    from combat.tabletop_service import TabletopService

    table = TabletopService.from_root(data) if hasattr(TabletopService, "from_root") else None
    if table is None:
        from combat.gate5_service import CombatService
        from tests.test_factory_live_match import ROOT

        table = TabletopService(CombatService(ROOT, data), data)

    mid = info["match_id"]
    browser = dict(fog=True, fog_view="own", fog_actor_ids=(info["viewer"],), compact_moves=True)

    # One warm-up poll so the shared services (menus, geometry, rules) are loaded for both modes alike.
    os.environ["CF_TABLE_STATE_REUSE"] = "0"
    table.state(mid, **browser)

    def polls(count):
        out = []
        for _ in range(count):
            started = time.perf_counter()
            value = table.state(mid, **browser)
            out.append(round(time.perf_counter() - started, 3))
        return out, value

    os.environ["CF_TABLE_STATE_REUSE"] = "0"
    uncached, fresh = polls(5)
    reuse = table._state_reuse
    assert reuse.misses == 0 and reuse.hits == 0, "reuse off must neither keep nor answer from a kept state"

    os.environ["CF_TABLE_STATE_REUSE"] = "1"
    cached, reused = polls(5)
    assert reuse.misses == 1, f"one build and four reuses expected, got {reuse.misses} builds"
    assert reuse.hits == 4, f"four reuses expected, got {reuse.hits}"

    fresh_bytes = json.dumps(fresh, separators=(",", ":"), ensure_ascii=False)
    reused_bytes = json.dumps(reused, separators=(",", ":"), ensure_ascii=False)
    assert reused_bytes == fresh_bytes, "a reused answer must equal an uncached read byte-for-byte"
    assert isinstance(reused["presentation"]["actors"], list)
    del os.environ["CF_TABLE_STATE_REUSE"]

    result = {"fight": info, "uncached_polls_s": uncached, "cached_polls_s": cached,
              "cached_first_build_s": cached[0],
              "uncached_median_s": sorted(uncached)[len(uncached) // 2],
              "cached_median_s": sorted(cached)[len(cached) // 2],
              "state_bytes": _size(fresh), "menu_actions": len((fresh.get("menu") or {}).get("actions") or []),
              "byte_identical": True}
    result["speedup_x"] = round(result["uncached_median_s"] / max(result["cached_median_s"], 1e-6), 2)
    print("\n===== SPEEDREUSE2M BENCH =====\n" + json.dumps(result, indent=1))
    Path("/var/tmp/auto-audit/fix/SPEEDREUSE2M-evidence").mkdir(parents=True, exist_ok=True)
    Path("/var/tmp/auto-audit/fix/SPEEDREUSE2M-evidence/bench_run.json").write_text(json.dumps(result, indent=1))