"""Temporary MAINREDMISC10F7 diagnostic (never committed; deleted after the run)."""
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


def test_diag_molten_mount():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="diag-"))
    try:
        combat, table, match_id, engine, mount = _terrain_on_rider(
            tmp, "TAL_MAGMA_LAVA_BURST", "Lava Burst", {"x": 9, "y": 4})
    except Exception as exc:  # noqa: BLE001 - the report needs the setup failure text
        raise AssertionError(f"SETUP FAILED {type(exc).__name__}: {exc}")
    mount_id = mount.entity_id
    since = engine.state.event_sequence
    zones = [
        {
            "id": zone.zone_id,
            "center": _cell(zone.center),
            "cells": len(zone.affected_cells),
            "has_6_4": [6, 4] in [_cell(cell) for cell in zone.affected_cells],
            "terrain": (zone.trigger_profile or {}).get("terrain"),
            "triggers": (zone.trigger_profile or {}).get("triggers"),
            "enter_start": (zone.trigger_profile or {}).get("enter_start"),
        }
        for zone in engine.state.zones.values()
    ]
    moves = [option.get("destination") for option in table.state(match_id)["menu"]["moves"]]
    walk_error = None
    try:
        menu = table.state(match_id)["menu"]
        move = next(option for option in menu["moves"] if option["destination"] == {"x": 6, "y": 4})
        _commit(table, match_id, "move", move=move)
    except Exception as exc:  # noqa: BLE001
        walk_error = f"{type(exc).__name__}: {exc}"
    reloaded = combat._load_session(match_id).engine
    events = []
    for event in reloaded.events:
        if event.sequence <= since:
            continue
        if event.event_type not in {"MOVEMENT_COMMITTED", "SAVE_ROLLED", "PASSIVE_TRIGGERED",
                                    "CONDITION_APPLIED", "DAMAGE_COMMITTED", "ZONE_CREATED"}:
            continue
        events.append({
            "seq": event.sequence,
            "type": event.event_type,
            "actor": event.actor_id,
            "source": event.source_definition_id,
            "moment": (event.payload or {}).get("moment"),
            "targets": list(event.target_ids or ()),
            "payload": {key: (event.payload or {}).get(key)
                        for key in ("mode", "condition_id", "hp_damage", "move_through", "path")},
        })
    out = {
        "mount": mount_id,
        "rider_pos": _cell(reloaded.state.actors[RIDER].position),
        "mount_pos": _cell(reloaded.state.actors[mount_id].position),
        "moves": moves,
        "walk_error": walk_error,
        "zones": zones,
        "events": events[:36],
    }
    raise AssertionError(json.dumps(out)[:2600])


def test_diag_fold_step_prompt(tmp_path):
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
    menu = table.state(mid)["menu"]
    result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, [])
    reaction = result.get("reaction") or {}
    choice = reaction.get("choice") or {}
    out = {
        "status": result.get("status"),
        "source": (reaction.get("context") or {}).get("reaction_source_id"),
        "checkpoint": (reaction.get("context") or {}).get("checkpoint"),
        "name": reaction.get("reaction"),
        "title": reaction.get("title"),
        "options": [{key: option.get(key) for key in ("id", "label", "cell")}
                    for option in (choice.get("options") or [])][:8],
        "has_map_pick": bool(choice.get("map_pick")),
    }
    raise AssertionError(json.dumps(out)[:2400])
