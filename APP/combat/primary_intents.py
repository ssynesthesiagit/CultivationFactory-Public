"""Primary turn eligibility shared by compilation and Gate2 candidate validation.

NONE is not an activation permission. Builders declare genuinely free turn
actions with ``parameters['free_primary'] = True``; storage-only selectors use
the existing setting_only contract and keep their parent/sheet picker route.
Trigger and rider handlers resolve their effects independently of this gate.
"""

from .gate2_runtime_models import EconomyKind
from .ext.setting_choices import is_setting_action


def allows_primary(action):
    """Accept paid turn actions, explicit free actions, and storage-only picks."""
    if action.economy in (EconomyKind.ACTION, EconomyKind.BONUS_ACTION):
        return True
    return action.economy == EconomyKind.NONE and (
        is_setting_action(action) or action.parameters.get('free_primary') is True)


def declare_free(actions):
    """Seal a builder's intentional free activations, preserving safe selectors.

    Used by the compiler's documented plug-in action builders. Their explicit
    NONE declarations are free activations; generated option rows never pass
    through this seam. Builders must use setting_only for future preferences.
    """
    return [action.model_copy(update={'parameters': {**action.parameters, 'free_primary': True}})
            if action.economy == EconomyKind.NONE and not is_setting_action(action)
            else action for action in actions]
