"""Seal zero-cost Sphere cultivation provenance for activation consumers.

Shared consumers are Mercurial conversion/assimilation and Balanced Flow's
Qi-powered roll benefits. Explicit source exclusions (prepared items, ordinary
weapons) win. No Sphere or no Qi chassis leaves the action unchanged.
"""
from copy import deepcopy
from . import hook


@hook('compile_action')
def sphere_profile(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if not typed.get('sphere') or typed.get('attack_action') or type(typed.get('qi_powered')) is bool:
        return None
    stats = (info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}
    if str((stats.get('primary_resource') or {}).get('name') or '').lower() != 'qi':
        return None
    parameters = deepcopy(action.parameters)
    parameters['typed']['qi_powered'] = True
    return action.model_copy(update={'parameters': parameters})
