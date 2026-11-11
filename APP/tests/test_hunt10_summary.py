"""Real terminal summaries retain verification and invalidate on byte changes."""
import time

import pytest

from combat.gate5_service import CombatService
from tests.test_factory_live_match import ROOT, _install


def completed(tmp_path):
    _install(tmp_path, "left")
    service = CombatService(ROOT, tmp_path)
    view = service.create_factory_match(project_ids=["left"], maximum_rounds=1, match_seed="H10-SUMMARY")
    mid = view["match_id"]
    for actor in view["state"]["actors"]:
        if actor["primary_combatant"]:
            service.set_controller_mode(mid, actor_id=actor["entity_id"], controller_mode="MANUAL")
    for _ in range(40):
        context = service.decision(mid)["context"]
        candidate = next(c for c in context["legal_candidates"] if c["kind"] == "END_TURN")
        service.submit_intent(mid, {"intent_id": f"end-{context['state_version']}",
            "decision_id": context["decision_id"], "candidate_id": candidate["candidate_id"],
            "state_version": context["state_version"], "actor_id": context["active_actor_id"]}, [], None)
        if service.get_match(mid)["state"]["terminal_result"] is not None:
            return service, mid
    raise AssertionError("did not finish")


def test_terminal_view_verifies_once_reloads_and_returns_independent_copies(tmp_path, monkeypatch):
    service, mid = completed(tmp_path)
    service = CombatService(ROOT, tmp_path)
    from combat.gate4_persistence import Gate4PersistentSession
    original = Gate4PersistentSession.verify
    calls = []
    def verify(session):
        calls.append(session.match_id)
        return original(session)
    monkeypatch.setattr(Gate4PersistentSession, "verify", verify)
    start = time.perf_counter()
    first = service.get_match(mid)["final_summary"]
    cold = time.perf_counter() - start
    start = time.perf_counter()
    second = service.get_match(mid)["final_summary"]
    warm = time.perf_counter() - start
    assert calls == [mid]
    assert first == second and first["verification"]["status"] == first["replay"]["status"] == "PASS"
    first["actors"][0]["display_name"] = "mutated return value"
    assert service.final_summary(mid) == second
    assert CombatService(ROOT, tmp_path).final_summary(mid) == second
    print(f"terminal view cold={cold:.4f}s warm={warm:.4f}s")


@pytest.mark.parametrize("filename", ["FinalSummary.json", "ControllerJournal.ndjson", "Journal.ndjson", "FactoryIntegration.json"])
def test_terminal_cache_invalidates_content_edits_even_with_restored_timestamp(tmp_path, filename):
    import os
    service, mid = completed(tmp_path)
    summary = service.final_summary(mid)
    path = service._match_dir(mid) / filename
    original = path.read_bytes()
    stat = path.stat()
    changed = original.replace(b'"PASS"', b'"FAIL"', 1) if filename == "FinalSummary.json" else original.replace(b'"', b' ', 1)
    assert changed != original and len(changed) == len(original)
    path.write_bytes(changed)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(Exception):
        service.final_summary(mid)
    path.write_bytes(original)
    assert service.final_summary(mid) == summary


def test_changed_summary_between_verification_and_cache_insert_is_not_trusted(tmp_path, monkeypatch):
    from combat import terminal_summary_cache
    service, mid = completed(tmp_path)
    service = CombatService(ROOT, tmp_path)
    original = terminal_summary_cache.identity
    calls = []
    path = service._match_dir(mid) / "FinalSummary.json"
    def racing_identity(folder):
        calls.append(1)
        if len(calls) == 2:
            path.write_bytes(path.read_bytes().replace(b'"PASS"', b'"FAIL"', 1))
        return original(folder)
    monkeypatch.setattr(terminal_summary_cache, "identity", racing_identity)
    assert service.final_summary(mid)["verification"]["status"] == "PASS"
    with pytest.raises(Exception):
        service.final_summary(mid)
