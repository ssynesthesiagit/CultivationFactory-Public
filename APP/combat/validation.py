from __future__ import annotations

from typing import Any

from .canonical import canonical_sha256
from .gate1 import Gate1BuildResult
from .models import FidelityDisposition, MechanicalDefinition, PackFamily


def _mechanics(result: Gate1BuildResult, stable_id: str) -> dict[str, Any]:
    definition = result.registry.require(stable_id)
    if not isinstance(definition, MechanicalDefinition):
        raise TypeError(f"{stable_id} is not a mechanical definition")
    return definition.mechanics


def validate_gate1(result: Gate1BuildResult) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(check_id: str, passed: bool, explanation: str, details: dict[str, Any] | None = None) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "explanation": explanation,
            "details": details or {},
        })

    families = {pack.manifest.family for pack in result.registry.packs.values()}
    record(
        "G1_FIVE_PACK_FAMILIES",
        families == set(PackFamily),
        "Exactly the five frozen Gate 1 pack families are installed.",
        {"families": sorted(item.value for item in families)},
    )
    record(
        "G1_FOUR_PROJECTIONS",
        len(result.projections) == 4,
        "Four CL5 character runtime projections compiled.",
        {"projection_ids": sorted(result.projections)},
    )
    record(
        "G1_FOUR_DOCTRINES",
        len(result.doctrines) == 4,
        "Four Tactical Doctrine artifacts compiled and bind exact projections.",
        {"doctrine_input_ids": sorted(result.doctrines)},
    )
    fidelity_failures: list[str] = []
    for projection in result.projections.values():
        for row in projection.projection.mechanic_fidelity:
            if row.disposition == FidelityDisposition.MVP_DEFERRED_UNSUPPORTED and any(
                (
                    row.changes_tactical_choices,
                    row.changes_action_sequence,
                    row.changes_resource_use,
                    row.changes_positioning,
                    row.changes_risk_tolerance,
                    row.changes_team_role,
                    row.changes_dao_expression,
                    row.changes_iching_expression,
                )
            ):
                fidelity_failures.append(f"{projection.projection.character_id}:{row.definition_id}")
    record(
        "G1_NO_MATERIAL_MECHANIC_DEFERRED",
        not fidelity_failures,
        "No mechanic that changes tactics, sequence, resources, position, risk, role, Dao, or I Ching is deferred.",
        {"failures": fidelity_failures},
    )
    record(
        "G1_AN_EUI_FIRST_ARM_STATE_GATE",
        _mechanics(result, "action:an_eui.first_arm").get("requires_existing_state") == "condition:an_eui.ruin_tempered",
        "An Eui's First Arm requires an already established Ruin-Tempered weapon state.",
    )
    ling_prohibitions = result.projections["character_mapping:ling_qi_early_outer_sect_cl5"].projection.doctrine_source.prohibitions_and_exceptions
    record(
        "G1_LING_QI_ACTION_AND_RESOURCE_LIMITS",
        "maximum one Bonus Action per turn" in ling_prohibitions and "never spend more Qi than currently available" in ling_prohibitions,
        "Ling Qi's mapping explicitly preserves one-Bonus-Action and no-Qi-underflow constraints.",
        {"prohibitions": ling_prohibitions},
    )
    cui = _mechanics(result, "creature:bai_cui")
    command = _mechanics(result, "action:bai_meizhen.command_cui")
    record(
        "G1_CUI_FIRST_CLASS_COMPANION",
        cui.get("default_without_command") == "DODGE" and command.get("geometry_required") is True,
        "Cui is a first-class companion with nested initiative, default Dodge, and required movement geometry.",
        {"creature": cui, "command": command},
    )
    battlefield = result.battlefield
    record(
        "G1_SQUARE_GRID_BATTLEFIELD",
        (battlefield.width_squares, battlefield.height_squares, battlefield.square_size_ft) == (20, 14, 5),
        "The Sect Training Court is the frozen 20×14 five-foot square grid.",
    )
    record(
        "G1_ONE_QI_HAZARD",
        sum(region.terrain_type == "QI_HAZARD" for region in battlefield.terrain_regions) == 1,
        "The battlefield contains exactly one visible Qi hazard region.",
    )
    participants = [member for team in result.encounter.teams for member in team.participant_ids]
    record(
        "G1_ACCEPTED_ENCOUNTER_ROSTER",
        participants == [
            "character_mapping:an_eui_early_book1_cl5",
            "character_mapping:lee_jia_early_book1_cl5",
            "character_mapping:bai_meizhen_early_outer_sect_cl5",
            "character_mapping:ling_qi_early_outer_sect_cl5",
        ],
        "The encounter contains the accepted four CL5 primary combatants in the frozen teams.",
        {"participants": participants},
    )
    record(
        "G1_NO_COMBAT_RESOLUTION",
        True,
        "Gate 1 compiles content and projections only; it does not resolve turns, rolls, damage, reactions, or terminal outcomes.",
    )
    failed = [check for check in checks if check["status"] != "PASS"]
    core = {
        "schema": "TianxiaFactoryHybridCombatGate1Validation.v1",
        "status": "PASS" if not failed else "FAIL",
        "registry_snapshot_sha256": result.registry.snapshot.snapshot_sha256,
        "projection_hashes": {
            key: value.projection_sha256 for key, value in sorted(result.projections.items())
        },
        "doctrine_hashes": {
            key: value.doctrine_sha256 for key, value in sorted(result.doctrines.items())
        },
        "checks": checks,
        "limitations": [
            "No combat resolution, roll authority, reaction execution, event log, save/replay, controller, escalation router, AI bridge, or combat UI is implemented in Gate 1.",
            "The four mapping artifacts are the accepted Phase 2I vertical-slice mappings; the original character package archives are not embedded in this Factory source checkpoint.",
            "The Qi hazard is identified spatially but its damage/timing mechanics are intentionally deferred to Gate 2.",
        ],
    }
    return {"validation": core, "validation_sha256": canonical_sha256(core)}
