"""Court of the Endless Tide's owned Domain modifiers.

Uses native zone identity/lifetime, free-use accounting, remote origins, final
save outcomes and forced paths. No physical water is created by the Domain.
Public additional_control(engine, actor) returns its live additive control
allowance (0/1), for the Shape Current control-pool owner; it does not replace
that pool's baseline or other talents' allowances.
"""
from copy import deepcopy
from itertools import combinations

from . import hook, effect
from .needle import ask, checkpoint_id, CHOICE

COURT = 'TAL_WATER_COURT_OF_THE_ENDLESS_TIDE'
SHAPE = 'WATER_BASE_SHAPE_CURRENT'
LASH = 'WATER_BASE_WATER_LASH'
ROSTER = 'endless_tide_allies'


def source_of(engine, definition):
    """Source-qualified action provenance, including compiled option variants."""
    action = engine.action_catalog.get(definition)
    return ((action.parameters or {}).get('typed') or {}).get('source') if action else None


def domains(engine, actor):
    """Actual active owned Domains; ownership of a condition alone grants nothing."""
    if actor is None or not actor.active:
        return []
    return [z for z in engine.state.zones.values() if z.active
            and z.owner_id == actor.entity_id and source_of(engine, z.source_definition_id) == COURT]


def additional_control(engine, actor):
    """Add one slot while this owner's Domain lasts; overlapping Courts do not stack."""
    return int(bool(domains(engine, actor)))


@hook('compile_action')
def domain_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if COURT not in info['owned_ids'] or typed.get('source') != COURT:
        return None
    typed = deepcopy(typed)
    # The spiritual Domain is not difficult ground or a physical Water Source.
    # Replace the deferred cast-time push: its trigger is a later Water save.
    typed['effects'] = [e for e in typed.get('effects') or [] if not e.get('deferred')]
    typed['effects'].append({'type': 'water_court_roster', 'cast_only': True})
    if typed.get('zone_spec'):
        typed['zone_spec'].update(difficult=False, obscured=False, terrain=[], triggers=[], inside=[])
    typed['riders'] = [r for r in typed.get('riders') or []
                       if 'additional Basin' in r or 'physical water' in r]
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})


@effect('water_court_roster', harmful=False)
def choose_allies(ctx, row):
    from ..target_knowledge import located
    from .retained_updates import record_zone_update
    allies = {a.entity_id: a for a in ctx.engine.state.actors.values()
              if a.active and a.team_id == ctx.actor.team_id}
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ENDLESS_TIDE_ALLIES', ctx.source),
                 ctx.actor, CHOICE + 'endless_tide_allies', list(allies), minimum=0,
                 maximum=len(allies), default='all',
                 automatic_options=[k for k, a in allies.items() if a is ctx.actor or located(ctx.engine, ctx.actor, a)],
                 labels={k: a.display_name for k, a in allies.items()}, name='Court of the Endless Tide',
                 feature_id=COURT,
                 prompt='Court of the Endless Tide: choose allies who ignore Difficult Terrain from your Water effects '
                        'while your Domain lasts. This costs no additional action or Cultivation Points.')
    for zone in domains(ctx.engine, ctx.actor):
        zone.trigger_profile[ROSTER] = list(chosen)
        record_zone_update(ctx.engine, zone)


@hook('effect_origins')
def lash_origins(engine, actor, action):
    if ((action.parameters or {}).get('typed') or {}).get('source') != LASH:
        return None
    cells = {p for z in domains(engine, actor) for p in z.affected_cells}
    return [{'id': f'endless-tide:{p.x},{p.y},{p.z}',
             'label': f'Court of the Endless Tide square ({p.x}, {p.y}, {p.z})',
             'position': p.model_dump(mode='json')} for p in sorted(cells, key=lambda p: (p.z, p.y, p.x))] or None


@hook('zone_difficult_policy')
def hostile_basins(policy, engine, zone, creature):
    owner = engine.state.actors.get(zone.owner_id)
    if (source_of(engine, zone.source_definition_id) == SHAPE and domains(engine, owner)
            and creature.team_id != owner.team_id):
        return 'all'
    return None


@hook('difficult_zone_exempt')
def chosen_water_ground(engine, creature, zone):
    source = source_of(engine, zone.source_definition_id) or ''
    if not source.startswith(('WATER_BASE_', 'TAL_WATER_')):
        return None
    owner = engine.state.actors.get(zone.owner_id)
    if owner is None or creature.team_id != owner.team_id:
        return None
    return True if any(creature.entity_id in z.trigger_profile.get(ROSTER, [])
                       for z in domains(engine, owner)) else None


@hook('candidate_allowed')
def court_grants(engine, actor, candidate, action):
    if action is None:
        return None
    parameters = action.parameters or {}
    if parameters.get('endless_tide_pair') and not domains(engine, actor):
        return False
    return None


@hook('free_use_grant_allowed')
def court_free_return(engine, actor, grant):
    """Validate only Court's funding; independent Incarnation grants survive."""
    if grant.get('key', '').startswith(COURT + ':'):
        return bool(domains(engine, actor) and engine.state.current_actor_id == actor.entity_id)
    return None


