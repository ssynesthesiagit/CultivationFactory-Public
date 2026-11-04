"""Atomic native match publication and between-fight preparation regressions.

Only isolated portable sheets, native persistence and cold reloads are used.
No live server, model or browser is involved.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Event, get_ident
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.preparation import PreparationStore
from tests.h1_support import ROOT
from tests.test_mgr_t14_fitted_armor import ACTOR, PROJECT, LAMELLAR, sheet

SECOND = "00000000-0000-4000-8000-000000000015"
POOL = "resource:equipment.helmet_discipline"
# The native registry discovers these inputs dynamically; retain them in CI.
FIXTURE_INPUTS = (
    "combat/rules/feature_blocks.d/auto68_equipment.json",
    "combat/rules/feature_blocks.d/riders_lane9.json",
    "combat/rules/feature_blocks.d/auto_lane4.json",
)


def installed_service(root, projects):
    doc = sheet(["helmet_discipline"])
    doc["equipment"][0]["head_protection"] = {"armor_key": LAMELLAR, "kind": "helmet"}
    for project in projects:
        path = root / "portable_characters" / project / "current.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    service = CombatService(ROOT, root)
    # Warm directory-discovered providers before starting concurrent requests.
    service.character_preparation_options(PROJECT)
    return service


def create(service, projects, seed):
    return service.create_factory_match(project_ids=projects, match_seed=seed,
                                        maximum_rounds=1)


def pause_publication(monkeypatch, service):
    entered, release = Event(), Event()
    original = service.persistence.create_match

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(15), "test did not release native publication"
        return original(*args, **kwargs)

    monkeypatch.setattr(service.persistence, "create_match", paused)
    return entered, release


def watch_competing_lock(monkeypatch):
    attempted = Event()
    competing_thread = []
    original = PreparationStore.lock

    @contextmanager
    def observed(store, actor_id):
        if competing_thread and get_ident() == competing_thread[0]:
            attempted.set()
        with original(store, actor_id):
            yield

    monkeypatch.setattr(PreparationStore, "lock", observed)
    return attempted, competing_thread


@pytest.mark.parametrize("projects", [[PROJECT], [SECOND, PROJECT]])
def test_overlapping_native_creates_publish_only_one_shared_allowance(monkeypatch, tmp_path, projects):
    first = installed_service(tmp_path, projects)
    second = CombatService(ROOT, tmp_path)
    entered, release = pause_publication(monkeypatch, first)
    attempted, competing_thread = watch_competing_lock(monkeypatch)
    second_publish = Event()
    original = second.persistence.create_match

    def record_publish(*args, **kwargs):
        second_publish.set()
        return original(*args, **kwargs)

    monkeypatch.setattr(second.persistence, "create_match", record_publish)

    def compete():
        competing_thread.append(get_ident())
        return create(second, list(reversed(projects)), "F6-SECOND")

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(create, first, projects, "F6-FIRST")
        try:
            assert entered.wait(15)
            loser = executor.submit(compete)
            assert attempted.wait(15), "competing request did not reach actor locking"
            assert not second_publish.wait(0.3), "two requests sealed the same rest allowance"
        finally:
            release.set()
        match = winner.result(timeout=15)
        with pytest.raises(ValueError, match="active fight"):
            loser.result(timeout=15)

    cold = CombatService(ROOT, tmp_path)
    assert [m["match_id"] for m in cold.persistence.list_matches()] == [match["match_id"]]
    session = cold._load_session(match["match_id"])
    for project in projects:
        actor_id = "actor:factory." + project
        assert session.engine.state.actors[actor_id].resources[POOL] == 1
        bundle = next(b for b in session.engine.typed_bundle_documents if b["actor_id"] == actor_id)
        assert bundle["armor_subject"]["rest_generation"] == 0
        assert bundle["armor_subject"]["head_protection_key"] == LAMELLAR
    assert session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("operation,parameters", [
    ("rest.start", {"kind": "long_rest", "armor_mode": "removed"}),
    ("time.advance", {"seconds": 28800, "observation": "sleep"}),
])
def test_preparation_cannot_enter_between_projection_and_native_publication(monkeypatch, tmp_path, operation, parameters):
    first = installed_service(tmp_path, [PROJECT])
    second = CombatService(ROOT, tmp_path)
    entered, release = pause_publication(monkeypatch, first)
    attempted, competing_thread = watch_competing_lock(monkeypatch)
    completed = Event()
    store = PreparationStore(tmp_path)

    def compete(revision):
        competing_thread.append(get_ident())
        try:
            return second.character_preparation(PROJECT, operation, parameters=parameters,
                                                expected_revision=revision)
        finally:
            completed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        winner = executor.submit(create, first, [PROJECT], "F6-PREPARATION")
        try:
            assert entered.wait(15)
            before = store.read(ACTOR)
            preparation = executor.submit(compete, before["revision"])
            assert attempted.wait(15)
            assert not completed.wait(0.3), "preparation entered before fight publication"
        finally:
            release.set()
        match = winner.result(timeout=15)
        with pytest.raises(ValueError, match="active fight"):
            preparation.result(timeout=15)
    assert store.read(ACTOR) == before
    cold = CombatService(ROOT, tmp_path)._load_session(match["match_id"])
    assert cold.engine.state.actors[ACTOR].resources[POOL] == 1
    assert cold.mechanical.replay()["status"] == "PASS"


def test_native_roster_locks_have_stable_actor_order(monkeypatch, tmp_path):
    service = installed_service(tmp_path, [PROJECT, SECOND])
    original = PreparationStore.lock
    attempts = []

    @contextmanager
    def observed(store, actor_id):
        attempts.append(actor_id)
        with original(store, actor_id):
            yield

    monkeypatch.setattr(PreparationStore, "lock", observed)
    create(service, [SECOND, PROJECT], "F6-LOCK-ORDER")
    assert len(attempts) >= 2
    assert attempts == sorted(set(attempts)), "roster locks must be unique and globally ordered"
