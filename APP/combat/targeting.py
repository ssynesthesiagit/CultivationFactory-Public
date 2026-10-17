"""Owner's 2026-10-06 targeting ruling, shared by recipients and attacks.

Sight delegates to target_knowledge/senses (the tabletop fog policy). Effect
paths reuse effect_cover.rays' physical geometry, ignoring visual obscurement.
Candidate generation, attack resolution and area origins use this one policy.
"""
from .gate2_runtime_models import DiceSpec
from functools import lru_cache
import json
from pathlib import Path
from .read_queries import pure


@lru_cache(maxsize=1)
def rules():
    return json.loads((Path(__file__).parent / 'rules' / 'targeting.json').read_text())


POLICY_KEYS = ('concealment_miss_percent', 'total_concealment_miss_percent')
LEGACY_POLICY = {'concealment_miss_percent': 20, 'total_concealment_miss_percent': 50}


def policy(engine):
    """Fight-scoped settings shared by attacks, menus and zone hover cards.

    New genesis events bind the configured integers without changing the state
    schema. Compatibility supplies a transient policy while replaying unstamped
    saves and persists it in the existing continuation event for ordinary loads.
    Engines without saved history (including portable previews) use rule data.
    """
    bound = getattr(engine, '_saved_targeting_policy', None)
    if bound is None:
        for event in reversed(getattr(engine, 'events', ())):
            if event.event_type in {'MATCH_CREATED', 'SAVED_FIGHT_CONTINUED'}:
                bound = event.payload.get('targeting_policy')
                if bound is not None:
                    break
    return dict(bound if bound is not None else rules())


def remembered_square_label(engine, actor, target):
    """General candidate wording; an optional percentage follows fight policy."""
    percent = policy(engine).get('total_concealment_miss_percent', 0)
    # The prepared-candidate journal binds presentation bytes as well as intent.
    # Only compatibility re-execution of unstamped saves uses the old wording;
    # a continuation's live menu always uses the plain current wording below.
    if getattr(engine, '_replaying_legacy_target_label', False) and percent > 0:
        return (f'Attack the square where you last saw {target.display_name} '
                f'({percent}% chance to miss because you cannot see it)')
    from .attack_modes import presentation_modes
    modes = presentation_modes(engine, actor, target)
    if modes == {'ADVANTAGE', 'DISADVANTAGE'}:
        mode = 'normal roll: your Advantage cancels it'
    elif modes == {'DISADVANTAGE'}:
        mode = 'Disadvantage'
    elif modes == {'ADVANTAGE'}:
        mode = 'Advantage'
    else:
        mode = 'normal roll: no Disadvantage applies'
    label = (f'Attack the square where you last saw {target.display_name} — '
             f'{mode}; a miss if nobody is there')
    if percent > 0:
        label += f'; {percent}% miss chance because you cannot see the target'
    return label


def line_of_effect(engine, actor, *, target=None, destination=None):
    """Any clear footprint ray, including finite-height solid obstacles."""
    from .effect_cover import rays
    from .gate2_runtime_models import Position
    starts = engine._effect_volume(actor)
    ends = engine._actor_volume(target) if target is not None else (destination,)
    if target is not None:
        from .shot_geometry import route
        routed = route(engine, actor, target)
        if routed:
            path = [Position(**p) for p in routed['path']]
            return all(next(rays(engine, (a,), (b,), purpose='effect'), None) is not None
                       for a, b in zip(path, path[1:]))
    return next(rays(engine, starts, ends, purpose='effect'), None) is not None


@pure
def reason(engine, actor, target, action):
    """Pure recipient denial; self and area recipients are unaffected."""
    from .target_knowledge import can_see, is_attack, knowledge
    if target is actor or action.target_kind in {'SELF', 'SELF_OR_CELL', 'CELL'}:
        return None
    if not is_attack(action) and not can_see(engine, actor, target):
        return "Can't target: no line of sight."
    known = knowledge(engine, actor, target, action)
    if known is None:
        return "Can't target: no line of sight or known square to attack."
    clear = (line_of_effect(engine, actor, destination=known.position) if known.mode == 'LAST_OBSERVED'
             else line_of_effect(engine, actor, target=target))
    if not clear:
        return "Can't target: no line of effect; a solid obstacle blocks the path."
    return None


@pure
def in_range(engine, actor, target, action, known=None):
    """Recipient and portable range queries measure a remembered aim, never hidden movement."""
    from .target_knowledge import knowledge
    from .attack_reach import maximum
    known = known or knowledge(engine, actor, target, action)
    if known is None:
        return False
    if known.mode == 'LAST_OBSERVED':
        limit = maximum(engine, actor, action)
        return limit is None or engine._effect_distance_to_cell(actor, known.position) <= limit
    return engine._target_in_range(actor, target, action)


