"""True Moon Yin Palace: one finite, moving, source-owned Foundation field.

Uses the existing chosen-recipient transport, native slot clock, pending-save
categories and Foundation affinity provider. Unknown provenance is ineligible;
Necrotic damage alone never establishes drain, contamination or anti-healing.
"""
import json

from . import effect, hook
from .needle import ask, checkpoint_id, CHOICE, condition, timed_condition
from .foundation_combat import hostile, roll_names
from ..targeting import line_of_effect

FOUNDATION = 'taiyin_lunar_body_v0_2B'
SOURCE = 'foundation.' + FOUNDATION + '.perfected_true_moon_yin_palace'
STATE = 'condition:typed.true_moon_yin_palace'
PICK = CHOICE + 'true_moon_yin_palace'
USED = 'true_moon_yin_palace_hit'
SPHERES = frozenset('tianxia.sphere.' + s for s in ('yin', 'water', 'dark', 'qiweaving'))
HAZARDS = frozenset({'damage:cold', 'cold', 'necrotic_drain',
                     'corpse_qi_contamination', 'fear_darkness', 'fear_death',
                     'fear_cold', 'hostile_stilling_pressure', 'hostile_stillness',
                     'anti_healing_yin', 'anti_healing_death',
                     'anti_healing_corpse_qi', 'anti_healing_drain'})


@hook('compile_action')
def seal_admission(action, info):
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != SOURCE:
        return action
    foundation = info['owner_sheet'].get('foundation') or {}
    admitted = (foundation.get('foundation_id') == FOUNDATION
                and foundation.get('stage') == 'Perfected')
    return action.model_copy(update={'parameters': {**action.parameters,
        'typed': {**typed, 'palace_admitted': int(admitted)}}})


@effect('taiyin_palace', harmful=False)
def manifest(ctx, eff):
    from ..typed_executor import clock_expiry

    allies = sorted((a for a in ctx.engine.state.actors.values() if a.active
                     and a.team_id == ctx.actor.team_id
                     and ctx.engine._distance_actor_to_actor(ctx.actor, a) <= 30
                     and line_of_effect(ctx.engine, ctx.actor, target=a)), key=lambda a: a.entity_id)
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'PALACE', ctx.source),
                 ctx.actor, PICK, [a.entity_id for a in allies], minimum=0,
                 maximum=len(allies), allow_decline=True, default='all',
                 preferred=[a.entity_id for a in allies],
                 labels={a.entity_id: a.display_name for a in allies},
                 name=ctx.action.display_name, feature_id=SOURCE,
                 prompt='True Moon Yin Palace: choose allies to protect for 1 minute while within 30 feet and an unobstructed path. This uses your Bonus Action and your once-per-long-rest use.')
    timed_condition(ctx.engine, ctx.actor, STATE, ctx.source, ctx.actor.entity_id,
                    clock_expiry(ctx.engine, 'one_minute'),
                    {'chosen': json.dumps(chosen),
                     'label': 'True Moon Yin Palace: chosen allies within 30 feet have Advantage against cold, necrotic drain, corpse-qi contamination, fear from darkness, death or cold, hostile stilling, and Yin, death, corpse-qi or drain anti-healing; once on your turn add Proficiency Bonus damage to an aligned cold, Yin, Water, Dark or Qiweaving technique hit. Lasts 1 minute; Lunar Yin Dew maximum stays 1.'})


def protects(engine, subject, source, named):
    """Live membership, independent of entry order and other Palace owners."""
    names = roll_names(named)
    hazards = names & HAZARDS
    # Native damage producers publish damage type and pressure separately.
    # Neither Necrotic damage alone nor an unqualified drain is necrotic drain.
    if {'damage:necrotic', 'pressure:drain'} <= names:
        hazards.add('necrotic_drain')
    # Only stilling pressure is qualified by hostility in the printed rule.
    if not hostile(source, subject):
        hazards -= {'hostile_stilling_pressure', 'hostile_stillness'}
    if not hazards:
        return False
    for owner in engine.state.actors.values():
        field = condition(owner, STATE)
        if (field and owner.active and field.source_actor_id == owner.entity_id
                and subject.team_id == owner.team_id
                and subject.entity_id in json.loads(field.data['chosen'])
                and engine._distance_actor_to_actor(owner, subject) <= 30
                and line_of_effect(engine, owner, target=subject)):
            return True
    return False


@hook('save')
def pending_save(ctx, subject, ability, named):
    if protects(ctx.engine, subject, ctx.actor, named):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}


