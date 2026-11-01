"""Thousand-Fold Steel Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, Thousand-Fold Steel Body (Tempering Forms, the five features and their Normalized
Procedures). Owned rows: ``{"type": "path_passive", "kind": "steel", "role": "forms" | "quench" | "folded" | "reforgings" |
"beyond"}``; Body Forged in Three Forms also carries the integrated-weapon row ``{"kind": "integrated_weapon", "group": "melee",
"choose": 1}`` (the Tempered Weapon, combat/ext/integrated_weapons.py).

Tempering Forms     at the start of your turn (asked; kept from the last turn when unanswered, Edge first) one Form, two different
                    ones with Ten Thousand Reforgings, all three with Body Beyond the Hammer (no choice) — the condition
                    ``condition:typed.tempering_forms`` shows them.
  Edge              once per turn on an unarmed or melee weapon hit + PB Slashing or Force (2 x PB with Ten Thousand Reforgings);
                    unarmed strikes may deal Slashing (hook attack_damage_types).
  Spine             the first Bludgeoning, Piercing or Slashing packet each round is PB smaller (2 x PB) (hook damage_reduction);
                    Advantage on saves against Prone.
  Reed              once per turn after you hit with a melee attack or a melee attack misses you, an asked 5-foot move without
                    provoking (10 feet); Advantage to escape a grapple.
Quench the Impact   as hostile damage is about to land (asked; Reaction, 1 Stamina, once per round; hook damage_pending): pick a
                    Form to make active now (with two Forms, the one it replaces) and its Quench — Edge: your next melee attack
                    before the end of your next turn + 2d8 on a hit; Spine: 2d8 + CON off this packet; Reed: a 15-foot move after
                    the damage.
Folded Edge, Hidden Spine  (the ignore-Resistance half is feature_blocks.json's defense row) once per turn when you hit while Edge
                    is active, asked: target AC - 1 until the start of your next turn (never stacking), no Reactions, or + 2d8.
Body Beyond the Hammer  no Disarm from an ordinary effect; once per turn on a melee hit, asked: Perfect Edge (+ 4d8, AC - 1),
                    Perfect Spine (2 x PB + CON Temporary HP, no push, pull or Prone until your next turn) or Perfect Reed (a
                    20-foot move without provoking).
Every hook returns early for a creature without these rows.
Pre-fix saved Edge Quench records are normalized on the first resumed event, before turn-start clearing. Their integer
deadline is preserved; a newer retained record wins, so the two saved keys never grant two charges.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.thousand_fold_steel_body.feature."
FORMS = "condition:typed.tempering_forms"
ALL = ("edge", "spine", "reed")
STAMINA = "resource:core.stamina"
AC_SOURCE = PREFIX + "tempered_ac"


def _edge_charge(actor: Any) -> Any:
    """Retain pre-fix saved charges; a newer charge refreshes, never stacks."""
    legacy = actor.turn_flags.pop("_edge_quench", None)
    if legacy:
        actor.turn_flags.setdefault("_round_edge_quench_charge", legacy)
    return actor.turn_flags.get("_round_edge_quench_charge")


@hook("event")
def retain_legacy_edge_quench(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """First resumed event migrates owned charges before turn-start flags clear."""
    for actor in engine.state.actors.values():
        if "_edge_quench" in actor.turn_flags and "quench" in _roles(engine, actor):
            _edge_charge(actor)


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "steel"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def forms(actor: Any) -> list[str]:
    held = next((c for c in actor.conditions.values() if c.condition_id == FORMS), None) if actor is not None else None
    return list((held.data or {}).get("forms") or []) if held is not None else []


def _set_forms(engine: Any, actor: Any, chosen: list[str]) -> None:
    for iid, held in list(actor.conditions.items()):
        if held.condition_id == FORMS:
            engine._remove_condition(actor, FORMS, PREFIX + "body_forged_in_three_forms")
    names = [f.title() for f in chosen]
    engine._apply_condition(actor, FORMS, PREFIX + "body_forged_in_three_forms", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"forms": list(chosen), "label": "Tempering Forms: " + (", ".join(names) or "none")})


def _count(roles: set[str]) -> int:
    return 3 if "beyond" in roles else 2 if "reforgings" in roles else 1


def _pb(actor: Any) -> int:
    return int(actor.proficiency_bonus or 2)


def _con(engine: Any, actor: Any) -> int:
    return next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)


def _melee(ctx: Any, kind: str) -> bool:
    return kind == "unarmed" or (kind == "weapon" and not (ctx.typed or {}).get("range_ft"))


def _free_move(engine: Any, intent: Any, actor: Any, feet: int, choice_id: str, name: str, *, feature_id: str = "",
               paid_by: str = "") -> None:
    """Ask where to move as part of a Form that has already been paid for.

    ``paid_by`` names the cost the player already spent to earn this move, so the prompt shows that the
    move is included rather than charging a second time. It is display-only text carried through
    ask(prompt_context=...); nothing here spends anything.
    """
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    paths = routes(engine, actor, feet)
    if not paths:
        return
    cost = (f"No extra cost: this {feet}-foot move comes with the {paid_by} you have already spent."
            if paid_by else "")
    picked = ask(engine, intent, checkpoint_id(engine, "steel_move", actor.entity_id), actor, choice_id, sorted(paths), allow_decline=True,
                 default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name=name,
                 feature_id=feature_id, prompt_context=({"cost": cost} if cost else None),
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        step(engine, actor, paths[picked[0]], PREFIX + "tempering_forms")


# ------------------------------------------------------------------------------------------------------ Tempering Forms
@hook("turn_start_choice")
def choose_forms(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "forms" not in roles or not actor.active:
        return
    count = _count(roles)
    if count >= 3:
        _set_forms(engine, actor, list(ALL))  # "All three Forms are active simultaneously"
        return
    from .needle import ask, checkpoint_id

    previous = [f for f in forms(actor) if f in ALL][:count] or ["edge"]
    labels = {"edge": f"Edge: once per turn + {(2 if count == 2 else 1) * _pb(actor)} on an unarmed or melee hit; unarmed strikes may cut",
              "spine": f"Spine: the first Bludgeoning, Piercing or Slashing damage each round - {(2 if count == 2 else 1) * _pb(actor)}; Advantage against Prone",
              "reed": f"Reed: a {10 if count == 2 else 5}-foot step after your melee hit or a melee miss against you; Advantage to escape grapples"}
    from ..knowledge_policy import enabled
    if enabled(engine):
        labels['edge'] = f"Edge: once per turn +{(2 if count == 2 else 1) * _pb(actor)} damage (Slashing or Force) on your unarmed or melee weapon hit; your unarmed strikes may deal Slashing damage"
        labels['spine'] = f"Spine: reduce the first Bludgeoning, Piercing or Slashing damage you take each round by {(2 if count == 2 else 1) * _pb(actor)}; Advantage on saving throws against being knocked Prone"
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "tempering_forms", actor.entity_id), actor, "choice:needle.tempering_forms", list(ALL),
                 labels=labels, minimum=count, maximum=count, preferred=previous, default_count=count, target_id=actor.entity_id, name="Tempering Forms",
                 prompt=f"Tempering Forms: choose {'one Form' if count == 1 else 'two different Forms'} "
                        + (f"for {actor.display_name} until the start of your next turn. No action or resource cost."
                           if enabled(engine) else "until your next turn."),
                 feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.body_forged_in_three_forms")
    chosen = [f for f in ALL if f in (picked or [])][:count] or previous
    _set_forms(engine, actor, chosen)


@hook("attack_damage_types")
def edge_cuts(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    """Edge Form: "Unarmed strikes may deal Slashing"."""
    if (attack or {}).get("attack_kind") != "unarmed" or "edge" not in forms(ctx.actor):
        return None
    current = [str(k).upper() for k in (kinds or [])]
    return list(dict.fromkeys([*current, "SLASHING"])) if current else None


@hook("damage_reduction")
def spine_form(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    if "spine" not in forms(target) or str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING"):
        return None
    if target.turn_flags.get("_round_spine_form") == int(engine.state.round_number):
        return None  # "the first ... damage each round"
    source = engine.state.actors.get(str(source_actor_id or ""))
    if source is None or source.team_id == target.team_id:
        return None
    if applied:
        target.turn_flags["_round_spine_form"] = int(engine.state.round_number)
    return _pb(target) * (2 if "reforgings" in _roles(engine, target) else 1)


@hook("save")
def spine_against_prone(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None or "prone" not in {str(n).lower() for n in named or ()}:
        return None
    perfect = subject.turn_flags.get("_round_perfect_spine")
    if "spine" in forms(subject) or perfect:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("escape_mode")
def reed_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if "reed" in forms(escaper) else None


@hook("escape_save_mode")
def reed_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if "reed" in forms(escaper) else None


def _reed(engine: Any, intent: Any, actor: Any) -> None:
    if "reed" not in forms(actor) or not actor.active or actor.turn_flags.get("_round_reed_form") == _stamp(engine):
        return
    actor.turn_flags["_round_reed_form"] = _stamp(engine)
    _free_move(engine, intent, actor, 10 if "reforgings" in _roles(engine, actor) else 5, "choice:needle.reed_form_move", "Reed Form")


@hook("after_miss")
def reed_on_a_miss(ctx: Any, target: Any) -> None:
    if target is None or ctx.actor.team_id == target.team_id or (ctx.typed or {}).get("range_ft") or "reed" not in forms(target):
        return
    _reed(ctx.engine, ctx.intent or _intent(ctx.engine), target)  # "a melee attack misses you"


# ------------------------------------------------------------------------------------------------------ hit riders
@hook("after_hit")
def steel_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or target is None or target.team_id == actor.team_id or not _melee(ctx, kind):
        return
    from .. import typed_executor as te

    stamp = _stamp(engine)
    active = forms(actor)
    sub = ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={})
    if "edge" in active and target.active and actor.turn_flags.get("_round_edge_form") != stamp:
        actor.turn_flags["_round_edge_form"] = stamp
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "flat": _pb(actor) * (2 if "reforgings" in roles else 1),
                              "damage_types": ["slashing", "force"], "evidence": "Edge Form"}])
    charge = _edge_charge(actor)
    if charge and target.active:
        actor.turn_flags.pop("_round_edge_quench_charge", None)
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Edge Quench: + 2d8"}])
    if "folded" in roles and "edge" in active and target.active and actor.turn_flags.get("_round_folded_edge") != stamp:
        _folded_edge(ctx, sub, target)
    if "beyond" in roles and target.active and actor.turn_flags.get("_round_perfect") != stamp:
        _perfect(ctx, sub, target)
    _reed(engine, ctx.intent, actor)


@hook("attack_resolved")
def edge_quench_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """"Your next melee attack before the end of your next turn": a miss uses it up too."""
    charge = _edge_charge(ctx.actor)
    if charge and not hit and not (ctx.typed or {}).get("range_ft"):
        ctx.actor.turn_flags.pop("_round_edge_quench_charge", None)


@hook("turn_end")
def edge_quench_expires(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    charge = _edge_charge(actor)
    if charge and custom_turn_due(actor, int(charge.get("until") or 0), actor.turn_flags, "edge_quench", nominal=nominal):
        actor.turn_flags.pop("_round_edge_quench_charge", None)


def _lower_ac(engine: Any, owner: Any, target: Any) -> None:
    """AC - 1 until the start of your next turn; it refreshes, never stacks, across this Subpath's reductions."""
    from .effect_durations import token

    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == AC_SOURCE and modifier.target_field == "armor_class":
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", AC_SOURCE, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REFRESHED"})
    expires = "START_OF_SOURCE_NEXT_TURN" if engine.state.current_actor_id == owner.entity_id else token("start", owner.entity_id, int(owner.turns_started) + 1)
    engine._add_modifier(target, AC_SOURCE, "armor_class", "ADD", -1, "ALWAYS", expires_on=expires)


