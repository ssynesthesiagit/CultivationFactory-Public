"""Cooling Wax on native condition repeats, through table/session commits and replay."""
import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests.test_a2_wax_medicine import MEDICINE, PREFIX, prepare
from tests.test_r5i_integration import PLAYER, act, candidate, check_reload, fixture, seed, turn
from tests.h1_support import ROOT


def repeat_fixture(tmp_path, hazard, *, medicine=True, legacy=False, dc=50, second_hazard=None):
    def configure(bundle, other):
        seed(bundle, "Repeat hazard", [{"type": "condition", "condition": hazard,
             "applies_to": "self", "repeat_save": {"ability": "CON", "when": "end"}}], target="SELF")
        bundle["action_catalog"][-1]["parameters"]["typed"]["duration"] = {"kind": "rounds", "amount": 10}
        bundle["action_catalog"][-1]["parameters"]["typed"]["numbers"]["save_dc"] = dc
        if second_hazard:
            bundle["action_catalog"][-1]["parameters"]["typed"]["effects"].append(
                {"type": "condition", "condition": second_hazard, "applies_to": "self",
                 "repeat_save": {"ability": "CON", "when": "end"}})
        if legacy:
            # A retained pre-Medicinal-Wax catalog has no reviewed preparation attachment.
            for action in bundle["action_catalog"]:
                typed = action["parameters"].get("typed", {})
                if typed.get("source") == "TAL_WAX_WAXEN_SHELL":
                    typed["effects"] = [e for e in typed["effects"] if e.get("type") != "wax_medicine"]

    talents = ["TAL_WAX_WAXEN_SHELL", *([MEDICINE] if medicine else [])]
    combat, table, mid = fixture(tmp_path, talents, configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Repeat hazard"))["status"] == "COMMITTED"
    if medicine and not legacy:
        prepare(combat, table, mid, "Waxen Shell", PLAYER, "cooling")
    else:
        assert act(table, mid, candidate(combat, mid, "Waxen Shell"))["status"] == "COMMITTED"
    check_reload(combat, mid, tmp_path)
    return combat, table, mid


def end_session(tmp_path, mid, *, attempt=0):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN")
    session.mechanical.execute_intent(ActionIntent(intent_id=f"wax-repeat:{c.state_version}:{attempt}",
        decision_id=c.decision_id, candidate_id=c.candidate_id, state_version=c.state_version,
        actor_id=c.actor_id, target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.verify()["status"] == "PASS"
    assert cold.mechanical.replay()["status"] == "PASS"
    return cold.engine


@pytest.mark.parametrize("hazard,dc", [("poisoned", 50), ("disease", 50), ("diseased", 1)])
def test_cooling_native_repeat_has_advantage_consumes_once_and_replays(tmp_path, hazard, dc):
    combat, table, mid = repeat_fixture(tmp_path, hazard, dc=dc)
    before = combat._load_session(mid).engine
    [wax] = [c for c in before.state.actors[PLAYER].conditions.values() if c.condition_id == PREFIX + "cooling"]
    start = before.state.event_sequence
    engine = end_session(tmp_path, mid)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "ADVANTAGE"
    assert wax.instance_id not in engine.state.actors[PLAYER].conditions
    assert len([e for e in engine.events if e.event_type == "CONDITION_REMOVED"
                and e.payload.get("instance_id") == wax.instance_id]) == 1
    assert saves[0].payload["success"] == (dc == 1)
    # Repeat the lasting failed hold, or reapply the successfully removed hold.
    turn(table, mid, PLAYER)
    if dc == 1:
        assert act(table, mid, candidate(combat, mid, "Repeat hazard"))["status"] == "COMMITTED"
    start = combat._load_session(mid).engine.state.event_sequence
    engine = end_session(tmp_path, mid)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "NORMAL"


def test_only_first_of_two_qualifying_native_repeats_uses_cooling(tmp_path):
    combat, table, mid = repeat_fixture(tmp_path, "poisoned", second_hazard="disease")
    start = combat._load_session(mid).engine.state.event_sequence
    engine = end_session(tmp_path, mid)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert [e.payload["mode"] for e in saves] == ["ADVANTAGE", "NORMAL"]


def test_native_cooling_cancels_disadvantage_and_still_consumes(tmp_path, monkeypatch):
    from combat import ext

    combat, table, mid = repeat_fixture(tmp_path, "poisoned")
    monkeypatch.setitem(ext._HOOKS, "save_mode", [*ext._HOOKS.get("save_mode", []),
        lambda engine, subject, ability, dc, source, context: "DISADVANTAGE"])
    start = combat._load_session(mid).engine.state.event_sequence
    engine = end_session(tmp_path, mid)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "NORMAL"
    assert not any(c.condition_id == PREFIX + "cooling" for c in engine.state.actors[PLAYER].conditions.values())


@pytest.mark.parametrize("medicine,legacy,hazard", [(True, False, "frightened"),
                                                    (False, False, "poisoned"), (True, True, "poisoned")])
def test_unrelated_unowned_and_legacy_native_repeats_are_inert(tmp_path, medicine, legacy, hazard):
    combat, table, mid = repeat_fixture(tmp_path, hazard, medicine=medicine, legacy=legacy)
    start = combat._load_session(mid).engine.state.event_sequence
    engine = end_session(tmp_path, mid)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "NORMAL"
    assert bool([c for c in engine.state.actors[PLAYER].conditions.values()
                 if c.condition_id == PREFIX + "cooling"]) == (medicine and not legacy)


@pytest.mark.parametrize("pause", [False, True])
def test_native_repeat_error_or_player_pause_preserves_wax_and_unwinds_scope(tmp_path, monkeypatch, pause):
    from tests.test_lock_choices import install
    from combat import ext

    combat, table, mid = repeat_fixture(tmp_path, "poisoned")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    hooks = list(ext._HOOKS.get("repeat_save_failed", []))
    def interrupted(engine, resolution):
        if pause:
            raise ext.ControllerPause("fixture player decision")
        return {"result": "MAYBE"}

    install(monkeypatch, "repeat_save_failed", interrupted)
    with pytest.raises(ext.ControllerPause if pause else ValueError):
        if pause:
            # Player pauses belong to the service's throwaway table preview,
            # never to an already prepared persistent transaction.
            act(table, mid, table.state(mid)["menu"]["end_turn"])
        else:
            end_session(tmp_path, mid)
    from combat.ext.wax_medicine import _COOLING_REPEAT
    assert _COOLING_REPEAT.get() is None
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    monkeypatch.setitem(ext._HOOKS, "repeat_save_failed", hooks)
    # Retry the same persisted turn: one Advantage roll, one exact removal.
    start = before["event_sequence"]
    engine = end_session(tmp_path, mid, attempt=1)
    saves = [e for e in engine.events if e.sequence > start and e.event_type == "SAVE_ROLLED"
             and e.source_definition_id == "test:Repeat hazard"]
    assert len(saves) == 1 and saves[0].payload["mode"] == "ADVANTAGE"
    assert not any(c.condition_id == PREFIX + "cooling" for c in engine.state.actors[PLAYER].conditions.values())
