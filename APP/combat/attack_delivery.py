"""Shared classification for a strike's melee or ranged delivery profile."""


def is_ranged(profile, range_ft=None, weapon=None):
    """Return whether a strike uses ranged-attack rules.

    The printed attack profile takes precedence over target-selection range:
    unarmed and melee weapon strikes can still have a numeric reach. Generic
    ``weapon`` profiles use the per-variant ``weapon.attack_delivery`` value
    from the compiler when available; this distinguishes a melee weapon's
    ordinary strike from its thrown variant. Older sealed profiles may use
    ``kind``/``attack_kind`` and otherwise default to melee. Open-ended profiles
    retain their numeric-range fallback.
    """
    kind = str(profile or "").strip().lower().replace("-", "_").replace(" ", "_")
    if kind.endswith("ranged") or kind == "ranged":
        return True
    if (kind.endswith("melee") or kind in {"melee", "unarmed", "weapon", "melee_weapon"}
            or kind.endswith("_unarmed")):
        if kind == "weapon" and isinstance(weapon, dict):
            # Compiled attacks carry this explicit delivery because a weapon's
            # equipment kind (bow, dagger, etc.) does not identify the selected
            # variant: a thrown dagger has both melee and ranged attacks.
            weapon_kind = str(weapon.get("attack_delivery") or weapon.get("kind") or weapon.get("attack_kind") or "").lower()
            return weapon_kind in {"ranged", "weapon_ranged"}
        return False
    return range_ft is not None and int(range_ft or 0) > 5
