from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .constants import CAPABILITY_NAMES, CAPABILITY_STATES, DEFAULT_CONTENT_FILES
from .models import Diagnostic, Severity, ValidationContext

_TYPED_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "action": ("timing", "economy", "target", "resolution"),
    "reaction": ("trigger", "economy", "effect"),
    "passive": ("scope", "effect"),
    "resource": ("maximum", "spend"),
    "state": ("application", "removal"),
    "condition": ("application", "effects", "removal"),
    "modifier": ("target", "operation", "value"),
    "procedure": ("steps", "result"),
    "movement": ("mode", "distance", "constraints"),
    "zone": ("geometry", "duration", "effects"),
    "creature": ("adapter", "combatant_fields"),
}


def validate_records_and_capabilities(context: ValidationContext) -> None:
    _validate_record_identity(context)
    definitions = _validate_execution_definitions(context)
    policies = _validate_controller_policies(context)
    advancement_records = {row.get("record_id") for row in context.advancement_rules}
    sheet_records = {row.get("record_id") for row in context.character_sheet_rules}
    gm_records = {row.get("record_id") for row in context.gm_display_rules}

    for index, record in enumerate(context.records):
        record_id = record.get("record_id")
        path = DEFAULT_CONTENT_FILES["records"]
        capabilities = record.get("capabilities")
        if not isinstance(capabilities, dict):
            continue
        for capability in CAPABILITY_NAMES:
            state = capabilities.get(capability)
            if state not in CAPABILITY_STATES:
                context.add(
                    Diagnostic(
                        code="CAPABILITY_STATE_INVALID",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="A record declares an invalid capability state.",
                        path=path,
                        record_id=record_id,
                        field_path=f"$.records[{index}].capabilities.{capability}",
                        details={"state": state, "allowed": list(CAPABILITY_STATES)},
                    )
                )
                continue
            if state == "BLOCKED_BY_DEPENDENCY":
                _validate_exact_blocker(context, record, capability, index)
        if capabilities.get("advancement") == "SUPPORTED" and record.get("selectable"):
            if not record.get("advancement_authority") and record_id not in advancement_records:
                context.add(
                    Diagnostic(
                        code="ADVANCEMENT_SUPPORT_WITHOUT_AUTHORITY",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="A selectable record claims advancement support without typed acquisition authority.",
                        path=path,
                        record_id=record_id,
                        field_path=f"$.records[{index}].capabilities.advancement",
                        recommended_action="Add a typed advancement rule or downgrade the capability declaration.",
                    )
                )
        if capabilities.get("character_sheet") == "SUPPORTED":
            display = record.get("display_representation")
            has_display = isinstance(display, dict) and bool(display.get("summary"))
            if not has_display and record_id not in sheet_records:
                context.add(
                    Diagnostic(
                        code="CHARACTER_SHEET_SUPPORT_WITHOUT_DISPLAY",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="Character Sheet support requires stable display representation and provenance.",
                        path=path,
                        record_id=record_id,
                    )
                )
        if capabilities.get("gm_display") == "SUPPORTED":
            display = record.get("display_representation")
            authenticated_display = isinstance(display, dict) and display.get("authenticated") is True
            if not record.get("gm_projection") and record_id not in gm_records and not authenticated_display:
                context.add(
                    Diagnostic(
                        code="GM_DISPLAY_SUPPORT_WITHOUT_PROJECTION",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="GM display support requires a GM projection or authenticated display representation.",
                        path=path,
                        record_id=record_id,
                    )
                )
        if capabilities.get("combat_execution") == "SUPPORTED":
            ids = record.get("execution_definition_ids")
            if not isinstance(ids, list) or not ids:
                context.add(
                    Diagnostic(
                        code="COMBAT_SUPPORT_WITHOUT_EXECUTION_DEFINITION",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="Combat support cannot be proved by metadata, prose, or an empty execution array.",
                        path=path,
                        record_id=record_id,
                    )
                )
            else:
                for definition_id in sorted(set(ids)):
                    definition = definitions.get(definition_id)
                    if definition is None:
                        context.add(
                            Diagnostic(
                                code="EXECUTION_DEFINITION_REFERENCE_MISSING",
                                severity=Severity.ERROR,
                                subsystem="capabilities",
                                message="A combat-supported record references a missing execution definition.",
                                path=path,
                                record_id=record_id,
                                details={"definition_id": definition_id},
                            )
                        )
                    elif definition.get("record_id") != record_id:
                        context.add(
                            Diagnostic(
                                code="EXECUTION_DEFINITION_RECORD_MISMATCH",
                                severity=Severity.ERROR,
                                subsystem="capabilities",
                                message="An execution definition is bound to a different record.",
                                path=DEFAULT_CONTENT_FILES["combat"],
                                record_id=record_id,
                                details={"definition_id": definition_id, "definition_record_id": definition.get("record_id")},
                            )
                        )
                    elif not _definition_complete(definition):
                        context.add(
                            Diagnostic(
                                code="EXECUTION_DEFINITION_INCOMPLETE",
                                severity=Severity.ERROR,
                                subsystem="capabilities",
                                message="A referenced execution definition lacks required typed fields or is not marked complete.",
                                path=DEFAULT_CONTENT_FILES["combat"],
                                record_id=record_id,
                                details={"definition_id": definition_id, "kind": definition.get("kind")},
                            )
                        )
        if capabilities.get("ai_policy") == "SUPPORTED":
            policy_id = record.get("controller_policy_id")
            tactical = record.get("tactical_metadata")
            if not policy_id and not isinstance(tactical, dict):
                context.add(
                    Diagnostic(
                        code="AI_SUPPORT_WITHOUT_TYPED_POLICY",
                        severity=Severity.ERROR,
                        subsystem="capabilities",
                        message="AI support requires typed tactical metadata or an exact controller-policy reference.",
                        path=path,
                        record_id=record_id,
                    )
                )
            if policy_id:
                policy = policies.get(policy_id)
                if policy is None:
                    context.add(
                        Diagnostic(
                            code="CONTROLLER_POLICY_REFERENCE_MISSING",
                            severity=Severity.ERROR,
                            subsystem="capabilities",
                            message="A record references a missing controller policy.",
                            path=path,
                            record_id=record_id,
                            details={"policy_id": policy_id},
                        )
                    )
                elif policy.get("requires_combat_execution") is True and capabilities.get("combat_execution") != "SUPPORTED":
                    context.add(
                        Diagnostic(
                            code="AI_SUPPORT_WHILE_COMBAT_BLOCKED",
                            severity=Severity.ERROR,
                            subsystem="capabilities",
                            message="The AI policy requires executable mechanics, but combat execution is not supported.",
                            path=path,
                            record_id=record_id,
                            details={"combat_execution": capabilities.get("combat_execution"), "policy_id": policy_id},
                        )
                    )
    _validate_capability_dependency_cycles(context)
    _validate_creatures_and_companions(context, definitions, policies)


