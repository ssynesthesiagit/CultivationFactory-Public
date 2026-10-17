"""Choose and temporarily suppress one represented ordinary named affliction.

No condition is created or guessed. Protected source categories and explicit
nonordinary instances are excluded. Old rows without this effect are inert.
"""
from . import effect, note
from .needle import ask, checkpoint_id, CHOICE
from .benefit_suppression import suppress
from .source_eligibility import stored_power, protected_power, catalog_action


def eligible(engine, holder, names):
    rows = []
    for item in holder.conditions.values():
        if item.condition_id not in {'condition:typed.' + name for name in names}:
            continue
        data = item.data or {}
        if data.get('ordinary') is False or any(data.get(k) for k in ('legendary', 'secret', 'artifact', 'realm_defining')):
            continue
        power = stored_power(engine, item.source_definition_id)
        action = catalog_action(engine, item.source_definition_id)
        typed = ((getattr(action, 'parameters', None) or {}).get('typed') or {})
        categories = {str(typed.get(key) or '').lower().replace('_', ' ').replace('-', ' ')
                      for key in ('source_category', 'pattern_category', 'authority_tier')}
        if typed.get('ordinary') is False or categories.intersection({'legendary', 'secret', 'secret inheritance', 'artifact', 'realm defining', 'restricted'}):
            continue
        if protected_power(*(power or (typed, ''))):
            continue
        rows.append(item)
    return rows


@effect('suppress_named_condition')
def apply(ctx, eff):
    from ..typed_executor import effect_subjects
    from .ability_source import source_label
    for holder in effect_subjects(ctx, eff, harmful=False):
        rows = eligible(ctx.engine, holder, eff.get('conditions') or [])
        labels = {c.instance_id: f"{c.condition_id.removeprefix('condition:typed.').replace('_', ' ').title()} "
                  f"from {source_label(ctx.engine, c.source_definition_id)} "
                  f"— suppress until {ctx.actor.display_name}'s next turn starts" for c in rows}
        totals = {label: list(labels.values()).count(label) for label in labels.values()}
        seen = {}
        for key, label in list(labels.items()):
            seen[label] = seen.get(label, 0) + 1
            if totals[label] > 1:
                labels[key] += f' (copy {seen[label]} of {totals[label]})'
        if not labels:
            note(ctx.engine, ctx.source, ctx.actor, f'{ctx.action.display_name}: {holder.display_name} has no eligible ordinary affliction.', (holder,))
            continue
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'named_suppression', holder.entity_id),
                     ctx.actor, CHOICE + 'named_suppression', list(labels), labels=labels,
                     name=ctx.action.display_name, target_id=holder.entity_id,
                     prompt=f'{ctx.action.display_name}: choose one ordinary affliction on {holder.display_name}. '
                            'Its effects pause until your next turn starts; its original duration keeps running.')
        if chosen:
            suppress(ctx.engine, ctx.actor, holder, 'condition:' + chosen[0], 'owner_turn', ctx.source,
                     label=f'{ctx.action.display_name}: {labels[chosen[0]]}')
