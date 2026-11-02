"""Gathered Weather: sealed zone profile, compatible signs and per-target queries.

Shared helper contract: fields/signs/severity are read by weather_shroud for
matching-weather saves and resistance cracking; this module also uses them for
Weather Cut, Storm Birth, Finger, and Rain Mantle damage defenses. These readers
inspect opt-in active fields, preserve occupied-cell volume and LoE, and accept
owner=None for unscoped matching weather. They never mutate field state.

No ambient damage is invented. Exposure/travel and narrative climate remain
procedures. Every combat query uses current volume membership and LoE. Existing
zones without profile.weather_field are inert, including historical saves.
"""
from __future__ import annotations
from typing import Any
from . import effect, hook
from . import weather_signs
from .needle import ask, CHOICE, checkpoint_id
from .choice_costs import payable
from .retained_updates import record_zone_update

BASE = 'WEATHER_BASE_GATHER_WEATHER'
FOUNDATION = 'TAL_WEATHER_FOUNDATION_WEATHER_FIELD'
CORE = 'TAL_WEATHER_CORE_WEATHER_FIELD'
SHIFT = 'TAL_WEATHER_SUDDEN_SHIFT'
CUT = 'TAL_WEATHER_WEATHER_CUT'
STORM = 'TAL_WEATHER_STORM_BIRTH'
SEVERE = 'TAL_WEATHER_SEVERE_SHROUD'
CP = 'resource:core.qi'
OPPOSED = {'cold': 'heat', 'heat': 'cold', 'rain': 'dry', 'dry': 'rain'}


def fields(engine, owner=None):
    from ..zones import typed_zones
    return [z for z in typed_zones(engine) if (z.trigger_profile.get('profile') or {}).get('weather_field') == 1
            and any(int(level) > 0 for level in ((z.trigger_profile.get('profile') or {}).get('signs') or {}).values())
            and (owner is None or z.owner_id == owner.entity_id)]


def signs(zone):
    return zone.trigger_profile['profile']['signs']


def _levels_at(engine, owner, point):
    from ..typed_executor import in_area
    all_levels, owned_levels = {}, {}
    # Resolve each occupied cell and LoE separately. A weather category has a
    # severity, rather than stacking repeated casts of the same category.
    for z in fields(engine):
        if not in_area(engine, z.center, z.center, point, z.trigger_profile):
            continue
        for name, raw in signs(z).items():
            level = int(raw)
            all_levels[name] = max(all_levels.get(name, 0), level)
            if owner is None or z.owner_id == owner.entity_id:
                owned_levels[name] = max(owned_levels.get(name, 0), level)
    values = {name: max(0, level - all_levels.get(OPPOSED.get(name), 0))
              for name, level in owned_levels.items()}
    return values


def _level(values, sign):
    return (min(values.get('wind', 0), max(values.get('rain', 0), values.get('dry', 0)))
            if sign == 'thunder' else values.get(sign, 0))


def severity(engine, owner, target, sign):
    from ..spatial_areas import actor_positions
    return max((_level(_levels_at(engine, owner, point), sign)
                for point in actor_positions(engine, target)), default=0)


@hook('compile_action')
def gather_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != BASE:
        if any(row.get('type') == 'weather_sky_mantle' or any(
                child.get('type') == 'weather_sky_mantle' for child in row.get('effects') or [])
                for row in typed.get('effects') or []):
            return action.model_copy(update={'parameters': {**action.parameters,
                'typed': {**typed, 'weather_field_policy': 1}}})
        return None
    radius = 60 if CORE in info['owned_ids'] else 30 if FOUNDATION in info['owned_ids'] else 20
    # Compose an immutable action replacement through the documented hook.
    parameters = {**action.parameters, 'typed': {**typed, 'area': {'shape': 'sphere', 'size_ft': radius}, 'zone_spec': {},
        'effects': [{'type': 'weather_gather', 'radius': radius,
                     'maximum': 3 if CORE in info['owned_ids'] else 2 if FOUNDATION in info['owned_ids'] else 1,
                     'dual': CORE in info['owned_ids']}], 'riders': []}}
    return action.model_copy(update={'target_kind':'CELL','range_ft':action.range_ft,'radius_ft':radius,'parameters':parameters})


