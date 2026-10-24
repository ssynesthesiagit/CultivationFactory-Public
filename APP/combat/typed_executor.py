"""Run typed abilities (factory_authoring.typed_mechanics) in the Gate 2 engine.

Owner 2026-09-24: combat must be modular so rules and abilities are easy to
change and tweak.  Abilities are data: an action whose ``resolution_kind`` is
``TYPED`` carries its typed effects in ``parameters["typed"]``; this module
walks them and hands each effect to the building block registered for its
type in ``BLOCKS``.  A new kind of effect is one new block here.  What a
condition does, how durations map and default targeting live in
``combat/rules/typed_conditions.json``, which is re-read when it changes.
Anything the typed data cannot express is shown to the GM as a rider event.

``parameters["typed"]``::

    {"effects": [...], "riders": [...], "numbers": {"pb", "save_dc", "attack_bonus", "key_mod", "cl"},
     "weapon": {"damage": {"count", "sides", "modifier"}, "damage_type"} | null,
     "duration": {...}, "area": {...} | null, "range_ft": int | null}
"""

from __future__ import annotations

import copy
import json
import math
import re
import threading
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from .gate2_runtime_models import ActionDefinition, ActorState, DiceSpec, LegalCandidate, ActionIntent, Position, RollRecord
from .temp_hp_terms import is_temp_hp_term as _is_temp_hp_term
from .read_queries import file_snapshot
from .ext import damage_delivery as _delivery

RULES_PATH = Path(__file__).resolve().parent / "rules" / "typed_conditions.json"
CONDITION_PREFIX = "condition:typed."
MARK_PREFIX = CONDITION_PREFIX + "mark."
_RULES_CACHE: dict[str, Any] = {"mtime": None, "data": None}
_RULES_LOCK = threading.RLock()
_REQUEST_RULES: ContextVar[dict[str, Any] | None] = ContextVar("typed_request_rules", default=None)
_ACTIVE_SAVES: ContextVar[tuple[tuple[int, str, str], ...]] = ContextVar("typed_active_saves", default=())


def active_save_pending(engine: Any, source: str, subject_id: str) -> bool:
    """Whether SAVE_ROLLED belongs to an active save awaiting final resolution.

    Event consumers (charm_rules immunity) must defer outcome-dependent effects
    to after_save_resolved. Repeated/legacy saves outside block_save retain their
    own event handling. Context-local nesting is cleared even on preview pauses.
    """
    return (id(engine), source, subject_id) in _ACTIVE_SAVES.get()


@contextmanager
def rules_snapshot():
    """Check the editable rules once at the request boundary, including nested table calls."""
    if _REQUEST_RULES.get() is not None:
        yield
        return
    token = _REQUEST_RULES.set(rules())
    try:
        yield
    finally:
        _REQUEST_RULES.reset(token)


def _literal_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_") or "mark"


def _mark_slug(name: str) -> str:
    slug = _literal_slug(name)
    return (rules().get("mark_aliases") or {}).get(slug, slug)


def _mark_lookup_slugs(name: str) -> set[str]:
    """Read equivalent spellings and one-way requirement relationships from rules.

    Queries accept every legacy alias in the requested canonical group. Special
    marks satisfy a broader requirement, but the broader mark does not satisfy
    a special one. This pure lookup never rewrites saved condition instances.
    """
    canonical = _mark_slug(name)
    accepted = {canonical, *(rules().get("mark_counts_as") or {}).get(canonical, ())}
    return accepted | {alias for alias, target in (rules().get("mark_aliases") or {}).items()
                       if target in accepted}


def mark_condition_id(name: str, owner_id: str) -> str:
    """The condition id a mark named ``name`` and placed by ``owner_id`` is stored under (owner
    2026-09-26): ``condition:typed.mark.<slug>.<owner>``, reusing the engine's own condition storage
    (combat/typed_reactions.py's ``bears_mark`` and the ``if_marked``/reaction ``requires_mark``
    checks read the same id)."""
    return f"{MARK_PREFIX}{_mark_slug(name)}.{owner_id}"


def mark_requirement_ids(name: str, owner_id: str) -> set[str]:
    """Stored IDs satisfying this owner's named requirement, including legacy aliases.

    Shared by bears_mark and Miko's purification of individual mark instances.
    Read-only; relationships and spellings come exclusively from rules data.
    """
    return {f"{MARK_PREFIX}{slug}.{owner_id}" for slug in _mark_lookup_slugs(name)}


def bears_mark(actor: ActorState, owner_id: str, mark: str | None = None) -> bool:
    """Whether ``actor`` carries a mark placed by ``owner_id`` (owner 2026-09-26): a specific named
    mark, or any mark at all when ``mark`` is None/"*" (a "marked creature" subject)."""
    if mark and mark != "*":
        wanted = mark_requirement_ids(mark, owner_id)
        return any(c.condition_id in wanted for c in actor.conditions.values())
    suffix = f".{owner_id}"
    return any(c.condition_id.startswith(MARK_PREFIX) and c.condition_id.endswith(suffix) for c in actor.conditions.values())


def is_active_typed_condition(condition: Any) -> bool:
    """Whether a stored typed condition currently grants its typed rules.

    Temporary suppression preserves condition data for later restoration but
    renames the condition under ``condition:typed.suppressed.``. Readers of
    condition benefits must ignore those stored rules until it is restored.
    """
    condition_id = str(getattr(condition, "condition_id", ""))
    return condition_id.startswith(CONDITION_PREFIX) and not condition_id.startswith(CONDITION_PREFIX + "suppressed.")


def rules() -> dict[str, Any]:
    """The owner-editable rules, refreshed on each request (or each unscoped call)."""
    snapshot = _REQUEST_RULES.get()
    if snapshot is not None:
        return snapshot
    return file_snapshot(('typed_conditions', RULES_PATH), _current_rules)


def _current_rules():
    with _RULES_LOCK:
        mtime = RULES_PATH.stat().st_mtime_ns
        if _RULES_CACHE["mtime"] != mtime or _RULES_CACHE.get("path") != RULES_PATH:
            _RULES_CACHE["data"] = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            _RULES_CACHE["mtime"] = mtime
            _RULES_CACHE["path"] = RULES_PATH
        return _RULES_CACHE["data"]


def _walk_rows(effects: Any):
    for row in effects or []:
        if isinstance(row, dict):
            yield row
            for key in ("on_fail", "on_success", "on_hit", "on_miss", "effects"):
                yield from _walk_rows(row.get(key))


def area_damage_rows(ctx: "Context", effects: list[dict[str, Any]], *, owner: ActorState | None = None):
    """Return eligible damage packets delivered to non-creature area recipients.

    Map objects have no saving throw, so a save's failed branch is their
    applicable branch. Successful creature branches and attack hit/miss
    branches are deliberately not merged into that object delivery. Keep the
    shared typed eligibility gates (menu, CL, deferred and once-use) here so
    hooks adding non-creature recipients do not invent a second interpreter.
    Damage uses the shared area recipient policy relative to the asset owner's
    team; a ``target`` child inherits its enclosing save scope. Only a save's
    failed branch is transparent. Other wrappers retain their predicates.
    """
    from .effect_eligibility import eligible
    from .area_recipients import effect_recipient_scope, harmful_area_subject_allowed
    area = (ctx.typed.get("area") or {})

    def visit(rows, inherited_scope=None):
        for row in rows or []:
            if not isinstance(row, dict) or not eligible(ctx, row):
                continue
            kind = row.get("type")
            if kind == "damage":
                # A map asset is a recipient distinct from its owner creature,
                # even when that owner is the area caster. Preserve each row's
                # scope and compare the asset owner by team.
                applies = effect_recipient_scope(row, inherited_scope)
                if applies in {"self", "attacker", "ally", "creatures_in_area"}:
                    continue
                if applies not in {None, "target", "allies", "allies_in_area", "enemies_in_area"}:
                    continue
                if owner is not None and not harmful_area_subject_allowed(
                        ctx.actor, owner, area, {**row, "applies_to": applies},
                        recipient_is_creature=False):
                    continue
                yield row
            elif kind == "save":
                # An inanimate object cannot make the save; resolve its failed
                # consequence only, retaining its recipient scope for children
                # that say "target". Explicit child scopes still override it.
                scope = effect_recipient_scope(row, inherited_scope)
                yield from visit(row.get("on_fail"), scope)
            elif kind == "if_summoned":
                # Summon predicates govern creatures. A map asset has no
                # summoned-creature identity and cannot satisfy this wrapper.
                continue
            elif kind == "attack":
                # An asset is not an attack target. Area delivery must not
                # infer a hit from a creature's separate attack outcome.
                continue
            # Unknown effect wrappers may carry their own predicate. They are
            # not transparent containers, so do not erase that predicate.

    return list(visit(effects))


def cant_hear(actor: ActorState) -> bool:
    """Deafened (2024, owner 2026-09-26): the creature can't hear."""
    return any(row.get("cant_hear") for row in condition_rules(actor))


def _delivery_source(ctx: Any) -> str:
    """Which delivery this commit is part of, for the transient record combat/ext/damage_delivery.py keeps.

    A Context's own ``typed["source"]`` is what the site that is delivering the damage opened its
    frame with -- a trap's ``trap:<zone id>``, an area's own trigger id -- so a commit naming it is
    continuing that delivery and keeps its hazard. Anything else is a different source's damage
    committed while that delivery was resolving, and is delivered as itself."""
    return str((getattr(ctx, "typed", None) or {}).get("source") or "")


def condition_rules(actor: ActorState, *, engine: Any = None) -> list[dict[str, Any]]:
    """The rule rows of every typed condition on the actor. A condition may carry its own rule in its data (``rule``): what
    an area does to the creatures inside it (Numbing Darkness: Disadvantage on Strength, Dexterity and Constitution saving
    throws; combat/zones.py sync_inside). Optional engine context filters sight-
    qualified roll modes, and drops an ENTIRE instance (all of its rows) when a ``condition_excluded`` subscriber says
    that ability retired it; it never narrows an action or movement restriction by itself. Core Dodge and
    data aliases keep their serialized IDs. Returned rows are fresh dictionaries.

    These rows describe a creature's state, not the moment its condition landed: a printed clause the effect itself
    qualified ("If the target is standing on a solid surface, it also cannot take the Dash action", Alchemy's Binding
    Dregs) is settled when that effect resolves, through the ``condition_state`` seam, so a condition that was applied
    stays applied for its own printed duration.

    An ability that has RETIRED a benefit an older build wrote can keep the stale saved instance from doing anything by
    registering a ``condition_excluded`` subscriber: with engine context it is asked about each instance and a True answer
    drops that instance's row.  That is the supported way to make a retired saved effect inert in a fight resumed before
    the boundary that would have removed it -- a save made during the actor's own turn carries the instance into the
    continuation, where nothing else would clear it until the next turn start (combat/motion.py ignores_difficult reads
    these rows; combat/ext/death_riders.py retires the old whole-map Court condition).  Without engine context the
    subscriber is not consulted, so every existing call site is unchanged.
    """
    return [row for _condition, row in condition_rule_instances(actor, engine=engine)]


def condition_rule_instances(actor: ActorState, *, engine: Any = None) -> list[tuple[Any, dict[str, Any]]]:
    """Each active typed condition paired with the rule row it carries (``condition_rules``' rows).

    A general seam for readers that must name the condition a rule came from -- the
    character sheet's Defences card (``typed_reactions.defense_display``) lists the
    condition that grants a damage Resistance or a condition Immunity.  Same filters,
    same rows, same order as ``condition_rules``; that function keeps its bare rows,
    so no existing reader changes.
    """
    table = rules()["conditions"]
    aliases = rules().get('condition_id_aliases') or {}
    out = []
    for c in actor.conditions.values():
        if not is_active_typed_condition(c) and c.condition_id not in aliases:
            continue
        if (c.data or {}).get('suppressed'):
            continue
        if engine is not None and _condition_excluded(engine, actor, c):
            continue
        name = aliases.get(c.condition_id, c.condition_id[len(CONDITION_PREFIX):])
        name = (rules().get('condition_aliases') or {}).get(name, name)
        row = table.get(name, {})
        own = (c.data or {}).get("rule")
        row = {**row, **own} if isinstance(own, dict) else dict(row)
        if row.get('roll_modes_require_source_visible'):
            from .ext.standard_conditions import source_visible
            if engine is None or not source_visible(engine, actor, c.source_actor_id):
                row.pop('attacks_have', None)
                row.pop('check_mode', None)
        out.append((c, row))
    return out


def _condition_excluded(engine: Any, actor: ActorState, condition: Any) -> bool:
    """Whether a ``condition_excluded`` subscriber retires this saved instance, so its rule row is not read at all."""
    from .ext import run

    return any(bool(answer) for answer in run("condition_excluded", engine, actor, condition))


from .typed_amounts import text_formula


def static_formula(name: str | None, numbers: dict[str, Any], *,
                   attack_ability_modifier: int | None = None) -> tuple[int | None, str]:
    """Resolve actor-number formulas for execution and combat displays without events.

    Return (value, trailing printed clause), with value None when unresolved or
    contextual; execution owns trigger data, riders and unknown defaults.

    Every formula a display can answer is read from the one shared table
    (``typed_amounts.formula_value``), the same one execution uses, so the printed
    chip can never hide a bonus the engine already knows (OC13: a weapon technique's
    ``attack_ability_modifier`` printed as "1d6 + a bonus decided when it hits"
    while combat rolled it). ``attack_ability_modifier`` is the delivered weapon's own
    ability modifier, which is what execution passes; without one the printed
    key-ability fallback stands. The two formulas that depend on a roll's outcome
    stay unresolved here rather than being guessed at.
    """
    from .typed_amounts import formula_value, text_formula

    if not name or name == "none":
        return 0, ""
    if name.startswith("text:"):
        return text_formula(name[5:], numbers)
    if name == "half_trigger_damage":
        # Half of the damage the triggering roll dealt: only a roll knows it.
        return None, ""
    value, _narration = formula_value(name, numbers, unknown=None,
                                      attack_ability_modifier=attack_ability_modifier)
    return value, ""


def check_modes(actor: ActorState, ability: str, skill: str | None = None, *,
                engine: Any = None, against_creature: ActorState | None = None,
                hazards: tuple[str, ...] = (), metadata: dict[str, Any] | None = None) -> set[str]:
    """Unresolved check modes, for callers adding other independent sources.

    Callers with a known opposing creature may supply engine
    and against_creature to include source/target-qualified ability_check_mode
    hooks. hazards names the actual check's hazards, never the actor's current
    conditions. Both contexts may contribute to the same check. Omitted or
    mismatched context is inert; suppressed scoped conditions are ignored.
    """
    modes = set()
    if engine is not None and hazards:
        from . import ext
        modes.update(m for m in ext.run_strict("ability_check_hazard_mode", engine, actor, ability, skill, against_creature, hazards)
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
    rows = [(None, row) for row in condition_rules(actor)] if engine is None else condition_rule_instances(actor, engine=engine)
    for condition, row in rows:
        table = row.get("check_mode") or {}
        for key in (ability, skill, "ALL"):  # "ALL": "Disadvantage on ability checks" names none in particular
            if key and table.get(key) in ("ADVANTAGE", "DISADVANTAGE"):
                modes.add(table[key])
    if engine is not None and (against_creature is not None or metadata):
        from . import ext
        from .check_context import checking

        with checking(engine, actor, metadata):
            modes.update(m for m in ext.run("ability_check_mode", engine, actor, ability, skill, against_creature)
                         if m in ("ADVANTAGE", "DISADVANTAGE"))
    if engine is not None and hazards:
        from . import ext
        modes.update(m for m in ext.run_strict("ability_check_hazards", engine, actor, ability, skill, hazards)
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
        for mode in ext.run_checkpoint("check_hazard_mode", engine, actor, ability, skill, hazards):
            if mode not in ("ADVANTAGE", "DISADVANTAGE"):
                raise ext.CheckpointError("check_hazard_mode must return a roll mode or None")
            modes.add(mode)
    # Suppression renames the condition but retains its data. Read scoped modes
    # only from their active condition namespace, not a suppressed copy's rule.
    for condition in getattr(actor, "conditions", {}).values():
        if condition.condition_id != CONDITION_PREFIX + "check_against":
            continue
        scoped = ((condition.data or {}).get("rule") or {}).get("check_against") or {}
        if scoped.get("skills") and skill not in scoped["skills"]:
            continue
        if ability in scoped.get("abilities", ()) and set(hazards).intersection(scoped.get("against", ())):
            if scoped.get("mode") in ("ADVANTAGE", "DISADVANTAGE"):
                modes.add(scoped["mode"])
    return modes


def check_mode(actor: ActorState, ability: str, skill: str | None = None, *,
               engine: Any = None, against_creature: ActorState | None = None,
               hazards: tuple[str, ...] = (), metadata: dict[str, Any] | None = None) -> str:
    """Resolve all supported sources together: any Advantage and Disadvantage cancel."""
    modes = check_modes(actor, ability, skill, engine=engine,
                        against_creature=against_creature, hazards=hazards, metadata=metadata)
    return "NORMAL" if len(modes) != 1 else modes.pop()


# ------------------------------------------------------------------ context
@dataclass
class Context:
    engine: Any
    actor: ActorState
    action: ActionDefinition
    intent: ActionIntent
    typed: dict[str, Any]
    targets: list[ActorState]
    target: ActorState | None = None
    damage_cache: dict[int, tuple[int, str]] = field(default_factory=dict)
    failed_save: bool | None = None
    destination: Any = None  # the square a self-teleport was aimed at (the candidate's destination)
    origin_save: dict[str, Any] | None = None  # the save (ability, DC) selecting either outcome's effects; retained for explicit rechecks (Bell of Clarity)
    save_geometry: dict[str, Any] | None = None  # secondary effects: origin_ids and range_ft, resolution-local only
    check_metadata: dict[str, Any] = field(default_factory=dict)  # explicit source/observer/issues for this check only
    save_result: Any = None  # exact current RollRecord at save_final, including opposed saves; transient only
    save_dc: int | None = None  # actual threshold after save modifiers; transient only
    save_effect: dict[str, Any] | None = None  # exact current save packet, when provided by block_save
    save_support_sources: list[dict[str, str]] = field(default_factory=list)  # actual helpful providers for this final save only
    area_harmful_scope: str | None = None  # transient parent permission for nested save/attack payloads
    attack_result: dict[str, Any] | None = None  # transient current attack roll; never saved or shared across attacks
    attack_effect: dict[str, Any] | None = None  # actual current strike, including derived/reaction strikes
    weapon_damage_dice: bool = False  # these attack dice came from the weapon's own damage, not a row the
    # technique printed; resolution-local, set by block_attack before attack_damage hooks run, never saved
    forced_movement_distance_ft: int | None = None  # remaining triggering distance while reduction hooks run; resolution-local
    attack_notice: Any = None  # immutable settled legacy attack metadata; never persisted
    attack_damage_context: Any = None  # explicit confirmed hit for this Context's damage only
    # General typed-save contract: `inherit_attack_damage_context` carries
    # these three transient fields when the fail branch is bonus damage attached
    # to the hit that opened the save. Ordinary saves intentionally start blank.
    # this one strike's transient record (strike_record): shared with this hit's own child contexts, replaced by a
    # nested strike's own, never saved
    strike_record: dict[str, Any] | None = None
    attack_mode_consumption_pending: bool = False  # transient roll-benefit sweep phase; inherited by attached damage
    attack_defense_spec: Any = None  # transient declared benefits for this hit's explicitly attributed damage
    missed_target_ids: tuple[str, ...] = ()  # frozen empty-square aims, never live recipients
    hit_snapshots: dict[str, Any] = field(default_factory=dict)  # hit-time receipts, never persisted
    hop_destination: dict[str, Any] = field(default_factory=dict)  # the answer already given for each teleport hop
    # this one use of an ability represents, keyed by combat/ext/teleport_steps.hop_key; shared by every effect row
    # that spells out the same teleport, resolution-local, never saved
    hop_completed: set[str] = field(default_factory=set)  # completed player-selected attempts, including blocks
    critical_hit: bool = False  # resolved hit only; reset per attack, including converted criticals
    effect_source: str | None = None  # attribution of a named rider; action/targeting ownership stays unchanged
    damage_packet_kind: str = "technique"  # resolution-local selection identity, never saved
    damage_source_flags: tuple[str, ...] = ()  # transient, scoped to this packet
    damage_pressure_kind: str = 'damage'  # explicit producer classification; no source-name inference
    damage_divisor: int = 1  # resolution-local delivery scaling; cached rolls retain their full value
    defer_damage_notifications: bool = False  # attached pre-primary damage is included in the enclosing attack notification; never saved
    damage_packets: tuple[dict[str, Any], ...] = ()  # committed packets of the enclosing damage_dealt report; never saved
    continue_after_defeat: bool = False  # finish packets already attached to the same confirmed hit; never saved
    defeat_notification_scope: dict[str, Any] = field(default_factory=lambda: {
        "drop": set(), "own_kill": set(),
    })  # shared by nested hit contexts; bounded to one damage chain
    explicit_self_recipient: bool = False  # parent save/attack explicitly targets its user;
    # child target effects retain that printed scope. Resolution-local, never saved.
    save_area: bool = False  # scope of the actual selecting save; never written into origin_save/conditions
    save_damage_responses: dict[str, Any] = field(default_factory=dict)  # one recipient/save outcome's local response budgets
    technique_event_start: int | None = None  # event window for this typed use; never engine-global or persisted
    effect_resolution: str = "ordinary"  # ordinary action or a previously installed delayed consequence

    def target_display(self) -> str:
        """Names for player prompts, without adding objects to creature rosters.

        Object deliveries carry their selected object in the activation cache;
        implicit self actions retain the caster fallback. Display only: this
        helper does not select recipients or change reaction/effect targeting.
        """
        obj = self.damage_cache.get("_object")
        names = [target.display_name for target in self.targets]
        if obj is not None:
            from .object_rules import label
            names.append(label(obj))
        return ", ".join(names) or self.actor.display_name

    def with_source(self, source: str | None) -> Context:
        """Name a rider without changing damage delivery or defense typing.

        Does not replace the triggering action, its costs, numbers or targeting.
        Plug-ins with placed effects still use action.source_definition_id for
        catalog lookup. Damage retains that action ID and records this override
        in event payloads only; saves and conditions retain the rider's identity.
        """
        return replace(self, effect_source=source)

    def on_hit_context(self, target: ActorState, **changes: Any) -> Context:
        """Child for damage belonging to this hit (bonuses, Forms, Exploits).

        Carries the resolved critical through independently cached effects.
        A different catalog action owns its own display attribution; a caller
        may explicitly supply effect_source to name that action's rider.
        Ordinary saves, zones and new attacks construct their own Context.
        """
        action = changes.get("action")
        if action is not None and action.source_definition_id != self.action.source_definition_id:
            changes.setdefault("effect_source", None)
            changes.setdefault("explicit_self_recipient", False)
        child = replace(self, targets=[target], target=target, failed_save=None,
                        origin_save=None, save_area=False, save_damage_responses={}, **changes)
        if child.attack_damage_context is not None:
            # An explicitly attached bonus keeps the hit/roll identity even
            # when a different catalog action supplies its damage and label.
            child.attack_damage_context = replace(child.attack_damage_context,
                                                 source_id=child.damage_source)
        return child

    @property
    def source(self) -> str:
        return self.effect_source or self.action.source_definition_id

    @property
    def damage_source(self) -> str:
        """Catalog delivery identity for defenses; rider attribution is event-only."""
        return self.action.source_definition_id

    def damage_metadata(self) -> dict[str, str]:
        return {"display_source_id": self.effect_source} if self.effect_source else {}

    @property
    def numbers(self) -> dict[str, int]:
        return self.typed.get("numbers") or {}

    def formula(self, name: str | None) -> int:
        from .typed_amounts import formula_value
        value, notice = formula_value(name, self.numbers,
            trigger_damage=getattr(self.engine, '_typed_trigger_damage', 0),
            attack_ability_modifier=(self.typed.get('weapon') or {}).get('ability_modifier'))
        if notice:
            self.rider(notice)
            if notice.startswith('Formula not typed:'):
                value = int(rules()['defaults'].get('unknown_formula_value', 0))
        return value

    def dice(self, spec: dict[str, Any] | None, *, flat: int = 0, formula: str | None = None) -> "DiceSpec | FlatAmount":
        from .typed_amounts import dice_terms
        count, sides, modifier = dice_terms(spec, flat=flat, formula=formula, resolve=self.formula)
        if count < 1 or sides < 2:
            return FlatAmount(modifier)
        return DiceSpec(count=count, sides=sides, modifier=modifier)

    def expires_on(self) -> str | None:
        duration = self.typed.get("duration") or {}
        if duration.get("concentration"):
            return "CONCENTRATION_END"
        return duration_expiry(self.engine, duration, source=self.actor, holder=self.target)

    def rider(self, text: str) -> None:
        self.engine._append_event("GM_RIDER", self.source, actor_id=self.actor.entity_id,
                                  target_ids=tuple(t.entity_id for t in self.targets), payload={"rider": text})


from .typed_amounts import dice_from_text as _dice_from_text


@dataclass(frozen=True)
class FlatAmount:
    """A fixed amount with no dice; rolls to its modifier."""

    modifier: int
    count: int = 0
    sides: int = 0


def _effect_dice(ctx: Context, effect: dict[str, Any]) -> dict[str, Any] | None:
    from .typed_amounts import effect_dice
    return effect_dice(effect, ctx.numbers)


def _roll(ctx: Context, dice: "DiceSpec | FlatAmount", reason: str, *, critical: bool = False, damage_label: str | None = None,
          preserve_sign: bool = False) -> int:
    """Record a roll; an optional effect-owned label identifies separate damage in history.

    The label is event metadata only and never changes dice, costs or damage delivery.
    """
    if dice.count <= 0 or dice.sides <= 0:
        return int(dice.modifier) if preserve_sign else max(0, dice.modifier)
    roll = ctx.engine.roller.roll(dice, actor_id=ctx.actor.entity_id, reason=f"{reason}:{ctx.damage_source}", critical=critical)
    ctx.engine._record_roll(roll)
    from .technique_interception import damage_amount
    amount = damage_amount(ctx.engine, ctx.actor.entity_id, ctx.source, roll.roll_id, roll.total) if reason == 'DAMAGE' else roll.total
    ctx.engine._append_event("DAMAGE_ROLLED", ctx.damage_source, actor_id=ctx.actor.entity_id,
                             target_ids=tuple(t.entity_id for t in ctx.targets),
                             payload={**roll.model_dump(mode="json"), **ctx.damage_metadata(), **({"critical": True} if critical else {}),
                                      **({"damage_label": damage_label} if damage_label else {}),
                                      **({"adjusted_total": amount} if amount != roll.total else {})})
    return amount


# What a row may do to another creature and never to its own user: a "target" row of these kinds
# stays unresolved when nobody was aimed at, rather than landing on the caster (_default_subject).
_NEVER_ON_THE_CASTER = frozenset({"save", "attack", "damage", "extra_damage", "half_damage", "condition", "forced_movement",
                                  "reaction_denied", "healing_reduction", "spend_resource", "mark"})


def _aimed_at_itself(ctx: Context, effect: dict[str, Any]) -> bool:
    """A single-target benefit cast on its own user.  ``resolve_typed`` leaves ``targets`` empty when the
    target is the actor, so a "the target gains ..." row would find nobody (hunt 3, bug 4: Coagulate cast
    on itself granted no Temporary HP).  Only a self or ally-or-self ability, never an area, and never a
    row that harms its subject."""
    if ctx.targets or ctx.target is not None or effect.get("harmful") or (effect.get("type") in _NEVER_ON_THE_CASTER and not effect.get("once_per_creature")):
        return False
    return str(ctx.action.target_kind).endswith("SELF") and not (ctx.typed.get("area") or {}).get("size_ft")


def _declared_subjects(ctx: Context, effect: dict[str, Any], *, harmful: bool) -> list[ActorState]:
    applies = effect.get("applies_to")
    if applies in {"self"}:
        return [ctx.actor]
    if applies == "attacker" and "triggering_source_id" in ctx.typed:
        source = ctx.engine.state.actors.get(ctx.typed["triggering_source_id"])
        return [source] if source is not None else []
    if applies in {"target", "enemies_in_area", "creatures_in_area", "allies_in_area", "allies", "attacker"} or harmful:
        found = [ctx.target] if ctx.target is not None else list(ctx.targets)
        from .area_recipients import scoped_area, harmful_area_subject_allowed, harmful_effect_scope
        area = scoped_area(ctx.typed.get("area") or {}, ctx.typed.get("effects") or [effect], typed=ctx.typed)
        if getattr(ctx, "explicit_self_recipient", False):
            area = {**area, "include_self": True}
        if harmful:
            found = [subject for subject in found
                     if harmful_area_subject_allowed(ctx.actor, subject, area, effect,
                         explicit_self=getattr(ctx, "explicit_self_recipient", False),
                         inherited=getattr(ctx, "area_harmful_scope", None))]
        # Nested/repeated effects and legacy contexts may supply their own
        # roster. Printed effect-level exclusions still apply after the area
        # scope guard; explicit self costs took the branch above.
        if effect.get("exclude_self"):
            found = [subject for subject in found if subject.entity_id != ctx.actor.entity_id]
        policy = harmful_effect_scope(area, effect, inherited=getattr(ctx, "area_harmful_scope", None)) if harmful else None
        if applies == "enemies_in_area" and policy not in {"all", "other_creatures"}:
            return [subject for subject in found if subject.team_id != ctx.actor.team_id]
        if applies in {"allies_in_area", "allies"} and not policy:
            return [subject for subject in found if subject.team_id == ctx.actor.team_id]
        if not found and applies == "target" and not harmful and _aimed_at_itself(ctx, effect):
            return [ctx.actor]
        return found
    if applies == "ally":
        redirected = ctx.engine.state.actors.get(ctx.typed.get("_activation_redirect_recipient_id") or "")
        if redirected is not None and redirected.active:
            return [redirected]
        protected = ctx.engine.state.actors.get(ctx.typed.get("protects") or "")
        if protected is not None:
            return [protected]  # a bystander's reaction shields this ally (combat/typed_reactions.py _run_generic_effects)
        if ctx.target is not None and ctx.target.team_id == ctx.actor.team_id and \
                (ctx.target is not ctx.actor or str(ctx.action.target_kind).endswith("ALLY_OR_SELF")):
            return [ctx.target]  # the ally (or, for an ally-or-self ability, the user) it was aimed at
        if str(ctx.action.target_kind).endswith("ALLY_OR_SELF") and ctx.target is None and not ctx.targets \
                and not (ctx.typed.get("area") or {}).get("size_ft"):
            return [ctx.actor]  # an ally-or-self ability aimed at its user (riders lane 2: Kindle the Rising on yourself)
        return _allies_near(ctx, effect)
    return [ctx.actor]


def _default_subject(ctx: Context, effect: dict[str, Any], *, harmful: bool) -> list[ActorState]:
    from . import ext

    return [subject for subject in _declared_subjects(ctx, effect, harmful=harmful)
            if not ext.any_false("effect_subject_allowed", ctx, effect, subject)]


def default_subjects(ctx: Context, effect: dict[str, Any], *, harmful: bool) -> list[ActorState]:
    """Declared subjects of ``effect`` that pass the ``effect_subject_allowed`` hook.

    Public name for plug-ins that pick an effect's default recipients.
    """
    return _default_subject(ctx, effect, harmful=harmful)


def simultaneous(ctx: Context, subjects: list[ActorState]):
    """Resolve one effect for several recipients as a single simultaneous batch.

    Area saves and area damage apply to every recipient at once. While a batch
    of two or more recipients resolves, the engine's victory_deferred hold keeps
    an early defeat (including the user caught in its own area under the
    2026-10-01 friendly-fire ruling) from ending combat before the remaining
    recipients resolve; the ordinary victory check then runs once, so a batch
    that defeats both sides is a simultaneous draw. One recipient keeps the
    immediate check. No saved state.
    """
    from contextlib import nullcontext
    hold = getattr(ctx.engine, "victory_deferred", None)
    return hold() if hold is not None and len(subjects) > 1 else nullcontext()


def activation_hold(engine: Any, typed: dict[str, Any]):
    """Hold victory until one whole activation has resolved, when its typed row opts in.

    ``hold_victory_until_resolved`` keeps a defeat from ending combat before the
    activation's remaining printed effects (payment, object and zone clauses)
    run. Opt-in, so no other action's resolution changes. No saved state.
    """
    from contextlib import nullcontext
    hold = getattr(engine, "victory_deferred", None)
    return hold() if hold is not None and typed.get("hold_victory_until_resolved") else nullcontext()


def effect_subjects(ctx: Context, effect: dict[str, Any], *, harmful: bool) -> list[ActorState]:
    """Resolve declared effect recipients using the executor's targeting rules.

    Shared by ordinary typed effects and extension effects such as damage wards.
    The effect_subject_allowed hook can exclude individual recipients.
    ``applies_to`` scopes this effect alone; ``exclude_self`` preserves printed
    "other creatures" exceptions without narrowing a mixed action's roster.
    A nested save/attack's explicit self recipient survives in its transient
    Context; child target rows retain it without widening the action roster.
    A harmful effect without a target stays unresolved; this does not authorize
    new targets or mutate state.
    """
    return _default_subject(ctx, effect, harmful=harmful)


def save_subjects(ctx: Context, effect: dict[str, Any]) -> list[ActorState]:
    """Pure save recipients shared by execution and area-risk previews.

    Legacy printed recipient phrases scope only this save, never another
    effect. Generic creature wording defaults to enemies; only explicitly
    inclusive wording admits allies. Emitted cones/lines still exclude their
    user through the shared area policy. Explicit scopes retain the rider
    lane's normal recipient behavior and owner overrides remain authoritative.
    """
    save_effect = effect
    phrase = str(effect.get("recipient_text") or effect.get("evidence") or "")
    if not effect.get("applies_to") and (ctx.typed.get("area") or {}).get("size_ft"):
        if re.search(r"\b(?:hostile creatures?|enem(?:y|ies))\b[^.!?]*\b(?:makes?|must|succeed|saving throw)", phrase, re.I):
            save_effect = {**effect, "applies_to": "enemies_in_area"}
        elif re.search(r"\bcreatures? (?:in|inside|within)\b", phrase, re.I):
            inclusive = re.search(r"\b(?:each|every|all|any) (?:other )?creatures?\b", phrase, re.I)
            save_effect = {**effect, "applies_to": "creatures_in_area" if inclusive else "enemies_in_area"}
    if re.search(r"\b(?:creatures? other than you|each other creature)\b", phrase, re.I):
        save_effect = {**save_effect, "exclude_self": True}
    return effect_subjects(ctx, save_effect, harmful=True)


# ---- How long an effect lasts (hunt 2026-09-29, bug 1) ----------------------------------------------------------------------
# An effect can carry its own duration -- a "duration" ("until_start_of_next_turn", "until_end_of_next_turn", "instant", ...)
# and the printed words ("until the end of its next turn") -- and it was ignored: only effect["expires_on"] and the whole
# ability's duration were read. A Reaction's "cannot take Reactions until the end of its next turn" ended with the turn it was
# used in; its "Speed reduced by 10 feet until the start of its next turn" never ended (a Reaction carries no ability duration).

_APOS = "(?:'|’)s"
_WHOSE = rf"(?P<who>your|its|their|his|her|the \w+{_APOS}|that \w+{_APOS})"
_LEAD = r"(?:until|before|expires at|ends at)"
_TURN_PHRASES = (
    ("end", re.compile(rf"\b{_LEAD} the end of {_WHOSE} (?:next|following) turn\b", re.I)),
    ("start", re.compile(rf"\b{_LEAD} (?:the start of )?{_WHOSE} (?:next|following) turn\b", re.I)),
    ("over", re.compile(r"\b(?:(?:until|before) the end of (?:the current|this|that|the|your|its|their)|(?:for )?the rest of (?:the|this|that)"
                        r"(?: current)?) turn\b", re.I)),
)
_ACTION = object()  # effect_expiry's fallback: the ability's own duration


def _turn_phrases(effect: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Every turn lifetime the effect's own words name, as (where it starts, edge, whose), in the order they are written.
    Edge "start", "end" or "over" ("until the end of the turn"); whose "your" or another owner word ("its", "the target's")."""
    for field_name in ("evidence", "on"):
        text = re.sub(r"\s+", " ", str(effect.get(field_name) or ""))
        found = [(match.start(), edge, (match.groupdict().get("who") or "").lower())
                 for edge, pattern in _TURN_PHRASES for match in pattern.finditer(text)]
        if found:
            return sorted(found)
    return []


def _turn_phrase(effect: dict[str, Any]) -> tuple[str, str] | None:
    """(edge, whose) of the first "until the start / end of <whose> next turn" in the effect's own words: edge "start", "end" or
    "over" ("until the end of the turn"); whose "your" or another owner word ("its", "the target's"). None when it names none."""
    found = _turn_phrases(effect)
    return (found[0][1], found[0][2]) if found else None


def _bounded_to_this_turn(effect: dict[str, Any]) -> bool:
    """Whether the effect's own words bound it to the turn it happens in ("for the rest of the turn", "until the end of the
    current turn"): a shorter statement than any counted or Concentrating lifetime, so it is read even under one."""
    phrase = _turn_phrase(effect)
    return phrase is not None and phrase[0] == "over"


# One effect's own words can describe more than one effect at once, so a turn phrase in them is not necessarily this effect's.
# These read that shape: _STATEMENT_SPLIT separates the sentences (or "; " clauses) of a quote, _A_CLAUSE_PAIR is the boundary
# between two clauses however it is punctuated (", and" or an " and " with no comma), _A_COUNTED_LIFETIME is a length stated in
# the same words, and _adds_a_second_effect says whether a later sentence, or a clause joined to this one, says that
# something else happens besides this effect.
_STATEMENT_SPLIT = re.compile(r"[.;]\s+")
_A_CLAUSE_PAIR = re.compile(r"(?:,\s*|\s+)(?:and|then|but|while)\s+", re.I)
_SPELLED_OUT_NUMBER = (r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|twenty"
                       r"|a few|an?|another|several")
_A_COUNTED_LIFETIME = re.compile(rf"\b(?:{_SPELLED_OUT_NUMBER})\s+(?:full\s+|extra\s+)?(?:rounds?|minutes?|hours?|days?)\b"
                                 rf"|\bfor the next (?:round|minute|hour)\b", re.I)

# Words added after the lifetime are a *limit* on the effect already stated, not a further effect, when their predicate states
# a floor or a ceiling ("This cannot reduce Speed below 0.", "... but cannot be reduced below 0", "at least 0 feet"). A floor
# or a ceiling is a bound on a number, so it is the only thing a limit needs to be one: read in either order, a bound before
# the predicate ("below 0 feet") or after it ("cannot reduce Speed below 0"). A predicate that asserts a state before it
# limits something is a new statement about the creature ("It is also Poisoned.", "its Speed is reduced", "gains
# Disadvantage on saves"), and a name written with a capital in the middle of a sentence is one ("Poisoned", "Disadvantage on
# saves"). Nothing here knows an ability, an effect type or a stat -- only what a floor and a ceiling are made of, and that
# one penalty with a floor is still one penalty.
_A_BOUND = re.compile(r"\b(?:below|above|under|minimum|maximum|no\s+more\s+than|no\s+less\s+than|at\s+least|at\s+most"
                      r"|instead\s+of|rather\s+than|only\s+to|down\s+to|up\s+to)\b", re.I)
# The negations a clause can state: "cannot", "is not", "no longer". A negation is not a limit by itself -- one that stops
# the creature doing something instead is a further effect, quoted beside this one: "Speed is reduced by 10 feet for the
# rest of the turn and it cannot take Reactions." carries two effects, so the row's own counted clock must stand
# (PRO15r4 review, finding 1). What it limits is decided by _names_the_effect_this_speaks_of.
_A_KEEPS = re.compile(r"\b(?:cannot|can\s+not|can't|may\s+not|is\s+not|are\s+not|does\s+not|do\s+not|has\s+not|have\s+not"
                      r"|will\s+not|does\s+never|never|no\s+longer|not)\b", re.I)
# What opens a fresh statement about the creature: a subject of its own ("It", "its Speed", "the target"), a predicate with
# the subject it follows ("and gains Disadvantage on saves"), or a capitalised name in the middle of a sentence. A
# coordination inside one noun phrase opens none of them ("Its walking and flying Speed are reduced by 10 feet"), so it is
# still one effect.
_OPENS_A_STATEMENT = re.compile(r"^(?:this|that|it|they|them|these|those|he|she|you|its|their|his|her|your|the|a|an)\b"
                                r"|^(?:is|are|am|become|becomes|gain|gains|lose|loses|has|have)\b", re.I)
_OPENS_WITH_A_NAME = re.compile(r"^[A-Z][a-z]")
# A predicate can be led by the effect's own name, written with a capital or not ("This reduction cannot reduce Speed below
# 0", "This Speed reduction cannot ..."), so up to two words between a subject and its predicate are read past. A word that
# joins two clauses, or that states something in its own right, stops the scan: that is a further effect, not a limit
# ("It is also Poisoned and cannot be cured").
_STOPS_A_PREDICATE = re.compile(r"^(?:and|or|but|then|while|because|so|which|also|gains?|loses?|becomes?|has|have|does|do"
                                r"|will|can|could|may|might)\b", re.I)
_ORDINARY_WORD = re.compile(r"^[A-Za-z]+$")
_EDGE_OF_A_WORD = str.maketrans("", "", ".,;:!?\"'()")
# A passive verb carries the subject it was built on, so a negated one speaks about the thing that was already said ("cannot
# be reduced"); a plain verb and its object is the creature losing something else.
_A_PASSIVE = re.compile(r"\bbe\s+(?:not\s+)?\w+(?:ed|en)\b", re.I)
# An adverb says how much, how often or how well, never what is done, so the verb behind it is still the verb of the clause.
# Printed rules set one in front of the verb ("cannot be further reduced", "cannot further reduce Speed below 0"); taking
# it for the verb would name the clause after it, and so refuse the floor it states. This is one closed class of English
# adverbs, not a list of ability names, and it is only ever read past -- never treated as the verb itself.
_AN_ADVERB_BEFORE_A_VERB = re.compile(
    r"^(?:further|furthermore|more|less|again|also|even|only|still|ever|already|hereafter|thereafter|instead|otherwise"
    r"|likewise|anymore|thus|hence|well)$", re.I)
# A word short enough to be shared by half the printed rules ("the", "its", "not", "10") names nothing on its own, so it can
# never be what says two passages are about the same thing.
_TOO_SHORT_TO_NAME_SOMETHING = 4
# "-ing" as a present participle drops a silent e and doubles a final consonant, so "reduce"/"reducing", "move"/"moving",
# "take"/"taking" and "dispel"/"dispelling" are one word whose stem is spelled three different ways.
_THE_PRESENT_PARTICIPLE = "ing"


def _the_same_word(one: str, other: str) -> bool:
    """Whether two words are one word written two ways -- a base and its inflection, "reduce"/"reduced", "reduce"/"reducing",
    "move"/"moving", "dispel"/"dispelling": the shorter leads the longer, or the longer is the shorter's present participle,
    and the shorter is long enough to be a word of its own."""
    shorter, longer = sorted((one, other), key=len)
    if len(shorter) < _TOO_SHORT_TO_NAME_SOMETHING:
        return False
    return longer.startswith(shorter) or _is_that_word_a_participle(shorter, longer)


def _is_that_word_a_participle(base: str, word: str) -> bool:
    """Whether ``word`` is ``base`` written as a present participle: "reduce"/"reducing", "move"/"moving", "take"/"taking",
    "dispel"/"dispelling". Adding "-ing" drops a silent e ("reduc" + "ing", "mov" + "ing") or doubles a final consonant
    ("dispell" + "ing"), so the stem is compared against the base with either of those done to it. Nothing here names an
    ability, an effect type or a stat -- only how English spells a participle."""
    if not word.endswith(_THE_PRESENT_PARTICIPLE) or len(word) < _TOO_SHORT_TO_NAME_SOMETHING:
        return False
    stem = word[: -len(_THE_PRESENT_PARTICIPLE)]
    return stem == base[:-1] or stem.startswith(base) or stem == base + base[-1]


def _the_verb_of(predicate: str) -> str:
    """The verb of ``predicate`` -- the words a denial governs -- as the one word that says what it is done to: the word
    after "be" when the predicate is passive ("be reduced"), otherwise the first word ("reduce Speed below 0"), reading
    past an adverb that stands in front of it ("be further reduced", "further reduce"). One word, because the verb is what
    says what a clause is about and the rest of the clause does not."""
    words = _words_of(predicate)
    if len(words) > 1 and words[0] == "be":
        words = words[1:]
    return next((word for word in words if not _AN_ADVERB_BEFORE_A_VERB.match(word)), "")


def _speaks_of_this_effect(predicate: str, said: str) -> bool:
    """Whether the verb of ``predicate`` is a word ``said`` -- the sentence that states the effect -- already uses, written
    as a base or as an inflection of it ("reduce"/"reduced", "reduce"/"reducing", "move"/"moved", "move"/"moving"). A limit
    has to be about the very thing that was stated, and a verb is what says what a clause is about: so a floor on this
    effect ("cannot reduce Speed below 0", "cannot be further reduced below 0") speaks of it, and a restriction on something
    else ("cannot be healed", "cannot be moved above 10 feet from the ground") does not, however much else the two
    passages share.

    The verb is read through the words that do not name what is done to anything -- the adverb in front of it ("cannot be
    further reduced", "cannot further reduce Speed below 0") -- and matched against the participles a sentence may print
    instead of its verb ("This is reducing Speed by 10 feet ... cannot reduce Speed below 0"), because a floor is still the
    same floor whichever of the two ways it is written, and the effect it bounds is still that same Speed.

    The numbers and nouns a restriction quotes are deliberately not evidence. "The target cannot be moved above 10 feet from
    the ground" beside "Speed is reduced by 10 feet" shares every number and every noun it has and is still about the
    target's height rather than this effect. Where the predicate does not name the effect, whether it is a limit on it or a
    second effect beside it is not stated by the words, and the row's own counted kind is kept (PRO15r5 review, finding 1).
    Nothing here names an ability, an effect type or a stat -- only whether two sentences use the same word."""
    verb = _the_verb_of(predicate)
    return bool(verb) and any(_the_same_word(verb, word) for word in _words_of(said))


def _names_the_effect_this_speaks_of(words: list[str], said: str) -> bool:
    """Whether ``words`` -- what is left of a clause once its negation is read -- is about the effect already stated, rather
    than about something else the creature is forbidden to do. It is about that effect when its own verb says so
    (``_speaks_of_this_effect``) *and* its predicate states a bound on it: a bound is a bound on a number ("cannot reduce
    Speed below 0"), and a passive is that same verb carrying the bound ("cannot be reduced below 0"). A plain verb and its
    object is the creature losing something else, which is a further effect."""
    if not words:
        return True  # a bare negation bounds nothing, but names no other effect either
    predicate = " ".join(words)
    if not _speaks_of_this_effect(predicate, said):
        return False  # its verb is not this effect's verb, so how far it limits that effect is not stated
    return _A_BOUND.search(predicate) is not None or _A_PASSIVE.match(predicate) is not None


def _adds_a_second_effect(clause: str, said: str) -> bool:
    """Whether ``clause`` -- a sentence or an "and" / "then" / "but" / "while" clause following this effect's lifetime --
    says something else happens, rather than limiting the effect already stated in ``said``. One general lexical test, shared
    by every counted row: a later sentence or clause is a further effect when it opens a statement of its own and its
    predicate is not a limit ("It is also Poisoned.", "The court ends.", "it cannot take Reactions."), and part of the same
    effect when it limits that effect ("This cannot reduce Speed below 0.", "This reduction cannot reduce Speed below 0.") or
    joins words inside one phrase ("walking and flying Speed"). A clause with no subject of its own only adds an effect when
    it denies the creature something, which it can only mean besides this one ("... and cannot take Reactions")."""
    opening = _OPENS_A_STATEMENT.match(clause) or _OPENS_WITH_A_NAME.match(clause)
    head = clause if opening is None else clause[opening.end():]
    if _is_a_limit(head, said):
        return False
    if opening is not None:
        return True
    # No subject of its own: a noun phrase or a verb joining words inside this effect's own sentence ("Its walking and
    # flying Speed are reduced by 10 feet") is part of it, and a denial that named this effect was read as a limit above.
    # What is left denies the creature something of its own, and so is a further effect.
    words = _words_of(head)
    denial = _A_KEEPS.match(" ".join(words))
    return denial is not None and not _names_the_effect_this_speaks_of(words[len(denial.group(0).split()):], said)


def _is_a_limit(head: str, said: str) -> bool:
    """Whether the words after a subject state a bound on this effect -- a floor, a ceiling, or a negation that keeps to
    this effect ("cannot reduce Speed below 0", "cannot be reduced below 0"). The effect may be named between the subject
    and its predicate ("This reduction cannot reduce Speed below 0"), so up to two words are read past first; a word that
    joins clauses or states something of its own stops the scan and is not a limit. What it bounds decides the rest: a
    predicate whose verb is not this effect's own bounds nothing here that the words state."""
    text = head.strip()
    words = _words_of(text)
    for index in range(min(3, len(words))):
        denial = _A_KEEPS.match(" ".join(words[index:]))
        if denial is not None:
            return _names_the_effect_this_speaks_of(words[index + len(denial.group(0).split()):], said)
        if _STOPS_A_PREDICATE.match(words[index]) or not _ORDINARY_WORD.match(words[index]):
            return False
    return False


def _words_of(text: str) -> list[str]:
    """The words of ``text``, stripped of the punctuation that ends them, so a participle is read as a participle whether it
    ends the clause ("reduced.") or comes before another word ("reduced by 10 feet")."""
    return [word.translate(_EDGE_OF_A_WORD).lower() for word in text.split() if word.translate(_EDGE_OF_A_WORD)]


def _own_words_state_one_lifetime(effect: dict[str, Any]) -> bool:
    """Whether the effect's own words name a turn lifetime *for this effect and nothing else*, so the words, not a coarser
    counted ``duration`` kind, decide how long it lasts (P20261005-15).

    A counted kind is the row's own reviewed lifetime, and one printed sentence routinely describes several effects: Heaven's
    Roar's Deafened reads "Deafened for 1 minute, and Disadvantage on Concentration saving throws until the end of your next
    turn", so the turn phrase there is a sibling effect's and the minute must stand. That is why this is a test about the
    *shape* of the words, not about whose turn they name: a quote that describes one effect and one lifetime only -- no second
    clause, no second lifetime, no length named beside the turn -- is read as this effect's own words, whether the phrase is
    ownerless ("for the rest of the turn") or owned ("until the start of its next turn"). A printed "for the rest of the turn"
    must not last ten rounds because the typed kind said ``one_minute``.

    Every way the words can carry more than one effect or one lifetime is refused, however it is punctuated (review
    2026-10-05, finding 1): two turn lifetimes in one quote ("Disadvantage until the start of its next turn and Speed reduced
    for the rest of the turn") are two effects', a length spelled out rather than written in digits beside the turn ("Poisoned
    for two minutes and its Speed is reduced until the start of its next turn") is a second lifetime, and the lifetime
    itself sitting in a later sentence than the effect it belongs to is the rider's.

    A sentence or a joined clause after the lifetime is part of that one description when it limits this effect, and a
    further effect when it says something else happens (review findings 1 and 2, PRO15r3): "This cannot reduce Speed below
    0.", "... but cannot be reduced below 0." and "Its walking and flying Speed are reduced by 10 feet" are one penalty --
    with a floor, or one Speed -- and keep the lifetime in the words, while "It is also Poisoned." is a second effect and the
    counted kind is kept. A row whose printed wording really is short is corrected in the typed data (its own ``duration``),
    not guessed from wording here. Every counted row whose words name a turn is such a sibling quote (P20261005-15 census,
    re-read after this change), so the exception changes no shipped ability.

    A limit must also *refer back* to that one effect (PRO15r4 review, findings 1 and 2), which is what its own words have to
    show, not merely that a negation is there, and it must show it with its own verb (PRO15r5 review, finding 1): the verb of
    the words a denial governs has to be a word this effect's own sentence already uses, written as a base or as an
    inflection of it. So the lifetime stays in the words for "This cannot reduce Speed below 0" and for "Its Speed cannot be
    reduced below 0", however the effect is named before its predicate ("This reduction cannot reduce Speed below 0") and
    whichever subject is put in front of it. A passive carries the subject it was built on and a bound bounds only the number
    it is written beside, so a restriction on the creature beside this effect is a further effect and its counted kind is
    kept -- "The target cannot be healed.", "and its wounds cannot be healed", "It cannot take Reactions.", and even
    "The target cannot be moved above 10 feet from the ground", whose numbers and nouns are this effect's own. Where the
    words do not say whether a clause limits this effect or states another beside it, the row's reviewed counted kind is what
    ends it, which is the conservative reading in both directions.

    Reading that verb means reading through the words in front of it that do not name what is done to anything, and matching
    the participles a sentence may print in place of its verb (PRO15r6 review, finding 1). "Its Speed cannot be further
    reduced below 0" puts an adverb in front of the passive, "This cannot further reduce Speed below 0" in front of the plain
    verb, and "This is reducing Speed by 10 feet for the rest of the turn. This cannot reduce Speed below 0." writes the
    effect itself as a participle. All three state one Speed penalty with a floor on it, so all three keep the lifetime in
    the words; taking the adverb or the participle for the verb named the clause after the wrong word and read the floor as a
    second effect, which lasted the row's counted ten rounds -- or a whole Concentration -- instead of the stated turn. The
    floor side is unchanged by reading them through: a restriction on the creature beside the effect still names another
    verb and still keeps its counted kind.
    """
    for field_name in ("evidence", "on"):
        text = re.sub(r"\s+", " ", str(effect.get(field_name) or "")).strip()
        phrases = _turn_phrases({field_name: text})
        if not phrases:
            continue
        if len(phrases) > 1 or _A_COUNTED_LIFETIME.search(text):
            return False  # more than one lifetime: the counted kind is the row's reviewed lifetime
        statements = [part.strip() for part in _STATEMENT_SPLIT.split(text) if part.strip()]
        if phrases[0][0] >= len(statements[0]):
            return False  # the lifetime is in a later sentence, so it is the rider's and not this effect's
        said = statements[0]  # the sentence that states the effect; every added clause is read against it
        parts = [part.strip() for part in _A_CLAUSE_PAIR.split(said) if part.strip()]
        # A clause that was joined to this sentence is read against the sentence with itself taken out, so that "its wounds
        # cannot be healed" cannot be the echo of its own "healed" rather than of the Speed penalty's "reduced".
        added = [(part, said) for part in statements[1:]] + [(part, said.replace(part, " ", 1)) for part in parts[1:]]
        return not any(_adds_a_second_effect(part, beside) for part, beside in added)
    return False


def _turn_expiry(ctx: Context, edge: str, anchor: ActorState, *, condition: bool,
                 modifier_source_actor_id: str | None = None) -> str:
    """The expiry name for the start / end of ``anchor``'s next turn. Native source-turn names are valid only when the
    anchor is the actor stored as the effect's source; every other anchor needs the persisted exact-turn token from
    combat/ext/effect_durations.py (the turn counter makes "its next turn" exact even when the actor is already taking it)."""
    # Source-anchored native expiries are swept by source_actor_id. A modifier applied by a zone
    # while its target is taking a turn therefore needs the explicit holder token too; current_actor_id
    # alone does not make START_OF_SOURCE_NEXT_TURN target-anchored.
    # Conditions record the applying actor explicitly. Modifiers normally
    # inherit the initiative actor in gate2_engine._add_modifier; off-turn
    # reactions therefore need a holder token when their turn anchor differs
    # from that stored owner. source_owned modifiers explicitly store ctx.actor.
    # _add_modifier defaults persisted ownership to the initiative actor, which
    # can differ from ctx.actor for an off-turn reaction. Keep expiry anchoring
    # aligned with that saved owner unless the caller explicitly owns it.
    filed_under = modifier_source_actor_id or (
        ctx.actor.entity_id if condition else str(ctx.engine.state.current_actor_id or ctx.actor.entity_id)
    )
    turn = int(anchor.turns_started) + 1
    if anchor.entity_id == filed_under:
        return "START_OF_SOURCE_NEXT_TURN" if edge == "start" else f"END_OF_SOURCE_TURN_AT:{turn}"
    from .ext import effect_durations

    return effect_durations.token(edge, anchor.entity_id, turn)


_SCENE_TEXT = re.compile(r"\bscene\b", re.I)


def clock_expiry(engine: Any, kind: str, amount: Any = None) -> str | None:
    """The expiry name for a duration the round clock covers, from now: a count of rounds ("rounds", "minutes", the effects'
    "one_minute", "hours", "days") -- the round clock of combat/ext/effect_durations.py, at the standard in the rules'
    ``duration_rounds`` table, shared with zones -- or the fight (explicit ``lasts_the_fight`` scene kinds).
    None for any other kind."""
    table = rules().get("duration_rounds") or {}
    rounds = duration_round_count(kind, amount)
    if rounds is not None:
        from .ext import effect_durations

        return effect_durations.round_token(engine, rounds)
    return "UNTIL_REMOVED" if kind in (table.get("lasts_the_fight") or ()) else None


def duration_round_count(kind: str, amount: Any = None) -> int | None:
    """Shared counted duration for executor effects/marks and zones, from rules data.

    Unknown kinds have no clock. Explicit scene kinds alone last the fight.
    """
    per_unit = (rules().get("duration_rounds") or {}).get(kind)
    return max(1, int(amount or 1)) * per_unit if type(per_unit) is int and per_unit >= 1 else None


def duration_turn(kind: str) -> tuple[str, str] | None:
    """Shared effect/mark/ability turn vocabulary: (edge, source or holder)."""
    row = (rules().get("duration_turns") or {}).get(kind)
    return (row["edge"], row["anchor"]) if row else None


def duration_expiry(engine: Any, duration: dict[str, Any], *, source: Any = None, holder: Any = None) -> str | None:
    """The expiry name for what an ability's duration (Concentration aside) does not name a turn for: the rules' table first
    (until_removed), then what the round clock covers (rounds, minutes, hours, days; explicit scene kinds last the fight). "special"
    with the text "The scene" lasts the fight too; the rest of the "special" texts (rests, "until destroyed") name no clock."""
    kind = str(duration.get("kind") or "instant").strip().lower()
    # Preserve the legacy short spelling's token. Explicit your/holder kinds
    # need an exact anchor; ability, effect and mark readers share duration_turns.
    turn = duration_turn(kind)
    if turn and kind != "until_start_of_next_turn":
        from .ext import effect_durations

        edge, whose = turn
        source = source or engine.state.actors[engine.state.current_actor_id]
        anchor = source if whose == "source" else holder or source
        return effect_durations.token(edge, anchor.entity_id, int(anchor.turns_started) + 1)
    named = rules()["durations"].get(kind)
    if named:
        return named
    if kind == "special" and _SCENE_TEXT.search(str(duration.get("text") or "")):
        return "UNTIL_REMOVED"
    return clock_expiry(engine, kind, duration.get("amount"))


# Effect-level duration kinds that name a turn edge and whose turn: "source" is the creature that used the ability. The kind
# "until_end_of_next_turn" says whose turn no more than the printed words do; the effect is on the affected creature.
_KIND_THIS_TURN = {"end_of_turn", "this_attack"}
_TRIGGERING = re.compile(r"\btriggering\b", re.I)
TARGET_NEXT_START = "START_OF_TARGET_NEXT_TURN"  # the sealed engine's name for it ends early; stated_expiry names the turn instead


def stated_expiry(ctx: Context, effect: dict[str, Any], subject: ActorState | None, *, condition: bool = False,
                  modifier_source_actor_id: str | None = None) -> str | None:
    """The expiry an effect states outright: its own ``expires_on``, or the turn it names in words ("until the end of its next
    turn"). None when it states none. ``condition``: the caller applies a condition (filed under the applier) rather than a
    modifier (filed under whoever's turn it is now); see _turn_expiry."""
    if effect.get("expires_on") == TARGET_NEXT_START:
        # "Until the start of its next turn", as the reviewed rows and combat/ext/* write it. The sealed engine ends this name at
        # the start of the applier's next turn *or* the holder's, whichever comes first, so a Smothered from a zone that fires
        # as the holder's own turn starts, or a Reaction on its turn, ended with the applier's turn and not the holder's
        # (hunt 2, bug 3). The holder's next turn has an exact name.
        return _turn_expiry(ctx, "start", subject or ctx.actor, condition=condition,
                            modifier_source_actor_id=modifier_source_actor_id)
    if effect.get("expires_on"):
        return effect["expires_on"]
    phrase = _turn_phrase(effect)
    if phrase is None:
        return None
    edge, who = phrase
    if edge == "over":
        return "END_OF_CURRENT_TURN"
    return _turn_expiry(ctx, edge, ctx.actor if who == "your" else subject or ctx.actor, condition=condition,
                        modifier_source_actor_id=modifier_source_actor_id)


def effect_expiry(ctx: Context, effect: dict[str, Any], subject: ActorState | None, *, condition: bool = False,
                  fallback: Any = _ACTION, modifier_source_actor_id: str | None = None) -> str | None:
    """Resolve explicit expiry, the effect's counted duration, then prose/turn kinds and the ability fallback.

    Evidence may quote several effects with different lifetimes, so an effect's own words decide when they state a lifetime
    for this effect alone. Explicit ``expires_on`` still wins, including holder-turn anchoring. A counted ``duration`` kind is
    then authoritative -- that fixes Heaven's Roar's Deafened, whose evidence also quotes a sibling's turn-length penalty --
    except in two documented cases, both narrower than "the kind always wins":

    * the words state one lifetime of this effect and nothing else (``_own_words_state_one_lifetime``), so they are read;
    * the ability is a Concentration and the words do not plainly say "this turn". A counted effect under a Concentrating
      ability shares that ability's end, which is a deliberate policy and not widened here; a printed "for the rest of the
      turn" that describes this effect alone is shorter than any Concentration, so it is still the words that decide.

    Everything else reads prose for turn semantics, then the turn/scene/unknown kinds and the ability fallback. Missing and
    instant kinds keep the ability fallback. A printed "until the start of your next turn" that an owning talent
    lengthens uses the general ``effect_turns`` hook (see :func:`counted_turns`) and ends at that later turn.
    """
    for low, high, duration in effect.get("duration_by_cl") or []:
        if int(low) <= int(ctx.numbers.get("cl") or 1) <= int(high):
            effect = {**effect, "duration": duration}
    if effect.get("expires_on"):
        return stated_expiry(ctx, effect, subject, condition=condition,
                             modifier_source_actor_id=modifier_source_actor_id)
    duration = effect.get("duration")
    kind = str((duration.get("kind") if isinstance(duration, dict) else duration) or "").strip().lower()
    amount = _clock_amount(ctx, duration, kind)
    if duration_round_count(kind, amount) is not None:
        own_words = _own_words_state_one_lifetime(effect)
        ability = ctx.expires_on()
        if ability == "CONCENTRATION_END" and not (own_words and _bounded_to_this_turn(effect)):
            return ability  # the ability says how long a counted effect of it lasts, whatever its words quote
        if not own_words:
            return clock_expiry(ctx.engine, kind, amount)
    stated = stated_expiry(ctx, effect, subject, condition=condition,
                           modifier_source_actor_id=modifier_source_actor_id)
    if stated:
        return counted_turns(ctx, effect, stated)
    holder = subject or ctx.actor
    turn = duration_turn(kind)
    if turn:
        edge, whose = turn
        return counted_turns(ctx, effect, _turn_expiry(ctx, edge, ctx.actor if whose == "source" else holder, condition=condition,
                                                      modifier_source_actor_id=modifier_source_actor_id))
    if kind in _KIND_THIS_TURN or (kind == "special" and _TRIGGERING.search(f"{effect.get('on') or ''} {effect.get('evidence') or ''}")):
        return "END_OF_CURRENT_TURN"  # "the triggering attack": bounded to the turn it happens in
    if kind == "until_end_of_turn":
        # Mostly the typing's short form of "until the end of your / its next turn": on a creature outside the user's side that
        # is the affected creature's next turn (owner 2026-09-26: "ends with the affected creature's next turn"); on the user
        # and its allies it is this turn, the printed reading of a self-buff.
        own = holder is ctx.actor or holder.team_id == ctx.actor.team_id
        if own or ctx.expires_on() == "END_OF_CURRENT_TURN":
            return "END_OF_CURRENT_TURN"
        return _turn_expiry(ctx, "end", holder, condition=condition,
                            modifier_source_actor_id=modifier_source_actor_id)
    named = rules()["durations"].get(kind)  # any other kind the engine's table names means here what it means for an ability
    if named:  # (until_removed; target_next_turn, which only marks carry, and they read their own duration in block_mark)
        return named
    counted = clock_expiry(ctx.engine, kind, amount)
    if counted:  # counted units share the round clock, unless the ability is Concentration, whose end it shares
        ability = ctx.expires_on()
        return ability if ability == "CONCENTRATION_END" else counted
    return ctx.expires_on() if fallback is _ACTION else fallback


# The engine's own name for "ends at the start of the applier's next turn"; the only one a lengthening talent replaces.
SOURCE_NEXT_START = "START_OF_SOURCE_NEXT_TURN"


def counted_turns(ctx: Context, effect: dict[str, Any], stated: str) -> str:
    """"... normally lasts until the start of your next turn, instead lasts until the start of your second turn after
    the attack": an owning plug-in may count that next turn in the applier's turns, the general ``effect_turns`` hook
    (ctx, the exact effect row) -> a positive number of turns. It only ever moves an applier-next-turn expiry later, so
    no other effect's lifetime can move here, and default-inert: nobody registered leaves every name as it was."""
    if stated != SOURCE_NEXT_START:
        return stated
    from . import ext

    turns = [int(value) for value in ext.run("effect_turns", ctx, effect) if isinstance(value, int) and value > 1]
    if not turns:
        return stated
    from .ext import effect_durations

    return effect_durations.token("start", ctx.actor.entity_id, int(ctx.actor.turns_started) + max(turns))


def _clock_amount(ctx: Context, duration: Any, kind: str) -> Any:
    """How many units of a counted kind: the effect's own amount, else the ability's when it counts in the same unit."""
    if isinstance(duration, dict) and duration.get("amount"):
        return duration["amount"]
    own = ctx.typed.get("duration") or {}
    return own.get("amount") if own.get("kind") == kind else None


_WITHIN_FT = re.compile(r"\bwithin (\d+) (?:feet|ft)\b", re.I)
_ONE_ALLY = re.compile(r"\b(?:one|an|a|another|that|the) (?:ally|allied creature|willing creature|friendly creature)\b", re.I)
_YOU_OR = re.compile(r"\byou or (?:an? |one |another )?(?:ally|allies|creature)", re.I)


def _allies_near(ctx: Context, effect: dict[str, Any]) -> list[ActorState]:
    """An ally effect of an ability not aimed at an ally (fight audit 2026-09-29: Battle Cadence's "one ally within 15 feet
    gains +5 feet Speed" and 101 other self-cast allies' lines -- "Allies inside the Domain gain ..." -- all landed on the
    caster): the nearest ally for "one ally", else every ally, within the printed distance or the ability's own area around
    its user (30 feet when neither is printed). "You or an ally" falls back to the user when no ally is there."""
    from . import ext

    for picked in ext.run("ally_subjects", ctx, effect):
        if picked is not None:
            return list(picked)  # a plug-in that knows who "allies" are for this ability (the Warleader's Shouts)
    text = str(effect.get("evidence") or effect.get("on") or "")
    found = _WITHIN_FT.search(text)
    area = ctx.typed.get("area") or {}
    radius = int(found.group(1)) if found else int(area.get("size_ft") or 0) if area.get("centered_on_self") else 30
    near = sorted((a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor and a.team_id == ctx.actor.team_id
                   and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= radius),
                  key=lambda a: (ctx.engine._distance_actor_to_actor(ctx.actor, a), a.entity_id))
    if near and _ONE_ALLY.search(text) and not re.search(r"\ballies\b", text, re.I):
        near = near[:1]
    return near or ([ctx.actor] if _YOU_OR.search(text) else [])


# ------------------------------------------------------------------ blocks
_BOTH_TYPES = re.compile(r"\band\b", re.I)
_EITHER_TYPE = re.compile(r"\bor\b", re.I)


def damage_choices(effect: dict[str, Any], weapon: dict[str, Any] | None = None) -> list[str]:
    """The damage types the attacker may pick from: "Fire, Necrotic, or Psychic damage", or a "Piercing or
    Slashing" weapon.  "Force and Psychic damage" is both at once, so it keeps the first listed type."""
    if weapon is not None:
        types = weapon.get("damage_types") or [weapon.get("damage_type") or "UNTYPED"]
    else:
        types = effect.get("damage_types") or ["untyped"]
        evidence = str(effect.get("evidence") or "")
        if len(types) > 1 and _BOTH_TYPES.search(evidence) and not _EITHER_TYPE.search(evidence):
            types = types[:1]
    return [str(kind).upper() for kind in types]


def choose_damage_type(ctx: Context, kinds: list[str], targets: list[ActorState]) -> str:
    """Owner 2026-09-26: with a choice of damage types, the attacker picks the one that lands hardest on the
    targets (not a resisted one when another is open; a vulnerable one first); the first listed wins a tie.

    ``damage_type_choices(ctx, kinds) -> list | None`` is the general seam for a printed ability that lets its user
    choose from other types than the ones the row lists (Alchemy's Seven-Flavor Furnace: "When an Alchemy technique
    lets you choose Acid, Fire, Poison, or Force damage, you may choose one of your selected damage types instead"). It
    is asked once, only where the row really offers a choice, and replaces the list the automatic pick chooses among;
    the pick itself, the dice and the recorded damage type are otherwise unchanged. No subscriber is the old behaviour
    exactly.
    """
    from . import ext
    replacements = ext.run_strict("damage_type_override", ctx, tuple(kinds), tuple(targets))
    if replacements:
        if len(replacements) != 1 or not isinstance(replacements[0], str) or not replacements[0]:
            raise ValueError("damage_type_override requires one named type")
        return replacements[0].upper()
    if len(kinds) <= 1:
        return kinds[0] if kinds else "UNTYPED"
    from . import ext

    if ext.has('damage_type_choices'):
        for replacement in ext.run('damage_type_choices', ctx, kinds):
            if replacement:
                kinds = [str(kind).upper() for kind in replacement]
    # A printed player choice may use the transactional extension transport.
    # Absent providers preserve the historical automatic defense-based choice.
    from . import ext
    choices = [kind for kind in ext.run_strict("damage_type_choice", ctx, kinds, targets) if kind is not None]
    if choices:
        if len(choices) != 1 or choices[0] not in kinds:
            raise ValueError("one damage_type_choice owner must return an allowed damage type")
        return choices[0]
    if not targets:
        return kinds[0] if kinds else "UNTYPED"
    from . import typed_reactions

    def landing(kind: str) -> float:
        return sum(typed_reactions.damage_factor(ctx.engine, target, kind, ctx.damage_source, ctx.actor.entity_id) for target in targets)

    return max(kinds, key=lambda kind: (landing(kind), -kinds.index(kind)))


def _damage_dice(ctx: Context, dice: "DiceSpec | FlatAmount | None", effect: dict[str, Any] | None = None,
                 kinds: list[str] | None = None) -> "DiceSpec | FlatAmount | None":
    """Shared damage-roll modifiers for attack sequences and cached damage effects.

    Fixed damage is not a roll. With no contribution return the original dice,
    preserving legacy serialization and event bytes.
    """
    if not isinstance(dice, DiceSpec) or dice.count <= 0 or dice.sides <= 0:
        return dice
    from . import ext

    bonus = sum(value for value in ext.run("damage_roll_bonus", ctx, effect, kinds or []) if type(value) is int)
    return dice.model_copy(update={"modifier": dice.modifier + bonus}) if bonus else dice


def _inherited_damage_type(ctx: Context) -> str | None:
    """The settled damage type of the actor's most recent committed damage against this target.

    General seam: a printed rider whose added damage "follows the attack or
    technique" (Momentum Drive, Dragon-Marrow Drive) takes the type of the hit
    it rides. The hit's damage packet is committed (DAMAGE_COMMITTED, with its
    settled type) before the own-hit reaction that carries the rider runs, so
    the rider reads the type the engine already settled for that hit. None
    when no committed packet of this actor against this target is in the log.
    """
    for event in reversed(ctx.engine.events):
        payload = event.payload or {}
        if event.event_type != "DAMAGE_COMMITTED" or event.actor_id != ctx.actor.entity_id:
            continue
        if ctx.target is not None and ctx.target.entity_id not in (event.target_ids or ()):
            continue
        settled = str(payload.get("damage_type") or "").upper()
        return settled or None
    return None


def _triggering_damage_causes(ctx: Context) -> list[str]:
    """Causes of the incoming packet, including its pre-commit reaction window.

    General seam: a rider whose behaviour names the damage that triggered
    it (Storm-Marrow Guard's 10-foot form) reads the causes the engine
    committed -- the packet's settled damage type and its source, since
    some printed causes (falling) commit under an ordinary type with a
    system source. Lower-cased; empty when no committed packet against
    this actor is in the log. During damage reactions the current immutable
    pending packet takes precedence over history, so an older hit cannot
    determine the response to damage that has not committed yet.
    """
    from .pending_damage import current
    pending = current(ctx.engine)
    if pending is not None:
        if pending.target_id != ctx.actor.entity_id:
            return []
        return [str(cause).strip().lower() for cause in (
            pending.damage_type, pending.source_id, pending.pressure_kind,
            *sorted(pending.source_flags)) if str(cause).strip()]
    for event in reversed(ctx.engine.events):
        if event.event_type != "DAMAGE_COMMITTED" or ctx.actor.entity_id not in (event.target_ids or ()):
            continue
        payload = event.payload or {}
        causes = [str(payload.get("damage_type") or "").strip().lower()]
        source = str(getattr(event, "source_definition_id", "") or "").strip().lower()
        if source:
            causes.append(source)
        return [cause for cause in causes if cause]
    return []


def damage_roll(ctx: Context, effect: dict[str, Any]) -> tuple[int, str]:
    """Public damage-packet roll for native alternate recipients (e.g. objects).

    Reuses typed scaling, declarations, source modifiers and activation cache;
    the caller owns recipient-specific defenses and the evented damage commit.
    """
    return _damage_roll(ctx, effect)


def take_activation_bonus(ctx: Context, name: str) -> int:
    """A flat bonus printed "once per activation" (Qi Technique Potency): its value the first time, 0 after.

    The flag lives in the activation's damage cache, which every strike, packet and on-hit child of one
    activation shares; a stored string key also survives the per-hit cache copies.
    """
    value = int(ctx.numbers.get(name) or 0)
    if not value or ctx.damage_cache.get(f"_{name}_used"):
        return 0
    ctx.damage_cache[f"_{name}_used"] = True
    return value


def _damage_roll(ctx: Context, effect: dict[str, Any]) -> tuple[int, str]:
    """Roll a damage effect once per resolution: every target of an area shares the roll."""
    key = id(effect)
    group = effect.get("damage_bonus_group")
    if group:
        # Optional general compiler seam: area recipients reuse one roll, later strikes/stages cannot
        # spend it again. String keys carry across attacks; no state survives this activation.
        from .effect_eligibility import damage_bonus_slot
        ctx.damage_cache[f"damage_bonus_stage:{group}"] = damage_bonus_slot(ctx, effect)
        key = f"damage_bonus_roll:{group}"
    if key not in ctx.damage_cache:
        # Every target of an area shares one choice of damage type, like the roll (block_save's subjects).
        targets = ctx.damage_cache.get("_area_targets") or list(ctx.targets) or ([ctx.target] if ctx.target else [])
        resolved_type = effect.get("resolved_damage_type")
        if resolved_type is not None:
            if not isinstance(resolved_type, str) or not resolved_type.strip():
                raise ValueError("resolved_damage_type requires a nonempty named type")
            resolved_type = resolved_type.upper()
        if effect.get("weapon_damage"):
            weapon = ctx.typed.get("weapon") or {}
            dice = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
            damage_type = resolved_type or choose_damage_type(ctx, damage_choices(effect, weapon), targets)
        else:
            spec = _effect_dice(ctx, effect)
            dice = ctx.dice(spec, flat=int(effect.get("flat") or 0) + take_activation_bonus(ctx, "potency"), formula=effect.get("formula"))
            # inherit_damage_type: the added damage takes the triggering hit's settled type
            # (_inherited_damage_type), not a fixed list of its own.
            inherited = _inherited_damage_type(ctx) if effect.get("inherit_damage_type") else None
            damage_type = resolved_type or inherited or (choose_damage_type(ctx, damage_choices(effect), targets) if effect.get("damage_types") else "UNTYPED")
        kinds = damage_choices(effect, ctx.typed.get("weapon") or {}) if effect.get("weapon_damage") else damage_choices(effect)
        # The roll's RESOLVED damage type is recorded around the modifier fold, exactly as at the attack fold point
        # below: a printed row may offer a choice ("6d8 Radiant or Necrotic damage, your choice"), and only the
        # chosen type is what the dice will carry.  A subscriber that adds a printed bonus to this roll ("add your
        # Proficiency Bonus to one damage roll" -- Death, Mark for the Grave) therefore reads
        # combat/typed_executor._typed_pending_damage_type instead of guessing from the printed rows, which would
        # refuse every row that offers a choice.  General: the value is restored at once, so nothing outside the hook
        # sees it and no recorded event changes.
        folded_type = getattr(ctx.engine, "_typed_pending_damage_type", None)
        ctx.engine._typed_pending_damage_type = damage_type
        try:
            spec = _damage_dice(ctx, dice, effect, kinds)
            recorded = len(ctx.engine.rolls)
            total = _roll(ctx, spec, "DAMAGE", critical=ctx.critical_hit, damage_label=effect.get("damage_label"))
            total += _rerolled_damage_dice(ctx, spec, effect, kinds, recorded)
        finally:
            ctx.engine._typed_pending_damage_type = folded_type
        ctx.damage_cache[key] = (total, damage_type)
    # Delivery can use a cached roll without dispatching its damage row (save
    # for half). Roll-dependent riders therefore bind here on every retrieval,
    # not only while first rolling or inside effect_resolution_scope.
    from . import ext

    ext.run_strict("damage_roll_resolved", ctx, effect, key)
    return ctx.damage_cache[key]


def _rerolled_damage_dice(ctx: Context, dice: "DiceSpec | FlatAmount", effect: dict[str, Any] | None,
                          kinds: list[str], recorded: int) -> int:
    """Damage dice an owner rerolled and then used the new rolls for, as a signed adjustment to this packet.

    The general seam (``damage_dice_reroll``): one answer per packet. An int is how many of the packet's own dice
    the owner rerolls, clamped to the dice it actually rolled; a dict may also carry ``{"bonus": int}``, a flat
    amount added to the same packet when the reroll was taken (one printed sentence often pays both halves, so the
    owner answers once and the engine does not ask twice). The new dice come from the same deterministic stream and
    the same die size, are recorded as their own roll so a replay draws exactly what the fight drew, and replace that
    many of the packet's lowest dice -- "Reroll a number of damage dice up to your Proficiency Bonus and use the
    new rolls" (Blacksmith Seven-Hammer Revision). No subscriber means no extra draw and no change at all.
    """
    if not isinstance(dice, DiceSpec) or dice.count <= 0 or dice.sides <= 0:
        return 0
    from . import ext

    original = ctx.engine.rolls[recorded] if len(ctx.engine.rolls) > recorded else None
    actual_count = len(original.dice) if original is not None else dice.count
    answers = [value for value in ext.run("damage_dice_reroll", ctx, effect, kinds or [], actual_count)
               if type(value) is int or isinstance(value, dict)]
    counts = [value if type(value) is int else int(value.get("reroll") or 0) for value in answers]
    count = max([0, *(min(int(value), actual_count) for value in counts if int(value) > 0)], default=0)
    bonus = max([0, *(int(value.get("bonus") or 0) for value in answers if isinstance(value, dict))], default=0)
    if count <= 0:
        return 0
    rerolled = ctx.engine.roller.roll(DiceSpec(count=count, sides=dice.sides, modifier=0), actor_id=ctx.actor.entity_id,
                                      reason=f"DAMAGE_REROLL:{ctx.damage_source}")
    ctx.engine._record_roll(rerolled)
    ctx.engine._append_event("DAMAGE_ROLLED", ctx.damage_source, actor_id=ctx.actor.entity_id,
                             target_ids=tuple(t.entity_id for t in ctx.targets),
                             payload={**rerolled.model_dump(mode="json"), **ctx.damage_metadata(),
                                      "rerolled_dice": count, "reroll_bonus": bonus,
                                      "damage_label": effect.get("damage_label")})
    replaced = sorted((original.dice if original is not None else ()) or ())[:count]
    return int(rerolled.total) - sum(replaced) + bonus


def _deal(ctx: Context, subject: ActorState, amount: int, damage_type: str, *, divisor: int = 1) -> None:
    """Deliver a full roll plus recipient bonuses, then apply its save/Evasion divisor."""
    with _defeat_chain(ctx):
        _deal_in_chain(ctx, subject, amount, damage_type, divisor=divisor)


def _deal_in_chain(ctx: Context, subject: ActorState, amount: int, damage_type: str, *, divisor: int = 1) -> None:
    if ((subject.active or ctx.continue_after_defeat)
            and (ctx.engine.state.terminal_result is None or ctx.continue_after_defeat
                 or getattr(ctx.engine, "_final_rider_active", False))):
        hp_before = subject.current_hp
        first_event = len(ctx.engine.events)
        # Owner 2026-09-26 ("make sure the mechanics aren't damaged"): the sealed _commit_damage does
        # not pass its damage_type through to typed_reactions.on_damage, so a "take Fire damage"-style
        # limit can't be checked there unless this non-sealed code records it first. Saved/restored
        # rather than just cleared, so a reaction's own nested damage (fired from inside this same
        # commit) never clobbers the type an outer, still-in-progress commit needs afterward.
        previous = getattr(ctx.engine, "_typed_pending_damage_type", None)
        previous_packet = getattr(ctx.engine, "_typed_damage_packet", None)
        # Standalone damage is not the enclosing attack's projectile packet.
        ctx.engine._typed_damage_packet = None
        ctx.engine._typed_pending_damage_type = damage_type
        # The same seam for the delivery identity, so a printed "damage from a trap / a fall / an
        # area's own hazard" limit is checkable the same way a damage-TYPE limit is
        # (combat/ext/damage_delivery.py; read by combat/ext/source_sphere.py). It names this
        # delivery's identity and the source its own Context carries, which is the string the
        # delivery site opened the frame with, so a trap's own dart and an area's own damage keep
        # that hazard; any other source committing inside that frame (a Reaction's own return) is a
        # delivery of its own and inherits none of it. The frame is put back with the type for the
        # same nested-damage reason.
        previous_source = _delivery.open_frame(ctx.engine, ctx.damage_source, continues=_delivery_source(ctx))
        try:
            # General per-recipient seam (combat/ext "deal_bonus"). An area rolls its damage
            # ONCE for every creature in it, so a printed bonus that names one creature cannot
            # live in that shared roll; a plug-in adds it to that one subject's amount here,
            # after the roll and before the commit. No subscriber leaves the amount untouched.
            from . import ext as _ext
            if _ext.has("deal_bonus"):
                amount += sum(int(value) for value in _ext.run("deal_bonus", ctx, subject, amount)
                              if type(value) is int)
            # Reduce the combined amount once, preserving rounding and the shared cached roll.
            amount //= divisor
            provenance = ctx.attack_damage_context
            # Inherited hit metadata belongs only to its original packet.
            # A named bonus can replace the action (Demon Mark, Forms, etc.);
            # that separate damage must not masquerade as the triggering hit.
            if provenance is not None and (
                    provenance.source_id != ctx.damage_source
                    or provenance.attacker_id != ctx.actor.entity_id
                    or provenance.target_id != subject.entity_id):
                provenance = None
            if provenance is not None:
                from dataclasses import replace
                provenance = replace(provenance, component='rider')
            from .ext.attack_defenses import packet_defenses

            from .save_context import damage_scope

            with packet_defenses(ctx.engine, ctx.attack_defense_spec), damage_scope(ctx, subject):
                ctx.engine._commit_damage(subject, amount, damage_type, ctx.damage_source, ctx.actor.entity_id, ctx.intent,
                    reaction_depth=0, attack_context=provenance, source_flags=ctx.damage_source_flags,
                    pressure_kind=ctx.damage_pressure_kind)
        finally:
            ctx.engine._typed_pending_damage_type = previous
            ctx.engine._typed_damage_packet = previous_packet
            _delivery.close_frame(ctx.engine, previous_source)
        for event in ctx.engine.events[first_event:]:
            if (event.source_definition_id == ctx.damage_source and event.actor_id == ctx.actor.entity_id
                    and subject.entity_id in event.target_ids):
                event.payload.update(ctx.damage_metadata())
        if not ctx.defer_damage_notifications:
            _notify_damage_dealt(ctx, subject, first_event)
        damaged = any(event.event_type == "DAMAGE_COMMITTED"
                      and event.source_definition_id == ctx.damage_source
                      and event.actor_id == ctx.actor.entity_id and subject.entity_id in event.target_ids
                      and int(event.payload.get("hp_damage") or 0)
                      + int(event.payload.get("temporary_hp_absorbed") or 0) > 0
                      for event in ctx.engine.events[first_event:])
        _after_own_blow(ctx, subject, was_active=True, hp_before=hp_before, damaged=damaged)


def _notify_damage_dealt(ctx: Context, subject: ActorState, first_event: int) -> None:
    """Report actual damage by this action, including absorbed temporary HP, after reactions.

    The packets behind the total ride along as ``ctx.damage_packets``, so a subscriber that reacts to a damage
    type (Eat the Flame's Fire) still sees a packet that its own attack's rider attached earlier in the same hit.
    """
    from . import ext

    if not ext.has("damage_dealt"):
        return
    packets = tuple(dict(event.payload) for event in ctx.engine.events[first_event:]
                    if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == ctx.damage_source
                    and event.actor_id == ctx.actor.entity_id and subject.entity_id in event.target_ids)
    amount = sum(int(packet.get("hp_damage") or 0) + int(packet.get("temporary_hp_absorbed") or 0) for packet in packets)
    if amount > 0:
        ext.run_strict("damage_dealt", replace(ctx, damage_packets=packets), subject, amount)


@contextmanager
def _defeat_chain(ctx: Context):
    """Share notifications across effects, after-hit riders and reaction damage.

    New reaction Contexts join the engine's active chain. Only its outermost
    damage/effect resolver clears it, including when a consent preview raises.
    This is transient resolution state; nothing is stored in a saved fight.
    """
    previous = getattr(ctx.engine, "_typed_defeat_chain", None)
    scope = previous if previous is not None else ctx.defeat_notification_scope
    local_scope = ctx.defeat_notification_scope
    ctx.defeat_notification_scope = scope
    ctx.engine._typed_defeat_chain = scope
    try:
        yield
    finally:
        ctx.defeat_notification_scope = local_scope
        if previous is None:
            ctx.engine.__dict__.pop("_typed_defeat_chain", None)
            scope["drop"].clear()
            scope["own_kill"].clear()


# ----------------------------------------------------------------- one resolution "moment"
# A moment is one player-visible resolution: an action, a save, a zone pulse or a reaction.
# Nested damage, on-hit riders and reaction prompts all resolve inside the same moment, and
# like ``_defeat_chain`` only the outermost ``run_effects`` opens and closes it.
#
# Once-per-turn riders spend their allowance per turn, and the turn is identified by
# ``round:slot:current actor:turns_started`` (see ``_on_hit_bonuses``). That identity is
# mutable while a resolution is still in flight -- a reaction that grants an isolated turn,
# or an advance of the initiative slot between two damage components of one hit -- so the
# turn flag alone let the same rider fire twice on one target inside a single moment
# (Demon Mark's "once per turn when you damage it, add Proficiency Bonus to the damage").
# A rider also records the moment it fired in, keyed by target, so one moment can never
# spend it twice on the same creature while several distinct creatures may each trigger it.
# The record is transient resolution state and is never stored in a saved fight.
@contextmanager
def _moment_scope(ctx: Context):
    engine = ctx.engine
    if getattr(engine, "_typed_moment", None) is not None:
        yield  # a nested resolution shares the moment already in flight
        return
    engine._typed_moment = set()
    try:
        yield
    finally:
        engine.__dict__.pop("_typed_moment", None)


def _moment_already_spent(engine: Any, actor_id: str, key: str, target_id: str) -> bool:
    """True when this rider already fired on this target during the moment in flight.

    False outside a moment (``_on_hit_bonuses`` reached without a resolution scope), where
    the per-turn flag alone governs. Only ever withholds a rider: it can never let one
    fire that the turn flag had already spent.
    """
    moment = getattr(engine, "_typed_moment", None)
    if moment is None:
        return False
    spent = (actor_id, key, target_id)
    if spent in moment:
        return True
    moment.add(spent)
    return False


def _after_own_blow(ctx: Context, subject: ActorState, *, was_active: bool,
                    hit: bool = False, ranged: bool | None = None, hp_before: int = 0,
                    damaged: bool = False) -> None:
    with _defeat_chain(ctx):
        _after_own_blow_in_chain(ctx, subject, was_active=was_active, hit=hit, ranged=ranged,
                                 hp_before=hp_before, damaged=damaged)


def _after_own_blow_in_chain(ctx: Context, subject: ActorState, *, was_active: bool,
                             hit: bool = False, ranged: bool | None = None, hp_before: int = 0,
                             damaged: bool = False) -> None:
    """The actor's own hit or kill (owner 2026-09-26: "we need the different resources to be generated"), for
    generation triggers such as "after you hit a hostile creature" or "when you reduce a creature to 0 HP".

    ``damaged`` is opt-in from a delivery's positive committed HP/temporary-HP loss.
    A missed attack supplies neither hit nor damaged; damage without an attack supplies only damaged.
    """
    if subject is None or ctx.engine.state.terminal_result is not None:
        return
    fresh_zero = was_active and hp_before > 0 and subject.current_hp == 0
    if fresh_zero:
        # "When it drops to 0 HP" watches the marked creature whoever brings it down (Astra's audit, 2026-09-26:
        # an ally's kill granted Demon Mark's marker no Devoured Essence).
        if subject.entity_id not in ctx.defeat_notification_scope["drop"]:
            ctx.defeat_notification_scope["drop"].add(subject.entity_id)
            run_kill_watches(ctx.engine, subject)
            from . import typed_reactions

            typed_reactions.on_creature_event(ctx.engine, subject, "any_drop_to_zero")  # "a creature within 60 feet drops to 0"
    if subject.team_id == ctx.actor.team_id:
        return
    from . import typed_reactions

    if damaged and not hit and was_active and not ctx.damage_cache.get("_bonus"):
        # Damage without an attack (save, zone, etc.) can trigger damage riders too.
        # An attack miss also calls this helper with hit=False, but supplies no damage.
        # Only a positive committed packet, including temporary HP loss, grants this trigger.
        _on_hit_bonuses(ctx, subject, {}, "", damage_only=True)
    if hit:
        typed_reactions.on_own_event(ctx.engine, ctx.actor, subject, "own_hit", ranged=ranged,
                                    source_id=ctx.source, action_name=ctx.action.display_name)
        from . import pressure

        pressure.after_hit(ctx.engine, ctx.actor, subject, ranged=bool(ranged))  # Golden Sea Pulse from a close hit
    if fresh_zero and subject.entity_id not in ctx.defeat_notification_scope["own_kill"]:
        ctx.defeat_notification_scope["own_kill"].add(subject.entity_id)
        typed_reactions.on_own_event(ctx.engine, ctx.actor, subject, "own_kill", source_id=ctx.source,
                                    action_name=ctx.action.display_name)


def run_kill_watches(engine: Any, fallen: ActorState) -> None:
    """Every "when it drops to 0 HP" watch bound to ``fallen``, whoever holds it."""
    for watcher in list(engine.state.actors.values()):
        for mid, modifier in list(watcher.modifiers.items()):
            if modifier.target_field != "typed_watch" or mid not in watcher.modifiers:
                continue
            kind, bound, evidence = (str(modifier.value).split("|", 2) + ["", ""])[:3]
            if kind != "own_kill" or bound != fallen.entity_id:
                continue
            del watcher.modifiers[mid]  # nothing left to watch
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=watcher.entity_id,
                                 target_ids=(watcher.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})
            _run_watched(engine, watcher, fallen, modifier.source_definition_id, evidence)


def damage_effect_context(ctx: Context, effect: dict[str, Any]) -> Context:
    """Packet metadata shared by full and save-for-half typed damage delivery.

    Explicit producer kinds are preserved, including unknown kinds. Soul Drain
    and Returning Source Guard use the drain contract; ordinary rows are inert.
    """
    delivery = replace(ctx, damage_source_flags=(*ctx.damage_source_flags, 'bypass_temporary_hp')) if effect.get('bypass_temporary_hp') is True else ctx
    if effect.get('pressure_kind') is not None:
        kind = effect['pressure_kind']
        if not isinstance(kind, str) or not kind:
            raise ValueError('Damage pressure_kind must be an explicit nonempty name')
        delivery = replace(delivery, damage_pressure_kind=kind)
    return delivery


def block_damage(ctx: Context, effect: dict[str, Any]) -> None:
    per_fight = effect.get("once_per_fight")
    if per_fight:  # a turn flag with "_round_" in its key survives turn resets: once per fight (Hidden Method)
        flag = f"typed_round_once:{per_fight}"
        if ctx.actor.turn_flags.get(flag):
            return
        ctx.actor.turn_flags[flag] = True
    once = effect.get("once_per_turn")
    if once:  # Explicit per-turn gates clear at the start of every creature's turn.
        flag = f"typed_once_turn:{once}"
        if ctx.actor.turn_flags.get(flag):
            return
        ctx.actor.turn_flags[flag] = True
    amount, damage_type = _damage_roll(ctx, effect)
    subjects = _default_subject(ctx, effect, harmful=True)
    with simultaneous(ctx, subjects):
        for subject in subjects:
            delivery = damage_effect_context(ctx, effect)
            _deal(delivery, subject, amount, damage_type, divisor=ctx.damage_divisor)


def block_half_damage(ctx: Context, effect: dict[str, Any]) -> None:
    """Handled by block_save: a successful save halves the failed branch's damage."""


def _half_save_damage(ctx: Context, effects: list[dict[str, Any]]) -> None:
    """Save-for-half and failed Evasion preserve normal dispatch for relocated bonuses.

    Scale delivery, not the row or cached roll: mixed area outcomes share the full roll.
    Unmarked historical base rows keep their existing direct save resolution.
    """
    from .effect_eligibility import damage_bonus_available

    for row in effects:
        # extra_damage is dispatched by the same block_damage as damage, so a
        # successful save owes it half too (forge-design converted saves carry
        # portable extra-damage payloads; no authority row pairs it with
        # half_damage today, so existing records are unaffected).
        if row.get("type") not in ("damage", "extra_damage"):
            continue
        if row.get("damage_bonus_packet") or row.get("bypass_temporary_hp") is True:
            run_effects(replace(ctx, damage_divisor=2), [row])
        elif damage_bonus_available(ctx, row):
            amount, damage_type = _damage_roll(ctx, row)
            delivery = damage_effect_context(ctx, row)
            _deal(delivery, ctx.target, amount, damage_type, divisor=2)


def _run_before_save_damage(ctx: Context, effects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run explicitly marked save consequences before any successful-save damage is delivered."""
    before = [row for row in effects if row.get("before_save_damage") is True]
    if before:
        run_effects(ctx, before)
    return [row for row in effects if row.get("before_save_damage") is not True]


def _size_purposes(effects: list[dict[str, Any]]) -> set[str]:
    from .ext.effective_size import purposes_of

    return purposes_of(effects)


def _size(ctx: Context, actor: ActorState, role: str, purposes: set[str]) -> int:
    """A creature's size in squares for one size limit: its footprint width plus any "count as N sizes larger" that applies
    (combat/ext/effective_size.py; the size_steps hook). No purposes, or no step, = the plain footprint width."""
    if not purposes:
        return int(ctx.engine._footprint(actor).width_cells)
    from .ext.effective_size import cells

    return cells(ctx.engine, actor, role, scoped_size_purposes(ctx, role, purposes))


def scoped_size_purposes(ctx: Context, role: str, purposes: set[str]) -> set[str]:
    """Qualified purposes shared by absolute-width and relative-rank queries."""
    from . import ext
    scoped = set(purposes)
    for extra in ext.run_strict("size_context_purposes", ctx, role, frozenset(purposes)):
        scoped.update(extra)
    return scoped


def _size_rank(ctx: Context, actor: ActorState, role: str, purposes: set[str]) -> int:
    from .ext.effective_size import rank
    return rank(ctx.engine, actor, role, scoped_size_purposes(ctx, role, purposes))


def size_rank(ctx: Context, creature: ActorState, role: str, effect: dict[str, Any]) -> int:
    """Public relative-category comparison, preserving qualified size steps."""
    purposes = _size_purposes([effect]) if effect else {"comparison"}
    return _size_rank(ctx, creature, "act" if role == "actor" else "resist", purposes)


def size_width(ctx: Context, creature: ActorState, role: str, effect: dict[str, Any]) -> int:
    """Public compatibility helper for Sumo/Elephant size comparisons.

    All size steps use the documented engine/role/purposes hook. Empty effect
    comparisons retain physical size grants, without inventing a shove/grapple.
    """
    purposes = _size_purposes([effect]) if effect else {"comparison"}
    return _size(ctx, creature, "act" if role == "actor" else "resist", purposes)


def typed_save_modifiers(ctx: Context, subject: ActorState, choice: str,
                         fail_effects: list[dict[str, Any]], success_effects: list[dict[str, Any]], *, categories: list[str] | None = None):
    """Shared pending-save modifiers/metadata for block saves and defending contests."""
    from .ext.save_damage import has_damage

    from . import typed_reactions

    # R4: "a creature within 60 feet is about to resolve a saving throw" -- a bonus or penalty, Advantage or Disadvantage.
    # Custom effect rows may describe their consequences with ``pending_effects``
    # when the effect itself applies them after a failed save. This keeps
    # pending-save reactions informed without executing those rows twice.
    pending_rows = list(_walk_rows(fail_effects))
    for row in tuple(pending_rows):
        pending_rows.extend(_walk_rows(row.get("pending_effects") or []))
    # An ongoing/repeating condition is the same pending consequence as an
    # immediate condition. Its actual declared condition names the save; no
    # action title, affinity or unrelated row supplies classification.
    named = {str(row.get("condition") or "").lower() for row in pending_rows
             if row.get("type") in {"condition", "ongoing"} and row.get('condition') not in (None, '', 'none')}
    # Save hooks receive only this save's possible failure consequences. This
    # prevents a spatial branch elsewhere in the action from affecting it.
    def pending_spatial(rows):
        for item in _walk_rows(rows):
            kind = item.get("spatial_transport")
            if kind in {"banishment", "pocket_entry", "possession", "planar_travel", "unwilling_teleport"}:
                return True
            if item.get("type") == "spatial_absence" and item.get("applies_to") == "target":
                return True
            if (item.get("type") == "teleport" or item.get("type") == "movement" and item.get("mode") == "teleport") and item.get("applies_to") == "target" and item.get("unwilling") is not False:
                return True
        return False
    # What the effect would do to it, for a reaction that answers only some saves (Yang's Complete Resolve: "an effect that would reduce
    # its Speed, prevent it from taking Reactions, ..."); a Speed cut or a denied Reaction is an effect row, not a condition row.
    does = named | {"reaction_denied" for row in pending_rows if row.get("type") == "reaction_denied"} \
        | {"speed_reduced" for row in pending_rows if row.get("type") == "speed" and (
            row.get("halved") or row.get("becomes") is not None or int((row.get("amount") if row.get("amount") is not None else row.get("flat")) or 0) < 0)}
    shaped = typed_reactions.on_d20_pending(ctx.engine, subject, "save", ability=choice, conditions=does)
    from . import pressure

    # Saint-Body Frame: +PB once a round against what tries to seize the body (forced movement, Prone, Grappled ...).
    pressed, pressed_by = pressure.save_bonus(ctx.engine, subject, choice, named | ({"forced_movement"} if any(
        row.get("type") == "forced_movement" for row in _walk_rows(fail_effects)) else set()))
    if pressed:
        shaped = {**shaped, "bonus": int(shaped["bonus"]) + pressed}
    if pressure.save_advantage(ctx.engine, subject, choice, named):
        shaped = {**shaped, "modes": [*shaped["modes"], "ADVANTAGE"]}  # Tempered Flesh, Meridian Reinforcement
    from . import ext

    # A damage row whose type is already fixed ("damage_types" holds one) is named to the plug-ins as "damage:<type>"
    # (Grounding Breath: saves against lightning or thunder damage); a row that still chooses its type is not.
    plug_in_named = named | ({"forced_movement"} if any(row.get("type") == "forced_movement" for row in _walk_rows(fail_effects)) else set()) \
        | ({"damaging_save"} if has_damage([*fail_effects, *success_effects]) else set()) \
        | {f"damage:{str(row['damage_types'][0]).lower()}" for row in _walk_rows(fail_effects)
           if row.get("type") == "damage" and len({str(kind).lower() for kind in row.get("damage_types") or []}) == 1}
    # Explicit printed save provenance; absent metadata retains legacy semantics.
    if categories is not None:
        if not isinstance(categories, list) or any(not isinstance(tag, str) or not tag for tag in categories):
            raise ValueError("save_categories must be a list of nonempty strings")
        plug_in_named |= {"category:" + tag for tag in categories}
    # Explicit packet producers describe the pressure this save resists. A
    # school, damage type, action name or unrelated owned talent is not proof.
    plug_in_named |= {'pressure:' + row['pressure_kind'] for row in pending_rows
                      if row.get('type') in {'damage', 'extra_damage'}
                      and isinstance(row.get('pressure_kind'), str) and row['pressure_kind']}
    for kinds in ext.run_strict('save_pressure_kinds', ctx, subject, choice, frozenset(plug_in_named)):
        if not isinstance(kinds, (tuple, list, set, frozenset)) or any(
                not isinstance(kind, str) or not kind for kind in kinds):
            raise ValueError('save_pressure_kinds must return explicit nonempty kind names')
        plug_in_named |= {'pressure:' + kind for kind in kinds}
    if pending_spatial(fail_effects):
        plug_in_named.add("unwilling_spatial_transport")
    support_sources = []
    ctx.save_support_sources = support_sources
    for extra in ext.run("save", ctx, subject, choice, plug_in_named):
        shaped = {**shaped, "bonus": int(shaped["bonus"]) + int(extra.get("bonus") or 0), "modes": [*shaped["modes"], *(extra.get("modes") or [])]}
        for source in extra.get('support_sources') or []:
            if (not isinstance(source, dict) or set(source) != {'actor_id', 'source_id'}
                    or any(not isinstance(value, str) or not value for value in source.values())):
                raise ValueError('save support requires actor_id and source_id')
            if source not in support_sources:
                support_sources.append(dict(source))
    # Freeze only this save's real reader contributions. Nested/subsequent saves
    # receive their own list, and final outcome subscribers receive no guesses.
    ctx.save_support_sources = support_sources
    # Opt-in consequence metadata for native d20 consumers. Existing saved
    # actions keep their old condition-only roll context without a provider.
    # Restrict replies to tags already established by the pending branches.
    for tags in ext.run_strict("save_roll_tags", ctx, subject, choice, frozenset(plug_in_named)):
        if not isinstance(tags, (list, tuple, set, frozenset)) or any(
                not isinstance(tag, str) or tag not in plug_in_named for tag in tags):
            raise ValueError("save_roll_tags must return established pending-save tags")
        named = named | set(tags)
    # Outcome-aware subscribers see only this save's own branches and recipient.
    for extra in ext.run("save_effects", ctx, subject, choice, fail_effects, success_effects, categories or []):
        shaped = {**shaped, "bonus": int(shaped["bonus"]) + int(extra.get("bonus") or 0), "modes": [*shaped["modes"], *(extra.get("modes") or [])]}
    return shaped, named, plug_in_named, pressed


def settle_typed_save(ctx: Context, subject: ActorState, choice: str, roll: RollRecord | None, failed: bool,
                      named: set[str], plug_in_named: set[str], pressed: int) -> bool:
    """Notify the staged save outcome, then settle any later reaction override.

    Native d20 rewrites may already have forced the outcome without changing
    the roll total. Consume that receipt before outcome-dependent listeners;
    listeners may still stage a new override during ordinary save reactions.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_roll_outcome")
    from . import ext, typed_reactions, pressure

    override = (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).pop(subject.entity_id, None)
    if override in ("success", "failure"):
        failed = override == "failure"
    typed_reactions.after_d20(ctx.engine, subject, "save", success=not failed, natural=getattr(roll, "natural_result", None),
                              other=ctx.actor, ability=choice, conditions=named)
    typed_reactions.on_creature_event(ctx.engine, subject, "creature_save_failed" if failed else "creature_save_succeeded")
    if pressed:
        pressure.after_pressure_save(ctx.engine, subject)  # an eligible Saint-Body Frame roll generates a Pulse
    ext.run("after_save", ctx, subject, choice, plug_in_named, failed)
    if failed and ctx.typed.get("unarmed_option") and subject.active:
        open_guard(ctx, subject, damaged=False)  # Iron Fist: a failed save against the Grapple or Shove option Opens it
    override = (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).pop(subject.entity_id, None)
    if override in ("success", "failure"):
        if failed and override == "success":
            # The original providers did not prevent this failure. An opaque
            # independent rescue cannot inherit their support attribution.
            ctx.save_support_sources = []
        failed = override == "failure"  # R6: Unbroken Brace, Steal the Decisive Moment, Rewrite Fate
    ext.run("after_save_resolved", ctx, subject, choice, plug_in_named, failed)
    ext.run_strict("save_final", replace(ctx, save_result=roll), subject, choice, plug_in_named, failed)
    return failed


def block_save(ctx: Context, effect: dict[str, Any]) -> None:
    subjects = save_subjects(ctx, effect)
    with simultaneous(ctx, subjects):
        _save_each(ctx, effect, subjects)


def _save_each(ctx: Context, effect: dict[str, Any], subjects: list[ActorState]) -> None:
    from . import ext, typed_reactions

    ability = str(effect.get("ability") or "con").upper()
    dc = int(ctx.numbers.get("save_dc") or 10)
    if effect.get("basis"):
        # A printed save DC named by basis ("your Cultivation Save DC"): the general
        # save_dcs seam resolves it from the caster's own sealed numbers, so a typed
        # save never silently falls back to the action's default Save DC.
        from .save_dcs import save_dc as _basis_save_dc

        dc = _basis_save_dc(ctx.engine, ctx.actor, str(effect["basis"]))
    # Keep the declared branches immutable. Marked pre-damage consequences are
    # consumed per recipient below, so an area save cannot consume them for the
    # remaining subjects.
    fail_branch = effect.get("on_fail") or []
    success_branch = effect.get("on_success") or []
    fail_effects = fail_branch
    success_effects = success_branch
    halves = any(row.get("type") == "half_damage" for row in success_effects)
    ctx.damage_cache.setdefault("_area_targets", list(subjects))
    for subject in subjects:
        fail_effects = fail_branch
        success_effects = success_branch
        if not subject.active or (ctx.engine.state.terminal_result is not None
                                  and not getattr(ctx.engine, "_final_rider_active", False)):
            continue
        if effect.get("max_size_larger") is not None and size_rank(ctx, subject, "subject", effect) > \
                size_rank(ctx, ctx.actor, "actor", effect) + int(effect["max_size_larger"]):
            continue  # trip, grapple or pull: no more than one size larger than you (2024 grapple and shove)
        if effect.get("max_size_cells") and size_width(ctx, subject, "subject", effect) > int(effect["max_size_cells"]):
            continue  # "One Large or smaller creature" (Weight): a Large creature is 2 squares wide
        if effect.get("min_size_larger") is not None and size_rank(ctx, subject, "subject", effect) <= \
                size_rank(ctx, ctx.actor, "actor", effect) + int(effect["min_size_larger"]) - 1:
            continue  # the other half of a size split: only a creature at least this many sizes larger (Draw the Line's Pull save)
        from . import ext
        if any(result is False for result in ext.run("effect_subject_allowed", ctx, effect, subject)):
            continue
        # "cannot affect creatures immune to the Charmed condition" (Turn the Blade Aside; rider lane 3, 2026-09-29), and a creature a plug-in
        # says is immune to this ability from this user for now (combat/ext hook "save_gate": Beauty Beyond Form's 24 hours).
        if effect.get("skip_if_immune") and condition_immune(ctx.engine, subject, str(effect["skip_if_immune"])):
            continue
        if ext.has("save_gate") and ext.any_false("save_gate", ctx, subject):
            continue
        automatic = any(reply is True for reply in ext.run_strict("automatic_save_success", ctx, subject, effect))
        # "STR_OR_DEX": the target uses its better one (a 2024 grapple, the rope dart's Grapple).
        choice = max(ability.split("_OR_"), key=lambda option: subject.saving_throws.get(option, 0)) if "_OR_" in ability else ability
        # Opt-in target-owned decisions; unflagged saved actions retain the old selector.
        options = ability.split("_OR_")
        for selected in ([] if automatic else ext.run("save_choice", ctx, subject, effect, options)):
            if selected in options:
                choice = selected
                break
        # Pinning Method: "A creature more than one size larger than you has Advantage on this save."
        bigger = effect.get("advantage_if_larger") is not None and size_rank(ctx, subject, "subject", effect) > \
            size_rank(ctx, ctx.actor, "actor", effect) + int(effect["advantage_if_larger"])
        # Fists Ring Like Bells: "Creatures already Opened by you have Disadvantage on the saving throw" -- a mark
        # already borne by the subject changes *this* save's mode, the same shape as advantage_if_larger above
        # (owner 2026-09-28, auto-ironclad: this was previously only a GM-only rider, never mechanically applied).
        marked_disadvantage = bool(effect.get("disadvantage_if_marked")) and _bore_mark(ctx, subject, ctx.actor.entity_id, str(effect["disadvantage_if_marked"]))
        # Headsman's Red Line: "Creatures immune to Frightened have Advantage on the saving throw" (rider lane 3, 2026-09-29).
        immune_advantage = bool(effect.get("advantage_if_immune")) and condition_immune(ctx.engine, subject, str(effect["advantage_if_immune"]))
        # Dragon-Felling Chop: "If the target is mounted ... it has Disadvantage on the save" (a condition the subject bears, by name).
        marked_disadvantage = marked_disadvantage or (bool(effect.get("disadvantage_if_condition")) and any(
            c.condition_id == f"condition:typed.{effect['disadvantage_if_condition']}" for c in subject.conditions.values()))
        # "Unclean creatures have Disadvantage on the saving throw" (rider lane C12): a printed creature kind, read by the shared
        # classification in combat/ext/creature_kinds.py (unlabelled creatures never match). Absent key: unchanged.
        if effect.get("disadvantage_if_kind"):
            from .ext import creature_kinds

            marked_disadvantage = marked_disadvantage or creature_kinds.matches(subject, effect["disadvantage_if_kind"])
        shaped, named, plug_in_named, pressed = typed_save_modifiers(ctx, subject, choice, fail_effects, success_effects, categories=effect.get("save_categories")) if not automatic else ({"bonus": 0, "modes": []}, set(), set(), 0)
        modes = {*shaped["modes"], *(["ADVANTAGE"] if bigger or immune_advantage else []), *(["DISADVANTAGE"] if marked_disadvantage else [])}
        if "ADVANTAGE" in modes and any(str(choice).upper() in (row.get("no_save_advantage") or []) for row in condition_rules(subject)):
            modes.discard("ADVANTAGE")  # Meridian Snare's Breath Line: "cannot benefit from Advantage on Constitution saving throws"
        mode = None if len(modes) != 1 else next(iter(modes))
        area = ctx.typed.get("area") or {}
        aim = ctx.damage_cache.get("_checkpoint_aim")
        from .action_geometry import valid, record_for
        origin = record_for(ctx.engine, ctx.actor, ctx.source)
        target_check = (lambda: valid(ctx.engine, ctx.actor, ctx.action) and subject in _area_targets(ctx.engine, ctx.actor, aim, area)) if area.get("size_ft") else \
            (lambda: ctx.engine._target_in_range(ctx.actor, subject, ctx.action))
        if ctx.save_geometry is not None:
            geometry = ctx.save_geometry
            target_check = lambda: any(
                ctx.engine._distance_actor_to_actor(ctx.engine.state.actors[who], subject) <= geometry["range_ft"]
                for who in geometry["origin_ids"] if who in ctx.engine.state.actors)
        if automatic:
            ctx.save_support_sources = []
            # Delivery has already selected this recipient. Geometry is rechecked
            # only after a save reaction can move it; automatic success has no
            # such checkpoint, and a delayed zone need not remain near its caster.
            roll, failed = None, False
        else:
            from .save_context import spatial_context
            outcome_receipt = {}
            save_token = _ACTIVE_SAVES.set((*_ACTIVE_SAVES.get(), (id(ctx.engine), ctx.source, subject.entity_id)))
            try:
                roll = ctx.engine._roll_save(subject, choice, dc - int(shaped["bonus"]), ctx.source, extra_mode=mode,
                                            outcome_receipt=outcome_receipt,
                                            checkpoint_context={"actor_id": ctx.actor.entity_id, "effect": effect, "area": area,
                                                                "center": aim.model_dump(mode="json") if aim else None,
                                                                **({"effect_origin": origin} if origin else {}),
                                                                **({"save_geometry": ctx.save_geometry} if ctx.save_geometry is not None else {})},
                                            target_check=target_check,
                                            roll_context={**spatial_context(ctx), "source_actor_id": ctx.actor.entity_id, "named": sorted(str(n) for n in plug_in_named), "save_modes": sorted(modes)})
            finally:
                _ACTIVE_SAVES.reset(save_token)
            if roll is None:
                continue
            failed = roll.total < dc - int(shaped["bonus"])
            # Native forced success can raise the returned total to the DC.
            # Credit support only if it helped the original numeric save,
            # just as for later typed overrides and Concentration settlement.
            if not failed and outcome_receipt.get("total_before_outcome", roll.total) < dc - int(shaped["bonus"]):
                ctx.save_support_sources = []
        failed = settle_typed_save(replace(ctx, save_effect=effect, save_dc=dc - int(shaped["bonus"])), subject, choice, roll, failed, named, plug_in_named, pressed)
        if "grappled" in named:
            typed_reactions.on_grapple_outcome(ctx.engine, ctx.actor, subject, grabbed=failed)

        attached_attack = bool(effect.get("inherit_attack_damage_context"))
        inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [subject], subject, ctx.damage_cache, failed,
                        area_harmful_scope=ctx.area_harmful_scope,
                        origin_save={"ability": choice, "dc": dc,
                                     **({"named": sorted("category:" + tag for tag in effect["save_categories"])}
                                        if effect.get("save_categories") else {})},
                        save_area=effect.get("applies_to") in {
                                         "creatures_in_area", "enemies_in_area", "allies_in_area"}
                                     or (not effect.get("applies_to") and bool(area.get("size_ft"))),
                        save_geometry=ctx.save_geometry,
                        effect_source=ctx.effect_source,
                        attack_damage_context=ctx.attack_damage_context if attached_attack else None,
                        attack_defense_spec=ctx.attack_defense_spec if attached_attack else None,
                        critical_hit=ctx.critical_hit if attached_attack else False,
                        explicit_self_recipient=getattr(ctx, "explicit_self_recipient", False) or effect.get("applies_to") == "self")
        # Some save consequences must resolve before a successful save's
        # half-damage packet. This data marker is generic and leaves ordinary
        # save branch ordering untouched.
        if failed:
            fail_effects = _run_before_save_damage(inner, fail_effects)
        else:
            success_effects = _run_before_save_damage(inner, success_effects)
        # Evasion-like features (Empty Bank Evasion): a success takes no damage, a failure half (combat/ext "evasion").
        evasion = bool(ext.run("evasion", ctx, subject, choice, failed, fail_effects))
        if evasion:
            if failed:
                _half_save_damage(inner, fail_effects)
                # The helper dealt every damage row at half; do not dispatch
                # extra_damage again at full ("a failure half" for both kinds).
                run_effects(inner, [row for row in fail_effects if row.get("type") not in ("damage", "extra_damage")])
            else:
                run_effects(inner, [row for row in success_effects if row.get("type") not in ("half_damage", "damage")])
            ext.run_strict("save_effects_settled", inner, subject, choice, failed)
            continue
        if failed:
            if subject.team_id != ctx.actor.team_id:
                from . import typed_reactions

                typed_reactions.on_own_event(ctx.engine, ctx.actor, subject, "own_save_failed")  # owner 2026-09-26
            run_effects(inner, fail_effects)
            ext.run_strict("save_effects_settled", inner, subject, choice, failed)
            continue
        if halves:
            _half_save_damage(inner, fail_effects)
        run_effects(inner, [row for row in success_effects if row.get("type") != "half_damage"])
        ext.run_strict("save_effects_settled", inner, subject, choice, failed)


def _still_in_reach(ctx: Context, target: ActorState) -> bool:
    """Whether the target is still within the action's reach or range (its long range for a ranged weapon): the menu
    checked it when the action was chosen, not at each attack. Unknown reach (an area's own strike) always counts."""
    reach = ctx.action.range_ft if ctx.action.range_ft is not None else getattr(ctx.action, "reach_ft", None)
    if reach is None:
        return True
    limit = max(int(reach), int(ctx.typed.get("range_ft") or 0), int(ctx.typed.get("long_range_ft") or 0))
    from .attack_reach import maximum
    limit = maximum(ctx.engine, ctx.actor, ctx.action, base=limit,
                    opportunity=bool(ctx.typed.get('opportunity_of')))
    from .action_geometry import valid
    return valid(ctx.engine, ctx.actor, ctx.action) and ctx.engine._effect_distance(ctx.actor, target) <= limit


def block_attack(ctx: Context, effect: dict[str, Any]) -> None:
    from .action_geometry import attack
    from .shot_geometry import attack_scope
    from contextlib import ExitStack
    from . import ext
    subjects = effect_subjects(ctx, effect, harmful=effect.get("stance") != "helpful")
    ctx = replace(ctx, targets=subjects, target=subjects[0] if len(subjects) == 1 else None)
    with ExitStack() as scopes, _defeat_chain(ctx), attack(ctx.engine, ctx.actor, ctx.source), attack_scope(ctx.engine, ctx.actor, ctx.source):
        for scope in ext.run_strict("effect_resolution_scope", ctx, effect):
            scopes.enter_context(scope)
        _block_attack_in_chain(ctx, effect)


def substitute_weapon_ability(ctx: Context, effect: dict[str, Any]) -> Context:
    """Apply one resolution-local weapon ability replacement before dice/hooks.

    Only actual weapon-delivered attacks with an explicit original modifier can
    be replaced. All proficiency, refinement, dice, costs and grip metadata stay
    intact; off-hand attacks still omit a positive ability damage modifier.
    Providers own their printed eligibility and optional choice. No answer is
    strictly inert, including historical saved packets.
    """
    from . import ext
    from .weapon_delivery import delivery_kind
    weapon = ctx.typed.get("weapon")
    if (not isinstance(weapon, dict) or "ability_modifier" not in weapon
            or delivery_kind(ctx.typed, effect, ctx.action.parameters) != "weapon"):
        return ctx
    answers = [a for a in ext.run_strict("weapon_attack_ability", ctx, effect) if a is not None]
    if not answers:
        return ctx
    if len(answers) != 1:
        raise ValueError("one weapon_attack_ability provider may replace an attack ability")
    choice = answers[0]
    if (not isinstance(choice, dict) or set(choice) != {"ability", "modifier"}
            or not isinstance(choice["ability"], str) or not choice["ability"]
            or type(choice["modifier"]) is not int):
        raise ValueError("weapon_attack_ability requires ability and integer modifier")
    old, new = int(weapon["ability_modifier"]), choice["modifier"]
    typed = copy.deepcopy(ctx.typed)
    typed["numbers"]["attack_bonus"] += new - old
    typed["weapon"].update(ability=choice["ability"], ability_modifier=new)
    if typed["weapon"].get("damage"):
        typed["weapon"]["damage"]["modifier"] += (min(0, new)-min(0, old)
            if weapon.get("omits_ability_damage") else new-old)
    return replace(ctx, typed=typed)


def resolve_attack_damage(ctx: Context, effect: dict[str, Any]) -> tuple[Any, list[str], str, Any, dict[str, Any]]:
    """Resolve the sealed primary attack damage for creature or object delivery.

    Sets weapon_damage_dice, applies attack_damage and attack_damage_types
    replacements, then folds damage_roll_bonus exactly once. Call only when
    resolving damage: bonus providers may consume evented next-use state.
    Returns dice, resolved type choices, initial type, primary damage row and
    weapon profile. The caller owns rolling/maximizing, critical dice and defenses.
    """
    on_hit = effect.get("on_hit") or []
    # Optional compiler metadata keeps relocated bonuses in run_effects, where their
    # eligibility and activation-local roll slot are applied. Unmarked saved rows are unchanged.
    damage = next((row for row in on_hit if isinstance(row, dict) and row.get("type") == "damage"
                   and not row.get("damage_bonus_packet")), None)
    weapon = ctx.typed.get("weapon") or {}
    ctx.weapon_damage_dice = False
    if damage is None and (str(effect.get("attack_kind") or "").startswith("cultivation") or effect.get("no_damage")):
        # A Cultivation Attack whose hit only moves or conditions the target rolls no damage
        # (owner 2026-09-25: these used to hit without any attack roll); so does a rope dart's Trip.
        dice, damage_type = None, "UNTYPED"
    elif damage is None or damage.get("weapon_damage"):
        dice = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
        ctx.weapon_damage_dice = True
        damage_type = weapon.get("damage_type") or "UNTYPED"
        kinds = damage_choices({}, weapon)
    else:
        spec = _effect_dice(ctx, damage)
        dice = ctx.dice(spec, flat=int(damage.get("flat") or 0), formula=damage.get("formula"))
        if isinstance(dice, FlatAmount):  # an attack always rolls: weapon dice plus the fixed bonus
            base = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
            dice = DiceSpec(count=base.count, sides=base.sides, modifier=base.modifier + dice.modifier)
            ctx.weapon_damage_dice = True
        damage_type = (damage.get("damage_types") or ["untyped"])[0].upper()
        kinds = damage_choices(damage)
    if dice is None:
        kinds = [damage_type]
    # The branch above is the only reliable answer to "is this the weapon's own damage?": a technique's
    # printed die can coincide with the weapon's (both 1d8), so numbers alone cannot tell them apart.
    # attack_damage plug-ins read this to resize weapon damage only (see combat/ext/__init__.py).
    # Owner's Hammering Shots modifies the later Barrage Bonus Action attack's
    # weapon damage, not the primary attack. A plug-in may replace its DiceSpec.
    from . import ext
    for replacement in ext.run("attack_damage", ctx, dice):
        if isinstance(replacement, DiceSpec):
            dice = replacement
    for replacement in ext.run("attack_damage_types", ctx, effect, kinds):
        if replacement:
            kinds = list(replacement)
    return dice, kinds, damage_type, damage, weapon


def _block_attack_in_chain(ctx: Context, effect: dict[str, Any]) -> None:
    # Critical outcome belongs to this attack and its on-hit children. Keep the
    # caller's context clean for separate effects later in the same activation.
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_pending_attack")
    preserve_pending(ctx.engine, "_typed_roll_outcome")
    preserve_pending(ctx.engine, "_typed_negated")
    from .attack_completion import can_continue
    if not can_continue(ctx.engine, ctx.actor):
        return
    ctx = replace(ctx, critical_hit=False, attack_result=None, attack_effect=None)
    if ctx.typed.get("granted_attack") and not effect.get("granted_attack_root"):
        return  # A Granted Attack cannot itself grant another attack.
    # Owner's Barrage rules: a primary attack and its Bonus Action follow-up are one sequence.
    # The plug-in starts a fresh counter before the first roll, even when this action is used again this turn.
    from . import ext
    ext.run("attack_sequence_start", ctx)
    on_hit = effect.get("on_hit") or []
    on_miss = effect.get("on_miss") or []
    dice, kinds, damage_type, damage, weapon = resolve_attack_damage(ctx, effect)
    # Roll-only contributions depend on live state at each confirmed strike,
    # after attack-roll choices/reactions. Never cache them in sequence dice.
    for flag in ctx.typed.get("opens") or []:  # an Attack action with a Light or Paired weapon readies the off-hand one
        ctx.actor.turn_flags[flag] = True
    for flag in ctx.typed.get("uses") or []:  # the off-hand attack is made once
        ctx.actor.turn_flags[flag] = False
    for flag in ctx.typed.get("marks_used") or []:  # a once-per-turn Pair talent (Synchronous Accuracy, Following Strike)
        ctx.actor.turn_flags[flag] = True
    for target_id in ctx.missed_target_ids:
        _pair_turn(ctx, target_id, False)
    count = int(effect.get("count") or 1)
    for low, high, scaled_count in effect.get("count_by_cl") or []:
        if int(low) <= int(ctx.numbers.get("cl") or 1) <= int(high):
            count = int(scaled_count)
            break
    for target in list(ctx.targets):
        if ext.any_false("effect_subject_allowed", ctx, effect, target):
            continue
        if ctx.typed.get("reaction_attack"):
            from .typed_reactions import attack_reaches

            if not attack_reaches(ctx.engine, ctx.actor, target, effect, ctx.typed.get("reaction_range_ft"), action=ctx.action):
                ctx.rider(f"{ctx.action.display_name}: the attack cannot reach its target (no attack made).")
                continue
        damage_type = choose_damage_type(ctx, kinds, [target])  # "Piercing or Slashing": whichever lands on this target
        hits = 0
        declared_target = target
        attack_context, declared_damage_type = ctx, damage_type
        base_strike_dice = dice
        base_weapon_modifier = int(((ctx.typed.get("weapon") or {}).get("damage") or {}).get("modifier") or 0)
        for index in range(count):
            target = declared_target
            ctx, damage_type, dice = attack_context, declared_damage_type, base_strike_dice
            ctx.attack_effect = effect
            ctx.attack_damage_context = None
            ctx.attack_mode_consumption_pending = False
            from .target_knowledge import location_missed
            if location_missed(ctx.engine, ctx.actor, target, ctx.source, index + 1):
                continue
            from .attack_notifications import can_strike
            if not can_strike(ctx.actor) or not target.active or ctx.engine.state.terminal_result is not None:
                break
            if False in ext.run_strict("attack_allowed", ctx, target, effect):
                break
            if not ctx.typed.get("reaction_attack") and not effect.get("continues_hit") and not _still_in_reach(ctx, target):
                # The target was chosen in reach, but a push, a pull or a reaction's step moved one of them since
                # (fight audit 2026-09-29: a Cha's second attack after Pressing at 15 feet, reach 10).
                # ``continues_hit`` marks an attack that is part of the hit that moved the target (Perpetual Motion's "immediately
                # make one additional shove against the same target"): the first shove has already pushed it out of reach.
                ctx.rider(f"{ctx.action.display_name}: {target.display_name} is out of reach now (no attack made).")
                break
            if index and effect.get("later_reach_ft") and ctx.engine._distance_actor_to_actor(ctx.actor, target) > int(effect["later_reach_ft"]):
                # Vacuum Cut "changes the reach of that single melee weapon attack": the Attack action's later strikes keep the
                # weapon's own reach (rider lane 10, combat/ext/needle_vacuum.py).
                ctx.rider(f"{ctx.action.display_name}: only the first attack reaches {target.display_name} (no more attacks made).")
                break
            # Optional packet replacement is resolved for this actual strike.
            # A declined/accepted answer cannot leak into the next Extra Attack.
            ctx = substitute_weapon_ability(ctx, effect)
            weapon = ctx.typed.get("weapon") or {}
            if ctx.weapon_damage_dice and isinstance(dice, DiceSpec) and weapon.get("damage"):
                replacement_modifier = int(weapon["damage"].get("modifier") or 0)
                dice = DiceSpec(count=dice.count, sides=dice.sides,
                    modifier=dice.modifier + replacement_modifier - base_weapon_modifier)
            from .attack_declaration import declare
            spec = {}
            from .attack_reach import maximum
            target, declaration_cover = declare(ctx.engine, ctx.actor, target, ctx.source, ctx.intent, index + 1,
                range_ft=maximum(ctx.engine, ctx.actor, ctx.action,
                    base=int(ctx.typed.get("long_range_ft") or ctx.action.range_ft or ctx.action.reach_ft or 5),
                    opportunity=bool(ctx.typed.get('opportunity_of'))),
                context={"effect": effect, "attack_spec": spec})
            from .attack_declaration import intercepted
            if intercepted(ctx.engine, ctx.actor, target, ctx.source, ctx.intent, index + 1, spec=spec):
                continue
            from .ext.trigger_occurrence import strike_scope
            with strike_scope(ctx.engine, ctx.actor, target):
                if target is not declared_target:
                    ctx = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache,
                                  area_harmful_scope=ctx.area_harmful_scope,
                                  explicit_self_recipient=getattr(ctx, "explicit_self_recipient", False) or effect.get("applies_to") == "self")
                    ctx.attack_effect = effect
                    damage_type = choose_damage_type(ctx, kinds, [target])
                # Default-inert extension for rules that let a player choose a damage
                # type separately for every strike in a multi-attack sequence.
                for selected_type in ext.run_strict("attack_damage_type_choice", ctx, effect, target, kinds, index + 1):
                    if selected_type is not None:
                        if str(selected_type).upper() not in {str(kind).upper() for kind in kinds}:
                            raise ValueError("attack damage type choice is not one of the printed options")
                        damage_type = str(selected_type).upper()
                from . import motion

                # Past a bow's normal range out to its long range, or a Heavy weapon without Strength 13 (2024 rules).
                strike_mode_ids = set()
                mode_provenance = {}

                def add_strike_mode(mode, why=""):
                    """Record this attempt's modifiers and their native provenance."""
                    mid = ctx.engine._add_modifier(ctx.actor, ctx.source, "attack_mode", "SET", mode, "NEXT_ATTACK", expires_on="CONSUMED")
                    strike_mode_ids.add(mid)
                    if why:
                        mode_provenance[mid] = f"{mode}:{why}"

                from .shot_geometry import attack_distance
                beyond = ctx.typed.get("long_range_ft") and attack_distance(ctx.engine, ctx.actor, target) > int(ctx.typed.get("range_ft") or 0)
                if ctx.typed.get("strike_penalty_provenance") == 1:
                    if beyond:
                        add_strike_mode("DISADVANTAGE", "long_range")
                    if ctx.typed.get("disadvantage") or _enemy_adjacent_to_ranged(ctx):
                        add_strike_mode("DISADVANTAGE")
                elif beyond or ctx.typed.get("disadvantage") or _enemy_adjacent_to_ranged(ctx):
                    add_strike_mode("DISADVANTAGE")
                from . import zones, ext

                obscuration = zones.attack_modes(ctx.engine, ctx.actor, target)
                if 'DISADVANTAGE' in obscuration and ext.has("unseen_ignored") and any(ext.run("unseen_ignored", ctx, target)):
                    obscuration = tuple(mode for mode in obscuration if mode != 'DISADVANTAGE')
                from . import ext

                from .attack_modes import typed_contribution
                for reply in ext.run("attack_mode", ctx, target):
                    contribution = typed_contribution(reply)
                    if contribution:
                        add_strike_mode(*contribution)
                # Keep delivery profile separate from target distance: melee talents
                # may carry numeric range for target selection.
                attack_kind = str(effect.get("attack_kind") or "")
                from .attack_delivery import is_ranged
                ranged_try = is_ranged(attack_kind, ctx.typed.get("range_ft"), ctx.typed.get("weapon"))
                dodged = motion.attack_mode(ctx.engine, ctx.actor, target, melee=not ranged_try, source=ctx.source)  # Mobility, Current Between Steps
                if dodged:
                    add_strike_mode(dodged)

                if "chosen_attack_modes" in effect:
                    spec["chosen_attack_modes"] = effect["chosen_attack_modes"]
                spec.update({"source_definition_id": ctx.source, "action_name": ctx.action.display_name,
                        "attack_bonus": int(ctx.numbers.get("attack_bonus") or 0), "range_ft": ctx.typed.get("range_ft"),
                        "declaration_done": True, "declaration_cover": declaration_cover,
                        "reach_ft": ctx.action.reach_ft or ctx.action.range_ft or 5, "reach_action": ctx.action,
                        "attack_profile": attack_kind,
                        "typed": ctx.typed,
                        "damage": dice, "damage_type": damage_type, "parameters": {"attack_kind": "unarmed" if effect.get("attack_kind") == "unarmed"
                                       else "weapon" if ctx.typed.get("weapon") is not None else "other"},
                        "checkpoint_context": {"effect": effect, "range_ft": ctx.action.range_ft,
                                               "action": ctx.action, "typed": ctx.typed},
                        "target_check": lambda: (False not in ext.run_strict("attack_allowed", ctx, target, effect)
                                                 and (typed_reactions.attack_reaches(ctx.engine, ctx.actor, target, effect,
                                                    ctx.typed.get("reaction_range_ft"), action=ctx.action) if ctx.typed.get("reaction_attack")
                                                 else _still_in_reach(ctx, target)))})
                if index == 0 and effect.get("first_roll_bonus"):
                    # A talent's own penalty or bonus to the maneuver's attack roll ("take a -5 penalty to the attack roll": Deadly
                    # Shot), on that one attack of the Attack action (docket 2026-09-28, combat/ext/docket_maneuvers.py).
                    spec["attack_bonus"] += int(effect["first_roll_bonus"])
                first_hit_damage = int(effect.get("first_hit_damage") or 0) if index == 0 else 0
                if first_hit_damage:
                    # The damage half of the same printed rule ("Hit: Deal +10 damage"). It joins the first hit's own
                    # damage roll, so it keeps that roll's damage type and appears in its DAMAGE_ROLLED event instead
                    # of a second unlabelled packet (combat/ext/pre_roll_attack.py).
                    held = spec.get("damage")
                    if isinstance(held, DiceSpec):
                        spec["damage"] = held.model_copy(update={"modifier": held.modifier + first_hit_damage})
                    elif isinstance(held, FlatAmount):
                        spec["damage"] = FlatAmount(held.modifier + first_hit_damage)
                lent = _tandem_bonus(ctx)
                if lent and isinstance(dice, DiceSpec):
                    spec["attack_bonus"] += lent
                    spec["damage"] = DiceSpec(count=dice.count, sides=dice.sides, modifier=dice.modifier + lent)
                from . import typed_reactions

                # Run paid d20 decisions at the resolver's final targeting checkpoint,
                # after declaration/movement rechecks and a passing concealment roll.
                def before_attack_d20(engine, attacker, defender, resolved_spec):
                    shaped = typed_reactions.on_d20_pending(engine, attacker, "attack", source_id=ctx.source)
                    resolved_spec["attack_bonus"] += int(shaped["bonus"])
                    if len(set(shaped["modes"])) == 1:
                        add_strike_mode(shaped["modes"][0])
                spec["before_attack_d20"] = before_attack_d20
                # A mixed hit exposes its deliveries before the primary packet
                # commits. Any named damage rider can select its delivery here.
                primary_kind = "weapon" if weapon and ctx.weapon_damage_dice else "technique"
                packet_kinds = [primary_kind] if dice is not None else []
                if any(row.get("type") == "damage" and row is not damage for row in _walk_rows(on_hit)):
                    packet_kinds.append("technique")
                packet_kinds = tuple(dict.fromkeys(packet_kinds))
                def before_attack_damage(engine, attacker, defender, resolved_spec, provenance):
                    child = ctx.on_hit_context(defender, attack_damage_context=provenance,
                        attack_defense_spec=resolved_spec, critical_hit=provenance.critical,
                        damage_packet_kind=primary_kind)
                    if ext.has("damage_packet_selection"):
                        ext.run_strict("damage_packet_selection", child, defender, packet_kinds)
                    # Recipient-dependent bonuses and reservations belong to the
                    # confirmed recipient, after redirection and hit reactions.
                    if resolved_spec.get("damage") is not None:
                        extra = sum(value for value in ext.run("attack_damage_bonus", child, defender, effect)
                                    if type(value) is int)
                        held = resolved_spec["damage"]
                        resolved_spec["damage"] = held.model_copy(update={"modifier": held.modifier + extra})
                spec["before_attack_damage"] = before_attack_damage

                def prepare_damage_roll(engine, attacker, defender, resolved_spec):
                    # Use the final packet, retaining confirmed-hit contributions.
                    # The resolver invokes this only for real damage rolls.
                    damage_ctx = replace(ctx, targets=[defender], target=defender)
                    resolved_spec["damage"] = _damage_dice(damage_ctx, resolved_spec["damage"])
                    held = resolved_spec["damage"]
                    if isinstance(held, DiceSpec) and held.count > 0 and held.sides > 0:
                        resolved_spec["damage"] = held.model_copy(update={"modifier": held.modifier + take_activation_bonus(damage_ctx, "potency")})
                spec["prepare_damage_roll"] = prepare_damage_roll
                from . import ext

                if weapon.get("fixed_damage") is not None and (damage is None or damage.get("weapon_damage")):
                    spec["fixed_damage"] = int(weapon["fixed_damage"]) + (first_hit_damage if spec.get("damage") is None else 0)
                # Resolve per-strike choices before bonus providers. Expose the
                # private selected metadata to all remaining consumers of this
                # strike; the next iteration restores attack_context above.
                ext.run_strict("attack_spec_choice", ctx, target, effect, spec, index + 1)
                if spec["typed"] is not ctx.typed:
                    ctx = replace(ctx, typed=spec["typed"])
                    spec["checkpoint_context"]["typed"] = ctx.typed
                # Flat bonuses (including penalties) see the resolved ability.
                for extra in ext.run("attack_bonus", ctx, ctx.actor):
                    spec["attack_bonus"] += int(extra)
                # A Factory attacker's typed attack is the only place a generic "attacked"/"missed"
                # reaction (combat/reaction_triggers.py) can hook in: the sealed engine only opens a
                # window once a hit is provisional (owner 2026-09-25).
                ctx.engine._typed_pending_attack = {"attacker": ctx.actor.entity_id, "target": target.entity_id,
                                                    "action_name": ctx.action.display_name,
                                                    "bonus": int(spec.get("attack_bonus") or 0), "reach": int(ctx.action.range_ft or 5)}
                position_before_reaction = target.position
                if target.entity_id in getattr(ctx.engine, "typed_actor_ids", set()):
                    from . import typed_reactions
                    typed_reactions.on_attacked(ctx.engine, ctx.actor, target, spec, ctx.intent)
                ctx.engine._typed_pending_attack = None
                negated = getattr(ctx.engine, "_typed_negated", set())
                decided = (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).pop(ctx.actor.entity_id, None)
                if (ctx.actor.entity_id, target.entity_id) in negated or decided == "failure":
                    # R6: a reaction negated this attack, or decided it misses (Rewrite Fate on an enemy's roll)
                    ctx.engine._typed_negated = negated - {(ctx.actor.entity_id, target.entity_id)}
                    from .attack_outcomes import discard_attempt_modes
                    discard_attempt_modes(ctx.engine, ctx.actor, sorted(strike_mode_ids))
                    continue
                if decided == "success":
                    spec["attack_bonus"] = int(spec.get("attack_bonus") or 0) + 100  # Rewrite Fate: "the attack hits"
                # A declared-attack reaction may move the defender before the sealed
                # resolver begins. Recheck that target only when it actually moved.
                if target.position != position_before_reaction and (not _still_in_reach(ctx, target) or
                        not ctx.engine._line_of_sight_actor_to_actor(ctx.actor, target)):
                    from .action_geometry import valid_for_source
                    from .shot_geometry import valid_for_attack
                    if not valid_for_source(ctx.engine, ctx.actor, ctx.source):
                        ctx.rider("The chosen origin moved or is no longer available; the attack misses.")
                    elif not valid_for_attack(ctx.engine, ctx.actor, target):
                        ctx.engine._append_event('PASSIVE_TRIGGERED', ctx.source, actor_id=ctx.actor.entity_id,
                            target_ids=(target.entity_id,), payload={'log':
                            'The chosen projectile path is no longer clear or no longer reaches the defender; the attack misses.'})
                    else:
                        ctx.rider("The defender moved out of the declared attack's reach or sight; the attack misses.")
                    continue
                # Owner 2026-09-26: same stash as _deal above -- the sealed _resolve_attack_spec commits its
                # own damage internally (spec["damage_type"]) without ever calling _deal, so a damage-type
                # limit on a "damaged" reaction fired from inside it needs the type recorded here instead.
                previous_damage_type = getattr(ctx.engine, "_typed_pending_damage_type", None)
                previous_packet = getattr(ctx.engine, "_typed_damage_packet", None)
                # General delivery provenance for interception hooks. Scoped to the
                # actual attack resolution; separate on-hit damage uses _deal above.
                ctx.engine._typed_damage_packet = {
                    "source": ctx.source, "actor": ctx.actor.entity_id, "target": target.entity_id,
                    "kind": effect.get("attack_kind"), "weapon": bool(ctx.typed.get("weapon")),
                    "ranged": ranged_attack_now(ctx), "interceptable": effect.get("interceptable", True),
                }
                ctx.engine._typed_pending_damage_type = damage_type
                # The delivery identity for the same transient seam _deal_in_chain opens: a printed
                # "damage from a trap / a fall" limit read by a reaction row (combat/ext/source_sphere.py).
                # The Context's own source says which delivery this strike is part of, so the frame's
                # hazard follows that delivery and not whatever happened to be resolving around it.
                previous_damage_source = _delivery.open_frame(ctx.engine, ctx.damage_source, continues=_delivery_source(ctx))
                aimed_target, aimed_ctx = target, ctx
                # Declarations and cover can settle on another creature. Snapshot
                # potential recipients before damage for kill and temporal riders.
                before_attack = {who: (actor.active, actor.current_hp)
                                 for who, actor in ctx.engine.state.actors.items()}
                # Opt-in temporal mark gates observe the victim before this attack's damage/reactions/riders.
                # Refresh per attack, rather than once per sequence (Extra Attack can change marks).
                hit_marks = {name for row in _walk_rows(on_hit)
                             if row.get("type") == "if_marked" and row.get("at") == "hit" for name in _mark_names(row)}
                if hit_marks:
                    ctx.damage_cache["_marks_at_hit"] = {who: {
                        name: bears_mark(actor, ctx.actor.entity_id, name) for name in hit_marks}
                        for who, actor in ctx.engine.state.actors.items()}
                attack_event_start = len(ctx.engine.events)
                ctx.attack_result = None
                ctx.critical_hit = False
                first_damage_event = len(ctx.engine.events)
                _begin_strike(ctx)  # what a Weapon Method runs on this hit, and nothing from the previous one
                try:
                    from .ext.attack_scope import resolving
                    from .ext.attack_defenses import resolving_defenses
                    from .attack_modes import strike
                    from .critical_attacks import typed_scope

                    with resolving_defenses(ctx.engine, spec), resolving(ctx, target, effect), strike(ctx.engine, ctx.actor, target, ctx.source, mode_provenance, obscuration=obscuration), typed_scope(ctx, target, spec, effect):
                        allowed = False not in ext.run_strict("attack_allowed", ctx, target, effect)
                        if not allowed or (not effect.get("continues_hit") and not spec["target_check"]()):
                            from .attack_outcomes import discard_attempt_modes
                            discard_attempt_modes(ctx.engine, ctx.actor, sorted(strike_mode_ids))
                            if allowed:
                                ctx.rider(f"{ctx.action.display_name}: {target.display_name} is out of reach now (no attack made).")
                            break
                        hit = ctx.engine._resolve_attack_spec(ctx.actor, target, spec, ctx.intent, source_definition_id=ctx.source, attack_index=index + 1, notify=False)
                finally:
                    ctx.engine._typed_pending_damage_type = previous_damage_type
                    ctx.engine._typed_damage_packet = previous_packet
                    _delivery.close_frame(ctx.engine, previous_damage_source)
                if not spec.get("attack_roll_occurred"):
                    from .attack_outcomes import discard_attempt_modes
                    discard_attempt_modes(ctx.engine, ctx.actor, sorted(strike_mode_ids))
                    if not spec.get('concealment_missed'):
                        continue  # Canceled/empty aims are not actual creature misses.
                # All aftermath uses the settled recipient, including misses and
                # Context-based riders. Keep the declaration for roll provenance
                # and the next strike in a sequence, never as the rider recipient.
                target = ctx.engine.state.actors.get(spec.get("resolved_target_id"), aimed_target)
                if target is not aimed_target:
                    ctx = replace(ctx, target=target, targets=[target])
                was_active, hp_before = before_attack[target.entity_id]
                ctx.attack_damage_context = spec.get("resolved_attack_context") if hit else None
                ctx.attack_result = next((dict(event.payload) for event in reversed(ctx.engine.events[attack_event_start:])
                    if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id
                    and event.source_definition_id == ctx.source
                    and event.payload.get("reason") == f"ATTACK:{ctx.source}:{index + 1}"), None)
                attack_event = next((event for event in ctx.engine.events[first_damage_event:]
                                     if event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id
                                     and event.source_definition_id == ctx.source
                                     and event.payload.get("reason") == f"ATTACK:{ctx.source}:{index + 1}"), None)
                if attack_event is not None and index > 0:
                    attack_event.payload["attack_sequence_index"] = index + 1
                ctx.critical_hit = bool(hit and ctx.attack_damage_context and ctx.attack_damage_context.critical)
                ctx.attack_mode_consumption_pending = True
                ext.run_strict("attack_result", ctx, target, hit, ctx.critical_hit)
                _notify_damage_dealt(replace(ctx, damage_packet_kind=primary_kind,
                    attack_defense_spec=spec), target, first_damage_event)
                _use_vex(ctx.engine, ctx.actor, target)
                ctx.attack_mode_consumption_pending = False
                if hit and not ranged_attack_now(ctx):
                    apply_exploit(ctx, target)  # the Piercing Needle's Exploits
                if hit and (ctx.typed.get("weapon") is not None or effect.get("attack_kind") in ("unarmed", "melee")) and target.active:
                    from . import unmaking

                    unmaking.charged_hit(ctx, target)  # Ruin Channel
                from . import ext

                kind = "unarmed" if effect.get("attack_kind") == "unarmed" or ".natural." in ctx.source else "weapon" if ctx.typed.get("weapon") is not None else "other"
                if hit:
                    hits += 1
                    if target.active and hits == int(effect.get("after_hits") or 0):
                        run_effects(ctx.on_hit_context(target), effect.get("after_hits_effects") or [])
                    ext.run_strict("after_hit_choice", ctx, target, kind)
                    ext.run("after_hit", ctx, target, kind)
                    from .attack_notifications import finish
                    finish(ctx, target, kind, spec)
                else:
                    ext.run("after_miss", ctx, target)
                if hit and target.active:
                    from . import stances

                    stances.after_hit(ctx, target, kind="unarmed" if effect.get("attack_kind") == "unarmed" or ".natural." in ctx.source
                                      else "weapon" if ctx.typed.get("weapon") is not None else "other")  # the Ruin Forms
                if hit and effect.get("attack_kind") == "unarmed" and any(
                        event.event_type == "DAMAGE_COMMITTED" and target.entity_id in (event.target_ids or ()) and int((event.payload or {}).get("hp_damage") or 0)
                        + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0 for event in ctx.engine.events[-12:]):
                    open_guard(ctx, target, damaged=True)  # Iron Fist: an Unarmed Strike that deals damage Opens the target
                from . import stealth

                # Assassinate (eye, 2026-09-28): a hit that reduces its target to 0 HP while hidden does not by itself
                # end the hidden state; a plug-in that wants to run its own reveal logic for this attack returns False.
                if not ext.any_false("attack_reveal", ctx, target, bool(hit)):
                    stealth.reveal(ctx.engine, ctx.actor, ctx.source, "attacked")  # Hidden ends after an attack roll (2024 Hide)
                ranged_attack = spec.get("range_ft") is not None and int(spec.get("range_ft") or 0) > 5
                _after_own_blow(ctx, target, was_active=was_active, hit=bool(hit), ranged=ranged_attack, hp_before=hp_before)
                if target.entity_id in getattr(ctx.engine, "typed_actor_ids", set()):
                    from . import typed_reactions

                    typed_reactions.on_attack_resolved(ctx.engine, ctx.actor, target, spec, ctx.intent)  # audit F10
                ext.run("attack_resolved", ctx, target, bool(hit), effect)  # plug-ins: after this attack resolved (Flowing Response)
                if not hit and target.active and target.entity_id in getattr(ctx.engine, "typed_actor_ids", set()):
                    from . import typed_reactions
                    typed_reactions.on_attack_missed(ctx.engine, ctx.actor, target, spec, ctx.intent)
                if not hit:
                    ext.run_strict("after_miss_choice", ctx, target, spec)
                if not hit and on_miss and target.active:
                    from .effect_eligibility import attack_damage_occurrence
                    with attack_damage_occurrence(ctx):
                        run_effects(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache,
                                            area_harmful_scope=ctx.area_harmful_scope,
                                            explicit_self_recipient=getattr(ctx, "explicit_self_recipient", False)), on_miss)
                if hit and ctx.typed.get("pair_role"):
                    _paired_rhythm(ctx)
                _pair_turn(ctx, target.entity_id, bool(hit))
                from . import typed_reactions

                if spec.get('attack_roll_occurred'):
                    typed_reactions.after_d20(ctx.engine, ctx.actor, "attack", success=bool(hit), other=target, melee=not ranged_attack,
                                              natural=spec.get('attack_natural_result'), source_id=ctx.source)
                elif spec.get('concealment_missed'):
                    typed_reactions.after_attack_miss(ctx.engine, ctx.actor, melee=not ranged_attack, source_id=ctx.source)
                # An outcome set after this attack resolved ("turn the success into a failure") came too late for it; it must not
                # carry over to the attacker's next roll.
                (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).pop(ctx.actor.entity_id, None)
                if ctx.typed.get("pair_role") == "answer":  # "you make your Paired Strike while wielding a third weapon"
                    typed_reactions.on_own_event(ctx.engine, ctx.actor, target, "own_action", accept=lambda row: row.get("action") == "paired_strike")
                if hit and target.active:
                    # Each hit rolls its own on-hit dice (Extra Attack); per-activation flags such as potency carry over.
                    hit_cache = {key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)}
                    inner = ctx.on_hit_context(target, damage_cache=hit_cache,
                                               attack_damage_context=spec.get('resolved_attack_context'),
                                               attack_defense_spec=spec)
                    # A weapon maneuver (Trip, Grapple, ...) rides one hit of the Attack action (owner 2026-09-26).
                    first = [row for row in on_hit if row is not damage and row.get("first_hit_only")]
                    from .effect_eligibility import attack_damage_occurrence
                    with attack_damage_occurrence(inner):
                        run_effects(inner, [row for row in on_hit if row is not damage and not row.get("first_hit_only")]
                                    + ([] if hit_cache.get("_maneuver_used") else first))
                    if first:
                        hit_cache["_maneuver_used"] = True
                    ctx.damage_cache.update({key: value for key, value in hit_cache.items() if isinstance(key, str)})
                    if target.active:
                        _on_hit_bonuses(ctx, target, effect, damage_type)
                    # General seam: this hit's own on-hit effects (a Weapon Method among them) have now executed, so a
                    # printed trigger naming one can ask executed_weapon_methods instead of the action's selected rows.
                    # after_hit observers are unchanged; with no handler registered nothing here runs.
                    ext.run_strict("after_hit_effects", ctx, target, kind)
                # A post-attack rider must run after every explicitly attached packet,
                # including late bonuses, and before this sequence's next attack.
                if hit and spec.get('resolved_attack_context') is not None:
                    ctx.engine._run_final_riders('attack_damage_final', ctx.engine, ctx.actor, target,
                                                spec['resolved_attack_context'], ctx.intent)
                ctx.attack_damage_context = None
                from .attack_completion import notify as complete_attack
                reacted = complete_attack(ctx.engine, ctx.actor, target, spec, ctx.intent, ctx.source, bool(hit), index + 1, kind=kind)
                target, ctx = aimed_target, aimed_ctx
                if reacted and not can_continue(ctx.engine, ctx.actor):
                    return


# ------------------------------------------------------------------ later hits (owner 2026-09-26 tournament)
# "Once per turn when you hit with an unarmed strike, deal an additional 2d6" (Oni Form, Lightning-God Body,
# Gather Charge's "the next time you hit", Demon Mark's "when you damage it"): using the ability registers a
# bonus on the actor for the ability's duration; each later hit that meets the printed limits deals it.
ON_HIT_BONUS = re.compile(r"\b(?:once (?:per|each) turn,?\s*when|the (?:first|next) time)\s+(?:(?:during each of your turns|each turn),?\s*)?"
                     r"you\s+(?:hit|deal damage|damage)\b|\bonce per turn when (?:you|it) hits?\b", re.I)
_ON_HIT_CLAUSE = re.compile(r"\b(?:hits?|deal damage|damage)\b(.*?)(?:,\s*(?:you|deal|add|it|the)\b|[.;]|$)", re.I)
_ON_HIT_BOUND = re.compile(r"\bwhen you (?:damage|hit) it\b", re.I)
_DAMAGE_WORDS = ("acid", "cold", "fire", "force", "lightning", "necrotic", "poison", "psychic", "radiant", "thunder")


def _register_on_hit(ctx: Context, effect: dict[str, Any]) -> None:
    if ((ctx.typed.get("duration") or {}).get("kind") or "instant") == "instant":
        return  # nothing lasts to carry the bonus
    evidence = " ".join(str(effect.get("evidence") or "").split())
    bound = ctx.target.entity_id if ctx.target is not None and _ON_HIT_BOUND.search(evidence) else ""
    value = f"{bound}|{evidence}"
    if ctx.damage_cache.get("_on_hit_weapon_id"):
        value += "|" + str(ctx.damage_cache["_on_hit_weapon_id"])
    for mid, modifier in list(ctx.actor.modifiers.items()):  # using it again refreshes the bonus
        if modifier.target_field == "typed_on_hit" and modifier.source_definition_id == ctx.source and modifier.value == value:
            del ctx.actor.modifiers[mid]  # logged, so the Gate 3 replay removes it too
            ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"modifier_id": mid, "reason": "REFRESHED"})
    ctx.engine._add_modifier(ctx.actor, ctx.source, "typed_on_hit", "ADD", value, "SELF", expires_on=ctx.expires_on())


# ------------------------------------------------------------------ later resource gains (owner 2026-09-26)
# "When it drops to 0 HP, gain 1 Devoured Essence" (Demon Mark), "the first time you hit ..., gain 1 X": using the
# ability registers a watch on the actor for its duration (bound to this target when the text says "it"); the
# actor's own hit, kill or an enemy's failed save (typed_reactions.on_own_event) runs the effect then.
_WATCH_BOUND = re.compile(r"\b(?:it|the target|that creature|the marked creature)\b", re.I)


def _register_watch(ctx: Context, effect: dict[str, Any]) -> None:
    from .reaction_triggers import classify_trigger

    evidence = " ".join(str(effect.get("evidence") or "").split())
    kind = classify_trigger(evidence).kind
    if not kind.startswith("own_"):
        return
    bound = ctx.target.entity_id if ctx.target is not None and _WATCH_BOUND.search(evidence) else ""
    if kind == "own_kill" and ctx.target is not None and bound and not ctx.target.active:
        _run_watched(ctx.engine, ctx.actor, ctx.target, ctx.source, evidence)  # this very use already brought it down
        return
    value = f"{kind}|{bound}|{evidence}"
    for mid, modifier in list(ctx.actor.modifiers.items()):  # using it again refreshes the watch
        if modifier.target_field == "typed_watch" and modifier.source_definition_id == ctx.source and modifier.value == value:
            del ctx.actor.modifiers[mid]
            ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"modifier_id": mid, "reason": "REFRESHED"})
    ctx.engine._add_modifier(ctx.actor, ctx.source, "typed_watch", "ADD", value, "SELF",
                             expires_on=ctx.expires_on() or "END_OF_CURRENT_TURN")


def _run_watched(engine: Any, actor: ActorState, other: ActorState | None, source: str, evidence: str) -> None:
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}

    def walk(rows: list[Any]):
        for row in rows or []:
            if isinstance(row, dict):
                yield row
                for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                    yield from walk(row.get(branch))

    effect = next((row for row in walk(typed.get("effects")) if row.get("deferred") and " ".join(str(row.get("evidence") or "").split()) == evidence), None)
    if effect is None or action is None:
        return
    run_effects(Context(engine, actor, action, None, typed, [other] if other is not None else [], other, {"_potency_used": True}),
                [{**effect, "deferred": False}])


def run_watches(engine: Any, actor: ActorState, other: ActorState | None, kind: str) -> None:
    """The watches this own event answers (called from typed_reactions.on_own_event)."""
    for mid, modifier in list(actor.modifiers.items()):
        if modifier.target_field != "typed_watch" or mid not in actor.modifiers:
            continue
        watched, bound, evidence = (str(modifier.value).split("|", 2) + ["", ""])[:3]
        if watched != kind or (bound and (other is None or bound != other.entity_id)) or (kind == "own_kill" and bound):
            continue  # a bound kill watch is run by run_kill_watches, whoever the killer
        if re.search(r"\bonce (?:per|each) (?:turn|round)\b", evidence, re.I):
            key = f"typed_watch_once:{mid}"
            if actor.turn_flags.get(key) == engine.state.round_number:
                continue
            actor.turn_flags[key] = engine.state.round_number
        elif re.search(r"\bthe (?:first|next) time\b", evidence, re.I) or (kind == "own_kill" and bound):
            del actor.modifiers[mid]  # used up (a bound kill watch has nothing left to watch)
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id,
                                 target_ids=(actor.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})
        _run_watched(engine, actor, other, modifier.source_definition_id, evidence)


def _registered_effect(engine: Any, source: str, evidence: str) -> dict[str, Any] | None:
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}

    def walk(rows: list[Any]):
        for row in rows or []:
            if isinstance(row, dict):
                yield row
                for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
                    yield from walk(row.get(branch))

    return next((row for row in walk(typed.get("effects")) if row.get("deferred") and row.get("type") == "extra_damage"
                 and " ".join(str(row.get("evidence") or "").split()) == evidence), None)


def _hit_qualifies(ctx: Context, target: ActorState, attack: dict[str, Any], damage_type: str, clause: str) -> bool:
    """The printed limit on which hits count ("with an unarmed strike, melee weapon attack, or Lightning Lash",
    "a creature bearing your Spear Intent"); a limit combat cannot check keeps the bonus off."""
    mark = re.search(r"bearing your ([A-Z][\w' -]*)", clause)
    if mark:
        return bears_mark(target, ctx.actor.entity_id, mark.group(1).strip())
    kind = str(attack.get("attack_kind") or "")
    ranged = ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5 or kind.endswith("ranged")
    name = ctx.action.display_name.lower()
    alternatives = [part.strip() for part in re.split(r",|\bor\b", re.sub(r"^\s*(?:with|using)\s+", "", clause.strip(), flags=re.I)) if part.strip()]
    if not alternatives or all(re.fullmatch(r"(?:during each of your turns|each turn|it)", part, re.I) for part in alternatives):
        return True
    for part in alternatives:
        text = part.lower()
        if "unarmed" in text:
            if kind == "unarmed" or "unarmed" in name:
                return True
            continue
        checks = []
        if "melee" in text:
            checks.append(not ranged)
        if "ranged" in text:
            checks.append(ranged)
        if "weapon" in text:
            from .ext.weapon_hits import is_weapon_hit

            checks.append(is_weapon_hit(ctx, attack))
        if "cultivation" in text:
            checks.append(kind.startswith("cultivation"))
        words = [word for word in _DAMAGE_WORDS if word in text]
        if words:
            checks.append(damage_type.lower() in words or any(word in name for word in words))
        if checks:
            if all(checks):
                return True
        elif re.sub(r"^(?:a|an|the)\s+", "", text) in name:
            return True  # a named ability ("Source Pulse")
    return False


def on_hit_turn_key(engine: Any, actor: ActorState, source: str, evidence: str) -> tuple[str, str]:
    """The transient per-turn gate a "once per turn" later-hit rider is keyed to.

    Both this module's ``_on_hit_bonuses`` and a plug-in that folds such a rider into the
    printed damage roll (combat/ext/roll_modifiers.py) resolve the same ``(key, turn)`` pair
    here, so a rider consumed by the roll is not also fired as its own packet afterwards.
    A turn belongs to the current actor, not the rider's owner; the flag is transient.
    """
    current = engine.state.actors[engine.state.current_actor_id]
    turn = f"{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}"
    return f"_round_typed_on_hit:{source}:{evidence}", turn


def on_hit_rider_available(engine: Any, actor: ActorState, key: str, turn: str, target_id: str) -> bool:
    """Read the shared turn/moment gate without reserving or spending a rider.

    Used by the executor and roll_modifiers' candidate/reservation path. A
    nested hit cannot reopen a spent rider by changing the turn counter.
    Characters without a qualifying rider never call this presentation-free seam.
    """
    moment = getattr(engine, "_typed_moment", None)
    return actor.turn_flags.get(key) != turn and (moment is None or (actor.entity_id, key, target_id) not in moment)


def spend_on_hit_rider(engine: Any, actor: ActorState, key: str, turn: str, target_id: str) -> bool:
    """Atomically claim a landed rider for its turn and resolution moment.

    Shared by ordinary on-hit packets and roll_modifiers' landed damage rolls.
    Return False when already spent. Missed attack reservations do not call it;
    the existing string turn flag persists, while the moment set is never saved.
    """
    if not on_hit_rider_available(engine, actor, key, turn, target_id):
        return False
    _moment_already_spent(engine, actor.entity_id, key, target_id)
    actor.turn_flags[key] = turn
    return True


def _on_hit_bonuses(ctx: Context, target: ActorState, attack: dict[str, Any], damage_type: str, *, damage_only: bool = False) -> None:
    """``damage_only``: damage dealt without an attack roll -- only a "when you damage it"/"deal damage" bonus counts."""
    for mid, modifier in list(ctx.actor.modifiers.items()):
        if modifier.target_field != "typed_on_hit" or mid not in ctx.actor.modifiers:
            continue
        bound, evidence, weapon_id = (str(modifier.value).split("|", 2) + [""])[:3]
        if weapon_id:
            from .ext.weapon_hits import available_weapons, is_weapon_hit, weapon_identity

            if (not is_weapon_hit(ctx, attack) or weapon_identity(ctx) != weapon_id
                    or weapon_id not in available_weapons(ctx.engine, ctx.actor)):
                continue
        if bound and bound != target.entity_id:
            continue
        if damage_only and not re.search(r"\bdamage it\b|\bdeal damage\b|\bdamage (?:a|the|that) (?:creature|target)\b", evidence, re.I):
            continue
        effect = _registered_effect(ctx.engine, modifier.source_definition_id, evidence)
        clause = _ON_HIT_CLAUSE.search(evidence.split("when", 1)[-1] if "when" in evidence.lower() else evidence)
        if effect is None or not _hit_qualifies(ctx, target, attack, damage_type, clause.group(1) if clause else ""):
            continue
        if re.search(r"\bonce (?:per|each) turn\b|\beach turn\b|\bduring each of your turns\b", evidence, re.I):
            # A turn belongs to the current actor, not the bonus owner. Persist
            # the ability/effect gate across owner's turn resets and refreshes.
            if "during each of your turns" in evidence.lower() and ctx.engine.state.current_actor_id != ctx.actor.entity_id:
                continue
            key, turn = on_hit_turn_key(ctx.engine, ctx.actor, modifier.source_definition_id, evidence)
            # One moment spends the rider once per target, whatever the turn identity does
            # while this resolution is still running (_moment_scope).
            if not spend_on_hit_rider(ctx.engine, ctx.actor, key, turn, target.entity_id):
                continue
        elif re.search(r"\bthe (?:first|next) time\b", evidence, re.I):
            del ctx.actor.modifiers[mid]
            ctx.engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=ctx.actor.entity_id,
                                     payload={"modifier_id": mid, "reason": "CONSUMED"})
        source_action = ctx.engine.action_catalog.get(modifier.source_definition_id)
        typed = ((source_action.parameters or {}).get("typed") or ctx.typed) if source_action is not None else ctx.typed
        # A hit-triggered bonus belongs to this attack's shared defense budget.
        # A damage-triggered mark can also fire on a save/zone, so it remains
        # an independent packet even when this triggering damage was a hit.
        attached = ctx.attack_damage_context if re.search(r"\bhits?\b", evidence, re.I) else None
        bonus = ctx.on_hit_context(target, action=source_action or ctx.action, typed=typed,
                                   attack_damage_context=attached,
                                   damage_cache={"_potency_used": True, "_bonus": True})
        block_damage(bonus, {**effect, "deferred": False, "applies_to": "target"})


def condition_save_data(ctx: Context, effect: dict[str, Any]) -> dict[str, Any]:
    """Snapshot explicit condition data and save provenance for direct or delayed application.

    A delay must retain the original ability/DC, not reconstruct them from the caster when it ends. Rule-specific
    defaults and condition-state hooks remain the caller's responsibility. ``origin_save`` alone never schedules
    a repeat and may come from either initial save outcome.
    """
    data = copy.deepcopy(effect.get("condition_data") or {})
    if effect.get("repeat_save"):
        data["repeat_save"] = {**copy.deepcopy(effect["repeat_save"]), "dc": int(ctx.numbers.get("save_dc") or 10)}
        inherited = (ctx.origin_save or {}).get("named") or []
        if inherited:
            data["repeat_save"]["named"] = list(dict.fromkeys([
                *(data["repeat_save"].get("named") or []), *inherited]))
    elif ctx.origin_save:
        data["origin_save"] = copy.deepcopy(ctx.origin_save)
    return data


def block_condition(ctx: Context, effect: dict[str, Any]) -> None:
    if str(effect.get("condition") or "").lower() == "invisible" and any(
            c.condition_id == NO_INVISIBLE for subject in _default_subject(ctx, effect, harmful=False) for c in subject.conditions.values()):
        return  # Unsettle Invisibility
    from . import typed_reactions

    name = str(effect.get("condition") or "").lower()
    if not name or name == "none":
        return
    if name not in rules()["conditions"]:
        ctx.rider(f"Condition not in the rules file: {name}")
    stands_up = bool(rules()["conditions"].get(name, {}).get("ends_on_stand_up"))
    for subject in _default_subject(ctx, effect, harmful=True):
        data: dict[str, Any] = {}
        # Never permanent: without a stated duration it ends with the affected creature's next turn (not the user's own
        # turn, owner 2026-09-26); Prone lasts until the creature stands up (combat/rules/typed_conditions.json); a grapple
        # lasts until the creature escapes or the grappler lets go (owner 2026-09-26). The effect's own duration comes first.
        stated = effect_expiry(ctx, effect, subject, condition=True)
        expires = "UNTIL_REMOVED" if effect.get("until_escape") else "STAND_UP" if stands_up else stated or "END_OF_HOLDER_NEXT_TURN"
        if name == "disarmed":
            # Disarming a creature that holds your taken weapon knocks yours loose (the attacker picks what drops,
            # owner 2026-09-26); it lands at the creature's feet for you to pick up.
            yours = next((iid for iid, c in ctx.actor.conditions.items() if c.data.get("held_by") == subject.entity_id), None)
            if yours is not None:
                data = {key: value for key, value in ctx.actor.conditions[yours].data.items() if key != "held_by"}
                _reapply_weapon_state(ctx, ctx.actor, yours, {**data, "dropped_at": subject.position.model_dump(mode="json")})
                continue
            # Otherwise the target drops its best weapon; it attacks with it again once it spends the pick-up.
            weapon = _best_weapon_action(ctx.engine, subject)
            if weapon is None:
                continue  # nothing in hand to knock away
            # It lands in the creature's space and stays there until picked up (within 5 ft).
            data, expires = {"disables_action": weapon, "dropped_at": subject.position.model_dump(mode="json")}, "UNTIL_REMOVED"
        elif name == "burning":
            # Tianxia Burn: Fire damage equal to the burner's Proficiency Bonus at the start of the creature's turn,
            # until the start of the burner's next turn unless stated; burns from one cultivator do not stack.
            data = {"burn": int(ctx.numbers.get("pb") or 2), "type": "FIRE"}
            if not stated:
                expires = "START_OF_SOURCE_NEXT_TURN"
            for iid, old in list(subject.conditions.items()):
                if old.condition_id == CONDITION_PREFIX + "burning" and old.source_actor_id == ctx.actor.entity_id:
                    del subject.conditions[iid]
                    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                             payload={"condition_id": old.condition_id, "instance_id": iid})
        elif name in ("grappled", "pinned"):
            # Escape: an Action, Athletics or Acrobatics against the grapple's DC; it ends past the grappler's reach.
            # A pin is a deeper hold on a grappled creature: the first escape breaks the pin, a second the grapple.
            data = {"escape_dc": int(ctx.numbers.get("save_dc") or 10), "reach_ft": int(ctx.action.range_ft or 5)}
            # General typed hold seam for effects whose printed escape is a repeated save.
            # Source-specific producers may continue writing the same retained condition data directly.
            if str(effect.get("escape_save") or "").upper() in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}:
                data["escape_save"] = str(effect["escape_save"]).upper()
        data = {**data, **condition_save_data(ctx, effect)}
        # condition_gained (owner 2026-09-26): offered before the condition actually lands, so a
        # resist/end reaction can prevent it outright rather than merely reacting after the fact.
        from . import ext

        if any(result is False for result in ext.iter_strict("condition_attempt", ctx, subject, effect)):
            continue
        if condition_immune(ctx.engine, subject, name):
            continue
        if typed_reactions.offer_condition_gained(ctx.engine, subject, ctx.actor, name):
            continue
        # General condition-state seam: dependent holds and other condition plug-ins
        # can attach event-persisted data/expiry without replacing condition save,
        # immunity or reaction handling. Absent/conflicting answers retain defaults.
        states = [state for state in ext.run("condition_state", ctx, subject, effect) if state is not None]
        if len(states) == 1:
            if states[0] is False:
                continue
            if isinstance(states[0], dict):
                data = {**data, **states[0].get("data", {})}
                expires = states[0].get("expires_on", expires)
        if isinstance(effect.get('condition_label'), str):
            data['label'] = effect['condition_label']
        ctx.engine._apply_condition(subject, CONDITION_PREFIX + name, ctx.source, ctx.actor.entity_id, expires_on=expires, data=data)
        # A condition that is several rules at once (Hollowed: no Temporary HP, no ordinary Invisible) puts on the conditions
        # the engine already checks, for exactly as long (owner 2026-09-29: Hollowed showed no effect).
        for companion in rules()["conditions"].get(name, {}).get("companions") or []:
            ctx.engine._apply_condition(subject, CONDITION_PREFIX + companion, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                        data={"label": f"{name.replace('_', ' ').title()}: {companion.replace('_', ' ')}", "companion_of": name})
        if rules()["conditions"].get(name, {}).get("no_reactions"):
            subject.reaction_available = False
        from . import ext
        ext.run("condition_applied", ctx, name, subject)
    if name == "disarmed":
        _reweigh(ctx)  # a weapon knocked away no longer weighs on its owner (owner 2026-09-27)


def block_remove_condition(ctx: Context, effect: dict[str, Any]) -> None:
    """End a typed condition on the subject ("end the Poisoned condition", Purify the Pulse's "Remove Blinded");
    Astra's audit 2026-09-26 found these typed as applying the condition."""
    name = str(effect.get("condition") or "").strip().lower().removeprefix(CONDITION_PREFIX)
    if not name or name == "none":
        return
    subjects = ([ctx.target] if ctx.target is not None else [ctx.actor]) if effect.get("applies_to") == "target_or_self" \
        else _default_subject(ctx, effect, harmful=False)  # Extinguish: yourself or an adjacent creature
    for subject in subjects:
        if subject is not None and subject.active:
            from . import ext
            if ext.has("te.condition_removal"):
                cause = str(effect.get("cause") or "cure").strip().lower()
                if ext.run_strict("te.condition_removal", ctx, subject, name, cause):
                    raise ValueError("te.condition_removal providers must return None")
            ctx.engine._remove_condition(subject, f"{CONDITION_PREFIX}{name}", ctx.source)


# Existing marker tokens remain readable for saved fights. New turn vocabulary
# comes from duration_turns, shared with effects rather than a second literal map.
def marker_expiry(kind: str) -> str | None:
    turn = duration_turn(kind)
    if turn and turn[1] == "source":
        return "START_OF_MARKER_NEXT_TURN" if turn[0] == "start" else "END_OF_MARKER_NEXT_TURN"
    return None


def expire_marks(engine: Any) -> None:
    """Remove every mark whose marker's deadline has passed (called as typed code runs, inside the engine's own
    transaction, so each removal is an ordinary CONDITION_REMOVED event and replays)."""
    from .ext.effect_durations import skipped_expiry_slots
    current = engine.state.current_actor_id
    for holder in list(engine.state.actors.values()):
        for condition in list(holder.conditions.values()):
            if condition.expires_on not in ("END_OF_MARKER_NEXT_TURN", "START_OF_MARKER_NEXT_TURN"):
                continue
            marker = engine.state.actors.get(condition.source_actor_id)
            placed = int((condition.data or {}).get("marker_turn") or 0)
            turns = int(marker.turns_started) + skipped_expiry_slots(holder, condition) if marker is not None else placed + 2
            if condition.expires_on == "START_OF_MARKER_NEXT_TURN":
                over = turns > placed
            else:
                over = turns > placed + 1 or (turns == placed + 1 and current != condition.source_actor_id)
            if over:
                engine._remove_condition_instance(holder, condition.instance_id, "system:typed.mark_expiry",
                                                  expected=condition, expiring=True)


def mark_capacity(ctx: Context, name: str) -> int | None:
    """Effective owned mark limit, shared by placement and optional replacement menus.

    Base typed limits and the documented mark_cap hooks use the same ordering;
    no limit is imposed when the actor has no configured cap for this mark.
    """
    from . import ext, typed_reactions

    caps: dict[str, Any] = {}
    for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "mark_caps"):
        caps.update(row.get("caps") or {})  # every feature's limits (a Glass + Smoke character has two mark_caps rows; rider lane C13)
    cap = caps.get(name.lower())
    if cap:
        for change in ext.run("mark_cap", ctx, name):
            cap = (int(cap) + int((change or {}).get("add") or 0)) * int((change or {}).get("mul") or 1)
    return int(cap) if cap else None


def block_mark(ctx: Context, effect: dict[str, Any]) -> None:
    """Place a named mark on the subject (owner 2026-09-26): a condition-like tag other reactions and
    effects key off (typed_reactions.bears_mark/``if_marked`` below). Re-marking the same creature with
    the same name refreshes it (the sealed engine's ``_apply_condition`` does not dedupe by id itself)
    rather than stacking a duplicate instance."""
    name = str(effect.get("mark") or "").strip()
    if not name:
        return
    owner = ctx.actor.entity_id
    condition_id = mark_condition_id(name, owner)
    duration_kind = (effect.get("duration") or {}).get("kind") or "until_removed"
    if duration_kind == "until_removed":
        # A mark whose own rule gives it a deadline (rules/typed_conditions.json "mark_durations": the Tension Mark "lasts until the
        # end of your next turn", Puppetry core rules); its talents' typed rows only say "gains a Tension Mark" (placed-effects 2026-09-29).
        duration_kind = (rules().get("mark_durations") or {}).get(name.lower(), duration_kind)
    data = None
    marker = marker_expiry(duration_kind)
    if marker:
        # "Until the end of your next turn", counted in the marker's own turns (Astra's audit, 2026-09-26: Yin's and
        # Yang's marks never expired); expire_marks removes it, through the engine, once that turn is over.
        expires, data = marker, {"marker_turn": int(ctx.actor.turns_started)}
    elif duration_kind == "concentration":
        # "While the bond lasts... you lose Concentration" (Qi Bond, Qiweaving): a mark tied to the marker's own
        # Concentration ends with it, same as a condition (gate2_engine._end_concentration); worker w2-support 2026-09-28.
        expires = "CONCENTRATION_END"
    else:
        expires = rules()["durations"].get(duration_kind)
        if not expires:
            # "for 1 minute": ten rounds (combat/ext/effect_durations.py), or as long as the ability's Concentration when it has one
            counted = clock_expiry(ctx.engine, duration_kind, _clock_amount(ctx, effect.get("duration"), duration_kind))
            expires = ("CONCENTRATION_END" if counted and ctx.expires_on() == "CONCENTRATION_END" else counted) or "UNTIL_REMOVED"
    from . import ext

    for replaced in ext.run("mark_duration", ctx, name, duration_kind):
        if isinstance(replaced, dict):
            # A counted lifetime replacement/floor, using the ordinary clock.
            # Existing string replies retain their marker-turn semantics.
            replacement_kind = replaced.get("kind")
            amount = replaced.get("amount")
            if (set(replaced) - {"kind", "amount", "minimum"} or type(amount) is not int or amount <= 0
                    or duration_round_count(replacement_kind, amount) is None
                    or type(replaced.get("minimum", False)) is not bool):
                raise ValueError("mark_duration requires a positive counted duration")
            if replaced.get("minimum"):
                if replacement_kind != duration_kind:
                    raise ValueError("mark_duration minimum requires the existing unit")
                amount = max(amount, int(_clock_amount(ctx, effect.get("duration"), duration_kind) or 1))
            if expires != "CONCENTRATION_END":
                duration_kind, expires, data = replacement_kind, clock_expiry(ctx.engine, replacement_kind, amount), None
        else:
            replacement = marker_expiry(replaced) if replaced else None
            if replaced != duration_kind and replacement:
                duration_kind, expires, data = replaced, replacement, {"marker_turn": int(ctx.actor.turns_started)}
    cap = mark_capacity(ctx, name)
    # Marks that count as one kind (Yang: Kindled and Overkindled are both Rising Marks; rules/typed_conditions.json "mark_families"): a
    # subject carries one of them from the same marker, and the limit counts them together.
    family = next((names for key, names in (rules().get("mark_families") or {}).items() if not key.startswith("_") and name.lower() in names), [name.lower()])
    family_ids = {mark_condition_id(member.title(), owner) for member in family}
    for subject in _default_subject(ctx, effect, harmful=False):
        if not subject.active:
            continue
        from . import ext
        if any(result is True for result in ext.run("mark_apply", ctx, effect, subject, expires, data)):
            continue
        ctx.engine._remove_condition(subject, condition_id, ctx.source)
        for other_id in family_ids - {condition_id}:
            ctx.engine._remove_condition(subject, other_id, ctx.source)  # "only one Rising Mark from you at a time"
        if cap:
            # "Maintain up to N": a new one past the limit ends the oldest (step 8, owner 2026-09-26).
            placed = sorted(((c.applied_sequence, actor, c) for actor in ctx.engine.state.actors.values() for c in actor.conditions.values()
                             if c.condition_id in family_ids), key=lambda row: row[0])
            for _, bearer, oldest in placed[:max(0, len(placed) - int(cap) + 1)]:
                ctx.engine._remove_condition(bearer, oldest.condition_id, ctx.source)
        ctx.engine._apply_condition(subject, condition_id, ctx.source, owner, expires_on=expires, data=data)
        from . import ext

        ext.run_strict("mark_applied", ctx, name, subject)


def block_spend_mark(ctx: Context, effect: dict[str, Any]) -> None:
    """Remove a named mark the actor placed (owner 2026-09-26): "spend/consume the mark". Tries the
    ability's own subject(s) first (the common "spend the mark on the target" shape); when none of
    them carry it (a self-triggered spend with no clear bearer), removes it from the first creature
    that does, so a bad printed name never crashes the fight -- it simply finds nothing to spend."""
    name = str(effect.get("mark") or "").strip()
    if not name:
        return
    owner = ctx.actor.entity_id
    condition_id = mark_condition_id(name, owner)
    subjects = [subject for subject in _default_subject(ctx, effect, harmful=False)
               if subject is not None and bears_mark(subject, owner, name)]
    if not subjects:
        subjects = [actor for actor in ctx.engine.state.actors.values() if bears_mark(actor, owner, name)][:1]
    for subject in subjects:
        from . import ext
        results = ext.run("mark_consume", ctx, effect, subject)
        if any(result is False for result in results):
            continue  # a counted mark cannot pay this cost; nothing was spent
        if not any(result is True for result in results):
            ctx.engine._remove_condition(subject, condition_id, ctx.source)

        # Charge-worker 2026-09-28: a mark the actor spent to power an effect is itself sometimes the
        # trigger of a further passive ("Storm-Heart Engine: once per turn when you consume a Charge to
        # empower a Lightning talent, choose one..."). No hook told a plug-in a mark was actually spent
        # (as opposed to placed, or expiring on its own); this is the smallest one that does.
        ext.run("mark_spent", ctx, name, subject)


def _mark_names(effect: dict[str, Any]) -> list[str]:
    """Charge-worker 2026-09-28: "mark" on if_marked/if_not_marked is usually one name, but some checks are
    really "bearing X or Y" (Lightning's Conductive is implied by already being Charged: "a creature ... is
    Conductive if ... it is currently Charged"). Accepts a single string or a list, either way."""
    raw = effect.get("mark")
    names = raw if isinstance(raw, list) else [raw]
    return [str(name).strip() for name in names if str(name or "").strip()]


def _marked_subjects(ctx: Context, effect: dict[str, Any]) -> list[ActorState]:
    """The subjects an if_marked/if_not_marked check considers: the actor itself for a self-check
    ("If you are Charged..."), otherwise this activation's own target(s) -- never every creature bearing
    the mark, so the check never widens who else the ability can affect."""
    if effect.get("applies_to") == "self":
        return [ctx.actor]
    return [ctx.target] if ctx.target is not None else list(ctx.targets)


def opened_before(engine: Any, actor_id: str, target_id: str) -> bool | None:
    """Whether the target was already Opened before the strike ``open_guard`` last handled (None: no such strike right now).
    Opened is placed by the very strike that "hits an Opened creature" / whose target "was already Opened", and ``open_guard`` runs
    before the strike's on-hit effects, so those read this instead of the mark (riders lane 2, 2026-09-29).  It stands until the
    same fighter rolls another attack or starts another typed action."""
    snap = getattr(engine, "_typed_opened_before", None)
    if not snap or snap[0] != actor_id or snap[1] != target_id:
        return None
    if any(event.event_type == "ATTACK_ROLLED" and event.actor_id == actor_id for event in engine.events[snap[3]:]):
        return None
    return bool(snap[2])


def _bore_mark(ctx: Context, subject: ActorState, owner: str, name: str) -> bool:
    """Whether ``subject`` bears the mark for this check: Opened inside a strike reads the pre-strike state (``opened_before``);
    every other mark, and Opened outside a strike, is read live."""
    was = opened_before(ctx.engine, owner, subject.entity_id) if _mark_slug(name) == "opened" else None
    return was if was is not None else bears_mark(subject, owner, name)


def block_if_marked(ctx: Context, effect: dict[str, Any]) -> None:
    """Gate nested effects on the subject already bearing the actor's named mark (owner 2026-09-26,
    e.g. "against a creature bearing your Stellar Mark, deal an extra..."): runs ``effects`` only for
    whichever of this activation's own targets qualify -- never widens who else the ability affects."""
    names = _mark_names(effect)
    nested = effect.get("effects") or []
    if not names or not nested:
        return
    owner = ctx.actor.entity_id
    pool = _marked_subjects(ctx, effect)
    def marked(subject: ActorState, name: str) -> bool:
        if effect.get("at") == "hit":
            return bool(ctx.damage_cache.get("_marks_at_hit", {}).get(subject.entity_id, {}).get(name))
        return _bore_mark(ctx, subject, owner, name)

    subjects = [subject for subject in pool if subject is not None and any(marked(subject, name) for name in names)]
    if not subjects:
        return
    inner = replace(ctx, targets=subjects, target=subjects[0] if len(subjects) == 1 else None)
    run_effects(inner, nested)


def block_if_not_marked(ctx: Context, effect: dict[str, Any]) -> None:
    """The complement of if_marked (Charge-worker 2026-09-28: Earthbind Line's "the first time a hostile
    creature crosses the line, it gains one Burden Mark. If it already has your Burden Mark, [save]
    instead" -- an either/or that if_marked alone cannot express): runs ``effects`` only for subjects
    that do NOT already bear any of the named marks."""
    names = _mark_names(effect)
    nested = effect.get("effects") or []
    if not names or not nested:
        return
    owner = ctx.actor.entity_id
    pool = _marked_subjects(ctx, effect)
    subjects = [subject for subject in pool if subject is not None and not any(_bore_mark(ctx, subject, owner, name) for name in names)]
    if not subjects:
        return
    inner = replace(ctx, targets=subjects, target=subjects[0] if len(subjects) == 1 else None)
    run_effects(inner, nested)


def block_forced_movement(ctx: Context, effect: dict[str, Any]) -> None:
    """A push or a pull.  ``direction`` (factory_authoring/typed_structure.derive_forced_movement_directions reads it from the printed
    words): "toward" / "away" the caster, "toward_center" / "away_center" the centre of the area the effect fills (hunt 3, bug 1:
    Collapsing Gap, Cyclone Prison and Gate of the Inner Sea pull toward the centre of their area), none = away from the caster."""
    base_distance = int(effect.get("distance_ft") or 0)
    direction = effect.get("direction")
    pull, centred = direction in ("toward", "toward_center"), direction in ("toward_center", "away_center")
    for subject in _default_subject(ctx, effect, harmful=True):
        distance = base_distance
        if effect.get("max_size_cells") and _size(ctx, subject, "resist", {"forced"}) > int(effect["max_size_cells"]):
            continue  # Push: "if it is Large or smaller" (a Large creature is 2 squares wide)
        if effect.get("max_size_larger") is not None and _size_rank(ctx, subject, "resist", {"forced"}) > \
                _size_rank(ctx, ctx.actor, "act", {"forced"}) + int(effect["max_size_larger"]):
            continue  # Draw the Line's Pull: "if it is your size or smaller"
        from . import ext
        if subject.active and subject is not ctx.actor and distance > 0:
            from . import ext

            # A push or pull lengthened by a talent or an area (rider lane C14: combat/ext/push_lengthening.py); no answer
            # leaves the printed distance.
            longest = distance + sum(int(value) for value in ext.run("forced_movement_bonus", ctx, subject, effect)
                                     if type(value) is int and value > 0)
            # Optional push/pull distances retain the ordinary forced-movement
            # row, including save defenses and the moved creature's reactions.
            # A mandatory restriction ("the forced movement fails") is a separate contract from that optional choice:
            # it caps whatever distance was chosen, so the printed clause still holds when another ability is also
            # choosing this push (Moon's Pull). The smallest answer is the cap; 0 ends the movement without asking.
            caps = [int(value) for value in ext.run("forced_movement_restriction", ctx, subject, effect, longest)
                    if type(value) is int and 0 <= value <= longest]
            cap = min(caps) if caps else None
            if cap == 0:
                continue
            choices = [value for value in ext.run("forced_movement_distance", ctx, subject, effect, longest)
                       if value is not None]
            chosen = choices[0] if len(choices) == 1 and type(choices[0]) is int and 0 <= choices[0] <= longest else longest
            if cap is not None:
                chosen = min(chosen, cap)
            if chosen > 0:
                _push(ctx, subject, chosen, pull=pull, centred=centred)


def _chosen_direction(ctx: Context, target: ActorState, distance_ft: int) -> tuple[int, int] | None:
    """The one-square step a plug-in chose for this forced movement, or None for the printed aim.

    General seam for any printed line that leaves the direction of a push to its user rather than
    deriving it from the caster ("up to 10 feet in one legal direction other than directly upward":
    Hard Whip). A plug-in answers one (dx, dy) unit step through the ``forced_movement_direction``
    hook; anything that is not exactly two integers in -1..1 with at least one nonzero is ignored,
    so an unanswered or malformed hook leaves the ordinary away/toward/centre routing untouched.
    The explicit step ``(0, 0)`` suppresses movement when a constrained policy has no legal heading.
    Called once per push, before any step, so the whole route is straight and legal.
    """
    from . import ext

    for answer in ext.run("forced_movement_direction", ctx, target, distance_ft):
        try:
            step_x, step_y = answer  # a plug-in answers one two-item step
        except (TypeError, ValueError):
            continue
        if (type(step_x) is int and type(step_y) is int
                and -1 <= step_x <= 1 and -1 <= step_y <= 1):
            return step_x, step_y
    return None


def _push(ctx: Context, target: ActorState, distance_ft: int, *, pull: bool, centred: bool = False) -> None:
    from .gate2_runtime_models import Position

    engine, actor = ctx.engine, ctx.actor
    # A reaction to being pushed or pulled (owner 2026-09-26, R2): the moved creature's own, then an ally's; "reduce
    # the movement by 10 feet" shortens it, down to none.
    from . import typed_reactions

    from .technique_interception import forced_distance, movement_committed
    distance_ft = forced_distance(engine, actor.entity_id, ctx.source, distance_ft, target.entity_id)
    distance_ft = typed_reactions.on_forced_movement(engine, target, actor, distance_ft)
    from .movement_paths import _reduced_by_hook
    distance_ft = _reduced_by_hook(target, ctx, distance_ft)
    if distance_ft < engine.grid.square_size_ft:
        return
    # Away from, or toward, the caster -- or the centre of the area, when the row is centred and the effect has one (a line or a
    # cone has none: it runs out from its caster, who is the point a blast from it pushes away from).
    anchor = actor.position
    if centred and ctx.typed.get("_area_centre"):
        anchor = Position(x=ctx.typed["_area_centre"][0], y=ctx.typed["_area_centre"][1])
    requested_cells = max(1, distance_ft // engine.grid.square_size_ft)
    chosen = _chosen_direction(ctx, target, distance_ft) if not pull else None
    def route():
        current = target.position
        for _ in range(requested_cells):
            if chosen is not None:
                # A printed line that leaves the direction to its user ("up to 10 feet in one legal
                # direction other than directly upward": Hard Whip) asked here once, for every step.
                # It is already the step to take, so no pull/away re-aim follows.
                step_x, step_y = chosen
            else:
                # Re-aim pulls each square so they stop at the anchor.
                step_x = (anchor.x > current.x) - (anchor.x < current.x)
                step_y = (anchor.y > current.y) - (anchor.y < current.y)
                if not pull:
                    step_x, step_y = -step_x, -step_y
            if not (step_x or step_y):
                break
            current = Position(x=max(0, current.x + step_x), y=max(0, current.y + step_y), z=current.z)
            yield current
    from .movement_paths import forced_steps
    path, blocked_at = forced_steps(engine, target, route(), ctx.source, ctx.intent, requested_cells)
    movement_committed(engine, actor.entity_id, ctx.source, target.entity_id, (len(path) - 1) * engine.grid.square_size_ft)
    # General seam (owner 2026-10-13): a completed push or pull reports
    # the distance it actually moved, so a printed rule that answers
    # "when you push a creature at least N feet" (Brutal Momentum) can
    # read it. Pure receipt: listeners record their own events; the
    # engine changes nothing here.
    from . import ext
    ext.run("forced_movement_committed", engine, actor, target,
            (len(path) - 1) * engine.grid.square_size_ft, "pull" if pull else "push")
    if blocked_at is not None and pull is False:
        # Impact Collision (Brute sphere; combat/ext/gu_brute.py): forced movement stopped short of what was asked
        # for. A plug-in decides what (if anything) that means for the ability that pushed; this is the smallest
        # hook call that lets one know a collision happened and by how much (owner 2026-09-28, "we need to automate
        # every aspect before another playtest" -- no existing hook point covered "forced movement was cut short").
        from . import ext

        ext.run("collision", ctx, target, blocked_at, (requested_cells - (len(path) - 1)) * engine.grid.square_size_ft)


def block_movement(ctx: Context, effect: dict[str, Any]) -> None:
    # Optional subject movement owns its controller choice and immediate landing.
    # No provider/legacy policy retains the historical grants and GM fallback.
    from . import ext
    if any(answer is True for answer in ext.run_strict("subject_reposition", ctx, effect)):
        return
    # "speed": a Dash (e.g. Stomping Step) grants movement equal to the actor's current Speed; "half_speed": Shadow
    # Step and the like (mind, 2026-09-28) -- teleport_reach already reads both for the action's own range_ft.
    token = effect.get("distance_ft")
    if token == "speed" and effect.get("applies_to") in (None, "self") and any(row.get("no_dash") for row in condition_rules(ctx.actor)):
        ctx.rider("Blocked: it cannot benefit from the Dash action right now.")
        return  # Clinging Seal (no_dash in combat/rules/typed_conditions.json)
    distance = ctx.engine._effective_speed(ctx.actor) if token == "speed" else \
        ctx.engine._effective_speed(ctx.actor) // 2 if token == "half_speed" else int(token or 0)
    # A printed step whose length names the damage that triggered it
    # (Storm-Marrow Guard: 5 ft, or 10 ft for thunder, lightning or
    # falling damage) carries distance_ft_by_cause beside its base
    # distance. The cause is the triggering hit's committed damage
    # type, or the committed source when the type alone cannot name it
    # (falling damage commits as Bludgeoning from system:combat.falling,
    # so the source names it). General seam: any movement effect may
    # scale its distance by the damage that triggered it.
    scaled = effect.get("distance_ft_by_cause")
    if isinstance(scaled, dict) and effect.get("applies_to") in (None, "self") \
            and token not in ("speed", "half_speed", None):
        for cause in _triggering_damage_causes(ctx):
            if cause in scaled:
                distance = int(scaled[cause])
                break
    if effect.get("mode") == "teleport" or effect.get("type") == "teleport":
        # A sealing effect (Dimensional Seal, Space) can deny a creature's own self-teleport (rule key
        # no_teleport in combat/rules/typed_conditions.json; worker w2-support 2026-09-28).
        if effect.get("applies_to") in (None, "self") and any(row.get("no_teleport") for row in condition_rules(ctx.actor)):
            ctx.rider("Blocked: sealed against teleportation right now.")
            return
        if ctx.destination is not None and effect.get("applies_to") in (None, "self"):
            # A candidate may bind a place before its player has chosen one (for
            # example a menu shortcut). Optional providers own that decision;
            # no provider preserves the historical bound/AI execution path.
            from . import ext
            from .ext.teleport_steps import hop_key, hop_reach

            represented_reach = hop_reach(ctx, effect, distance)
            key = hop_key(ctx, represented_reach)
            if key in ctx.hop_completed:
                return
            answers = ext.run_strict("self_teleport_destination", ctx, effect, represented_reach)
            answer = next((answer for answer in answers if answer is not None), None)
            if answer is not None:
                ctx.destination = answer.square
                if answer.square is not None:
                    _teleport(ctx, answer.square)
                else:
                    from .ext.teleport_steps import payment_text
                    ctx.rider(f"{ctx.action.display_name}: {ctx.actor.display_name} stays where it is; {payment_text(ctx)}.")
                ctx.hop_completed.add(key)
                return
            _teleport(ctx, ctx.destination)
            return
        if effect.get("applies_to") in (None, "self"):
            # No square is bound to this action: the printed rule is "Teleport to an unoccupied space you can see
            # within range", so the user picks it. A human is asked through the bounded choice transport
            # (combat/ext/teleport_steps.ask_destination, shared by every self-teleport, asked once per hop so the
            # parser's second spelling of the same teleport lands on the same square, and carried on the intent so
            # a reaction interrupting between paying the cost and choosing does not drop it). Only a self row asks:
            # a row that teleports someone else has no owner of that square here, so it keeps the GM instruction
            # below. Nothing answering (an AI combatant, no transport) and a decline both stay put, and the line
            # says which of the two happened.
            from .ext.teleport_steps import ask_destination, hop_key, hop_reach, payment_text

            represented_reach = hop_reach(ctx, effect, distance)
            key = hop_key(ctx, represented_reach)
            if key in ctx.hop_completed:
                return
            answer = ask_destination(ctx, represented_reach, name=str(ctx.action.display_name))
            if answer.square is not None:
                _teleport(ctx, answer.square)
            elif answer.asked:
                ctx.rider(f"{ctx.action.display_name}: {ctx.actor.display_name} stays where it is; {payment_text(ctx)}.")
            else:
                ctx.rider(f"Teleport up to {distance or 'range'} feet: place the creature on the map.")
            if answer.asked:
                # Mark only after the gate returns: ChoicePause must replay the attempt, not suppress it.
                ctx.hop_completed.add(key)
            return
        ctx.rider(f"Teleport up to {distance or 'range'} feet: place the creature on the map.")
        return
    from .technique_interception import movement_distance, movement_committed
    # Only a literal zero-distance effect denotes Disengage. A positive grant
    # exhausted by a shared cap (or a Speed-based grant at Speed 0) does not.
    explicit_disengage = token in (None, 0)
    distance = movement_distance(ctx.engine, ctx.actor.entity_id, ctx.source, ctx.actor.entity_id, distance)
    movement_committed(ctx.engine, ctx.actor.entity_id, ctx.source, ctx.actor.entity_id, distance)
    ctx.actor.movement_remaining_ft += distance
    if token == "speed":
        from .flight import dash
        dash(ctx.engine, ctx.actor, typed=True)
    if effect.get("no_opportunity_attacks"):
        # Only this movement is free of opportunity attacks (owner 2026-09-27 playtest: after a "move without provoking"
        # step, nothing provoked for the rest of the turn); gate2_engine._resolve_leave_reach spends it step by step.
        if distance > 0:
            ctx.actor.turn_flags["oa_free_ft"] = int(ctx.actor.turn_flags.get("oa_free_ft") or 0) + distance
        elif explicit_disengage:
            ctx.actor.turn_flags["disengaged"] = True
    ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=ctx.actor.entity_id, payload={"distance_ft": distance})


def block_remaining_movement(ctx: Context, effect: dict[str, Any]) -> None:
    """Change movement left this turn, not Speed (Restraining Hook's two save outcomes)."""
    for subject in _default_subject(ctx, effect, harmful=True):
        before = subject.movement_remaining_ft
        remaining = int(effect["becomes"]) if effect.get("becomes") is not None else before + int(effect.get("flat") or 0)
        subject.movement_remaining_ft = max(0, remaining)
        ctx.engine._append_event("MOVEMENT_GRANTED", ctx.source, actor_id=subject.entity_id,
                                 payload={"distance_ft": subject.movement_remaining_ft - before})


def teleport_reach(engine: Any, actor: ActorState, action: ActionDefinition) -> int | None:
    """How far a self-teleport ability (compiled SELF with its reach in range_ft: combat/factory_compiler.py _target_kind)
    takes its user, in feet; None when the ability is not one. "Speed" distances follow the user's current Speed."""
    typed = (action.parameters or {}).get("typed") or {}
    # "picks_destination": a plug-in's own self row that needs the square too (rider lane C8: Black Current's River-Cut route).
    rows = [effect for effect in typed.get("effects") or [] if isinstance(effect, dict) and effect.get("applies_to") in (None, "self")
            and (effect.get("type") == "teleport" or (effect.get("type") == "movement" and effect.get("mode") == "teleport")
                 or effect.get("picks_destination"))]
    if not rows or typed.get("area") or action.target_kind != "SELF":
        return None
    reach = int(action.range_ft or 0)
    for effect in rows:
        distance = effect.get("distance_ft")
        if distance == "speed":
            reach = max(reach, engine._effective_speed(actor))
        elif distance == "half_speed":
            reach = max(reach, engine._effective_speed(actor) // 2)
        elif str(distance or "").isdigit():
            reach = max(reach, int(distance))
    return reach or None


def _teleport(ctx: Context, destination: Any) -> None:
    """Move the user to the chosen square: no path, no opportunity attacks, no moving-through saves; entering an area
    there counts (combat/zones.py on_moved)."""
    teleport_subject(ctx, ctx.actor, destination)


def teleport_subject(ctx: Context, actor: ActorState, destination: Any, *, movement_context: str = "WILLING", unwilling: bool = False, forced: bool | None = None,
                     settlement_source_id: str | None = None, settlement_feature_id: str | None = None) -> None:
    """Shared self/subject landing; ctx.actor owns payment, actor owns footprint and gates.

    Destination providers validate reach and the controller's sight. This commits
    the moved subject through the same teleport gates, movement ledger and zones.
    Derived hops may supply their own public settlement source/feature identity
    for distance receipts while retaining the triggering intent and its context.
    Omitted identities retain the executing context's source and action feature.
    """
    engine = ctx.engine
    # Every teleport adapter, including direct extension calls, observes the
    # same subject-level seal. Keep the action's existing payment semantics.
    if any(row.get("no_teleport") for row in condition_rules(actor)):
        ctx.rider(f'{actor.display_name} cannot teleport right now.')
        return
    start = actor.position
    from .technique_interception import movement_distance, movement_committed
    distance = engine.grid.distance_ft(start, destination)
    maximum = movement_distance(engine, ctx.actor.entity_id, ctx.source, actor.entity_id, distance)
    if distance > maximum:
        ctx.rider(f'{ctx.action.display_name} was weakened: the chosen teleport destination is beyond the remaining {maximum} feet it allows, so no teleport occurs.')
        return
    if destination == start or not engine.grid.placement_legal(destination, footprint=engine._footprint(actor),
                                                                occupied_cells=engine._occupied_cells_except(actor.entity_id)):
        return
    from . import ext

    if False in ext.run_strict("subject_teleport_attempt", ctx, actor, start, destination):
        return
    if actor is ctx.actor:
        gate_ctx = ctx
    else:
        from .ext.ability_source import numbers_of
        gate_ctx = replace(ctx, actor=actor, typed={**ctx.typed, "numbers": numbers_of(engine, actor)})
    if ext.has("teleport_gate") and ext.any_false("teleport_gate", gate_ctx, start, destination):
        return  # a plug-in stopped it (Cut the Road Behind You: the road is sealed and the check failed)
    if False in ext.run("teleport_check", engine, actor, start, destination):
        return  # a sealing array (Formations, Sealing Gate) made the teleport fail: the CP and action are spent
    # Context is explicit at the shared landing seam so rules that restrict a
    # creature's willing departure do not prevent another creature forcing it.
    if False in ext.run("teleport_context_check", engine, actor, start, destination, movement_context):
        return
    from .movement_sequences import sequence, receipt
    from .ext.ability_source import mechanic_of
    with sequence(engine, actor):
        ext.run_strict("teleport_begin", ctx, actor, start, destination, movement_context,
                       unwilling, forced, mechanic_of(ctx.action) if settlement_feature_id is None
                       else str(settlement_feature_id))
        actor.position = destination
        movement_committed(engine, ctx.actor.entity_id, ctx.source, actor.entity_id, distance)
        consent_forced = False if actor.entity_id == ctx.actor.entity_id else forced
        selection = receipt(engine, actor)
        movement_event = engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=actor.entity_id,
                         payload={"destination": destination.model_dump(mode="json"),
                                  "path": [start.model_dump(mode="json"), destination.model_dump(mode="json")],
                                  "cost_ft": 0, "teleport": True,
                                  # Actor identity does not establish consent.
                                  # Subject movement rows may provide an explicit
                                  # `forced` rule; otherwise a moved ally's consent
                                  # remains unknown in passive receipts.
                                  "forced": consent_forced,
                                  **({"movement_selections": selection} if selection else {})})
        from . import zones

        zones.on_moved(engine, actor, start, destination, forced=True)
        ext.run_strict("teleport_settled", ctx, actor, start, destination, unwilling)
        from .movement_receipts import teleport_committed

        teleport_committed(ctx, actor, start, destination, movement_event,
                       movement_context=movement_context, unwilling=unwilling, forced=forced,
                       settlement_source_id=settlement_source_id,
                       settlement_feature_id=settlement_feature_id)


EXPLOIT_PICK = CONDITION_PREFIX + "exploit_pick"


def ranged_attack_now(ctx: Context) -> bool:
    return ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5


def apply_exploit(ctx: Context, target: ActorState) -> None:
    """The Piercing Needle's Exploits on a melee hit: the rules, Focus costs and choices live in combat/ext/needle.py."""
    from . import ext

    ext.run_strict("apply_exploit", ctx, target)


def block_pick_exploit(ctx: Context, effect: dict[str, Any]) -> None:
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == EXPLOIT_PICK:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    ctx.engine._apply_condition(ctx.actor, EXPLOIT_PICK, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"exploit": effect.get("exploit"), "label": f"Exploit: {effect.get('name') or ''}"})


OPEN_THE_GATE = CONDITION_PREFIX + "open_the_gate"
GATE_CHOICES = {"centerline": "Centerline Impact", "hooking": "Hooking Step", "breath": "Breath-Checking Strike"}
NO_OPPORTUNITY = CONDITION_PREFIX + "no_opportunity_attacks"


def open_guard(ctx: Context, target: ActorState, *, damaged: bool) -> None:
    """Iron Fist's Opening (owner 2026-09-28, "automate every aspect"): the target is Opened by the striker until the end
    of the striker's next turn (a mark, so Form talents' "if the target was already Opened" can read it), and once a turn
    Open the Gate: Centerline Impact (+PB damage, when the strike dealt damage), Hooking Step (5 feet of movement that does
    not provoke from it) or Breath-Checking Strike (it cannot make opportunity attacks until the start of its next turn).
    The striker's pick stays until changed (the table's Open the Gate toggles); without one, Centerline Impact when the
    strike dealt damage, else Breath-Checking Strike."""
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_opened_before")
    from . import typed_reactions, ext

    if not any(row.get("block") == "opening" for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "opening")):
        return
    ctx.engine._typed_opened_before = (ctx.actor.entity_id, target.entity_id, bears_mark(target, ctx.actor.entity_id, "Opened"), len(ctx.engine.events))
    block_mark(Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache,
                       explicit_self_recipient=getattr(ctx, "explicit_self_recipient", False)),
               {"mark": "Opened", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    if ctx.actor.turn_flags.get("open_the_gate"):
        return
    # Optional replacements of a named hit benefit are owned, default-inert
    # plug-ins. Keep the Opening mark independent of the replaced benefit.
    if False in ext.run("hit_benefit_allowed", ctx, target, "open_the_gate"):
        return
    ctx.actor.turn_flags["open_the_gate"] = True
    picked = next((str((c.data or {}).get("choice")) for c in ctx.actor.conditions.values() if c.condition_id == OPEN_THE_GATE), None)
    choice = picked if picked in GATE_CHOICES and (picked != "centerline" or damaged) else ("centerline" if damaged else "breath")
    source = f"{ctx.source}.open_the_gate"
    if choice == "centerline":
        amount = int(ctx.numbers.get("pb") or 2)
        ctx.engine._commit_damage(target, amount, "BLUDGEONING", source, ctx.actor.entity_id, None, reaction_depth=0)
    elif choice == "hooking":
        ctx.actor.movement_remaining_ft += 5
        ctx.actor.turn_flags["oa_free_ft"] = int(ctx.actor.turn_flags.get("oa_free_ft") or 0) + 5
        ctx.engine._append_event("MOVEMENT_GRANTED", source, actor_id=ctx.actor.entity_id, payload={"distance_ft": 5})
    else:
        ctx.engine._apply_condition(target, NO_OPPORTUNITY, source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"label": "No opportunity attacks (Breath-Checking Strike)"})
    ctx.rider(f"Open the Gate: {GATE_CHOICES[choice]}")


def block_open_the_gate(ctx: Context, effect: dict[str, Any]) -> None:
    """The table's toggle: which Open the Gate effect this Iron Fist fighter uses (kept until changed)."""
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == OPEN_THE_GATE:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    ctx.engine._apply_condition(ctx.actor, OPEN_THE_GATE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"choice": effect.get("choice"), "label": f"Open the Gate: {GATE_CHOICES.get(str(effect.get('choice')), '')}"})


NO_TEMP_HP = CONDITION_PREFIX + "no_temp_hp"
NO_INVISIBLE = CONDITION_PREFIX + "no_invisible"


def block_stance(ctx: Context, effect: dict[str, Any]) -> None:
    from . import stances

    stances.start(ctx, effect)


def block_deny_temp_hp(ctx: Context, effect: dict[str, Any]) -> None:
    """"Cannot gain Temporary HP until the start of your next turn" (Void Needle's Empty Vitality, Nullifying Strike)."""
    for subject in _default_subject(ctx, effect, harmful=True):
        if subject.active:
            ctx.engine._apply_condition(subject, NO_TEMP_HP, ctx.source, ctx.actor.entity_id,
                                        expires_on=stated_expiry(ctx, effect, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Cannot gain temporary hit points"})


def block_deny_invisible(ctx: Context, effect: dict[str, Any]) -> None:
    """"Cannot gain the Invisible condition from an ordinary temporary supernatural effect" (Unsettle Invisibility)."""
    for subject in _default_subject(ctx, effect, harmful=True):
        if subject.active:
            # effect_expiry reads the row's typed duration too: a printed sentence the public export scrambles must not
            # silently replace "until the end of your next turn" with this default (F10 batch, Demon-Subduing Tag).
            ctx.engine._apply_condition(subject, NO_INVISIBLE, ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, effect, subject, condition=True, fallback=None)
                                        or "START_OF_SOURCE_NEXT_TURN",
                                        data={"label": "Cannot turn Invisible"})


def block_ruin_channel(ctx: Context, effect: dict[str, Any]) -> None:
    """Ruin Channel: the next hit before the start of its next turn carries the Realm's Ruin damage (combat/unmaking.py)."""
    from . import unmaking

    ctx.engine._remove_condition(ctx.actor, unmaking.CHANNEL, ctx.source)
    ctx.actor.turn_flags["ruin_channel_round_pb"] = int(ctx.numbers.get("pb") or 2)
    ctx.engine._apply_condition(ctx.actor, unmaking.CHANNEL, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"dice_by_cl": effect.get("dice_by_cl"), "damage_type": str((effect.get("damage_types") or ["force"])[0]).upper(),
                                      "label": "Ruin Channel (charged)"})


def block_deny_reactions_against(ctx: Context, effect: dict[str, Any]) -> None:
    """"Cannot take Reactions against you until the start of your next turn" (Sting, Saint-Body Rebuke)."""
    from . import unmaking

    for subject in _default_subject(ctx, effect, harmful=True):
        if subject.active:
            ctx.engine._apply_condition(subject, unmaking.NO_REACTIONS_AGAINST, ctx.source, ctx.actor.entity_id,
                                        expires_on=stated_expiry(ctx, effect, subject, condition=True) or "START_OF_SOURCE_NEXT_TURN",
                                        data={"against": ctx.actor.entity_id, "label": f"No Reactions against {ctx.actor.display_name}"})


def block_toggle_overdraw(ctx: Context, effect: dict[str, Any]) -> None:
    from . import unmaking

    ctx.engine._remove_condition(ctx.actor, unmaking.OVERDRAW, ctx.source)
    if effect.get("on"):
        ctx.engine._apply_condition(ctx.actor, unmaking.OVERDRAW, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": "Overdraw ready"})


def _fold_temp_hp(ctx: Context, effects: list[dict[str, Any]], anchor: dict[str, Any], folded: set[int]) -> dict[str, Any]:
    from .effect_eligibility import eligible
    from .temp_hp_terms import fold_temp_hp
    return fold_temp_hp(effects, anchor, folded, eligible=lambda row: eligible(ctx, row))


def block_temp_hp(ctx: Context, effect: dict[str, Any]) -> None:
    from .typed_amounts import effect_flat
    from . import ext
    amount = 0
    for part in effect.get("parts") or [effect]:
        flat = effect_flat(part, ctx.numbers)
        amount += _roll(ctx, ctx.dice(_effect_dice(ctx, part), flat=flat, formula=part.get("formula")), "TEMP_HP", preserve_sign=True)
    for subject in _default_subject(ctx, effect, harmful=False):
        grant = min(amount, max(0, subject.maximum_hp - subject.current_hp)) if effect.get("cap_at_missing_hp") else amount
        # Providers adjust the original grant before the native one-time
        # interception in _grant_temp_hp. Keep follow-up bonuses out of the
        # already-reduced event payload.
        additional = sum(ext.run("temp_hp_grant_bonus", ctx, effect, subject, grant))
        grant += additional
        # The native grant owns the single interception query for every caller.
        ctx.engine._grant_temp_hp(subject, grant, ctx.source, ctx.actor.entity_id,
            original_amount=amount + additional,
            offer_cap=max(0, subject.maximum_hp - subject.current_hp) if effect.get('cap_at_missing_hp') else None)


def block_healing(ctx: Context, effect: dict[str, Any]) -> None:
    spec = _effect_dice(ctx, effect)
    from . import ext
    bonus = sum(ext.run("healing_roll_bonus", ctx, effect))
    rolled = _roll(ctx, ctx.dice(spec, flat=int(effect.get("flat") or 0) + bonus, formula=effect.get("formula")), "HEALING", preserve_sign=True)
    additions = ext.run_strict("healing_roll_resolved", ctx, effect, rolled)
    if any(type(value) is not int or value < 0 for value in additions):
        raise ValueError("healing_roll_resolved must return nonnegative integers")
    rolled += sum(additions)
    from .ext import life_state

    # The roster is the creatures this heal can actually reach: the dead (only a soul-return talent does) and
    # any creature whose prohibition names this recovery's source are not offered, chosen, or counted as
    # recipients. A prohibition scoped to sleep/rest leaves an ability's or potion's healing here.
    sources = healing_source_tags(effect)
    healing_targets = tuple(subject for subject in _default_subject(ctx, effect, harmful=False)
                            if not life_state.is_dead(subject) and not healing_denied(subject, sources))
    for subject in healing_targets:
        amount = stored_healing_reductions(ctx.engine, subject, rolled, healer=ctx.actor, source=ctx.source,
                                           source_tags=sources,
                                           sphere=str((getattr(ctx, "typed", None) or {}).get("sphere") or ""),
                                           power_resources=tuple(str(r) for r, _ in (getattr(getattr(ctx, "action", None), "costs", None) or ())),
                                           eligible_recipients=healing_targets,
                                           action_name=getattr(getattr(ctx, "action", None), "display_name", ""),
                                           activation_id=f"{id(getattr(ctx, 'intent', None))}:{ctx.source}")
        with healing_activation(ctx.engine, f"{id(getattr(ctx, 'intent', None))}:{ctx.source}"):
            ctx.engine._heal(subject, amount, ctx.source, ctx.actor.entity_id, notify_healed=True)


@contextmanager
def healing_activation(engine: Any, activation_id: str):
    """Expose the exact active healing activation to its synchronous aftermath hooks."""
    previous = getattr(engine, "_healing_activation_id", None)
    engine._healing_activation_id = str(activation_id)
    try:
        yield
    finally:
        if previous is None:
            engine.__dict__.pop("_healing_activation_id", None)
        else:
            engine._healing_activation_id = previous


def healing_pending(engine: Any, subject: ActorState, amount: int, healer: Any, source: str, kind: str) -> int:
    """Interception reductions after stored modifiers, before HP or Temporary HP."""
    from . import ext
    if kind not in {"hp", "temp_hp"} or type(amount) is not int:
        raise ValueError("healing_pending requires integer healing and a supported kind")
    if amount <= 0:
        return max(0, amount)
    replies = ext.run_checkpoint("healing_pending", engine, subject, amount, healer, source, kind)
    if any(type(value) is not int or value < 0 for value in replies):
        raise ext.CheckpointError("healing_pending reductions must be nonnegative integers")
    return max(0, amount - sum(replies))


def _reduced_healing(engine: Any, subject: ActorState, amount: int, *, healer: Any = None, source: str = "") -> int:
    """C15 compatibility entry for callers that commit HP themselves; do not intercept twice."""
    return healing_pending(engine, subject, stored_healing_reductions(engine, subject, amount, healer=healer, source=source),
                           healer, source, "hp")


#: Provenance keys a healing row carries to name the recovery it is, the same contract
#: combat/ext/regeneration.py documents for ``regeneration``. A rest recovery is
#: ``"rest": true`` and a sleep recovery ``"sleep": true``; a row without a key is ordinary
#: healing. A condition may refuse every source (``"healing_denied": true``) or only the
#: sources it names (``"healing_denied": ["sleep", "rest"]``).
HEALING_SOURCE_KEYS = ("regeneration", "sleep", "rest")


def healing_source_tags(effect: dict[str, Any] | None) -> frozenset[str]:
    """The recovery sources one healing row belongs to (empty for ordinary healing)."""
    return frozenset(key for key in HEALING_SOURCE_KEYS if isinstance(effect, dict) and effect.get(key))


def healing_denied(subject: ActorState, sources: frozenset[str] = frozenset()) -> bool:
    """Whether a condition on ``subject`` forbids this ordinary healing.

    ``healing_denied`` is ``True`` for every ordinary source, or a list of healing-source
    tags (``healing_source_tags``) that refuses only those recoveries. A scoped rule with no
    matching tag leaves the healing untouched, so "cannot regain Hit Points from sleep or
    rest" still allows an ability's or potion's healing in the same window.
    """
    for row in condition_rules(subject):
        denied = row.get("healing_denied")
        if denied is True:
            return True
        if isinstance(denied, (list, tuple, set, frozenset)) and sources.intersection(
                str(tag) for tag in denied):
            return True
    return False


def stored_healing_reductions(engine: Any, subject: ActorState, amount: int, *, consume: bool = True,
                              healer: Any = None, source: str = "", sphere: str = "",
                              power_resources: tuple[str, ...] = (), eligible_recipients: tuple[Any, ...] = (),
                              action_name: str = "", activation_id: str = "",
                              source_tags: frozenset[str] = frozenset()) -> int:
    """Healing reductions on the creature (block_healing_reduction): none, halved, minus a number; a "next healing"
    one is spent. A condition that halves healing (Sickened) counts too. Then what plug-ins take off as it lands, knowing who
    heals (healing_pending; rider lane C15). Positive offers first receive flat additions through healing_offered_bonus;
    consume=False queries additions and stored penalties without spending either allowance.

    ``healer``/``source``/``sphere`` and ``power_resources`` are feature provenance. ``eligible_recipients`` is the
    resolved effect roster; ``action_name`` and ``activation_id`` identify the choice prompt and its one live
    activation. They ride the general provenance-aware ``healing_offered_bonus_from`` seam so a provider can
    qualify the printed source and bind its choice to the actual action. Omitting provenance keeps existing callers
    on their historical path; the seam is inert without a provider.

    ``source_tags`` is the recovery provenance of the healing row itself (``healing_source_tags``) so a prohibition
    that names its sources refuses only those; a caller that cannot state its source is refused only by an unscoped
    ``healing_denied`` rule."""
    if healing_denied(subject, source_tags):
        return 0
    if consume and healer is not None and source:
        from .support_values import healing_offer
        amount = healing_offer(engine, subject, source, healer.entity_id, amount)
    if amount > 0:
        from . import ext

        bonuses = ext.run_checkpoint("healing_offered_bonus", engine, subject, amount, consume=consume)
        if any(type(value) is not int or value < 0 for value in bonuses):
            raise ext.CheckpointError("healing_offered_bonus must return nonnegative integers")
        amount += sum(bonuses)
        if healer is not None or source or sphere:
            sourced = ext.run_checkpoint("healing_offered_bonus_from", engine, subject, amount, consume=consume,
                                         healer=healer, source=source, sphere=sphere,
                                         power_resources=power_resources, eligible_recipients=eligible_recipients,
                                         action_name=action_name, activation_id=activation_id)
            if any(type(value) is not int or value < 0 for value in sourced):
                raise ext.CheckpointError("healing_offered_bonus_from must return nonnegative integers")
            amount += sum(sourced)
    if any(row.get("healing_halved") for row in condition_rules(subject)):
        amount //= 2
    amount = max(0, amount - sum(int(row.get("healing_minus") or 0) for row in condition_rules(subject)))  # Rot, Centipede (combat/ext/afflictions.py)
    for mid, modifier in list(subject.modifiers.items()):
        if modifier.target_field != "healing_reduction":
            continue
        kind = str(modifier.value)
        once = kind.startswith("next:")
        kind = kind.removeprefix("next:")
        amount = 0 if kind == "none" else amount // 2 if kind == "half" else max(0, amount - int(kind.split(":")[1]) if kind.startswith("minus:") else amount)
        if once and consume:
            del subject.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=subject.entity_id,
                                 target_ids=(subject.entity_id,), payload={"modifier_id": mid, "reason": "CONSUMED"})
    if amount > 0 and consume:
        from . import ext

        # Restrictions resolve before any surviving healing can be assigned elsewhere.
        amount = ext.reduce_amount("healing_received", engine, subject, amount)
        amount = ext.reduce_amount("healing_assigned", engine, subject, amount)
    return amount


def block_healing_reduction(ctx: Context, effect: dict[str, Any]) -> None:
    """"Reduce healing received by your Proficiency Bonus", "healing received is halved", "cannot regain Hit Points"
    (owner 2026-09-26): a modifier checked when healing lands. A misread (e.g. "reduced to 0 HP") stays rules text."""
    from factory_authoring.typed_structure import healing_reduction_amount

    evidence = str(effect.get("evidence") or "")
    kind = healing_reduction_amount(evidence)
    if kind is None:
        ctx.rider(evidence)
        return
    value = f"minus:{int(ctx.numbers.get('pb') or 2)}" if kind == "pb" else kind
    lowered = evidence.lower()
    if "next healing" in lowered or lowered.rstrip(". ").endswith(" once"):
        value, expires = f"next:{value}", effect_expiry(ctx, effect, ctx.target, fallback="UNTIL_REMOVED")
    elif "start of its next turn" in lowered or "start of their next turn" in lowered:
        expires = "START_OF_SELF_NEXT_TURN"
    else:
        expires = None  # the effect's own words or duration, else the start of the user's next turn (_modifier)
    _modifier(ctx, {**effect, **({"expires_on": expires} if expires else {}), "applies_to": effect.get("applies_to") or "target"},
              "healing_reduction", value, harmful=True, fallback="START_OF_SOURCE_NEXT_TURN")


def application_identity(ctx: Context) -> str:
    """The identity of one activation's owned modifier rows: the enclosing intent plus its applier.

    One activation's rows share this identity and are added together, which is what
    lets a single use of an ability apply several Speed rows that combine. Two
    activations that merely share a table intent must not: a delivery can dispatch
    for more than one owner inside one intent (each arriving area runs its own save
    under the movement intent that brought the creature in), so the intent alone
    would merge independently owned applications into one and hand the creature a
    penalty neither owner earned on its own.

    The applier is part of the identity rather than a separate grouping key so the
    name survives persistence: the row is stored once, and both this identity and
    its owner are restored by a cold reload.
    """
    applier = getattr(getattr(ctx, "actor", None), "entity_id", None) or "no-applier"
    intent = getattr(getattr(ctx, "intent", None), "intent_id", None) or "no-intent"
    return f"{intent}@{applier}"


def _modifier(ctx: Context, effect: dict[str, Any], field_name: str, value: Any, *, harmful: bool = False, fallback: Any = _ACTION) -> None:
    """Apply a modifier, independently declaring ownership and refresh scope.

    source_owned retains the applier for expiry. refresh_across_owners opts a
    printed nonstacking effect into refreshing the same ability from any user;
    absent that flag, independently owned modifiers retain their prior policy.
    """
    for subject in _default_subject(ctx, effect, harmful=harmful):
        if harmful and (field_name == "speed_halved" or (field_name == "speed_ft" and value < 0)) and effect.get("becomes") != 0:
            from . import motion

            if motion.floors_speed(ctx.engine, subject):  # Juggernaut: ordinary effects cannot cut its Speed (a Speed of 0 still works)
                ctx.rider(f"{subject.display_name}: Speed is not reduced (its Speed cannot drop below normal from ordinary effects).")
                continue
        # Using the same ability again refreshes its bonus rather than stacking it (owner 2026-09-26 tournament:
        # Domain Armament's +2 AC stacked every turn, 18 -> 42 AC, and fights ran out the round limit).
        # Effects of one activation still combine (the first one clears the previous use's modifiers).
        key = ("refreshed", ctx.source, subject.entity_id, field_name)
        if effect.get("refresh_across_owners") is True:
            key += (ctx.actor.entity_id,)  # two appliers can share one activation's cache
        if not ctx.damage_cache.get(key):
            ctx.damage_cache[key] = True
            for mid, modifier in list(subject.modifiers.items()):
                if modifier.source_definition_id == ctx.source and modifier.target_field == field_name and modifier.operation == "ADD" \
                        and (not effect.get("source_owned") or effect.get("refresh_across_owners") is True
                             or modifier.source_actor_id == ctx.actor.entity_id) \
                        and (isinstance(modifier.value, int) or modifier.value == value):
                    del subject.modifiers[mid]
                    ctx.engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(subject.entity_id,),
                                             payload={"modifier_id": mid, "reason": "REFRESHED"})
        # A negative Speed row is one independently owned application. Several
        # owners can resolve inside one shared table intent (each arriving area
        # dispatches its own save under the movement intent that brought the
        # creature in, combat/zones.py), so the intent alone does not say who
        # applied a row: two owners' slows would share one identity and be
        # added as a single activation. Naming the applier keeps independently
        # owned activations distinct while one activation's own rows still
        # share an identity and combine (motion.speed_adjustment).
        # The identity is persisted, so it must be stable across a reload.
        owned_slow = field_name == "speed_ft" and isinstance(value, int) and value < 0
        ctx.engine._add_modifier(subject, ctx.source, field_name, "ADD", value, "ALWAYS",
                                 expires_on=effect_expiry(ctx, effect, subject, fallback=fallback,
                                     modifier_source_actor_id=(ctx.actor.entity_id if (effect.get("source_owned") or owned_slow)
                                         else str(ctx.engine.state.current_actor_id or ctx.actor.entity_id))),
                                 application_id=(application_identity(ctx) if owned_slow else None),
                                 # An owned Speed row is filed under the actor that applied it, not
                                 # whoever the engine thinks is acting: an off-turn delivery (an
                                 # area resolving inside another creature's turn) must keep its own
                                 # owner, so its nonstacking grouping and its source-anchored expiry
                                 # stay independent. effect_expiry resolves START_OF_SOURCE_NEXT_TURN
                                 # against that same applier (modifier_source_actor_id above), so
                                 # stored ownership matches what the row states.
                                 **({"source_actor_id": ctx.actor.entity_id} if (effect.get("source_owned") or owned_slow) else {}))


_AC_AGAINST = re.compile(r"\bAC\b[^.;]*?\bagainst\b[^.;]*", re.I)


def ac_field(effect: dict[str, Any]) -> str:
    """Which AC an ``ac_bonus`` raises: "+2 AC against ranged attack rolls" (Domain Armament's Guard Mode) is no
    armour against a sword (owner 2026-09-26 tournament).  combat/typed_reactions.py's on_attack_hit counts the
    qualified fields; the sealed engine sums plain ``armor_class`` only."""
    match = _AC_AGAINST.search(str(effect.get("evidence") or ""))
    qualifier = f"{effect.get('on') or ''} {match.group(0) if match else ''}".lower()
    ranged, melee = bool(re.search(r"\branged\b", qualifier)), bool(re.search(r"\bmelee\b", qualifier))
    return "armor_class_vs_ranged" if ranged and not melee else "armor_class_vs_melee" if melee and not ranged else "armor_class"


def block_ac_bonus(ctx: Context, effect: dict[str, Any]) -> None:
    if effect.get("duration") == "triggering_attack":
        from .ext.attack_defenses import grant
        spec = ctx.typed.get("triggering_attack_spec")
        if spec is None:
            raise ValueError("Attack-only AC requires the triggering attack spec")
        for subject in _default_subject(ctx, effect, harmful=False):
            grant(spec, subject, ctx.source, int(effect.get("amount") or effect.get("flat") or 0))
        return
    _modifier(ctx, effect, ac_field(effect), int(effect.get("amount") or effect.get("flat") or 0))


def _speed_becomes(ctx: Context, effect: dict[str, Any], goal: int) -> None:
    """"Its Speed becomes 10 feet" (Gravity Domain's failed save): a set, not an add -- typed as ``flat: 10`` it sped every
    enemy up (fight audit 2026-09-29).  The engine reads only ADD ``speed_ft`` modifiers (gate2_engine._effective_speed), so
    the modifier is the gap between the goal and the Speed the creature would otherwise have.  That is worked out from its
    unconditioned Speed (a grapple or a Speed-zero condition that zeroes it now must not turn the set into a boost once it
    ends) and leaves out this ability's own earlier use, which ``_modifier`` is about to replace, not stack."""
    from dataclasses import replace
    from .motion import speed_adjustment

    for subject in _default_subject(ctx, effect, harmful=True):
        refreshing = not ctx.damage_cache.get(("refreshed", subject.entity_id, "speed_ft"))  # the first Speed effect of this use
        # Share motion.speed_adjustment's nonstacking/application arithmetic
        # so set-Speed conversions agree with the effective Speed the
        # creature has now. Refreshing this source excludes all of its old
        # rows, then replaces them with the gap to the requested goal.
        current = subject.speed_ft + speed_adjustment(ctx.engine, subject,
                                                    replacing_source=ctx.source if refreshing else None)
        # Keep an explicit self benefit explicit. Recasting it as a target
        # effect would let a self-centered area's harmful-recipient filter
        # exclude its user (e.g. a historical speed row beside a presence aura).
        applies = "self" if effect.get("applies_to") == "self" else "target"
        _modifier(replace(ctx, target=subject), {**effect, "applies_to": applies}, "speed_ft", goal - current, harmful=True)


def block_speed(ctx: Context, effect: dict[str, Any]) -> None:
    amount = effect.get("amount") if effect.get("amount") is not None else effect.get("flat")
    if effect.get("halved"):
        # "Halve the target's Speed until ...": a marker the Gate 4 engine's _effective_speed reads (owner 2026-09-28).
        _modifier(ctx, effect, "speed_halved", 1, harmful=True)
        return
    if effect.get("becomes") is not None:  # "Its Speed becomes 10 feet"
        _speed_becomes(ctx, effect, int(effect["becomes"]))
        return
    _modifier(ctx, effect, "speed_ft", int(amount or 0), harmful=int(amount or 0) < 0)


def block_resistance(ctx: Context, effect: dict[str, Any]) -> None:
    field_name = "damage_immunity" if effect.get("type") == "immunity" else "damage_resistance"
    for kind in effect.get("damage_types") or []:
        _modifier(ctx, effect, field_name, str(kind).upper())
    if effect.get("type") == "immunity":
        for name in effect.get("conditions") or []:
            _modifier(ctx, effect, "condition_immunity", str(name).lower())


def block_cleave(ctx: Context, effect: dict[str, Any]) -> None:
    """2024 Cleave: after a melee hit, one attack against a second creature within 5 feet of the first and within
    reach; its damage adds no ability modifier unless negative. Once per turn."""
    if ctx.typed.get("granted_attack"):
        return
    first = ctx.target
    if first is None or ctx.actor.turn_flags.get("typed_once_turn:cleave"):
        return
    reach = int(ctx.action.range_ft or 5)
    others = [actor for actor in ctx.engine.state.actors.values() if actor.active and actor.team_id != ctx.actor.team_id
              and actor.entity_id != first.entity_id and ctx.engine._distance_actor_to_actor(first, actor) <= 5
              and ctx.engine._distance_actor_to_actor(ctx.actor, actor) <= reach]
    if not others:
        return
    ordered = sorted(others, key=lambda actor: (actor.current_hp, actor.entity_id))
    from . import ext
    selections = ext.run_strict("optional_followup_target", ctx, effect, ordered, ordered[0].entity_id)
    if len(selections) > 1:
        raise ext.OptionalFollowupTargetConflict("one plug-in must own each optional follow-up target choice")
    second_id = str(selections[0]) if selections else ordered[0].entity_id
    if not second_id:
        return  # declined: the once-per-turn use stays available for a later hit this turn
    if second_id not in {actor.entity_id for actor in ordered}:
        raise ValueError("optional follow-up target is not eligible")
    ctx.actor.turn_flags["typed_once_turn:cleave"] = True
    second = ctx.engine.state.actors[second_id]
    weapon = ctx.typed.get("weapon") or {}
    base = DiceSpec(**weapon["damage"]) if weapon.get("damage") else DiceSpec(count=1, sides=4, modifier=0)
    dice = DiceSpec(count=base.count, sides=base.sides, modifier=base.modifier - max(0, int(effect.get("ability_mod") or 0)))
    damage_type = choose_damage_type(ctx, damage_choices({}, weapon), [second])
    spec = {"attack_bonus": int(ctx.numbers.get("attack_bonus") or 0), "range_ft": None, "damage": dice, "damage_type": damage_type, "parameters": {}}
    was_active = second.active
    hp_before = second.current_hp
    previous = getattr(ctx.engine, "_typed_pending_damage_type", None)
    ctx.engine._typed_pending_damage_type = damage_type
    first_event = len(ctx.engine.events)
    try:
        hit = ctx.engine._resolve_attack_spec(ctx.actor, second, spec, ctx.intent, source_definition_id=ctx.source, attack_index=99)
    finally:
        ctx.engine._typed_pending_damage_type = previous
    for event in ctx.engine.events[first_event:]:
        if (event.event_type == "ATTACK_ROLLED" and event.actor_id == ctx.actor.entity_id
                and event.source_definition_id == ctx.source and event.target_ids == (second.entity_id,)):
            event.payload["attack_label"] = "Cleave follow-up"
    _use_vex(ctx.engine, ctx.actor, second)
    _after_own_blow(ctx, second, was_active=was_active, hit=bool(hit), ranged=False, hp_before=hp_before)


def _enemy_adjacent_to_ranged(ctx: Context) -> bool:
    return ranged_attack_crowded(ctx)


def ranged_attack_crowded(ctx: Context) -> bool:
    """Pure nearby-hostile rule shared by strike resolution and target previews.

    A ranged attack has Disadvantage while a nearby hostile can see the attacker
    and is not Incapacitated (the existing 2024 rule).
    """
    if int(ctx.typed.get("range_ft") or 0) <= 5:
        return False
    from .target_knowledge import can_see

    close = any(other.active and other.team_id != ctx.actor.team_id
                and ctx.engine._distance_actor_to_actor(ctx.actor, other) <= 5
                and can_see(ctx.engine, other, ctx.actor)
                and not any(row.get("no_actions") for row in condition_rules(other))
                for other in ctx.engine.state.actors.values())
    from . import ext

    # "Being within 5 feet of a hostile creature does not impose Disadvantage on your Bow attacks" (Bow Body; ext hook
    # close_ranged_ok, rider lane C7 2026-09-30). Other sources of Disadvantage are untouched.
    return close and not (ext.has("close_ranged_ok") and any(ext.run("close_ranged_ok", ctx)))


def _use_vex(engine: Any, actor: ActorState, target: ActorState) -> None:
    """Spend target-specific next-roll modes at the existing typed result phase."""
    from .attack_modes import consume_targeted_next_attack

    consume_targeted_next_attack(engine, actor, target)


def block_vex(ctx: Context, effect: dict[str, Any]) -> None:
    """2024 Vex: Advantage on your next attack roll against that creature before the end of your next turn."""
    if ctx.target is None:
        return
    _use_vex(ctx.engine, ctx.actor, ctx.target)  # a fresh Vex replaces an unspent one
    ctx.engine._add_modifier(ctx.actor, ctx.source, "attack_mode_vs", "SET", f"ADVANTAGE:{ctx.target.entity_id}", "NEXT_ATTACK",
                             expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + 1}")


def _best_weapon_action(engine: Any, actor: ActorState) -> str | None:
    """The weapon a Disarm knocks away: the creature's hardest-hitting weapon attack still in hand."""
    dropped = {c.data.get("disables_action") for c in actor.conditions.values()}
    options = [(int((engine.action_catalog[action_id].parameters or {}).get("expected_damage") or 0), action_id)
               for action_id in actor.action_ids if ".weapon." in action_id and "#" not in action_id
               and not action_id.endswith(".pickup") and action_id in engine.action_catalog and action_id not in dropped
               and not (engine.action_catalog[action_id].parameters or {}).get("requires_held_weapon")]  # its own weapons only
    return max(options)[1] if options else None


def _restore_recovered_grip(ctx: Context, weapon: str | None) -> None:
    """A thrown weapon comes back into the hand that picks it up.

    Only an existing stowed grip is restored: legacy catalogs without managed
    grips stay inert, and Draw/Stow remains the only way to move a carried spare.
    """
    from .ext.equipment_hands import set_weapon_readiness
    from .ext.hand_occupancy import GRIP

    if not weapon:
        return
    grip = next((condition for condition in ctx.actor.conditions.values()
                 if condition.condition_id == GRIP and condition.data.get("weapon") == weapon), None)
    if grip is None or grip.data.get("held"):
        return
    set_weapon_readiness(ctx.engine, ctx.actor, str(weapon), True,
                         source=ctx.source, source_actor_id=ctx.actor.entity_id)


def block_recover_weapon(ctx: Context, effect: dict[str, Any]) -> None:
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.data.get("disables_action") == effect.get("weapon"):
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    _restore_recovered_grip(ctx, effect.get("weapon"))
    _reweigh(ctx)


def _reweigh(ctx: Context) -> None:
    """Every Factory fighter's load after a weapon or item changes hands (combat/carry.py; owner 2026-09-27)."""
    from . import carry

    for actor in ctx.engine.state.actors.values():
        if actor.entity_id in getattr(ctx.engine, "typed_actor_ids", set()):
            carry.refresh(ctx.engine, actor, ctx.source)


def block_drop_item(ctx: Context, effect: dict[str, Any]) -> None:
    """Drop something it carries (free, 2024): it lies at its feet until picked up; a weapon can't attack meanwhile."""
    from . import carry

    key = str(effect.get("item") or "")
    item = carry.item_of(carry.carrying_of(ctx.engine, ctx.actor.entity_id), key=key)
    if item is None or not carry.holds(ctx.engine, ctx.actor, key):
        return
    identity = carry.clear_owned_item_location(ctx.engine, ctx.actor, key, ctx.source)
    data = {**identity, "item_key": key, "item_name": item.get("name"), "dropped_at": ctx.actor.position.model_dump(mode="json")}
    if item.get("weapon_action"):
        data["disables_action"] = item["weapon_action"]  # the engine offers its "Pick up" within reach
    ctx.engine._apply_condition(ctx.actor, carry.DROPPED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)
    _reweigh(ctx)


def block_pickup_item(ctx: Context, effect: dict[str, Any]) -> None:
    from . import carry

    key = str(effect.get("item") or "")
    iid = carry.dropped(ctx.actor, key)
    if iid is None or not carry.can_pick_up(ctx.engine, ctx.actor, key):
        return
    item = carry.item_of(carry.carrying_of(ctx.engine, ctx.actor.entity_id), key=key) or {}
    carry.clear_owned_item_location(ctx.engine, ctx.actor, key, ctx.source)
    condition = ctx.actor.conditions.pop(iid)
    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid})
    _restore_recovered_grip(ctx, item.get("weapon_action"))
    _reweigh(ctx)


def block_shape_zone(ctx: Context, effect: dict[str, Any]) -> None:
    """Choose the talents its next areas of one kind carry ("Shape Darkness: Pure Darkness + Numbing Darkness"; owner
    2026-09-27): a free choice that stays until changed (combat/zones.py _shaped)."""
    from . import zones

    family = str(effect.get("zone") or "")
    for iid, condition in list(ctx.actor.conditions.items()):
        if condition.condition_id == zones.SHAPING and (condition.data or {}).get("zone") == family:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
    ctx.engine._apply_condition(ctx.actor, zones.SHAPING, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"zone": family, "zone_name": effect.get("zone_name"), "talents": list(effect.get("talents") or []),
                                      "label": effect.get("label")})


def block_toggle_augment(ctx: Context, effect: dict[str, Any]) -> None:
    from . import loadout

    loadout.toggle(ctx.engine, ctx.actor, str(effect.get("family") or ""), effect.get("augment"), ctx.source)


def block_hide(ctx: Context, effect: dict[str, Any]) -> None:
    from . import stealth

    stealth.hide(ctx.engine, ctx.actor, int(effect.get("bonus") or 0), ctx.source, str(effect.get("mode") or "NORMAL"), effect.get("inside"))


def block_search(ctx: Context, effect: dict[str, Any]) -> None:
    from . import ext, stealth

    stealth.search(ctx.engine, ctx.actor, int(effect.get("bonus") or 0), ctx.source)
    ext.run("after_search", ctx, effect)


def _reapply_weapon_state(ctx: Context, owner: ActorState, iid: str, data: dict[str, Any]) -> None:
    """A dropped/taken weapon's state lives in the owner's Disarmed condition; a change removes and re-applies it, so
    the change is in the event log (a saved fight reloads by replaying events, and in-place edits would not replay)."""
    condition = owner.conditions.pop(iid)
    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(owner.entity_id,),
                             payload={"condition_id": condition.condition_id, "instance_id": iid})
    ctx.engine._apply_condition(owner, condition.condition_id, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=data)


def block_grab_improvised(ctx: Context, effect: dict[str, Any]) -> None:
    """A stick, a table leg, a brass vase: held until thrown (the turn's free object interaction)."""
    from .object_interaction import claim
    claim(ctx.engine, ctx.actor, ctx.source)
    ctx.engine._apply_condition(ctx.actor, CONDITION_PREFIX + "improvised", ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED")


def block_take_weapon(ctx: Context, effect: dict[str, Any]) -> None:
    """Pick up another creature's dropped weapon within 5 ft (2024: an unattended object). Its owner has lost it until
    it disarms the taker, who can fight with it meanwhile."""
    for owner, iid in ctx.engine._dropped_weapons_near(ctx.actor)[:1]:
        data = {key: value for key, value in owner.conditions[iid].data.items() if key != "dropped_at"}
        _reapply_weapon_state(ctx, owner, iid, {**data, "held_by": ctx.actor.entity_id})
    _reweigh(ctx)


def block_release_grapple(ctx: Context, effect: dict[str, Any]) -> None:
    """A grappler may let go whenever it likes (2024), e.g. to move without dragging."""
    for other in ctx.engine.state.actors.values():
        for iid, condition in list(other.conditions.items()):
            if condition.condition_id in (CONDITION_PREFIX + "grappled", CONDITION_PREFIX + "pinned") and condition.source_actor_id == ctx.actor.entity_id:
                del other.conditions[iid]
                ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(other.entity_id,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid})


def block_escape_grapple(ctx: Context, effect: dict[str, Any]) -> None:
    """2024: a Grappled creature uses its Action for Athletics or Acrobatics against the escape DC."""
    held = lambda name: [(iid, condition) for iid, condition in ctx.actor.conditions.items() if condition.condition_id == CONDITION_PREFIX + name]  # noqa: E731
    from .ext.hold_escapes import escape_stage
    grips = escape_stage(held("pinned") + held("grappled"))
    if not grips:
        return
    from . import ext

    # A source-qualified escape benefit may ask which hold this Action tests. Hooks may
    # narrow the existing grips only; absent/conflicting/invalid results preserve legacy rolls.
    available = dict(grips)
    selections = [value for value in ext.run("escape_grips", ctx, available) if value is not None]
    if len(selections) == 1 and isinstance(selections[0], (list, tuple)):
        selected = selections[0]
        if (selected and all(isinstance(iid, str) and iid in available for iid in selected)
                and len(set(selected)) == len(selected)):
            grips = [(iid, available[iid]) for iid in selected]
    dc = max(int(condition.data.get("escape_dc") or 10) for _, condition in grips)

    if any(condition.data.get("escape_save") for _, condition in grips):
        # A grip whose rules say "may use its Action to repeat the saving throw" (the Living Painting Serpent's Coiling Stroke).
        ability = str(next(condition.data["escape_save"] for _, condition in grips if condition.data.get("escape_save"))).upper()
        from .ext.escape_checks import resolve_escape_save
        if resolve_escape_save(ctx.engine, ctx.actor, ability, dc, ctx.source,
                               [condition for _, condition in grips]):
            for iid, condition in grips:
                del ctx.actor.conditions[iid]
                ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                         payload={"condition_id": condition.condition_id, "instance_id": iid})
            _escaped(ctx, [condition for _, condition in grips], ability, "save")
        return
    from .ext.escape_checks import resolve_escape_check

    if resolve_escape_check(ctx, effect, dc, [condition for _, condition in grips],
                            ("grappled", "restrained") if held("pinned") else ("grappled",)):
        for iid, condition in grips:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
        _escaped(ctx, [condition for _, condition in grips], "STR", "check")  # Athletics or Acrobatics: physical


def _escaped(ctx: Context, grips: list[Any], ability: str, way: str) -> None:
    """Report the escape to the shared "a hold was escaped" seam (combat/ext/hold_escapes.py; inert without a listener)."""
    from .ext.hold_escapes import escaped, how_for

    escaped(ctx.engine, ctx.actor, grips, how_for(ability, ctx.actor), by=ctx.actor, source=ctx.source, way=way)


def _pair_turn(ctx: Context, target_id: str, hit: bool) -> None:
    """Dual Wielding Pair/Rhythm talents (owner 2026-09-26): what this turn's Lead and Answering Weapon attacks leave for
    Synchronous Accuracy, Following Strike and Tandem Offensive -- whether a Lead attack missed, who the Lead attacks and
    the Paired Strike went at, and the Lead's numeric bonus."""
    role, flags = ctx.typed.get("pair_role"), ctx.actor.turn_flags
    if role == "lead":
        flags["pair:lead_targets"] = sorted({*(flags.get("pair:lead_targets") or []), target_id})
        if not hit:
            flags["pair:lead_missed"] = True
        elif ctx.typed.get("tandem") and ctx.actor.resources.get("resource:core.martial_focus", 0) >= 1:
            flags["pair:tandem_magic"] = max(int(flags.get("pair:tandem_magic") or 0), int(ctx.typed.get("magic_bonus") or 0))
    elif role == "answer":
        flags["pair:paired_strike_done"] = True
        flags["pair:paired_target"] = target_id


def _tandem_bonus(ctx: Context) -> int:
    """Tandem Offensive: the Answering Weapon uses the higher of the two numeric bonuses (only the number)."""
    if ctx.typed.get("pair_role") != "answer":
        return 0
    return max(0, int(ctx.actor.turn_flags.get("pair:tandem_magic") or 0) - int(ctx.typed.get("magic_bonus") or 0))


def _paired_rhythm(ctx: Context) -> None:
    """Dual Wielding's Paired Rhythm: once per turn, hitting with both weapons of the pair regains Martial Focus."""
    ctx.actor.turn_flags[f"pair_hit:{ctx.typed['pair_role']}"] = True
    if ctx.typed.get("paired_rhythm") and ctx.actor.turn_flags.get("pair_hit:lead") and ctx.actor.turn_flags.get("pair_hit:answer") \
            and not ctx.actor.turn_flags.get("paired_rhythm_used"):
        ctx.actor.turn_flags["paired_rhythm_used"] = True
        resource = "resource:core.martial_focus"
        if resource in ctx.actor.resources and ctx.actor.resources[resource] < ctx.actor.resource_maximums.get(resource, 0):
            ctx.engine._gain_resource(ctx.actor, resource, 1, ctx.source)


WEAPON_METHOD_LOG = "_typed_weapon_methods"
WEAPON_METHODS_KEY = "weapon_methods"


def strike_record(ctx: Any) -> dict[str, Any] | None:
    """This one strike's transient record, the live dictionary every row of that strike may read and write, or None
    when no strike is being resolved.

    The general seam a printed trigger needs when the printed wording is about the hit itself ("if the hit deals
    damage", "when you use Breaking Method") rather than about the action's selected rows: an action's rows cannot
    say what the resolution actually did, and a rider that runs late must not be read as the hit's own damage.

    One record belongs to one strike (see ``_begin_strike``), so a second hit of an Extra Attack cannot inherit the
    first one's record. The record lives on the Context, not on the engine: the child Context of this hit's own
    riders and bonuses inherits it (they are part of the same strike), while a reaction attack that builds its own
    Context begins its own empty record and so cannot clear or overwrite the enclosing strike's. Nothing here is
    saved: it is resolution state that a commit never keeps.
    """
    record = getattr(ctx, "strike_record", None)
    return record if isinstance(record, dict) else None


def _note_weapon_method(ctx: Context, effect: dict[str, Any]) -> None:
    """General seam (owner 2026-10-05): remember the Weapon Method this hit actually executed.

    A printed trigger like "when you use Breaking Method" needs proof the method ran on this very hit, which
    an action's selected rows cannot give: block_weapon_method refuses a second one, and an on-hit row may be
    first_hit_only, so with Extra Attack a later hit would otherwise answer as though the method were its own.
    Recorded in this strike's own record (see ``strike_record``), so a nested reaction attack resolving in the
    middle of this hit cannot erase it; a method applied outside any strike keeps the engine-level fallback.
    Readable through ``executed_weapon_methods``.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, WEAPON_METHOD_LOG)
    entry = {"actor_id": ctx.actor.entity_id, "target_id": getattr(getattr(ctx, "target", None), "entity_id", None),
             "source": ctx.source,
             "effects": [dict(row) for row in effect.get("effects") or [] if isinstance(row, dict)]}
    record = strike_record(ctx)
    if record is None:
        ctx.engine.__dict__.setdefault(WEAPON_METHOD_LOG, []).append(entry)
    else:
        record.setdefault(WEAPON_METHODS_KEY, []).append(entry)


def executed_weapon_methods(ctx: Any, target: Any = None) -> list[dict[str, Any]]:
    """Every Weapon Method that executed for the hit now being resolved, oldest first.

    Read by ``after_hit_effects`` plug-ins whose printed trigger names a method (Iron Against Iron, combat/ext/
    weapons_sphere.py). ``target`` narrows to one creature. Empty when the fighter used no method on this hit,
    including a method the table's one-per-turn limit refused.

    The engine-level fallback (see ``_note_weapon_method``) belongs to resolution with no strike of its own and is
    consulted only then. While a strike is being resolved this strike's own record is the whole answer: a nested
    attack may have written its methods there, and the enclosing strike must not read another strike's record as its
    own, nor read an empty one as "look at the fallback".
    """
    target_id = getattr(target, "entity_id", target)
    record = strike_record(ctx)
    if record is None:
        log = getattr(ctx.engine, WEAPON_METHOD_LOG, None) or []
    else:
        log = record.get(WEAPON_METHODS_KEY) or []
    actor_id = getattr(getattr(ctx, "actor", None), "entity_id", None)
    return [entry for entry in log if (actor_id is None or entry.get("actor_id") == actor_id)
            and (target_id is None or entry.get("target_id") == target_id)]


def _begin_strike(ctx: Context) -> None:
    """Start this strike's own record, so what ran or committed on this hit cannot be read as the last hit's.

    A new empty record replaces the previous one on this Context only. Anything this strike's riders and reactions
    record afterwards, and anything a nested attack records in its own Context, therefore lands in the right place
    and the enclosing strike's record is still whole when the engine reads it again after them.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, WEAPON_METHOD_LOG)
    ctx.strike_record = {}
    ctx.engine.__dict__.pop(WEAPON_METHOD_LOG, None)


def block_weapon_method(ctx: Context, effect: dict[str, Any]) -> None:
    """Weapons Sphere, Apply Weapon Method (owner 2026-09-26): once per turn when you hit, one method fitting the weapon's
    tags; a major one expends Martial Focus."""
    if ctx.actor.turn_flags.get("weapon_method"):
        return
    ctx.actor.turn_flags["weapon_method"] = True
    _note_weapon_method(ctx, effect)
    run_effects(ctx, effect.get("effects") or [])


def block_guard_against(ctx: Context, effect: dict[str, Any]) -> None:
    """Guarding Method: the target's next attack against you before the start of your next turn has Disadvantage."""
    if ctx.target is not None:
        ctx.engine._add_modifier(ctx.target, ctx.source, "attack_mode_vs", "SET", f"DISADVANTAGE:{ctx.actor.entity_id}", "NEXT_ATTACK",
                                 expires_on="START_OF_SOURCE_NEXT_TURN")


def block_ignore_oa_from_target(ctx: Context, effect: dict[str, Any]) -> None:
    """Pressing Method: this turn's next 5 ft does not provoke the target's opportunity attack."""
    if ctx.target is not None:
        ctx.actor.turn_flags["spark_step_ignore_oa_from"] = ctx.target.entity_id


def block_sweep(ctx: Context, effect: dict[str, Any]) -> None:
    """Sweeping Method: a second creature within your reach and within 5 ft of the target takes damage equal to your PB
    of the weapon's type (no riders)."""
    first = ctx.target
    if first is None:
        return
    reach = int(ctx.action.range_ft or 5)
    others = [actor for actor in ctx.engine.state.actors.values() if actor.active and actor.team_id != ctx.actor.team_id
              and actor.entity_id != first.entity_id and ctx.engine._distance_actor_to_actor(first, actor) <= 5
              and ctx.engine._distance_actor_to_actor(ctx.actor, actor) <= reach]
    if others:
        second = min(others, key=lambda actor: (actor.current_hp, actor.entity_id))
        _deal(ctx, second, int(ctx.numbers.get("pb") or 2), str((ctx.typed.get("weapon") or {}).get("damage_type") or "UNTYPED"))


def block_vulnerability(ctx: Context, effect: dict[str, Any]) -> None:
    """Doubles that damage type after Resistance (combat/typed_reactions.py defend); ``next_only`` for
    "Vulnerability to the next Fire damage it takes"."""
    field_name = "damage_vulnerability_next" if effect.get("next_only") else "damage_vulnerability"
    for kind in effect.get("damage_types") or []:
        _modifier(ctx, effect, field_name, str(kind).upper(), harmful=True)


def block_suppress_resistance(ctx: Context, effect: dict[str, Any]) -> None:
    """"The target loses Resistance to Bludgeoning, Piercing, and Slashing damage" (To the Hilt)."""
    for kind in effect.get("damage_types") or []:
        _modifier(ctx, effect, "resistance_suppressed", str(kind).upper(), harmful=True)


def save_provenance(ctx: Context) -> dict[str, Any]:
    """The save whose failure is running these effects, as the ``origin_save`` a condition stores to remember it.

    ``block_condition`` has always stored this, so "repeat one saving throw against that effect" (Bell of Clarity) and the
    read-the-printed-DC features can tell how a condition got there. The three roll-mode rows below store it too, for the
    same reason and with no behaviour of their own: a "Disadvantage on ability checks / saving throws" imposed by a
    failed save is as save-imposed as a Poisoned row, and any plug-in reading a printed DC needs to be able to see it.
    Absent outside a failed save (a standing benefit), so nothing else changes.
    """
    return dict(ctx.origin_save) if ctx.origin_save else {}


def block_advantage(ctx: Context, effect: dict[str, Any]) -> None:
    from .roll_mode_semantics import roll_mode_target
    on, incoming = roll_mode_target(effect)
    mode = "ADVANTAGE" if effect.get("type") == "advantage" else "DISADVANTAGE"
    # A mode imposed by a failed save remembers that save (see save_provenance), so a later "against that effect's
    # printed DC" reading (Meridian Regulation's "Effect without Repeat Saves") can find it here as well as on a
    # condition row. Only strings and integers are stored.
    origin = save_provenance(ctx)
    if "death sav" in on:
        from .ext import life_state  # "Advantage on death saving throws" (auto/H3: combat/ext/life_state.py rolls them for a Dying creature)

        return life_state.give_death_save_mode(ctx, effect, mode, on)
    if incoming:
        _modifier(ctx, effect, "incoming_attack_mode", mode, harmful=mode == "ADVANTAGE")
    elif "attack roll" in on:
        subjects = _default_subject(ctx, effect, harmful=mode == "DISADVANTAGE")
        for subject in subjects:
            # The engine reads the mode from the value (gate2 _attack_mode); stored as the operation, it did nothing.
            ctx.engine._add_modifier(subject, ctx.source, "attack_mode", "SET", mode, "NEXT_ATTACK",
                                     expires_on=effect_expiry(ctx, effect, subject), source_actor_id=ctx.actor.entity_id,
                                     origin_save=({"ability": str(origin["ability"]), "dc": int(origin["dc"])}
                                                  if origin.get("ability") and origin.get("dc") else None))
    elif re.search(r"\bchecks?\b", on) and (checked := _check_keys(on)):
        # "Disadvantage on Wisdom (Perception) checks until the end of your next turn" (owner 2026-09-28): a condition carrying
        # the check mode, read by every check the table rolls (check_mode: stealth, Scoundrel Checks, escapes, skill checks).
        for subject in _default_subject(ctx, effect, harmful=mode == "DISADVANTAGE"):
            ctx.engine._apply_condition(subject, CONDITION_PREFIX + "check_mode", ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, effect, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                                        data={"rule": {"check_mode": {key: mode for key in checked}},
                                              "label": f"{mode.title()} on {effect.get('on')}", **({"origin_save": origin} if origin else {})})
    elif "concentration" in on and re.search(r"saving throws?|\bsaves?\b|\bchecks?\b", on):
        # "Disadvantage on Concentration saving throws", "... on its next Concentration saving throw" (Breath Seal, Locked
        # Breath Method, Staggering Break; owner 2026-09-29): read by the engine's own Concentration save
        # (combat/concentration.py save_mode); a "next" one is used up by that save.
        for subject in _default_subject(ctx, effect, harmful=mode == "DISADVANTAGE"):
            ctx.engine._apply_condition(subject, CONDITION_PREFIX + "concentration_mode", ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, effect, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                                        data={"rule": {"concentration_mode": mode, "next": bool(re.search(r"\bnext\b", on))},
                                              "label": f"{mode.title()} on {effect.get('on')}", **({"origin_save": origin} if origin else {})})
    elif _names_a_save(on):
        # "Advantage on saving throws against Charmed, Frightened ..." (Consecrated Boundary), "Advantage on resisting Shove,
        # Grapple, forced movement, and effects that would knock you Prone" (Weight Shift's Body Heavying), "Advantage on the
        # next Dexterity saving throw ..." (roster playtest 2026-09-29: these were GM lines). A condition read at each typed
        # save by combat/ext/save_against.py; a "next" one is used up by the first save it changes.
        for subject in _default_subject(ctx, effect, harmful=mode == "DISADVANTAGE"):
            ctx.engine._apply_condition(subject, CONDITION_PREFIX + "save_against", ctx.source, ctx.actor.entity_id,
                                        expires_on=effect_expiry(ctx, effect, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                                        data={"rule": {"save_against": {"mode": mode, "against": _save_against_keys(on),
                                                                        "abilities": [code for word, code in _CHECK_ABILITIES if word in on],
                                                                        "next": bool(re.search(r"\bnext\b", on))}},
                                              "label": f"{mode.title()} on {effect.get('on')}", **({"origin_save": origin} if origin else {})})
    else:
        from . import ext

        description = next((text for text in ext.run("unresolved_roll_mode_text", ctx, effect, mode)
                            if isinstance(text, str) and text.strip()), None)
        ctx.rider(description or f"{mode.title()} on {effect.get('on')}")


_SAVE_AGAINST = (("shove", "forced_movement"), ("forced movement", "forced_movement"), ("pushed", "forced_movement"),
                 ("moved against your will", "forced_movement"), ("prone", "prone"), ("grappl", "grappled"),
                 ("restrain", "restrained"), ("charm", "charmed"), ("frighten", "frightened"), ("poison", "poisoned"),
                 ("paraly", "paralyzed"), ("stun", "stunned"), ("blind", "blinded"), ("deafen", "deafened"),
                 ("incapacitat", "incapacitated"), ("petrif", "petrified"), ("exhaustion", "exhaustion"))


def _save_against_keys(on: str) -> list[str]:
    """The conditions a save Advantage/Disadvantage names ("against Charmed and Frightened", "resisting Shove, Grapple ...
    Prone"), as block_save names them (the failure's conditions, plus "forced_movement" for a push or pull)."""
    return sorted({key for word, key in _SAVE_AGAINST if word in on})


def _names_a_save(on: str) -> bool:
    """An "on" that is about saves (not Concentration: the engine rolls those itself) and names what it covers."""
    return bool(re.search(r"saving throws?|\bsaves?\b|\bresist", on)) and "concentration" not in on and \
        bool(_save_against_keys(on) or any(word in on for word, _ in _CHECK_ABILITIES))


_CHECK_ABILITIES = (("strength", "STR"), ("dexterity", "DEX"), ("constitution", "CON"), ("intelligence", "INT"), ("wisdom", "WIS"), ("charisma", "CHA"))
_SKILLS = ("Acrobatics", "Animal Handling", "Arcana", "Athletics", "Deception", "History", "Insight", "Intimidation", "Investigation",
           "Medicine", "Nature", "Perception", "Performance", "Persuasion", "Religion", "Sleight of Hand", "Stealth", "Survival")


def _check_keys(on: str) -> list[str]:
    """The abilities and skills an "on ... checks" names: a skill in parentheses narrows its ability to that skill."""
    skills = [skill for skill in _SKILLS if skill.lower() in on]
    if skills:
        return skills
    codes = [code for word, code in _CHECK_ABILITIES if re.search(rf"\b{word}\b", on)]
    # "Disadvantage on ability checks" (playtest 2026-09-29: a GM line): every check.
    return codes or (["ALL"] if re.fullmatch(r"(?:all |its |their |your )?ability checks?", on.strip()) else [])


def block_rider(ctx: Context, effect: dict[str, Any]) -> None:
    ctx.rider(str(effect.get("evidence") or effect.get("type")))


def _resource_amount(ctx: Context, effect: dict[str, Any]) -> int:
    spec = _effect_dice(ctx, effect)
    dice = ctx.dice(spec, flat=int(effect.get("flat") or 0), formula=effect.get("formula"))
    if isinstance(dice, FlatAmount):
        return max(0, dice.modifier)
    return _roll(ctx, dice, "RESOURCE")


# The CP pools a "cannot regain CP" condition stops (no_cp_regain in combat/rules/typed_conditions.json).
CP_POOLS = ("resource:core.qi", "resource:core.stamina", "resource:core.resonance")


def block_gain_resource(ctx: Context, effect: dict[str, Any]) -> None:
    """combat/factory_compiler.py resolves ``resource_id`` from the printed evidence text (a Path
    pool, Martial Focus, or the character's Foundation resource) at compile time (owner 2026-09-26);
    an unresolved effect (a resource this compiler does not know) stays a GM rider."""
    resource_id = effect.get("resource_id")
    if not resource_id:
        ctx.rider(f"Gain resource not identified: {effect.get('evidence') or ''}")
        return
    amount = _resource_amount(ctx, effect)
    for subject in _default_subject(ctx, effect, harmful=False):
        if resource_id in subject.resources:
            ctx.engine._gain_resource(subject, resource_id, amount, ctx.source)


def block_spend_resource(ctx: Context, effect: dict[str, Any]) -> None:
    """Clamped to what the subject actually holds: the sealed engine's ``_spend_resource`` raises on
    an overspend, and a bad typed row must never end a fight (owner 2026-09-26)."""
    resource_id = effect.get("resource_id")
    if not resource_id:
        ctx.rider(f"Spend resource not identified: {effect.get('evidence') or ''}")
        return
    amount = _resource_amount(ctx, effect)
    for subject in _default_subject(ctx, effect, harmful=False):
        spend = min(amount, subject.resources.get(resource_id, 0))
        if spend:
            ctx.engine._spend_resource(subject, resource_id, spend, ctx.source)


# ------------------------------------------------------------------ R6 reaction effects (owner 2026-09-26)
def _reaction_roll_mode(ctx: Context) -> str:
    """Advantage or Disadvantage on the reactor's own d20 in a reaction (a contest, a chance roll) from a plug-in (the
    ``reaction_roll_mode`` hook: Charged Countermeasure, combat/ext/charged_countermeasure.py); both cancel out."""
    from . import ext

    modes = {mode for mode in ext.run("reaction_roll_mode", ctx) if mode in ("ADVANTAGE", "DISADVANTAGE")}
    return modes.pop() if len(modes) == 1 else "NORMAL"


@dataclass(frozen=True)
class OpposedCheckResult:
    """Resolution-local opposed rolls; between two dice a tie preserves the defended situation.

    No natural die automatically wins an ability check. Margin is the signed
    difference between final totals, for data-driven success-by-N riders. A printed
    DC (``kind: "dc"``) has no defending die, so ``target`` is None and ``resistance``
    is the DC itself. Margin still reads the same either way, but how it is read
    differs: two rolled checks need the actor strictly ahead (a tie holds), while a
    printed DC is a fixed difficulty that a total reaching it meets, exactly as the
    wall-breach check below compares ``roll.total >= dc``.
    This object is never stored in MatchState; events serialize its rolls.
    """

    actor: RollRecord
    target: RollRecord | None
    outcome_override: bool | None = None
    dc: int | None = None

    @property
    def resistance(self) -> int:
        """What the actor's total had to beat: the defender's total, or the printed DC."""
        return int(self.dc) if self.target is None else int(self.target.total)

    @property
    def margin(self) -> int:
        return self.actor.total - self.resistance

    @property
    def tied(self) -> bool:
        """Two defending dice drew level. Meeting a printed DC exactly is a success, not a tie."""
        return self.target is not None and self.margin == 0

    @property
    def success(self) -> bool:
        if self.outcome_override is not None:
            return self.outcome_override
        return self.margin >= 0 if self.target is None else self.margin > 0


def dc_of(ctx: Context, target: ActorState, spec: dict[str, Any]) -> int:
    """The Difficulty Class an opposed check is measured against.

    ``of`` names a plug-in provider through the ``check_dc`` hook, so another sphere may
    read its own printed DC without a new resolver. Whatever the name -- absent, the
    printed default ``cultivation_save_dc``, or one no plug-in answers -- an unanswered
    DC falls back to the target's own Cultivation Save DC, the printed DC every
    cultivation talent uses. Always an integer, never a silent flat 10.
    """
    from . import ext
    from .ext.end_effect import cultivation_dc

    if spec.get("dc") is not None:
        return int(spec["dc"])
    if spec.get("basis"):
        from .save_dcs import save_dc
        return save_dc(ctx.engine, target, str(spec["basis"]))
    name = str(spec.get("of") or "").strip()
    if name:
        for answer in ext.run("check_dc", ctx, target, spec):
            if isinstance(answer, int) and not isinstance(answer, bool) and answer > 0:
                return answer
    return cultivation_dc(ctx.engine, target)


def resolve_opposed_check(ctx: Context, target: ActorState, actor_check: dict[str, Any],
                          target_check: dict[str, Any], *, save_fail_effects: list[dict[str, Any]] | None = None,
                          save_success_effects: list[dict[str, Any]] | None = None) -> OpposedCheckResult:
    """General actor check against a target check/save/printed DC, with normal d20 hooks.

    Specs are already selected: kind=check (ability/skill), cultivation, key_ability, dc (printed Save DC), or save
    (defender only). A check spec may carry ``hazards`` -- what the check relies on
    (e.g. ``["visual_concealment"]`` for a Stealth check to slip past on sight alone), read
    by ``check_modes`` so a scoped ``check_against`` condition applies only to a check that
    names it; absent the key the check is unscoped, as every spec was before. Choices
    belong to ext.contests, before either die is drawn.
    Check modifiers/modes/floors use the same public seams as other checks;
    Both raw totals exist before outcome-dependent adjustments. The first
    check is adjusted against the opposing total, then the second against the
    adjusted first total. A defending save retains native save resolution and
    shares typed pending modifiers/final settlement with block_save. A printed DC
    draws no defending die at all: the actor's own check is compared with the number
    the sheet names, and CHECK_ROLLED records that number. Forced outcomes stay
    separate from the real totals, even when those totals agree with the outcome.
    Only opting-in callers roll or emit events. No engine methods are patched.
    """
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_roll_outcome")
    from . import ext, typed_reactions
    from .ability_checks import ability_modifier, key_modifier, skill_bonus
    from .ext.needle import numbers_of
    from .roll_checkpoints import rewrite_d20
    from .check_context import metadata_document
    actor_check = {**actor_check, 'metadata': metadata_document(actor_check.get('metadata'))}
    target_check = {**target_check, 'metadata': metadata_document(target_check.get('metadata'))}

    def check(subject: ActorState, opponent: ActorState, spec: dict[str, Any]) -> RollRecord:
        numbers = ctx.numbers if subject is ctx.actor else numbers_of(ctx.engine, subject)
        sub = replace(ctx, actor=subject, targets=[opponent], target=opponent,
                      typed={**ctx.typed, "numbers": numbers}, check_metadata=dict(spec.get("metadata") or {}))
        ability, skill = str(spec.get("ability") or "").upper(), spec.get("skill")
        if spec.get("kind") == "cultivation":
            bonus = int(numbers.get("pb") or subject.proficiency_bonus) + int(numbers.get("key_mod") or 0)
        elif spec.get("kind") == "key_ability":
            # "its spellcasting ability check": the creature's own Key Ability, which is the
            # spellcasting ability a sphere talent casts from (combat/ability_checks.py). A
            # plain ability check carries no Proficiency Bonus, so this is the weaker roll.
            bonus = key_modifier(ctx.engine, subject, numbers=numbers)
        else:
            fallback = (int(subject.dexterity_score) - 10) // 2 if ability == "DEX" else None
            bonus = ability_modifier(subject, ability, numbers=numbers, fallback=fallback)
            if skill:
                bonus = skill_bonus(ctx.engine, subject, str(skill), bonus)
        bonus += sum(int(n) for n in ext.run("check_bonus", sub, subject) if isinstance(n, int))
        modes = check_modes(subject, ability, skill, engine=ctx.engine, against_creature=opponent,
                            hazards=tuple(str(h) for h in (spec.get("hazards") or ())), metadata=sub.check_metadata)
        modes.update(m for m in ext.run("skill_check_mode", sub, subject, ability, skill)
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
        modes.update(m for m in (spec.get("mode"),) if m in ("ADVANTAGE", "DISADVANTAGE"))
        modes.update(m for m in ext.run("contest_check_mode", ctx, subject, opponent, spec)
                     if m in ("ADVANTAGE", "DISADVANTAGE"))
        if subject is ctx.actor:
            modes.update(m for m in ext.run("reaction_roll_mode", ctx)
                         if m in ("ADVANTAGE", "DISADVANTAGE"))
        reason = f"CHECK:{ctx.source}"
        # Pre-draw choices precede both opposed totals. Post-roll adjustments
        # stay deferred until both rolls exist.
        with ctx.engine.d20_scope({"kind": "check", "actor_id": subject.entity_id,
                                   "target_id": opponent.entity_id, "source_id": ctx.source,
                                   "source_actor_id": ctx.actor.entity_id, "ability": spec.get("ability"),
                                   "skill": spec.get("skill"),
                                   "hazards": [str(h) for h in (spec.get("hazards") or ())]}):
            request = dict(modifier=bonus, actor_id=subject.entity_id, reason=reason,
                           mode=next(iter(modes)) if len(modes) == 1 else "NORMAL")
            # The engine's pre-draw seam (Roller.before_d20): Wheel-style bonuses, then fixed-natural
            # consent. Post-draw rewrites stay deferred to adjust(), so this stops before the rewrite.
            prepared = ctx.engine.roller.before_d20(request) if ctx.engine.roller.before_d20 is not None else None
            return prepared if prepared is not None else ctx.engine.roller.raw_d20(**request)

    def adjust(subject: ActorState, opponent: ActorState, spec: dict[str, Any],
               roll: RollRecord, dc: int) -> RollRecord:
        with ctx.engine.d20_scope({"kind": "check", "actor_id": subject.entity_id,
                                   "target_id": opponent.entity_id, "source_id": ctx.source,
                                   "source_actor_id": ctx.actor.entity_id, "ability": spec.get("ability"),
                                   "skill": spec.get("skill"), "check_kind": spec.get("kind", "check"), "dc": dc,
                                   "hazards": [str(h) for h in (spec.get("hazards") or ())]}):
            roll = rewrite_d20(ctx.engine, roll)
            roll = ext.floored(ctx.engine, subject, roll, dc)
        ctx.engine._record_roll(roll)
        return roll

    if target_check.get("kind") == "dc":
        # "Make a Cultivation Check against the binder's Cultivation Save DC" (Break the Cruel Seal,
        # Exorcist's Mercy): the opponent is a printed Difficulty Class, not a die, so nothing is
        # rolled for it and its side of OpposedCheckResult carries the DC itself (expression "DC n",
        # no dice). Read through ext.check_dc so a plug-in may name other printed DCs; an unknown
        # name falls back to the target's own Cultivation Save DC.
        mine = check(ctx.actor, target, actor_check)
        dc = dc_of(ctx, target, target_check)
        # Named-provider histories retain their original non-rolled DC record;
        # save-DC alternatives use the no-defending-roll result and event shape.
        theirs = (RollRecord(roll_id=f"DC:{ctx.source}:{target.entity_id}", counter_start=0, counter_end=0,
                             expression=f"DC {dc}", actor_id=target.entity_id, reason=f"DC:{ctx.source}",
                             dice=(), modifier=0, total=dc) if target_check.get("of") else None)
        mine = adjust(ctx.actor, target, actor_check, mine, dc)
    elif target_check.get("kind") == "save":
        mine = check(ctx.actor, target, actor_check)
        choice = str(target_check["ability"]).upper()
        shaped, named, plug_in_named, pressed = typed_save_modifiers(
            ctx, target, choice, save_fail_effects or [], save_success_effects or [])
        modes = set(shaped["modes"])
        if any(choice in (row.get("no_save_advantage") or []) for row in condition_rules(target)):
            modes.discard("ADVANTAGE")
        token = _ACTIVE_SAVES.set((*_ACTIVE_SAVES.get(), (id(ctx.engine), ctx.source, target.entity_id)))
        try:
            from .ext.d20_rewrite import opposed_save_totals

            with opposed_save_totals(ctx.engine, target, ctx.source):
                # The whole mode set travels, not the collapsed single mode. An opposed save is the
                # same wrapper as block_save: the typed `save` hook (save_against's next-save grants,
                # a pressure advantage, a no-advantage strip) has already settled this creature's modes
                # and consumed its one-use grants before _roll_save is called. Passing only `extra_mode`
                # loses that settlement, and the native save_mode bridge then re-reads the persistent
                # half on its own and hands back one surviving mode -- turning an intended NORMAL
                # cancellation into ADVANTAGE/DISADVANTAGE on contested saves for unrelated creatures.
                # save_modes seeds _roll_save's contributed set exactly as block_save's does, so the
                # bridge's re-read is a no-op union and Advantage/Disadvantage still cancel here.
                theirs = ctx.engine._roll_save(target, choice, mine.total - int(shaped["bonus"]), ctx.source,
                                              extra_mode=next(iter(modes)) if len(modes) == 1 else None,
                                              roll_context={"source_actor_id": ctx.actor.entity_id, "named": sorted(plug_in_named),
                                                            "save_modes": sorted(modes)})
        finally:
            _ACTIVE_SAVES.reset(token)
        # Pending typed bonuses normally shift the DC. Opposed totals need the
        # equivalent effective modifier so history/margin compare like units.
        theirs = theirs.model_copy(update={"modifier": theirs.modifier + int(shaped["bonus"]),
                                          "total": theirs.total + int(shaped["bonus"])})
        mine = adjust(ctx.actor, target, actor_check, mine, theirs.total + 1)
        dc = None
    else:
        theirs = check(target, ctx.actor, target_check)
        mine = check(ctx.actor, target, actor_check)
        theirs = adjust(target, ctx.actor, target_check, theirs, mine.total)
        mine = adjust(ctx.actor, target, actor_check, mine, theirs.total + 1)
        dc = None
    result = OpposedCheckResult(mine, theirs, dc=dc)
    if target_check.get("kind") == "dc" and theirs is not None:
        result = replace(result, outcome_override=mine.total >= dc)
    actor_allowed = False not in ext.run_strict('check_success_allowed',
        replace(ctx, check_metadata=dict(actor_check.get('metadata') or {})), ctx.actor, actor_check, mine)
    target_allowed = True if theirs is None or target_check.get('kind') == 'save' else False not in ext.run_strict(
        'check_success_allowed', replace(ctx, check_metadata=dict(target_check.get('metadata') or {})), target, target_check, theirs)
    if target_check.get("kind") == "save":
        # Both sides must hear the already-forced save outcome, not a numeric
        # comparison that a native rewrite has explicitly superseded. Leave the
        # receipt for settle_typed_save, which also handles later save reactions.
        forced = (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).get(target.entity_id)
        if forced in ("success", "failure"):
            result = replace(result, outcome_override=forced == "failure")
    if not actor_allowed:
        result = replace(result, outcome_override=False)
    elif not target_allowed:
        result = replace(result, outcome_override=True)
    sides = [(ctx.actor, target, actor_check, mine, result.success)]
    if theirs is not None and target_check.get("kind") != "dc":
        sides.append((target, ctx.actor, target_check, theirs, not result.success))
    for subject, opponent, spec, roll, succeeded in sides:
        if spec.get("kind") == "save":
            forced = (getattr(ctx.engine, "_typed_roll_outcome", None) or {}).get(subject.entity_id)
            failed = settle_typed_save(ctx, subject, choice, roll, not succeeded, named, plug_in_named, pressed)
            if failed != (not succeeded) or forced in ("success", "failure"):
                result = replace(result, outcome_override=failed)
        else:
            typed_reactions.after_d20(ctx.engine, subject, "check", success=succeeded, other=opponent,
                                      ability=spec.get("ability"), natural=roll.natural_result)
    overrides = getattr(ctx.engine, "_typed_roll_outcome", {})
    actor_override = overrides.pop(ctx.actor.entity_id, None)
    target_override = overrides.pop(target.entity_id, None)
    if target_override in ("success", "failure"):
        result = replace(result, outcome_override=target_override == "failure")
    elif actor_override in ("success", "failure") and result.outcome_override is None:
        result = replace(result, outcome_override=actor_override == "success")
    # Explicit source-qualified rules can forbid benefiting from a completed
    # check (ordinary concealment, for example). They never skip the dice or
    # create sight/location knowledge. Missing providers preserve old results.
    if not actor_allowed:
        result = replace(result, outcome_override=False)
    elif not target_allowed:
        result = replace(result, outcome_override=True)
    named_against = target_check.get("label") or target_check.get("skill")
    payload = {
        "actor": mine.model_dump(mode="json"),
        "skill": actor_check.get("skill"),
        "target_skill": target_check.get("skill") if target_check.get("kind") != "save" else None,
        "against": named_against,
        **({"check_metadata": dict(actor_check["metadata"])} if actor_check.get("metadata") else {}),
        **({"target_check_metadata": dict(target_check["metadata"])} if target_check.get("metadata") else {}),
        "success": result.success, "tied": result.tied, "margin": result.margin,
        **({"outcome_override": result.outcome_override} if result.outcome_override is not None else {}),
    }
    if target_check.get("kind") == "dc":
        # A printed DC: one die, and the number it was compared with (combat/history_feed.py).
        payload |= {"roll_kind": "dc_check", "dc": result.dc,
                    "check": actor_check.get("label") or actor_check.get("skill") or
                             ("Cultivation Check" if actor_check.get("kind") == "cultivation" else "Check")}
        if theirs is not None:
            # Keep the historical named-provider DC sidecar, which is not a
            # defending die and must never trigger defending d20 reactions.
            payload["target"] = theirs.model_dump(mode="json")
    else:
        payload |= {"target": theirs.model_dump(mode="json"), "roll_kind": "opposed_check",
                    "check": "Cultivation Check contest" if actor_check.get("kind") == target_check.get("kind") == "cultivation"
                             else "Opposed check"}
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id,
                             target_ids=(target.entity_id,), payload=payload)
    ext.run("opposed_check_resolved", ctx, target, result, actor_check, target_check)
    return result


def _contest(ctx: Context, against: int, reason: str, description: str) -> bool:
    """The reactor's d20 + its attack bonus against ``against`` (an attack total rolled for the other side, or a DC)."""
    from . import ext
    from .ext.roll_context import described_d20

    modifier = int(ctx.numbers.get("attack_bonus") or 0) + sum(ext.run("check_bonus", ctx, ctx.actor))
    roll = described_d20(ctx.engine, description=description, modifier=modifier,
                         actor_id=ctx.actor.entity_id, reason=reason, mode=_reaction_roll_mode(ctx))
    ctx.engine._record_roll(roll)
    return roll.total >= against


def block_negate_attack(ctx: Context, effect: dict[str, Any]) -> None:
    """Negate the triggering attack (Ten-Thousand Arrow Reversal, Misdirected Attack, False Double, Peach-Thief Escape,
    Intercepting Strike): outright, on a d20 of ``chance_d20`` or better, on winning a contest against the attack roll, or
    when the reactor ended out of the attacker's reach. block_attack skips a negated attack."""
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_negated")
    pending = getattr(ctx.engine, "_typed_pending_attack", None)
    if not pending:
        ctx.rider(str(effect.get("evidence") or "Negate the triggering attack (GM)."))
        return
    engine = ctx.engine
    attacker, protected = engine.state.actors.get(pending["attacker"]), engine.state.actors.get(pending["target"])
    if attacker is None or protected is None:
        return
    success = True
    if effect.get("if_out_of_reach"):
        success = engine._distance_actor_to_actor(attacker, protected) > int(pending.get("reach") or 5)
    elif effect.get("chance_d20"):
        roll = engine.roller.d20(modifier=0, actor_id=ctx.actor.entity_id, reason="REACTION_CHANCE", mode=_reaction_roll_mode(ctx))
        engine._record_roll(roll)
        success = roll.total >= int(effect["chance_d20"])
    elif effect.get("contest"):
        from .ext.roll_context import described_d20

        attack_name = pending.get("action_name") or "attack"
        theirs = described_d20(engine, description=f"attack roll for {attack_name} against {protected.display_name}, opposed by {ctx.action.display_name}",
                               modifier=int(pending.get("bonus") or 0), actor_id=attacker.entity_id, reason="REACTION_CONTEST")
        engine._record_roll(theirs)
        roll_kind = "attack roll" if effect.get("contest") == "attack" else "ability check"
        success = _contest(ctx, theirs.total, "REACTION_CONTEST",
                           f"{roll_kind} for {ctx.action.display_name} to stop {attacker.display_name}'s {attack_name} against {protected.display_name}")
    if success:
        engine._typed_negated = {*getattr(engine, "_typed_negated", set()), (attacker.entity_id, protected.entity_id)}
    ctx.rider(f"{ctx.action.display_name}: the attack on {protected.display_name} is {'negated' if success else 'not negated'}.")


def block_reaction_move(ctx: Context, effect: dict[str, Any]) -> None:
    """Move the reactor toward or away from the triggering creature as its reaction (Unbroken Pursuit, Follow Footwork,
    Peach-Thief Escape): up to half its Speed or its Speed, square by square, without opportunity attacks."""
    from .gate2_runtime_models import Position

    engine, actor, other = ctx.engine, ctx.actor, ctx.target
    if other is None or other is actor:
        return
    speed = engine._effective_speed(actor)
    feet = {"half_speed": speed // 2, "speed": speed}.get(str(effect.get("distance_ft")), int(effect.get("distance_ft") or 0) if str(effect.get("distance_ft") or "0").isdigit() else 0)
    from .technique_interception import movement_distance, movement_committed
    feet = movement_distance(engine, actor.entity_id, ctx.source, actor.entity_id, feet)
    toward = effect.get("direction") == "toward"
    # Every square reachable within the distance (around allies and walls), then the one nearest to (or farthest from) the
    # triggering creature; ties keep the shorter path.
    occupied, footprint = engine._occupied_cells_except(actor.entity_id), engine._footprint(actor)
    start = actor.position
    came: dict[tuple[int, int], tuple[int, int] | None] = {(start.x, start.y): None}
    frontier = [start]
    for _ in range(feet // engine.grid.square_size_ft):
        nxt_frontier = []
        for cell in frontier:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    x, y = cell.x + dx, cell.y + dy
                    if not (dx or dy) or (x, y) in came or not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
                        continue  # off the map edge (fight audit 2026-09-29: a square at x=-1 was built before the check)
                    step = Position(x=x, y=y)
                    if engine.grid.step_legal(cell, step, occupied_cells=occupied, footprint=footprint):
                        came[(step.x, step.y)] = (cell.x, cell.y)
                        nxt_frontier.append(step)
        frontier = nxt_frontier
    gap = lambda key: engine.grid.distance_ft(Position(x=key[0], y=key[1]), other.position)  # noqa: E731
    depth = lambda key: 0 if came[key] is None else 1 + depth(came[key])  # noqa: E731
    best = min(came, key=lambda key: (gap(key) if toward else -gap(key), depth(key), key))
    path, key = [], best
    while key is not None:
        path.append(Position(x=key[0], y=key[1]))
        key = came[key]
    path.reverse()
    current = path[-1]
    if len(path) > 1 and (gap(best) < gap((start.x, start.y)) if toward else gap(best) > gap((start.x, start.y))):
        actor.position = current
        movement_committed(engine, actor.entity_id, ctx.source, actor.entity_id, (len(path) - 1) * engine.grid.square_size_ft)
        engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=actor.entity_id,
                             payload={"destination": current.model_dump(mode="json"), "path": [row.model_dump(mode="json") for row in path],
                                      "cost_ft": 0, "forced": False, "reaction": True})


def block_set_outcome(ctx: Context, effect: dict[str, Any]) -> None:
    """The triggering roll's outcome (Unbroken Brace: "the target succeeds instead"; Steal the Decisive Moment: "turn the
    success into a failure"; Rewrite Fate: the reactor's choice -- success for an ally, failure for an enemy). A saving
    throw or an attack roll still to be resolved reads it (block_save, block_attack)."""
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_roll_outcome")
    target = ctx.target
    if target is None:
        return
    outcome = str(effect.get("outcome") or "")
    if outcome == "favourable":
        outcome = "success" if target.team_id == ctx.actor.team_id else "failure"
    ctx.engine._typed_roll_outcome = {**(getattr(ctx.engine, "_typed_roll_outcome", None) or {}), target.entity_id: outcome}


def block_counter_technique(ctx: Context, effect: dict[str, Any]) -> None:
    """Counterweave: the triggering technique fails if the reactor wins the contest against its save DC."""
    from .paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_typed_countered")
    pending = getattr(ctx.engine, "_typed_pending_technique", None)
    if not pending:
        return
    caster = ctx.engine.state.actors.get(pending.get("actor"))
    technique = pending.get("action_name") or "technique"
    success = _contest(ctx, int(pending.get("save_dc") or 10), "REACTION_COUNTER",
                       f"ability check for {ctx.action.display_name} to counter {caster.display_name if caster else 'the creature'}'s {technique}")
    if success:
        ctx.engine._typed_countered = True
    ctx.rider(f"{ctx.action.display_name}: the technique is {'countered' if success else 'not countered'}.")


def block_summon(ctx: Context, effect: dict[str, Any]) -> None:
    """Bring the summoner's creatures of ``group`` onto the map (combat/summons.py), beside it toward the nearest foe."""
    from . import summons

    foes = [other for other in ctx.engine.state.actors.values() if other.active and other.team_id != ctx.actor.team_id]
    near = min(foes, key=lambda other: ctx.engine._distance_actor_to_actor(ctx.actor, other)).position if foes else None
    chosen = ctx.intent.destination if 'cell_placement' in ctx.action.parameters else None
    summons.summon(ctx.engine, ctx.actor, str(effect["group"]), ctx.source, near=near,
                   destination=chosen, action=ctx.action if chosen is not None else None)


def block_command_summons(ctx: Context, effect: dict[str, Any]) -> None:
    from . import summons, ext

    commanded = summons.command(ctx.engine, ctx.actor, str(effect["group"]), ctx.source)
    # General seam (owner 2026-10-13): a printed rule may spend one
    # command on more than the order itself -- Bone General: one
    # commanded servant may move up to 10 feet before it takes its
    # action. The intent rides along so a player-owned choice is
    # asked, never assumed; plug-ins that perform nothing answer None.
    ext.run("command_resolved", ctx.engine, ctx.actor, str(effect["group"]), commanded, ctx.intent,
            ctx.action.economy)


def block_zone(ctx: Context, effect: dict[str, Any]) -> None:
    """An area the ability leaves on the map (combat/zones.py); without a compiled zone_spec the line stays a GM note."""
    spec = ctx.typed.get("zone_spec")
    if not spec:
        block_rider(ctx, effect)
        return
    from . import zones

    zones.create(ctx, spec)


_AGAINST_YOU = re.compile(r"\bagainst (?:you|the user)\b", re.I)
_OPPORTUNITY = re.compile(r"\bopportunity attacks?\b", re.I)


def block_reaction_denied(ctx: Context, effect: dict[str, Any]) -> None:
    """"Cannot take Reactions" is reaction_denied; "... against you" only denies Reactions against the user (fight audit
    2026-09-29: Lightning Lash's Jolt and 25 other "against you" lines took every Reaction away), and "cannot make
    Opportunity Attacks" is no_opportunity_attacks (combat/typed_reactions.wants_opportunity_attack)."""
    text = f"{effect.get('on') or ''} {effect.get('evidence') or ''}"
    against = ctx.actor.entity_id if _AGAINST_YOU.search(text) else None
    if not against and not _OPPORTUNITY.search(text):
        block_condition(ctx, {**effect, "condition": "reaction_denied"})
        return
    from . import unmaking

    condition = NO_OPPORTUNITY if _OPPORTUNITY.search(text) else unmaking.NO_REACTIONS_AGAINST
    label = ("No opportunity attacks" if condition == NO_OPPORTUNITY else "No Reactions") + (f" against {ctx.actor.display_name}" if against else "")
    for subject in _default_subject(ctx, effect, harmful=True):
        if subject is None or subject.team_id == ctx.actor.team_id:
            continue
        ctx.engine._apply_condition(subject, condition, ctx.source, ctx.actor.entity_id,
                                    expires_on=effect_expiry(ctx, effect, subject, condition=True) or "END_OF_HOLDER_NEXT_TURN",
                                    data={"against": against, "label": label})


def block_on_success(ctx: Context, effect: dict[str, Any]) -> None:
    """A talent that rides a reaction's success (combat/factory_compiler.py _attach_reaction_modifiers, success_deferred):
    nothing when the reaction fires; the reaction's own plug-in runs ``effects`` once it has succeeded."""


def condition_immune(engine: Any, actor: ActorState, name: str) -> bool:
    """A creature immune to the condition, through a standing or temporary benefit (a Corpse Servant is never Frightened;
    combat/summons.py; a reviewed "Immunity to Poisoned" modifier)."""
    from . import ext, typed_reactions

    if any(name in row.get("condition_immunities", ()) for row in condition_rules(actor)) or any(
            m.target_field == "condition_immunity" and str(m.value).lower() == name.lower() for m in actor.modifiers.values()) or any(
            name in row.get("conditions", ()) for row in typed_reactions._rows(engine, actor.entity_id, "condition_immunity")):
        return True
    return any(ext.run("condition_immune", engine, actor, name))  # Imperial Mandate (combat/ext/warleader_commands.py)


def block_wall_breach(ctx: Context, effect: dict[str, Any]) -> None:
    """An Action beside a wall (owner 2026-09-27, combat/rules/terrain.json "breach"): a Large or larger creature forces
    through Dune Wall with Strength (Athletics), and any creature works the Puzzle Wall with Intelligence (Investigation),
    against the wall's creator's save DC. Success collapses the section, or opens it until the start of its next turn."""
    from . import zones

    found = zones.breachable(ctx.engine, ctx.actor, str(effect.get("result") or ""))
    if found is None:
        ctx.rider("No wall section to get through here.")
        return
    zone, cell = found
    rule = zone.trigger_profile["wall"]["breach"]
    dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
    from . import ext

    modifier = int(ctx.numbers.get("check_bonus") or 0) + sum(ext.run("check_bonus", ctx, ctx.actor))
    # Resolve native condition modes before drawing: the post-draw checkpoint
    # may consume a next-check allowance even when opposing modes cancel.
    mode = check_mode(ctx.actor, str(rule.get("ability") or "").upper(), rule.get("skill"), engine=ctx.engine)
    with ctx.engine.d20_scope({"kind": "check", "actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id,
                               "source_id": ctx.source, "source_actor_id": ctx.actor.entity_id,
                               "skill": rule.get("skill"), "ability": rule.get("ability"), "dc": dc}):
        roll = ctx.engine.roller.d20(modifier=modifier, actor_id=ctx.actor.entity_id, reason=f"CHECK:{ctx.source}", mode=mode)
    ctx.engine._record_roll(roll)
    roll = ext.floored(ctx.engine, ctx.actor, roll, dc)  # Complete Mandala Auspice (combat/ext/d20_floor.py)
    success = roll.total >= dc
    ctx.engine._append_event("CHECK_ROLLED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success,
                                      "skill": rule.get("skill"), "wall": zone.trigger_profile.get("name")})
    if success:
        zones.breach(ctx.engine, ctx.actor, zone, cell)
    elif rule.get("result") == "opening":
        ctx.rider("The Puzzle Wall rearranges; its creator may move the creature 5 feet (GM).")


BLOCKS: dict[str, Callable[[Context, dict[str, Any]], None]] = {
    "save": block_save,
    "attack": block_attack,
    "damage": block_damage,
    "extra_damage": block_damage,
    "half_damage": block_half_damage,
    "condition": block_condition,
    "remove_condition": block_remove_condition,
    "reaction_denied": lambda ctx, e: block_reaction_denied(ctx, e),
    "on_success": block_on_success,
    "mark": block_mark,
    "spend_mark": block_spend_mark,
    "if_marked": block_if_marked,
    "if_not_marked": block_if_not_marked,
    "forced_movement": block_forced_movement,
    "movement": block_movement,
    "remaining_movement": block_remaining_movement,
    "teleport": block_movement,
    "temp_hp": block_temp_hp,
    "healing": block_healing,
    "ac_bonus": block_ac_bonus,
    "speed": block_speed,
    "resistance": block_resistance,
    "immunity": block_resistance,
    "vulnerability": block_vulnerability,
    "cleave": block_cleave,
    "vex": block_vex,
    "recover_weapon": block_recover_weapon,
    "escape_grapple": block_escape_grapple,
    "release_grapple": block_release_grapple,
    "weapon_method": block_weapon_method,
    "guard_against": block_guard_against,
    "ignore_oa_from_target": block_ignore_oa_from_target,
    "sweep": block_sweep,
    "take_weapon": block_take_weapon,
    "grab_improvised": block_grab_improvised,
    "healing_reduction": block_healing_reduction,
    "suppress_resistance": block_suppress_resistance,
    # Read from the action itself when its damage lands (combat/typed_reactions.py _resistance_ignored).
    "ignore_resistance": lambda ctx, effect: None,
    "advantage": block_advantage,
    "disadvantage": block_advantage,
    "gain_resource": block_gain_resource,
    "spend_resource": block_spend_resource,
    # R6 (owner 2026-09-26): reaction effects; hold_at_1hp, redirect_damage_to_self and roll_die are read by the reaction
    # hook that runs them (combat/typed_reactions.py) and do nothing on their own.
    "negate_attack": block_negate_attack,
    "reaction_move": block_reaction_move,
    "set_outcome": block_set_outcome,
    "summon": block_summon,
    "zone": block_zone,
    "wall_breach": block_wall_breach,
    "drop_item": block_drop_item,
    "shape_zone": block_shape_zone,
    "toggle_augment": block_toggle_augment,
    "open_the_gate": block_open_the_gate,
    "ruin_channel": block_ruin_channel,
    "stance": block_stance,
    "deny_temp_hp": block_deny_temp_hp,
    "deny_invisible": block_deny_invisible,
    "deny_reactions_against": block_deny_reactions_against,
    "toggle_overdraw": block_toggle_overdraw,
    "pick_exploit": block_pick_exploit,
    "hide": block_hide,
    "search": block_search,
    "pickup_item": block_pickup_item,
    "command_summons": block_command_summons,
    "counter_technique": block_counter_technique,
    "hold_at_1hp": lambda ctx, effect: None,
    "redirect_damage_to_self": lambda ctx, effect: None,
    "roll_die": lambda ctx, effect: None,
}


def run_effects(ctx: Context, effects: list[dict[str, Any]]) -> None:
    from .action_geometry import attack
    from .shot_geometry import attack_scope
    # Delayed consequences retain their original attribution while resolving
    # without treating the absent source as taking a new action.
    previous = getattr(ctx.engine, "_effect_resolution_mode", "ordinary")
    ctx.engine._effect_resolution_mode = ctx.effect_resolution
    try:
        with (_defeat_chain(ctx), _moment_scope(ctx), attack(ctx.engine, ctx.actor, ctx.source),
              attack_scope(ctx.engine, ctx.actor, ctx.source)):
            _run_effects_in_chain(ctx, effects)
    finally:
        ctx.engine._effect_resolution_mode = previous


def _run_effects_in_chain(ctx: Context, effects: list[dict[str, Any]]) -> None:
    from .paid_relocation import causal_scope, take_effect

    expire_marks(ctx.engine)
    folded: set[int] = set()  # Temporary HP rows already granted as a term of an earlier row's sum (_fold_temp_hp)
    for effect in effects:
        with ExitStack() as ownership:
            receipt = take_effect(ctx.engine, effect)
            if receipt is not None:
                ownership.enter_context(causal_scope(ctx.engine, receipt))
            if ctx.engine.state.terminal_result is not None and not getattr(ctx.engine, "_final_rider_active", False):
                return
            if not isinstance(effect, dict):
                ctx.rider(str(effect))
                continue
            if ctx.missed_target_ids and not ctx.targets and effect.get('type') != 'attack' and effect.get('applies_to') != 'self':
                continue  # an empty aim has no recipient; explicit user effects and attack-use accounting remain
            if id(effect) in folded:
                continue
            from .effect_eligibility import eligible, modifier_key
            if not eligible(ctx, effect, include_deferred=True):
                continue
            if effect.get("deferred"):
                # A later trigger is not an effect of using the ability (factory_authoring/typed_structure.mark_deferred).
                if effect.get("type") == "extra_damage" and ON_HIT_BONUS.search(str(effect.get("evidence") or "")):
                    _register_on_hit(ctx, effect)
                elif effect.get("type") in ("gain_resource", "mark", "spend_resource", "spend_mark"):
                    _register_watch(ctx, effect)
                continue
            # A modifier limited to once per turn (or round) adds its effects the first time only; every
            # effect of one activation shares the gate (combat/factory_compiler.py sets modifier_once).
            gate = effect.get("modifier_once")
            from . import ext

            if any(result is False for result in ext.run_strict("effect_allowed", ctx, effect)):
                continue
            if gate:
                # The turn flag stops later uses this turn; the tuple key (not copied between hits) lets the
                # rest of this one application through.
                key = modifier_key(effect)
                ctx.actor.turn_flags[key] = True
                ctx.damage_cache[("modifier_once", gate)] = True
            block = BLOCKS.get(effect.get("type"))
            if block is None:
                from . import ext

                block = ext.effects().get(effect.get("type"), block_rider)  # a plug-in's own effect type (combat/ext)
            if effect.get("type") == "temp_hp":
                effect = _fold_temp_hp(ctx, effects, effect, folded)
            # Named modifier packets retain their attribution through save branches.
            # Do not change a plug-in's action source: placement/menu handlers may
            # need the actual catalog action to look up their triggering attack.
            packet = ctx.with_source(f"passive:{effect['source_modifier']}") if effect.get("source_modifier") and effect.get("type") in {
                "damage", "extra_damage", "save"} else ctx
            with ExitStack() as scopes:
                # Attack blocks also have direct callers (granted attacks). They own
                # the same general scope inside block_attack, exactly once.
                for scope in ([] if effect.get("type") == "attack" else ext.run_strict("effect_resolution_scope", packet, effect)):
                    scopes.enter_context(scope)
                from .area_recipients import harmful_effect_scope
                previous_scope = getattr(packet, "area_harmful_scope", None)
                packet.area_harmful_scope = harmful_effect_scope(
                    packet.typed.get("area") or {}, effect, inherited=previous_scope)
                try:
                    block(packet, effect)
                finally:
                    packet.area_harmful_scope = previous_scope
            from .falling import settle
            settle(ctx.engine, ctx.source, ctx.intent)


def placed_at_aim(area: dict[str, Any] | None) -> bool:
    """Whether a line or cone is laid down at the point its user aims at rather than running out from them.

    A printed Range longer than the shape's own length is a placement range, not a length: Earthbind Line is
    "Range: 60 feet ... Area: 20-foot line", so the 20-foot line starts at the chosen point and runs on away from
    its user. combat/factory_compiler.py ``_aimed_area`` marks such a row's area ``placed``; the flag is absent on
    every other area (an aura, an emanation, and a line whose own length is its range), which keeps running from
    its user exactly as before."""
    return bool(area) and area.get("shape") in ("line", "cone") and bool(area.get("placed"))


def aim_gives_direction(area: dict[str, Any] | None, vertex: Any, aim: Any) -> bool:
    """Whether an area aimed from ``vertex`` at ``aim`` can be drawn at all.

    This is the one place that decides what a line or cone does when the aim point sits on
    its user's own square. A line and a cone are paths, so they need a direction to run in,
    and a point on the caster's own square gives none -- there is no printed rule that says
    which way a 20-foot line laid down under your own feet should run. So that aim is not a
    placement the shape can make: ``combat/ext/placed_areas.py`` leaves the choice out of what
    the fighter is offered, and the action is refused before any Stamina, CP, action or turn
    is spent (``Gate2Engine.execute_intent`` rejects a candidate that is not legal before it
    reaches ``_spend_costs``). Preview, the AI's scoring and persistent zones agree because
    they all read the same geometry, which returns no squares for such an aim.

    Every other aim is unaffected: another square than the user's own -- for a ``placed``
    shape (``placed_at_aim``) or one that runs out from its user -- and every shape that is
    not a line or a cone (a sphere, a cube, an emanation, an aura) is drawable as before.
    """
    if not area or area.get("shape") not in ("line", "cone") or vertex is None or aim is None:
        return True
    return (int(vertex.x), int(vertex.y), int(vertex.z)) != (int(aim.x), int(aim.y), int(aim.z))


def _line_ray(engine: Any, vertex, aim, area: dict[str, Any] | None) -> tuple[Any, tuple[float, float, float]] | None:
    """The point a line or cone starts at and the unit direction it runs in, in feet, or None when the caster and
    the aim point coincide (no facing to project onto; ``aim_gives_direction`` is the one policy that says such an
    aim is not a legal choice). A ``placed`` shape starts at the aim point and runs on away
    from the user; every other line and cone starts at its user and runs through the aim point."""
    square = engine.grid.square_size_ft
    direction = tuple((b-a) * square for a, b in zip((vertex.x, vertex.y, vertex.z), (aim.x, aim.y, aim.z)))
    length = math.sqrt(sum(value * value for value in direction))
    if length <= 0:
        return None
    start = aim if placed_at_aim(area) else vertex
    return start, tuple(value / length for value in direction)


def _ray_offsets(engine: Any, vertex, aim, point, area: dict[str, Any] | None = None) -> tuple[float, float] | None:
    """Along/perpendicular distances in feet for a 3D line or cone.

    Placed shapes start at the aim; other shapes start at the user.
    Coincident user and aim points provide no direction.
    """
    ray = _line_ray(engine, vertex, aim, area)
    if ray is None:
        return None
    start, direction = ray
    square = engine.grid.square_size_ft
    vector = tuple((b-a) * square for a, b in zip((start.x, start.y, start.z), (point.x, point.y, point.z)))
    along = sum(a*b for a, b in zip(vector, direction))
    return along, math.sqrt(max(0.0, sum(value * value for value in vector) - along * along))


def _area_targets(engine: Any, actor: ActorState, center, area: dict[str, Any], *, include_allies: bool = False, include_self: bool = False, typed: dict[str, Any] | None = None, actors=None) -> list[ActorState]:
    """Shape-aware area membership (owner 2026-09-26): sphere/cylinder/emanation are a radius
    around the aim point; cube/square is a block with the printed side length (see in_area);
    line and cone project onto the caster -> aim-point ray (a 120-foot line no longer catches
    everyone within 120 feet in every direction).

    ``typed`` supplies effects for unscoped/legacy bundles: harmful areas default
    to enemies and exclude their user unless explicitly included. Compiled area
    metadata shares this policy with menu risk previews. Cones/lines emitted
    by the user always exclude that user. Other geometry-only queries keep the
    full roster; explicit self effects use their separate path.
    ``actors`` is an explicit query-only roster used by AI placement estimates.
    Execution omits it and always resolves against the real fight roster.
    """
    from .action_geometry import point
    if typed is not None:
        from .area_recipients import scoped_area
        area = scoped_area(area, typed.get("effects"), typed=typed)
    include_self = include_self or bool(area.get("include_self"))
    from .area_recipients import origin_shape_excludes_user
    exclude_origin_user = origin_shape_excludes_user(area)
    origin = point(engine, actor)
    size = int(area.get("size_ft") or 0)
    shape = area.get("shape") or "sphere"
    aim = center if center is not None else origin
    roster = engine.state.actors.values() if actors is None else actors
    # Geometry-only queries use the full roster. Harmful action queries carry a
    # scoped area from compilation or the typed argument above.
    recipients = area.get("recipients", rules()["defaults"].get("area_targets", "all"))

    if shape == "wall":  # a wall raised across the user's line through the aim point (combat/zones.py)
        from .zones import wall_cells_for

        cells = set(wall_cells_for(engine, actor, aim, size, int(area.get("thick_ft") or 5)))  # the points its user laid out (docket)
        return [other for other in roster
                if other.active and (other.entity_id != actor.entity_id or include_self or (recipients == "all" and not area.get("exclude_self"))) and _area_recipient_matches(actor, other, recipients, include_self=include_self)
                and engine._footprint_intersects(other, cells)]

    from .spatial_areas import actor_in_area
    return [
        other for other in roster
        if other.active and (other.entity_id != actor.entity_id or (not exclude_origin_user and
            (include_self or (recipients == "all" and not area.get("exclude_self")))))
        and _area_recipient_matches(actor, other, recipients, include_self=include_self)
        and actor_in_area(engine, other, origin, aim, area)
    ]


def _area_recipient_matches(actor: ActorState, other: ActorState, recipients: str, *, include_self: bool = False) -> bool:
    """Apply reviewed recipient scopes; unknown values fail closed to enemies."""
    if recipients in ("hostile", "enemies_in_area"):
        return other.entity_id != actor.entity_id and other.team_id != actor.team_id
    if recipients in ("allies", "allies_in_area"):
        return other.team_id == actor.team_id and (include_self or other.entity_id != actor.entity_id)
    if recipients in ("all", "creatures_in_area"):
        return True
    return other.team_id != actor.team_id


def _creature_space_in_area(engine: Any, vertex, aim, creature: ActorState, area: dict[str, Any]) -> bool:
    """A creature is affected when any occupied 5e space lies in the area shape."""
    actor_cells = getattr(engine, "_actor_cells", None)
    if actor_cells is None:
        return in_area(engine, vertex, aim, creature.position, area)
    return any(in_area(engine, vertex, aim, Position(x=x, y=y), area) for x, y in actor_cells(creature))


def _clear_line(engine: Any, origin, position) -> bool:
    """Areas stop at walls (docket 2026-09-28: "The darkness ... cannot extend through walls"): a square is in an area only
    if the straight line from the area's point of origin to it crosses no square that blocks movement -- a wall drawn on
    the map or a solid wall raised in the fight (combat/zones.py sync_walls lays those on the grid). The wall's own
    squares are not in it."""
    roof_blocked = getattr(engine.grid, "roof_ray_blocked", None)
    if roof_blocked is not None and roof_blocked(origin, position):
        return False
    blocked = getattr(engine.grid, "blocked", None)
    if not blocked:
        return True
    if engine.grid.terrain_at(position, "BLOCKED") and position != origin:
        return False
    return not any(engine.grid.terrain_at(cell, "BLOCKED") for cell in engine.grid.effect_ray_cells(origin, position)[1:-1])


def _spread(engine: Any, origin, cells: tuple) -> tuple:
    """An area that "spreads around corners" (Darkness): the squares of its shape it can reach from its center square by
    square without crossing a wall (a diagonal step does not squeeze between two walls)."""
    blocked = getattr(engine.grid, "blocked", None)
    if blocked and (origin.z or engine.grid.finite_heights):
        blocked = {cell for cell in blocked if engine.grid.terrain_at((*cell, origin.z), "BLOCKED")}
    if not blocked:
        return cells
    allowed = {(cell.x, cell.y) for cell in cells} - blocked
    start = (origin.x, origin.y)
    if start not in allowed:
        return tuple(cell for cell in cells if (cell.x, cell.y) in allowed and _clear_line(engine, origin, cell))
    seen, queue = {start}, [start]
    while queue:
        x, y = queue.pop()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxt = (x + dx, y + dy)
                if nxt in seen or nxt not in allowed or (dx and dy and (x + dx, y) in blocked and (x, y + dy) in blocked):
                    continue
                seen.add(nxt)
                queue.append(nxt)
    return tuple(cell for cell in cells if (cell.x, cell.y) in seen)


def in_area(engine: Any, vertex, aim, position, area: dict[str, Any]) -> bool:
    """Whether a square is in an area aimed from ``vertex`` at ``aim``. A sphere, cylinder or emanation is round (owner
    2026-09-27: "all the aoes are square and im pretty sure a number of them are radious not square"): a square is in it
    when its centre lies within the three-dimensional radius of the aim point's centre (feet). A cube or square is the square block around the aim
    point; a line or cone runs from the user through the aim point, or starts at
    the aim point when the reviewed area is marked placed. Cube/square bounds include
    the negative edge and exclude the positive edge: even square counts have no centre square,
    so the aim selects the positive-side middle square (the same tie-break as wall_cells).
    Odd square counts retain their symmetric footprint. This shared membership feeds targets,
    area_cells previews and persisted zones; radius and ray shapes keep their own geometry."""
    size = int(area.get("size_ft") or 0)
    shape = area.get("shape") or "sphere"
    square = engine.grid.square_size_ft
    if shape in ("cube", "square"):
        inside = all(-size / 2 <= offset * square < size / 2
                     for offset in (position.x - aim.x, position.y - aim.y, position.z - aim.z))
        origin = aim
    elif shape == "cylinder" and area.get("height_ft") is not None:
        # Explicit cylinders use a radius on the ground plane and a height
        # above the aim plane. Missing height retains sealed legacy geometry.
        inside = (math.hypot(position.x - aim.x, position.y - aim.y) * square <= size + 1e-9
                  and 0 <= (position.z - aim.z) * square < int(area["height_ft"]))
        origin = aim
    elif shape in ("line", "cone"):
        offsets = _ray_offsets(engine, vertex, aim, position, area)
        if offsets is None:
            return False
        along, perp = offsets
        origin = aim if placed_at_aim(area) else vertex
        # A cone begins beyond its point of origin; creature-wide recipient
        # wording cannot put its caster into the emitted cone. Placed cones
        # use the same rule at their actual vertex. An explicit include_origin
        # geometry choice can include it; broad include_self recipient metadata
        # is not that choice. Lines retain their existing origin behavior.
        if along < 0 or (shape == 'cone' and along == 0 and not area.get('include_origin')) or engine.grid.distance_ft(origin, position) > size:
            return False
        inside = perp <= (float(area.get("width_ft") or 5.0) / 2 if shape == "line" else along * 0.5)
        # Where the shape actually starts: the point it was laid down at, or its user.
        origin = aim if placed_at_aim(area) else vertex
    else:
        inside = math.hypot(position.x - aim.x, position.y - aim.y, position.z - aim.z) * square <= size + 1e-9
        origin = aim
    # Not through a wall (_clear_line); an area that spreads around corners is walked square by square in area_cells.
    return inside and (bool(area.get("spreads")) or _clear_line(engine, origin, position))


def area_cells(engine: Any, vertex, aim, area: dict[str, Any], *, include_altitude: bool = False) -> tuple[Position, ...]:
    """Cells in the area; opt into altitude layers for three-dimensional placement.

    The default retains the sealed aim-plane projection used by existing zones.
    """
    size = int(area.get("size_ft") or 0)
    reach = size // engine.grid.square_size_ft + 1
    shape = area.get("shape") or "sphere"
    # A line or cone runs out from its user, and a ``placed`` one from the point it was laid down at.
    origin = vertex if shape in ("line", "cone") and not placed_at_aim(area) else aim
    xs = range(max(0, origin.x - reach), min(engine.grid.width, origin.x + reach + 1))
    ys = range(max(0, origin.y - reach), min(engine.grid.height, origin.y + reach + 1))
    zs = range(max(0, origin.z - reach), origin.z + reach + 1) if include_altitude else (aim.z,)
    cells = tuple(Position(x=x, y=y, z=z) for z in zs for y in ys for x in xs
                  if in_area(engine, vertex, aim, Position(x=x, y=y, z=z), area))
    return _spread(engine, origin, cells) if area.get("spreads") else cells


ACTIVE_ABILITY = CONDITION_PREFIX + "active_ability"
_CHANGES = {"CONDITION_APPLIED", "MODIFIER_APPLIED", "ZONE_CREATED", "SUMMON_CREATED", "CONCENTRATION_STARTED"}


def _mark_lasting_gm_ability(ctx: Context, first_event: int, riders: list[str]) -> None:
    """An ability that lasts but whose effects the GM applies leaves a marker on its user for as long as it lasts, with its
    text on hover (owner 2026-09-29: Court of Measured Openings was cast and nothing showed it was up)."""
    duration = ctx.typed.get("duration") or {}
    if ctx.typed.get("effects") or str(duration.get("kind") or "instant") in ("instant", "") or not ctx.actor.active:
        return  # only an ability the fight runs nothing for
    if any(event.event_type in _CHANGES and event.source_definition_id == ctx.source for event in ctx.engine.events[first_event:]):
        return  # it put something on the board of its own
    expires = ctx.expires_on()
    if not expires:
        return
    amount, kind = duration.get("amount"), str(duration.get("kind"))
    span = f"{amount} {kind.rstrip('s')}{'s' if amount not in (None, 1) else ''}" if amount else kind.replace("_", " ")
    ctx.engine._apply_condition(ctx.actor, ACTIVE_ABILITY, ctx.source, ctx.actor.entity_id, expires_on=expires,
                                data={"label": f"{ctx.action.display_name} ({span})", "reading": " / ".join(riders)[:900] or None})


def activation_reactions(ctx: Context) -> bool:
    """Offer non-weapon activation reactions; return False if countered.

    Both creature and opted-in object deliveries use this before effects.
    ctx.targets contains only creature recipients (empty for an object), so
    bystanders can answer technique_used without inventing creature targets.
    Costs/preparations are already spent by the caller and are not refunded.
    Pending metadata is activation-local and cleared even if a player choice
    pauses resolution; the table replays the activation with their answer.
    """
    from . import typed_reactions

    engine, actor, action, typed = ctx.engine, ctx.actor, ctx.action, ctx.typed
    numbers = typed.setdefault("numbers", {})
    numbers["_cost"] = sum(int(amount) for _resource, amount in action.costs)
    numbers["_cp_cost"] = sum(int(amount) for resource, amount in action.costs
                              if resource in {"resource:core.qi", "resource:core.stamina", "resource:core.resonance"})
    engine._typed_pending_technique = {"actor": actor.entity_id,
        "save_dc": int(numbers.get("save_dc") or 10), "action_name": action.display_name,
        "technique": typed.get("option_of") or typed.get("source")}
    engine._typed_countered = False
    try:
        typed_reactions.on_technique_start(engine, actor, ctx.targets, typed, ctx.intent)
        return not getattr(engine, "_typed_countered", False)
    finally:
        engine._typed_pending_technique = None
        engine._typed_countered = False


def resolve_typed(engine: Any, actor: ActorState, target: ActorState | None, action: ActionDefinition,
                  candidate: LegalCandidate, intent: ActionIntent) -> None:
    # A local shallow copy (owner 2026-09-26): action.parameters["typed"] is the character's persistent,
    # compiled action data, its "numbers" dict often shared by every one of that character's actions
    # (combat/factory_compiler.py). on_technique_start below may adjust attack_bonus/save_dc for this
    # activation only; mutating the shared dicts in place would leak that adjustment into every later
    # use of this (or any other) action.
    from .paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_opened_before")
    preserve_pending(engine, "_typed_pending_technique")
    preserve_pending(engine, "_typed_countered")
    typed = dict(action.parameters.get("typed") or {})
    typed["numbers"] = dict(typed.get("numbers") or {})
    from . import ext

    from .ext.setting_choices import is_setting_action

    if is_setting_action(action):
        # A standing selector only stores its setting. It is not an activation:
        # no technique hooks, reaction windows, concentration or use accounting.
        run_effects(Context(engine, actor, action, intent, typed, [], None), typed.get("effects") or [])
        return

    ext.run_strict("technique_accepted", engine, actor, action)
    if any(ext.run("technique_start", engine, actor, action)):
        return  # a plug-in stopped it as it started (Speech-Knot Point: the speech falters; combat/ext/speech.py)
    area = typed.get("area")
    if area and area.get("size_ft"):
        targets = _area_targets(engine, actor, candidate.destination, area, typed=typed)
        if (area.get("shape") or "sphere") not in ("line", "cone", "wall"):
            # What a "toward the center" pull (or an "away from the center" push) is measured from: the point the area is aimed at.
            from .action_geometry import point
            aim = candidate.destination if candidate.destination is not None else point(engine, actor)
            typed["_area_centre"] = (aim.x, aim.y)
        elif candidate.destination is not None:
            typed["_area_aim"] = (candidate.destination.x, candidate.destination.y)  # where a cone or line is pointed (ext ``ally_subjects``)
    else:
        # SELF supplies an implicit actor fallback. A selected creature target,
        # including the user of ANY_CREATURE/ALLY_OR_SELF, is an actual recipient.
        explicit_self = action.target_kind != 'SELF' and actor.entity_id in candidate.target_ids
        targets = [target] if target is not None and (target is not actor or explicit_self) else []
    from .target_knowledge import location_missed
    missed_target_ids = tuple(subject.entity_id for subject in targets
                              if location_missed(engine, actor, subject, action.source_definition_id))
    targets = [subject for subject in targets if subject.entity_id not in missed_target_ids]
    if typed.get("requires_hearing"):
        # "Creatures that can hear you" (Iron Voice, Heaven-Silencing Word): a Deafened one is not reached.
        from .speech import can_hear_from
        targets = [row for row in targets if can_hear_from(engine, actor, row, action.source_definition_id)]
    engine._typed_opened_before = None  # action-local guard bookkeeping
    ctx = Context(engine, actor, action, intent, typed, targets, targets[0] if len(targets) == 1 else None,
                  missed_target_ids=missed_target_ids)
    ctx.damage_cache["_checkpoint_aim"] = candidate.destination
    if action.target_kind == "SELF" and teleport_reach(engine, actor, action) is not None:
        ctx.destination = candidate.destination
    # Plug-ins may resolve an opted-in recipient decision here. The final
    # action-local roster must be known before target reactions are offered.
    from .recipient_choices import apply as choose_recipients
    choose_recipients(ctx)
    targets = ctx.targets
    if typed.get("weapon") is None and not (missed_target_ids and not targets):
        # Not a weapon/unarmed attack (those open ATTACK_DECLARED/ATTACK_MISSED windows of their own
        # via block_attack below): offer technique_targets/technique_used reactions first.
        if not activation_reactions(ctx):
            return
    ctx.target = targets[0] if len(targets) == 1 else None
    if 'cell_placement' in action.parameters:
        from . import cell_placement
        if not cell_placement.legal(engine, actor, action, candidate.destination):
            engine._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=actor.entity_id,
                payload={'log': f'{action.display_name} fails: the chosen space is unavailable. Any action and resources already spent are not refunded.'})
            return
        cell_placement.record(engine, actor, action, candidate.destination)
        ctx.destination = candidate.destination
    ctx.damage_cache["_checkpoint_aim"] = candidate.destination
    if action.target_kind == "SELF" and teleport_reach(engine, actor, action) is not None:
        ctx.destination = candidate.destination
    if (typed.get("duration") or {}).get("concentration"):
        engine._start_concentration(actor, action.source_definition_id)
    first_event = len(engine.events)
    if typed.get("zone_spec") and not missed_target_ids and not any(isinstance(effect, dict) and effect.get("type") == "zone" for effect in typed.get("effects") or []):
        from . import zones

        zones.create(ctx, typed["zone_spec"])  # e.g. Ashfall, whose text is all area: "The area becomes Ash Terrain"
    unmaking_use = typed.get("sphere") == "tianxia.sphere.unmaking"
    if unmaking_use:
        from . import unmaking

        unmaking.impaired_cost(engine, actor, int(typed["numbers"].get("pb") or 2), action.source_definition_id)
    # General seam: the journal index where this use's own effects begin. ``technique_used``
    # subscribers receive only ``ctx``, so an ability whose printed trigger names something
    # the effect did to several creatures at once (a cone hurting more than one recipient)
    # reads this window instead of guessing which packet came first. It is set for the whole
    # of this use, including nested hit and save rows, and is resolution-local.
    ctx.technique_event_start = first_event
    with activation_hold(engine, typed):
        run_effects(ctx, typed.get("effects") or [])
    from . import ext

    ext.run("technique_used", ctx)
    if unmaking_use and actor.active:
        damaged = next((engine.state.actors.get(target_id) for event in engine.events[first_event:]
                        if event.event_type == "DAMAGE_COMMITTED" and event.actor_id == actor.entity_id and event.source_definition_id == action.source_definition_id
                        and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
                        for target_id in event.target_ids if target_id != actor.entity_id), None)
        if damaged is not None:
            unmaking.after_unmaking_damage(ctx, damaged)  # Black Trace's Mark, Overdraw
    if typed.get("weapon") is None:
        from . import typed_reactions

        typed_reactions.after_technique(engine, actor, {target_id for event in engine.events[first_event:]
                                                          if event.event_type == "DAMAGE_COMMITTED" and event.source_definition_id == action.source_definition_id
                                                          for target_id in event.target_ids})
    # One GM call per use carries every untyped line (a CL10 tournament fighter
    # produced 1,405 separate calls in 11 fights, one per line per use).
    riders = [" ".join(str(rider).split()) for rider in typed.get("riders") or [] if str(rider).strip()]
    if riders:
        ctx.rider(" / ".join(riders)[:1200])
    elif (action.parameters or {}).get("inert") and "gm_text" in typed and not any(event.event_type == "GM_RIDER" for event in engine.events[first_event:]):
        # Nothing here is automated (owner 2026-09-28: "when i click them nothing happens"): say so, with its text. Only
        # for characters compiled since (their "gm_text"), so fights saved before replay unchanged.
        ctx.rider(f"{action.display_name} is not automated; the GM resolves it. {typed.get('gm_text') or ''}".strip()[:1200])
    _mark_lasting_gm_ability(ctx, first_event, riders)
    engine._run_final_riders("technique_final", ctx)