def _validate_record_identity(context: ValidationContext) -> None:
    versions: dict[str, list[str]] = defaultdict(list)
    for record in context.records:
        record_id = record.get("record_id")
        version = record.get("record_version")
        if isinstance(record_id, str):
            versions[record_id].append(str(version))
    for record_id, all_versions in sorted(versions.items()):
        if len(all_versions) > 1:
            context.add(
                Diagnostic(
                    code="RECORD_ID_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="identity",
                    message="A stable record ID appears more than once in the pack.",
                    path=DEFAULT_CONTENT_FILES["records"],
                    record_id=record_id,
                    details={"occurrences": len(all_versions), "versions": sorted(all_versions)},
                )
            )
        if len(set(all_versions)) > 1:
            context.add(
                Diagnostic(
                    code="RECORD_VERSION_CONFLICT",
                    severity=Severity.ERROR,
                    subsystem="identity",
                    message="One stable record ID is assigned conflicting versions in the same pack.",
                    path=DEFAULT_CONTENT_FILES["records"],
                    record_id=record_id,
                    details={"versions": sorted(set(all_versions))},
                )
            )


def _validate_execution_definitions(context: ValidationContext) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    seen: dict[str, int] = defaultdict(int)
    for index, definition in enumerate(context.combat_definitions):
        definition_id = definition.get("definition_id")
        if not isinstance(definition_id, str):
            continue
        seen[definition_id] += 1
        if definition_id not in result:
            result[definition_id] = definition
        kind = definition.get("kind")
        if kind not in _TYPED_FIELDS_BY_KIND:
            continue
        typed_fields = definition.get("typed_fields")
        missing = [key for key in _TYPED_FIELDS_BY_KIND[kind] if not isinstance(typed_fields, dict) or key not in typed_fields]
        if missing:
            context.add(
                Diagnostic(
                    code="EXECUTION_TYPED_FIELDS_MISSING",
                    severity=Severity.ERROR,
                    subsystem="execution",
                    message="An execution definition omits required typed fields for its mechanical kind.",
                    path=DEFAULT_CONTENT_FILES["combat"],
                    record_id=definition.get("record_id"),
                    field_path=f"$.definitions[{index}].typed_fields",
                    details={"definition_id": definition_id, "kind": kind, "missing_fields": missing},
                )
            )
        primitive_ids = definition.get("primitive_ids")
        if not isinstance(primitive_ids, list) or not primitive_ids:
            context.add(
                Diagnostic(
                    code="EXECUTION_PRIMITIVES_EMPTY",
                    severity=Severity.ERROR,
                    subsystem="execution",
                    message="Typed execution definitions must reference at least one supplied mechanical primitive.",
                    path=DEFAULT_CONTENT_FILES["combat"],
                    record_id=definition.get("record_id"),
                    details={"definition_id": definition_id},
                )
            )
    for definition_id, count in sorted(seen.items()):
        if count > 1:
            context.add(
                Diagnostic(
                    code="EXECUTION_DEFINITION_ID_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="execution",
                    message="An execution definition ID appears more than once.",
                    path=DEFAULT_CONTENT_FILES["combat"],
                    details={"definition_id": definition_id, "occurrences": count},
                )
            )
    return result


