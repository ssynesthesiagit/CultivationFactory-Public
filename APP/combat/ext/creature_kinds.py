"""Creature kinds for typed rows and plug-ins (rider lane C12, 2026-09-30 -- shared helper).

Creature labels have been persisted since lock round 4 (combat/creature_types.py: explicit printed creature_type /
creature_types on Factory identity, portable stat blocks and summon stat blocks), but nothing used them, so every line that
turns on a kind ("has no effect on undead or constructs", "if the target is Unclean", "if the target is a construct") stayed
the GM's. This module is the one place that answers "is this creature of that kind":

  matches(actor, kinds)   True when the creature carries one of the printed labels (case-insensitive, exact label;
                          "undead" also matches "Undead", "constructs" matches "Construct"). Unknown creatures (no label)
                          never match: nothing is inferred from a name, race, condition or immunity.
  "unclean"               the Radiance classification (Sphere Compendium, Radiance, "Unclean Targets": undead; a demon, fiend,
                          corrupted spirit, or possession entity; or applied by stat block). A creature labelled Undead,
                          Demon, Fiend, Corrupted Spirit, Possession Entity or Unclean counts. A creature explicitly
                          labelled Possessed or Possessing also counts. Unlabelled corruption and GM
                          rulings remain the GM's; names, conditions and immunities never imply a label.

Typed effects (same shape as if_marked; they only ever narrow who the nested rows reach):
  if_creature_kind      {"kinds": [...], "effects": [...], "else": [...], "once_per_turn": "<key>"}
                        runs ``effects`` for this activation's own target(s) of a listed kind and ``else`` for the others.
                        ``once_per_turn`` ("once per turn, if ... an Unclean target"): after it has run for a matching target
                        once in the user's turn, later targets take ``else``. The nested rows keep this activation's attack
                        context (critical hits, provenance), so an on-hit damage row inside still doubles on a critical.
Any effect row may carry ``unless_kind``: {"kinds": [...], "except_owner_modifier": "<feature id>"} ("has no effect on
undead or constructs"): an action whose targets are all of a listed kind is not offered against them (candidate_allowed),
and each excluded recipient is skipped through effect_subject_allowed, including mixed-target rows. Extension effects
use typed_executor.effect_subjects to honor the same recipient filter. ``except_owner_modifier``: when the user compiled that modifier talent (Esoteric
Vitality: "Mend the Pulse ... can affect undead, constructs ..."), nothing is held back.
Damage rows may carry ``bonus_if_kind``: {"kinds": [...], "formula": "pb", "once_per_turn": "<key>"} adds that amount to the
row's damage roll when its single target is of a listed kind -- "add your Proficiency Bonus to one damage roll". A damage
row of its own uses the ``damage_roll_bonus`` hook (added once to the roll, after dice selection and before defenses; area
rolls shared by several targets take no bonus). On an attack's ``on_hit`` damage row the bonus rides that attack's damage
(``attack_damage_bonus``), and ``once_per_turn`` is spent only when the attack hits (``after_hit``; a miss keeps it). Save rows may also carry ``disadvantage_if_kind`` (typed_executor's save block): the listed kinds roll that save with
Disadvantage ("Unclean creatures have Disadvantage on the saving throw").

Inert for creatures without labels and for abilities without these rows. Stored state: one turn flag per
``once_per_turn`` key (a bool), cleared with the user's turn flags. Owned ``unarmed_kind_bonus`` rows instead
store a round/current-actor string: their limit applies separately on each creature's turn, including reactions.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from . import effect, hook, note

UNCLEAN = ("undead", "demon", "fiend", "corrupted spirit", "possession entity", "possessed", "possessing", "unclean")
# Explicit printed vocabulary only. Animated is not automatically a Construct;
# Mindless is not inferred from Intelligence, immunity, or being Undead.
_ALIASES = {"fiendish": "fiend", "demonic": "daemonic", "daemonic-tagged": "daemonic",
            "daemonically corrupted": "daemonic corruption", "possessing entity": "possession entity",
            "possessor": "possession entity", "spirit-beast": "spirit beast"}
_PLURALS = {"undead", "construct", "demon", "fiend", "beast", "celestial", "elemental", "aberration", "ghost", "spirit",
            "plant", "ooze", "giant", "dragon", "humanoid", "monstrosity", "fey", "intruder", "host",
            "curse source", "spirit asset", "projected soul", "possession entity", "puppet body", "clone",
            "projection", "possession vessel", "temporary body", "haunt", "spirit parasite", "spirit beast", "yokai",
            "undead spirit", "incorporeal undead", "animated construct", "summoned construct"}
_MEMBERS = {"undead spirit": {"undead", "spirit"}, "incorporeal undead": {"undead"},
            "animated construct": {"animated", "construct"}, "summoned construct": {"construct", "summoned"}}
_ONCE = "creature_kind_once:"


def _norm(label: str) -> str:
    text = " ".join(str(label).split()).casefold()
    text = _ALIASES.get(text, text)
    if text.endswith("ies") and text[:-3] + "y" in _PLURALS:
        text = text[:-3] + "y"
    elif text.endswith("ies") and text[:-3] + "y" in _ALIASES:
        text = _ALIASES[text[:-3] + "y"]
    elif text.endswith("s") and text[:-1] in _PLURALS:
        text = text[:-1]
    elif text.endswith("s") and text[:-1] in _ALIASES:
        text = _ALIASES[text[:-1]]
    return _ALIASES.get(text, text)


def labels(actor: Any) -> set[str]:
    from ..creature_types import types_for

    try:
        printed = {_norm(label) for label in types_for(actor)}
        return printed | {member for label in printed for member in _MEMBERS.get(label, ())}
    except (AttributeError, TypeError):
        return set()


def matches(actor: Any, kinds: Any) -> bool:
    """Match explicit printed kinds, their listed compound members, or Radiance's Unclean classification."""
    if actor is None:
        return False
    have = labels(actor)
    if not have:
        return False
    wanted: set[str] = set()
    for kind in ([kinds] if isinstance(kinds, str) else list(kinds or [])):
        kind = _norm(kind)
        wanted.update(_norm(member) for member in UNCLEAN) if kind == "unclean" else wanted.add(kind)
    return bool(have & wanted)


