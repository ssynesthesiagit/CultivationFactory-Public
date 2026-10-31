"""Sand sphere: the Buried state (rider lane C4, 2026-09-30; owner: "i want everything we can automated").

Sphere of Sand, Burial (printed core rule): "A Buried creature is partially covered, pinned, or swallowed by sand ...
Unless a talent says otherwise: the creature's Speed is reduced by 10 feet; the creature cannot benefit from being invisible
against creatures that can perceive the sand covering it; the creature has Disadvantage on Dexterity (Acrobatics) checks and
Dexterity saving throws made to avoid being knocked Prone or moved by Sand talents; the creature can end the Buried state by
using an Action to make a Strength (Athletics) or Dexterity (Acrobatics) check against your Cultivation Save DC. If a talent
says a creature is Buried and Restrained, it suffers the Restrained condition while the Buried state lasts. Ending the
Buried state ends that Restrained condition."

Typed rows apply the condition "buried" (combat/rules/typed_conditions.json); before this module it was a label only.
- condition_state: each Buried instance stores its burier's save DC (escape_dc) and a plain label. A row's condition_data
  may add escape_move "half_speed" (Burial of the Nameless Army: "A creature that succeeds may move up to half its Speed
  immediately as part of that Action").
- speed: -10 feet while the creature holds any Buried (once, however many).
- masked_conditions: its Invisible does not count for attacks against it, or for its own attacks, unless the other creature
  is Blinded (it cannot perceive the sand).
- save: Disadvantage on a Dexterity save against a Sand-sphere effect that would knock it Prone or move it.
- linked_hold_tracking topic "sand_burial": a typed Restrained row with parent_condition "buried" and tracking
  "sand_burial" lasts until that Buried ends (combat/ext/linked_holds.py).
- "Dig free of the sand": an Action every Buried creature gets; the better of Strength (Athletics) or Dexterity
  (Acrobatics) against the chosen Buried's DC (ext.escape_checks.resolve_escape_check). Success ends that Buried and the
  Restrained tied to it; escape_move then grants half its Speed of movement.
- Thousand-Grain Grip (TAL_SAND_THOUSAND_GRAIN_GRIP, "Trigger: A creature Buried by your Sand talent attempts to escape
  or move 5 feet or more ... The creature makes its escape check or relevant saving throw with Disadvantage. If it fails,
  it takes Slashing damage equal to your Proficiency Bonus + your key ability modifier."): the burier's compiled reaction
  row is offered (Ask me / AI) on that escape check. Its generic "moved" trigger has no check to affect, so the row never
  fires on bare movement (row_allowed); the escape check is the only roll it modifies here.
Inert for everyone else: nothing here acts unless a creature holds a Buried condition that a Sand talent applied.
"""
from __future__ import annotations

from typing import Any

from . import effect, effect_durations, hook
from .ability_source import escape_bonus

BURIED = "condition:typed.buried"
RESTRAINED = "condition:typed.restrained"
DIG = "system:combat.sand_dig_free"
GRIP = "TAL_SAND_THOUSAND_GRAIN_GRIP"
SAND = "tianxia.sphere.sand"
TOPIC = "sand_burial"
LABEL = "Buried: Speed -10 ft; Disadvantage on Dexterity saves against Sand pushes and Prone; Action: dig free (Athletics or Acrobatics)"


def buried(actor: Any) -> list[tuple[str, Any]]:
    """The Buried instances ``actor`` holds, as (instance id, condition)."""
    return [(key, condition) for key, condition in actor.conditions.items() if condition.condition_id == BURIED]


def _sand_effect(ctx: Any) -> bool:
    typed = ctx.typed or {}
    if typed.get("sphere") == SAND:
        return True
    action = ctx.engine.action_catalog.get(ctx.source)
    return action is not None and ((action.parameters or {}).get("typed") or {}).get("sphere") == SAND


