"""Seal zero-cost Sphere cultivation provenance for activation consumers.

Shared consumers are Mercurial conversion/assimilation and Balanced Flow's
Qi-powered roll benefits. Explicit source exclusions (prepared items, ordinary
weapons) win. No Sphere or no Qi chassis leaves the action unchanged.
"""
from copy import deepcopy
from . import hook


@hook('compile_action', priority=100)
def sphere_profile(action, info):
    # Existing source-specific producers run first. This fallback never
    # republishes or overrides their explicit Qi-powered decision.
    typed = (action.parameters or {}).get('typed') or {}
    if not typed:
        return None
    source = str(typed.get('option_of') or typed.get('source') or '')
    mechanic = (info.get('mechanics') or {}).get(source) or {}
    kinds = {'path_feature': 'Path', 'subpath_feature': 'Subpath', 'talent': 'Sphere',
             'base_ability': 'Sphere', 'recorded_art': 'Recorded', 'forged_technique': 'Forged',
             'immortal_art': 'Immortal', 'item_power': 'item', 'formation': 'Formation'}
    category = ('Immortal' if typed.get('immortal_from') else 'Forged' if typed.get('forged_from')
                else kinds.get(mechanic.get('kind')))
    changes = {}
    stats = (info.get('owner_sheet') or {}).get('ability_scores_and_statistics') or {}
    if (typed.get('sphere') and not typed.get('attack_action') and type(typed.get('qi_powered')) is not bool
            and str((stats.get('primary_resource') or {}).get('name') or '').lower() == 'qi'):
        changes['qi_powered'] = True
    if category:
        compiled = dict(typed.get('activation_profile') or {})
        compiled.setdefault('source_kind', category)
        cl = (typed.get('numbers') or {}).get('cl')
        if category in ('Path', 'Subpath', 'Sphere', 'Recorded', 'Forged', 'Immortal') and type(cl) is int:
            compiled.setdefault('source_cl', cl)
        from ..weapon_delivery import delivery_kind
        declared_qi = changes.get('qi_powered', typed.get('qi_powered'))
        qi = declared_qi if type(declared_qi) is bool else (any(
            pool == 'resource:core.qi' and amount > 0 for pool, amount in action.costs) or source.startswith(
                ('tianxia.path.qi_cultivation.', 'tianxia.subpath.qi.')))
        # Only source-authored weapon_damage delivery inside a technique can
        # authorize converting an ordinary weapon's printed physical component.
        if qi and not typed.get('attack_action') and any(
                e.get('type') == 'attack' and delivery_kind(typed, e, action.parameters) == 'weapon'
                and any(d.get('weapon_damage') for d in e.get('on_hit') or ())
                for e in mechanic.get('effects') or ()):
            compiled.setdefault('weapon_delivery', True)
        if compiled != typed.get('activation_profile'):
            changes['activation_profile'] = compiled
    if not changes:
        return None
    parameters = deepcopy(action.parameters)
    parameters['typed'].update(changes)
    return action.model_copy(update={'parameters': parameters})
