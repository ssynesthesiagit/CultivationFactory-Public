"""Scoundrel's reviewed area object result, using the existing transfer ledger.

Only the newly sealed scoundrel_area_object row opts in. Held-item theft uses
real weapon/shield/ordinary-object hands; the drop option uses ordinary accessible
carried items. Selection is from the affected target's current possessions.
Existing transfer_object handles identity, weight, weapon availability, and the
player's explicit 30-foot landing choice. Markerless saved actions are inert.
"""
from . import effect


@effect('scoundrel_area_object')
def area_object(ctx, row):
    from . import needle, scoundrel_riders as objects
    from .. import typed_executor as te

    target = ctx.target
    if target is None or target.team_id == ctx.actor.team_id:
        return
    pool = objects.possessions(ctx.engine, target)
    if row.get('held_only'):
        pool = objects.held_possessions(ctx.engine, target)
    else:
        pool = [item for item in pool if item.get('kind') == 'item' and not item.get('worn')]
    pool = [item for item in pool if not any(item.get(flag) for flag in
            ('artifact', 'soul_bound', 'fused', 'protected', 'sealed'))]
    if not pool:
        from . import note
        note(ctx.engine, ctx.source, ctx.actor,
             f'{ctx.action.display_name}: {target.display_name} has no eligible accessible object to move.', (target,))
        return
    by_id = {str(item['object']): item for item in pool}
    labels = {key: str(item.get('name') or 'Object') for key, item in by_id.items()}
    for key, label in list(labels.items()):
        if sum(str(item.get('name') or 'Object') == label for item in pool) > 1:
            owner = ctx.engine.state.actors.get(key.partition('|')[0])
            if owner is not None:
                labels[key] = f'{label} belonging to {owner.display_name}'
    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, 'WRONG_PLACE_OBJECT', target.entity_id), ctx.actor,
        'choice:needle.wrong_place_object', list(by_id),
        labels=labels,
        minimum=1, maximum=1, name=ctx.action.display_name, target_id=target.entity_id,
        prompt=f'{ctx.action.display_name}: choose one accessible '
               f'{"held" if row.get("held_only") else "ordinary carried"} object from {target.display_name}. '
               'It lands in an unoccupied square you choose within 30 feet of you; no extra cost.')
    if not chosen or chosen[0] not in by_id:
        return
    item = by_id[chosen[0]]
    te.run_effects(ctx, [{'type': 'transfer_object', 'applies_to': 'target',
        'from': 'victim', 'as': 'fall', 'item': item['key'], 'object': item['object'],
        'ability': ctx.action.display_name, 'landing_range_ft': 30}])
