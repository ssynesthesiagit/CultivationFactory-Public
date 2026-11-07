"""Piledriver: one paid Unarmed Strike, with an optional Twin Tie-Up second target.

The reviewed effect is a compile marker. Fresh actions freeze the fighter's
ordinary unarmed damage/attack numbers; old saved catalogs remain untouched.
All targets must still be grappled by the user when their attack resolves.
"""
import copy
from . import effect, hook

SOURCE = 'TAL_WRESTLING_PILEDRIVER'
TWIN = 'TAL_WRESTLING_TWIN_TIE_UP'
GRAPPLED = 'condition:typed.grappled'


@effect('wrestling_piledriver')
def piledriver(ctx, row):
    from ..typed_executor import Context, run_effects
    from ..attack_declaration import can_target
    from ..relations import relation, ENEMY
    from .. import stealth
    from . import ai_controlled
    from .rider_choices import pick

    def legal(target):
        return (target is not None and target.active and relation(ctx.engine, ctx.actor, target) == ENEMY
                and any(c.condition_id == GRAPPLED and c.source_actor_id == ctx.actor.entity_id
                        for c in target.conditions.values())
                and (not ai_controlled(ctx.engine, ctx.actor) or stealth.sees(ctx.engine, ctx.actor, target))
                and can_target(ctx.engine, ctx.actor, target, ctx.source, action=ctx.action,
                               typed_profile=ctx.typed, effect=row['attack'], range_ft=ctx.action.range_ft))

    if not legal(ctx.target):
        return
    targets = [ctx.target]
    if row.get('twin'):
        others = [a for a in ctx.engine.state.actors.values() if a is not ctx.target and legal(a)]
        if others:
            chosen = pick(ctx.engine, ctx.actor, 'piledriver_second', 'Piledriver',
                          [a.entity_id for a in others], subject=ctx.target,
                          labels={a.entity_id: f'Also strike {a.display_name}, Grappled by you' for a in others},
                          preferred=[others[0].entity_id], automatic=ai_controlled(ctx.engine, ctx.actor),
                          prompt=f'Piledriver: Unarmed Strike against {ctx.target.display_name}. With Twin Tie-Up, '
                                 'also make one Unarmed Strike against another creature '
                                 'Grappled by you? This costs no additional Martial Focus. You may pass.')
            targets += [a for a in others if a.entity_id in chosen]
    for target in targets:
        if legal(target):
            child = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
            run_effects(child, [row['attack']])


@hook('maneuvers')
def compile_piledriver(info):
    if SOURCE not in set(info.get('owned') or ()):
        return None
    mechanic = (info.get('mechanics') or {}).get(SOURCE) or {}
    if not any(r.get('type') == 'wrestling_piledriver' for r in mechanic.get('effects') or []):
        return None
    bases = [a for a in info.get('actions') or () if '.natural.' in a.source_definition_id
             and not ((a.parameters or {}).get('typed') or {}).get('modifier')
             and not ((a.parameters or {}).get('typed') or {}).get('variant_of')
             and any(e.get('type') == 'attack' and e.get('attack_kind') == 'unarmed'
                     for e in ((a.parameters or {}).get('typed') or {}).get('effects') or [])]
    base = max(bases, key=lambda a: int(a.parameters.get('expected_damage') or 0), default=None)
    if base is None:
        return None
    params = copy.deepcopy(base.parameters)
    typed = params['typed']
    attack = copy.deepcopy(typed['effects'][0])
    remaining = max(0, int(attack.get('count') or 1) - 1)
    follow = copy.deepcopy(attack)
    follow['count'] = remaining
    attack['count'] = 1
    attack['on_hit'] += [
        {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'},
        {'type': 'save', 'ability': 'CON', 'dc': 'technique_save_dc', 'on_fail': [
            {'type': 'condition', 'condition': 'stunned', 'applies_to': 'target',
             'duration': 'until_end_of_your_next_turn'}], 'on_success': []}]
    typed.update(source=SOURCE, sphere='tianxia.sphere.wrestling', riders=[],
                 effects=[{'type': 'wrestling_piledriver', 'attack': attack,
                           'twin': TWIN in set(info.get('owned') or ())}] + ([follow] if remaining else []))
    grapple = next((a for a in info['actions'] if a.source_definition_id.endswith('.unarmed.grapple')), None)
    if grapple is not None:
        typed['numbers']['save_dc'] = grapple.parameters['typed']['numbers']['save_dc']
    # Use the ordinary attack's sealed loadout and existing player preferences.
    # settings() refreshes variants from their final compiled parent and avoids
    # creating a second, independent set of rider controls for this maneuver.
    typed['variant_of'] = base.source_definition_id
    params.update(target_requires_condition=GRAPPLED, piledriver_runtime=True)
    return {'actions': [base.model_copy(update={'source_definition_id': base.source_definition_id + '.piledriver',
        'display_name': 'Piledriver: Unarmed Strike', 'parameters': params,
        'costs': (('resource:core.martial_focus', 1),)})]}


@hook('candidate_allowed')
def held_target(engine, actor, candidate, action):
    if action is None or not action.parameters.get('piledriver_runtime'):
        return None
    return bool(candidate.target_ids) and all(
        tid in engine.state.actors and any(c.condition_id == GRAPPLED and c.source_actor_id == actor.entity_id
            for c in engine.state.actors[tid].conditions.values()) for tid in candidate.target_ids)


@hook('choice_reactors')
def reactors(engine):
    return tuple(a.owner_id for a in engine.action_catalog.values() if a.parameters.get('piledriver_runtime'))
