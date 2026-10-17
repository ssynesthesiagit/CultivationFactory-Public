"""Deterministic Composite Playbook proposer (no AI model involved).

Fills the data-driven templates in ``rules/playbook_templates.v1.json`` from a
character's ``ActionRegistry`` under the rules file, then runs every proposed
row through ``validate_playbook``.  Only rows that pass are emitted; rows that
fail are returned separately with their diagnostics, and templates that cannot
be filled are listed with the reason, so a data problem stays visible.

Prose fields are derived from the chosen steps' printed lines and computed
totals; nothing about the rules is invented.  The Dao hook is keyword evidence
from the steps' printed text against ``rules/dao_aspects.v1.json`` and the I
Ching hook is the line's change reading computed from its real cost, the pool
and the template's declared shift target (``hooks.py``); the sheet's authored
themes lead both when present.  A new playbook shape is a templates edit and a
legality change is a rules edit; this module only fills and describes.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .hooks import AspectTable, Themes, build_dao_hook, build_i_ching_hook, load_aspects
from .registry import ActionRecord, ActionRegistry
from .rules import RuleSet, load_rules
from .sheet_adapter import registry_from_sheet
from .templates import Slot, Template, TemplateSet, load_templates
from .validator import validate_playbook

DOCUMENT_SCHEMA_VERSION = "TianxiaFoundry.CharacterGMCompositePlaybooks.v1"
CLASSIFICATION = "DISPLAY_ONLY_NOT_EXECUTION_AUTHORITY"
CAPABILITY_STATUS = "SERVER_VALIDATED_PROPOSAL"
GENERATOR_KIND = "deterministic_template_proposer"
DEFAULT_ID_PREFIX = "gm.playbook.proposed"
_ECONOMY_LABELS = {"action": "action", "bonus_action": "bonus action", "reaction": "reaction", "passive": "passive"}


@dataclass
class ProposalResult:
    """Emitted rows plus everything that was not emitted and why."""

    composites: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_document(self, *, source_label: str | None = None) -> dict[str, Any]:
        """In-repo ``Composite_Playbook.json`` shape: vendor-shaped rows under ``composites``."""
        return {
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "composites": deepcopy(self.composites),
            "execution_authority": False,
            "classification": CLASSIFICATION,
            "generator": {
                "kind": GENERATOR_KIND,
                "source": source_label,
                "skipped_templates": deepcopy(self.skipped),
                "rejected_count": len(self.rejected),
                "rejected": [
                    {
                        "composite_id": row.get("composite_id"),
                        "template_id": (row.get("generator") or {}).get("template_id"),
                        "errors": [
                            {"code": item.get("code"), "pointer": item.get("pointer"), "message": item.get("message")}
                            for item in (row.get("validation") or {}).get("diagnostics") or []
                            if isinstance(item, dict) and item.get("severity") == "error"
                        ],
                    }
                    for row in self.rejected
                ],
                "warnings": list(self.warnings),
            },
        }


def _label(economy: str) -> str:
    return _ECONOMY_LABELS.get(economy, economy.replace("_", " "))


def _is_base(record: ActionRecord) -> bool:
    return bool(record.raw.get("base"))


def _cost(record: ActionRecord, resource_id: str | None) -> int:
    return sum(amount for rid, amount in record.resource_costs if resource_id is None or rid == resource_id)


def _zero_cost(record: ActionRecord) -> bool:
    return all(amount <= 0 for _, amount in record.resource_costs)


def _eligible(record: ActionRecord, rules: RuleSet) -> bool:
    return rules.is_executable(record.economy) and bool(record.raw.get("cost_parsed", True))


def _sort_key(record: ActionRecord, prefer: str, resource_id: str | None) -> tuple:
    base_last = 1 if _is_base(record) else 0
    cost = _cost(record, resource_id)
    if prefer == "highest_cost":
        return (-cost, base_last, record.display_name.casefold(), record.action_id)
    return (base_last, cost, record.display_name.casefold(), record.action_id)


def _candidates(slot: Slot, registry: ActionRegistry, rules: RuleSet, used: set[str],
                resource_id: str | None) -> list[ActionRecord]:
    """Records that may fill ``slot``; whitelist order when ``action_ids`` is set, else sorted by preference."""
    if slot.action_ids:
        pool = [registry.get(action_id) for action_id in slot.action_ids if action_id in registry]
    else:
        pool = [registry.get(action_id) for action_id in registry.ids()]
    out: list[ActionRecord] = []
    for record in pool:
        if record is None or record.economy != slot.economy or not _eligible(record, rules):
            continue
        if slot.distinct and record.action_id in used:
            continue
        if slot.own_only and _is_base(record):
            continue
        if slot.base_only and not _is_base(record):
            continue
        if slot.forged_only and not record.raw.get("forged"):
            continue
        if slot.prefer == "zero_cost" and not _zero_cost(record):
            continue
        out.append(record)
    if not slot.action_ids:
        out.sort(key=lambda record: _sort_key(record, slot.prefer, resource_id))
    return out


def _fill(template: Template, registry: ActionRegistry, rules: RuleSet, resource_id: str | None,
          budget: int | None, min_own_steps: int = 0) -> tuple[list[tuple[Slot, ActionRecord]], str | None]:
    """Fill the template's slots in order; return (steps, None) or ([], reason)."""
    steps: list[tuple[Slot, ActionRecord]] = []
    used: set[str] = set()
    spent = 0
    per_round: dict[tuple[int, str], int] = {}
    for index, slot in enumerate(template.slots):
        where = f"slots[{index}] {slot.economy} ({slot.prefer}) at round_offset {slot.round_offset}"
        if slot.round_offset > rules.max_round_offset:
            return [], f"{where}: exceeds max_round_offset {rules.max_round_offset}"
        key = (slot.round_offset, slot.economy)
        capacity = rules.capacity_for(slot.economy)
        if capacity is not None and per_round.get(key, 0) >= capacity:
            if slot.optional:
                continue
            return [], f"{where}: exceeds per-round capacity {capacity}"
        chosen: ActionRecord | None = None
        for record in _candidates(slot, registry, rules, used, resource_id):
            if budget is not None and spent + _cost(record, resource_id) > budget:
                continue
            chosen = record
            break
        if chosen is None:
            if slot.optional:
                continue
            suffix = f" within budget {budget}" if budget is not None else ""
            return [], f"{where}: no eligible action{suffix}"
        steps.append((slot, chosen))
        used.add(chosen.action_id)
        spent += _cost(chosen, resource_id)
        per_round[key] = per_round.get(key, 0) + 1
    low, high = rules.sequence_length["min"], rules.sequence_length["max"]
    steps = steps[:high]
    if len(steps) < low:
        return [], f"only {len(steps)} step(s) filled; sequence_length.min is {low}"
    own = sum(1 for _, record in steps if not _is_base(record))
    if own < min_own_steps:
        return [], f"only {own} step(s) come from the character's own records; min_own_steps is {min_own_steps}"
    return steps, None