def _folded_edge(ctx: Any, sub: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    labels = {"ac": f"{target.display_name}'s AC - 1 until the start of your next turn", "reactions": "No Reactions until the start of its next turn",
              "damage": "+ 2d8 Slashing or Force"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "folded_edge", target.entity_id), actor, "choice:needle.folded_edge", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Folded Edge, Hidden Spine",
                 prompt=f"Folded Edge, Hidden Spine: your Edge Form hit {target.display_name}. Choose one.")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_folded_edge"] = _stamp(engine)
    if picked[0] == "ac":
        _lower_ac(engine, actor, target)
    elif picked[0] == "reactions":
        te.run_effects(sub, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])
    else:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Folded Edge: + 2d8"}])


def _perfect(ctx: Any, sub: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    pb = _pb(actor)
    labels = {"edge": "Perfect Edge: + 4d8 Slashing or Force and its AC - 1", "spine": f"Perfect Spine: {2 * pb + _con(engine, actor)} Temporary HP; no push, pull or Prone until your next turn",
              "reed": "Perfect Reed: move 20 feet without provoking"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "perfect", target.entity_id), actor, "choice:needle.body_beyond_the_hammer", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Body Beyond the Hammer",
                 prompt="Body Beyond the Hammer: choose a Perfect result for this hit.")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_perfect"] = _stamp(engine)
    if picked[0] == "edge":
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 4, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Perfect Edge: + 4d8"}])
        if target.active:
            _lower_ac(engine, actor, target)
    elif picked[0] == "spine":
        te.run_effects(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {}),
                       [{"type": "temp_hp", "applies_to": "self", "flat": 2 * pb + _con(engine, actor), "evidence": "Perfect Spine"}])
        actor.turn_flags["_round_perfect_spine"] = {"until": int(actor.turns_started) + 1}
    else:
        _free_move(engine, ctx.intent, actor, 20, "choice:needle.perfect_reed_move", "Perfect Reed")


