"""Fail-closed bridge to the Factory's existing delegated final validators."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.core import FoundryError, sha256_json
from character_creation.delegated_choice_authority import (
    final_plan_sha256,
    validate_accepted_final_plan_target,
    validate_delegated_choice_plan,
)

from .contracts import fail, require_digest
from .contracts import require_exact_keys, require_string, require_type


PlanProjector = Callable[[Mapping[str, Any]], Mapping[str, Any]]


FACTORY_VALIDATOR_AUTHORITY_SCHEMA = "TianxiaFoundry.FactoryFinalValidatorAuthorityBinding.v1"
_AUTHORITY_BINDING_KEYS = {
    "schema",
    "canonical_project_sha256",
    "request_sha256",
    "content_lock_hash",
    "typed_choice_snapshot_sha256",
    "delegated_choice_envelope_sha256",
    "target_cl",
    "projector_version_sha256",
    "validator_inputs",
    "authority_sha256",
}
_VALIDATOR_INPUT_KEYS = {
    "run_sha256",
    "project_sha256",
    "response_sha256",
    "provider_required_planning_slot_ids",
}


def validate_mortal_level0_completion(*, target_cl: int, selected_paths: Sequence[str]) -> dict[str, Any]:
    """Validate the explicit mortal completion lane before export.

    The normal delegated validator remains CL1--20.  This small dispatch is
    deliberately separate so a level-0 completion cannot weaken that route.
    """

    if type(target_cl) is not int or target_cl != 0:
        raise ValueError("MORTAL_LEVEL0_TARGET_REQUIRED")
    if not isinstance(selected_paths, (list, tuple)) or selected_paths:
        raise ValueError("MORTAL_LEVEL0_PATHS_FORBIDDEN")
    return {"route": "completed_level0_mortal", "target_cl": 0, "selected_paths": []}


def _normalise_provider_slot_ids(values: Sequence[str] | None) -> list[str]:
    if values is None:
        rows: list[Any] = []
    elif not isinstance(values, (list, tuple)):
        fail("DCC_SCHEMA_TYPE", "factory validator.provider_required_planning_slot_ids must be an array.")
    else:
        rows = list(values)
    result = [require_string(value, path="factory validator.provider_required_planning_slot_ids[]") for value in rows]
    if len(result) != len(set(result)):
        fail("DCC_SCHEMA_DUPLICATE", "factory validator.provider_required_planning_slot_ids must be duplicate-free.")
    return result


def build_factory_validator_authority_binding(
    *,
    canonical_project_sha256: str,
    request_sha256: str,
    content_lock_hash: str,
    typed_choice_snapshot_sha256: str,
    delegated_choice_envelope_sha256: str,
    target_cl: int,
    projector_version_sha256: str,
    run: Mapping[str, Any],
    project: Mapping[str, Any],
    response_sha256: str | None = None,
    provider_required_planning_slot_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Seal every input which can affect the detached Factory validation.

    The first group is the shadow authority supplied by the caller.  The
    nested ``validator_inputs`` group commits the exact detached inputs used
    by the existing Factory validators, including the response and required
    planning-slot arguments.  Keeping the two groups separate makes it
    possible for ``ShadowInputs`` to prove that its authority and the
    adapter's validator authority are the same binding.
    """

    for value, path in (
        (canonical_project_sha256, "factory validator.canonical_project_sha256"),
        (request_sha256, "factory validator.request_sha256"),
        (content_lock_hash, "factory validator.content_lock_hash"),
        (typed_choice_snapshot_sha256, "factory validator.typed_choice_snapshot_sha256"),
        (delegated_choice_envelope_sha256, "factory validator.delegated_choice_envelope_sha256"),
        (projector_version_sha256, "factory validator.projector_version_sha256"),
    ):
        require_digest(value, path=path)
    require_type(target_cl, int, path="factory validator.target_cl")
    if target_cl < 1 or target_cl > 20:
        fail("DCC_SCHEMA_VALUE", "factory validator.target_cl must be in [1,20].")
    if response_sha256 is not None:
        require_string(response_sha256, path="factory validator.response_sha256", nonempty=False)
    if not isinstance(run, Mapping) or not isinstance(project, Mapping):
        fail("DCC_FACTORY_VALIDATOR_INPUT", "Factory validator run and project inputs must be objects.")
    provider_slots = _normalise_provider_slot_ids(provider_required_planning_slot_ids)
    validator_inputs = {
        "run_sha256": sha256_json(dict(run)),
        "project_sha256": sha256_json(dict(project)),
        "response_sha256": response_sha256,
        "provider_required_planning_slot_ids": provider_slots,
    }
    unsigned = {
        "schema": FACTORY_VALIDATOR_AUTHORITY_SCHEMA,
        "canonical_project_sha256": canonical_project_sha256,
        "request_sha256": request_sha256,
        "content_lock_hash": content_lock_hash,
        "typed_choice_snapshot_sha256": typed_choice_snapshot_sha256,
        "delegated_choice_envelope_sha256": delegated_choice_envelope_sha256,
        "target_cl": target_cl,
        "projector_version_sha256": projector_version_sha256,
        "validator_inputs": validator_inputs,
    }
    return {**unsigned, "authority_sha256": sha256_json(unsigned)}