def _pool(resource_pools: Mapping[str, Mapping[str, Any]] | None, resource_id: str | None) -> Mapping[str, Any] | None:
    if not resource_pools or not resource_id:
        return None
    pool = resource_pools.get(resource_id)
    return pool if isinstance(pool, Mapping) else None


def _pool_limit(pool: Mapping[str, Any] | None) -> int | None:
    for key in ("current", "maximum"):
        value = pool.get(key) if pool else None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _fallback(steps: list[tuple[Slot, ActionRecord]], registry: ActionRegistry, rules: RuleSet,
              economy: str) -> ActionRecord | None:
    """Zero-cost action in the fallback bucket; prefers one not already in the sequence, own before base."""
    used = {record.action_id for _, record in steps}
    candidates = [registry.get(action_id) for action_id in registry.ids()]
    candidates = [r for r in candidates if r is not None and r.economy == economy and _eligible(r, rules) and _zero_cost(r)]
    candidates.sort(key=lambda r: (r.action_id in used, _is_base(r), r.display_name.casefold(), r.action_id))
    return candidates[0] if candidates else None


def _unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _hook_overrides(templates: TemplateSet, overrides: Mapping[str, str] | None) -> dict[str, str]:
    """Verbatim hook texts a caller (or the templates file) forces; empty when hooks are to be computed."""
    merged = dict(templates.hooks)
    merged.update(overrides or {})
    return {key: merged[key] for key in ("dao_hook", "i_ching_hook") if isinstance(merged.get(key), str) and merged[key]}


