"""AI teleport menus apply candidate_allowed once per landing, to the offered candidate (AISTEPONCE1).

Gate4's AI query used teleport_steps.destinations(), which ran every candidate_allowed subscriber on a synthetic
per-cell candidate, and then Gate4's own filter ran them all again on each real offered candidate. Gate4 now asks
teleport_steps.landings() (landing rules only, Void Step's teleport_landing_allowed seam included) and its single
filter decides. The offered list must not change: the legacy path (destinations()) must give exactly the same rows.
"""
import pytest

from combat import ext
from combat.candidate_knowledge import query
from combat.ext import teleport_steps
from combat.ext import void_touched_cultivator as void
from tests.test_a2r23_athletics_map import FIGHTER, FLASH_STEP, FOE, engine_of, table_fight
from tests.test_void_step_known_destination_regression import OWNER, _table
from tests.void_family_support import acquired  # noqa: F401  (module fixture)
from tests.worker2_support import reload


def _rows(engine):
    with query(engine):
        return sorted((c.candidate_id, str(c.kind), c.source_definition_id, c.destination, tuple(c.option_ids))
                      for c in engine.legal_candidates())


def _legacy_rows(fresh, monkeypatch):
    # The pre-AISTEPONCE1 query: per-cell candidate hooks inside the landing search.
    with monkeypatch.context() as patch:
        patch.setattr(teleport_steps, "landings", teleport_steps.destinations)
        return _rows(fresh())


def _hook_calls(engine, monkeypatch, is_teleport):
    calls = []
    real = ext.any_false

    def counting(point, *args, **kwargs):
        if point == "candidate_allowed" and is_teleport(args[2]):
            calls.append(args[2].destination)
        return real(point, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ext, "any_false", counting)
        rows = _rows(engine)
    return rows, calls


def _check(fresh, monkeypatch, is_teleport):
    rows, calls = _hook_calls(fresh(), monkeypatch, is_teleport)
    assert rows == _legacy_rows(fresh, monkeypatch), "the AI's offered list must not change"
    assert calls, "fixture must offer teleport landings"
    assert len(calls) == len(set(calls)), "candidate_allowed must run once per landing, not twice"


def test_flash_step_ai_menu_hooks_each_landing_once(tmp_path, monkeypatch):
    combat, _, mid = table_fight(tmp_path, [FLASH_STEP], where={FIGHTER: {"x": 3, "y": 4}, FOE: {"x": 8, "y": 4}})
    _check(lambda: engine_of(combat, mid), monkeypatch,
           lambda c: "flash_step" in c.source_definition_id.lower() and c.destination is not None)


@pytest.mark.parametrize("surveyed", [False, True])
def test_void_step_ai_menu_keeps_known_landings_and_hooks_once(acquired, tmp_path, monkeypatch, surveyed):  # noqa: F811
    combat, _, mid = _table(tmp_path, acquired, surveyed=surveyed)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")

    def fresh():
        return reload(tmp_path, mid)

    def is_void(c):
        engine = fresh_engine[0]
        return (c.destination is not None and
                void.family_source(engine.action_catalog.get(c.source_definition_id)) == void.VOID_STEP)

    fresh_engine = [fresh()]
    _check(fresh, monkeypatch, is_void)
