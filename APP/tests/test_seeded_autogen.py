"""Seeded autogeneration and Quick Build (owner 2026-09-24): a seed alone builds a character, no AI."""

import json
import time

from app.core import FoundryError
from character_creation.creative_controller import seeded_picker
from character_creation.creative_controller.linear_menus import StepMenu, StepOption
from character_creation.creative_controller.linear_prompt import parse_step_response, validate_identity_owner_lock
from character_creation.quick_build import QuickBuildQueue


def _menu(step_id: str = "path_choice:1", count: int = 6) -> StepMenu:
    options = tuple(StepOption(f"dcc.opt.{index:024x}", (f"path.{index}",), f"Path {index}", "pick") for index in range(count))
    return StepMenu(step_id=step_id, step_kind="path_choice", ordinal=1, title="Path", min_choices=1, max_choices=1,
                    options=options, page_id=f"{step_id}:page:1")


def test_the_same_seed_makes_the_same_choices_and_different_seeds_differ():
    assert seeded_picker.identity("QB-1") == seeded_picker.identity("QB-1")
    assert len({seeded_picker.identity(f"QB-{n}")["name"] for n in range(20)}) > 10
    menu = _menu()
    assert seeded_picker.choose_option("QB-1", menu) == seeded_picker.choose_option("QB-1", menu)
    picks = {seeded_picker.choose_option(f"QB-{n}", menu) for n in range(60)}
    assert len(picks) > 3  # varied, not always the top option


def test_seeded_answers_pass_the_same_validation_as_a_model_answer():
    receipt = seeded_picker.step_receipt("QB-7F3A91", _menu())
    assert parse_step_response(receipt["value"], _menu()) in _menu().option_ids
    identity = seeded_picker.identity("QB-7F3A91")
    assert validate_identity_owner_lock(identity, {}, {}) == identity
    assert len(identity["concept"]) <= 240 and identity["concept"].startswith("A ")


def test_seeded_picks_lean_toward_the_concept_ranked_top():
    menu = _menu(count=10)
    counts = [0] * 10
    for n in range(2000):
        counts[menu.option_ids.index(seeded_picker.choose_option(f"S{n}", menu))] += 1
    assert counts[0] > counts[9] * 3


def test_seed_format():
    assert seeded_picker.valid_seed(seeded_picker.new_seed())
    assert seeded_picker.valid_seed("tourney-1.a:b_c")
    assert not seeded_picker.valid_seed("has space") and not seeded_picker.valid_seed("x" * 65)


def _queue(tmp_path, *, walk_status="READY_FOR_REVIEW", busy_finalizes=0):
    calls = {"created": [], "finalized": []}
    busy = {"left": busy_finalizes}

    def create_project(**kwargs):
        calls["created"].append(kwargs)
        return {"project_id": f"p{len(calls['created'])}"}

    def start_run(project_id, **kwargs):
        assert kwargs["controller_route"] == "DETERMINISTIC_CREATIVE_CONTROLLER"
        return {"run_id": f"run.{project_id}", "status": walk_status, "owner_descriptive_fields": {"resolved": {"identity": {"name": f"Name {project_id}"}}},
                "blockers": [{"code": "SOME_BLOCKER"}] if walk_status != "READY_FOR_REVIEW" else []}

    def finalize_run(run_id):
        if busy["left"]:
            busy["left"] -= 1
            raise FoundryError("CG1_FINALIZATION_IN_PROGRESS", "busy")
        calls["finalized"].append(run_id)
        return {"status": "CLEAN_AND_FINALIZED"}

    queue = QuickBuildQueue(tmp_path / "quick_builds", create_project=create_project, lock_choices=lambda pid: None,
                            start_run=start_run, finalize_run=finalize_run)
    return queue, calls


