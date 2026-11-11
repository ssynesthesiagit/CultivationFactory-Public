"""Portable table scenarios for Dust Cloud, Air Court and paid melee choices."""
import hashlib
import json

import pytest

from combat.gate5_service import CombatService
from combat import menu_rank
from combat.placement_menu import CHOICE
from pathlib import Path
from tests import r1i_service_support as s
from tests.auto8f1_table_support import AXE_KIT

DUST = "tianxia.subpath.qi.dust_cultivator.feature.dust_cloud"
COURT = "TAL_AIR_COURT_OF_THE_FOUR_WINDS"
NULL = "TAL_VOID_NULLIFYING_STRIKE"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    monkeypatch.setattr(menu_rank, "rank_ids", lambda *a, **k: pytest.fail("unexpected embedding ranking"))


def cold(combat, mid, tmp_path):
    session = combat._load_session(mid)
    fresh = CombatService(s.ROOT, tmp_path)._load_session(mid)
    assert session.engine.state == fresh.engine.state
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return fresh.engine


def expanded(table, mid, source):
    # The same deterministic scenario also runs on installations predating
    # lazy discovery: compare their native eager menu with the expanded menu.
    menu = table.state(mid, **({"lazy": True} if hasattr(table, "expand_action") else {}))["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == source)
    if group.get("lazy"):
        rows = table.expand_action(mid, source, menu["decision_id"], menu["state_version"])["actions"]
        group = next(g for g in rows if g["source_definition_id"] == source)
    assert group["options"]
    return group


def trace(combat, mid, capsys, label):
    """Emit a stable comparison digest; never read repository history or owner data."""
    engine = combat._load_session(mid).engine
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in sorted(value.items())
                    if not any(word in k.lower() for word in
                               ("id", "uuid", "sequence", "version", "transaction", "intent", "decision", "time", "_at", "seed", "counter", "match"))}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        return value
    events = [{"type": e.event_type, "source": e.source_definition_id,
               "actor": e.actor_id, "targets": list(e.target_ids), "payload": clean(e.payload)}
              for e in engine.events]
    actors = {aid: {"hp": a.current_hp, "position": a.position.model_dump(mode="json"),
                    "resources": dict(a.resources),
                    "conditions": sorted(c.condition_id for c in a.conditions.values()),
                    "turn_flags": clean(a.turn_flags), "action": a.action_available,
                    "bonus": a.bonus_action_available, "reaction": a.reaction_available}
              for aid, a in engine.state.actors.items()}
    digest = hashlib.sha256(json.dumps({"events": events, "actors": actors},
                                      sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with capsys.disabled():
        print(f"SCENARIO_SOURCE sha256={hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}", flush=True)
        print(f"BEHAVIOUR {label}: {len(events)} events; sha256={digest}", flush=True)


def test_dust_cloud_then_court_expansion_commit_and_reload(tmp_path, capsys):
    # Unlike a generic Stamina-only fighter, this character actually owns the
    # Dust feature and its printed Qi resource. Do not waive costs or economy.
    combat, table, mid, send, commit = s.fixture(
        tmp_path, [DUST, COURT], owner_cl=17, owner_resource="Qi",
        seed="MENU-DUST-COURT", owner_kit=AXE_KIT)
    engine = cold(combat, mid, tmp_path)
    start = engine.state.actors[s.OWNER].position
    qi = engine.state.actors[s.OWNER].resources["resource:core.qi"]
    assert qi >= 3
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == s.OWNER and a.display_name == "Dust Cloud")
    group = expanded(table, mid, source)
    # The fixture's floor plan decides which centres catch a creature; read a
    # legal aim from the expanded set instead of assuming one map coordinate.
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    aims = [Position.model_validate(o["destination"]) for o in group["options"] if o.get("destination")]
    assert aims, f"{source!r} expanded without a destination"
    aim = aims[0]
    cell = cell_id(aim, include_altitude=True)
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["source_definition_id"] == source)
    assert group.get("placement_picker"), (
        group.get("label"), [o.get("destination") for o in group["options"]][:8])
    reply = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"],
                      menu["state_version"], state["last_sequence"])
    assert reply["status"] == "REACTION_REQUIRED", reply
    question = reply["reaction"]
    assert question["context"]["reaction_source_id"] == CHOICE
    assert cell in {o["id"] for o in question["choice"]["options"]}
    reply = send(group["options"][0]["candidate_id"], [
        {**question["context"], "selection": "USE", "option_ids": [cell]}])
    assert reply["status"] == "COMMITTED", reply
    engine = cold(combat, mid, tmp_path)
    assert engine.state.actors[s.OWNER].position == start
    assert engine.state.actors[s.OWNER].resources["resource:core.qi"] == qi - 1
    zone = next(z for z in engine.state.zones.values()
                if z.active and DUST in z.source_definition_id)
    assert zone.center == aim

    # Dust and Court both cost a Bonus Action: take a new turn before Court.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != s.OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = cold(combat, mid, tmp_path)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == s.OWNER and a.display_name == "Court of the Four Winds")
    group = expanded(table, mid, source)
    commit(group["options"][0]["candidate_id"])
    engine = cold(combat, mid, tmp_path)
    assert engine.state.actors[s.OWNER].resources["resource:core.qi"] == qi - 3
    assert any(z.active and DUST in z.source_definition_id for z in engine.state.zones.values()), (
        [(z.active, z.source_definition_id) for z in engine.state.zones.values()])
    trace(combat, mid, capsys, "dust-court")


def test_nullifying_strike_expansion_keeps_paid_hit_choice(tmp_path, capsys):
    combat, table, mid, send, _ = s.fixture(
        tmp_path, [NULL], owner_cl=17, owner_resource="Qi", foe_ac=1,
        seed="MENU-NULL-CHOICE", owner_kit=AXE_KIT)
    engine = cold(combat, mid, tmp_path)
    qi = engine.state.actors[s.OWNER].resources["resource:core.qi"]
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == s.OWNER and a.display_name == "Fu (Short Axe) attack")
    group = expanded(table, mid, source)
    cid = next(o["candidate_id"] for o in group["options"] if s.FOE in o["target_ids"])
    answers, asked = [], []
    for _ in range(16):
        reply = send(cid, answers)
        if reply["status"] == "COMMITTED":
            break
        assert reply["status"] == "REACTION_REQUIRED", reply
        question = reply["reaction"]
        asked.append(question)
        choice = question.get("choice") or {}
        wanted = next((o["id"] for o in choice.get("options", [])
                       if "Nullifying Strike" in o["label"] and "Speed -10" in o["label"]), None)
        answer = {**question["context"], "selection": "USE" if wanted else "DECLINE"}
        if wanted:
            answer["option_ids"] = [wanted]
        answers.append(answer)
    else:
        pytest.fail("unresolved paid-hit question")
    engine = cold(combat, mid, tmp_path)
    assert any("Nullifying Strike" in p.get("moment", "") for p in asked)
    assert engine.state.actors[s.OWNER].resources["resource:core.qi"] == qi - 2
    assert any(e.event_type == "DAMAGE_ROLLED" and e.payload.get("damage_label") == "Nullifying Strike"
               for e in engine.events)
    trace(combat, mid, capsys, "nullifying")
