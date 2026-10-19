"""Composite Playbook validator: JSON-schema plus data-driven legality rules.

Rules are plain functions ``rule_<name>(playbook, ctx) -> list[Diagnostic]``.
To add a rule: write the function, register it in ``RULES`` (end of this
module), and list its code in ``rules/combat_economy.v1.json`` ``enabled_rules``.
Rules never parse prose fields (``resource_budget``, ``temporal_feasibility``)
for numbers; they read only the action registry and the rule data.
``external_preconditions`` are external by definition and are not checked.
The vendor ``fallback`` field is prose; zero-cost checking applies only when a
playbook carries an optional ``fallback_action_id`` (hook for the generator).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .registry import ActionRegistry
from .rules import SCHEMA_DIR, RuleSet, load_rules

PLAYBOOK_SCHEMA_FILE = "composite_playbook.schema.json"
COMMON_DEFS_SCHEMA_FILE = "common_defs.schema.json"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: str  # "error" | "warning"
    pointer: str   # JSON pointer into the playbook, e.g. "/sequence/1/economy"
    message: str
    rule: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "pointer": self.pointer,
                "message": self.message, "rule": self.rule}


@dataclass
class ValidationReport:
    playbook_id: str | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    rules_run: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"playbook_id": self.playbook_id, "ok": self.ok,
                "rules_run": list(self.rules_run),
                "diagnostics": [d.to_dict() for d in self.diagnostics]}


@dataclass(frozen=True)
class ValidationContext:
    registry: ActionRegistry
    rules: RuleSet
    resource_pools: Mapping[str, Mapping[str, Any]] | None
    available_states: frozenset[str]
    schema_validator: Draft202012Validator


_SCHEMA_CACHE: dict[tuple[int, int], Draft202012Validator] = {}


def schema_validator() -> Draft202012Validator:
    """Offline validator for the vendor playbook schema (no network refs)."""
    playbook_path = SCHEMA_DIR / PLAYBOOK_SCHEMA_FILE
    defs_path = SCHEMA_DIR / COMMON_DEFS_SCHEMA_FILE
    key = (playbook_path.stat().st_mtime_ns, defs_path.stat().st_mtime_ns)
    cached = _SCHEMA_CACHE.get(key)
    if cached is not None:
        return cached
    playbook_schema = json.loads(playbook_path.read_text(encoding="utf-8"))
    defs_schema = json.loads(defs_path.read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        (playbook_schema["$id"], Resource.from_contents(playbook_schema)),
        (defs_schema["$id"], Resource.from_contents(defs_schema)),
    ])
    validator = Draft202012Validator(playbook_schema, registry=registry)
    _SCHEMA_CACHE.clear()
    _SCHEMA_CACHE[key] = validator
    return validator


def _error(code: str, pointer: str, message: str, rule: str) -> Diagnostic:
    return Diagnostic(code=code, severity="error", pointer=pointer, message=message, rule=rule)


def _warning(code: str, pointer: str, message: str, rule: str) -> Diagnostic:
    return Diagnostic(code=code, severity="warning", pointer=pointer, message=message, rule=rule)


def _steps(playbook: Mapping[str, Any]) -> list[tuple[int, Mapping[str, Any]]]:
    """(index, step) for every well-formed step; malformed shapes are SCHEMA's job."""
    sequence = playbook.get("sequence") if isinstance(playbook, Mapping) else None
    if not isinstance(sequence, list):
        return []
    return [(index, step) for index, step in enumerate(sequence) if isinstance(step, Mapping)]


def _pointer(parts: Iterable[Any]) -> str:
    text = "/".join(str(part) for part in parts)
    return "/" + text if text else ""