def _build_row(template: Template, order: int, steps: list[tuple[Slot, ActionRecord]], *, registry: ActionRegistry,
               rules: RuleSet, templates: TemplateSet, resource_id: str | None, pool: Mapping[str, Any] | None,
               budget: int | None, id_prefix: str) -> dict[str, Any]:
    pool_name = str(pool.get("name") or resource_id) if pool else (resource_id or "resource")
    limit = _pool_limit(pool)
    spent = sum(_cost(record, resource_id) for _, record in steps)
    sequence: list[dict[str, Any]] = []
    for number, (slot, record) in enumerate(steps, start=1):
        step: dict[str, Any] = {
            "step": number,
            "action_id": record.action_id,
            "round_offset": slot.round_offset,
            "economy": record.economy,
            "requires_states": list(record.consumes_states),
            "external_preconditions": [str(p) for p in (record.raw.get("external_preconditions") or ()) if p],
            "display_name": record.display_name,
            "source": "5.5e baseline" if _is_base(record) else ("forged technique" if record.raw.get("forged") else "character record"),
            "resource_costs": [{"resource_id": rid, "amount": amount} for rid, amount in record.resource_costs],
            "cost_text": record.raw.get("cost_text") or "None",
        }
        record_id = record.raw.get("record_id")
        if isinstance(record_id, str) and record_id:
            step["record_id"] = record_id
        sequence.append(step)
    preconditions = _unique(p for step in sequence for p in step["external_preconditions"])
    offsets = sorted({slot.round_offset for slot, _ in steps})
    per_round = "; ".join(
        f"round +{offset}: " + ", ".join(_label(record.economy) for slot, record in steps if slot.round_offset == offset)
        for offset in offsets)
    caps = ", ".join(f"{_label(bucket)} x{count}" for bucket, count in rules.round_economy_capacity.items())
    costed = sum(1 for step in sequence if step["resource_costs"])
    when = "Use when each step's economy slot is free in its round"
    when += (" and each printed condition holds: " + "; ".join(preconditions) + ".") if preconditions \
        else " and no printed condition blocks a step."
    if spent and limit is not None:
        avoid = (f"Do not use when {pool_name} is below {spent} (the sequence spends {spent} of {limit}), "
                 "or when a printed trigger or prerequisite is not met.")
        budget_text = (f"{spent} {pool_name} across {costed} costed step(s); proposal cap {budget} of {limit} "
                       f"current ({round(templates.budget_fraction * 100)}%).")
    elif spent:
        avoid = (f"Do not use when fewer than {spent} {pool_name} remain, "
                 "or when a printed trigger or prerequisite is not met.")
        budget_text = f"{spent} {pool_name} across {costed} costed step(s); no pool total was supplied, so no cap applied."
    else:
        avoid = ("Do not use when a step's action, bonus action or reaction has already been spent this round, "
                 "or when a printed trigger or prerequisite is not met.")
        budget_text = f"No {pool_name} cost; every step is zero-cost."
    fallback = _fallback(steps, registry, rules, templates.fallback_economy)
    totals: dict[str, int] = {}
    for _, record in steps:
        for rid, amount in record.resource_costs:
            if amount > 0:
                totals[rid] = totals.get(rid, 0) + amount
    row: dict[str, Any] = {
        "composite_id": f"{id_prefix}.{template.template_id}",
        "name": " -> ".join(record.display_name for _, record in steps),
        "category": template.category,
        "priority": order,
        "execution_role": template.execution_role,
        "when_to_use": when,
        "do_not_use_when": avoid,
        "resource_budget": budget_text,
        "temporal_feasibility": f"{len(offsets)} round(s); {per_round}; per-round caps: {caps}.",
        "fallback": (f"If a step cannot be taken, {fallback.display_name} is a zero-cost {_label(fallback.economy)}; "
                     "otherwise hold the action." if fallback
                     else "No zero-cost fallback exists in this repertoire; hold the action rather than inventing one."),
        "sequence": sequence,
        "resource_totals": totals,
        "classification": CLASSIFICATION,
        "execution_authority": False,
        "capability_status": CAPABILITY_STATUS,
        "generator": {"kind": GENERATOR_KIND, "template_id": template.template_id,
                      "rules_schema_version": rules.schema_version, "templates_schema_version": templates.schema_version},
    }
    if fallback is not None:
        row["fallback_action_id"] = fallback.action_id
    return row


