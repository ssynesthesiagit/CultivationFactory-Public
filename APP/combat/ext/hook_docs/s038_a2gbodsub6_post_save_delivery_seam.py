"""A2GBODSUB6 post-save delivery seam:
save_effects_settled(ctx, subject, ability, failed) -> None. Strict, after the
selected save outcome's effects (including Evasion) have actually applied.
ctx.origin_save records the selecting ability/DC; ctx.failed_save is its final
outcome. Subscribers may ask for choices and persist records for effects that
landed; canceled saves never invoke it. No subscribers is inert.
damage_type_choice may receive an empty target list for an object-only area.
Absent a choice provider, empty-target damage keeps the historical first type.
"""
