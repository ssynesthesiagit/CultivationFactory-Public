"""Ink Lash's printed declaration choice and native map-object delivery.

Only the owned base row opts in. The existing objects provider rolls attacks,
CL-scaled damage, criticals and object defenses; this module does not duplicate
that implementation. AI uses the first printed type, without inspecting private
defenses. Cosmetic brush shapes and discretionary writing are not damage rules.
"""
from __future__ import annotations

from . import effect, hook

LASH = "INK_BASE_INK_LASH"
CHOICE = "ink_lash_declaration"


@hook("compile_action")
def lash_declaration(action, info):
    typed = (action.parameters or {}).get("typed") or {}
    if LASH not in info["owned_ids"] or typed.get("source") != LASH:
        return None
    effects = list(typed.get("effects") or [])
    if not any(row.get("type") == CHOICE for row in effects):
        effects.insert(0, {"type": CHOICE})
    return action.model_copy(update={"parameters": {
        **action.parameters, "typed": {**typed, "effects": effects},
    }})


@effect(CHOICE, harmful=False)
def declare_lash(ctx, row):
    """Ask before either the creature or object attack roll, including misses."""
    if ctx.typed.get("source") != LASH:
        return
    from .needle import ask
    from .. import object_rules

    obj = ctx.damage_cache.get("_object")
    affected = object_rules.label(obj) if obj is not None else ", ".join(t.display_name for t in ctx.targets)
    chosen = ask(ctx.engine, ctx.intent, "TECHNIQUE_USE", ctx.actor,
        "choice:needle.ink_lash_damage", ["SLASHING", "PSYCHIC"],
        labels={"SLASHING": "Slashing damage", "PSYCHIC": "Psychic damage"},
        preferred=["SLASHING"], name="Ink Lash", feature_id=LASH,
        target_id=obj.object_id if obj is not None else (ctx.targets[0].entity_id if ctx.targets else None),
        prompt=f"Ink Lash: choose Slashing or Psychic damage for your ranged Cultivation Attack against {affected}. "
               "This uses your Action, costs no Cultivation Points, and deals damage only on a hit. "
               "The GM decides any cutting, staining, writing or weakening of unattended objects; this does not automatically open locks or disintegrate objects.")
    ctx.damage_cache[CHOICE] = chosen[0] if chosen else "SLASHING"


@hook("damage_type_override")
def declared_type(ctx, kinds, targets):
    # Additional fixed-type packets keep their own printed type. This owns
    # only Lash's two-type choice, not every damage row in its activation.
    if ctx.typed.get("source") == LASH and set(kinds) == {"SLASHING", "PSYCHIC"}:
        return ctx.damage_cache.get(CHOICE)
    return None
