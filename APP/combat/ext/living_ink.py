"""Living Ink's native unused supply and action-integrated medium.

Uses existing compile_passives/compile_actions, effect, technique_start and
technique_used hooks. Only the exact base owner opts in. Supply is a personal
condition, never a transferable or saleable inventory commodity. This does not
create writing artifacts or infer observers, concealment, or scene facts.
"""
from . import effect, hook

BASE = "INK_BASE_LIVING_INK"
SUPPLY = "condition:typed.living_ink_supply"
ORIGINS = ("fingertips", "brush", "weapon", "mouth", "blood", "sleeve", "shadow", "focus")


@hook("compile_passives")
def ownership(passives, info):
    if BASE not in info["owned_ids"]:
        return passives
    return [*passives, {"block": "living_ink", "feature_id": BASE}]


def owns(engine, actor):
    return any(r.get("block") == "living_ink" and r.get("feature_id") == BASE
               for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ()))


def supply(actor):
    """Find this owner's supply by condition identity, not storage instance id."""
    return next((c for c in actor.conditions.values()
                 if c.condition_id == SUPPLY and c.source_actor_id == actor.entity_id), None)


@hook("compile_actions")
def supply_action(info):
    if BASE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.living_ink.supply",
        display_name="Living Ink: conjure a supply", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        costs=(), parameters={"typed": {
            "source": BASE, "numbers": info["numbers"], "riders": [],
            "effects": [{"type": "living_ink_supply"}],
        }, "description": "Conjure your own Living Ink, with no action or resource cost. "
            "Unused ink fades after 1 hour and cannot be sold as ordinary ink. "
            "Ink techniques also provide their ink as part of their own action."})]


def conjure(engine, actor, source, intent, *, choose_origin=True):
    from .needle import ask
    origin = "fingertips"
    if choose_origin:
        picked = ask(engine, intent, "TECHNIQUE_USE", actor, "choice:needle.living_ink_origin", list(ORIGINS),
            labels={key: key.title() for key in ORIGINS}, name="Living Ink", feature_id=BASE,
            target_id=actor.entity_id,
            prompt=f"Living Ink: {actor.display_name} conjures a personal supply. Choose where the ink appears. "
                "No extra action or resource cost; unused ink fades after 1 hour and cannot be sold as ordinary ink.")
        if not picked:
            return
        origin = picked[0]
    # Native slot clock: one hour = 600 rounds. Only flat int/string data is
    # persisted; producing more ink replaces the previous sufficient supply.
    expires = f"START_OF_SLOT_AT:{engine.state.round_number + 600}:{engine.state.current_slot_index}"
    if supply(actor) is not None:
        engine._remove_condition(actor, SUPPLY, BASE)
    engine._apply_condition(actor, SUPPLY, source, actor.entity_id, expires_on=expires,
        data={"origin": origin, "label": f"Living Ink from {origin}: personal supply; unused ink fades in 1 hour; cannot be sold as ordinary ink"})


@effect("living_ink_supply", harmful=False)
def produce(ctx, row):
    if owns(ctx.engine, ctx.actor) and ctx.typed.get("source") == BASE:
        conjure(ctx.engine, ctx.actor, ctx.source, ctx.intent)


def ink_technique(action):
    typed = (action.parameters or {}).get("typed") or {}
    return typed.get("sphere") == "tianxia.sphere.ink" and typed.get("source") != BASE


@hook("technique_start")
def provide_medium(engine, actor, action):
    if owns(engine, actor) and ink_technique(action) and supply(actor) is None:
        # Appearance is optional flavor, not a new mandatory decision before
        # every attack/save. The free supply action exposes every printed
        # origin when the owner wants one; techniques otherwise use fingertips.
        conjure(engine, actor, action.source_definition_id, getattr(engine, "_active_intent", None), choose_origin=False)


@hook("technique_used")
def use_medium(ctx):
    if owns(ctx.engine, ctx.actor) and ink_technique(ctx.action) and supply(ctx.actor) is not None:
        ctx.engine._remove_condition(ctx.actor, SUPPLY, BASE)