def choose(ctx, options, suffix, prompt, *, optional=False, name='Gather Weather'):
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, suffix, ctx.actor.entity_id), ctx.actor,
               CHOICE + 'weather_field_' + suffix.lower(), options, labels={s: s.title() for s in options},
               name=name, feature_id=BASE, prompt=prompt,
               allow_decline=optional, default='decline' if optional else 'first')


@effect('weather_gather')
def gather(ctx, spec):
    from .. import zones
    maximum = int(spec['maximum'])
    options = [s for s in weather_signs.names() if s != 'thunder']
    picked = choose(ctx, options, 'GATHER_SIGN', 'Choose the Weather Sign you know to gather. Thunder requires a storm.')
    if not picked:
        return
    values = {picked[0]: 1}
    if spec.get('dual'):
        second = choose(ctx, [s for s in options if s != picked[0] and s != OPPOSED.get(picked[0])],
                        'SECOND_SIGN', 'You may maintain a second compatible sign in this field.', optional=True)
        if second:
            values[second[0]] = 1
    # Each gathered sign pays its own printed severity surcharge.
    for s in list(values):
        costs = {1: 0, 2: 2, 3: 4}
        offered = [str(n) for n in range(1, maximum + 1) if ctx.actor.resources.get(CP, 0) >= costs[n]]
        selected = choose(ctx, offered, 'SEVERITY_' + s, f'Choose {s.title()} severity: 1 costs no extra Cultivation Points; '
                          '2 costs 2 extra Cultivation Points; 3 costs 4 extra Cultivation Points.')
        level = int(selected[0]) if selected else 1
        if costs[level]:
            ctx.engine._spend_resource(ctx.actor, CP, costs[level], ctx.source)
        values[s] = level
    zone = zones.create(ctx, {'shape': 'sphere', 'size_ft': int(spec['radius']), 'placed': 1,
        'name': 'Gather Weather', 'duration': {'kind': 'minutes', 'amount': 1, 'concentration': True},
        'profile': {'weather_field': 1, 'signs': values}})
    if zone is None:
        return
    record_zone_update(ctx.engine, zone)


@hook('candidate_allowed')
def shift_allowed(engine, actor, candidate, action):
    if action is not None and any(r.get('type') == 'weather_shift' for r in ((action.parameters or {}).get('typed') or {}).get('effects') or []):
        return bool(fields(engine, actor))
    return None


@effect('weather_shift')
def shift(ctx, spec):
    found = fields(ctx.engine, ctx.actor)
    if not found:
        return
    z = found[0]
    if len(found) > 1:
        selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SHIFT_FIELD', ctx.actor.entity_id), ctx.actor,
            CHOICE + 'weather_field_shift_field', [field.zone_id for field in found],
            labels={field.zone_id: f'Field at {field.center.x}, {field.center.y}; height {field.center.z*5} feet: '
                    + ', '.join(f'{name.title()} {level}' for name, level in signs(field).items()) for field in found},
            name='Sudden Shift', feature_id=SHIFT, prompt='Choose which gathered field to change.', default='first')
        if not selected:
            return
        z = next(field for field in found if field.zone_id == selected[0])
    old = choose(ctx, list(signs(z)), 'SHIFT_OLD', 'Choose the gathered sign to change.', name='Sudden Shift')
    if not old:
        return
    new = choose(ctx, [s for s in weather_signs.names() if s != 'thunder' and s != old[0]],
                 'SHIFT_NEW', 'Choose the Weather Sign you know to gather instead. Any opposing sign already in this field is reduced by the new sign’s severity.', name='Sudden Shift')
    if not new:
        return
    old, new = old[0], new[0]
    if OPPOSED.get(old) == new:
        level = int(signs(z)[old])
        if level > 0:
            if level > 1:
                signs(z)[old] = level - 1
            else:
                del signs(z)[old]
                if not any(int(value) > 0 for value in signs(z).values()):
                    record_zone_update(ctx.engine, z)
                    from .. import zones
                    zones.remove(ctx.engine, z, 'WEATHER_SIGNS_CANCELLED')
                    return
        else:
            del signs(z)[old]
            signs(z)[new] = 1
        # This action reduces old severity; a later shift establishes severity 1.
    else:
        level = max(1, int(signs(z)[old]))
        del signs(z)[old]
        opposing = OPPOSED.get(new)
        if opposing and int(signs(z).get(opposing, 0)):
            remaining = int(signs(z)[opposing]) - level
            if remaining > 0:
                signs(z)[opposing] = remaining
            elif remaining < 0:
                del signs(z)[opposing]
                signs(z)[new] = max(int(signs(z).get(new, 0)), -remaining)
            else:
                del signs(z)[opposing]
                if not any(int(value) > 0 for value in signs(z).values()):
                    # A field with no signs has no remaining effect or legal Shift
                    # choice. Remove it through the shared zone lifecycle so it
                    # cannot keep offering a paid, ineffective Bonus Action.
                    record_zone_update(ctx.engine, z)
                    from .. import zones
                    zones.remove(ctx.engine, z, 'WEATHER_SIGNS_CANCELLED')
                    return
        else:
            signs(z)[new] = max(int(signs(z).get(new, 0)), level)
    record_zone_update(ctx.engine, z)


