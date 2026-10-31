"""Oni Blood Subpath riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, "17. Oni Blood" (Blood Hunger and the five features, with their Normalized
Procedures). States (combat/ext/states.py): "oni_mask", "oni_form", "crimson_oni_form". Owned rows: ``{"type": "path_passive",
"kind": "oni", "role": "drinker"}``. Effects: ``oni_form`` (Oni Form's body, shared with Crimson Oni), ``crimson_oni``.

Oni Mask        1 minute: once per turn on an unarmed hit + 1d6 Necrotic (2d6 in Oni Form, 3d6 in Crimson Oni's form: each
                replaces the smaller); "End Oni Mask" is a free button while it lasts.
Blood Hunger    at the start of your turn with the Mask or Form on and a Bloodied hostile creature within 30 feet: choose the
                obligation (asked). Moving 10 feet toward a hostile creature or attacking is yours to keep (logged); restraining
                is a Wisdom save against your own Cultivation Save DC -- on a failure, until the start of your next turn a move
                may not end farther from every hostile creature than where it began (candidate_allowed).
Blood Drinker   with the Mask or Form on: once per turn when an unarmed strike damages a hostile creature that was Bloodied
                before the hit, Temporary Hit Points PB (twice PB in Crimson Oni's form); a hostile creature your unarmed strike
                drops to 0 heals you CON + PB, once per creature.
Demon Roar      its typed cone; a Bloodied creature has Disadvantage on the initial save.
Oni Form        the Mask (free), Temporary HP twice CL, Resistance to Cold, Fire and Necrotic, Advantage on Strength saves and
                checks, +5 ft unarmed reach (reach_bonus), 2d6; when it ends, the Mask ends too.
Crimson Oni     its free drop-to-zero row holds you at 1 HP and ``crimson_oni`` brings you to half your maximum once the packet
                lands, starts Oni Form (free, even if used) and ends your Frightened, Stunned and Restrained of Source CL no
                higher than yours; in that form Advantage on unarmed attacks against Bloodied hostile creatures; when it ends,
                1 Exhaustion level.
Every hook returns early for a creature without these rows or states.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

PREFIX = "tianxia.subpath.body.oni_blood.feature."
MASK, FORM, CRIMSON = "oni_mask", "oni_form", "crimson_oni_form"
HUNGER = "condition:typed.blood_hunger"


def _state(engine: Any, actor: Any, name: str) -> Any:
    from .states import active

    return active(engine, actor, name) if actor is not None else None


def _masked(engine: Any, actor: Any) -> bool:
    return bool(_state(engine, actor, MASK) or _state(engine, actor, FORM))


def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "oni"}


def _stamp(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def _bloodied(creature: Any, hp: int | None = None) -> bool:
    return int(creature.current_hp if hp is None else hp) <= int(creature.maximum_hp) // 2


def _cl(engine: Any, actor: Any) -> int:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == actor.entity_id), None)
    return int((bundle or {}).get("cl") or 1)


def _unarmed(ctx: Any) -> bool:
    return ".natural." in ctx.source or any(isinstance(e, dict) and e.get("type") == "attack" and e.get("attack_kind") == "unarmed"
                                            for e in ctx.typed.get("effects") or [])


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _put_state(engine: Any, actor: Any, name: str, label: str, expires: str, source: str) -> None:
    from .states import PREFIX as STATE, slug

    for iid, held in list(actor.conditions.items()):
        if held.condition_id == STATE + slug(name):
            engine._remove_condition_instance(actor, iid, source, expected=held)
    engine._apply_condition(actor, STATE + slug(name), source, actor.entity_id, expires_on=expires, data={"label": label, "name": name})


def _end_state(engine: Any, actor: Any, name: str, source: str) -> None:
    from .states import PREFIX as STATE, slug

    for iid, held in list(actor.conditions.items()):
        if held.condition_id == STATE + slug(name):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "ENDED"})


# ------------------------------------------------------------------------------------------------ Mask and Form
@hook("after_hit")
def necrotic_rider(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    if kind != "unarmed" or target is None or not target.active or target.team_id == actor.team_id or not _masked(engine, actor):
        return
    if actor.turn_flags.get("_round_oni_rider") == _stamp(engine):
        return
    actor.turn_flags["_round_oni_rider"] = _stamp(engine)
    count = 3 if _state(engine, actor, CRIMSON) else 2 if _state(engine, actor, FORM) else 1
    from .. import typed_executor as te

    te.run_effects(ctx.on_hit_context(target, action=ctx.action, typed=ctx.typed, damage_cache={}),
                   [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 6}, "damage_types": ["necrotic"],
                     "evidence": f"Oni Blood: once per turn + {count}d6 Necrotic"}])


@hook("compile_actions")
def end_mask_button(info: dict[str, Any]) -> list[Any] | None:
    if PREFIX + "oni_mask" not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.end_oni_mask", display_name="End Oni Mask", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             parameters={"setting_only": True, "end_oni_mask": True, "expected_damage": 0, "player_only": True,
                                         "typed": {"effects": [{"type": "end_oni_mask"}], "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                                         "description": "End your Oni Mask (no action)."})]


@hook("candidate_allowed")
def end_mask_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("end_oni_mask"):
        return None if _state(engine, actor, MASK) else False
    if _hungry_move_blocked(engine, actor, candidate):
        return False
    return None


@effect("end_oni_mask")
def end_oni_mask(ctx: Any, row: dict[str, Any]) -> None:
    _end_state(ctx.engine, ctx.actor, MASK, PREFIX + "oni_mask")


@effect("oni_form")
def oni_form(ctx: Any, row: dict[str, Any]) -> None:
    start_form(ctx, crimson=bool(row.get("crimson")))


def start_form(ctx: Any, *, crimson: bool = False) -> None:
    """Oni Form's body: the Mask for free, the form's own state and its lasting benefits (typed, 1 minute)."""
    from .. import typed_executor as te

    engine, actor = ctx.engine, ctx.actor
    expires = te.clock_expiry(engine, "minutes", 1) or "UNTIL_REMOVED"
    _put_state(engine, actor, MASK, "Oni Mask", expires, PREFIX + "oni_mask")
    _put_state(engine, actor, FORM, "Oni Form", expires, PREFIX + "oni_form")
    if crimson:
        _put_state(engine, actor, CRIMSON, "Crimson Oni", expires, PREFIX + "crimson_oni")
    te.run_effects(ctx, [{"type": "temp_hp", "applies_to": "self", "flat": 2 * _cl(engine, actor), "evidence": "Oni Form: Temporary Hit Points twice your CL"},
                         {"type": "resistance", "applies_to": "self", "damage_types": ["cold", "fire", "necrotic"], "expires_on": expires}])


@hook("save")
def form_strength(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is not None and str(ability).upper()[:3] == "STR" and _state(ctx.engine, subject, FORM):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    if subject is not None and ctx.source.endswith(PREFIX + "demon_roar") and ctx.actor is not subject and _bloodied(subject):
        return {"bonus": 0, "modes": ["DISADVANTAGE"]}  # Demon Roar: a Bloodied creature's initial save
    return None


@hook("ability_check_mode")
def form_strength_checks(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    return "ADVANTAGE" if str(ability).upper()[:3] == "STR" and _state(engine, actor, FORM) else None


@hook("attack_mode")
def crimson_hunter(ctx: Any, target: Any) -> str | None:
    if target is None or not _state(ctx.engine, ctx.actor, CRIMSON) or not _unarmed(ctx) or target.team_id == ctx.actor.team_id or not _bloodied(target):
        return None
    return "ADVANTAGE"


@hook("effect_expiring")
def form_ends(engine: Any, holder: Any, row: Any) -> None:
    """"When Oni Form ends, Oni Mask also ends"; Crimson Oni's form also costs 1 Exhaustion level."""
    from .states import PREFIX as STATE

    cid = getattr(row, "condition_id", None)
    if cid == STATE + FORM:
        _end_state(engine, holder, MASK, PREFIX + "oni_form")
        if _state(engine, holder, CRIMSON):
            _end_state(engine, holder, CRIMSON, PREFIX + "crimson_oni")
            from . import forged_exhaustion

            forged_exhaustion.add(engine, holder, 1, PREFIX + "crimson_oni")
            note(engine, PREFIX + "crimson_oni", holder, f"Crimson Oni's form ends: {holder.display_name} gains 1 Exhaustion level; its demonic traits cannot be hidden until a 2-hour Cultivation Session.")