def propose_playbooks(
    registry: ActionRegistry,
    *,
    rules: RuleSet | None = None,
    templates: TemplateSet | None = None,
    resource_pools: Mapping[str, Mapping[str, Any]] | None = None,
    primary_resource_id: str | None = None,
    hooks: Mapping[str, str] | None = None,
    aspects: AspectTable | None = None,
    themes: Themes | None = None,
    id_prefix: str = DEFAULT_ID_PREFIX,
    available_states: Iterable[str] = (),
) -> ProposalResult:
    """Fill every template from ``registry``, validate each row, and sort rows into emitted / rejected / skipped."""
    active_rules = rules if rules is not None else load_rules()
    active_templates = templates if templates is not None else load_templates()
    overrides = _hook_overrides(active_templates, hooks)
    active_aspects = aspects if aspects is not None else load_aspects()
    result = ProposalResult(warnings=list(registry.warnings))
    pool = _pool(resource_pools, primary_resource_id)
    limit = _pool_limit(pool)
    pool_name = str(pool.get("name") or primary_resource_id) if pool else (primary_resource_id or "resource")
    budget = int(limit * active_templates.budget_fraction) if limit is not None else None
    if primary_resource_id and limit is None:
        result.warnings.append(f"no pool total for {primary_resource_id}; proposals are not budget-capped")
    states = tuple(available_states)
    # Phase 1: fill and describe every template, so each change reading can name its sibling by real name and cost.
    filled: list[tuple[Template, dict[str, Any], list[tuple[Slot, ActionRecord]]]] = []
    for order, template in enumerate(active_templates.templates, start=1):
        steps, reason = _fill(template, registry, active_rules, primary_resource_id, budget, active_templates.min_own_steps)
        if reason is not None:
            result.skipped.append({"template_id": template.template_id, "reason": reason})
            continue
        row = _build_row(template, order, steps, registry=registry, rules=active_rules, templates=active_templates,
                         resource_id=primary_resource_id, pool=pool, budget=budget, id_prefix=id_prefix)
        filled.append((template, row, steps))
    by_template = {template.template_id: row for template, row, _ in filled}
    # Remove rejected change targets to a fixed point. The target set only shrinks.
    while True:
        result.composites.clear()
        result.rejected.clear()
        # Phase 2: hooks from evidence and real numbers, then validation of the complete row.
        for template, row, steps in filled:
            spent = sum(_cost(record, primary_resource_id) for _, record in steps)
            fallback = registry.get(row["fallback_action_id"]) if row.get("fallback_action_id") else None
            target = by_template.get(template.shift_to) if template.shift_to else None
            dao_text, dao_aspects = build_dao_hook(
                [(record.display_name, str(record.raw.get("rules_text") or "")) for _, record in steps], active_aspects, themes)
            row["dao_aspects"] = dao_aspects
            row["dao_hook"] = overrides.get("dao_hook") or dao_text
            row["i_ching_hook"] = overrides.get("i_ching_hook") or build_i_ching_hook(
                tendency=template.tendency, shift_when=template.shift_when,
                shift_to=target["name"] if target else (template.shift_to.replace("_", " ") if template.shift_to else None),
                shift_to_proposed=target is not None,
                shift_to_spent=int((target or {}).get("resource_totals", {}).get(primary_resource_id or "", 0)),
                spent=spent, pool_name=pool_name, limit=limit,
                fallback_name=fallback.display_name if fallback else None, themes=themes)
            row["i_ching_shift"] = {"kind": template.shift_when, "to_template_id": template.shift_to,
                                    "to_composite_id": target["composite_id"] if target else None}
            report = validate_playbook(row, registry=registry, rules=active_rules,
                                       resource_pools=resource_pools, available_states=states)
            row["validation"] = report.to_dict()
            (result.composites if report.ok else result.rejected).append(row)
        accepted = {row["composite_id"] for row in result.composites}
        targets = {key: row for key, row in by_template.items() if row["composite_id"] in accepted}
        if targets.keys() == by_template.keys():
            break
        by_template = targets
    return result


def propose_from_sheet(
    snapshot: Mapping[str, Any],
    *,
    rules: RuleSet | None = None,
    templates: TemplateSet | None = None,
    hooks: Mapping[str, str] | None = None,
    aspects: AspectTable | None = None,
    themes: Themes | None = None,
    id_prefix: str = DEFAULT_ID_PREFIX,
    **adapter_kwargs: Any,
) -> tuple[ProposalResult, ActionRegistry]:
    """Sealed owner sheet -> (proposals, the registry they were drawn from)."""
    registry, pools, primary_id = registry_from_sheet(snapshot, **adapter_kwargs)
    result = propose_playbooks(registry, rules=rules, templates=templates, resource_pools=pools,
                               primary_resource_id=primary_id, hooks=hooks, aspects=aspects, themes=themes, id_prefix=id_prefix)
    return result, registry
