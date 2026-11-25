"""Authored effect names survive table commits and a cold reload of the combat log."""
import re

from combat import concentration
from combat.ext import qi_instability, unmaking_channels
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.auto_worker1_support import ALLY, LEFT, RIGHT, act, fight, resolve
from tests.equipment_readiness import ready_table_weapon
from tests.test_feed_summary import ROOT, render, visible

FORBIDDEN = re.compile(r"[a-f0-9]{8,}|\bTyped\b|Copy\d|Unnamed effect|Concentration Held", re.IGNORECASE)
COPY = ".weapon.biao_qiang.copy2"
FIELD = "TAL_QIWEAVING_TURBULENT_FIELD"


def _reload(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()["status"] == "PASS"
    return session


def _assert_log(tmp_path, mid, *removals):
    rows = TabletopService(CombatService(ROOT, tmp_path), tmp_path).events(mid, 0)["events"]
    for detail, view in ((False, "summary"), (True, "All events")):
        lines = visible(render([rows], detail=detail))
        bad = [line for line in lines if FORBIDDEN.search(line)]
        assert not bad, f"{view} exposes internal names:\n" + "\n".join(bad)
        for label in removals:
            assert any(f"{label} was removed" in line for line in lines), (
                f"{view} is missing the named removal {label!r}:\n" + "\n".join(lines)
            )


def test_crack_on_a_thrown_copy_keeps_its_name_through_breakage(tmp_path):
    kit = {"items": [{"item_id": "tianxia.mortal.weapon.biao_qiang", "name": "Marsh Javelin", "quantity": 2}]}

    def seal_throw(bundle):
        if bundle["actor_id"] != LEFT:
            return
        base = next(a for a in bundle["action_catalog"] if a["source_definition_id"].endswith(COPY))
        throw = next(a for a in bundle["action_catalog"] if a["source_definition_id"].endswith(COPY + "#thrown"))
        base["display_name"] = "Marsh Javelin attack"
        throw["display_name"] = "Marsh Javelin throw"
        # A synthetic price on the real throw reaches the break threshold in one action,
        # without depending on an attack roll, extra turns, or a modified running engine.
        throw["parameters"]["typed"]["effects"].append(
            {"type": "unmaking_cost", "options": [{"crack": 3, "weapon": base["source_definition_id"]}]}
        )

    combat, table, mid = fight(tmp_path, left_kit=kit, bundle_edit=seal_throw)
    weapon = next(source for source, action in combat._load_session(mid).engine.action_catalog.items()
                  if action.owner_id == LEFT and source.endswith(COPY))
    ready_table_weapon(table, mid, weapon + "#thrown")
    resolve(lambda answers: act(table, mid, weapon + "#thrown", answers, target_id=RIGHT))

    engine = _reload(tmp_path, mid).engine
    assert unmaking_channels.is_broken(engine.state.actors[LEFT], weapon)
    applied, removed = [
        event for event in engine.events
        if event.event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED"}
        and event.payload.get("condition_id", "").startswith(unmaking_channels.CRACK)
    ]
    assert (applied.event_type, removed.event_type) == ("CONDITION_APPLIED", "CONDITION_REMOVED")
    assert applied.payload["instance_id"] == removed.payload["instance_id"]
    assert applied.transaction_id == removed.transaction_id
    assert any(e.event_type == "ATTACK_ROLLED" and e.source_definition_id == weapon + "#thrown"
               and e.transaction_id == removed.transaction_id for e in engine.events)
    _assert_log(tmp_path, mid, "Marsh Javelin: 3 Crack (it breaks at 3)")


def test_held_turbulent_field_and_its_friend_are_named_when_the_field_ends(tmp_path):
    def shorten_field(bundle):
        for action in bundle["action_catalog"]:
            typed = action["parameters"].get("typed") or {}
            if action["source_definition_id"].endswith("." + FIELD):
                typed["duration"] = {"kind": "rounds", "amount": 1, "concentration": True}
            elif action["display_name"] == "Keep the Beacon":
                typed["duration"] = {"kind": "rounds", "amount": 10, "concentration": True}
                action["concentration"] = True

    combat, table, mid = fight(
        tmp_path, [FIELD, "TAL_QIWEAVING_FRIEND_IN_THE_STORM"], ally=True,
        extra_actions=[("Keep the Beacon", {})], bundle_edit=shorten_field,
    )
    resolve(lambda answers: act(table, mid, FIELD, answers))
    resolve(lambda answers: act(table, mid, "Keep the Beacon", answers))

    engine = combat._load_session(mid).engine
    [held] = concentration.held(engine.state.actors[LEFT])
    held_id, field = held
    field_name = engine.action_catalog[field.source_definition_id].display_name
    [friend] = [row for row in engine.state.actors[ALLY].conditions.values()
                if row.condition_id == qi_instability.FRIEND]
    beacon = engine.state.actors[LEFT].concentration
    assert engine.action_catalog[beacon.source_definition_id].display_name == "Keep the Beacon"

    for _ in range(6):
        resolve(lambda answers: act(table, mid, "end", answers))
        engine = combat._load_session(mid).engine
        if not concentration.held(engine.state.actors[LEFT]):
            break

    engine = _reload(tmp_path, mid).engine
    assert held_id not in engine.state.actors[LEFT].conditions
    assert friend.instance_id not in engine.state.actors[ALLY].conditions
    assert engine.state.actors[LEFT].concentration == beacon
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.source_definition_id == field.source_definition_id
               and e.payload.get("held") and e.payload.get("reason") == "DURATION_ENDED" for e in engine.events)
    _assert_log(tmp_path, mid, f"Concentrating: {field_name}", "Friend in the Storm")