@hook("condition_state")
def buried_state(ctx: Any, subject: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("sand_parent"):  # the Restrained of "Buried and Restrained" (sand_bury below): it lasts while that Buried does
        name = str(row.get("condition") or "restrained").replace("_", " ").title()
        return {"expires_on": "UNTIL_REMOVED", "data": {"parent_hold": str(row["sand_parent"]), "hold_kind": TOPIC,
                                                        "label": f"{name} while Buried (ends when the burial does)"}}
    if str(row.get("condition") or "").lower() != "buried" or row.get("parent_condition"):
        return None
    data = {"escape_dc": int(ctx.numbers.get("save_dc") or 10), "label": LABEL}
    move = (row.get("condition_data") or {}).get("escape_move")
    if move:
        data["escape_move"] = str(move)
    return {"data": data}


@hook("linked_hold_tracking")
def track_burial(engine: Any, actor: Any, topic: str) -> bool | None:
    return True if topic == TOPIC else None


@hook("speed")
def buried_speed(engine: Any, actor: Any) -> int | None:
    return -10 if buried(actor) else None


@hook("masked_conditions")
def sand_clings(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for who, other in ((target, attacker), (attacker, target)):
        if not buried(who) or any(c.condition_id == "condition:typed.blinded" for c in other.conditions.values()):
            continue
        rows = {key for key, condition in who.conditions.items() if condition.condition_id == "condition:typed.invisible"}
        if rows:
            out[who.entity_id] = rows
    return out or None


@hook("save")
def buried_dex_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability).upper() != "DEX" or not buried(subject) or not ({"prone", "forced_movement"} & set(named or ())):
        return None
    return {"modes": ["DISADVANTAGE"]} if _sand_effect(ctx) else None


@effect("sand_bury")
def sand_bury(ctx: Any, row: dict[str, Any]) -> None:
    """{"type": "sand_bury", "applies_to": "target", duration keys as a condition row, "condition_data": {...},
    "restrain": "always" | "if_already_buried" (optional), "only_in": ["deep" | "storming" | "shallow"] (optional)}.
    Buried on each subject through the ordinary condition row (immunity, condition reactions and plug-ins still apply).
    ``restrain`` adds a Restrained tied to that new Buried: "always" is "Buried and Restrained" (Burial of the Nameless
    Army); "if_already_buried" is "If already Buried, it is Buried and Restrained" (Devouring Dune Mouth, Quicksand Gate).
    ``with``: further conditions tied to that Buried along with the Restrained (Bury the Line's Blinded).
    ``only_in``: only a subject standing in Sand Terrain of that strength the user controls (Sand Drag: "If the movement
    ends in Deep Sand Terrain, the target is Buried until the start of your next turn"). A "concentration" duration lasts
    as long as the user's Concentration on this ability, also when a zone's trigger applies it."""
    from dataclasses import replace

    from ..typed_executor import _default_subject, block_condition
    from .sand_terrain import standing_in

    from .. import concentration

    base = {key: value for key, value in row.items() if key not in ("type", "restrain", "only_in", "with")}
    if effect_durations.kind_of(row.get("duration")) == "concentration" and not row.get("expires_on") and concentration.concentrating_on(ctx.actor, ctx.source):
        # A zone's own trigger runs with an instant duration; "while the effect lasts" is this copy's Concentration.
        base["expires_on"] = "CONCENTRATION_END"
    for subject in _default_subject(ctx, row, harmful=True):
        if not subject.active:
            continue
        if row.get("only_in") and not standing_in(ctx.engine, ctx.actor.entity_id, subject, set(row["only_in"])):
            continue
        before = {key for key, _condition in buried(subject)}
        one = replace(ctx, target=subject, targets=[subject])
        block_condition(one, {**base, "type": "condition", "condition": "buried", "applies_to": "target"})
        new = [key for key, _condition in buried(subject) if key not in before]
        if new and (row.get("restrain") == "always" or (row.get("restrain") == "if_already_buried" and before)):
            block_condition(one, {"type": "condition", "condition": "restrained", "applies_to": "target", "sand_parent": new[-1],
                                  "evidence": "Buried and Restrained"})
            for name in row.get("with") or []:  # "While restrained this way, it is also Blinded by sand" (Bury the Line)
                block_condition(one, {"type": "condition", "condition": str(name), "applies_to": "target", "sand_parent": new[-1],
                                      "evidence": f"{str(name).title()} while Buried"})


# ------------------------------------------------------------------------------------------------ digging free
@hook("match_start")
def dig_action(engine: Any) -> None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[DIG] = ActionDefinition(
        source_definition_id=DIG, display_name="Dig free of the sand", owner_id="*", economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF", parameters={
            "typed": {"effects": [{"type": "sand_dig_free"}], "numbers": {}, "duration": {"kind": "instant"}, "riders": []},
            "expected_damage": 0, "requires_condition": BURIED, "sand_dig_free": True,
            "description": "Buried: use your Action for a Strength (Athletics) or Dexterity (Acrobatics) check against the "
                           "DC of the Sand talent that buried you. On a success you are no longer Buried, and any Restrained "
                           "that came with that burial ends too."})


@hook("additional_actions")
def dig_offered(engine: Any, actor: Any) -> list[str]:
    return [DIG] if buried(actor) and DIG in engine.action_catalog else []


@hook("candidate_allowed")
def dig_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and (action.parameters or {}).get("sand_dig_free"):
        return bool(buried(actor))
    return None


def _grip_row(engine: Any, burier: Any) -> dict[str, Any] | None:
    from .. import typed_reactions as tr

    return next((row for row in tr._ordered_generic_rows(engine, burier.entity_id, "moved") if row.get("feature_id") == GRIP), None)


