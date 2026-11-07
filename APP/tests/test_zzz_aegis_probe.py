"""TEMP diagnostic probe v2 (not committed): which Aegis candidates does the menu offer?"""
from __future__ import annotations

import json

from combat.ext import protection
from tests.r1i_service_support import FOE, OWNER, SECOND
from tests.test_auto_protection_wards import BASE, PR, await_actor, option, play, table_fixture


def menu_rows(table, mid):
    out = []
    for index, group in enumerate(table.state(mid)["menu"]["actions"]):
        if "Aegis" not in group["label"]:
            continue
        for choice in group["options"]:
            out.append(f"[{index}] {group['label']} | {choice['label']} | tgt={choice.get('target_ids')}")
    return out


def test_probe_menu(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}, FOE: {"x": 20, "y": 6}})
    first_menu = menu_rows(table, mid)
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    await_actor(table, mid, OWNER, first=True)
    second_menu = menu_rows(table, mid)
    engine = combat._load_session(mid).engine
    owner_conditions = [f"{i} {r.condition_id} exp={r.expires_on}" for i, r in engine.state.actors[OWNER].conditions.items()]
    assert False, ("\nfirst menu:\n" + "\n".join(first_menu) + "\nsecond menu:\n" + "\n".join(second_menu)
                   + "\nowner conditions:\n" + "\n".join(owner_conditions)
                   + "\nowner concentration:\n" + json.dumps(engine.state.actors[OWNER].concentration.model_dump(mode="json") if engine.state.actors[OWNER].concentration else None))