def normalize(label: Any) -> str:
    """One printed label in the spelling :func:`matches` compares by (shared by Fate's Hallow category menu).

    Lets a caller that lists categories of its own (the Hallow Mandate Edict menu, which offers the printed
    list plus the categories this fight's creatures carry) drop the ones it already lists.
    """
    return _norm(str(label))


def is_unclean(actor: Any) -> bool:
    return matches(actor, ["unclean"])


def owns_modifier(engine: Any, actor: Any, feature: str) -> bool:
    """Whether the creature's compiled character carries ``feature`` as a modifier talent (its bundle's modifier report)."""
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == getattr(actor, "entity_id", None):
            return any(row.get("id") == feature for row in bundle.get("modifiers") or [] if isinstance(row, dict))
    return False
@hook('zone_recipient_allowed')
def zone_kinds(engine, zone, actor, spec):
    kinds = spec.get('requires_kind')
    return matches(actor, kinds) if kinds else None




def _subjects(ctx: Any, row: dict[str, Any]) -> list[Any]:
    if row.get("applies_to") == "self":
        return [ctx.actor]
    pool = [ctx.target] if ctx.target is not None else list(ctx.targets or [])
    return [subject for subject in pool if subject is not None]


def _run(ctx: Any, subjects: list[Any], rows: list[dict[str, Any]]) -> None:
    from .. import typed_executor

    if not subjects or not rows:
        return
    inner = dataclasses.replace(ctx, targets=list(subjects), target=subjects[0] if len(subjects) == 1 else None)
    typed_executor.run_effects(inner, rows)


@effect("if_creature_kind")
def if_creature_kind(ctx: Any, row: dict[str, Any]) -> None:
    kinds = row.get("kinds") or []
    pool = _subjects(ctx, row)
    key = f"{_ONCE}{row['once_per_turn']}" if row.get("once_per_turn") else None
    used = bool(key and ctx.actor.turn_flags.get(key))
    chosen, others = [], []
    for subject in pool:
        if not used and matches(subject, kinds):
            chosen.append(subject)
            if key:
                used = True  # once per turn: the first matching target takes it, the rest take ``else``
        else:
            others.append(subject)
    if chosen and key:
        ctx.actor.turn_flags[key] = True
        note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} uses {ctx.action.display_name}'s extra effect. It is available again at the start of their next turn.")
    _run(ctx, chosen, row.get("effects") or [])
    _run(ctx, others, row.get("else") or [])


@hook("damage_roll_bonus")
def kind_damage_bonus(ctx: Any, effect: Any, kinds: Any) -> int | None:
    row = (effect or {}).get("bonus_if_kind") if isinstance(effect, dict) else None
    if not isinstance(row, dict):
        return None
    targets = ctx.damage_cache.get("_area_targets") or list(ctx.targets or []) or ([ctx.target] if ctx.target is not None else [])
    targets = [target for target in targets if target is not None]
    if len(targets) != 1 or not matches(targets[0], row.get("kinds") or []):
        return None
    key = f"{_ONCE}{row['once_per_turn']}" if row.get("once_per_turn") else None
    if key and ctx.actor.turn_flags.get(key):
        return None
    if key:
        ctx.actor.turn_flags[key] = True
    return int(ctx.formula(str(row.get("formula") or "none")) + int(row.get("flat") or 0))


def _blocked(engine: Any, actor: Any, row: Any, subjects: list[Any]) -> bool:
    if isinstance(row, dict) and row.get("only_kind") and subjects and all(not matches(subject, row["only_kind"]) for subject in subjects):
        return True
    gate = row.get("unless_kind") if isinstance(row, dict) else None
    if not isinstance(gate, dict) or not subjects:
        return False
    if gate.get("except_owner_modifier") and owns_modifier(engine, actor, str(gate["except_owner_modifier"])):
        return False
    return all(matches(subject, gate.get("kinds") or []) for subject in subjects)