# ------------------------------------------------------------------------------------------------- Blood Hunger
@hook("turn_start_choice")
def blood_hunger(engine: Any, actor: Any) -> None:
    if not actor.active or not _masked(engine, actor):
        return
    near = [c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and _bloodied(c)
            and engine._distance_actor_to_actor(actor, c) <= 30]
    if not near:
        return
    from .needle import ask, checkpoint_id

    labels = {"move": "Move at least 10 feet toward a hostile creature this turn", "attack": "Make at least one attack against a hostile creature this turn",
              "restrain": "Restrain the hunger (Wisdom save against your own Cultivation Save DC)"}
    picked = ask(engine, _intent(engine), checkpoint_id(engine, "blood_hunger", actor.entity_id), actor, "choice:needle.blood_hunger", list(labels),
                 labels=labels, preferred=["attack"], target_id=actor.entity_id, name="Blood Hunger",
                 prompt=f"Blood Hunger: a Bloodied hostile creature is within 30 feet of {actor.display_name}. Choose the obligation.")
    choice = picked[0] if picked else "attack"
    if choice != "restrain":
        note(engine, PREFIX + "oni_mask", actor, f"Blood Hunger: {actor.display_name} must {labels[choice][0].lower() + labels[choice][1:]}.")
        return
    dc = next((int(r.get("save_dc")) for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []) if r.get("save_dc")), None) \
        or next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 0)
                 for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and PREFIX in a.source_definition_id), 10)
    roll = engine._roll_save(actor, "WIS", int(dc), PREFIX + "oni_mask")
    if roll is not None and int(roll.total) < int(dc):
        engine._apply_condition(actor, HUNGER, PREFIX + "oni_mask", actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"label": "Blood Hunger: a move may not end farther from every hostile creature"})