def _definition_complete(definition: dict[str, Any]) -> bool:
    kind = definition.get("kind")
    required = _TYPED_FIELDS_BY_KIND.get(kind, ())
    typed_fields = definition.get("typed_fields")
    return (
        definition.get("complete") is True
        and isinstance(typed_fields, dict)
        and all(key in typed_fields for key in required)
        and isinstance(definition.get("primitive_ids"), list)
        and len(definition["primitive_ids"]) > 0
    )


def _validate_controller_policies(context: ValidationContext) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = defaultdict(int)
    for policy in context.controller_policies:
        policy_id = policy.get("policy_id")
        if not isinstance(policy_id, str):
            continue
        counts[policy_id] += 1
        policies.setdefault(policy_id, policy)
        tactical = policy.get("tactical_metadata")
        if not isinstance(tactical, dict) or not tactical:
            context.add(
                Diagnostic(
                    code="CONTROLLER_POLICY_TACTICS_MISSING",
                    severity=Severity.ERROR,
                    subsystem="ai_policy",
                    message="A controller policy lacks typed tactical metadata.",
                    path=DEFAULT_CONTENT_FILES["policies"],
                    record_id=policy_id,
                )
            )
    for policy_id, count in sorted(counts.items()):
        if count > 1:
            context.add(
                Diagnostic(
                    code="CONTROLLER_POLICY_ID_DUPLICATE",
                    severity=Severity.ERROR,
                    subsystem="ai_policy",
                    message="A controller policy ID appears more than once.",
                    path=DEFAULT_CONTENT_FILES["policies"],
                    record_id=policy_id,
                    details={"occurrences": count},
                )
            )
    return policies


def _validate_exact_blocker(context: ValidationContext, record: dict[str, Any], capability: str, index: int) -> None:
    blockers = record.get("capability_blockers")
    exact = []
    if isinstance(blockers, list):
        for blocker in blockers:
            if isinstance(blocker, dict) and blocker.get("capability") == capability:
                identity_keys = [key for key in ("pack_id", "record_id", "primitive_id") if blocker.get(key)]
                if identity_keys:
                    exact.append(blocker)
    if not exact:
        context.add(
            Diagnostic(
                code="CAPABILITY_BLOCKER_IDENTITY_MISSING",
                severity=Severity.ERROR,
                subsystem="capabilities",
                message="BLOCKED_BY_DEPENDENCY requires an exact pack, record, or primitive blocker identity.",
                path=DEFAULT_CONTENT_FILES["records"],
                record_id=record.get("record_id"),
                field_path=f"$.records[{index}].capabilities.{capability}",
            )
        )


def _validate_capability_dependency_cycles(context: ValidationContext) -> None:
    graph: dict[str, set[str]] = defaultdict(set)
    record_ids = {row.get("record_id") for row in context.records if isinstance(row.get("record_id"), str)}
    for record in context.records:
        record_id = record.get("record_id")
        if not isinstance(record_id, str):
            continue
        for dependency in record.get("record_dependencies", []) if isinstance(record.get("record_dependencies"), list) else []:
            if not isinstance(dependency, dict):
                continue
            target = dependency.get("record_id")
            if isinstance(target, str):
                graph[record_id].add(target)
                if target not in record_ids:
                    context.add(
                        Diagnostic(
                            code="RECORD_DEPENDENCY_MISSING",
                            severity=Severity.ERROR,
                            subsystem="dependencies",
                            message="A record dependency references an unknown record in this pack.",
                            path=DEFAULT_CONTENT_FILES["records"],
                            record_id=record_id,
                            details={"dependency_record_id": target},
                        )
                    )
        blockers = record.get("capability_blockers")
        if isinstance(blockers, list):
            for blocker in blockers:
                if isinstance(blocker, dict) and isinstance(blocker.get("record_id"), str):
                    graph[record_id].add(blocker["record_id"])
    cycle = _first_cycle(graph)
    if cycle:
        context.add(
            Diagnostic(
                code="CAPABILITY_DEPENDENCY_CYCLE",
                severity=Severity.ERROR,
                subsystem="dependencies",
                message="Record capability dependencies contain a cycle.",
                path=DEFAULT_CONTENT_FILES["records"],
                details={"cycle": cycle},
            )
        )


