"""Divine King Body generation from completed, source-attributed effects.

One pressure generator owns all three alternatives, cap, round clock and expiry.
The old generic failed-save row is replaced at compilation, not wrapped at runtime.
Named spheres identify eligible manifestations; actual outward deliveries and
perception establish meaningful visible use, never sphere ownership alone.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from . import hook, note

GENERATE = 'foundation.divine_king_body_v0_2B.generate_moon_sea_radiance'
POOL = 'resource:foundation.moon_sea_radiance'
REASON = 'moon_sea_completed'
SPHERES = {'radiance', 'water', 'protection', 'force', 'stars', 'qiweaving', 'spirit_companions'}
_resolution = ContextVar('moon_sea_resolution', default=None)


@hook('compile_bundle')
def generation_bundle(bundle, info):
    from pathlib import Path
    from ..authority_cache import read_authority

    rows = bundle.get('typed_reactions', [])
    if not any(r.get('feature_id') == GENERATE for r in rows):
        return None
    mechanics = read_authority(Path(__file__).resolve().parents[2] /
        'authority/Tianxia_Typed_Mechanics_Authority_R1.json')[0]['mechanics']
    def protective(tree):
        if isinstance(tree, dict):
            return tree.get('type') in ('damage_modifier', 'half_damage', 'resistance', 'immunity') \
                or any(protective(v) for v in tree.values())
        return isinstance(tree, list) and any(protective(v) for v in tree)

    protection_sources = [fid for fid in dict.fromkeys(r['feature_id']
        for r in [*rows, *bundle.get('typed_passives', [])])
        if _eligible({'sphere': mechanics.get(fid, {}).get('sphere_id')})
        and protective(mechanics.get(fid, {}).get('effects', []))]
    protection_sources.append('foundation.divine_king_body_v0_2B.sea_moon_interposition')
    return {**bundle,
        'typed_reactions': [r for r in rows if r.get('feature_id') != GENERATE],
        'typed_passives': [*bundle.get('typed_passives', []),
            {'feature_id': GENERATE, 'block': 'generate', 'resource_id': POOL,
             'on': [REASON], 'max': 1, 'per_round': 1, 'expires': 'end_of_next_turn',
             'cp_resource': 'resource:core.' + info['primary'],
             'protection_sources': protection_sources}]}


def _owns(engine, actor):
    return actor is not None and any(r.get('feature_id') == GENERATE
        for r in engine.typed_passive_rows.get(actor.entity_id, []))


def _generation(engine, actor):
    return next(r for r in engine.typed_passive_rows[actor.entity_id] if r.get('feature_id') == GENERATE)


def _visible(engine, actor, other):
    from ..senses import cell_probe, perceives
    # Visibility belongs to the manifestation at its recipient, not to the
    # caster's body or to the recipient's ability to see the caster. An
    # Invisible caster or Blinded victim does not hide a visible water effect.
    return (other is not None and other.entity_id != actor.entity_id
            and (perceives(engine, actor, cell_probe(other.position), sight_only=True)
                 or perceives(engine, other, cell_probe(other.position), sight_only=True)))


def _eligible(typed):
    return str(typed.get('sphere') or '').removeprefix('tianxia.sphere.') in SPHERES


def _gain(engine, actor, source):
    from .. import pressure
    if not _owns(engine, actor) or any(c.condition_id.rsplit('.', 1)[-1] == 'unconscious'
                                      for c in actor.conditions.values()):
        return
    if pressure.generate(engine, actor, REASON):
        note(engine, GENERATE, actor,
             f'{actor.display_name} gains 1 Moon-Sea Radiance after the visible effect resolves. '
             'Maximum 1, once per round; expires at the end of their next turn. '
             'It can only be spent on a later event.', triggering_source=source)


def _journal(ctx):
    return ctx.engine.events[getattr(ctx, 'technique_event_start', len(ctx.engine.events)):]


@hook('technique_used')
def completed_technique(ctx):
    engine, owner = ctx.engine, ctx.actor
    if not _owns(engine, owner) or not _eligible(ctx.typed):
        return
    events = list(_journal(ctx))
    # Payment must be an actual debit by this actor for this accepted use.
    # The technique window starts after payment; scan back only to its intent.
    paid = False
    for event in reversed(engine.events):
        if event.event_type == 'INTENT_ACCEPTED':
            break
        if (event.event_type == 'RESOURCE_SPENT' and event.actor_id == owner.entity_id
                and event.source_definition_id == ctx.source
                and (event.payload or {}).get('resource_id') == _generation(engine, owner)['cp_resource']
                and int((event.payload or {}).get('amount') or 0) > 0):
            paid = True
    meaningful = False
    for event in events:
        if event.source_definition_id != ctx.source:
            continue
        payload = event.payload or {}
        if event.event_type == 'SAVE_ROLLED':
            subject = engine.state.actors.get(event.actor_id)
            meaningful |= _visible(engine, owner, subject) and subject.team_id != owner.team_id
        if event.actor_id != owner.entity_id:
            continue
        for aid in event.target_ids:
            subject = engine.state.actors.get(aid)
            if not _visible(engine, owner, subject):
                continue
            if event.event_type in ('CONDITION_APPLIED', 'MODIFIER_APPLIED', 'FORCED_MOVEMENT_COMMITTED'):
                meaningful = True
            elif event.event_type == 'ATTACK_ROLLED' and subject.team_id != owner.team_id:
                meaningful = True  # a genuinely contested manifestation can miss
            elif event.event_type == 'DAMAGE_COMMITTED' and subject.team_id != owner.team_id:
                meaningful |= int(payload.get('hp_damage') or 0) + int(payload.get('temporary_hp_absorbed') or 0) > 0
        if event.event_type == 'ZONE_CREATED':
            zone = payload.get('zone') or {}
            cells = {(p['x'], p['y']) for p in zone.get('affected_cells', [])}
            meaningful |= any(a.team_id != owner.team_id and _visible(engine, owner, a)
                              and (a.position.x, a.position.y) in cells for a in engine.state.actors.values())
    if paid and meaningful:
        _gain(engine, owner, ctx.source)


@hook('effect_resolution_scope')
def completed_effect_scope(ctx, effect):
    if not _owns(ctx.engine, ctx.actor) or not _eligible(ctx.typed):
        return None
    return _effect_scope(ctx)


@contextmanager
def _effect_scope(ctx):
    frame = _resolution.get()
    if frame is not None and frame[:2] == (ctx.engine, ctx.actor.entity_id):
        yield
        return
    pending = []
    token = _resolution.set((ctx.engine, ctx.actor.entity_id, pending))
    try:
        yield
        if pending:
            _gain(ctx.engine, ctx.actor, ctx.source)
    finally:
        _resolution.reset(token)


def _failed_roll(ctx):
    frame = _resolution.get()
    if frame is not None and frame[:2] == (ctx.engine, ctx.actor.entity_id):
        frame[2].append(True)


@hook('save_final')
def completed_save(ctx, subject, ability, named, failed):
    if (failed and _owns(ctx.engine, ctx.actor) and _eligible(ctx.typed)
            and subject.team_id != ctx.actor.team_id and _visible(ctx.engine, ctx.actor, subject)):
        _failed_roll(ctx)


@hook('opposed_check_resolved')
def completed_check(ctx, target, result, actor_check, target_check):
    if (not _owns(ctx.engine, ctx.actor) or not _eligible(ctx.typed)
            or not _visible(ctx.engine, ctx.actor, target) or target.team_id == ctx.actor.team_id
            or target_check.get('kind') in ('save', 'dc') or not result.success):
        return
    # This is a settled defending ability check, not the user's failed check.
    # Defer the grant until the enclosing effects (including consequences) end.
    _failed_roll(ctx)


@hook('event', nested=True)
def completed_protection(engine, event_type, kwargs):
    if event_type != 'REACTION_RESOLVED':
        return
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if not _owns(engine, owner):
        return
    payload = kwargs.get('payload') or {}
    before, after = payload.get('pending_before'), payload.get('pending_after')
    if type(before) is not int \
            or type(after) is not int or not 0 <= after < before:
        return
    target_ids = kwargs.get('target_ids') or ()
    protected_id = (payload.get('protects') or owner.entity_id) if payload.get('checkpoint') == 'DAMAGE_APPLICATION' \
        else (target_ids[0] if len(target_ids) == 1 else None)
    protected = engine.state.actors.get(protected_id)
    if protected is None or protected.team_id != owner.team_id:
        return
    source = kwargs.get('source_definition_id')
    row = next((r for r in engine.typed_reaction_rows.get(owner.entity_id, [])
                if r.get('feature_id') == source), None)
    if row is not None and any(e.get('type') in ('redirect_damage_to_self', 'hold_at_1hp')
                               for e in row.get('effects', [])):
        return
    if source not in _generation(engine, owner)['protection_sources']:
        return
    if protected.entity_id != owner.entity_id and not _visible(engine, owner, protected):
        return
    _gain(engine, owner, source)
