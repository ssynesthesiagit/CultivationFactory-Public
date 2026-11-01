"""Dream Qi combat rules sealed in reviewed rows (A2GQISUB10).

Dream Ward uses native save_mode/d20_bonus, including typed saving throws.
Only explicit Dream/Illusion provenance or printed adverse conditions qualify.
The failed-roll rescue is optional, evented and once per scene (one fight).
Lucid Strike uses ordinary typed damage, saves, expiry and delivery; the fifth
Distortion adds a source-owned visibility marker through existing sight hooks.
Rest recovery/awareness are outside this combat provider.
"""
from . import effect, hook

WARD = 'tianxia.subpath.qi.dream_qi_cultivator.feature.dreamer_s_rest'
BLOCK = 'dream_ward'
USED = 'condition:typed.dream_ward_used'
HORIZON = 'condition:typed.lucid_horizon'


@effect(BLOCK)
def ward_declaration(ctx, row):
    pass  # compiled passive declaration; not an activation


@hook('compile_actions')
def compile_ward(info):
    record = info['mechanics'].get(WARD) or {}
    if WARD in info['owned_ids'] and any(e.get('type') == BLOCK for e in record.get('effects') or []):
        info['passives'].append({'feature_id': WARD, 'block': BLOCK, 'numbers': dict(info['numbers'])})


def _ward(engine, actor):
    return next((r for r in (getattr(engine, 'typed_passive_rows', {}) or {}).get(actor.entity_id, [])
                 if r.get('block') == BLOCK), None)


def _qualifies(engine, source, named):
    names = {str(n).lower() for n in named or ()}
    if names & {'charmed', 'frightened', 'dream_sleep', 'asleep', 'category:dream', 'category:illusion', 'category:sleep'}:
        return True
    action = engine.action_catalog.get(source)
    typed = ((action.parameters or {}).get('typed') or {}) if action else {}
    return (typed.get('sphere') in {'tianxia.sphere.dreams', 'tianxia.sphere.illusion'}
            or bool(set(typed.get('tags') or []) & {'dream', 'illusion'})
            or str(typed.get('option_of') or typed.get('source') or '').startswith('tianxia.subpath.qi.dream_qi_cultivator.feature.'))


@hook('save_mode')
def ward_mode(engine, actor, ability, dc, source, metadata):
    if _ward(engine, actor) and _qualifies(engine, source, metadata.get('conditions') or metadata.get('named')):
        return 'ADVANTAGE'


@hook('d20_bonus')
def ward_rescue(engine, roll, intent):
    metadata = engine.d20_context(roll) or {}
    # Signed save totals are valid; eligibility comes from the save context.
    if metadata.get('kind') != 'save' or not metadata.get('dc'):
        return None
    actor = engine.state.actors.get(roll.actor_id)
    row = _ward(engine, actor) if actor else None
    if not row or not _qualifies(engine, metadata.get('source_id'), metadata.get('conditions') or metadata.get('named')):
        return None
    pb = int(row['numbers'].get('pb') or 2)
    if not roll.total < metadata['dc'] or any(c.condition_id == USED for c in actor.conditions.values()):
        return None
    from .needle import ask, checkpoint_id
    source_id = str(metadata.get('source_id') or getattr(engine, '_active_action_source_id', '') or '')
    reason = str(getattr(roll, 'reason', '') or '')
    if not source_id and reason.startswith('SAVE:'):
        source_id = reason[5:].rpartition(':')[0]
    action = engine.action_catalog.get(source_id)
    source_actor = engine.state.actors.get(action.owner_id) if action is not None else None
    from .choice_prompt import action_context
    prompt_context = action_context(engine, source_actor, source_id, actor, action=action)
    action_name = action.display_name if action is not None else 'the triggering effect'
    take = ask(engine, intent, checkpoint_id(engine, 'dream_ward', roll.roll_id), actor,
               'choice:needle.dream_ward', ['rescue'], minimum=0, maximum=1, allow_decline=True,
               labels={'rescue': f'Dream Ward: add {pb} to this failed save (once this scene)'}, preferred=['rescue'], automatic_options=(['rescue'] if roll.total+pb>=metadata['dc'] else []),
               prompt=f'Dream Ward: add {pb} to {actor.display_name}’s failed save against {action_name} (once this scene)?',
               prompt_context=prompt_context)
    if not take:
        return None
    engine._apply_condition(actor, USED, 'passive:'+WARD, actor.entity_id, expires_on='UNTIL_REMOVED',
                            data={'label':'Dream Ward rescue used this scene'})
    return {'source_id':'passive:'+WARD, 'bonus':pb}


@effect('lucid_horizon', harmful=True)
def horizon(ctx, row):
    if ctx.target:
        ctx.engine._apply_condition(ctx.target, HORIZON, ctx.source, ctx.actor.entity_id,
                                    expires_on='START_OF_SOURCE_NEXT_TURN', data={'label':'Shifting Horizon: visible to the dreamer'})


def _horizon(subject, viewer):
    return subject is not None and viewer is not None and any(c.condition_id == HORIZON and c.source_actor_id == viewer.entity_id
                                                              for c in subject.conditions.values())


def _ordinary_visual_hide(engine, viewer, seen):
    """Whether native Hide is supported by an ordinary visual obscurer here.

    Hidden remains meaningful behind physical sight barriers and in magical or
    superior concealment. Horizon lifts only an ordinary visual area; matching
    that area here removes the native Hide rider without changing line of sight.
    """
    from .. import zones
    from .darkness_scope import scope
    if zones.ordinary_visual_wall_between(engine, viewer, seen):
        return True
    for zone in zones.typed_zones(engine):
        profile = zone.trigger_profile
        visual = profile.get('visual') or {}
        if not (profile.get('obscured') == 'heavy' or visual.get('darkness')) or scope(engine, zone) != 'ordinary':
            continue
        viewer_in, seen_in = zones._inside(engine, viewer, zone), zones._inside(engine, seen, zone)
        inward = visual.get('sees') == 'inward'
        if (viewer_in and seen_in) or (seen_in and not inward) or (viewer_in and inward):
            return True
    return False


@hook('masked_conditions')
def horizon_sight(engine, attacker, target):
    out = {}
    for who, viewer in ((target, attacker), (attacker, target)):
        if _horizon(who, viewer):
            out[who.entity_id] = {iid for iid, c in who.conditions.items()
                                  if c.condition_id.endswith('.invisible')
                                  or (c.condition_id.endswith('.hidden') and c.data.get('stealth_total') is not None
                                      and _ordinary_visual_hide(engine, viewer, who))}
    return out or None


@hook('darkness_lifted')
def horizon_concealment(engine, zone, viewer, seen):
    from .darkness_scope import scope
    if _horizon(seen, viewer) and scope(engine, zone) == 'ordinary':
        return True


@hook('zone_obscuration_ignored')
def horizon_ordinary_concealment(engine, zone, viewer, seen):
    from .darkness_scope import scope
    if _horizon(seen, viewer) and scope(engine, zone) == 'ordinary':
        return True