def rule_schema(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """SCHEMA: every jsonschema error becomes one diagnostic."""
    return [
        _error("SCHEMA", _pointer(error.absolute_path), error.message, "SCHEMA")
        for error in ctx.schema_validator.iter_errors(playbook)
    ]


def rule_step_numbering(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """STEP_NUMBERING: steps are exactly 1..n in order and n is within sequence_length."""
    steps = _steps(playbook)
    out: list[Diagnostic] = []
    bounds = ctx.rules.sequence_length
    if steps and not (bounds["min"] <= len(steps) <= bounds["max"]):
        out.append(_error("STEP_NUMBERING", "/sequence",
                          f"sequence has {len(steps)} steps; rules allow {bounds['min']}..{bounds['max']}",
                          "STEP_NUMBERING"))
    for position, (index, step) in enumerate(steps, start=1):
        if step.get("step") != position:
            out.append(_error("STEP_NUMBERING", f"/sequence/{index}/step",
                              f"expected step {position}, found {step.get('step')!r}", "STEP_NUMBERING"))
            break
    return out


def rule_economy_executable(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """ECONOMY_EXECUTABLE: each step's economy is an executable bucket per the rules data."""
    out: list[Diagnostic] = []
    for index, step in _steps(playbook):
        economy = step.get("economy")
        if not isinstance(economy, str) or not ctx.rules.is_executable(economy):
            kind = " (listed under non_executable_kinds)" if economy in ctx.rules.non_executable_kinds else ""
            out.append(_error("ECONOMY_EXECUTABLE", f"/sequence/{index}/economy",
                              f"economy {economy!r} is not an executable bucket{kind} "
                              f"(see rules/combat_economy.v1.json executable_buckets: "
                              f"{list(ctx.rules.executable_buckets)})", "ECONOMY_EXECUTABLE"))
    return out


def rule_action_known(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """ACTION_KNOWN: every sequence step and conditional option names a registered action."""
    out: list[Diagnostic] = []
    for index, step in _steps(playbook):
        action_id = step.get("action_id")
        if not isinstance(action_id, str) or action_id not in ctx.registry:
            out.append(_error("ACTION_KNOWN", f"/sequence/{index}/action_id",
                              f"action_id {action_id!r} is not in the action registry", "ACTION_KNOWN"))
    options = playbook.get("conditional_options") if isinstance(playbook, Mapping) else None
    if isinstance(options, list):
        for index, option in enumerate(options):
            if not isinstance(option, Mapping):
                continue
            action_id = option.get("action_id")
            if not isinstance(action_id, str) or action_id not in ctx.registry:
                out.append(_error("ACTION_KNOWN", f"/conditional_options/{index}/action_id",
                                  f"action_id {action_id!r} is not in the action registry", "ACTION_KNOWN"))
    return out


def _known_steps(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[tuple[int, Mapping[str, Any], Any]]:
    """(index, step, ActionRecord) for steps whose action is registered."""
    out = []
    for index, step in _steps(playbook):
        action_id = step.get("action_id")
        record = ctx.registry.get(action_id) if isinstance(action_id, str) else None
        if record is not None:
            out.append((index, step, record))
    return out


def rule_economy_matches_action(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """ECONOMY_MATCHES_ACTION: a step's economy equals the registered action's economy."""
    out: list[Diagnostic] = []
    for index, step, record in _known_steps(playbook, ctx):
        economy = step.get("economy")
        if economy != record.economy:
            out.append(_error("ECONOMY_MATCHES_ACTION", f"/sequence/{index}/economy",
                              f"step economy {economy!r} does not match action {record.action_id!r} "
                              f"economy {record.economy!r}", "ECONOMY_MATCHES_ACTION"))
    return out


def _round_offset(step: Mapping[str, Any]) -> int | None:
    value = step.get("round_offset")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def rule_round_offset_monotonic(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """ROUND_OFFSET_MONOTONIC: round offsets are nondecreasing and within max_round_offset."""
    out: list[Diagnostic] = []
    previous: int | None = None
    for index, step in _steps(playbook):
        offset = _round_offset(step)
        if offset is None:
            continue  # SCHEMA reports the type problem
        pointer = f"/sequence/{index}/round_offset"
        if offset > ctx.rules.max_round_offset:
            out.append(_error("ROUND_OFFSET_MONOTONIC", pointer,
                              f"round_offset {offset} exceeds max_round_offset {ctx.rules.max_round_offset}",
                              "ROUND_OFFSET_MONOTONIC"))
        if previous is not None and offset < previous:
            out.append(_error("ROUND_OFFSET_MONOTONIC", pointer,
                              f"round_offset {offset} is earlier than the previous step's {previous}",
                              "ROUND_OFFSET_MONOTONIC"))
        previous = offset
    return out


def rule_round_economy_capacity(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """ROUND_ECONOMY_CAPACITY: per (round_offset, economy) usage stays within the rules' capacity."""
    out: list[Diagnostic] = []
    used: dict[tuple[int, str], int] = {}
    for index, step in _steps(playbook):
        offset = _round_offset(step)
        economy = step.get("economy")
        if offset is None or not isinstance(economy, str):
            continue
        capacity = ctx.rules.capacity_for(economy)
        if capacity is None:
            continue  # ECONOMY_EXECUTABLE reports buckets without capacity
        key = (offset, economy)
        used[key] = used.get(key, 0) + 1
        if used[key] > capacity:
            out.append(_error("ROUND_ECONOMY_CAPACITY", f"/sequence/{index}/economy",
                              f"round_offset {offset} uses {economy!r} {used[key]} times; capacity is {capacity}",
                              "ROUND_ECONOMY_CAPACITY"))
    return out


def rule_states_available(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """STATES_AVAILABLE: requires_states come from available_states or EARLIER steps' creates_states.

    After a step is checked, the states its action consumes are removed and the
    states it creates are added, so a consumed state is not available later.
    """
    out: list[Diagnostic] = []
    available = set(ctx.available_states)
    for index, step in _steps(playbook):
        required = step.get("requires_states")
        if isinstance(required, list):
            missing = [state for state in required if isinstance(state, str) and state not in available]
            if missing:
                out.append(_error("STATES_AVAILABLE", f"/sequence/{index}/requires_states",
                                  f"required state(s) {missing} are not available before this step "
                                  f"(available: {sorted(available)})", "STATES_AVAILABLE"))
        action_id = step.get("action_id")
        record = ctx.registry.get(action_id) if isinstance(action_id, str) else None
        if record is not None:
            available.difference_update(record.consumes_states)
            available.update(record.creates_states)
    return out


def _pool_limit(pools: Mapping[str, Mapping[str, Any]] | None, resource_id: str) -> int | None:
    if not pools or resource_id not in pools:
        return None
    pool = pools[resource_id]
    if not isinstance(pool, Mapping):
        return None
    for key in ("current", "maximum"):
        value = pool.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def rule_resource_totals(playbook: Mapping[str, Any], ctx: ValidationContext) -> list[Diagnostic]:
    """RESOURCE_TOTALS: registry costs summed per resource stay within the supplied pools.

    A resource with no pool entry yields one RESOURCE_POOL_UNKNOWN warning, not an error.
    """
    out: list[Diagnostic] = []
    totals: dict[str, int] = {}
    order: list[str] = []
    for index, step, record in _known_steps(playbook, ctx):
        for resource_id, amount in record.resource_costs:
            if resource_id not in totals:
                order.append(resource_id)
            totals[resource_id] = totals.get(resource_id, 0) + amount
        for resource_id, minimum in record.resource_requirements:
            if resource_id not in totals:
                order.append(resource_id)
                totals[resource_id] = 0
            limit = _pool_limit(ctx.resource_pools, resource_id)
            if limit is not None and minimum > limit:
                out.append(_error("RESOURCE_TOTALS", f"/sequence/{index}",
                                  f"action {record.action_id!r} requires {resource_id} >= {minimum}; pool has {limit}",
                                  "RESOURCE_TOTALS"))
    for resource_id in order:
        limit = _pool_limit(ctx.resource_pools, resource_id)
        if limit is None:
            out.append(_warning("RESOURCE_POOL_UNKNOWN", "/sequence",
                                f"no resource pool supplied for {resource_id}; total cost "
                                f"{totals[resource_id]} not checked", "RESOURCE_TOTALS"))
        elif totals[resource_id] > limit:
            out.append(_error("RESOURCE_TOTALS", "/sequence",
                              f"sequence spends {totals[resource_id]} {resource_id}; pool has {limit}",
                              "RESOURCE_TOTALS"))
    fallback_id = playbook.get("fallback_action_id") if isinstance(playbook, Mapping) else None
    if ctx.rules.fallback_must_be_zero_cost and isinstance(fallback_id, str):
        record = ctx.registry.get(fallback_id)
        if record is not None and any(amount > 0 for _, amount in record.resource_costs):
            out.append(_error("FALLBACK_NOT_ZERO_COST", "/fallback_action_id",
                              f"fallback action {fallback_id!r} is not zero-cost", "RESOURCE_TOTALS"))
    return out


#: Ordered rule registry. Adding a rule: write the function above, add it here,
#: and list its code in rules/combat_economy.v1.json ``enabled_rules``.
RULES: dict[str, Callable[[Mapping[str, Any], ValidationContext], list[Diagnostic]]] = {
    "SCHEMA": rule_schema,
    "STEP_NUMBERING": rule_step_numbering,
    "ECONOMY_EXECUTABLE": rule_economy_executable,
    "ACTION_KNOWN": rule_action_known,
    "ECONOMY_MATCHES_ACTION": rule_economy_matches_action,
    "ROUND_OFFSET_MONOTONIC": rule_round_offset_monotonic,
    "ROUND_ECONOMY_CAPACITY": rule_round_economy_capacity,
    "STATES_AVAILABLE": rule_states_available,
    "RESOURCE_TOTALS": rule_resource_totals,
}


def validate_playbook(
    playbook: Mapping[str, Any],
    *,
    registry: ActionRegistry,
    rules: RuleSet | None = None,
    resource_pools: Mapping[str, Mapping[str, Any]] | None = None,
    available_states: Iterable[str] | None = None,
) -> ValidationReport:
    """Run every enabled rule, in the rules file's order, over one playbook."""
    active = rules if rules is not None else load_rules()
    unknown = [code for code in active.enabled_rules if code not in RULES]
    if unknown:
        raise ValueError(f"unknown rule codes in enabled_rules: {unknown}; known: {list(RULES)}")
    ctx = ValidationContext(
        registry=registry,
        rules=active,
        resource_pools=resource_pools,
        available_states=frozenset(available_states or ()),
        schema_validator=schema_validator(),
    )
    playbook_id = playbook.get("composite_id") if isinstance(playbook, Mapping) else None
    report = ValidationReport(playbook_id=playbook_id if isinstance(playbook_id, str) else None)
    for code in active.enabled_rules:
        report.diagnostics.extend(RULES[code](playbook, ctx))
        report.rules_run.append(code)
    return report


def validate_playbook_document(document: Any, **kwargs: Any) -> list[ValidationReport]:
    """Validate every playbook in a ``{"composites": [...]}`` document or a bare list."""
    if isinstance(document, Mapping):
        composites = document.get("composites")
        if not isinstance(composites, list):
            raise ValueError("playbook document has no 'composites' list")
    elif isinstance(document, list):
        composites = document
    else:
        raise ValueError(f"playbook document must be an object or list, got {type(document).__name__}")
    return [validate_playbook(playbook, **kwargs) for playbook in composites]
