"""Delayed breakage shared by shield_uncbroken and shield_incarnation.

Called only from transactional expiry: remove the due protection before typed
prevention so it cannot suppress its own deadline. Exclude that rescue's provider
for this attempt, while retaining every other condition prevention and immunity.
No transient exclusion is stored in fight state.
"""
from typing import Any


def resume(engine: Any, holder: Any, condition: Any, feature: str) -> None:
    """End this protection and reattempt its postponed break with other rescues."""
    from ..typed_executor import run_effects
    from ..typed_reactions import triggered_context

    engine._remove_condition(holder, condition.condition_id, feature)
    ctx = triggered_context(engine, holder, holder,
                            {'feature_id': feature, 'name': 'Delayed Shield breakage',
                             'effects': [], 'numbers': {}},
                            getattr(engine, '_active_intent', None))
    run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken',
                      'applies_to': 'self', 'expires_on': 'UNTIL_REMOVED',
                      'shield_rescue_excluded': feature,
                      'shield_breakage_trigger': f"At the end of {holder.display_name}'s turn, their Shield's temporary protection ends and it would break",
                      'condition_data': {'label': 'Shield broken: its Armor Class bonus and Shield talents are unavailable'}}])