@hook("forced_distance")
def perfect_spine_holds(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    """Perfect Spine: "cannot be pushed, pulled, or knocked Prone until your next turn"."""
    record = mover.turn_flags.get("_round_perfect_spine") if mover is not None else None
    if not record or source is None or source.entity_id == mover.entity_id:
        return None
    return distance_ft


@hook("condition_attempt")
def perfect_spine_prone(ctx: Any, subject: Any, effect: Any) -> bool | None:
    name = str((effect or {}).get("condition") or "").lower()
    if subject is None:
        return None
    if name == "prone" and subject.turn_flags.get("_round_perfect_spine") and ctx.actor is not subject:
        return False
    if name == "disarmed" and "beyond" in _roles(ctx.engine, subject) and not str((ctx.typed or {}).get("source") or "").startswith(("tianxia.", "TAL_")):
        return False  # "You cannot be Disarmed by an ordinary effect"
    return None


@hook("turn_start")
def perfect_spine_ends(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    record = actor.turn_flags.get("_round_perfect_spine")
    if record and custom_turn_due(actor, int(record.get("until") or 0), actor.turn_flags, "perfect_spine", nominal=nominal):
        actor.turn_flags.pop("_round_perfect_spine", None)


@hook("nominal_slot_boundary")
def nominal_steel(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "START_OF_TURN":
        perfect_spine_ends(engine, actor, nominal=True)
    else:
        edge_quench_expires(engine, actor, nominal=True)


# ------------------------------------------------------------------------------------------------------ Quench the Impact
@hook("damage_pending")
def quench_the_impact(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    roles = _roles(engine, target)
    source = engine.state.actors.get(str(source_actor_id or ""))
    if "quench" not in roles or pending <= 0 or source is None or source.team_id == target.team_id or not target.active:
        return None
    if not target.reaction_available or int(target.resources.get(STAMINA, 0) or 0) < 1 or target.turn_flags.get("_round_quench") == int(engine.state.round_number):
        return None
    from ..gate2_runtime_models import DiceSpec
    from .needle import ask, checkpoint_id

    intent = _intent(engine)
    labels = {"edge": "Edge Quench: your next melee attack before the end of your next turn + 2d8",
              "spine": "Spine Quench: 2d8 + Constitution modifier off this damage", "reed": "Reed Quench: move 15 feet after the damage"}
    picked = ask(engine, intent, checkpoint_id(engine, "quench", target.entity_id), target, "choice:needle.quench_the_impact", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Quench the Impact",
                 prompt=f"Quench the Impact: {pending} damage from {source.display_name} is about to land. Reaction, 1 Stamina: change Form?",
                 feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact")
    if not picked or picked[0] not in labels:
        return None
    choice = picked[0]
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, target, PREFIX + "quench_the_impact", independent=True):
        target.reaction_available = False
        target.turn_flags["_round_quench"] = int(engine.state.round_number)
        engine._spend_resource(target, STAMINA, 1, PREFIX + "quench_the_impact")
        current = forms(target)
        if choice not in current:
            count = _count(roles)
            if len(current) >= count and count > 1:
                options = {f: f"Replace {f.title()} Form" for f in current}
                drop = ask(engine, intent, checkpoint_id(engine, "quench_replace", target.entity_id), target, "choice:needle.quench_replace", list(options),
                           labels=options, target_id=target.entity_id, name="Quench the Impact", prompt=f"Quench the Impact: which Form does {choice.title()} replace?")
                gone = drop[0] if drop and drop[0] in options else current[0]
                current = [f for f in current if f != gone] + [choice]
            else:
                current = (current + [choice])[-count:] if count > 1 else [choice]
            _set_forms(engine, target, current)
        reduction = 0
        if choice == "spine":
            roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=_con(engine, target)), actor_id=target.entity_id, reason=f"REDUCTION:{PREFIX}quench_the_impact")
            engine._record_roll(roll)
            reduction = max(0, int(roll.total))
        elif choice == "edge":
            target.turn_flags["_round_edge_quench_charge"] = {"until": int(target.turns_started) + 1}
        else:
            from ..paid_relocation import capture, retain
            retain(engine, ("steel_quench_reed", target.entity_id), capture(engine))
            target.turn_flags["_quench_reed"] = True
        engine._append_event("REACTION_RESOLVED", PREFIX + "quench_the_impact", actor_id=target.entity_id, target_ids=(source.entity_id,),
                             payload={"checkpoint": "DAMAGE_APPLICATION", "quench": choice, "reduction": reduction})
        return max(0, pending - reduction) if reduction else None


@hook("event")
def reed_quench_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Reed Quench: "After the triggering damage resolves, move up to 15 feet without provoking" (even if it became 0)."""
    if event_type != "DAMAGE_COMMITTED":
        return
    actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is None or not actor.turn_flags.pop("_quench_reed", None) or not actor.active:
        return
    from ..paid_relocation import causal_scope, take
    with causal_scope(engine, take(engine, ("steel_quench_reed", actor.entity_id))):
        _free_move(engine, _intent(engine), actor, 15, "choice:needle.reed_quench_move", "Reed Quench",
                   feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact",
                   paid_by="Quench the Impact reaction and its 1 Stamina")