@hook('turn_start')
def move_field(engine, owner):
    if not weather_signs.owns(engine, owner, 'foundation_weather_field'):
        return
    from ..gate2_runtime_models import Position
    from ..typed_executor import area_cells, _clear_line
    from ..senses import perceives_cell
    for z in fields(engine, owner):
        points = [Position(x=x, y=y, z=height) for x in range(engine.grid.width) for y in range(engine.grid.height)
                  for height in range(max(0,z.center.z-4),z.center.z+5)]
        points = [p for p in points if engine.grid.distance_ft(z.center, p) <= 20
                  and perceives_cell(engine, owner, p) and _clear_line(engine, owner.position, p)]
        options = {f'{p.x},{p.y},{p.z}': p for p in points}
        selected = ask(engine, getattr(engine, '_active_intent', None), checkpoint_id(engine, 'FIELD_MOVE', z.zone_id), owner,
                       CHOICE + 'weather_field_move', list(options), labels={key:f'Point {p.x}, {p.y}; height {p.z*5} feet' for key,p in options.items()}, name='Move Gather Weather', feature_id=FOUNDATION,
                       prompt='You may move your gathered field up to 20 feet to a point you can see.',
                       allow_decline=True, automatic=False, default='decline')
        if selected:
            z.center = options[selected[0]]
            z.affected_cells = area_cells(engine, z.center, z.center, z.trigger_profile)
            record_zone_update(engine, z)


@hook('damage_roll_bonus')
def weather_cut(ctx, effect_row=None, kinds=None):
    if not (ctx.typed or {}).get('weather_shroud_roll') or not weather_signs.owns(ctx.engine, ctx.actor, 'weather_cut'):
        return None
    turn = turn_key(ctx.engine)
    if ctx.actor.turn_flags.get('weather_cut_turn') == turn:
        return None
    ctx.damage_cache['weather_cut_roll'] = turn
    matching = severity(ctx.engine, None, ctx.target, ctx.typed.get('weather_sign', ''))
    return int(ctx.actor.proficiency_bonus) * (2 if matching else 1)


@hook('after_save_resolved')
def storm_charge(ctx, subject, ability, named, failed):
    if (not failed or (ctx.typed or {}).get('sphere') != weather_signs.SPHERE
            or not weather_signs.owns(ctx.engine, ctx.actor, 'storm_birth')
            or not severity(ctx.engine, ctx.actor, subject, 'thunder')):
        return
    key = 'weather_storm_round:' + subject.entity_id
    if ctx.actor.turn_flags.get(key) == ctx.engine.state.round_number:
        return
    # Automatic harmful choice is enemies only; hidden subjects cannot be chosen.
    from ..target_knowledge import can_see
    from ..tabletop_service import MANUAL_MODES
    automatic = (getattr(ctx.engine, 'typed_control_modes', {}) or {}).get(ctx.actor.entity_id, 'MANUAL') not in MANUAL_MODES
    if automatic and (subject.team_id == ctx.actor.team_id or not can_see(ctx.engine, ctx.actor, subject)):
        return
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'STORM_CHARGE', subject.entity_id), ctx.actor,
                 CHOICE + 'weather_storm_charge', ['use'], name='Storm Birth', feature_id=STORM,
                 target_id=subject.entity_id, allow_decline=True,
                 prompt=f'{subject.display_name} failed a Weather save inside your storm. Deal your Proficiency Bonus in thunder damage?')
    if chosen:
        ctx.actor.turn_flags[key] = ctx.engine.state.round_number
        from .. import typed_executor as te
        delivery = te.Context(ctx.engine, ctx.actor,
            ctx.action.model_copy(update={'source_definition_id': STORM}), ctx.intent,
            {'source': STORM, 'sphere': weather_signs.SPHERE, 'effects': []}, [subject], subject, {})
        te._deal(delivery, subject, int(ctx.actor.proficiency_bonus), 'THUNDER')


