"""Hearthward Pavilion: a fixed 20-foot sanctuary built around a live Kindled Hearth.

Only the owned reviewed record (reviewed_final.d/zz_redo_hearthward_pavilion.json)
creates this field. The Pavilion needs an active Hearth, is centred on that Hearth
when created, and stays where it was built when the Hearth is carried later.
Chosen allies inside gain +1 AC, Advantage against Charmed and Frightened, and
Advantage against environmental cold and exposure. Ordinary weather discomfort
does not affect a protected ally. Weatherward entry blocking, Private Hearth
speech, and Civic Shelter capacity are not implemented here (see the report).
"""
from . import effect, hook
from .qi_hearthfire import BASE, hearths
from .qi_welcoming_flame import ordinary

SOURCE = BASE + 'hearthward_pavilion'
CONDITIONS = {'charmed', 'frightened'}
CATEGORIES = {'environmental_cold', 'environmental_exposure_exhaustion'}


@hook('compile_action')
def self_built(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') == SOURCE and any(e.get('type') == 'qi_hearthward_pavilion' for e in typed.get('effects') or []):
        # The effect builds its own 20-foot field, centred on the Hearth.
        return action.model_copy(update={'target_kind': 'SELF', 'range_ft': None,
            'parameters': {**action.parameters, 'typed': {**typed, 'area': None, 'zone_spec': {}}}})


@hook('candidate_allowed')
def needs_hearth(engine, actor, candidate, action):
    typed = (action.parameters or {}).get('typed') or {} if action is not None else {}
    if any(e.get('type') == 'qi_hearthward_pavilion' for e in typed.get('effects') or []):
        return bool(hearths(engine, actor))


def fields(engine):
    return [z for z in engine.state.zones.values() if z.active
            and (z.trigger_profile.get('profile') or {}).get('hearthward_pavilion')]


def protects(engine, zone, subject):
    from ..relations import ALLY, relation
    from ..spatial_areas import zone_contains
    owner = engine.state.actors.get(zone.owner_id)
    return (owner is not None and subject.entity_id in zone.trigger_profile['profile']['recipients']
            and relation(engine, owner, subject) == ALLY and zone_contains(engine, subject, zone))


def guarded(engine, subject):
    return [z for z in fields(engine) if protects(engine, z, subject)]


@effect('qi_hearthward_pavilion', harmful=False)
def build(ctx, row):
    from dataclasses import replace
    from .. import zones
    from .needle import ask, CHOICE, checkpoint_id
    from . import ai_controlled
    from ..target_knowledge import can_see
    from ..relations import ALLY, relation
    active = hearths(ctx.engine, ctx.actor)
    if not active:
        raise ValueError('Hearthward Pavilion requires an active Kindled Hearth.')
    allies = [a for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine, ctx.actor, a) == ALLY]
    ids = [a.entity_id for a in allies]
    if ai_controlled(ctx.engine, ctx.actor):
        chosen = [a.entity_id for a in allies if can_see(ctx.engine, ctx.actor, a)]
    else:
        chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'pavilion_recipients', ctx.actor.entity_id), ctx.actor,
            CHOICE + 'pavilion_recipients', ids, preferred=ids, minimum=0, maximum=len(ids),
            allow_decline=True, default='all', labels={a.entity_id: a.display_name for a in allies},
            feature_id=SOURCE, name='Hearthward Pavilion',
            prompt='Hearthward Pavilion: choose the allies and invited guests inside the 20-foot sanctuary for 8 hours.')
    intent = ctx.intent.model_copy(update={'destination': active[0].center})
    zones.create(replace(ctx, intent=intent), {'name': 'Hearthward Pavilion', 'shape': 'cylinder',
        'size_ft': 20, 'height_ft': 20, 'duration': {'kind': 'hours', 'amount': 8},
        'profile': {'hearthward_pavilion': 1, 'recipients': chosen}, 'inside': [], 'triggers': [],
        'visual': {'material': 'fire'}})


@hook('ac')
def armor(engine, subject):
    return 1 if guarded(engine, subject) else None


@hook('save_effects')
def saves(ctx, subject, ability, fail_effects, success_effects, categories):
    from ..typed_executor import _walk_rows
    named = {e.get('condition') for e in _walk_rows(fail_effects)}
    if (named & CONDITIONS or set(categories) & CATEGORIES) and guarded(ctx.engine, subject):
        return {'modes': ['ADVANTAGE']}


@hook('effect_subject_allowed')
def ordinary_immunity(ctx, effect, subject):
    """Printed immunity: ordinary weather discomfort does not affect a protected ally."""
    if ordinary(effect) and guarded(ctx.engine, subject):
        return False
