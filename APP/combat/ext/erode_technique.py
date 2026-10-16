"""Erode Technique answers the particular ordinary benefit being granted.

Uses reaction_rows to retain the owned row's consent, payment and activation;
healing_pending owns Temporary HP, event owns exact temporary modifier/condition
receipts. No HP-healing listener and no scan of unrelated existing benefits.
"""
from copy import deepcopy
from . import effect, hook

ERODE = "TAL_VOID_ERODE_TECHNIQUE"
FIELDS = {"armor_class": 1, "armor_class_vs_melee": 1, "armor_class_vs_ranged": 1,
          "speed_ft": 10, "damage_reduction": "pb", "damage_resistance": "suppress",
          "cost_reduction": "suppress"}


@hook("reaction_rows")
def rows(engine, actor_id, block, rows):
    if block != "generic" or not any(r.get("feature_id") == ERODE for r in rows):
        return None
    pending = getattr(engine, "_pending_healing", None)
    benefit = getattr(engine, "_gained_temporary_benefit", None)
    out = []
    for row in rows:
        if row.get("feature_id") != ERODE:
            out.append(row)
            continue
        if row.get("kind") == "temp_hp_gained" and pending and pending["kind"] == "temp_hp":
            effects = [{"type": "pending_healing_reduction", "formula": "pb",
                        "evidence": "reduce Temporary HP gained by your Proficiency Bonus"}]
        elif row.get("kind") == "benefit_gained" and benefit:
            effects = [{"type": "erode_gained_benefit", "applies_to": "target"}]
        else:
            continue
        made = deepcopy(row)
        made["effects"] = effects
        # One receipt offers exactly its applicable printed option. The other
        # options cannot affect this benefit (e.g. Invisible is not temp HP).
        for key in ("reaction_modes", "option_labels", "option"):
            made.pop(key, None)
        out.append(made)
    return out


@hook("event")
def gained(engine, event_type, kwargs):
    if event_type not in {"MODIFIER_APPLIED", "CONDITION_APPLIED"}:
        return
    if not any(r.get("feature_id") == ERODE for rows in getattr(engine, "typed_reaction_rows", {}).values() for r in rows):
        return
    payload = kwargs.get("payload") or {}
    target = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), ""))
    if target is None:
        return
    kind = "modifier" if event_type == "MODIFIER_APPLIED" else "condition"
    key = payload.get("modifier_id" if kind == "modifier" else "instance_id")
    held = (target.modifiers if kind == "modifier" else target.conditions).get(key)
    if held is None or held.expires_on in {None, "", "UNTIL_REMOVED"}:
        return
    if kind == "modifier":
        if held.target_field not in FIELDS or (isinstance(held.value, int) and held.value <= 0):
            return
    elif held.condition_id != "condition:typed.invisible":
        return
    action = engine.action_catalog.get(held.source_definition_id)
    typed = (action.parameters.get("typed") or {}) if action else {}
    if typed.get("domain") or typed.get("protected") or typed.get("artifact") or typed.get("secret_inheritance"):
        return
    previous = getattr(engine, "_gained_temporary_benefit", None)
    engine._gained_temporary_benefit = (target.entity_id, kind, key)
    try:
        from ..typed_reactions import on_creature_event
        on_creature_event(engine, target, "benefit_gained", source_id=held.source_definition_id)
    finally:
        engine._gained_temporary_benefit = previous


@effect("erode_gained_benefit", harmful=True)
def reduce_benefit(ctx, eff):
    receipt = getattr(ctx.engine, "_gained_temporary_benefit", None)
    if not receipt or ctx.target is None or receipt[0] != ctx.target.entity_id:
        return
    _, kind, key = receipt
    target = ctx.target
    held = (target.modifiers if kind == "modifier" else target.conditions).get(key)
    if held is None:
        return
    from .benefit_suppression import suppress
    value = held.value if kind == "modifier" else None
    field = held.target_field if kind == "modifier" else None
    if not suppress(ctx.engine, ctx.actor, target, kind + ":" + key, "owner_turn", ctx.source,
                    label="Erode Technique: this temporary benefit is reduced until the start of the user's next turn"):
        return
    reduction = FIELDS.get(field)
    if kind == "modifier" and isinstance(value, int) and reduction != "suppress":
        amount = int(ctx.numbers.get("pb") or 0) if reduction == "pb" else int(reduction)
        left = max(0, value - amount)
        if left:
            ctx.engine._add_modifier(target, ctx.source, field, held.operation, left, held.applies_to,
                                     expires_on="START_OF_SOURCE_NEXT_TURN", source_actor_id=ctx.actor.entity_id,
                                     application_id="erode:" + key)


def expire_replacements(engine):
    """A reduced replacement cannot outlive the original hidden benefit."""
    from .benefit_suppression import SUPPRESSED
    from .suppressed_effects import alive
    for holder in engine.state.actors.values():
        hidden = {(c.data.get("model") or {}).get("modifier_id") for c in holder.conditions.values()
                  if c.condition_id == SUPPRESSED and c.source_definition_id == ERODE
                  and alive(engine, c.data.get("lifetime") or {})}
        for mid, modifier in list(holder.modifiers.items()):
            application = modifier.application_id or ""
            if (modifier.source_definition_id == ERODE and application.startswith("erode:")
                    and application.removeprefix("erode:") not in hidden):
                engine._remove_modifier_instance(holder, mid, ERODE,
                                                 payload={"modifier_id": mid, "reason": "DURATION_ENDED"})


@hook("turn_start")
def turn_start(engine, actor):
    expire_replacements(engine)


@hook("turn_end")
def turn_end(engine, actor, *, nominal=False):
    expire_replacements(engine)
