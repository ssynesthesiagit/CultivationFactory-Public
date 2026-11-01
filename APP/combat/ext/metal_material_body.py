"""Metal's finite scrap and Ninefold Body on existing effect/choice/hit seams.

Equipment may declare metal_scrap_pouches (a nonnegative integer), each a
modest pouch of actual needles, coins or filings meeting Hundred Needles Fan's
printed material requirement. No declaration grants no material. Compilation
seals this finite stock as a resource; scattering spends it before the save,
and adds PB to the same damage packet (so success halves the bonus too).

Ninefold Body has an evented timed benefit, not an always-on Sharpen
modifier and an unexecuted deferred retaliation row. Its ordinary rule grants
defenses and hit_snapshot/hit_final deliver the optional paid melee Reaction.
A separate pressure deadline survives suppression of the benefit: at the
original duration's end effect_expiring_choice resolves payment or Exhaustion.
No new hooks or saved-fight fields; all choices use the native transport.
"""
from copy import deepcopy

from . import effect, hook

FAN = "TAL_METAL_HUNDRED_NEEDLES_FAN"
BODY = "TAL_METAL_NINEFOLD_ADAMANT_BODY"
STOCK = "resource:named.metal_scrap_pouches"
STATE = "condition:typed.ninefold_adamant_body"
PRESSURE = "condition:typed.ninefold_adamant_pressure"


def _state(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE), None)


@hook("status_description")
def body_description(engine, holder, row, data):
    cid = row.get("condition_id")
    if cid == STATE:
        return {"text": "Ninefold Adamant Body lasts 1 minute and costs 8 cultivation points to activate. "
                "You take half Bludgeoning, Piercing and Slashing damage, have Advantage on Strength and "
                "Constitution saves, and Sharpen deals twice your Proficiency Bonus. When a melee attack "
                "hits you, you may spend your Reaction to deal Piercing damage equal to your Proficiency "
                "Bonus plus your Metal key ability modifier to the attacker.",
                "handling": "The table applies these benefits and asks before the optional Reaction."}
    if cid == PRESSURE:
        return {"text": "When Ninefold Adamant Body's original minute ends, spend 2 cultivation points "
                "or Stamina, or gain one level of Exhaustion. Suppressing the body's benefits does not "
                "remove this pressure. No action or Reaction is needed.",
                "handling": "The table asks before payment; if you decline or cannot pay, it adds Exhaustion."}
    return None


@hook("compile_resources")
def scrap_stock(info):
    if FAN not in info["owned_ids"]:
        return None
    count = 0
    for entry in (info.get("owner_sheet") or {}).get("equipment") or []:
        if not isinstance(entry, dict) or "metal_scrap_pouches" not in entry:
            continue
        amount = entry["metal_scrap_pouches"]
        if type(amount) is not int or amount < 0:
            raise ValueError("Metal scrap pouches must be a nonnegative integer")
        count += amount
    if not count:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    return [ResourceDefinition(resource_id=STOCK, initial=count, maximum=count)]


@effect("metal_fan")
def scatter_fan(ctx, row):
    from .needle import CHOICE, ask, checkpoint_id
    from ..typed_executor import run_effects

    scatter = False
    if ctx.actor.resources.get(STOCK, 0) > 0:
        scatter = bool(ask(ctx.engine, ctx.intent,
            checkpoint_id(ctx.engine, "metal_fan_scrap", ctx.actor.entity_id), ctx.actor,
            CHOICE + "metal_fan_scrap", ["scatter"], allow_decline=True,
            name="Hundred Needles Fan", feature_id=FAN,
            labels={"scatter": "Scatter one pouch of metal scrap: add Proficiency Bonus to the damage"},
            prompt=f"Hundred Needles Fan: scatter one carried pouch of needles, coins or filings? "
                   f"Add {int(ctx.numbers['pb'])} Piercing damage before any successful save halves it. "
                   "The pouch is consumed and cannot be reused this scene; no additional action or cultivation cost."))
    rows = deepcopy(row["effects"])
    if scatter:
        ctx.engine._spend_resource(ctx.actor, STOCK, 1, ctx.source)
        for save in rows:
            for damage in save.get("on_fail") or []:
                if damage.get("type") == "damage":
                    damage["flat"] = int(damage.get("flat") or 0) + int(ctx.numbers["pb"])
    run_effects(ctx, rows)


@effect("metal_ninefold_body")
def enter_body(ctx, row):
    from ..typed_executor import effect_expiry

    previous = next((c for c in ctx.actor.conditions.values() if c.condition_id == PRESSURE), None)
    if previous is not None:
        # Replacing a duration ends that activation; refreshing cannot evade its cost.
        vent_body(ctx.engine, ctx.actor, previous)
        ctx.engine._remove_condition(ctx.actor, PRESSURE, previous.source_definition_id)
    from .benefit_suppression import consume_suppressed_conditions
    consume_suppressed_conditions(ctx.engine, ctx.actor, STATE)
    for old in list(ctx.actor.conditions.values()):
        if old.condition_id in (STATE, "condition:typed.suppressed.ninefold_adamant_body"):
            ctx.engine._remove_condition(ctx.actor, old.condition_id, old.source_definition_id)
    expiry = effect_expiry(ctx, {"duration": "one_minute"}, ctx.actor, condition=True)
    ctx.engine._apply_condition(ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
        expires_on=expiry,
        data={"label": "Ninefold Adamant Body", "numbers": dict(ctx.numbers), "temporary_benefit": 1,
              "rule": {"damage_resistances": ["bludgeoning", "piercing", "slashing"],
                       "save_mode": {"STR": "ADVANTAGE", "CON": "ADVANTAGE"}}})
    ctx.engine._apply_condition(ctx.actor, PRESSURE, ctx.source, ctx.actor.entity_id,
        expires_on=expiry, data={"label": "Ninefold Adamant Body: vent pressure when its minute ends"})


