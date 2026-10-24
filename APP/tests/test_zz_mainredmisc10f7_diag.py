"""Temporary MAINREDMISC10F7 diagnostic (never committed; deleted after the run).

Each test raises one short message because the public CI collector keeps only the
first 500 characters of an error string.
"""
import json
import pathlib
import tempfile

from tests.test_mount_carried_terrain_regressions import (
    FOE,
    RIDER,
    _commit,
    _terrain_on_rider,
)


def _cell(position):
    return [position.x, position.y]


def _molten():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="diag-"))
    combat, table, match_id, engine, mount = _terrain_on_rider(
        tmp, "TAL_MAGMA_LAVA_BURST", "Lava Burst", {"x": 9, "y": 4})
    since = engine.state.event_sequence
    menu = table.state(match_id)["menu"]
    move = next(option for option in menu["moves"] if option["destination"] == {"x": 6, "y": 4})
    _commit(table, match_id, "move", move=move)
    reloaded = combat._load_session(match_id).engine
    return reloaded, since, mount.entity_id


def test_diag_molten_zones():
    engine, _since, _mount = _molten()
    zones = [
        {
            "c": _cell(zone.center),
            "has64": [6, 4] in [_cell(cell) for cell in zone.affected_cells],
            "has54": [5, 4] in [_cell(cell) for cell in zone.affected_cells],
            "terrain": (zone.trigger_profile or {}).get("terrain"),
            "keys": sorted((zone.trigger_profile or {})),
        }
        for zone in engine.state.zones.values()
    ]
    raise AssertionError(json.dumps({"zones": zones})[:480])


def test_diag_molten_events():
    engine, since, mount = _molten()
    rows = [
        [event.event_type, (event.actor_id or "")[-10:], (event.payload or {}).get("moment"),
         (event.target_ids or [None])[0][-10:] if event.target_ids else None,
         (event.payload or {}).get("mode")]
        for event in engine.events
        if event.sequence > since and event.event_type in {
            "MOVEMENT_COMMITTED", "SAVE_ROLLED", "PASSIVE_TRIGGERED", "CONDITION_APPLIED", "DAMAGE_COMMITTED"}
    ]
    raise AssertionError(json.dumps({"mount": mount[-10:], "rows": rows[:20]})[:480])


def test_diag_molten_positions():
    from combat.ext import mounts

    engine, _since, mount = _molten()
    paired = mounts.mount_of(engine, engine.state.actors[RIDER])
    raise AssertionError(json.dumps({
        "rider": _cell(engine.state.actors[RIDER].position),
        "mount": _cell(engine.state.actors[mount].position),
        "pair": paired is engine.state.actors[mount],
    })[:480])


def test_diag_fold_chain(tmp_path):
    from tests import test_c2_review as c2

    prison = "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON"
    target = c2.sheet(["TAL_SPACE_FOLD_STEP"], cl=17, ac=0)
    target["ability_scores_and_statistics"]["hit_points"] = {"maximum": 400}
    combat, table, mid = c2.table_fixture(tmp_path, {
        c2.ME: c2._sheet([prison, "TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"], cl=17, dc=50),
        c2.ATK: target,
    }, {c2.ME: (3, 6), c2.ATK: (4, 6)})
    from combat.ext import verdant_chassis

    for _ in range(6):
        c2.until_turn(table, mid, c2.ME)
        engine = c2.reload(tmp_path, mid)
        if verdant_chassis.marks(engine.state.actors[c2.ATK], engine.state.actors[c2.ME]) >= 3:
            break
        assert c2.send(table, mid, c2.action(table, mid, "Seed-Thorn Strike", c2.ATK))["status"] == "COMMITTED"
        c2.end_turn(table, mid)
    c2.until_turn(table, mid, c2.ME)
    assert c2.send(table, mid, c2.action(table, mid, "Thousand-Root Prison", c2.ATK))["status"] == "COMMITTED"
    c2.end_turn(table, mid)
    c2.until_turn(table, mid, c2.ATK)
    initial = c2.reload(tmp_path, mid)
    cid = next(c.candidate_id for c in initial.legal_candidates()
               if c.display_name == "Fold Step to 8,6")
    chain = []
    answers = []
    for _ in range(4):
        menu = table.state(mid)["menu"]
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
        status = result.get("status")
        if status != "REACTION_REQUIRED":
            chain.append({"status": status})
            break
        reaction = result.get("reaction") or {}
        choice = reaction.get("choice") or {}
        options = choice.get("options") or []
        cells = [option for option in options if option.get("cell")]
        wanted = [option for option in cells
                  if option["cell"].get("x") == 8 and option["cell"].get("y") == 6]
        chain.append({
            "src": (reaction.get("context") or {}).get("reaction_source_id"),
            "opts": len(options),
            "cells": len(cells),
            "wanted": bool(wanted),
            "label": (wanted[0]["label"] if wanted else None),
        })
        pick = wanted[0]["id"] if wanted else (options[0]["id"] if options else None)
        if pick is None:
            break
        answers.append({**reaction["context"], "selection": "USE", "option_ids": [pick]})
    raise AssertionError(json.dumps(chain)[:480])