@hook("row_allowed")
def grip_not_on_bare_movement(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != GRIP or getattr(engine, "_sand_grip_offer", None):
        return None
    return False  # moving has no escape check or save for the Grip to worsen; it is offered on the escape check below


def _offer_grip(ctx: Any, burier: Any, checkpoint: str) -> tuple[dict[str, Any], Any] | None:
    """The accepted Grip and its transient owner receipt, else None."""
    from .. import typed_reactions as tr
    from ..paid_relocation import activation, capture

    row = _grip_row(ctx.engine, burier)
    if row is None or not burier.active or burier.entity_id == ctx.actor.entity_id:
        return None
    ctx.engine._sand_grip_offer = True
    try:
        if not tr._can_trigger(ctx.engine, burier, row) or not tr._generic_affordable(ctx.engine, burier, row):
            return None
        if not tr._consent(ctx.engine, row, burier, checkpoint, trigger={
                "actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id, "source_id": DIG}):
            return None
        # Opening rechecks row_allowed too; this is still the escape offer,
        # not the unrelated bare-movement trigger the hook suppresses.
        with activation(ctx.engine, burier, GRIP):
            tr._open(ctx.engine, row, burier, (ctx.actor.entity_id,), checkpoint)
            tr._spend_generic(ctx.engine, burier, row)
            if not row.get("free"):
                burier.reaction_available = False
            return row, capture(ctx.engine)
    finally:
        ctx.engine._sand_grip_offer = False


@hook("escape_mode")
def grip_disadvantage(engine: Any, escaper: Any, grips: Any) -> str | None:
    return "DISADVANTAGE" if escaper.entity_id in (getattr(engine, "_sand_grip_escape", None) or ()) else None


@effect("sand_dig_free")
def dig_free(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_reactions as tr
    from ..paid_relocation import causal_scope
    from ..typed_executor import run_effects
    from .escape_checks import resolve_escape_check
    from .needle import ask, checkpoint_id

    held = buried(ctx.actor)
    if not held:
        return
    names = {key: getattr(ctx.engine.action_catalog.get(c.source_definition_id), "display_name", "a Sand talent") for key, c in held}
    easiest = min(held, key=lambda pair: int(pair[1].data.get("escape_dc") or 10))
    chosen = [easiest[0]] if len(held) == 1 else ask(
        ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "sand_dig_free", ctx.actor.entity_id), ctx.actor,
        "choice:needle.sand_dig_free", [key for key, _c in held],
        labels={key: f"{names[key]} from {getattr(ctx.engine.state.actors.get(c.source_actor_id), 'display_name', 'another creature')} "
                     f"(escape DC {int(c.data.get('escape_dc') or 10)})" for key, c in held},
        preferred=[easiest[0]], name="Dig free of the sand",
        prompt=f"Dig free of the sand: {ctx.actor.display_name} is Buried more than once. Choose one burial to try to escape "
               "with this Action's Athletics or Acrobatics check. Success ends that burial and any Restrained or Blinded conditions caused by it; "
               "the other burials remain. No CP or Stamina cost.")
    key, condition = next(((k, c) for k, c in held if k in chosen), easiest)
    dc = int(condition.data.get("escape_dc") or 10)
    burier = ctx.engine.state.actors.get(condition.source_actor_id)
    offered = _offer_grip(ctx, burier, f"SAND_GRIP:{ctx.engine.state.event_sequence}:{ctx.actor.entity_id}") if burier is not None else None
    grip = offered[0] if offered is not None else None
    ctx.engine._sand_grip_escape = {ctx.actor.entity_id} if grip is not None else set()
    try:
        success = resolve_escape_check(ctx, {"bonus": escape_bonus(ctx.engine, ctx.actor)}, dc, [condition],
                                       ("restrained",), check_name="Dig free of the sand (Athletics or Acrobatics)")
    finally:
        ctx.engine._sand_grip_escape = set()
    if grip is not None:
        with causal_scope(ctx.engine, offered[1]):
            if not success:
                context = tr.triggered_context(ctx.engine, burier, ctx.actor, grip, ctx.intent)
                run_effects(context, [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["slashing"],
                                       "dice": {"count": 0, "sides": 0, "bonus_formula": "key_ability_modifier"},
                                       "evidence": "Thousand-Grain Grip: Slashing damage equal to your Proficiency Bonus + your key ability modifier"}])
            ctx.engine._append_event("REACTION_RESOLVED", GRIP, actor_id=burier.entity_id, target_ids=(ctx.actor.entity_id,),
                                     payload={"checkpoint": "SAND_ESCAPE", "escaped": success})
    if not success or key not in ctx.actor.conditions:
        return
    del ctx.actor.conditions[key]
    ctx.engine._append_event("CONDITION_REMOVED", ctx.source, actor_id=ctx.actor.entity_id, target_ids=(ctx.actor.entity_id,),
                             payload={"condition_id": BURIED, "instance_id": key})
    if condition.data.get("escape_move") == "half_speed" and ctx.actor.active:
        run_effects(ctx, [{"type": "movement", "applies_to": "self", "distance_ft": "half_speed"}])