@hook('choice_reactors')
def storm_birth_choice_reactors(engine):
    """Enroll owners who can be asked about Storm Birth during another creature's AI step."""
    return tuple(sorted(actor.entity_id for actor in engine.state.actors.values()
                        if weather_signs.owns(engine, actor, 'storm_birth')))


@effect('weather_runtime')
def runtime_marker(ctx, spec):
    """Standing talent attribution; actual execution is in owned hooks."""


def severe_rider(ctx, target, sign):
    """Optional first-failure effect; Dry absorption is stopped at the lock."""
    if sign == 'dry':
        return
    from .. import typed_executor as te
    options = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'SEVERE_RIDER', target.entity_id), ctx.actor,
                  CHOICE + 'weather_severe_rider', ['use'], name='Severe Shroud', feature_id=SEVERE,
                  target_id=target.entity_id, allow_decline=True,
                  prompt=(f'{target.display_name} failed the first save against your {sign.title()} Cloud Shroud in matching weather. '
                          + {'wind': 'Push it 10 feet away now, with no extra cost?',
                             'cold': 'Set its Speed to 0 until the start of your next turn, with no extra cost?',
                             'heat': 'Stop it regaining Hit Points until the start of your next turn, with no extra cost?',
                             'rain': 'Douse it and deny its Reactions until the start of your next turn, with no extra cost?',
                             'thunder': 'Deafen it, deny its Reactions until the start of your next turn, with no extra cost?'}[sign]))
    if not options:
        return
    expires = weather_signs.owner_start(ctx.engine, ctx.actor)
    if sign == 'wind':
        te.run_effects(ctx, [{'type':'forced_movement','applies_to':'target','distance_ft':10,'direction':'away'}])
        return
    if sign in ('cold','heat'):
        rule = {'speed_zero':True} if sign == 'cold' else {'healing_denied':True}
        ctx.engine._apply_condition(target, 'condition:typed.weather_severe_' + sign, SEVERE, ctx.actor.entity_id,
            expires_on=expires, data={'label':'Severe '+sign.title()+(': Speed 0' if sign == 'cold' else ': cannot regain hit points'), 'rule':rule})
    else:
        condition = 'weather_doused' if sign == 'rain' else 'deafened'
        te.run_effects(ctx,[{'type':'condition','applies_to':'target','condition':condition,'expires_on':expires},
                           {'type':'reaction_denied','applies_to':'target','expires_on':expires}])

FINGER = 'TAL_WEATHER_STORMLORD_S_FINGER'


def storm_at(engine, owner, point):
    """Storm severity at a legal aim point, using the same LoE as recipients."""
    return _level(_levels_at(engine, owner, point), 'thunder')


