"""Medicinal Wax composition and settlement through committed cold sessions.

Free fixture actions establish real Halo state and deterministic damage; the
production Halo and Wax subscribers are used without replacing either.
"""
import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_a2_wax_medicine import MEDICINE, PREFIX, prepare
from tests.test_r5i_integration import PLAYER, OTHER, act, candidate, check_reload, fixture, seed, turn


def wax_halo_fixture(tmp_path, *, medicine=True, legacy=False):
    def configure(bundle, other):
        other["actor_template"]["creature_types"] = ["Undead"]
        seed(bundle, "Fixture Merciful Halo", [{"type": "radiance_state", "kind": "merciful_halo",
             "label": "Halo of the Merciful Sovereign", "applies_to": "self"}], target="SELF")
        halo = bundle["action_catalog"][-1]["parameters"]["typed"]
        halo["numbers"]["pb"] = 6
        halo["duration"] = {"kind": "until_removed"}
        for amount in (3, 8, 20):
            seed(other, f"Fixture damage {amount}", [{"type": "damage", "flat": amount,
                 "damage_types": ["force"]}])
        if legacy:
            for action in bundle["action_catalog"]:
                typed = action["parameters"].get("typed", {})
                if typed.get("source") == "TAL_WAX_WAXEN_SHELL":
                    typed["effects"] = [e for e in typed["effects"] if e.get("type") != "wax_medicine"]

    combat, table, mid = fixture(tmp_path, ["TAL_WAX_WAXEN_SHELL", *([MEDICINE] if medicine else [])],
                                 configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Fixture Merciful Halo"))["status"] == "COMMITTED"
    if medicine and not legacy:
        prepare(combat, table, mid, "Waxen Shell", PLAYER, "numbing")
    else:
        assert act(table, mid, candidate(combat, mid, "Waxen Shell"))["status"] == "COMMITTED"
    turn(table, mid, OTHER)
    check_reload(combat, mid, tmp_path)
    return combat, mid


def damage(tmp_path, mid, amount):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    c = next(c for c in session.engine.legal_candidates()
             if c.display_name == f"Fixture damage {amount}" and PLAYER in c.target_ids)
    session.mechanical.execute_intent(ActionIntent(intent_id=f"waxfin:{c.state_version}",
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"
    assert cold.engine.state.model_dump(mode="json") == session.engine.state.model_dump(mode="json")
    packet = next(e for e in reversed(cold.engine.events) if e.event_type == "DAMAGE_COMMITTED")
    return cold.engine, packet.payload["reduced_to"]


def test_numbing_adds_to_halo_and_is_consumed_exactly_once(tmp_path):
    combat, mid = wax_halo_fixture(tmp_path)
    [wax] = [c for c in combat._load_session(mid).engine.state.actors[PLAYER].conditions.values()
             if c.condition_id == PREFIX + "numbing"]
    engine, amount = damage(tmp_path, mid, 20)
    assert amount == 10
    assert wax.instance_id not in engine.state.actors[PLAYER].conditions
    assert len([e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("instance_id") == wax.instance_id]) == 1
    engine, amount = damage(tmp_path, mid, 20)
    assert amount == 14


def test_numbing_survives_packet_already_prevented_by_halo(tmp_path):
    combat, mid = wax_halo_fixture(tmp_path)
    [wax] = [c for c in combat._load_session(mid).engine.state.actors[PLAYER].conditions.values()
             if c.condition_id == PREFIX + "numbing"]
    engine, amount = damage(tmp_path, mid, 3)
    assert amount == 0
    assert wax.instance_id in engine.state.actors[PLAYER].conditions
    engine, amount = damage(tmp_path, mid, 20)
    assert amount == 10
    assert wax.instance_id not in engine.state.actors[PLAYER].conditions


def test_numbing_consumes_when_only_part_of_its_reduction_is_needed(tmp_path):
    combat, mid = wax_halo_fixture(tmp_path)
    [wax] = [c for c in combat._load_session(mid).engine.state.actors[PLAYER].conditions.values()
             if c.condition_id == PREFIX + "numbing"]
    engine, amount = damage(tmp_path, mid, 8)
    assert amount == 0
    assert wax.instance_id not in engine.state.actors[PLAYER].conditions
    assert len([e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("instance_id") == wax.instance_id]) == 1
    engine, amount = damage(tmp_path, mid, 20)
    assert amount == 14


@pytest.mark.parametrize("medicine,legacy", [(False, False), (True, True)])
def test_unowned_and_legacy_wax_leave_halo_damage_unchanged(tmp_path, medicine, legacy):
    combat, mid = wax_halo_fixture(tmp_path, medicine=medicine, legacy=legacy)
    engine, amount = damage(tmp_path, mid, 20)
    assert amount == 14
    assert not any(c.condition_id.startswith(PREFIX) for c in engine.state.actors[PLAYER].conditions.values())