@hook('save_mode')
def repeat_save(engine, subject, ability, dc, source_id, context):
    source = engine.state.actors.get((context or {}).get('source_actor_id'))
    if protects(engine, subject, source, (context or {}).get('named')):
        return 'ADVANTAGE'


@hook('hit_snapshot')
def aligned_damage_type(engine, actor, target, attack_context, intent):
    """Freeze this typed strike's delivery type before damage or nested riders.

    The typed resolver scopes _typed_pending_damage_type to the actual strike;
    The receipt reaches attack_damage_bonus in the confirmed strike's spec,
    not via recent damage logs or a later rider's damage type.
    Nonowners and deliveries with no established type contribute no receipt.
    """
    field = condition(actor, STATE)
    packet = getattr(engine, '_typed_damage_packet', None) or {}
    damage_type = getattr(engine, '_typed_pending_damage_type', None)
    if (field and field.source_actor_id == actor.entity_id
            and packet.get('source') == attack_context.source_id
            and packet.get('actor') == actor.entity_id
            and damage_type and str(damage_type).upper() != 'UNTYPED'):
        return {'taiyin_palace': str(damage_type).lower()}


@hook('attack_damage_bonus')
def aligned_hit(ctx, target, effect):
    """Add PB to the confirmed hit's own packet, before mitigation, once per turn."""
    from .foundation_resources import affinity_spheres

    field = condition(ctx.actor, STATE)
    if (ctx.engine.state.current_actor_id != ctx.actor.entity_id
            or field is None or field.source_actor_id != ctx.actor.entity_id
            or ctx.actor.turn_flags.get(USED)):
        return
    sphere = ctx.typed.get('sphere') or ctx.typed.get('sphere_id')
    if not sphere or sphere not in affinity_spheres(FOUNDATION):
        return
    damage_type = (ctx.attack_defense_spec.get('hit_snapshots') or {}).get('taiyin_palace')
    # An untyped hit has no damage type to add to; the bonus is skipped, not guessed.
    if not damage_type:
        return
    # Cold is a printed technique category as well as a damage type: the
    # sealed source must independently establish Foundation compatibility.
    # A physical Ice construct is not automatically a cold hit, while an
    # actually cold hit from another compatible sphere still qualifies.
    if sphere not in SPHERES and damage_type != 'cold':
        return
    ctx.actor.turn_flags[USED] = 1
    return int(ctx.actor.proficiency_bonus)


@hook('candidate_allowed')
def conscious_activation(engine, actor, candidate, action):
    if action is None:  # ordinary actions (end turn, moves) carry no catalog row
        return None
    typed = action.parameters.get('typed') or {}
    if typed.get('source') != SOURCE:
        return None
    # Consciousness is narrower than having Hit Points: magical sleep also bars it.
    if (not typed.get('palace_admitted') or not actor.active or actor.current_hp <= 0
            or any(c.condition_id in {'condition:typed.unconscious',
                                     'condition:typed.life_unconscious',
                                     'condition:typed.asleep'} for c in actor.conditions.values())):
        return False
    return None


@hook('journey_rest')
def restore_palace(session, actor_id):
    """Recover only the Palace's own once-long-rest use after the real eight-hour rest.

    Only a uses counter that no other owned action spends is the Palace's own:
    a counter shared with another ability is left exactly as paid. The write
    happens inside the enclosing long_rest transaction, so a failed hook rolls
    it back with the rest; the journey already carries exact paid balances.
    """
    actor = session.state['actors'][actor_id]
    catalog = actor['bundle'].get('action_catalog', [])

    def typed_of(row):
        return (row.get('parameters') or {}).get('typed') or {}

    def uses_of(row):
        return [pool for pool, _ in (row.get('costs') or []) if pool.startswith('resource:uses.')]

    palace = [row for row in catalog if typed_of(row).get('source') == SOURCE and typed_of(row).get('palace_admitted')]
    shared = {pool for row in catalog if row not in palace for pool in uses_of(row)}
    own = {pool for row in palace for pool in uses_of(row)} - shared
    for pool in sorted(own):
        if pool not in actor['resources']:
            continue
        before = actor['resources'][pool]
        actor['resources'][pool] = 1
        if before != 1:
            session.emit('RESOURCE_RECOVERED', actor_id, source=SOURCE,
                         resource_id=pool, amount=1 - before,
                         text=f"{actor['name']} can use True Moon Yin Palace again after this Long Rest.")
