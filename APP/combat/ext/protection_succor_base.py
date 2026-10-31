"""Succor's base wrapper for existing generic talent reaction producers.

Protection's full catalog sphere text supplies the 300-foot recipient range
and immediate sacrifice before the talent effect. Luck already implements its
own range and pre-effect sacrifice through d20_rewrite; this module leaves it
alone. No talent trigger or effect is implemented a second time here.
"""
from copy import deepcopy

from . import hook

BASE = 'PROTECTION_BASE_SUCCOR'
MARK = 'Persistent Aegis'


@hook('compile_bundle')
def inherit_succor_procedure(bundle, info):
    """Apply the owned wrapper to reactions explicitly sacrificing an Aegis.

    Inert without the base record or a generic reaction with the printed
    Persistent Aegis price. Retain all talent-specific eligibility, choices,
    effects and ordering among effects other than the up-front sacrifice.
    """
    block = info['owner_sheet'].get('spheres_and_talents') or {}
    owned = set(block.get('automatic_sphere_component_record_ids') or ())
    owned.update(block.get('learned_talent_record_ids') or ())
    if BASE not in owned:
        return None
    changed = None
    for index, row in enumerate(bundle.get('typed_reactions') or ()):
        effects = row.get('effects') or []
        prices = [effect for effect in effects if effect.get('type') == 'spend_mark'
                  and effect.get('mark') == MARK and effect.get('applies_to') == 'ally']
        if row.get('block') != 'generic' or not prices:
            continue
        if changed is None:
            changed = deepcopy(bundle)
        reaction = changed['typed_reactions'][index]
        reaction['requires_mark'] = MARK
        reaction['mark_on'] = 'subject'
        reaction['range_ft'] = min(int(row.get('range_ft') or 300), 300)
        reaction['range_reference'] = 'subject'
        reaction['effects'] = deepcopy(prices + [effect for effect in effects if effect not in prices])
    return changed
