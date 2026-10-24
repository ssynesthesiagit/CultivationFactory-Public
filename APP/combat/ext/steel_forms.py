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
from dataclasses import replace

from . import effect, hook, note
from .body_modes_scene_resources import effective_body_cl

PREFIX = "tianxia.subpath.body.thousand_fold_steel_body.feature."
FORMS = "condition:typed.tempering_forms"
ALL = ("edge", "spine", "reed")
STAMINA = "resource:core.stamina"
AC_SOURCE = PREFIX + "tempered_ac"
PARENT = PREFIX.removesuffix('.feature.')
LEVELS = {'forms': ('body_forged_in_three_forms', 3), 'quench': ('quench_the_impact', 6),
          'folded': ('folded_edge_hidden_spine', 10), 'reforgings': ('ten_thousand_reforgings', 14),
          'beyond': ('body_beyond_the_hammer', 18)}


@hook('body_mode_profiles')
def body_profile(bundle):
    from .body_modes_scene_resources import feature_owned
    if not feature_owned(bundle, PREFIX+'body_forged_in_three_forms'):
        return None
    return [{'source': PARENT, 'name': 'Thousand-Fold Steel Body',
             'feature_levels': {PREFIX+name: level for name, level in LEVELS.values()}}]


def _edge_charge(actor: Any) -> Any:
    """Retain pre-fix saved charges; a newer charge refreshes, never stacks."""
    legacy = actor.turn_flags.pop("_edge_quench", None)
    if legacy:
        actor.turn_flags.setdefault("_round_edge_quench_charge", legacy)
    return actor.turn_flags.get("_round_edge_quench_charge")


@hook("event")
def retain_legacy_edge_quench(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """First resumed event migrates owned charges before turn-start flags clear."""
    if event_type!='INTENT_ACCEPTED':return
    for actor in engine.state.actors.values():
        if 'forms' in _roles(engine,actor):
            legacy=f'{engine.state.round_number}:{engine.state.current_actor_id}'
            for key in ('_round_edge_form','_round_reed_form','_round_folded_edge','_round_perfect'):
                if actor.turn_flags.get(key)==legacy:actor.turn_flags[key]=_stamp(engine)
        if "_edge_quench" in actor.turn_flags and owns_quench(engine,actor):
            _edge_charge(actor)


def owns_quench(engine,actor):
    from .body_modes_scene_resources import bundle_of,feature_owned
    return feature_owned(bundle_of(engine,actor),PREFIX+'quench_the_impact')


def _roles(engine: Any, actor: Any) -> set[str]:
    from .body_modes_scene_resources import available
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "steel"
            and row.get('role') in LEVELS
            and available(engine, actor, PREFIX+LEVELS[row['role']][0], LEVELS[row['role']][1], requires_conscious=False)}


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def forms(actor: Any) -> list[str]:
    held = next((c for c in actor.conditions.values() if c.condition_id == FORMS
                 and c.source_definition_id == PREFIX+'body_forged_in_three_forms' and c.source_actor_id == actor.entity_id), None) if actor is not None else None
    return list((held.data or {}).get("forms") or []) if held is not None else []


def active_forms(engine, actor):
    """Acquired Forms above current effective CL remain saved but dormant."""
    roles = _roles(engine, actor)
    if 'forms' not in roles:
        return []
    if 'beyond' in roles:
        return list(ALL)
    return [f for f in forms(actor) if f in ALL][:_count(roles)]


def _set_forms(engine: Any, actor: Any, chosen: list[str], *, retain_dormant: bool = False) -> None:
    from .body_modes_scene_resources import effective_body_cl
    owned=[c for c in actor.conditions.values() if c.condition_id==FORMS
           and c.source_definition_id==PREFIX+'body_forged_in_three_forms' and c.source_actor_id==actor.entity_id]
    old=next(iter(owned),None);previous=forms(actor);saved=list(chosen)
    count=_count(_roles(engine,actor));current_cl=effective_body_cl(engine,actor)
    if retain_dormant and len(previous)>count:
        reserve=[f for f in [*previous[count:],*previous[:count]] if f not in saved]
        saved+=reserve[:len(previous)-count]
    old_cl=int(old.data.get('source_cl',current_cl)) if old else current_cl
    source_cl=old_cl if old is not None and previous==saved else current_cl
    source_cls={f:int((old.data.get('form_source_cls') or {}).get(f,old_cl)) if old else current_cl for f in saved}
    if previous[:count]!=chosen:
        for f in chosen:source_cls[f]=current_cl
    for held in owned:
        engine._remove_condition_instance(actor,held.instance_id,PREFIX+'body_forged_in_three_forms',expected=held)
    names = [f.title() for f in saved[:count]]
    label='Tempering Forms: '+(', '.join(names) or 'none')
    if len(saved)>count:label+='; dormant: '+', '.join(f.title() for f in saved[count:])
    data={"forms":saved,"source_cl":source_cl,"form_source_cls":source_cls,"label":label}
    if retain_dormant and len(saved)>count:data['suppressed_choice_cl']=current_cl
    engine._apply_condition(actor, FORMS, PREFIX + "body_forged_in_three_forms", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data=data)


def _count(roles: set[str]) -> int:
    return 3 if "beyond" in roles else 2 if "reforgings" in roles else 1


def _pb(actor: Any, engine: Any = None) -> int:
    if engine is not None:
        from .body_modes_scene_resources import effective_body_pb
        return effective_body_pb(engine,actor)
    return int(actor.proficiency_bonus or 2)