@hook('compile_actions')
def dual_forms(info):
    """Reuse compiled ordinary forms, including their actual triggers and upgrades.

    All six distinct pairs remain reachable alongside every ordinary option.
    No sibling form definition is copied or replaced. Each paired Basin is one
    activation, zone, concentration link and control load.
    """
    if COURT not in info['owned_ids']:
        return None
    forms = {}
    for action in info['actions']:
        typed = (action.parameters or {}).get('typed') or {}
        if (typed.get('source') == SHAPE and not typed.get('modifier')
                and any(e.get('type') == 'zone' for e in typed.get('effects', []))
                and not action.parameters.get('zone_move_technique')):
            label = typed.get('option_label')
            if label in ('Flowing Current', 'Mist Basin', 'Pressure Basin', 'Cleansing Basin'):
                forms[label] = action
    made = []
    for left, right in combinations(forms, 2):
        base, other = forms[left], forms[right]
        typed = deepcopy(base.parameters['typed'])
        second = other.parameters['typed']
        spec = next(e for e in typed['effects'] if e.get('type') == 'zone')
        extra = next(e for e in second['effects'] if e.get('type') == 'zone')
        spec['obscured'] = spec.get('obscured') or extra.get('obscured')
        spec['difficult'] = spec.get('difficult') or extra.get('difficult')
        for field in ('triggers', 'inside'):
            spec[field] = [*spec.get(field, []), *deepcopy(extra.get(field, []))]
        # Flow's initial save remains an actual cast effect, not a repeat trigger.
        typed['effects'] = [*typed.get('effects', []), *deepcopy([
            e for e in second.get('effects', []) if e.get('cast_only') and e.get('type') != 'zone'])]
        typed['option_label'] = left + ' + ' + right
        typed['endless_tide_flow'] = int('Flowing Current' in (left, right))
        made.append(base.model_copy(update={
            'source_definition_id': base.source_definition_id + '.court.' + right.lower().replace(' ', '_'),
            'display_name': 'Shape Current: ' + typed['option_label'],
            'parameters': {**base.parameters, 'typed': typed, 'endless_tide_pair': 1}}))
    return made or None


@hook('button_description')
def paired_description(row):
    parameters = row.get('parameters') or {}
    if not parameters.get('endless_tide_pair'):
        return None
    label = (parameters.get('typed') or {}).get('option_label') or ''
    benefits = {
        'Mist Basin': 'The area is Lightly Obscured.',
        'Pressure Basin': 'The first hostile creature each round that enters or starts its turn there makes a '
                          'Strength save or loses 10 feet of Speed until the start of its next turn.',
        'Cleansing Basin': 'Once per creature each round on entering or starting its turn there, you or an ally may '
                           'end Soaked, extinguish ordinary flames, or gain Advantage on its next save against '
                           'Poisoned, disease, smoke, heat or mundane contamination before its next turn.',
        'Flowing Current': 'The area is Difficult Terrain for hostiles. When created, one chosen creature there '
                           'makes a Strength save or is pushed or pulled 10 feet into a legal space.',
    }
    return ('Shape Current: Action, 1 Cultivation Point, within 60 feet; Concentration up to 1 minute. '
            'While your Court of the Endless Tide lasts, create one Basin with both forms: '
            + ' '.join(text for form, text in benefits.items() if form in label))


@hook('before_target_reactions')
def choose_flow_recipient(ctx):
    """A paired Flow creation chooses one creature from its actual native area."""
    if not ctx.action.parameters.get('endless_tide_pair') or not ctx.typed.get('endless_tide_flow'):
        return
    from ..target_knowledge import located
    pool = {a.entity_id: a for a in ctx.targets}
    if not pool:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'ENDLESS_TIDE_FLOW', ctx.source),
                   ctx.actor, CHOICE + 'endless_tide_flow', list(pool),
                   automatic_options=[k for k, a in pool.items() if located(ctx.engine, ctx.actor, a)],
                   labels={k: a.display_name for k, a in pool.items()}, name='Shape Current', feature_id=SHAPE,
                   prompt='Shape Current: choose one creature inside your new Flowing Current and Basin. '
                          'It makes a Strength save against a 10-foot push or pull; no additional cost.')
    ctx.targets = [pool[k] for k in selected]


@hook('after_save_resolved')
def failed_water_save(ctx, subject, ability, named, failed):
    if (not failed or subject is None or not subject.active or subject.team_id == ctx.actor.team_id
            or not domains(ctx.engine, ctx.actor)
            or not str(ctx.typed.get('source') or source_of(ctx.engine, ctx.source) or '').startswith(
                ('WATER_BASE_', 'TAL_WATER_'))):
        return
    from .water_defenses import shield_routes
    from .. import movement_paths
    routes = shield_routes(ctx.engine, subject, 10)
    if not routes:
        return
    chosen = ask(ctx.engine, ctx.intent,
                 checkpoint_id(ctx.engine, 'ENDLESS_TIDE_SAVE', subject.entity_id), ctx.actor,
                 CHOICE + 'endless_tide_save', list(routes), allow_decline=True,
                 labels={k: f'Move {subject.display_name} to ({path[-1].x}, {path[-1].y}, {path[-1].z}), '
                         f'{(len(path)-1)*5} feet' for k, path in routes.items()},
                 name='Court of the Endless Tide', feature_id=COURT, target_id=subject.entity_id,
                 prompt=f'Court of the Endless Tide: {subject.display_name} failed a saving throw against '
                        f'{ctx.action.display_name}. Move it up to 10 feet into a legal space, or decline; '
                        'no action or Cultivation Point cost.')
    if chosen:
        movement_paths.resolve(ctx.engine, subject, routes[chosen[0]], COURT, kind='forced', feet=10,
                               intent=ctx.intent, provokes=False, source_actor_id=ctx.actor.entity_id, ctx=ctx)
