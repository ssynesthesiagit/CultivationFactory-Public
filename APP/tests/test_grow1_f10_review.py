"""Persisted removal dependencies and shared ASI validation; synthetic data only."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from combat import table_advance as ta
from combat.tabletop import TabletopError
from stage2 import ability_changes
from stage2.service import RulesCausalStage2Service, _state
from tests.test_grow1_abilities import PID, growth_service, installed_sheet
from tests.test_grow1_respec_review import history, seal, selection


RESET = {
    "reason": "gm_respec", "cl": 8,
    "changes": {"STR": 13, "DEX": 15, "CON": 8, "INT": 14, "WIS": 12, "CHA": 10},
}


def sealed_con_character(root, con=19, cl=8):
    base = installed_sheet()
    base["identity"]["cultivation_level"] = cl
    old = ta.current_scores(base)
    base = ta.recompute_from_abilities(base, old, {**old, "CON": con})
    base["background_and_origin"] = {"background": {"ability_score_change": {"CON": 2}}}
    base["advancement_history"] = history([
        (4, selection("sealed-cl4", "ability_score_change", deltas={"CON": 2})),
    ])
    return seal(root, base)


@pytest.mark.parametrize("later_reset", [False, True], ids=["last-increase", "later-reset"])
def test_remove_reset_rejects_dependent_ordinary_increase_without_mutation(tmp_path, later_reset):
    package = sealed_con_character(tmp_path)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    service = growth_service(tmp_path)
    service.add_ability(PID, RESET)
    service.add_ability(PID, {"reason": "level_increase", "cl": 8, "changes": {"CON": 2}})
    if later_reset:
        # A later legal reset cannot excuse an illegal intermediate allocation.
        service.add_ability(PID, RESET)
    cold = growth_service(tmp_path)
    before = deepcopy(cold.buttons.get(PID)["advancement"])
    before_sheet = cold.combat._factory_owner_sheet(PID)
    assert ta.current_scores(before_sheet)["CON"] == 14
    assert all(not row["gm"] for row in before["abilities"])
    assert all(row["status"]["legal"] for row in cold.advancement(PID)["added"]["abilities"])

    with pytest.raises(TabletopError, match="cap") as error:
        cold.remove_advancement(PID, "ability", "0")
    assert error.value.status_code == 409
    assert "remove" in str(error.value).lower()
    reloaded = growth_service(tmp_path)
    assert reloaded.buttons.get(PID)["advancement"] == before
    assert reloaded.combat._factory_owner_sheet(PID) == before_sheet
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_remove_reset_reprojects_legal_dependent_increase_after_cold_reload(tmp_path):
    package = sealed_con_character(tmp_path, con=17)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    service = growth_service(tmp_path)
    service.add_ability(PID, RESET)
    service.add_ability(PID, {"reason": "level_increase", "cl": 8, "changes": {"CON": 2}})
    growth_service(tmp_path).remove_advancement(PID, "ability", "0")
    cold = growth_service(tmp_path)
    entries = cold.buttons.get(PID)["advancement"]["abilities"]
    assert len(entries) == 1 and entries[0]["gm"] is False
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == 19
    assert cold.advancement(PID)["added"]["abilities"][0]["status"]["legal"]
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_remove_reset_preserves_explicit_gm_grant(tmp_path):
    package = sealed_con_character(tmp_path)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    service = growth_service(tmp_path)
    service.add_ability(PID, RESET)
    # +9 is outside the ordinary +2 budget, so this really is a saved GM grant.
    service.add_ability(PID, {"reason": "level_increase", "cl": 8, "changes": {"CON": 9}}, gm=True)
    growth_service(tmp_path).remove_advancement(PID, "ability", "0")
    cold = growth_service(tmp_path)
    assert cold.buttons.get(PID)["advancement"]["abilities"][0]["gm"] is True
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == 28
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def test_remove_reset_does_not_reject_legal_earlier_level_entry(tmp_path):
    # A CL4 table increase remains valid at CL8; removal is not a new acquisition.
    base = installed_sheet()
    seal(tmp_path, base)
    growth_service(tmp_path).add_ability(
        PID, {"reason": "level_increase", "cl": 4, "changes": {"CON": 2}},
    )
    base["identity"]["cultivation_level"] = 8
    package = seal(tmp_path, base)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    growth_service(tmp_path).add_ability(PID, RESET)
    growth_service(tmp_path).remove_advancement(PID, "ability", "1")
    cold = growth_service(tmp_path)
    assert ta.current_scores(cold.combat._factory_owner_sheet(PID))["CON"] == 16
    rows = cold.buttons.get(PID)["advancement"]["abilities"]
    assert len(rows) == 1 and rows[0]["cl"] == 4 and rows[0]["gm"] is False
    assert cold.advancement(PID)["added"]["abilities"][0]["status"]["legal"]
    assert hashlib.sha256(package.read_bytes()).hexdigest() == digest


def stage2_allocation(monkeypatch, cl, deltas, score):
    """Exercise the real reducer, substituting only catalog and derived-stat IO."""
    service = object.__new__(RulesCausalStage2Service)
    service.projects = SimpleNamespace(_reduce_events=lambda *args, **kwargs: {})
    service.registry = SimpleNamespace(validate=lambda event: None)
    rule = {"allowed_cls": [4, 8, 12, 16, 19], "budget": 2, "allowed_deltas": [1, 2], "cap": 20}
    record = {
        "record_id": "synthetic.asi", "display_name": "Ability Score Improvement",
        "record_hash": "r" * 64, "content_type": "path_feature",
        "source": {"source_id": "synthetic", "source_hash": "s" * 64, "anchor": "ASI"},
        "content_binding": {"pack_id": "synthetic", "pack_version": "1", "pack_hash": "p" * 64},
        "compatibility": {"factory": {"stage2_authority": {"ability_change": rule}}},
    }
    monkeypatch.setattr(service, "_record", lambda *args, **kwargs: (record, []))
    monkeypatch.setattr(service, "_stage2_authority", lambda *args: [])
    monkeypatch.setattr(service, "_legality_relation_blockers", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(service, "_cardinality_blockers", lambda *args: [])
    candidates = []

    def recalculate(conn, project_id, candidate, prior_scores, **kwargs):
        candidates.append(deepcopy(candidate))
        return {}, {}, [], {}

    monkeypatch.setattr(service, "_recalculate_after_ability", recalculate)
    state = _state("synthetic")
    state.update(current_cl=cl, ability_scores=dict.fromkeys(ta.ABILITIES, 10))
    state["ability_scores"]["CON"] = score
    original = deepcopy(state)
    result = service._choice_event(
        conn=None, row={
            "project_id": "synthetic", "proposal_id": "synthetic.asi",
            "expected_project_revision": 0, "idempotency_key": "synthetic.asi",
            "created_at": "2026-01-01T00:00:00Z",
        },
        project={"content_lock": {"catalog_build_id": "synthetic"}}, state=state,
        choice={"kind": "ability_score_change", "record_id": record["record_id"],
                "acquisition_channel": "level", "effective_cl": cl, "parameters": {"deltas": deltas}},
        index=0, sequence=1, previous_hash="0" * 64, generic_prefix=[],
    )
    assert state == original
    return result, candidates, state, rule


@pytest.mark.parametrize("deltas", [{"CON": 2}, {"CON": 1, "WIS": 1}])
def test_shared_validation_keeps_both_ordinary_asi_allocations_legal(monkeypatch, deltas):
    (event, returned, blockers), candidates, state, rule = stage2_allocation(
        monkeypatch, 4, deltas, 14,
    )
    assert blockers == [] and event is not None
    assert returned["ability_scores"]["CON"] == 14 + deltas["CON"]
    assert candidates[0]["ability_scores"] == returned["ability_scores"]
    assert ta.ability_status(
        {"reason": "level_increase", "cl": 4, "changes": deltas}, installed_sheet(),
    )["legal"]


def test_stage2_and_grow_delegate_to_same_pure_asi_validation(monkeypatch):
    real_validate = ability_changes.validate_ability_change
    calls = []

    def validate(*args, **kwargs):
        calls.append((args, kwargs))
        return [*real_validate(*args, **kwargs),
                {"code": "SYNTHETIC_SHARED_VALIDATION", "message": "Shared allocation rule checked."}]

    monkeypatch.setattr(ability_changes, "validate_ability_change", validate)
    (event, returned, blockers), candidates, state, rule = stage2_allocation(
        monkeypatch, 4, {"CON": 2}, 14,
    )
    assert event is None and returned is state
    assert [row["code"] for row in blockers] == ["SYNTHETIC_SHARED_VALIDATION"]
    assert candidates[0]["ability_scores"]["CON"] == 16
    base = installed_sheet()
    status = ta.ability_status({"reason": "level_increase", "cl": 4, "changes": {"CON": 2}}, base)
    assert status["legal"] is False
    assert "Shared allocation rule checked." in status["reasons"]
    assert len(calls) == 2


@pytest.mark.parametrize("cl,deltas,score,candidate", [
    (3, {"CON": 2}, 14, 16),
    (4, {"CON": 1}, 14, 15),
    (4, {"CON": 2}, 19, 21),
    (4, {"CON": True, "WIS": 1}, 14, None),
    (4, {"UNKNOWN": 2}, 14, None),
])
def test_shared_validation_preserves_stage2_blocked_candidate_semantics(
    monkeypatch, cl, deltas, score, candidate,
):
    (event, returned, blockers), candidates, state, rule = stage2_allocation(
        monkeypatch, cl, deltas, score,
    )
    expected = ability_changes.validate_ability_change(
        state["ability_scores"], deltas, cl, rule,
    )
    assert event is None and returned is state
    assert [row["code"] for row in blockers] == [row["code"] for row in expected]
    if candidate is None:
        assert candidates == []
    else:
        assert len(candidates) == 1
        assert candidates[0]["ability_scores"]["CON"] == candidate
        assert candidates[0]["ability_modifiers"]["CON"] == ta.ability_modifier(candidate)
