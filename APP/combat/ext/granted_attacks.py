"""Opt-in Granted Attack ancestry shared by all typed sources.

A granted_attack typed action or granted_attack_root effect opens a transient
ancestry frame through all its attacks and reactions. Attack-granting responses
require explicit allow_granted_followup=True on that responding source. An
ordinary action with neither marker is inert, regardless of roster ownership.
Frames restore on nested resolution, errors and choice pauses; nothing persists.
"""
from contextlib import contextmanager
from . import hook


def grants_attack(rows):
    return any(isinstance(row, dict) and (row.get("type") == "attack" or
        any(grants_attack(row.get(key) or []) for key in ("effects", "on_hit", "on_miss", "on_fail", "on_success")))
        for row in rows)


@hook("row_allowed")
def response_allowed(engine, actor, row):
    if not engine.__dict__.get("_granted_attack_ancestry"):
        return None
    # Permission belongs to this response's source, never another actor's row.
    if row.get("allow_granted_followup") is True:
        return None
    if grants_attack(row.get("effects") or []):
        return False
    return None


@hook("effect_resolution_scope")
def granted_scope(ctx, effect):
    if effect.get("type") != "attack" or not (ctx.typed.get("granted_attack") or effect.get("granted_attack_root")):
        return None
    @contextmanager
    def scope():
        engine = ctx.engine
        previous = engine.__dict__.get("_granted_attack_ancestry", ())
        typed = ctx.typed
        ctx.typed = {**typed, "granted_attack": True}
        engine.__dict__["_granted_attack_ancestry"] = (*previous, (ctx.actor.entity_id, ctx.source))
        try:
            yield
        finally:
            ctx.typed = typed
            if previous:
                engine.__dict__["_granted_attack_ancestry"] = previous
            else:
                engine.__dict__.pop("_granted_attack_ancestry", None)
    return scope()


def prepare(ctx, effect):
    """Consume source permission at admission; a nested root marker grants no override."""
    from dataclasses import replace
    ancestry = ctx.engine.__dict__.get("_granted_attack_ancestry")
    if not ancestry:
        if "allow_granted_followup" not in ctx.typed:
            return ctx, effect
        typed = dict(ctx.typed)
        typed.pop("allow_granted_followup", None)
        return replace(ctx, typed=typed), effect
    typed = dict(ctx.typed)
    permitted = typed.pop("allow_granted_followup", False) is True or effect.get("allow_granted_followup") is True
    typed["granted_attack"] = True
    effect = dict(effect)
    effect.pop("allow_granted_followup", None)
    if permitted:
        effect["granted_attack_root"] = True
    else:
        effect.pop("granted_attack_root", None)
    return replace(ctx, typed=typed), effect


def allows_root(engine, *, permission=False):
    """Pure pre-payment query for an original or explicitly permitted root.

    Permission belongs to the source's actual printed exception. This query
    creates no frame, activation or permission and does not consume the opt-in;
    prepare still enforces admission during actual attack resolution.
    """
    if type(permission) is not bool:
        raise ValueError('Granted follow-up permission must be an explicit boolean')
    return not engine.__dict__.get('_granted_attack_ancestry') or permission


def depth(engine):
    """Current transient Granted Attack ancestry depth, for completion consumers."""
    return len(engine.__dict__.get('_granted_attack_ancestry',()))