@hook('compile_action')
def stormlord_action(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    if typed.get('source') != FINGER:
        return None
    return action.model_copy(update={'target_kind':'CELL', 'range_ft':100000,
        'parameters':{**action.parameters,'expected_damage':33,'delivers_strike':True,'typed':{**typed,'area':{'shape':'sphere','size_ft':5},
            'effects':[{'type':'weather_storm_bolt','harmful':True}],'riders':[]}}})


@hook('candidate_allowed')
def stormlord_allowed(engine, actor, candidate, action):
    if action is None or not any(r.get('type') == 'weather_storm_bolt'
                                for r in ((action.parameters or {}).get('typed') or {}).get('effects') or []):
        return None
    return (actor.turn_flags.get('weather_finger_turn') != actor.turns_started
            and candidate.destination is not None and storm_at(engine, actor, candidate.destination) >= 2)


@effect('weather_storm_bolt')
def stormlord_bolt(ctx, spec):
    from .. import typed_executor as te
    point = getattr(ctx.intent, 'destination', None)
    level = storm_at(ctx.engine, ctx.actor, point) if point is not None else 0
    if level < 2 or ctx.actor.turn_flags.get('weather_finger_turn') == ctx.actor.turns_started:
        return
    ctx.actor.turn_flags['weather_finger_turn'] = ctx.actor.turns_started
    # Owner's unscoped damaging-area rule: enemies only. Target perception is
    # already settled by the controller's area candidate and native recipients.
    te.run_effects(ctx,[{'type':'save','ability':'dex','dc':'technique_save_dc',
        'on_fail':[{'type':'damage','applies_to':'enemies_in_area','dice':{'count':6 if level==2 else 8,'sides':10},
                    'damage_types':['lightning']}], 'on_success':[{'type':'half_damage'}]}])


@hook('damage_dealt')
def weather_cut_spent(ctx, target, amount):
    if amount > 0 and (ctx.typed or {}).get('weather_shroud_roll') and ctx.damage_cache.get('weather_cut_roll'):
        ctx.actor.turn_flags['weather_cut_turn'] = ctx.damage_cache['weather_cut_roll']


def turn_key(engine):
    current=engine.state.actors[engine.state.current_actor_id]
    return f'{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}'


@hook('damage_defenses')
def gathered_rain_mantle(engine, target, damage_type, typed, source_actor_id):
    if str(damage_type).upper() != 'FIRE':
        return None
    from .weather_mantle import all_mantles, sign_of
    if not any(sign_of(m)=='rain' for m in all_mantles(target)):
        return None
    if severity(engine, None, target, 'rain'):
        return [{'kind':'resistance','damage_types':['FIRE']}]
    return None


@hook('button_description')
def field_description(row):
    effects=((row.get('parameters') or {}).get('typed') or {}).get('effects') or []
    if any(e.get('type')=='weather_storm_bolt' for e in effects):
        return ('Action, 3 Cultivation Points: choose a visible point inside a storm you maintain at severity 2 or higher. '
                'Enemies within 5 feet make a Dexterity save: 6d10 lightning damage at severity 2 or 8d10 at severity 3; '
                'half damage on a success. You can use this bolt again at the start of your next turn.')
    if any(e.get('type')=='weather_gather' for e in effects):
        return ('Action, 2 Cultivation Points, Concentration up to 1 minute: gather a Weather Sign you know into a field centered '
                f'on a visible point within {row.get("range_ft") or 60} feet. The field has a radius of 20 feet, 30 feet with Foundation Weather Field, or 60 feet with Core Weather Field. Choose the sign and severity; upgrades show their extra Cultivation Point costs. '
                'Opposing weather is reduced in the overlap. Wind plus Rain or Dry can support a storm. Sealed barriers block the field.')
    if any(e.get('type')=='weather_shift' for e in effects):
        return ('Bonus Action, 1 Cultivation Point: change one sign in your gathered field to another sign you know. '
                'An opposing sign first reduces the old weather; it does not instantly reverse it.')
    return None


SKY_BOUND = 'TAL_WEATHER_SKY_BOUND_RANGE'


@hook('compile_action')
def sky_bound_range(action, info):
    typed = (action.parameters or {}).get('typed') or {}
    source = str(typed.get('source') or '')
    if SKY_BOUND not in info['owned_ids'] or not (source.startswith(BASE)
            or source.startswith('WEATHER_BASE_CLOUD_SHROUD')):
        return None
    cl = int((info.get('numbers') or {}).get('cl') or 1)
    band = weather_signs.BANDS.index(weather_signs.realm_at(cl))
    bonus = 120 if band >= 2 else 60 if band >= 1 else 30
    return action.model_copy(update={'range_ft': int(action.range_ft or 0) + bonus})