def _hungry_move_blocked(engine: Any, actor: Any, candidate: Any) -> bool:
    if getattr(getattr(candidate, "kind", None), "value", getattr(candidate, "kind", None)) != "MOVE" or getattr(candidate, "destination", None) is None:
        return False
    if not any(c.condition_id == HUNGER for c in actor.conditions.values()):
        return False
    foes = [c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id]
    if not foes:
        return False
    dest = candidate.destination
    return all(engine.grid.distance_ft(dest, f.position) > engine.grid.distance_ft(actor.position, f.position) for f in foes)


# ------------------------------------------------------------------------------------------------ Blood Drinker
@hook("damage_dealt")
def blood_drinker(ctx: Any, target: Any, amount: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or target.team_id == actor.team_id or "drinker" not in _roles(engine, actor) or not _masked(engine, actor) or not _unarmed(ctx):
        return
    from .. import typed_executor as te

    hp_lost = sum(int((e.payload or {}).get("hp_damage") or 0) for e in engine.events[-12:]
                  if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ()) and e.actor_id == actor.entity_id)
    before = int(target.current_hp) + hp_lost
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [actor], actor, {})
    if _bloodied(target, before) and before > 0 and actor.turn_flags.get("_round_blood_drinker") != _stamp(engine):
        actor.turn_flags["_round_blood_drinker"] = _stamp(engine)
        te.run_effects(sub, [{"type": "temp_hp", "applies_to": "self", "formula": "double_pb" if _state(engine, actor, CRIMSON) else "pb",
                              "evidence": "Blood Drinker"}])
    drunk = str(actor.turn_flags.get("_round_blood_drunk") or "").split("|")
    if int(target.current_hp) <= 0 and target.entity_id not in drunk:
        actor.turn_flags["_round_blood_drunk"] = "|".join([*[d for d in drunk if d], target.entity_id])
        con = int(((ctx.typed.get("numbers") or {}).get("con_mod")) or 0)
        te.run_effects(sub, [{"type": "healing", "applies_to": "self", "flat": con + int(actor.proficiency_bonus or 2), "evidence": "Blood Drinker"}])


# -------------------------------------------------------------------------------------------------- Crimson Oni
@effect("crimson_oni")
def crimson_oni(ctx: Any, row: dict[str, Any]) -> None:
    """After the held packet lands: half your maximum Hit Points, Oni Form (free), and the listed conditions of no higher CL end."""
    ctx.actor.turn_flags["_round_crimson_pending"] = int(ctx.engine.state.event_sequence)
    start_form(ctx, crimson=True)
    from .end_effect import source_cl

    mine = _cl(ctx.engine, ctx.actor)
    for iid, held in list(ctx.actor.conditions.items()):
        if held.condition_id.rsplit(".", 1)[-1] in ("frightened", "stunned", "restrained") and source_cl(ctx, held) <= mine:
            del ctx.actor.conditions[iid]
            ctx.engine._append_event("CONDITION_REMOVED", PREFIX + "crimson_oni", actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"condition_id": held.condition_id, "instance_id": iid, "reason": "CRIMSON_ONI"})


@hook("event")
def crimson_restores(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        actor = engine.state.actors.get(target_id)
        if actor is None or not actor.turn_flags.get("_round_crimson_pending"):
            continue
        actor.turn_flags.pop("_round_crimson_pending", None)
        half = int(actor.maximum_hp) // 2
        if actor.current_hp < half:
            before = actor.current_hp
            actor.current_hp = half
            engine._append_event("HEALING_APPLIED", PREFIX + "crimson_oni", actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"offered": half - before, "before": before, "after": half})
