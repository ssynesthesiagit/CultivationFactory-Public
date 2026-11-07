"""Optional reviewed melee hit riders, compiled by the generic core modifier pass.

Uses Needle's public transactional choice transport. No catalog metadata means
no change, including old sealed fights. Payment and effects belong to one hit.

Shared helpers used by attack_modifiers: effect_text(effects) formats reviewed
player text, and apply_paid_effects(ctx, target, source, costs, effects) spends one
payment and runs its effects on the hit target. Both callers own eligibility,
affordability and player consent before calling this activation executor.
"""
from typing import Any

from . import hook
from .needle import ask, checkpoint_id


def effect_text(effects: list[dict[str, Any]]) -> str:
    """Describe nested effects and saves, allowing a plug-in's complete text."""
    from . import run
    lines = []
    for effect in effects:
        # Some effect types (end_effect) carry on_success as a plain string such
        # as "suppress", so only dicts are effect rows and only lists nest.
        if not isinstance(effect, dict):
            continue
        replacement = [text for text in run("effect_player_text", effect) if text]
        if replacement:
            lines.extend(replacement)
            continue  # the public hook describes this entire subtree
        if effect.get("evidence"):
            from ..player_text import plain
            lines.append(plain(effect["evidence"]))
        if isinstance(effect.get("effects"), list):
            lines.append(effect_text(effect["effects"]))
        for branch, prefix in (("on_fail", "Failed save: "), ("on_success", "Successful save: ")):
            nested = effect.get(branch)
            if isinstance(nested, list) and nested:
                lines.append(prefix + effect_text(nested))
    return " ".join(lines)


def apply_paid_effects(ctx: Any, target: Any, source: str, costs: list, effects: list) -> None:
    """Shared activation executor for paid_hit and attack_modifiers loadouts.

    Callers own choice, affordability and eligibility. One payment belongs to
    one confirmed hit. The child names the selected rider via effect_source;
    the triggering attack and parent context stay unchanged. Only named hit
    metadata survives between activations.
    """
    for resource, amount in costs:
        ctx.engine._spend_resource(ctx.actor, resource, amount, source)
    from ..typed_executor import run_effects
    hit_cache = {key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)}
    run_effects(ctx.on_hit_context(target, damage_cache=hit_cache, effect_source=source), effects)
    ctx.damage_cache.update({key: value for key, value in hit_cache.items() if isinstance(key, str)})
    from . import run_strict
    run_strict("paid_hit_applied", ctx, target, source)


@hook("after_hit_choice")
def paid_hit(ctx: Any, target: Any, kind: str, *, confirmed=False):
    if not confirmed and getattr(ctx, "attack_damage_context", None) is not None:
        target = ctx.engine.state.actors[ctx.attack_damage_context.target_id]
    if kind != "weapon" or not target.active:
        return
    owners = {row.get("feature_id") for row in
              (getattr(ctx.engine, "typed_passive_rows", {}) or {}).get(ctx.actor.entity_id, [])
              if row.get("block") == "paid_hit" and row.get("choice_owner")}
    if not owners:
        return
    from .roll_modifiers import is_roll_modifier, fold_confirmed_rows
    held = ctx.damage_cache.setdefault("_paid_hit_roll_choices", {})
    total = 0
    if not confirmed:
        for source, effects in list(held.items()):
            if effects:
                apply_paid_effects(ctx, target, source, [], effects)
            held[source] = []
    for choice in ctx.typed.get("paid_hit_choices") or []:
        if choice["id"] not in owners:
            continue
        if choice["id"] in held:
            continue
        if confirmed:
            if not any(is_roll_modifier(row) for option in choice["options"] for row in option["effects"]):
                continue
            held[choice["id"]] = []
        from .attack_modifiers import automatic, chosen, family
        if not automatic(ctx.engine, ctx.actor) and chosen(ctx.actor, family(ctx), choice["id"]).get("family"):
            continue  # the persistent player row owns this decision now
        options = [option for option in choice["options"] if all(
            ctx.actor.resources.get(resource, 0) >= amount for resource, amount in option["costs"])]
        if not options:
            continue
        labels = {}
        for option in options:
            price = ", ".join(f"{amount} {resource.rsplit('.', 1)[-1].replace('_', ' ').title()}"
                              for resource, amount in option["costs"])
            labels[option["id"]] = f"{option['label']} (pay {price} for this hit). {effect_text(option['effects'])}"
        picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "paid_hit", choice["id"], target.entity_id),
            ctx.actor, "choice:needle.paid_hit", list(labels), labels=labels, allow_decline=True,
            target_id=target.entity_id, name=choice["name"], feature_id=choice["id"],
            prompt=f"{choice['name']}: {ctx.action.display_name} hit {target.display_name}. "
                   "Choose an effect and pay its listed cost for this hit, or decline to keep the ordinary hit. "
                   "You pay separately for each hit; conditions last for the duration shown in the option. "
                   "Later attacks continue normally.")
        selected = next((option for option in options if option["id"] in picked), None)
        if selected is None:
            continue
        if confirmed:
            total += fold_confirmed_rows(ctx, target, [row for row in selected["effects"] if is_roll_modifier(row)])
            for resource, amount in selected["costs"]:
                ctx.engine._spend_resource(ctx.actor, resource, amount, choice["id"])
            held[choice["id"]] = [row for row in selected["effects"] if not is_roll_modifier(row)]
        else:
            apply_paid_effects(ctx, target, choice["id"], selected["costs"], selected["effects"])
    return total


@hook("confirmed_hit_roll_bonus")
def confirmed_paid_roll(engine, attacker, target, spec, intent, source):
    """Unconfigured and automatic paid-hit menus retain one-roll delivery too."""
    frame = getattr(engine, "_typed_critical_scope", None)
    if not frame or frame[0].actor is not attacker or frame[0].source != source:
        return None
    ctx = frame[0]
    ctx.damage_cache["_paid_hit_roll_choices"] = {}
    kind = "weapon" if ctx.typed.get("weapon") is not None else "other"
    return paid_hit(ctx, target, kind, confirmed=True)