def concealment_percent(engine, actor, target):
    """Optional fight-bound visual concealment check; absent/zero is inert."""
    from .target_knowledge import can_see
    from . import senses, zones
    configured = policy(engine)
    if not any(configured.get(key, 0) for key in POLICY_KEYS):
        return 0
    if not can_see(engine, actor, target):
        return configured.get('total_concealment_miss_percent', 0)
    if senses.perceives_without_sight(engine, actor, target):
        return 0
    for zone in concealment_zones(engine):
        profile = zone.trigger_profile
        lightly_obscured = (profile.get('lightly_obscured') is True or profile.get('obscured') == 'light'
                            or (profile.get('visual') or {}).get('light') == 'dim')
        if lightly_obscured and zones._inside(engine, target, zone):
            return configured.get('concealment_miss_percent', 0)
        # Smoke's chosen allies see its heavy veil as lightly obscured.
        if profile.get('obscured') == 'heavy' and profile.get('team_sees') and zones._inside(engine, target, zone):
            owner = engine.state.actors.get(zone.owner_id)
            if owner is not None and owner.team_id == actor.team_id and actor.entity_id != owner.entity_id:
                return configured.get('concealment_miss_percent', 0)
    return 0


def concealment_zones(engine):
    """Active stored, map and hook zones, regardless of their producer's kind.

    Only attack resolution calls this query; it adds no table-refresh work.
    Deduplicate typed stored zones already included by the shared zone query.
    """
    from . import zones
    represented = {zone.zone_id: zone for zone in zones.typed_zones(engine)}
    represented.update((zone.zone_id, zone) for zone in engine.state.zones.values() if zone.active)
    return represented.values()


def concealment_missed(engine, actor, target, source, index=1):
    """One evented percentile roll per attack attempt, before its d20 roll."""
    percent = concealment_percent(engine, actor, target)
    if not percent:
        return False
    roll = engine.roller.roll(DiceSpec(count=1, sides=100, modifier=0),
                              actor_id=actor.entity_id, reason='CONCEALMENT_MISS_CHANCE')
    engine._record_roll(roll)
    missed = roll.total <= percent
    from .target_knowledge import can_see
    engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
        target_ids=(target.entity_id,), payload={'roll_id': roll.roll_id, 'attack_index': index,
        'miss_chance_percent': percent, 'missed': missed,
        'log': f'{actor.display_name} attacks {target.display_name} with {percent}% miss chance '
               f'because the target is {"unseen" if not can_see(engine, actor, target) else "partly obscured"}: '
               f'rolled {roll.total} out of 100; ' + ('the attack misses before the attack roll.' if missed else 'make the attack roll.')})
    return missed


def attack_line_of_effect(engine, actor, target, source):
    """Area attacks need effect to their origin; area selection clips propagation.

    Creature attacks use the defender ray. CELL spheres use the chosen cell;
    self emanations and directional areas originate at the acting source.
    """
    action = engine.action_catalog.get(source)
    if action is not None and action.target_kind in {'SELF', 'SELF_OR_CELL', 'CELL'}:
        area = (action.parameters.get('typed') or {}).get('area') or {}
        if area.get('size_ft') or action.radius_ft is not None:
            from .action_geometry import point
            candidate = getattr(engine, '_active_candidate', None)
            origin = point(engine, actor)
            if (area.get('shape', 'sphere') not in {'line', 'cone', 'wall'}
                    and candidate is not None and candidate.actor_id == actor.entity_id
                    and candidate.source_definition_id == source and candidate.destination is not None):
                origin = candidate.destination
            return line_of_effect(engine, actor, destination=origin)
    return line_of_effect(engine, actor, target=target)


def attack_missed(engine, actor, target, source, index=1, *, spec=None):
    """Native and portable final targeting checkpoint; no d20 on failure.

    An optional transient spec['before_attack_d20'] callback receives
    (engine, actor, target, spec) only after all targeting checks pass. It may
    shape that upcoming roll or pause for consent; absent callbacks are inert.
    This seam is shared by every typed attack, never persisted in fight state.
    """
    from .target_knowledge import location_missed
    if location_missed(engine, actor, target, source, index):
        return True
    if not attack_line_of_effect(engine, actor, target, source):
        engine._append_event('PASSIVE_TRIGGERED', source, actor_id=actor.entity_id,
            payload={'log': 'The attack misses: a solid obstacle blocks line of effect.'})
        return True
    missed = concealment_missed(engine, actor, target, source, index)
    if missed and spec is not None:
        spec['concealment_missed'] = True  # An actual miss, with no attack d20.
    if not missed and spec is not None and spec.get('before_attack_d20'):
        spec['before_attack_d20'](engine, actor, target, spec)
    return missed