def _wait(queue, batch_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        batch = next(b for b in queue.list() if b["batch_id"] == batch_id)
        if all(item["status"] in {"finished", "failed", "needs_review", "ready"} for item in batch["items"]):
            return batch
        time.sleep(0.05)
    raise AssertionError(f"batch did not finish: {batch}")


def test_quick_build_walks_then_finalizes_each_character(tmp_path, monkeypatch):
    monkeypatch.setattr("character_creation.quick_build.time.sleep", lambda seconds: None)
    queue, calls = _queue(tmp_path, busy_finalizes=2)
    batch = queue.submit(items=[{"route": "seeded", "seed": "QB-1"}, {"route": "seeded"}, {"route": "local_ai"}], target_cl=5)
    done = _wait(queue, batch["batch_id"])
    assert [item["status"] for item in done["items"]] == ["finished"] * 3
    assert [kwargs["autogen_seed"] for kwargs in calls["created"]][0] == "QB-1"
    assert seeded_picker.valid_seed(calls["created"][1]["autogen_seed"])  # a blank seeded row gets a fresh seed
    assert calls["created"][2]["autogen_seed"] is None  # Local AI rows carry no seed
    assert all(kwargs["target_cl"] == 5 for kwargs in calls["created"])
    assert sorted(calls["finalized"]) == ["run.p1", "run.p2", "run.p3"]
    assert done["items"][0]["name"] == "Name p1"


def test_quick_build_reports_a_stopped_walk_and_marks_interrupted_runs(tmp_path):
    queue, calls = _queue(tmp_path, walk_status="NEEDS_REVIEW")
    batch = queue.submit(items=[{"route": "seeded", "seed": "QB-2"}], target_cl=5)
    done = _wait(queue, batch["batch_id"])
    assert done["items"][0]["status"] == "needs_review" and "SOME_BLOCKER" in done["items"][0]["message"]
    assert not calls["finalized"]
    # A build left running when the Factory stopped shows as interrupted after a restart.
    path = tmp_path / "quick_builds" / f"{batch['batch_id']}.json"
    stored = json.loads(path.read_text())
    stored["items"][0]["status"] = "building"
    path.write_text(json.dumps(stored))
    reopened, _ = _queue(tmp_path)
    assert reopened.list()[0]["items"][0]["status"] == "interrupted"


def test_background_sphere_menu_skips_a_sphere_whose_talents_cannot_be_built(monkeypatch):
    """Temple Initiate + Protection offers only Ward, which Stage 2 cannot record (found by seeded builds)."""
    from character_creation.creative_controller import linear_menus as M

    linkage = {"bg": [
        {"background_sphere_choice_id": "sphere.protection", "background_talent_choice_id": "bt.ward", "canonical_talent_id": "bt.ward"},
        {"background_sphere_choice_id": "sphere.radiance", "background_talent_choice_id": "bt.lantern", "canonical_talent_id": "talent.lantern"},
    ]}
    talents = {"sphere.protection": ["bt.ward"], "sphere.radiance": ["bt.lantern"]}

    def linkage_candidates(request, envelope, background_id, sphere_id=None, slot_id=""):
        if slot_id == "background_sphere_choice":
            return [M._Candidate((sphere,), sphere) for sphere in talents]
        return [M._Candidate((talent,), talent) for talent in talents[sphere_id]]

    monkeypatch.setattr(M, "_linkage_candidates", linkage_candidates)
    monkeypatch.setattr(M, "_linear_projection", lambda request, envelope: {"background_package_linkage": linkage})
    monkeypatch.setattr(M, "_slot_rows_by_id", lambda request, envelope, slot: {"talent.lantern": {"availability": {"minimum_cl": 1}}})
    monkeypatch.setattr(M, "_owner_or_state_ids", lambda *args: set())
    assert [c.choice_ids for c in M._background_sphere_candidates({}, {}, "bg")] == [("sphere.radiance",)]


def test_quick_build_never_walks_while_another_character_finalizes(tmp_path):
    """A concurrent walk broke the finalize's identity check (CG1_NONDETERMINISTIC_COMPILATION, 2026-09-24)."""
    import threading

    active = {"now": 0, "peak": 0}
    guard = threading.Lock()

    def busy(result):
        with guard:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time.sleep(0.02)
        with guard:
            active["now"] -= 1
        return result

    queue = QuickBuildQueue(
        tmp_path / "quick_builds",
        create_project=lambda **kwargs: busy({"project_id": f"p{time.monotonic_ns()}"}),
        lock_choices=lambda pid: None,
        start_run=lambda pid, **kwargs: busy({"run_id": f"run.{pid}", "status": "READY_FOR_REVIEW"}),
        finalize_run=lambda run_id: busy({"status": "CLEAN_AND_FINALIZED"}),
    )
    batch = queue.submit(items=[{"route": "seeded"} for _ in range(5)], target_cl=5)
    done = _wait(queue, batch["batch_id"])
    assert [item["status"] for item in done["items"]] == ["finished"] * 5
    assert active["peak"] == 1


def test_spirit_awakening_ability_options_put_dex_second():
    """Owner 2026-09-24: every Spirit Awakening build had DEX 10 and AC 10 (no kit armour); DEX is ranked second now."""
    from character_creation.creative_controller import linear_menus as M

    committed = M.CommittedState().with_slot("path_choice", ["tianxia.path.spirit_awakening"])
    preset = {"abilities": ["STR", "DEX", "CON", "INT", "WIS", "CHA"], "scores": [15, 14, 13, 12, 10, 8]}
    options = M._assignment_candidates(preset, committed)
    assert options
    for option in options:  # every offered arrangement, not just the first
        scores = M._decode_score_bundle(option.choice_ids, "point_buy_assignment")
        assert scores["WIS"] == 15 and scores["DEX"] == 14


def test_walk_menus_enforce_talent_path_prerequisites():
    """2026-09-24 CL10 batch: a non-Qi character was offered Borrowed Furnace Method (requires Qi Cultivation)."""
    from canonical_catalog.service import talent_prerequisite_gates
    from character_creation.creative_controller import linear_menus as M

    request = {"talent_prerequisite_gates": talent_prerequisite_gates()}
    talent = "tianxia.talent.blacksmith.borrowed_furnace_method"
    assert not M._structural_gates_met(request, {}, talent, {"tianxia.path.body_refining", "tianxia.sphere.blacksmith"})
    assert M._structural_gates_met(request, {}, talent, {"tianxia.path.qi_cultivation", "tianxia.sphere.blacksmith"})


def test_an_insight_milestone_does_not_see_training_from_its_own_cl(monkeypatch):
    """CL20 build 2026-09-24: Brush-Armed Guard (needs Brushstroke Shield) was offered at the CL8 milestone,
    but Brushstroke Shield came from CL8 constructed training, which Stage 2 orders after the milestone."""
    from character_creation.creative_controller import linear_menus as M

    insight = "insight.brush-armed-guard"
    talent = "tianxia.talent.ink.brushstroke_shield"
    rows = {"insight_priorities": {insight: {"prerequisites": [{"kind": "talent", "operator": "requires", "target_id": talent}]}}}
    monkeypatch.setattr(M, "_slot_rows_by_id", lambda request, envelope, slot: rows.get(slot, {}))
    committed = M.CommittedState(trained_choices=[{"cl": 8, "slot": 1, "record_id": talent, "choice_type": "known_sphere_talent"}])
    offer = {"allowed_insight_ids": [insight]}
    assert [c.choice_ids for c in M._insight_candidates({}, {}, offer, committed=committed, causal_cl=8)] == []
    assert [c.choice_ids for c in M._insight_candidates({}, {}, offer, committed=committed, causal_cl=9)] == [(insight,)]