def _validate_authority_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    require_exact_keys(value, _AUTHORITY_BINDING_KEYS, path="factory validator.authority_binding")
    result = deepcopy(dict(value))
    if result["schema"] != FACTORY_VALIDATOR_AUTHORITY_SCHEMA:
        fail("DCC_SCHEMA_VALUE", "Unsupported Factory validator authority binding schema.")
    for field in (
        "canonical_project_sha256",
        "request_sha256",
        "content_lock_hash",
        "typed_choice_snapshot_sha256",
        "delegated_choice_envelope_sha256",
        "projector_version_sha256",
    ):
        require_digest(result[field], path=f"factory validator.authority_binding.{field}")
    require_type(result["target_cl"], int, path="factory validator.authority_binding.target_cl")
    if result["target_cl"] < 1 or result["target_cl"] > 20:
        fail("DCC_SCHEMA_VALUE", "factory validator.authority_binding.target_cl must be in [1,20].")
    validator_inputs = result["validator_inputs"]
    require_exact_keys(validator_inputs, _VALIDATOR_INPUT_KEYS, path="factory validator.authority_binding.validator_inputs")
    for field in ("run_sha256", "project_sha256"):
        require_digest(validator_inputs[field], path=f"factory validator.authority_binding.validator_inputs.{field}")
    if validator_inputs["response_sha256"] is not None:
        require_string(validator_inputs["response_sha256"], path="factory validator.authority_binding.validator_inputs.response_sha256", nonempty=False)
    _normalise_provider_slot_ids(validator_inputs["provider_required_planning_slot_ids"])
    require_digest(result["authority_sha256"], path="factory validator.authority_binding.authority_sha256")
    expected = sha256_json({key: result[key] for key in _AUTHORITY_BINDING_KEYS if key != "authority_sha256"})
    if result["authority_sha256"] != expected:
        fail(
            "DCC_FACTORY_VALIDATOR_AUTHORITY_INVALID",
            "The Factory validator authority binding does not match its sealed digest.",
            details={"expected": expected, "actual": result["authority_sha256"]},
        )
    return result