@hook("choice_reactors")
def body_choices(engine):
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if any(c.condition_id == PRESSURE for c in a.conditions.values()))


@hook("effect_expiring_choice")
def vent_body(engine, holder, condition):
    if getattr(condition, "condition_id", None) != PRESSURE:
        return
    from .cp_pools import all_of
    from .forged_exhaustion import add
    from .needle import CHOICE, ask, checkpoint_id

    pools = [pool for pool in all_of(holder) if holder.resources.get(pool, 0) >= 2]
    # CP can be any actual Path pool; Stamina is also explicitly legal.
    selected = ask(engine, getattr(engine, "_active_intent", None),
        checkpoint_id(engine, "ninefold_vent", holder.entity_id, condition.instance_id),
        holder, CHOICE + "ninefold_vent", pools, allow_decline=True,
        name="Ninefold Adamant Body", feature_id=BODY, target_id=holder.entity_id,
        labels={pool: "Spend 2 " + pool.rsplit(".", 1)[-1].title() + " to prevent Exhaustion" for pool in pools},
        prompt=f"Ninefold Adamant Body ends for {holder.display_name}. Spend 2 cultivation points "
               "or Stamina to vent the pressure, or gain one level of Exhaustion. No action or Reaction.")
    if selected:
        engine._spend_resource(holder, selected[0], 2, condition.source_definition_id)
    else:
        add(engine, holder, 1, condition.source_definition_id)


@hook("deal_bonus")
def body_sharpen(ctx, subject, amount):
    # Sharpen is fixed damage, not a die roll. Its source attribution survives
    # normal modifier delivery and the Domain's additional base expression.
    state = _state(ctx.actor)
    if state is not None and ctx.source == "passive:METAL_BASE_SHARPEN":
        return int(state.data["numbers"]["pb"])
    return None


@hook("hit_snapshot")
def body_hit(engine, attacker, target, attack_context, intent):
    state = _state(target)
    if state is None:
        return None
    # Snapshot before damage; the settled Context supplies exact delivery below.
    return {"metal_ninefold": {"source": state.source_definition_id,
                              "numbers": dict(state.data["numbers"])}}


@hook("hit_final")
def body_counter(ctx, target, kind):
    receipt = ctx.hit_snapshots.get("metal_ninefold")
    if receipt is None:
        return
    from ..attack_delivery import is_ranged
    notice = ctx.attack_notice
    if notice is not None:
        melee = notice.melee
    else:
        profile = (ctx.attack_effect or {}).get("attack_kind")
        melee = bool(profile) and not is_ranged(profile, ctx.typed.get("range_ft"), ctx.typed.get("weapon"))
    if not melee:
        return
    from ..typed_reactions import can_use_reaction, open_reaction
    from ..typed_executor import Context, run_effects
    from .needle import CHOICE, ask, checkpoint_id

    row = {"feature_id": BODY, "name": "Ninefold Adamant Body", "block": "metal_ninefold"}
    if not can_use_reaction(ctx.engine, target, ctx.actor, row):
        return
    numbers = receipt["numbers"]
    amount = int(numbers["pb"]) + int(numbers["key_mod"])
    selected = ask(ctx.engine, ctx.intent,
        checkpoint_id(ctx.engine, "ninefold_counter", target.entity_id, ctx.actor.entity_id),
        target, CHOICE + "ninefold_counter", ["counter"], allow_decline=True,
        name="Ninefold Adamant Body", feature_id=BODY, target_id=ctx.actor.entity_id,
        labels={"counter": f"Use your Reaction: deal {amount} Piercing damage to {ctx.actor.display_name}"},
        prompt=f"Ninefold Adamant Body: {ctx.actor.display_name} hit {target.display_name} with "
               f"{ctx.action.display_name}, a melee attack. Use your Reaction to deal {amount} Piercing "
               "damage to the attacker? No cultivation cost.",
        automatic=ctx.actor.team_id != target.team_id)
    if not selected:
        return
    open_reaction(ctx.engine, row, target, (ctx.actor.entity_id,), "NINEFOLD_COUNTER")
    action = ctx.engine.action_catalog[receipt["source"]]
    inner = Context(ctx.engine, target, action, ctx.intent,
                    {"source": BODY, "numbers": numbers}, [ctx.actor], ctx.actor, {})
    run_effects(inner, [{"type": "damage", "flat": amount, "damage_types": ["piercing"],
                         "applies_to": "target"}])
