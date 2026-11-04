"""Built-in AI difficulty; character defaults and per-fight overrides.

Mastermind deliberately uses Tricky until phase 2 supplies its planner.
These are preferences, not combat rules or permissions.
"""
TIERS = ("TRICKY", "MASTERMIND")


def tier_for_power_band(power_band):
    return "MASTERMIND" if str(power_band or "").strip().lower() == "rival/boss" else "TRICKY"


def tier_for_sheet(sheet):
    """Creation locks are retained in the portable owner sheet."""
    band = sheet.get("power_band") or (sheet.get("identity") or {}).get("power_band")
    for row in (sheet.get("advancement_history") or {}).get("all_owner_locks") or ():
        if row.get("field") == "power_band":
            band = row.get("value")
    return tier_for_power_band(band)


def effective_tier(actor, overrides=None):
    value = (overrides or {}).get(actor.entity_id) or actor.ai_tier
    return value if value in TIERS else "TRICKY"


def tier_label(tier):
    return "AI: Mastermind" if tier == "MASTERMIND" else "AI: Tricky"