def _first_cycle(graph: dict[str, set[str]]) -> list[str] | None:
    visited: set[str] = set()
    active: list[str] = []
    active_set: set[str] = set()

    def visit(node: str) -> list[str] | None:
        if node in active_set:
            start = active.index(node)
            return active[start:] + [node]
        if node in visited:
            return None
        visited.add(node)
        active.append(node)
        active_set.add(node)
        for target in sorted(graph.get(node, set())):
            cycle = visit(target)
            if cycle:
                return cycle
        active.pop()
        active_set.remove(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return None


def _validate_creatures_and_companions(
    context: ValidationContext,
    definitions: dict[str, dict[str, Any]],
    policies: dict[str, dict[str, Any]],
) -> None:
    document = context.parsed_json.get(DEFAULT_CONTENT_FILES["creatures"])
    if not isinstance(document, dict):
        return
    creature_ids: set[str] = set()
    for group in ("creatures", "companions"):
        rows = document.get(group, [])
        if not isinstance(rows, list):
            continue
        for index, creature in enumerate(rows):
            if not isinstance(creature, dict):
                continue
            creature_id = creature.get("creature_id")
            if creature_id in creature_ids:
                context.add(
                    Diagnostic(
                        code="CREATURE_ID_DUPLICATE",
                        severity=Severity.ERROR,
                        subsystem="creatures",
                        message="A creature or companion ID appears more than once.",
                        path=DEFAULT_CONTENT_FILES["creatures"],
                        record_id=creature_id,
                    )
                )
            if isinstance(creature_id, str):
                creature_ids.add(creature_id)
            footprint = creature.get("footprint")
            if not isinstance(footprint, dict) or not footprint.get("width_cells") or not footprint.get("height_cells"):
                context.add(
                    Diagnostic(
                        code="CREATURE_FOOTPRINT_MISSING",
                        severity=Severity.ERROR,
                        subsystem="creatures",
                        message="Creature definitions require an explicit typed battlefield footprint.",
                        path=DEFAULT_CONTENT_FILES["creatures"],
                        record_id=creature_id,
                        field_path=f"$.{group}[{index}].footprint",
                    )
                )
            for field in ("typed_actions", "typed_reactions", "passives", "conditions"):
                refs = creature.get(field, [])
                if isinstance(refs, list):
                    for definition_id in refs:
                        if definition_id not in definitions:
                            context.add(
                                Diagnostic(
                                    code="CREATURE_EXECUTION_REFERENCE_MISSING",
                                    severity=Severity.ERROR,
                                    subsystem="creatures",
                                    message="A creature references an execution definition that is absent.",
                                    path=DEFAULT_CONTENT_FILES["creatures"],
                                    record_id=creature_id,
                                    field_path=f"$.{group}[{index}].{field}",
                                    details={"definition_id": definition_id},
                                )
                            )
            policy_id = creature.get("controller_policy_ref")
            if policy_id not in policies:
                context.add(
                    Diagnostic(
                        code="CREATURE_POLICY_REFERENCE_MISSING",
                        severity=Severity.ERROR,
                        subsystem="creatures",
                        message="A creature references a missing controller policy.",
                        path=DEFAULT_CONTENT_FILES["creatures"],
                        record_id=creature_id,
                        details={"policy_id": policy_id},
                    )
                )
            if group == "companions":
                owner = creature.get("owner_relationship")
                if not isinstance(owner, dict) or not owner.get("owner_record_id"):
                    context.add(
                        Diagnostic(
                            code="COMPANION_OWNER_BINDING_MISSING",
                            severity=Severity.ERROR,
                            subsystem="creatures",
                            message="A companion requires an exact owner relationship binding.",
                            path=DEFAULT_CONTENT_FILES["creatures"],
                            record_id=creature_id,
                            field_path=f"$.companions[{index}].owner_relationship",
                        )
                    )