@dataclass(frozen=True)
class FactoryFinalValidatorAdapter:
    """Project one controller plan into, then validate, a Factory final plan.

    The projector is an explicit version-bound integration seam.  The adapter
    runs the established delegated-choice and frozen-target validators against
    detached copies and returns only a deterministic receipt to the compiler.
    """

    run: Mapping[str, Any]
    project: Mapping[str, Any]
    plan_projector: PlanProjector
    projector_version_sha256: str
    response_sha256: str | None = None
    provider_required_planning_slot_ids: Sequence[str] | None = None
    authority_binding: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run, Mapping) or not isinstance(self.project, Mapping):
            fail("DCC_FACTORY_VALIDATOR_INPUT", "Factory validator run and project inputs must be objects.")
        if not callable(self.plan_projector):
            fail("DCC_FACTORY_PLAN_PROJECTOR_REQUIRED", "A version-bound Factory plan projector is required.")
        require_digest(self.projector_version_sha256, path="factory validator.projector_version_sha256")
        object.__setattr__(self, "run", deepcopy(dict(self.run)))
        object.__setattr__(self, "project", deepcopy(dict(self.project)))
        object.__setattr__(self, "provider_required_planning_slot_ids", tuple(_normalise_provider_slot_ids(self.provider_required_planning_slot_ids)))
        if self.authority_binding is not None:
            binding = _validate_authority_binding(self.authority_binding)
            expected_inputs = {
                "run_sha256": sha256_json(self.run),
                "project_sha256": sha256_json(self.project),
                "response_sha256": self.response_sha256,
                "provider_required_planning_slot_ids": list(self.provider_required_planning_slot_ids),
            }
            if binding["validator_inputs"] != expected_inputs or binding["projector_version_sha256"] != self.projector_version_sha256:
                fail(
                    "DCC_FACTORY_VALIDATOR_AUTHORITY_BINDING",
                    "The sealed Factory validator authority does not match its detached validator inputs.",
                    details={"expected_validator_inputs": expected_inputs, "actual_validator_inputs": binding["validator_inputs"]},
                )
            object.__setattr__(self, "authority_binding", binding)

    @property
    def authority_sha256(self) -> str:
        if self.authority_binding is not None:
            return _validate_authority_binding(self.authority_binding)["authority_sha256"]
        return sha256_json({
            "run_sha256": sha256_json(self.run),
            "project_sha256": sha256_json(self.project),
            "projector_version_sha256": self.projector_version_sha256,
            "response_sha256": self.response_sha256,
            "provider_required_planning_slot_ids": list(self.provider_required_planning_slot_ids or ()),
        })

    def validate_shadow_authority(
        self,
        *,
        canonical_project_sha256: str,
        request_sha256: str,
        content_lock_hash: str,
        typed_choice_snapshot_sha256: str,
        delegated_choice_envelope_sha256: str,
        target_cl: int,
    ) -> str:
        """Require an exact authority match before shadow compilation."""

        if self.authority_binding is None:
            fail(
                "DCC_FACTORY_VALIDATOR_AUTHORITY_REQUIRED",
                "Shadow execution requires a sealed Factory validator authority binding.",
            )
        expected = build_factory_validator_authority_binding(
            canonical_project_sha256=canonical_project_sha256,
            request_sha256=request_sha256,
            content_lock_hash=content_lock_hash,
            typed_choice_snapshot_sha256=typed_choice_snapshot_sha256,
            delegated_choice_envelope_sha256=delegated_choice_envelope_sha256,
            target_cl=target_cl,
            projector_version_sha256=self.projector_version_sha256,
            run=self.run,
            project=self.project,
            response_sha256=self.response_sha256,
            provider_required_planning_slot_ids=self.provider_required_planning_slot_ids,
        )
        actual = _validate_authority_binding(self.authority_binding)
        if actual != expected:
            fail(
                "DCC_FACTORY_VALIDATOR_AUTHORITY_BINDING",
                "The Factory validator authority is not bound to the exact ShadowInputs authority.",
                details={"expected": expected, "actual": actual},
            )
        return actual["authority_sha256"]

    def __call__(self, controller_plan: Mapping[str, Any]) -> dict[str, Any]:
        if self.authority_binding is not None:
            # Re-check detached inputs at every invocation because the frozen
            # dataclass protects field assignment, not nested mapping writes.
            binding = _validate_authority_binding(self.authority_binding)
            expected_inputs = {
                "run_sha256": sha256_json(self.run),
                "project_sha256": sha256_json(self.project),
                "response_sha256": self.response_sha256,
                "provider_required_planning_slot_ids": list(self.provider_required_planning_slot_ids),
            }
            if binding["validator_inputs"] != expected_inputs:
                fail(
                    "DCC_FACTORY_VALIDATOR_AUTHORITY_BINDING",
                    "The Factory validator inputs changed after authority sealing.",
                    details={"expected_validator_inputs": expected_inputs, "actual_validator_inputs": binding["validator_inputs"]},
                )
        controller_plan_sha256 = sha256_json(controller_plan)
        run_before = sha256_json(self.run)
        project_before = sha256_json(self.project)
        projected = self.plan_projector(deepcopy(dict(controller_plan)))
        if not isinstance(projected, Mapping):
            fail("DCC_FACTORY_PLAN_PROJECTION_INVALID", "The Factory plan projector must return an object.")
        try:
            final_plan = validate_delegated_choice_plan(
                deepcopy(dict(self.run)),
                deepcopy(dict(self.project)),
                deepcopy(dict(projected)),
                response_sha256=self.response_sha256,
                provider_required_planning_slot_ids=list(self.provider_required_planning_slot_ids) if self.provider_required_planning_slot_ids is not None else None,
            )
            if final_plan is None:
                fail("DCC_FACTORY_FINAL_VALIDATOR_UNAVAILABLE", "The active run has no delegated Factory validation envelope.")
            target_cl = validate_accepted_final_plan_target(deepcopy(dict(self.run)), deepcopy(dict(self.project)), final_plan)
        except FoundryError as exc:
            return {
                "accepted": False,
                "controller_plan_sha256": controller_plan_sha256,
                "factory_error_code": exc.code,
                "projector_version_sha256": self.projector_version_sha256,
                "validator_authority_sha256": self.authority_sha256,
            }
        if sha256_json(self.run) != run_before or sha256_json(self.project) != project_before:
            fail("DCC_FACTORY_VALIDATOR_MUTATION", "Factory validation mutated its frozen run or project authority.")
        return {
            "accepted": True,
            "controller_plan_sha256": controller_plan_sha256,
            "factory_final_plan_sha256": final_plan_sha256(final_plan),
            "factory_target_cl": target_cl,
            "projector_version_sha256": self.projector_version_sha256,
            "validator_authority_sha256": self.authority_sha256,
        }


def build_factory_final_validator(**kwargs: Any) -> FactoryFinalValidatorAdapter:
    return FactoryFinalValidatorAdapter(**kwargs)
