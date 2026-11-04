from contextlib import nullcontext
from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest

from app.core import FoundryError, sha256_json
from character_creation.candidate_action_authoring import (
    complete_candidate_action_workspace, prepare_candidate_actions,
)
from factory_authoring.command4_provider import COMMAND4_DETERMINISTIC_CHOICE_REQUIRED, Command4ProviderAuthoring


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    metadata = {"project_id": "project", "project_revision": 7}
    run = {"run_id": "run", "project_id": "project", "status": "NEEDS_REVIEW",
           "request": {"request_sha256": "frozen"}, "created_at": "frozen-clock"}
    capsule = {"summary": {"capsule_id": "original"},
               "context": {"candidate_project": metadata, "factory_workspace": {"workspace_sha256": "base"}},
               "exact_response_text": "{}", "final_plan": {"selected": "frozen"}}
    state = {"capsule": capsule, "calls": 0, "unresolved": [{"record_id": "action"}]}
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "Workspace_Manifest.json").write_text('{"sealed":true}')
    (overlay / "action.json").write_text('{"cost":0}')

    def author(self, project_id, provider, output):
        state["calls"] += 1
        return {"valid": True, "execution_authority": True, "overlay_path": str(overlay)}

    def materialize_deterministic(self, project_id, output):
        if state.get("forced"):
            state["forced_calls"] = state.get("forced_calls", 0) + 1
            return {"valid": True, "execution_authority": True, "overlay_path": str(overlay), "provider_calls": 0}
        raise FoundryError(COMMAND4_DETERMINISTIC_CHOICE_REQUIRED, "A real choice remains.")

    monkeypatch.setattr(Command4ProviderAuthoring, "author", author)
    monkeypatch.setattr(Command4ProviderAuthoring, "materialize_deterministic", materialize_deterministic)
    monkeypatch.setattr("factory_authoring.service.FactoryAuthoringWorkspaceService", lambda db: db)
    monkeypatch.setattr("non_sphere_authority.foundation_mechanics.initial_foundation_record_version", lambda request: "v1")
    monkeypatch.setattr("non_sphere_authority.method_mechanics.initial_method_record_version", lambda request: "v1")

    def materialize(run_id, root):
        (root / "Command_4").mkdir()
        (root / "Command_4/Complete_Action_Surface.json").write_text(json.dumps({"unresolved": state["unresolved"]}))

    gm = SimpleNamespace(
        _root=lambda run_id: tmp_path / "retained",
        _run_scope=lambda run_id: nullcontext(SimpleNamespace(exclusive_lock=nullcontext)),
        _capsule=lambda run_id: (state["capsule"], {}),
        _load_existing=lambda parts: None,
    )
    service = SimpleNamespace(
        candidate_gm=SimpleNamespace(
            _project_snapshot=lambda *args, **kwargs: ({"metadata": metadata}, {}, {}),
            materialize_factory_workspace=materialize,
        ), candidate_gm_authoring=gm, provider=object(), get=lambda run_id: deepcopy(run),
        _normalize_and_materialize_response=lambda run, value: ({}, None, None),
        _plan_with_accepted_final_target=lambda run, plan, final: final,
    )

    def compile_once(run, plan, index, **kwargs):
        from app.core import deterministic_approval_seed, utcnow

        assert utcnow() == "frozen-clock"
        assert deterministic_approval_seed() == run["request"]["request_sha256"]
        assert kwargs["candidate_action_authoring"] == capsule
        assert kwargs["final_plan"] == {"selected": "frozen"}
        state["capsule"] = deepcopy(capsule)
        state["capsule"]["summary"]["capsule_id"] = "authored"
        raise FoundryError("CHARACTER_GM_COMMAND4_BLOCKED", "Needs normal GM approval", details={"gm_candidate_capsule": {"capsule_id": "authored"}})

    service._compile_once = compile_once
    return service, run, capsule, state, overlay


@pytest.mark.parametrize("changed", ["project", "workspace"])
def test_replay_binding_failure_precedes_provider(bridge, tmp_path, changed):
    service, run, capsule, state, _ = bridge
    expected = deepcopy(capsule)
    if changed == "project":
        expected["context"]["candidate_project"]["project_revision"] += 1
    else:
        expected["context"]["factory_workspace"]["workspace_sha256"] = "changed"
    with pytest.raises(FoundryError, match="replay|workspace"):
        complete_candidate_action_workspace(service, run, object(), tmp_path, {"workspace_sha256": "base"}, expected)
    assert state["calls"] == 0


