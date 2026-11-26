"""Roll-modifier riders raise the printed damage roll instead of opening a second packet.

Several printed riders do not deal damage of their own; they modify a damage roll that is
already being made: Daemonic Cultivation's Demon Mark reads "once per turn when you damage
it, add Proficiency Bonus to the damage", and its Daemonic Augment option reads "add
Proficiency Bonus to one damage roll".  ``extra_damage`` is the typed home for both, but
``block_damage`` committed such a row as its own packet -- its own roll, its own reaction
window and (with no ``damage_types``) an "untyped" log line -- so a bonus never reached the
roll it was printed to modify, and the named bonus was invisible to the player.

This module recognises a *roll modifier*: a dice-free ``extra_damage`` whose printed
evidence adds a value **to** a damage roll or **to** the damage.  Rows that grant their own
damage ("you deal additional X damage", "the target takes extra X damage") keep their own
typed packet.  A modifier is then folded into the damage roll that reaches its target, at
whichever printed fold point that is:

* ``attack_damage_bonus`` for a typed attack -- this hook sees each attempt separately, with
  that attempt's real target, and is the ONLY place an attack's bonus is added.  An attack
  sequence shares one set of dice across every strike and every target (typed_executor
  ``_damage_dice`` at the top of ``block_attack``), and that dice is shaped before any strike
  is rolled, so a bonus added there would be paid on every strike -- including a missed one.
  Armed riders are reserved here and spent by ``attack_result`` after damage commits,
  before later hit subscribers can reuse the same clock, on the creature that was
  actually damaged; ``after_miss`` gives the rider back for a later attempt.
* ``damage_roll_bonus`` for a typed damage effect's own roll, which has already survived its
  save or its aim and therefore always lands.

An area rolls **once** for every creature in it and shares that roll between them, so a
bonus that names one creature is not part of the printed roll at all: the shared roll stays
exactly what the area printed, and the bound rider is added to that one creature's damage at
delivery through the ``deal_bonus`` seam in ``_deal_in_chain``.  A chosen "add ... to one
damage roll" option names no creature, so it is folded into the shared roll and charged once
for the whole area.

Folding *moves* a bonus, so the row's ordinary use-clock keys are recorded when damage
lands, after checking eligibility and effect/recipient vetoes. A row whose gate is already spent, that this
character's level does not allow, or that was not the chosen option is therefore never folded
and never charged.

The executor's per-turn gate is shared with ``_on_hit_bonuses`` (see
``typed_executor.on_hit_turn_key`` and ``spend_on_hit_rider``), so a rider consumed by the roll is not also fired as
its own packet afterwards, and a rider whose attack missed stays armed for a later hit.

Inert without an armed or sibling roll modifier: no subscriber contributes, no damage, no
new event, and every other ability and every saved fight is unchanged.
"""

from __future__ import annotations

import re
from typing import Any

from . import hook
from .rider_support import area_recipients

# A printed "add/adds ... to ... damage (roll)": the bonus modifies a roll being made.
# Deliberately narrow, so rows that grant their own damage keep their own packet.
ROLL_MODIFIER = re.compile(
    r"\badd(?:s|ed)?\b[^.;]*?\bto\s+(?:one|a|an|the|that|its|this)\s+(?:\w+\s+){0,3}damage(?:\s+roll)?\b", re.I)
# A rider only about "this" creature ("when you damage it"). One that also names a weapon,
# a range or a damage type is left to the ordinary on-hit path, so this module never folds
# a bonus it has not fully qualified.
_BOUND_RIDER = re.compile(r"\bwhen you (?:damage|hit) it\b", re.I)
_RESTRICTED = re.compile(r"\b(unarmed|weapon|melee|ranged|natural weapon|"
                         r"acid|cold|fire|force|lightning|necrotic|poison|psychic|radiant|thunder)\b", re.I)
ONCE_PER_TURN = re.compile(r"\bonce (?:per|each) turn\b|\beach turn\b|\bduring each of your turns\b", re.I)

# Resolution-local bookkeeping (a damage_cache, so it never reaches a saved fight).
# _FOLDED marks a sibling row whose bonus already went into a roll; _RESERVED
# holds (creature id, turn-flag key, turn, source context, row) for a rider waiting to be spent by that creature's
# hit; _PENDING holds (creature id, rows) for a sibling folded into a roll that creature's
# attack has not resolved yet.
_FOLDED = "_roll_mod_folded"
_RESERVED = "_roll_mod_reserved"
_PENDING = "_roll_mod_pending"


def _clean(text: Any) -> str:
    return " ".join(str(text or "").split())


