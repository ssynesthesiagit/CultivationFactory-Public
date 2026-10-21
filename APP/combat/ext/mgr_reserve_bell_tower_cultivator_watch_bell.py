"""Watch Bell's creature Revealing Tone (Qi Subpath R19, CL3).

This narrow provider supplies the native mark producer for the observer-darkness
repair. Other Watch Bell clauses and the later Bell progression remain with
their parent implementation. Existing catalog choices are retained.
"""
from . import effect, hook

WATCH = 'tianxia.subpath.qi.bell_tower_cultivator.feature.watch_bell'
MARK = 'condition:typed.bell.marked'
UNTIL = 'START_OF_SOURCE_NEXT_TURN'


def owned(engine, actor):
    return any(row.get('block') == 'watch_bell' and row.get('feature_id') == WATCH
               for row in engine.typed_passive_rows.get(actor.entity_id, ()))


def marks(target, viewer):
    return [condition for condition in target.conditions.values()
            if condition.condition_id == MARK and condition.source_actor_id == viewer.entity_id]


@hook('compile_passives')
def ownership(rows, info):
    if WATCH not in info['owned_ids'] or int(info['numbers'].get('cl') or 1) < 3:
        return None
    return [*rows, {'block': 'watch_bell', 'feature_id': WATCH}]


@hook('compile_action')
def revealing_tone(action, info):
    typed = action.parameters.get('typed') or {}
    if (typed.get('source') != WATCH or typed.get('option_label') != 'Revealing Tone'
            or WATCH not in info['owned_ids'] or int(info['numbers'].get('cl') or 1) < 3):
        return None
    # Only the creature mode is implemented here. Leave the other catalog
    # choices and their identities untouched; do not import the parent graph.
    return action.model_copy(update={
        'display_name': 'Watch Bell: Revealing Tone', 'target_kind': 'SELF', 'range_ft': None,
        'costs': (('resource:core.qi', 1),),
        'parameters': {**action.parameters,
            'description': 'Watch Bell: Revealing Tone (bonus action, 1 Qi). Choose a creature within 60 feet. '
                           'It makes a Charisma save; failure marks it until your next turn starts, '
                           'success until this turn ends. Darkness alone cannot hide it from you.',
            'typed': {**typed, 'manual_inline_choice': True, 'area': None, 'riders': [],
                      'effects': [{'type': 'watch_bell_mark'}]}}})


@effect('watch_bell_mark')
def apply_mark(ctx, row):
    from ..target_knowledge import knowledge, located
    from .rider_choices import pick
    from .spirit_traditions import save

    if not owned(ctx.engine, ctx.actor):
        raise ValueError('Revealing Tone requires an acquired Watch Bell feature')
    creatures = [actor for actor in ctx.engine.state.actors.values()
                 if actor.active and ctx.engine._on_battlefield(actor)
                 and ctx.engine._distance_actor_to_actor(ctx.actor, actor) <= 60
                 and knowledge(ctx.engine, ctx.actor, actor) is not None]
    if not creatures:
        return
    chosen = pick(ctx.engine, ctx.actor, 'bell_reveal_target', 'Watch Bell: Revealing Tone',
                  [actor.entity_id for actor in creatures], subject=ctx.actor,
                  labels={actor.entity_id: actor.display_name for actor in creatures},
                  optional=False, intent=ctx.intent,
                  automatic_options=[actor.entity_id for actor in creatures
                                     if actor is ctx.actor or located(ctx.engine, ctx.actor, actor)],
                  choose='Choose one creature within 60 feet to make a Charisma save and receive your Bell Mark.')
    if not chosen:
        return
    target = ctx.engine.state.actors[chosen[0]]
    failed = save(ctx, target, 'cha')
    ctx.engine._apply_condition(target, MARK, ctx.source, ctx.actor.entity_id,
        expires_on=UNTIL if failed else 'END_OF_CURRENT_TURN',
        data={'label': 'Bell-Marked: darkness alone cannot hide you from the bell ringer; '
                       'ends at their next turn start on a failed save, or this turn end on success'})