def test_overlay_copy_is_exact_and_original_unchanged(bridge, tmp_path):
    service, run, capsule, state, overlay = bridge
    result = complete_candidate_action_workspace(service, run, object(), tmp_path, {"workspace_sha256": "base"}, capsule)
    assert state["calls"] == 1
    assert result["workspace_sha256"] == sha256_json(result["artifact_hashes"])
    assert (tmp_path / "authored_candidate_actions/action.json").read_bytes() == (overlay / "action.json").read_bytes()
    assert capsule["summary"]["capsule_id"] == "original"


def test_forced_answer_uses_the_deterministic_path_without_the_model(bridge, tmp_path):
    service, run, capsule, state, overlay = bridge
    state["forced"] = True
    result = complete_candidate_action_workspace(service, run, object(), tmp_path, {"workspace_sha256": "base"}, capsule)
    assert state["calls"] == 0 and state["forced_calls"] == 1
    assert (tmp_path / "authored_candidate_actions/action.json").read_bytes() == (overlay / "action.json").read_bytes()
    assert result["workspace_sha256"] == sha256_json(result["artifact_hashes"])


def test_first_capture_completes_forced_actions_and_leaves_real_choices(bridge, tmp_path):
    from character_creation.candidate_action_authoring import complete_forced_candidate_actions

    service, run, _capsule, state, overlay = bridge
    workspace = tmp_path / "workspace"
    (workspace / "Command_4").mkdir(parents=True)
    (workspace / "Command_4/Complete_Action_Surface.json").write_text(json.dumps({"unresolved": [{"record_id": "action"}]}))
    original = {"workspace_path": str(workspace), "workspace_sha256": "base"}
    # A real choice remains: the capture is unchanged and the model is not called here.
    assert complete_forced_candidate_actions(service, run, object(), tmp_path, original) is original
    assert state["calls"] == 0
    state["forced"] = True
    result = complete_forced_candidate_actions(service, run, object(), tmp_path, original)
    assert state["calls"] == 0 and state["forced_calls"] == 1
    assert result["workspace_status"] == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
    assert (tmp_path / "authored_candidate_actions/action.json").read_bytes() == (overlay / "action.json").read_bytes()
    # Nothing unresolved: nothing to do.
    (workspace / "Command_4/Complete_Action_Surface.json").write_text(json.dumps({"unresolved": []}))
    assert complete_forced_candidate_actions(service, run, object(), tmp_path / "other", original) is original


def test_overlay_links_are_rejected(bridge, tmp_path):
    service, run, capsule, state, overlay = bridge
    (overlay / "linked").symlink_to(overlay / "action.json")
    with pytest.raises(FoundryError, match="symbolic link"):
        complete_candidate_action_workspace(service, run, object(), tmp_path, {"workspace_sha256": "base"}, capsule)
    assert not (tmp_path / "authored_candidate_actions").exists()


def test_prepare_recaptures_without_approving_and_restores_environment(bridge, monkeypatch):
    service, run, capsule, state, _ = bridge
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_UTC", "previous")
    monkeypatch.delenv("TIANXIA_DETERMINISTIC_APPROVAL_SEED", raising=False)
    prepare_candidate_actions(service, "run")
    assert state["capsule"]["summary"]["capsule_id"] == "authored"
    assert capsule["summary"]["capsule_id"] == "original"
    assert os.environ["TIANXIA_DETERMINISTIC_UTC"] == "previous"
    assert "TIANXIA_DETERMINISTIC_APPROVAL_SEED" not in os.environ


@pytest.mark.parametrize("skip", ["already_authored", "complete_surface"])
def test_existing_authoring_or_complete_actions_do_not_replay(bridge, skip):
    service, run, capsule, state, _ = bridge
    if skip == "already_authored":
        service.candidate_gm_authoring._load_existing = lambda parts: {"receipt": "preserved"}
    else:
        state["unresolved"] = []
    service._compile_once = lambda *args, **kwargs: pytest.fail("Unexpected replay")
    prepare_candidate_actions(service, "run")
    assert state["calls"] == 0


def test_unexpected_compile_failure_is_not_swallowed(bridge, monkeypatch):
    service, run, capsule, state, _ = bridge
    monkeypatch.setenv("TIANXIA_DETERMINISTIC_UTC", "previous")
    def fail(*args, **kwargs):
        raise FoundryError("OTHER_BLOCKER", "Preserve the blocker")
    service._compile_once = fail
    with pytest.raises(FoundryError, match="Preserve the blocker"):
        prepare_candidate_actions(service, "run")
    assert os.environ["TIANXIA_DETERMINISTIC_UTC"] == "previous"
    assert state["capsule"] is capsule