@hook("effect_allowed")
def kind_effect_allowed(ctx: Any, row: Any) -> bool | None:
    if isinstance(row, dict) and row.get("applies_to") == "ally":
        # Ally resolution can select creatures outside ctx.targets (a protected
        # ally or allies near the user). The subject hook filters that real list.
        return None
    subjects = _subjects(ctx, row) if isinstance(row, dict) else []
    return False if _blocked(ctx.engine, ctx.actor, row, subjects) else None


@hook("effect_subject_allowed")
def kind_subject_allowed(ctx: Any, row: Any, subject: Any) -> bool | None:
    return False if _blocked(ctx.engine, ctx.actor, row, [subject]) else None


@hook("candidate_allowed")
def kind_candidate_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    rows = [row for row in (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects") or [])
            if isinstance(row, dict) and (row.get("unless_kind") or row.get("only_kind"))]
    if not rows:
        return None
    subjects = [engine.state.actors[t] for t in (getattr(candidate, "target_ids", None) or ()) if t in engine.state.actors]
    return False if all(_blocked(engine, actor, row, subjects) for row in rows) else None


@hook("attack_damage_bonus")
def unarmed_kind_bonus(ctx: Any, target: Any, effect: Any) -> int | None:
    """Owned path_passive/unarmed_kind_bonus: flat bonus to the hit's damage roll."""
    if not isinstance(effect, dict) or effect.get("attack_kind") != "unarmed" or target is None:
        return None
    bonus = 0
    stamp = f"{ctx.engine.state.round_number}:{ctx.engine.state.current_actor_id}"
    for row in (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, []):
        if row.get("block") != "path_rider" or row.get("kind") != "unarmed_kind_bonus" or not matches(target, row.get("kinds")):
            continue
        key = _ONCE + str(row["feature_id"])
        used = ctx.actor.turn_flags.get(key)
        if isinstance(used, int) and used:
            # Prior saves stored 1 without a turn identity. Conservatively
            # count the current turn as spent, then let later turns qualify.
            ctx.actor.turn_flags[key] = stamp
            continue
        if used == stamp:
            continue
        ctx.damage_cache.setdefault("_unarmed_kind_pending", []).append((target.entity_id, key, stamp))
        bonus += int(row["pb"])
    return bonus or None


@hook("after_hit")
def unarmed_kind_landed(ctx: Any, target: Any, kind: Any) -> None:
    for target_id, key, stamp in ctx.damage_cache.pop("_unarmed_kind_pending", []):
        if target_id == getattr(target, "entity_id", None):
            ctx.actor.turn_flags[key] = stamp


@hook("after_miss")
def unarmed_kind_missed(ctx: Any, target: Any) -> None:
    ctx.damage_cache.pop("_unarmed_kind_pending", None)


def _on_hit_bonus(effect: Any) -> dict[str, Any] | None:
    for row in (effect or {}).get("on_hit") or [] if isinstance(effect, dict) else []:
        if isinstance(row, dict) and row.get("type") in ("damage", "extra_damage") and isinstance(row.get("bonus_if_kind"), dict):
            return row["bonus_if_kind"]
    return None


@hook("attack_damage_bonus")
def kind_attack_bonus(ctx: Any, target: Any, effect: Any) -> int | None:
    row = _on_hit_bonus(effect)
    if row is None or not matches(target, row.get("kinds") or []):
        return None
    key = f"{_ONCE}{row['once_per_turn']}" if row.get("once_per_turn") else None
    if key and ctx.actor.turn_flags.get(key):
        return None
    ctx.damage_cache["_creature_kind_pending"] = (target.entity_id, key or "", ctx.engine.state.event_sequence)
    return int(ctx.formula(str(row.get("formula") or "none")) + int(row.get("flat") or 0))


@hook("after_hit")
def kind_bonus_landed(ctx: Any, target: Any, kind: Any) -> None:
    pending = ctx.damage_cache.pop("_creature_kind_pending", None) if hasattr(ctx, "damage_cache") else None
    dealt = pending and any(e.sequence > pending[2] and e.event_type == 'DAMAGE_COMMITTED'
                            and e.actor_id == ctx.actor.entity_id and e.source_definition_id == ctx.source
                            and target.entity_id in e.target_ids
                            and int(e.payload.get('hp_damage', 0)) + int(e.payload.get('temporary_hp_absorbed', 0)) > 0
                            for e in ctx.engine.events)
    if dealt and pending[0] == getattr(target, "entity_id", None) and pending[1]:
        ctx.actor.turn_flags[pending[1]] = True
        note(ctx.engine, ctx.source, ctx.actor, f"{ctx.actor.display_name} uses {ctx.action.display_name}'s damage bonus. It is available again at the start of their next turn.")


@hook("after_miss")
def kind_bonus_missed(ctx: Any, target: Any) -> None:
    if hasattr(ctx, "damage_cache"):
        ctx.damage_cache.pop("_creature_kind_pending", None)
