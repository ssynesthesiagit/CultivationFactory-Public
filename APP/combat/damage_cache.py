"""Activation-local identity keys shared by damage rolls and their combat extensions.

Used by typed_executor, stars_insights, zz_dual_wielding and daemonic_augment.
"""


def effect_cache_key(cache, effect, *, namespace=None):
    """Return a stable effect key, retaining identity-keyed rows for the cache lifetime."""
    group = effect.get("damage_bonus_group") if namespace is None else None
    if group:
        return f"damage_bonus_roll:{group}"
    identity = id(effect)
    cache.setdefault(("effect_identity_refs",), {})[identity] = effect
    return (namespace, identity) if namespace is not None else identity
