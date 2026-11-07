"""TEMP diagnostic probe (not committed): why does the owner's Energy Resistance Aegis vanish?"""
from __future__ import annotations

import json

from combat.ext import protection
from tests.r1i_service_support import FOE, OWNER, SECOND
from tests.test_auto_protection_wards import BASE, PR, await_actor, log, option, play, table_fixture


def dump(engine, mark: int) -> str:
    rows = []
    for event in engine.events[mark:]:
        payload = event.payload or {}
        keep = {k: payload[k] for k in ("log", "reason", "condition_id", "instance_id", "modifier_id", "started_sequence")
                if k in payload}
        rows.append(f"{event.sequence} {event.event_type} src={event.source_definition_id} tgt={event.target_ids} {json.dumps(keep, default=str)}")
    owners = []
    for iid, row in engine.state.actors[OWNER].conditions.items():
        owners.append(f"{iid} cid={row.condition_id} src={row.source_definition_id} exp={row.expires_on} seq={row.applied_sequence} data={json.dumps(row.data, default=str)[:200]}")
    conc = engine.state.actors[OWNER].concentration
    return ("\n--- events ---\n" + "\n".join(rows) + "\n--- owner conditions ---\n" + "\n".join(owners)
            + "\n--- owner concentration ---\n" + json.dumps(conc.model_dump(mode="json") if conc else None)
            + "\n--- log ---\n" + log(engine)[-3000:])


def test_probe_owner_second_aegis(tmp_path):
    combat, table, mid = table_fixture(tmp_path, [*BASE, PR + "status", PR + "energy_resistance"], allies=[SECOND],
                                       positions={OWNER: {"x": 4, "y": 6}, SECOND: {"x": 4, "y": 7}, FOE: {"x": 20, "y": 6}})
    play(table, mid, option(table, mid, "Aegis: Armored Aegis", target=SECOND))
    await_actor(table, mid, OWNER, first=True)
    engine = combat._load_session(mid).engine
    mark = len(engine.events)
    play(table, mid, option(table, mid, "Aegis: Energy Resistance"))
    engine = combat._load_session(mid).engine
    with_owner = protection._with(engine.state.actors[OWNER], PR + "energy_resistance")
    assert with_owner, dump(engine, mark)
