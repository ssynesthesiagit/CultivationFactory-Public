"""Body-armor benefits and penalties follow storage, drops and transfers.

The compiler quotes armor-dependent calculations once. Shadow Stash and ordinary equipment
relocation share this passive receipt; no ability identity or runtime patching.
"""
from copy import deepcopy
from . import hook


@hook('compile_bundle')
def quote_armor_presence(bundle, info):
    worn = next((item for item in bundle['carrying']['items'] if item.get('worn')), None)
    amount = info.get('body_armor_ac_delta', 0)
    if worn is None:
        return bundle
    result = deepcopy(bundle)
    result['typed_passives'].append({'block': 'body_armor_presence',
        'item_key': worn['key'], 'amount': amount,
        'speed_delta': info.get('body_armor_speed_delta', 0),
        'stealth_disadvantage': int(bool(bundle['carrying'].get('stealth_disadvantage')))})
    return result


@hook('ac')
def armor_presence(engine, actor, *_):
    from ..carry import lost_to_another_hand
    return -sum(row['amount'] for row in engine.typed_passive_rows.get(actor.entity_id, ())
                if row.get('block') == 'body_armor_presence'
                and lost_to_another_hand(actor, row['item_key']))


@hook('carrying_speed')
def armor_speed(speed, engine, actor):
    """Restore the quoted armor-only Speed loss before load limits apply."""
    from ..carry import lost_to_another_hand
    return speed + sum(row.get('speed_delta', 0)
        for row in engine.typed_passive_rows.get(actor.entity_id, ())
        if row.get('block') == 'body_armor_presence'
        and lost_to_another_hand(actor, row['item_key']))


@hook('hide_base_mode')
def armor_hide_mode(mode, engine, actor):
    """Remove only the compiler's armor mode; other check sources still stack."""
    from ..carry import lost_to_another_hand
    if mode == 'DISADVANTAGE' and any(
        row.get('block') == 'body_armor_presence' and row.get('stealth_disadvantage')
        and lost_to_another_hand(actor, row['item_key'])
        for row in engine.typed_passive_rows.get(actor.entity_id, ())):
        return 'NORMAL'


@hook('candidate_allowed')
def armor_drop_allowed(engine, actor, candidate, action):
    """Worn armor needs doffing; recovered/carried armor can be dropped freely."""
    from ..carry import carrying_of, item_of, lost_to_another_hand
    if action is None or action.parameters.get('item_action') != 'drop':
        return None
    item = item_of(carrying_of(engine, actor.entity_id), key=action.parameters.get('item_key'))
    if item and item.get('worn') and not lost_to_another_hand(actor, item['key']):
        return False