def _con(engine: Any, actor: Any) -> int:
    return next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id
                 and (((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("con_mod") is not None), 0)


def _melee(ctx: Any, kind: str) -> bool:
    from ..attack_delivery import is_ranged
    typed=ctx.typed or {}
    profile=next((e.get('attack_kind') for e in typed.get('effects',()) if e.get('type')=='attack'),kind)
    return not is_ranged(profile,typed.get('range_ft'),typed.get('weapon') or typed.get('object_weapon'))


def _free_move(engine: Any, intent: Any, actor: Any, feet: int, choice_id: str, name: str, *, feature_id: str = "",
               paid_by: str = "", use_flag: str = "") -> None:
    """Ask where to move as part of a Form that has already been paid for.

    ``paid_by`` names the cost the player already spent to earn this move, so the prompt shows that the
    move is included rather than charging a second time. It is display-only text carried through
    ask(prompt_context=...); nothing here spends anything.
    """
    from .needle import ask, checkpoint_id
    from .rider_movement import routes, step

    from contextlib import nullcontext
    scope = perfect_reed_scope(engine, actor) if choice_id == 'choice:needle.perfect_reed_move' else nullcontext()
    with scope:
        paths = routes(engine, actor, feet, native=True, source=feature_id or PREFIX+'body_forged_in_three_forms')
    if not paths:
        return
    cost = (f"No extra cost: this {feet}-foot move comes with the {paid_by} you have already spent."
            if paid_by else "No Action or Stamina cost.")
    picked = ask(engine, intent, checkpoint_id(engine, "steel_move", actor.entity_id), actor, choice_id, sorted(paths), allow_decline=True,
                 default="decline", labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name=name,
                 feature_id=feature_id, prompt_context=({"cost": cost} if cost else None),
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        if use_flag:actor.turn_flags[use_flag]=_stamp(engine)
        with (perfect_reed_scope(engine, actor) if choice_id == 'choice:needle.perfect_reed_move' else nullcontext()):
            step(engine, actor, paths[picked[0]], feature_id or PREFIX + "body_forged_in_three_forms",
                 native=True, feet=feet, intent=intent)


# ------------------------------------------------------------------------------------------------------ Tempering Forms
@hook("turn_start_choice", priority=-200)
def choose_forms(engine: Any, actor: Any) -> None:
    roles = _roles(engine, actor)
    if "forms" not in roles or not actor.active:
        return
    count = _count(roles)
    if count >= 3:
        _set_forms(engine, actor, list(ALL))  # "All three Forms are active simultaneously"
        return
    from .needle import ask, checkpoint_id

    previous = [f for f in forms(actor) if f in ALL][:count]
    previous += [f for f in ALL if f not in previous][:count-len(previous)]
    labels = {"edge": f"Edge: once per turn + {(2 if count == 2 else 1) * _pb(actor, engine)} on an unarmed or melee hit; unarmed strikes may cut",
              "spine": f"Spine: the first Bludgeoning, Piercing or Slashing damage each round - {(2 if count == 2 else 1) * _pb(actor, engine)}; Advantage against Prone",
              "reed": f"Reed: a {10 if count == 2 else 5}-foot step after your melee hit or a melee miss against you; Advantage to escape grapples"}
    from ..knowledge_policy import enabled
    if enabled(engine):
        labels['edge'] = f"Edge: once per turn +{(2 if count == 2 else 1) * _pb(actor, engine)} damage (Slashing or Force) on your unarmed or melee weapon hit; your unarmed strikes may deal Slashing damage"
        labels['spine'] = f"Spine: reduce the first Bludgeoning, Piercing or Slashing damage you take each round by {(2 if count == 2 else 1) * _pb(actor, engine)}; Advantage on saving throws against being knocked Prone"
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "tempering_forms", actor.entity_id), actor, "choice:needle.tempering_forms", list(ALL),
                 labels=labels, minimum=count, maximum=count, preferred=previous, default_count=count, allow_decline=True,
                 target_id=actor.entity_id, name="Tempering Forms",
                 prompt=f"Tempering Forms: choose {'one Form' if count == 1 else 'two different Forms'} "
                        + (f"for {actor.display_name} until the start of your next turn. No action or resource cost."
                           if enabled(engine) else "until your next turn."),
                 feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.body_forged_in_three_forms")
    chosen = [f for f in ALL if f in (picked or [])][:count] or previous
    _set_forms(engine, actor, chosen)
    if _intent(engine) is None:
        # Bootstrap can establish the legal fallback before an intent exists,
        # but the first real intent must still offer its owner the free choice.
        held=next(c for c in actor.conditions.values() if c.condition_id==FORMS
                  and c.source_definition_id==PREFIX+'body_forged_in_three_forms' and c.source_actor_id==actor.entity_id)
        engine._update_condition_data(actor,held,{**held.data,'initial_choice_turn':_stamp(engine)},PREFIX+'body_forged_in_three_forms')


@hook('event',priority=-500)
def deferred_initial_forms(engine,event_type,kwargs):
    if event_type!='INTENT_ACCEPTED':return
    actor=engine.state.actors.get(engine.state.current_actor_id)
    if actor is None or 'forms' not in _roles(engine,actor):return
    held=next((c for c in actor.conditions.values() if c.condition_id==FORMS
        and c.source_definition_id==PREFIX+'body_forged_in_three_forms' and c.source_actor_id==actor.entity_id),None)
    if held is not None and held.data.get('initial_choice_turn')==_stamp(engine):
        if len(forms(actor))>_count(_roles(engine,actor)):
            # The suppression selection below owns this same-turn decision.
            # Removing the bootstrap marker must not delete dormant Forms.
            data=dict(held.data);data.pop('initial_choice_turn',None)
            engine._update_condition_data(actor,held,data,TEMPER)
        else:choose_forms(engine,actor)


@hook("attack_damage_types")
def edge_cuts(ctx: Any, attack: Any, kinds: Any) -> list[str] | None:
    """Edge Form: "Unarmed strikes may deal Slashing"."""
    if (attack or {}).get("attack_kind") != "unarmed" or "edge" not in active_forms(ctx.engine, ctx.actor):
        return None
    current = [str(k).upper() for k in (kinds or [])]
    return list(dict.fromkeys([*current, "SLASHING"])) if current else None


@hook("damage_reduction")
def spine_form(engine: Any, target: Any, damage_type: str, typed: Any, source_actor_id: Any, applied: bool = False) -> int | None:
    if "spine" not in active_forms(engine, target) or str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING"):
        return None
    if target.turn_flags.get("_round_spine_form") == int(engine.state.round_number):
        return None  # "the first ... damage each round"
    if own_reduction_excluded(engine):return None
    if applied:
        target.turn_flags["_round_spine_form"] = int(engine.state.round_number)
    return _pb(target, engine) * (2 if "reforgings" in _roles(engine, target) else 1)


@hook("save")
def spine_against_prone(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if ctx is None or subject is None or "prone" not in {str(n).lower() for n in named or ()}:
        return None
    perfect = subject.turn_flags.get("_round_perfect_spine") and "beyond" in _roles(ctx.engine, subject)
    if "spine" in active_forms(ctx.engine, subject) or perfect:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("escape_mode")
def reed_escape(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if "reed" in active_forms(engine, escaper) else None


@hook("escape_save_mode")
def reed_escape_save(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "ADVANTAGE" if "reed" in active_forms(engine, escaper) else None


def _reed(engine: Any, intent: Any, actor: Any) -> None:
    if "reed" not in active_forms(engine, actor) or not actor.active or actor.turn_flags.get("_round_reed_form") == _stamp(engine):
        return
    _free_move(engine, intent, actor, 10 if "reforgings" in _roles(engine, actor) else 5, "choice:needle.reed_form_move", "Reed Form", use_flag='_round_reed_form')


@hook("after_miss")
def reed_on_a_miss(ctx: Any, target: Any) -> None:
    if target is None or not _melee(ctx, str((ctx.typed or {}).get("attack_kind") or "weapon")) or "reed" not in active_forms(ctx.engine, target):
        return
    _reed(ctx.engine, ctx.intent or _intent(ctx.engine), target)  # "a melee attack misses you"


# ------------------------------------------------------------------------------------------------------ hit riders
@hook("after_hit")
def steel_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or target is None or not actor.active or actor.current_hp<=0 or not _melee(ctx, kind):
        return
    from .. import typed_executor as te

    stamp = _stamp(engine)
    active = active_forms(engine, actor)
    sub = ctx.hit_bonus_context(target, action=ctx.action, typed={**ctx.typed, "steel_damage_choice": 1})
    if ("edge" in active and target.active and actor.turn_flags.get("_round_edge_form") != stamp
            and edge_form_declared(ctx,target.entity_id)):
        actor.turn_flags["_round_edge_form"] = stamp
        te.run_effects(sub.hit_bonus_context(target,source=PREFIX+'body_forged_in_three_forms'), [{"type": "extra_damage", "applies_to": "target", "flat": _pb(actor, engine) * (2 if "reforgings" in roles else 1),
                              "damage_types": ["slashing", "force"], "evidence": "Edge Form"}])
    charge = _edge_charge(actor) if 'quench' in roles else None
    if charge and target.active:
        actor.turn_flags.pop("_round_edge_quench_charge", None)
        te.run_effects(sub.hit_bonus_context(target,source=PREFIX+'quench_the_impact'), [{"type": "extra_damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Edge Quench: + 2d8"}])
    if "folded" in roles and "edge" in active and actor.turn_flags.get("_round_folded_edge") != stamp:
        _folded_edge(ctx, sub, target)
    if "beyond" in roles and actor.turn_flags.get("_round_perfect") != stamp:
        _perfect(ctx, sub, target)
    _reed(engine, ctx.intent, actor)


@hook("attack_resolved")
def edge_quench_spent(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    """"Your next melee attack before the end of your next turn": a miss uses it up too."""
    charge = _edge_charge(ctx.actor) if 'quench' in _roles(ctx.engine,ctx.actor) else None
    if charge and _melee(ctx, str((attack_effect or {}).get("attack_kind") or "weapon")):
        ctx.actor.turn_flags.pop("_round_edge_quench_charge", None)


@hook("turn_end")
def edge_quench_expires(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    from .effect_durations import custom_turn_due
    if not owns_quench(engine,actor):return
    charge = _edge_charge(actor)
    if charge and custom_turn_due(actor, int(charge.get("until") or 0), actor.turn_flags, "edge_quench", nominal=nominal):
        actor.turn_flags.pop("_round_edge_quench_charge", None)


def _lower_ac(engine: Any, owner: Any, target: Any, *, feature: str = PREFIX+'folded_edge_hidden_spine') -> None:
    """AC - 1 until the start of your next turn; it refreshes, never stacks, across this Subpath's reductions."""
    from .effect_durations import token
    from .body_modes_scene_resources import effective_body_cl

    for mid, modifier in list(target.modifiers.items()):
        if modifier.source_definition_id == AC_SOURCE and modifier.target_field == "armor_class":
            del target.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", AC_SOURCE, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                 payload={"modifier_id": mid, "reason": "REFRESHED"})
    expires = "START_OF_SOURCE_NEXT_TURN" if engine.state.current_actor_id == owner.entity_id else token("start", owner.entity_id, int(owner.turns_started) + 1)
    engine._add_modifier(target, AC_SOURCE, "armor_class", "ADD", -1, "ALWAYS", expires_on=expires, source_actor_id=owner.entity_id,
        data={"feature":feature,"source_cl":effective_body_cl(engine,owner)})


def _folded_edge(ctx: Any, sub: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    sub=sub.hit_bonus_context(target,source=PREFIX+'folded_edge_hidden_spine')
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
    sub=sub.hit_bonus_context(target,source=PREFIX+'body_beyond_the_hammer')
    pb = _pb(actor, engine)
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
        _lower_ac(engine, actor, target, feature=PREFIX+'body_beyond_the_hammer')
    elif picked[0] == "spine":
        engine._grant_temp_hp(actor, 2 * pb + _con(engine, actor), PREFIX+'body_beyond_the_hammer', actor.entity_id)
        actor.turn_flags["_round_perfect_spine"] = {"until": int(actor.turns_started) + 1,"source_cl":effective_body_cl(engine,actor)}
    else:
        _free_move(engine, ctx.intent, actor, 20, "choice:needle.perfect_reed_move", "Perfect Reed",feature_id=PREFIX+'body_beyond_the_hammer')


@hook("forced_distance")
def perfect_spine_holds(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    """Perfect Spine: "cannot be pushed, pulled, or knocked Prone until your next turn"."""
    record = mover.turn_flags.get("_round_perfect_spine") if mover is not None else None
    if not record or 'beyond' not in _roles(engine, mover):
        return None
    return distance_ft


@hook("condition_attempt")
def perfect_spine_prone(ctx: Any, subject: Any, effect: Any) -> bool | None:
    name = str((effect or {}).get("condition") or "").lower()
    if subject is None:
        return None
    if name == "disarmed" and ("beyond" in _roles(ctx.engine, subject) or tempered_core(ctx.engine,subject,'heavenly_fist',17)):
        authority=(effect or {}).get('source_authority') or (ctx.typed or {}).get('source_authority')
        if authority is None:
            from ..observer_information import source_profile
            authority=source_profile(ctx.engine,str(ctx.typed.get('source') or ctx.source),{})
        if isinstance(authority,dict) and authority.get('authority')=='ordinary':
            from .body_modes_scene_resources import effective_body_cl
            if (not authority.get('explicit_source_cl') or int(authority.get('source_cl',0))<effective_body_cl(ctx.engine,subject)):
                weapon=(effect or {}).get('recipient_weapon')
                if weapon and weapon==tempered_weapon(ctx.engine,subject):return False
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
        object_ac_expires(engine,actor,nominal=True)
    else:
        edge_quench_expires(engine, actor, nominal=True)


# ------------------------------------------------------------------------------------------------------ Quench the Impact
@hook("damage_pending")
def quench_the_impact(engine: Any, target: Any, pending: int, source_definition_id: str, source_actor_id: str) -> int | None:
    roles = _roles(engine, target)
    source = engine.state.actors.get(str(source_actor_id or ""))
    if own_reduction_excluded(engine):return None
    from ..pending_damage import current as pending_packet
    packet=pending_packet(engine)
    from .body_modes_scene_resources import qualifying_hostile_damage
    if "quench" not in roles or not qualifying_hostile_damage(engine,target,packet) or not target.active:
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
                 prompt=f"Quench the Impact: {pending} damage from {source.display_name if source is not None else "an active environmental hazard"} is about to land. Reaction, 1 Stamina: change Form?",
                 feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact")
    if not picked or picked[0] not in labels:
        return None
    choice = picked[0]
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, target, PREFIX + "quench_the_impact", independent=True):
        target.reaction_available = False
        target.turn_flags["_round_quench"] = int(engine.state.round_number)
        engine._spend_resource(target, STAMINA, 1, PREFIX + "quench_the_impact")
        from ..activation_payments import reaction_completed
        if not reaction_completed(engine,target,PREFIX+'quench_the_impact'):return None
        roles=_roles(engine,target)
        if 'quench' not in roles:return None
        count = _count(roles)
        current = active_forms(engine, target)
        if count == 3:
            selected = list(ALL)
        elif count == 1:
            selected = [choice]
        else:
            # Form replacement and Quench benefit are independent printed choices.
            pairs = {'edge_spine': ['edge', 'spine'], 'edge_reed': ['edge', 'reed'],
                     'spine_reed': ['spine', 'reed']}
            keep = next((key for key, pair in pairs.items() if set(pair) == set(current)), 'edge_spine')
            picked_pair = ask(engine, intent, checkpoint_id(engine, 'quench_forms', target.entity_id), target,
                'choice:needle.quench_forms', list(pairs), labels={k: 'Maintain '+', '.join(f.title() for f in pair)
                    for k, pair in pairs.items()}, preferred=[keep], default=keep, target_id=target.entity_id,
                name='Quench the Impact', feature_id=PREFIX+'quench_the_impact',
                prompt='Quench the Impact: keep your two Forms or replace one or both. Only the selected Quench benefit applies. No additional cost.')
            selected = pairs[picked_pair[0] if picked_pair and picked_pair[0] in pairs else keep]
        _set_forms(engine, target, selected, retain_dormant=True)
        reduction = 0
        if choice == "spine":
            roll = engine.roller.roll(DiceSpec(count=2, sides=8, modifier=_con(engine, target)), actor_id=target.entity_id, reason=f"REDUCTION:{PREFIX}quench_the_impact")
            engine._record_roll(roll)
            reduction += max(0, int(roll.total))
        elif choice == "edge":
            target.turn_flags['_round_quench_edge_pending']={'packet':packet.event_sequence,'until':int(target.turns_started)+1,
                'source_cl':effective_body_cl(engine,target)}
        else:
            from ..paid_relocation import capture, retain
            retain(engine, ("steel_quench_reed", target.entity_id), capture(engine))
            target.turn_flags["_round_quench_reed_pending"] = packet.event_sequence
        engine._append_event("REACTION_RESOLVED", PREFIX + "quench_the_impact", actor_id=target.entity_id, target_ids=((source.entity_id,) if source is not None else ()),
                             payload={"checkpoint": "DAMAGE_APPLICATION", "quench": choice, "reduction": reduction})
        return max(0, pending - reduction) if reduction else None


@hook("event")
def reed_quench_move(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Reed Quench: "After the triggering damage resolves, move up to 15 feet without provoking" (even if it became 0)."""
    if event_type != "DAMAGE_COMMITTED":
        return
    actor = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if actor is None:return
    from ..pending_damage import current
    packet=current(engine)
    if packet is None:return
    edge=actor.turn_flags.get('_round_quench_edge_pending')
    if edge and edge['packet']==packet.event_sequence:
        actor.turn_flags.pop('_round_quench_edge_pending',None)
        actor.turn_flags['_round_edge_quench_charge']={k:v for k,v in edge.items() if k!='packet'}
    if actor.turn_flags.get('_round_quench_reed_pending')!=packet.event_sequence:return
    actor.turn_flags.pop('_round_quench_reed_pending',None)
    if not actor.active or actor.current_hp<=0 or 'quench' not in _roles(engine,actor):return
    from ..paid_relocation import causal_scope, take
    with causal_scope(engine, take(engine, ("steel_quench_reed", actor.entity_id))):
        _free_move(engine, _intent(engine), actor, 15, "choice:needle.reed_quench_move", "Reed Quench",
                   feature_id="tianxia.subpath.body.thousand_fold_steel_body.feature.quench_the_impact",
                   paid_by="Quench the Impact reaction and its 1 Stamina")


from contextlib import contextmanager


@contextmanager
def perfect_reed_scope(engine, actor):
    """Transient source-owned passage permission, never a lasting creature flag."""
    previous = engine.__dict__.get('_steel_perfect_reed_actor')
    engine.__dict__['_steel_perfect_reed_actor'] = actor.entity_id
    try:
        yield
    finally:
        if previous is None:
            engine.__dict__.pop('_steel_perfect_reed_actor', None)
        else:
            engine.__dict__['_steel_perfect_reed_actor'] = previous


@hook('pass_through')
def perfect_reed_passage(engine, mover, occupant):
    from ..granted_movement import query_source
    context=query_source(engine,mover.entity_id)
    if context is None:context=engine.movement_scope(mover.entity_id)
    if (engine.__dict__.get('_steel_perfect_reed_actor') == mover.entity_id
            and context is not None and context.get('source_id')==PREFIX+'body_beyond_the_hammer'
            and 'beyond' in _roles(engine, mover) and occupant.team_id != mover.team_id):
        return 'difficult'


TEMPERED = 'condition:typed.tempered_weapon'
TEMPER = PREFIX+'body_forged_in_three_forms'


def tempered_weapon(engine, actor):
    """Current owned physical weapon, only while possessed and wielded."""
    if 'forms' not in _roles(engine, actor):return ''
    held = next((c for c in actor.conditions.values() if c.condition_id == TEMPERED
                 and c.source_definition_id == TEMPER and c.source_actor_id == actor.entity_id), None)
    if held is None:return ''
    from ..weapon_delivery import ready_weapons
    weapon = str(held.data.get('weapon') or '')
    # Readiness is distinct from the second hand needed to swing a Two-Handed
    # weapon. Native attack eligibility still checks that separate capacity.
    return weapon if weapon in ready_weapons(engine,actor) else ''


@hook('candidate_allowed')
def selected_integration_candidate(engine, actor, candidate, action):
    if action is None:return
    typed = action.parameters.get('typed') or {}
    if TEMPER not in typed.get('integration_sources', ()):return
    from .weapon_hits import physical_weapon_id
    return tempered_weapon(engine, actor) == physical_weapon_id(action.source_definition_id, action.parameters)


@hook('attack_allowed')
def selected_integration_attack(ctx, target, effect):
    if TEMPER not in ctx.typed.get('integration_sources', ()):return
    from .weapon_hits import weapon_identity
    return tempered_weapon(ctx.engine, ctx.actor) == weapon_identity(ctx)


def journey_weapons(session, aid):
    from .integrated_weapons import in_group
    from .weapon_hits import physical_weapon_id
    import json
    snapshot=session.state['actors'][aid].get('encounter_snapshot') or {}
    disabled={json.loads(row).get('data',{}).get('disables_action') for row in snapshot.get('conditions',{}).values()}
    return {a['source_definition_id']: a for a in session.state['actors'][aid]['bundle'].get('action_catalog', ())
            if a['source_definition_id'] not in disabled
            if in_group((a.get('parameters') or {}).get('typed') or {}, 'melee')
            and physical_weapon_id(a['source_definition_id'],a.get('parameters')) == a['source_definition_id']}


def journey_forms_access(session, aid):
    from .body_modes_scene_resources import feature_owned, journey_body_cl
    return feature_owned(session.state['actors'][aid]['bundle'], TEMPER) and journey_body_cl(session,aid)>=3


@hook('journey_options')
def temper_options(session, aid):
    if not journey_forms_access(session, aid) or session.state['phase'] != 'travel':return
    return [{'id':'steel:temper:'+key,'kind':'activity_start','auto_select':0,
             'payload':{'source':TEMPER,'parameters':{'weapon':key}},
             'label':'Temper '+a['display_name'].removesuffix(' attack')+': 10 minutes of work; Constitution for attack and damage while wielded. No Stamina cost.'}
            for key,a in journey_weapons(session, aid).items()]


@hook('activity_spec')
def temper_activity(session, aid, source, parameters):
    if source != TEMPER:return
    from ..journey import require
    require(journey_forms_access(session,aid) and set(parameters)=={'weapon'}
            and parameters['weapon'] in journey_weapons(session,aid), 'Choose one acquired, proficient melee weapon to temper.')
    return {'seconds':600,'label':'tempering your weapon against your body','required_tools':['smithing'],
            'tool_task':{'operation':'maintain','owner':aid,'item':parameters['weapon'],'context':'downtime'}}


@hook('activity_validate')
def temper_validate(session, aid, activity):
    if activity['source']==TEMPER:
        spec=temper_activity(session,aid,TEMPER,activity['parameters'])
        from .journey_activities import available_tool_objects
        from ..journey import require
        require(set(spec['required_tools'])<=set(available_tool_objects(session,aid,spec['tool_task'])), 'Your tempering tools are no longer available.')


@hook('activity_finished')
def tempered_finished(session, aid, activity):
    if activity['source']!=TEMPER:return
    temper_validate(session, aid, activity)
    state=session.state['actors'][aid].setdefault('source_states',{}).setdefault(PARENT,{})
    from .body_modes_scene_resources import journey_body_cl
    state.update(tempered_weapon=activity['parameters']['weapon'],tempered_source_cl=journey_body_cl(session,aid))
    session.emit('WEAPON_TEMPERED',aid,source=TEMPER,weapon=activity['parameters']['weapon'],worked_seconds=activity['worked_seconds'])


@hook('journey_combat_bundle')
def seal_tempered_weapon(bundle, session, aid):
    weapon=session.state['actors'][aid].get('source_states',{}).get(PARENT,{}).get('tempered_weapon')
    if weapon and journey_forms_access(session,aid):return {**bundle,'steel_tempered_weapon':weapon,
        'steel_tempered_source_cl':session.state['actors'][aid]['source_states'][PARENT].get('tempered_source_cl',bundle.get('cl',1))}


@hook('match_initialize')
def restore_tempered_weapon(engine):
    from .body_modes_scene_resources import bundle_of
    for actor in engine.state.actors.values():
        weapon=bundle_of(engine,actor).get('steel_tempered_weapon')
        if weapon and 'forms' in _roles(engine,actor):
            for held in list(actor.conditions.values()):
                if held.condition_id==TEMPERED and held.source_definition_id==TEMPER and held.source_actor_id==actor.entity_id:
                    engine._remove_condition_instance(actor,held.instance_id,TEMPER,expected=held)
            engine._apply_condition(actor,TEMPERED,TEMPER,actor.entity_id,expires_on='UNTIL_REMOVED',
                                    data={'weapon':weapon,'source_cl':int(bundle_of(engine,actor).get('steel_tempered_source_cl',1)),'label':'Tempered Weapon: Constitution attack and damage while wielded'})


@hook('object_attack_packet')
def folded_object_hit(ctx, obj, kind, packets):
    """One native object hit, after ordinary attack modifiers, before defenses."""
    from .needle import ask, checkpoint_id
    roles=_roles(ctx.engine,ctx.actor)
    if not roles or not _melee(ctx,kind):return
    extras=[];multiplier=1;stamp=_stamp(ctx.engine)
    if ('edge' in active_forms(ctx.engine,ctx.actor) and ctx.actor.turn_flags.get('_round_edge_form')!=stamp
            and edge_form_declared(ctx,obj.object_id)):
        ctx.actor.turn_flags['_round_edge_form']=stamp
        extras.append(object_bonus(ctx, obj, flat=_pb(ctx.actor,ctx.engine)*(2 if 'reforgings' in roles else 1), name='Edge Form'))
    eligible=(not obj.destroyed and not (obj.component or {}).get('world_scale') and
              (obj.unattended or any((obj.component or {}).get(key) for key in
                                    ('temporary_barrier','vehicle','structure','formation_anchor'))))
    if ('folded' in roles and 'edge' in active_forms(ctx.engine,ctx.actor)
            and ctx.actor.turn_flags.get('_round_folded_edge')!=stamp):
        labels={'ac':'Reduce its AC by 1 until the start of your next turn','damage':'Add 2d8 Slashing or Force to this hit'}
        if eligible:labels['double']='Double this hit’s final damage once'
        picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'folded_object',obj.object_id),ctx.actor,
            'choice:needle.folded_edge',list(labels),labels=labels,allow_decline=True,default='decline',
            target_id=obj.object_id,name='Folded Edge, Hidden Spine',feature_id=PREFIX+'folded_edge_hidden_spine',
            prompt='Folded Edge, Hidden Spine: choose one result for this object hit. No action or Stamina cost.')
        if picked and picked[0] in labels:
            ctx.actor.turn_flags['_round_folded_edge']=stamp
            if picked[0]=='double':multiplier=2
            elif picked[0]=='ac':ctx.damage_cache.setdefault('steel_object_results',{}).setdefault(obj.object_id,{})['ac']=PREFIX+'folded_edge_hidden_spine'
            else:
                extras.append(object_bonus(ctx,obj,count=2,name='Folded Edge, Hidden Spine'))
    charge=_edge_charge(ctx.actor) if 'quench' in roles else None
    if charge:
        ctx.actor.turn_flags.pop('_round_edge_quench_charge',None)
        extras.append(object_bonus(ctx,obj,count=2,name='Edge Quench'))
    if 'beyond' in roles and ctx.actor.turn_flags.get('_round_perfect')!=stamp:
        labels={'edge':'Perfect Edge: +4d8 Slashing or Force and reduce its AC by 1 until your next turn',
                'spine':f'Perfect Spine: {2*_pb(ctx.actor,ctx.engine)+_con(ctx.engine,ctx.actor)} Temporary HP and resist physical push, pull and Prone until your next turn',
                'reed':'Perfect Reed: move up to 20 feet without provoking; hostile spaces are difficult terrain'}
        picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'perfect_object',obj.object_id),ctx.actor,
            'choice:needle.body_beyond_the_hammer',list(labels),labels=labels,allow_decline=True,default='decline',
            target_id=obj.object_id,name='Body Beyond the Hammer',feature_id=PREFIX+'body_beyond_the_hammer',
            prompt='Body Beyond the Hammer: choose one Perfect result for this melee hit. No action or Stamina cost.')
        if picked and picked[0] in labels:
            ctx.actor.turn_flags['_round_perfect']=stamp
            if picked[0]=='edge':
                extras.append(object_bonus(ctx,obj,count=4,name='Perfect Edge'))
                ctx.damage_cache.setdefault('steel_object_results',{}).setdefault(obj.object_id,{})['ac']=PREFIX+'body_beyond_the_hammer'
            else:
                ctx.damage_cache.setdefault('steel_object_results',{}).setdefault(obj.object_id,{})['perfect']=picked[0]
    result={'packets':extras,'final_multiplier':multiplier}
    if 'folded' in roles and ordinary_body_object_resistance(ctx,obj,kind):
        result['ignore_resistance_types']=['BLUDGEONING','PIERCING','SLASHING']
    return result if extras or multiplier>1 or result.get('ignore_resistance_types') else None


def ordinary_body_object_resistance(ctx,obj,kind):
    """Actual Body delivery and explicit object defense authority, not labels."""
    if kind!='unarmed':
        from .weapon_hits import weapon_identity
        from .integrated_weapons import active_integration
        action=ctx.engine.action_catalog.get(weapon_identity(ctx))
        if kind!='weapon' or action is None or not active_integration(ctx.engine,ctx.actor,action):return False
    component=obj.component or {}
    if any(component.get(k) for k in ('artifact','divine_protection','secret_protection','immortal_protection','void_protection','physical_force_protected')):return False
    if component.get('unbypassable_resistance'):
        from .body_modes_scene_resources import object_source_cl,effective_body_cl
        cl=object_source_cl(ctx.engine,ctx.actor,obj)
        if cl is None or cl>=effective_body_cl(ctx.engine,ctx.actor):return False
    return True


@hook('source_consequence')
def hammer_source_result(engine, actor, result):
    beyond='beyond' in _roles(engine,actor)
    operation=result['operation']
    if not beyond:
        if (not tempered_core(engine,actor,'heavenly_fist',17) or result['target_kind']!='weapon'
                or result['target_key']!=tempered_weapon(engine,actor) or operation not in ('disarm','break','rust','dull')):return
        from .body_modes_scene_resources import effective_body_cl
        if result['authority']=='ordinary' and not (result['explicit_source_cl']==1 and result['source_cl']>=effective_body_cl(engine,actor)):
            return {'prevented':1}
        return
    if operation in ('destroy_limb','deform_limb'):
        from .source_consequences import result_nature
        if (result['target_kind'] in ('limb','natural_structure','appendage')
                and result['reconstructable']==1 and result_nature(result)=='physical'):
            return {'dice':{'count':4,'sides':10},'damage_type':'FORCE',
                    'source':PREFIX+'body_beyond_the_hammer','exclude_temp_hp_source':PREFIX+'body_beyond_the_hammer',
                    'excluded_reduction_sources':[PARENT],
                    'label':'Body Beyond the Hammer: take 4d10 Force damage instead of losing the physical structure. It remains functional. Thousand-Fold Steel Body cannot reduce this damage; independent legal defenses still apply. No Reaction or Stamina cost.'}
        return
    from .body_modes_scene_resources import effective_body_cl
    if result['authority']!='ordinary' or (result['explicit_source_cl']==1 and result['source_cl']>=effective_body_cl(engine,actor)):return
    if result['target_kind'] in ('body','limb','natural_structure','appendage') or (result['target_kind']=='weapon' and result['target_key']==tempered_weapon(engine,actor)):
        return {'prevented':1}


@hook('attack_materials')
def hammer_material(engine, actor, action, attack_kind):
    beyond='beyond' in _roles(engine,actor)
    if not beyond and not tempered_core(engine,actor,'heavenly_fist',17):return
    from .weapon_hits import physical_weapon_id
    if attack_kind=='unarmed' and beyond or (attack_kind=='weapon' and action is not None
        and physical_weapon_id(action.source_definition_id,action.parameters)==tempered_weapon(engine,actor)):
        return ['adamantine']


def object_bonus(ctx,obj,*,count=0,flat=0,name):
    from .needle import ask,checkpoint_id
    from ..gate2_runtime_models import DiceSpec
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'steel_object_type',obj.object_id+name),ctx.actor,
        'choice:needle.steel_object_damage_type',['slashing','force'],labels={'slashing':'Slashing damage','force':'Force damage'},
        preferred=['slashing'],default='slashing',name=name,target_id=obj.object_id,
        prompt=name+': choose Slashing or Force damage for this hit. No additional cost.')
    kind=(picked[0] if picked else 'slashing').upper()
    if count:
        roll=ctx.engine.roller.roll(DiceSpec(count=count,sides=8),actor_id=ctx.actor.entity_id,reason='DAMAGE:'+name,critical=bool(ctx.critical_hit))
        ctx.engine._record_roll(roll);flat+=int(roll.total)
    return flat,kind


def lower_object_ac(engine,owner,obj,feature):
    # One shared source reduction; another hit refreshes its source-turn clock.
    obj=engine.state.objects[obj.object_id]
    component=dict(obj.component or {})
    if not component.get('steel_ac_reduction'):
        obj=obj.model_copy(update={'ac':obj.ac-1})
    from .body_modes_scene_resources import effective_body_cl
    component['steel_ac_reduction']={'owner':owner.entity_id,'until':int(owner.turns_started)+1,
        'feature':feature,'source_cl':effective_body_cl(engine,owner)}
    engine._update_object(obj.model_copy(update={'component':component}),AC_SOURCE,owner.entity_id)


@hook('turn_start')
def object_ac_expires(engine,actor,*,nominal=False):
    for obj in list(engine.state.objects.values()):
        held=(obj.component or {}).get('steel_ac_reduction')
        from .effect_durations import custom_turn_due
        if held and held['owner']==actor.entity_id and custom_turn_due(actor,held['until'],actor.turn_flags,'steel_object_ac:'+obj.object_id,nominal=nominal):
            component=dict(obj.component);component.pop('steel_ac_reduction')
            engine._update_object(obj.model_copy(update={'ac':obj.ac+1,'component':component}),AC_SOURCE,actor.entity_id)


@hook('integrated_weapon_selection')
def selected_tempered_integration(engine,actor,source,weapon):
    if source==TEMPER:return bool(weapon and weapon==tempered_weapon(engine,actor))


@hook('resistance_ignored')
def folded_body_resistance(engine,kind,typed,source_actor_id,target):
    actor=engine.state.actors.get(source_actor_id)
    if actor is None or 'folded' not in _roles(engine,actor) or kind not in ('BLUDGEONING','PIERCING','SLASHING'):return
    from .weapon_hits import physical_weapon_id
    from .integrated_weapons import active_integration
    from ..weapon_delivery import delivery_kind
    attack=next((e for e in typed.get('effects',()) if e.get('type')=='attack'),None)
    if attack is None or typed.get('range_ft'):return
    delivery=delivery_kind(typed,attack)
    if delivery!='unarmed':
        from ..pending_damage import current
        from .source_eligibility import catalog_action
        from ..weapon_delivery import weapon_identity
        packet=current(engine)
        action=catalog_action(engine,packet.source_id) if packet is not None and packet.source_actor_id==actor.entity_id else None
        if action is not None:
            identity=weapon_identity(engine,action.source_definition_id,typed,action.parameters,owner_id=actor.entity_id)
            action=engine.action_catalog.get(identity)
        if delivery!='weapon' or action is None or not active_integration(engine,actor,action):return
    # Explicit protected authority is not ordinary Resistance. Immunity is
    # handled independently by the native defense pipeline and remains intact.
    if target is not None:
        from .body_modes_scene_resources import effective_body_cl
        rows=list(getattr(engine,'typed_passive_rows',{}).get(target.entity_id,()))
        rows += [c.data for c in target.conditions.values()]
        for row in rows:
            if row.get('kind')!='resistance' and row.get('defense_kind')!='resistance':continue
            if row.get('damage_types') and kind not in {str(k).upper() for k in row['damage_types']}:continue
            if row.get('authority') in ('artifact','divine','secret','immortal') or (row.get('explicit_source_cl')==1
                and int(row.get('source_cl',0))>=effective_body_cl(engine,actor) and row.get('cannot_bypass')==1):return
    return True


@hook('activity_finished')
def session_tempered_choice(session,aid,activity):
    from .journey_activities import CULTIVATION_SESSION
    from .body_modes_scene_resources import queue_journey_choice
    if activity['source']==CULTIVATION_SESSION and journey_forms_access(session,aid):
        queue_journey_choice(session,aid,TEMPER,'temper_after_session',{})


@hook('body_journey_choice_options')
def session_weapon_options(session,aid,pending):
    if pending['source']!=TEMPER or pending['kind']!='temper_after_session':return
    choices=[('retain','Keep your current Tempered Weapon')]+[(key,'Temper '+a['display_name'].removesuffix(' attack'))
        for key,a in journey_weapons(session,aid).items()]
    return [{'id':'steel:session:'+key,'kind':'body_mode_choice','auto_select':0,
        'payload':{'choice':key,'parameters':{}},'label':label+' after your completed Full Cultivation Session; no additional time or Stamina cost.'}
        for key,label in choices]


@hook('body_journey_choice_resolve')
def session_weapon_selected(session,aid,pending,choice,parameters):
    if pending['source']!=TEMPER or pending['kind']!='temper_after_session':return
    from ..journey import require
    require(not parameters and journey_forms_access(session,aid),'Tempering requires current access to Body Forged in Three Forms.')
    if choice!='retain':
        require(choice in journey_weapons(session,aid),'Choose a proficient melee weapon you possess.')
        state=session.state['actors'][aid].setdefault('source_states',{}).setdefault(PARENT,{})
        from .body_modes_scene_resources import journey_body_cl
        state.update(tempered_weapon=choice,tempered_source_cl=journey_body_cl(session,aid))
        session.emit('WEAPON_TEMPERED',aid,source=TEMPER,weapon=choice,worked_seconds=7200)
    return True


@hook('event',priority=-300)
def suppression_selection(engine,event_type,kwargs):
    if event_type!='INTENT_ACCEPTED':return
    from .body_modes_scene_resources import effective_body_cl
    from .needle import ask,checkpoint_id
    for actor in engine.state.actors.values():
        roles=_roles(engine,actor)
        if 'forms' not in roles:continue
        count=_count(roles);held=next((c for c in actor.conditions.values() if c.condition_id==FORMS),None)
        level=effective_body_cl(engine,actor)
        if held is None or len(forms(actor))<=count or held.data.get('suppressed_choice_cl')==level:continue
        allowed=forms(actor)
        picked=ask(engine,_intent(engine),checkpoint_id(engine,'steel_suppression',actor.entity_id),actor,
            'choice:needle.steel_suppressed_forms',allowed,minimum=count,maximum=count,preferred=allowed[:count],
            name='Ten Thousand Reforgings',feature_id=PREFIX+'ten_thousand_reforgings',target_id=actor.entity_id,
            prompt=f'Cultivation suppression: choose {count} active Tempering Form'+('s' if count>1 else '')+'. Your other Forms remain dormant; no action or Stamina cost.')
        selected=list(picked or allowed[:count]);selected += [f for f in allowed if f not in selected]
        engine._update_condition_data(actor,held,{**held.data,'forms':selected,'suppressed_choice_cl':level},TEMPER)


@hook('activity_tool_objects')
def maintenance_tools(session,aid,task):
    if (not journey_forms_access(session,aid) or task.get('owner')!=aid
            or task.get('operation') not in ('maintain','sharpen','clean','repair')
            or task.get('context') not in ('rest','downtime','cultivation_session')):return
    # This is the actual tool object permission, not a Blacksmith rank,
    # crafting recipe, facility, material grant, or repair of destroyed gear.
    from ..carry import item_of
    bundle=session.state['actors'][aid]['bundle'];carrying=bundle.get('carrying') or {}
    items=set()
    for action in bundle.get('action_catalog',()):
        item=item_of(carrying,weapon_action=action['source_definition_id'])
        if item is not None and int(item.get('quantity',0))>0:
            items.update((action['source_definition_id'],item['key']))
    items.update(item['key'] for item in carrying.get('items',())
                 if item.get('kind')=='armor' and int(item.get('quantity',0))>0)
    return ['smithing'] if task.get('item') in items else None


@hook('damage_bypasses_temporary_hp')
def replacement_ignores_perfect_buffer(engine,target,amount,damage_type,source_id,source_actor_id):
    if not own_reduction_excluded(engine):return
    latest=next((e for e in reversed(engine.events) if e.event_type=='TEMP_HP_GRANTED' and target.entity_id in e.target_ids
        and int(e.payload.get('after',0))>int(e.payload.get('before',0))),None)
    return bool(latest and latest.source_definition_id==PREFIX+'body_beyond_the_hammer')


@hook('damage_defended')
def spine_first_packet_consumed(engine,target,kind,source,source_actor_id,defenses):
    from ..pending_damage import current
    packet=current(engine)
    if (packet is not None and packet.amount>0 and 'spine' in active_forms(engine,target)
            and str(kind).upper() in ('BLUDGEONING','PIERCING','SLASHING')):
        target.turn_flags['_round_spine_form']=int(engine.state.round_number)


@hook('ability_check_hazard_mode')
def form_check_advantage(engine,actor,ability,skill,against,hazards):
    names={str(n).lower().removeprefix('category:') for n in hazards}
    active=active_forms(engine,actor)
    if ('spine' in active and names & {'prone','avoid_prone','resist_prone'}
        or 'reed' in active and names & {'escape_grapple','escape_grappled'}):return 'ADVANTAGE'


@hook('damage_type_choice')
def steel_damage_type(ctx,kinds,targets):
    if not ctx.typed.get('steel_damage_choice') or not _roles(ctx.engine,ctx.actor):return
    from .needle import ask,checkpoint_id
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'steel_damage_type',ctx.target.entity_id if ctx.target else ''),
        ctx.actor,'choice:needle.steel_damage_type',list(kinds),labels={k:k.title()+' damage' for k in kinds},
        preferred=list(kinds)[:1],name='Thousand-Fold Steel Body',target_id=ctx.target.entity_id if ctx.target else ctx.actor.entity_id,
        prompt='Thousand-Fold Steel Body: choose the added damage type for this hit. No additional action or Stamina cost.')
    return picked[0] if picked else kinds[0]


@hook('attack_spec_choice')
def tempered_constitution(ctx,target,attack,spec,index):
    from .weapon_hits import weapon_identity
    from ..weapon_delivery import delivery_kind
    from .attack_abilities import select_strike_ability
    if (delivery_kind(ctx.typed,attack,ctx.action.parameters)!='weapon'
            or weapon_identity(ctx)!=tempered_weapon(ctx.engine,ctx.actor)):return
    weapon=(spec.get('typed') or {}).get('weapon') or {}
    # A separately chosen independent mental-stat replacement retains its own
    # contract. This source replaces Strength and Dexterity only.
    if str(weapon.get('ability') or 'STR').upper() in ('STR','DEX'):
        select_strike_ability(ctx,spec,'CON',_con(ctx.engine,ctx.actor))
        if TEMPER not in ctx.typed.get('integration_sources',()):
            current_pb=_pb(ctx.actor,ctx.engine);old_pb=int(ctx.numbers.get('pb') or ctx.actor.proficiency_bonus or 2)
            spec['attack_bonus']+=current_pb-old_pb
            spec['typed']['numbers']={**spec['typed']['numbers'],'pb':current_pb,'attack_bonus':spec['attack_bonus']}


@hook('resolution_numbers')
def tempered_suppressed_numbers(ctx,numbers):
    if TEMPER not in ctx.typed.get('integration_sources',()):return
    from .body_modes_scene_resources import effective_body_pb
    pb=effective_body_pb(ctx.engine,ctx.actor)
    old=int(numbers.get('pb') or ctx.actor.proficiency_bonus or 2)
    return {**numbers,'pb':pb,'attack_bonus':int(numbers.get('attack_bonus',0))-old+pb}


def edge_form_declared(ctx,target_id):
    from .needle import ask,checkpoint_id
    from ..weapon_delivery import delivery_kind
    attack=next((e for e in ctx.typed.get('effects',()) if e.get('type')=='attack'),None)
    if attack is not None and delivery_kind(ctx.typed,attack,ctx.action.parameters) not in ('unarmed','weapon'):return False
    amount=_pb(ctx.actor,ctx.engine)*(2 if 'reforgings' in _roles(ctx.engine,ctx.actor) else 1)
    return bool(ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'steel_edge',target_id),ctx.actor,
        'choice:needle.edge_form',['use'],labels={'use':f'Add {amount} Slashing or Force damage to this hit'},
        allow_decline=True,default='use',preferred=['use'],name='Edge Form',feature_id=TEMPER,target_id=target_id,
        prompt=f'Edge Form: add {amount} Slashing or Force damage to this hit, once this turn? No action or Stamina cost.'))


@hook('object_attack_resolved')
def steel_object_resolved(ctx,obj,kind,hit):
    if not _roles(ctx.engine,ctx.actor) or not _melee(ctx,kind):return
    if not hit:
        ctx.actor.turn_flags.pop('_round_edge_quench_charge',None)
        return
    result=ctx.damage_cache.get('steel_object_results',{}).pop(obj.object_id,{})
    if result.get('ac'):lower_object_ac(ctx.engine,ctx.actor,obj,result['ac'])
    if result.get('perfect')=='spine':
        ctx.engine._grant_temp_hp(ctx.actor,2*_pb(ctx.actor,ctx.engine)+_con(ctx.engine,ctx.actor),PREFIX+'body_beyond_the_hammer',ctx.actor.entity_id)
        ctx.actor.turn_flags['_round_perfect_spine']={'until':int(ctx.actor.turns_started)+1,'source_cl':effective_body_cl(ctx.engine,ctx.actor)}
    elif result.get('perfect')=='reed':
        _free_move(ctx.engine,ctx.intent,ctx.actor,20,'choice:needle.perfect_reed_move','Perfect Reed',feature_id=PREFIX+'body_beyond_the_hammer')
    _reed(ctx.engine,ctx.intent,ctx.actor)


CORE='tianxia.path.body_refining.feature.'


def tempered_core(engine,actor,name,level):
    from .body_modes_scene_resources import bundle_of,available
    # Already-acquired core progression is consumed, never granted by learning
    # this Subpath or by merely reaching a character level.
    return (CORE+name in bundle_of(engine,actor).get('body_feature_levels',{})
            and available(engine,actor,CORE+name,level,requires_conscious=False)
            and bool(tempered_weapon(engine,actor)))


@hook('object_attack_all_profiles')
def all_owned_weapon_profiles(info):
    return True if TEMPER in info['owned_ids'] else None


@hook('object_attack_profile_actions')
def object_cultivation_profiles(info):
    if TEMPER not in info['owned_ids']:return
    from .integrated_weapons import integrated_bases,constitution_typed
    return [a.model_copy(update={'source_definition_id':a.source_definition_id+'#integrated_con',
        'display_name':a.display_name+' (Cultivation attack, Constitution damage)',
        'parameters':{**a.parameters,'typed':constitution_typed(info,a.parameters['typed'])}})
        for a in integrated_bases(info)]


@hook('candidate_allowed')
def object_physical_weapon_gate(engine,actor,candidate,action):
    if action is None or not action.parameters.get('object_attack'):return
    source=action.parameters.get('weapon_source_id')
    if not source:return
    base=engine.action_catalog.get(source)
    if base is None:return False
    from .hand_occupancy import weapon_allowed
    if weapon_allowed(engine,actor,base) is False:return False
    typed=base.parameters.get('typed') or {}
    if TEMPER in typed.get('integration_sources',()):
        from .weapon_hits import physical_weapon_id
        return physical_weapon_id(base.source_definition_id,base.parameters)==tempered_weapon(engine,actor)


@hook('object_attack_statistics')
def tempered_object_statistics(ctx,obj,weapon):
    from .weapon_hits import weapon_identity
    identity=weapon_identity(ctx)
    if not identity or identity!=tempered_weapon(ctx.engine,ctx.actor):return
    import copy
    numbers=dict(ctx.numbers);out=copy.deepcopy(weapon)
    current_pb=_pb(ctx.actor,ctx.engine);old_pb=int(numbers.get('pb') or ctx.actor.proficiency_bonus or 2)
    numbers['attack_bonus']=int(numbers.get('attack_bonus',0))-old_pb+current_pb
    numbers['pb']=current_pb
    parent=ctx.engine.action_catalog.get(ctx.action.parameters.get('weapon_source_id'))
    integrated=parent is not None and TEMPER in (parent.parameters.get('typed') or {}).get('integration_sources',())
    if not integrated:
        old=int(out.get('ability_modifier',0));new=_con(ctx.engine,ctx.actor)
        numbers['attack_bonus']=int(numbers.get('attack_bonus',0))-old+new
        out['damage']['modifier']=int(out['damage'].get('modifier',0))-old+new
        out.update(ability='CON',ability_modifier=new)
    return {'numbers':numbers,'weapon':out}


@hook('attack_magical')
def refined_tempered_weapon(engine,source_actor_id,typed):
    from ..pending_damage import current
    from .source_eligibility import catalog_action
    from ..weapon_delivery import weapon_identity
    actor=engine.state.actors.get(source_actor_id);packet=current(engine)
    if actor is None or packet is None or not tempered_core(engine,actor,'refined_iron_fist',5):return
    action=catalog_action(engine,packet.source_id)
    return bool(action and weapon_identity(engine,action.source_definition_id,typed,action.parameters,owner_id=actor.entity_id)==tempered_weapon(engine,actor))


@hook('attack_damage_types')
def heavenly_tempered_damage_types(ctx,attack,kinds):
    from .weapon_hits import weapon_identity,is_weapon_hit
    if (is_weapon_hit(ctx,attack) and weapon_identity(ctx)==tempered_weapon(ctx.engine,ctx.actor)
            and tempered_core(ctx.engine,ctx.actor,'heavenly_fist',17)):
        return list(dict.fromkeys([*kinds,'FORCE']))


@hook('object_attack_packet')
def heavenly_tempered_object(ctx,obj,kind,packets):
    from .weapon_hits import weapon_identity
    from .body_modes_scene_resources import object_source_cl,effective_body_cl
    if (weapon_identity(ctx)!=tempered_weapon(ctx.engine,ctx.actor)
            or not tempered_core(ctx.engine,ctx.actor,'heavenly_fist',17)):return
    cl=object_source_cl(ctx.engine,ctx.actor,obj)
    if cl is None or cl>effective_body_cl(ctx.engine,ctx.actor) or obj.component.get('world_scale'):return
    eligible=obj.unattended or any(obj.component.get(k) for k in ('vehicle','structure','temporary_barrier','formation_anchor'))
    if eligible:
        result={'multiplier':2}
        # Double the qualifying attack without waiving protected defenses.
        # Actual Immunity always remains with the normal object pipeline.
        if not any(obj.component.get(flag) for flag in ('artifact','immortal_protection','void_protection','physical_force_protected')):
            result.update(ignore_threshold=1,ignore_resistance_types=['BLUDGEONING','PIERCING','SLASHING','FORCE'])
        return result


@hook('attack_damage_type_choice')
def heavenly_tempered_damage_choice(ctx,attack,target,kinds,index):
    from .weapon_hits import weapon_identity,is_weapon_hit
    if (not is_weapon_hit(ctx,attack) or weapon_identity(ctx)!=tempered_weapon(ctx.engine,ctx.actor)
            or not tempered_core(ctx.engine,ctx.actor,'heavenly_fist',17)):return
    from .needle import ask,checkpoint_id
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'tempered_heavenly_type',target.entity_id),ctx.actor,
        'choice:needle.tempered_weapon_damage_type',list(kinds),labels={k:k.title()+' damage' for k in kinds},
        preferred=list(kinds)[:1],name='Tempered Weapon',feature_id=TEMPER,target_id=target.entity_id,
        prompt='Tempered Weapon: choose its normal damage type or Force from your acquired Heavenly Fist. No extra action or Stamina cost.')
    return picked[0] if picked else kinds[0]


@hook('object_attack_damage_types')
def steel_object_damage_types(ctx,obj,kind,kinds):
    if 'forms' not in _roles(ctx.engine,ctx.actor):return
    from .weapon_hits import weapon_identity
    result=list(kinds)
    if kind=='unarmed' and 'edge' in active_forms(ctx.engine,ctx.actor):result.append('SLASHING')
    if weapon_identity(ctx)==tempered_weapon(ctx.engine,ctx.actor) and tempered_core(ctx.engine,ctx.actor,'heavenly_fist',17):result.append('FORCE')
    return list(dict.fromkeys(result))


@hook('object_attack_damage_type_choice')
def steel_object_primary_type(ctx,obj,kind,kinds):
    if 'forms' not in _roles(ctx.engine,ctx.actor) or len(kinds)<2:return
    from .needle import ask,checkpoint_id
    picked=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'steel_object_primary_type',obj.object_id),ctx.actor,
        'choice:needle.steel_object_primary_damage_type',list(kinds),labels={k:k.title()+' damage' for k in kinds},
        preferred=list(kinds)[:1],name='Thousand-Fold Steel Body',feature_id=TEMPER,target_id=obj.object_id,
        prompt='Choose this object attack’s damage type from its legal weapon and Body options. No extra action or Stamina cost.')
    return picked[0] if picked else kinds[0]


@hook('effect_resolution_scope')
def steel_hit_aftermath(ctx,effect):
    if effect.get('type') in ('attack','object_attack') and _roles(ctx.engine,ctx.actor):
        # Earned hit results finish before this activation checks victory.
        return ctx.engine.victory_deferred()


def own_reduction_excluded(engine):
    from ..pending_damage import current
    packet=current(engine)
    return bool(packet and 'exclude_reduction_source:'+PARENT in packet.source_flags)


@hook('condition_application_attempt')
def perfect_spine_native_prone(engine,target,condition_id,source_id,source_actor_id):
    if (str(condition_id).rsplit('.',1)[-1]=='prone' and 'beyond' in _roles(engine,target)
            and target.turn_flags.get('_round_perfect_spine')):
        return False


@hook('armor_class_modifier_enabled')
def steel_ac_available(engine,target,modifier):
    """A saved rider keeps its creating feature and Source CL during suppression."""
    if modifier.source_definition_id!=AC_SOURCE:return
    owner=engine.state.actors.get(modifier.source_actor_id)
    feature=modifier.data.get('feature',PREFIX+'folded_edge_hidden_spine')
    role=next((role for role,(name,level) in LEVELS.items() if PREFIX+name==feature),None)
    level=LEVELS[role][1] if role else None
    if level is None or owner is None or role not in _roles(engine,owner):return False
    from .body_modes_scene_resources import available
    return bool(owner and available(engine,owner,feature,level,requires_conscious=False))


@hook('object_armor_class_adjustment')
def steel_object_ac_dormancy(engine,obj):
    held=(obj.component or {}).get('steel_ac_reduction')
    if not held:return
    owner=engine.state.actors.get(held.get('owner'))
    feature=held.get('feature',PREFIX+'folded_edge_hidden_spine')
    role=next((role for role,(name,level) in LEVELS.items() if PREFIX+name==feature),None)
    level=LEVELS[role][1] if role else None
    if owner is None or role not in _roles(engine,owner):return 1
    from .body_modes_scene_resources import available
    if level is None or not owner or not available(engine,owner,feature,level,requires_conscious=False):return 1


@hook('condition_state')
def folded_condition_provenance(ctx,target,effect):
    if ctx.source==PREFIX+'folded_edge_hidden_spine' and effect.get('condition')=='reaction_denied' and 'folded' in _roles(ctx.engine,ctx.actor):
        return {'data':{'source_cl':effective_body_cl(ctx.engine,ctx.actor)}}


@hook('state_event',priority=500)
def folded_condition_dormancy(engine,event):
    from .body_modes_scene_resources import SUPPRESSION
    if event.event_type not in ('CONDITION_APPLIED','CONDITION_REMOVED'):return
    if event.payload.get('condition_id')!=SUPPRESSION:return
    from ..typed_executor import condition_rule_instances
    for target in engine.state.actors.values():
        for held in list(target.conditions.values()):
            if held.source_definition_id!=PREFIX+'folded_edge_hidden_spine' or held.condition_id!='condition:typed.reaction_denied':continue
            owner=engine.state.actors.get(held.source_actor_id)
            dormant=not owner or 'folded' not in _roles(engine,owner)
            if bool(held.data.get('suppressed'))==dormant:continue
            data={**held.data,'suppressed':int(dormant)}
            if not dormant:
                # Remember only an actually unspent Reaction; later suppression
                # cannot refund one spent during the earlier dormant interval.
                data['reaction_suppression_restore']=int(target.reaction_available)
                target.reaction_available=False
            if dormant and data.get('reaction_suppression_restore') and not any(rule.get('no_reactions')
                    for other,rule in condition_rule_instances(target) if other.instance_id!=held.instance_id):
                target.reaction_available=True
            # The recognized condition update captures both the retained effect
            # and native Reaction balance in the same mechanical replay event.
            engine._update_condition_data(target,held,data,PREFIX+'folded_edge_hidden_spine')


@hook('state_event',priority=600)
def folded_dormant_reaction_spent(engine,event):
    """A real spent Reaction invalidates a dormant denial's restoration credit."""
    for target in engine.state.actors.values():
        if target.reaction_available:continue
        for held in list(target.conditions.values()):
            if (held.source_definition_id==PREFIX+'folded_edge_hidden_spine'
                    and held.condition_id=='condition:typed.reaction_denied'
                    and held.data.get('suppressed') and held.data.get('reaction_suppression_restore')):
                engine._update_condition_data(target,held,{**held.data,'reaction_suppression_restore':0},PREFIX+'folded_edge_hidden_spine')
