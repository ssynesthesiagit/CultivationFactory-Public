"""Reagent Stock preparation from real common-reagent holdings at Long Rest.

Consumers: existing alchemy_stock compiler and typed named-resource spending.
A plan is an actor choice, not prepared inventory. Only a completed eight-hour
rest consumes its recorded common reagents and prepares uses. Unused uses may
be folded into that preparation; all other old uses spoil at that rest's end.
"""
from . import hook
from . import material_ledger as ledger
from .alchemy_stock import REAGENT_STOCK, STOCK
from ..journey import require, integer


def capacity(session, aid):
    return next((r['maximum'] for r in session.state['actors'][aid]['bundle']['actor_template']['resources']
                 if r['resource_id'] == STOCK), 0)


@hook('journey_command')
def plan(session, aid, kind, payload):
    if kind != 'prepare_reagents':
        return None
    require(ledger.owned(session, aid, REAGENT_STOCK), 'This creature has not learned Reagent Stock.')
    require(set(payload) == {'new_uses', 'fold_uses', 'materials'}, 'Choose new uses, folded uses and their actual common reagents.')
    actor = session.state['actors'][aid]
    new, fold, materials = payload['new_uses'], payload['fold_uses'], payload['materials']
    require(not actor['incapacitated'] and integer(new) and integer(fold)
            and fold <= actor['resources'].get(STOCK, 0) and new + fold <= capacity(session, aid),
            'Preparation must fit your own capacity and remaining prepared uses.')
    require(isinstance(materials, dict) and all(isinstance(k, str) and integer(v, 1) for k, v in materials.items())
            and sum(materials.values()) == 10 * new,
            'Each new use needs exactly 10 gp of recorded common reagents.')
    for key, amount in materials.items():
        row = ledger.holdings(session, aid).get(key)
        require(row is not None and row['kind'] == 'common_reagents' and row['unit'] == 'gp'
                and row['quantity'] >= amount, 'Use your own available common reagents, valued in gold pieces.')
    actor.setdefault('material_preparation', {})['reagents'] = dict(payload)
    ledger.record(session, aid, 'REAGENT_PREPARATION_PLANNED', new_uses=new, fold_uses=fold, materials=materials)
    return True


@hook('journey_rest')
def prepare(session, aid):
    if not ledger.owned(session, aid, REAGENT_STOCK):
        return None
    actor = session.state['actors'][aid]
    old = actor['resources'].get(STOCK, 0)
    plan = actor.get('material_preparation', {}).get('reagents')
    if plan:
        # Revalidate at settlement: combat or other consumption may have changed
        # stock/materials since the plan. Failure rolls back the entire rest.
        require(plan['fold_uses'] <= old and plan['new_uses'] + plan['fold_uses'] <= capacity(session, aid),
                'Your preparation plan changed; choose a legal plan before resting.')
        for key, amount in plan['materials'].items():
            ledger.consume(session, aid, key, amount, kind='common_reagents')
        prepared = plan['new_uses'] + plan['fold_uses']
        del actor['material_preparation']['reagents']
    else:
        prepared = 0
    actor['resources'][STOCK] = prepared
    actor.setdefault('material_preparation', {})['native_stock_prepared'] = 1
    ledger.record(session, aid, 'REAGENT_STOCK_PREPARED', previous=old, prepared=prepared,
                  spoiled=old - (plan['fold_uses'] if plan else 0), rest=actor['long_rests'])


@hook('journey_options')
def options(session, aid):
    if not ledger.owned(session, aid, REAGENT_STOCK) or session.state['phase'] != 'travel' or session.state['actors'][aid]['incapacitated']:
        return None
    actor = session.state['actors'][aid]
    # Whole legal quantities remain reachable through structured service input;
    # menu includes each single-source plan plus retaining existing uses.
    rows = []
    for fold in range(min(capacity(session, aid), actor['resources'].get(STOCK, 0)) + 1):
        rows.append({'id': f'reagent-fold:{fold}', 'kind': 'prepare_reagents',
                     'payload': {'new_uses': 0, 'fold_uses': fold, 'materials': {}},
                     'label': f'At your next Long Rest, fold {fold} unused Reagent Stock uses into preparation; other unused uses spoil.'})
        for key, item in ledger.holdings(session, aid).items():
            if item['kind'] == 'common_reagents' and item['unit'] == 'gp':
                for new in range(1, min(capacity(session, aid) - fold, item['quantity'] // 10) + 1):
                    rows.append({'id': f'reagent-plan:{key}:{new}:{fold}', 'kind': 'prepare_reagents',
                        'payload': {'new_uses': new, 'fold_uses': fold, 'materials': {key: 10 * new}},
                        'label': f'At your next eight-hour Long Rest, prepare {new} new Reagent Stock uses for {10 * new} gp in common reagents and fold {fold} unused uses into the same preparation.'})
    return rows


@hook('journey_actor_restored')
def unknown_old_stock(session, aid):
    if not ledger.owned(session,aid,REAGENT_STOCK): return None
    actor = session.state['actors'][aid]
    if actor['resources'].get(STOCK,0) and not actor.get('material_preparation',{}).get('native_stock_prepared'):
        actor['resources'][STOCK] = 0
        ledger.record(session,aid,'REAGENT_STOCK_UNKNOWN',
            text='The old stored count has no recorded preparation. Prepare actual common reagents during a Long Rest before spending Reagent Stock.')