def is_roll_modifier(row: dict[str, Any] | None) -> bool:
    """Whether a typed ``extra_damage`` row modifies a damage roll rather than dealing its own.

    A dice-bearing row keeps its own packet (an added ``1d8`` is a second roll the printed
    text grants outright); this recognises only a flat, formula-driven bonus that the text
    adds to a roll or to the damage.
    """
    if not row or row.get("type") != "extra_damage" or row.get("dice"):
        return False
    return bool(ROLL_MODIFIER.search(_clean(row.get("evidence"))))


def _matched_row(rows: Any, evidence: str) -> dict[str, Any] | None:
    """Return the registered deferred modifier, retaining its amount and restrictions."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if row.get("deferred") and is_roll_modifier(row) and _clean(row.get("evidence")) == evidence:
            return row
        for branch in ("on_hit", "on_miss", "on_fail", "on_success", "effects"):
            found = _matched_row(row.get(branch), evidence)
            if found is not None:
                return found
    return None


def _armed_riders(ctx: Any, target: Any) -> list[tuple[Any, dict[str, Any], str, str]]:
    """The actor's armed, per-turn, roll-modifier riders that this target's damage triggers.

    Only the universal case is folded: bound to exactly this creature, a plain "add ... to
    the damage", no weapon/range/damage-type limit.  The executor's on-hit path owns every
    other rider, and the shared per-turn gate keeps one use per turn across both.
    """
    from .. import typed_executor as te

    if target is None:
        return []
    out = []
    for modifier in list(ctx.actor.modifiers.values()):
        if modifier.target_field != "typed_on_hit":
            continue
        bound, evidence = (str(modifier.value).split("|", 2) + ["", ""])[:2]
        evidence = _clean(evidence)
        if not bound or bound != target.entity_id or not _BOUND_RIDER.search(evidence):
            continue
        if _RESTRICTED.search(evidence) or not ONCE_PER_TURN.search(evidence):
            continue
        if "during each of your turns" in evidence.lower() and ctx.engine.state.current_actor_id != ctx.actor.entity_id:
            continue
        action = ctx.engine.action_catalog.get(modifier.source_definition_id)
        typed = ((action.parameters or {}).get("typed") or {}) if action is not None else {}
        row = _matched_row(typed.get("effects"), evidence)
        if row is None:
            continue
        key, turn = te.on_hit_turn_key(ctx.engine, ctx.actor, modifier.source_definition_id, evidence)
        if not te.on_hit_rider_available(ctx.engine, ctx.actor, key, turn, target.entity_id):
            continue  # this turn's use is already spent
        source_ctx = ctx.on_hit_context(target, action=action, typed=typed,
                                        damage_cache={"_potency_used": True, "_bonus": True})
        immediate = {**row, "deferred": False, "applies_to": "target"}
        if not _permitted(source_ctx, immediate, [target]):
            continue
        out.append((source_ctx, immediate, key, turn))
    return out


def _fold_armed(ctx: Any, target: Any, *, commit: bool) -> int:
    """Sum the armed roll modifiers for ``target`` and record how to consume each.

    ``commit`` spends the executor's per-turn gate now, for a roll that always lands (a typed
    damage effect's own roll, or a rider delivered to one recipient of a shared area roll).
    The attack path reserves against the creature instead and lets that creature's own
    ``attack_result`` commit, so a miss gives the rider back.
    """
    from .. import typed_executor as te

    total = 0
    held_keys = set()
    held_clocks = set()
    for source_ctx, row, key, turn in _armed_riders(ctx, target):
        clocks = {(field, row[field]) for field in ("once_per_turn", "once_per_fight") if row.get(field)}
        if key in held_keys or clocks & held_clocks:
            continue
        amount = source_ctx.formula(row.get("formula")) + int(row.get("flat") or 0)
        if not amount:
            continue
        if commit and not te.spend_on_hit_rider(ctx.engine, ctx.actor, key, turn, target.entity_id):
            continue
        total += amount
        held_keys.add(key)
        held_clocks.update(clocks)
        if commit:
            _consume(source_ctx, row)
        else:
            ctx.damage_cache.setdefault(_RESERVED, []).append((target.entity_id, key, turn, source_ctx, row))
    return total


def _shared_roll(ctx: Any) -> list[str]:
    """The creature ids sharing one roll, or ``[]`` when this roll reaches one creature alone.

    The shared query lives in combat/ext/rider_support.py (area_recipients), which combat/ext/death_riders.py
    reads for the same "one roll, several creatures" case.
    """
    return area_recipients(ctx)


def _fold_siblings(ctx: Any, *, target: Any = None, pending: bool = False, hit_rows=()) -> int:
    """Fold the activation's own sibling roll modifiers into the roll being made.

    A chosen "add ... to one damage roll" option is a sibling of the effect it modifies, so
    it is added to that effect's printed roll and then suppressed as a packet.  A row is
    folded only when the shared ``effect_eligibility`` contract allows it, so a spent
    once-per-turn gate, a level this character is not yet at, and an option that was not
    chosen are all left to the ordinary path.

    ``pending`` records the rows against ``target`` while the roll is still being made: an
    attack that misses hands the option back so a later attempt can fold it instead.
    """
    from .. import typed_executor as te

    total = 0
    rows: list[dict[str, Any]] = []
    held_clocks = set()
    recipient_ctx = ctx.on_hit_context(target) if target is not None else ctx
    for row in [*(ctx.typed.get("effects") or []), *hit_rows]:
        if not is_roll_modifier(row) or ctx.damage_cache.get(f"{_FOLDED}:{id(row)}"):
            continue
        if row.get("deferred"):
            continue  # registration is not qualification of a later trigger
        clocks = {(field, row[field]) for field in ("once_per_turn", "once_per_fight") if row.get(field)}
        if clocks & held_clocks:
            continue  # the first folded row reserves this damage use until attack_result
        recipients = ctx.damage_cache.get("_area_targets") or recipient_ctx.targets
        if not recipients or not all(
            [s.entity_id for s in te.effect_subjects(recipient_ctx.on_hit_context(subject), row, harmful=True)]
            == [subject.entity_id]
            and _permitted(recipient_ctx.on_hit_context(subject), row, [subject])
            for subject in recipients):
            # A shared roll may fold only if every recipient permits the bonus.
            # Mixed eligibility retains the ordinary row's recipient filtering.
            continue
        amount = ctx.formula(row.get("formula")) + int(row.get("flat") or 0)
        if not amount:
            continue
        ctx.damage_cache[f"{_FOLDED}:{id(row)}"] = True
        rows.append(row)
        held_clocks.update(clocks)
        total += amount
        if not pending:
            _consume(ctx, row)
    if pending and rows and target is not None:
        ctx.damage_cache.setdefault(_PENDING, []).append((target.entity_id, rows))
    return total


def _permitted(ctx: Any, row: dict[str, Any], subjects: Any) -> bool:
    """Keep eligibility, all damage clocks and recipient vetoes before moving a row."""
    from ..effect_eligibility import eligible
    from . import effect_permitted

    if not eligible(ctx, row):
        return False
    if any(row.get(field) and ctx.actor.turn_flags.get(f"{prefix}:{row[field]}")
           for field, prefix in (("once_per_turn", "typed_once_turn"),
                                 ("once_per_fight", "typed_round_once"))):
        return False
    return effect_permitted(ctx, row, subjects, exclude=suppress_folded_sibling)


def _consume(ctx: Any, row: dict[str, Any]) -> None:
    """Record the same use keys as run_effects and block_damage, once damage lands."""
    from ..effect_eligibility import modifier_key

    gate = row.get("modifier_once")
    if gate:
        ctx.actor.turn_flags[modifier_key(row)] = True
        ctx.damage_cache[("modifier_once", gate)] = True
    for field, prefix in (("once_per_turn", "typed_once_turn"), ("once_per_fight", "typed_round_once")):
        if row.get(field):
            ctx.actor.turn_flags[f"{prefix}:{row[field]}"] = True


@hook("attack_damage_bonus")
def fold_into_attack(ctx: Any, target: Any, effect_row: dict[str, Any] | None) -> int | None:
    """Add a bound rider and a chosen "one damage roll" option to one attack's damage.

    This hook runs once per attempt with that attempt's real target, so neither a retargeted
    attack nor a second target nor a second strike repeats the bonus.  Both contributions are
    reserved rather than spent: ``attack_result`` commits the rider for the creature that was
    damaged, and ``after_miss`` gives both back for a later attempt.
    """
    if ctx.damage_cache.get("_bonus"):
        return None  # this roll is itself a rider's own packet
    hit_rows = (effect_row or {}).get("on_hit") or []
    total = _fold_armed(ctx, target, commit=False) + _fold_siblings(
        ctx, target=target, pending=True, hit_rows=hit_rows)
    return total or None


def fold_confirmed_rows(ctx: Any, target: Any, rows: list[dict]) -> int:
    """Attack loadouts use the same eligibility, reservation and clock delivery as siblings."""
    return _fold_siblings(ctx, target=target, pending=True, hit_rows=rows)


@hook("damage_roll_bonus")
def fold_into_damage(ctx: Any, effect_row: dict[str, Any] | None, kinds: list[str] | None) -> int | None:
    """Add a bound rider and a chosen option to a typed damage effect's printed roll.

    ``effect_row`` is ``None`` for the shared dice of an attack sequence (typed_executor
    ``block_attack``).  That dice is shaped once, before any strike or target is rolled, so
    nothing is added there; ``attack_damage_bonus`` is the per-attempt fold point.  A typed
    damage roll has already survived its save or its aim, so what lands here is committed.
    """
    if ctx.damage_cache.get("_bonus"):
        return None
    if effect_row is None:
        return None  # an attack sequence's shared dice: see attack_damage_bonus
    # A row that is itself a roll modifier keeps its own packet and never folds options into itself.
    total = 0 if is_roll_modifier(effect_row) else _fold_siblings(ctx)
    if _shared_roll(ctx):
        # One roll, several creatures. The printed option names no creature, so it joins the
        # shared roll; a bound rider names one creature, so it is not in this roll at all and is
        # delivered per recipient by the deal_bonus hook instead.
        return total or None
    return (_fold_armed(ctx, ctx.target, commit=True) + total) or None


@hook("deal_bonus")
def deliver_to_recipient(ctx: Any, subject: Any, amount: int) -> int | None:
    """Add a bound rider to its creature's damage, including a flat damage packet.

    Fixed damage has no dice hook, so its bound rider is folded here too. The
    shared per-turn gate skips riders already folded into a roll or attack.
    An area's shared roll stays exactly what it printed. Whether its marked creature is
    rolled for first or last decides whether ``damage_roll_bonus`` is reached for it at all --
    a cached roll is reused without calling that hook -- so the decision is made here, per
    recipient, rather than once at the roll.  The use is charged here because this creature has
    only just been damaged.  Every other creature, and any roll of its own, is untouched.
    """
    if ctx.damage_cache.get("_bonus"):
        return None
    if subject is None or amount <= 0:
        return None
    return _fold_armed(ctx, subject, commit=True) or None


@hook("attack_result")
def commit_reservation(ctx: Any, target: Any, hit: bool, critical: bool) -> None:
    """Spend landed reservations before later hit subscribers make their own damage rolls."""
    from .. import typed_executor as te

    if not hit:
        return
    if ctx.attack_damage_context is not None:
        target = ctx.engine.state.actors[ctx.attack_damage_context.target_id]
    reserved = ctx.damage_cache.get(_RESERVED) or []
    for creature, key, turn, source_ctx, row in reserved:
        if creature == target.entity_id:
            if te.spend_on_hit_rider(ctx.engine, ctx.actor, key, turn, target.entity_id):
                _consume(source_ctx, row)
    held = [entry for entry in reserved if entry[0] != target.entity_id]
    if held:
        ctx.damage_cache[_RESERVED] = held
    else:
        ctx.damage_cache.pop(_RESERVED, None)
    # A sibling folded into this creature's roll was made; keep it folded.
    for creature, rows in ctx.damage_cache.get(_PENDING) or []:
        if creature == target.entity_id:
            for row in rows:
                _consume(ctx, row)
    pending = [entry for entry in ctx.damage_cache.get(_PENDING) or [] if entry[0] != target.entity_id]
    if pending:
        ctx.damage_cache[_PENDING] = pending
    else:
        ctx.damage_cache.pop(_PENDING, None)


@hook("after_miss")
def release_reservation(ctx: Any, target: Any) -> None:
    """A miss on this creature damaged nothing, so its rider and option stay unspent."""
    held = [entry for entry in ctx.damage_cache.get(_RESERVED) or [] if entry[0] != target.entity_id]
    if held:
        ctx.damage_cache[_RESERVED] = held
    else:
        ctx.damage_cache.pop(_RESERVED, None)
    pending = [entry for entry in ctx.damage_cache.get(_PENDING) or [] if entry[0] != target.entity_id]
    for creature, rows in ctx.damage_cache.get(_PENDING) or []:
        if creature == target.entity_id:
            for row in rows:
                ctx.damage_cache.pop(f"{_FOLDED}:{id(row)}", None)
    if pending:
        ctx.damage_cache[_PENDING] = pending
    else:
        ctx.damage_cache.pop(_PENDING, None)


@hook("effect_allowed")
def suppress_folded_sibling(ctx: Any, row: dict[str, Any]) -> bool | None:
    """A sibling roll modifier already folded into this activation's roll is not a packet.

    The fold records the ordinary clocks when damage lands (immediately for a damage
    effect, attack_result for an attack). Suppression consumes nothing and cannot turn
    an unqualified deferred registration into an immediate effect.
    """
    if not is_roll_modifier(row) or not ctx.damage_cache.get(f"{_FOLDED}:{id(row)}"):
        return None
    return False
