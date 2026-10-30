"""Grave Sense: represented death signs, never a hidden creature's identity.

No-action detection projects only presence/direction. Focus spends an Action
and asks for one sign and one available diagnostic fact. Unknown historical
facts remain unknown; scene metadata explicitly supplies them when represented.
"""
from . import effect, hook
from .observer_information import bearing, record
from .fight_ownership import owns_feature
from .needle import ask, checkpoint_id, numbers_of

GRAVE = 'TAL_DEATH_GRAVE_SENSE'


@hook('compile_actions')
def focus_action(info):
    if GRAVE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    info['passives'].append({'feature_id': GRAVE, 'block': 'grave_sense', 'kind': 'grave_sense'})
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.grave_sense_focus",
        display_name='Grave Sense: Focus', owner_id=info['actor_id'], economy='ACTION',
        resolution_kind='TYPED', target_kind='SELF', parameters={'typed': {
            'source': GRAVE, 'sphere': 'tianxia.sphere.death', 'numbers': info['numbers'], 'effects': [{'type': 'grave_sense_focus'}],
            'duration': {'kind': 'instant'}, 'riders': []},
            'description': 'Spend an Action to focus on a sensed death-sign within range and learn one available fact. No cultivation point cost.'})]


def signs(engine, viewer):
    if not owns_feature(engine, viewer, GRAVE):
        return {}
    cl = int(numbers_of(engine, viewer).get('cl') or 1)
    reach = 120 if cl >= 15 else 60 if cl >= 10 else 30
    found = {}
    for actor in engine.state.actors.values():
        if actor is viewer or actor.position is None or engine._distance_actor_to_actor(viewer, actor) > reach:
            continue
        kinds = {str(x).lower() for x in actor.creature_types}
        category = 'undead' if 'undead' in kinds else 'ghost' if 'ghost' in kinds else 'dying creature' if actor.current_hp == 0 and actor.life_state == 'DYING' else 'corpse' if not actor.active and actor.current_hp == 0 and actor.life_state not in ('STABLE', 'CONSCIOUS') else ''
        facts = {'kind': category} if category else {}
        for condition in actor.conditions.values():
            from .observer_information import FACT
            source = engine.action_catalog.get(condition.source_definition_id)
            if condition.condition_id != FACT and source is not None and (source.parameters.get('typed') or {}).get('sphere') == 'tianxia.sphere.death':
                found[actor.entity_id + '#' + condition.instance_id] = (actor, {'kind': 'active Death effect'})
            authored = condition.data.get('death_sign')
            if isinstance(authored, dict):
                facts.update({k: str(v) for k, v in authored.items()
                              if k in ('kind', 'age', 'corpse_state', 'undead_state', 'soul_binding') and v})
        if facts:
            found[actor.entity_id] = (actor, facts)
    return found


@hook('observer_information')
def death_directions(engine, viewer):
    return [{'ability': 'Grave Sense', 'direction': bearing(viewer, actor.position),
             'text': 'Grave Sense: a death-sign is present to the ' + bearing(viewer, actor.position)}
            for actor, facts in signs(engine, viewer).values()]


@effect('grave_sense_focus')
def focus(ctx, row):
    available = signs(ctx.engine, ctx.actor)
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'grave_focus', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.grave_focus', list(available), name='Grave Sense',
        labels={key: 'Death-sign to the ' + bearing(ctx.actor, actor.position) for key, (actor, _) in available.items()},
        prompt='Grave Sense: choose a sensed death-sign to focus on with this Action. This does not identify a hidden creature.')
    if not selected:
        return
    actor, facts = available[selected[0]]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'grave_fact', ctx.actor.entity_id), ctx.actor,
        'choice:needle.grave_fact', list(facts), name='Grave Sense',
        labels={'kind': 'What kind of death-sign is this?', 'age': 'Was the death recent or old?',
                'corpse_state': 'Is the corpse preserved, desecrated, animated or protected?',
                'undead_state': 'Is the undead bound, feral, willing, commanded or self-willed?',
                'soul_binding': 'Is a visible possession or soul-binding effect present?'},
        prompt='Grave Sense: choose one available fact about the focused death-sign.')
    if chosen:
        key = chosen[0]
        record(ctx.engine, ctx.actor, ctx.source, f'Grave Sense: you learned that the death-sign you focused on to the {bearing(ctx.actor, actor.position)} was {facts[key]}.',
               fact=key, value=facts[key], ability='Grave Sense')
