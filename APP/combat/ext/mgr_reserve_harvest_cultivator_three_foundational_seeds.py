"""Harvest Cultivator's source-owned stock and planted Asset progression.

Acquisition uses subpath_acquisition; physical plants use asset_anchor_runtime.
Only this family's sealed ownership opts in. Formula selections and stock are
source state, never guessed from a name, team, or the presence of Wood talents.
Journey preparation consumes elapsed time and requires a live table-owner
material declaration. Combat continuation uses the public journey bundle seam.
"""
from copy import deepcopy
from dataclasses import replace
import json
from itertools import combinations

from . import effect, hook

PARENT = 'tianxia.subpath.qi.harvest_cultivator'
BASE = PARENT + '.feature.three_foundational_seeds'
GROWTH = PARENT + '.feature.accelerated_growth'
FIELD = PARENT + '.feature.orchard_field'
RESTORE = PARENT + '.feature.seed_of_restoration'
ASCEND = PARENT + '.feature.ten_thousand_seed_ascension'
TIERS = {BASE: 3, GROWTH: 6, FIELD: 10, RESTORE: 14, ASCEND: 18}
FORMULAS = ['root', 'blossom', 'thorn', 'water_reed', 'lantern_fruit']
AUGMENTS = ['wide_roots', 'deep_roots', 'guiding_vine', 'violent_germination',
            'protective_bloom', 'swift_germination']
SEASONS = ['spring', 'summer', 'autumn', 'winter']
MANIFESTATIONS = {'invisible_spirit', 'incorporeal', 'possessing_entity', 'active_possession',
                  'visual_illusion', 'poison', 'disease', 'corruption'}
EXHAUSTION_CAUSES = {'travel', 'hunger', 'thirst', 'exposure', 'ordinary_disease', 'ordinary_poison'}
STATE = 'condition:typed.harvest_stock'
KEY = 'harvest_cultivator'


def title(value):
    return value.replace('_', ' ').title()


@hook('compile_passives')
def owned(rows, info):
    numbers = deepcopy(info['numbers'])
    # The compiler's per-source variant pass already hands this provider the
    # Seed source's own numbers (source_compilation.compile_passives), so the
    # tier gate, PB clamp and save DC read that source's CL; every other
    # consumer reads the numbers sealed onto this row.
    level = int(numbers['cl'])
    old_pb = int(numbers['pb'])
    numbers['pb'] = min(old_pb, 2 + max(0, int(level) - 1) // 4)
    if 'save_dc' in numbers:
        numbers['save_dc'] = int(numbers['save_dc']) + numbers['pb'] - old_pb
    features = [s for s, minimum in TIERS.items() if s in info['owned_ids']
                and int(level) >= minimum]
    if BASE not in features:
        return rows
    return [*rows, {'block': KEY, 'feature_id': BASE, 'features': features,
                   'numbers': numbers}]


def ownership(engine, actor):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == KEY), None)


def bundle_ownership(bundle):
    return next((r for r in bundle.get('typed_passives', ()) if r.get('block') == KEY), None)


def blank():
    return {'formulas': [], 'stock': 0, 'formula_cl': 0, 'ascension_used': 0}


def held(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == STATE), None)


def stock(actor):
    c = held(actor)
    return json.loads(c.data['state']) if c else blank()


def store(engine, actor, value):
    from .retained_updates import record_instance_update
    c = held(actor)
    if c:
        c.data['state'] = json.dumps(value, sort_keys=True)
        record_instance_update(engine, actor, 'condition', c.instance_id, c)
    else:
        engine._apply_condition(actor, STATE, BASE, actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'state': json.dumps(value, sort_keys=True), 'label': 'Prepared Spirit Seeds and learned formulas'})


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition
    own = next((r for r in info['passives'] if r.get('block') == KEY), None)
    if not own:
        return []
    numbers = own['numbers']; cl = int(numbers['cl'])
    made = []
    def add(key, name, source, economy, target, reach, cost=0):
        if source not in own['features'] or cl < TIERS[source]:
            return
        duration = {'kind': 'minutes', 'amount': 1, 'concentration': True} if key in ('field', 'ascension') else {'kind': 'instant'}
        made.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.harvest.{key}",
            display_name=name, owner_id=info['actor_id'], economy=economy,
            resolution_kind='TYPED', target_kind=target, range_ft=reach,
            costs=(('resource:core.qi', cost),) if cost else (), parameters={
                KEY: key, 'any_cell': target == 'CELL', 'typed': {'source': source,
                    'manual_inline_choice': True, 'manual_zone': 1, 'numbers': numbers, 'duration': duration,
                    'effects': [{'type': 'harvest_execute', 'operation': key}], 'riders': []},
                'description': description(key, cl, int(numbers['pb']))}))
    for formula in FORMULAS:
        add('plant_' + formula, 'Plant ' + title(formula) + ' Seed', BASE, 'BONUS_ACTION', 'CELL', 60 if GROWTH in own['features'] else 30)
    add('field', 'Orchard Field', FIELD, 'ACTION', 'CELL', 60, 5)
    add('restoration', 'Seed of Restoration', RESTORE, 'BONUS_ACTION', 'CELL', 30, 4)
    add('ascension', 'Ten Thousand Seed Ascension', ASCEND, 'ACTION', 'CELL', 90, 8)
    add('harvest', 'Harvest of Restoration', ASCEND, 'NONE', 'SELF', 0)
    add('lantern_inspect', 'Lantern-Fruit: Examine Concealment', BASE, 'NONE', 'SELF', 0)
    return made


def description(key, cl, pb):
    if key.startswith('plant_'):
        details = {
            'root': 'Hostile creatures treat its area as difficult terrain.',
            'blossom': f'At the start of an ally’s turn in the area, it gains {pb} Temporary Hit Points, once per round.',
            'thorn': f'A hostile creature entering for the first time during a turn or starting there makes a Dexterity save: {1 + int(cl >= 11) + int(cl >= 17)}d6 Piercing damage, half on success.',
            'water_reed': 'Chosen allies ignore difficult terrain, shallow water, mud, reeds and ordinary vegetation. An ally entering for the first time in a turn may move 5 feet without provoking.',
            'lantern_fruit': 'Bright Light extends 10 feet, then Dim Light another 10 feet. Spirit and possession forms leave outlines, lower-level visual illusions flicker, and active poison, disease or corruption discolors; stronger concealment may need a Cultivation Check.'}
        return ('Bonus Action: plant one prepared Spirit Seed in an unoccupied supported space within 30 feet. '
            f'It lasts 1 minute, affects a 10-foot radius, has AC 13 and {2 * cl} Hit Points, and is immune to Psychic damage. '
            + details[key[6:]] + (' Spend 1 Qi for one Growth Augment; Swift Germination extends planting range to 60 feet.' if cl >= 6 else '')
            + (' At CL14, spend 2 Qi for two different augments.' if cl >= 14 else ''))
    return {
        'field': 'Action, 5 Qi, within 60 feet: choose two Seed Formulas throughout a 20-foot-radius, 20-foot-high cylinder. No Seed stock is consumed. Concentration, up to 1 minute; maintain one field. Choose one season at each turn start.',
        'restoration': f'Bonus Action, 4 Qi, within 30 feet: plant a Seed within 5 feet of a willing Ward. AC 15, {3 * cl} Hit Points, three charges, up to 1 minute. At the Ward’s turn start within 10 feet, spend a charge to heal 2d8 plus your Qi key modifier. One extra charge may purify a qualifying condition or ordinary Exhaustion. A new Restoration Seed replaces yours.',
        'ascension': 'Action, 8 Qi, once per scene, within 90 feet: choose three Seed Formulas throughout a 40-foot-radius, 40-foot-high cylinder. Concentration, up to 1 minute. Chosen allies ignore difficult terrain and may move 10 feet without provoking at turn start; Restoration Seeds heal 3d8 plus your Qi key modifier. Choose two different seasons at each turn start. A hostile creature entering for the first time during a turn or starting there makes a Strength saving throw: on a failure its Speed drops by 10 feet and it cannot Dash until the start of its next turn; on a success its Speed drops by 5 feet until the start of its next turn.',
        'harvest': 'No action and no additional Qi: once during your active celestial orchard, choose any number of allies in it. Each regains 3d8 plus your Qi key modifier Hit Points.',
        'lantern_inspect': 'Examine a form already in your Lantern-Fruit’s Bright Light. Equal or higher cultivation concealment may require a Cultivation Check. This spends no Seed or Qi.'}[key]


@hook('compile_action')
def supersede_inferred_actions(action, info):
    """Retire inferred fragments; all legal family operations are published above."""
    typed = action.parameters.get('typed') or {}
    source = typed.get('option_of') or typed.get('source')
    if source in TIERS and KEY not in action.parameters:
        return action.model_copy(update={'parameters': {**action.parameters, 'harvest_obsolete': 1,
            'typed': {**typed, 'effects': [], 'riders': [], 'options': [], 'zone_spec': None}}})


def plants(engine, owner, restoration=False):
    from ..asset_anchor_runtime import members
    return [o for o in members(engine, owner.entity_id, KEY)
            if bool(o.component.get('restoration')) == restoration]


def fields(engine, owner=None):
    from ..zones import typed_zones
    return [z for z in typed_zones(engine) if (z.trigger_profile.get('profile') or {}).get(KEY)
            and (owner is None or z.owner_id == owner.entity_id)]


def inside(engine, zone, actor):
    from ..spatial_areas import zone_contains, positions_inside_zone
    if hasattr(actor, 'entity_id'):
        return zone_contains(engine, actor, zone)
    p = actor.position
    return positions_inside_zone(engine, [(p.x, p.y, p.z)], zone)


def live(engine, zone):
    profile = zone.trigger_profile.get('profile') or {}
    oid = profile.get('seed_object')
    obj = engine.state.objects.get(oid) if oid else None
    suppressed = bool(obj and obj.component.get('suppressed') and engine.state.round_number <= int(obj.component.get('bed_expires_round', 0)))
    return not oid or bool(obj and not obj.destroyed and not suppressed)


def source_categories(condition):
    """The native category tags one effect carries, never guessed from its name.

    Reads the effect's own ``data.categories`` and the engine's stored save
    classification tags (``origin_save`` / ``repeat_save`` hold
    ``category:<tag>``), plus a native source record's category. Purifying
    Germination identifies a disease from this real classification."""
    tags = set(condition.data.get('categories', ()) or ())
    for key in ('origin_save', 'repeat_save'):
        save = condition.data.get(key) or {}
        for tag in save.get('named', ()) or ():
            text = str(tag)
            tags.add(text[len('category:'):] if text.startswith('category:') else text)
    record = condition.data.get('native_source_record') or {}
    if record.get('category'):
        tags.add(str(record['category']))
    return tags


def live_export(engine, owner):
    """Snapshot this owner's live Seeds, fields and Concentration as integers and
    strings for an encounter break. An already-ended Seed or field is not
    carried; each zone records its remaining whole rounds and (for a Seed) the
    exact object with its remaining charges."""
    rows = []
    for zone in fields(engine, owner):
        if not live(engine, zone):
            continue
        remaining = None
        if zone.duration_rounds:
            remaining = max(0, zone.created_round + zone.duration_rounds - engine.state.round_number)
        row = {'zone': zone.model_dump(mode='json'), 'remaining_rounds': remaining}
        oid = zone.trigger_profile['profile'].get('seed_object')
        obj = engine.state.objects.get(oid) if oid else None
        if obj is not None and not obj.destroyed:
            row['object'] = obj.model_dump(mode='json')
        rows.append(row)
    concentration = None
    if owner.concentration is not None:
        concentration = {'source_definition_id': owner.concentration.source_definition_id,
                         'started_sequence': int(owner.concentration.started_sequence)}
    if not rows and concentration is None:
        return None
    return {'zones': rows, 'concentration': concentration}


def live_export_bundle(live, elapsed):
    """Reduce one stored snapshot by the journey seconds elapsed since it was
    taken. A Seed or field whose 1-minute duration ran out is not carried, and a
    Concentration whose owning field is gone is not carried either."""
    kept = []
    for row in live.get('zones', ()):
        zone = deepcopy(row['zone'])
        remaining = row.get('remaining_rounds')
        if remaining is not None:
            seconds = int(remaining) * 6 - int(elapsed)
            if seconds <= 0:
                continue
            zone['duration_rounds'] = max(1, (seconds + 5) // 6)
        kept.append({'zone': zone, 'object': deepcopy(row.get('object'))})
    if not kept:
        return None
    concentration = live.get('concentration')
    if concentration and not any(row['zone']['source_definition_id'] == concentration['source_definition_id']
                                 for row in kept):
        concentration = None
    return {'zones': kept, 'concentration': concentration}


def live_restore(engine, actor, live):
    """Recreate the carried Seeds, fields and Concentration in a new encounter
    under the owner's own identifiers, with fresh instance ids and a local
    clock that has already absorbed the travel time. Only called from the
    match_initialize hook inside uncommitted match genesis."""
    from ..gate2_runtime_models import ConcentrationState, RuntimeObjectState, ZoneState
    from ..asset_anchor_runtime import refresh
    from ..zones import sync_inside
    sources = {}
    for index, row in enumerate(live.get('zones', ()), start=1):
        zone = ZoneState.model_validate(row['zone'])
        new_zone_id = f'zone:typed:{actor.entity_id}:carried:{index}'
        zone = zone.model_copy(update={'zone_id': new_zone_id, 'created_round': engine.state.round_number,
                                       'per_turn_triggered': {}})
        object_row = row.get('object')
        if object_row is not None:
            obj = RuntimeObjectState.model_validate(object_row)
            new_object_id = f'object:asset:{actor.entity_id}:carried:{index}'
            component = {**obj.component, 'zone_id': new_zone_id}
            component['asset_anchor_runtime'] = {**(component.get('asset_anchor_runtime') or {}),
                                                 'owner': actor.entity_id}
            obj = obj.model_copy(update={'object_id': new_object_id, 'component': component})
            zone.trigger_profile['profile']['seed_object'] = new_object_id
            engine._update_object(obj, zone.source_definition_id, actor.entity_id)
        engine.state.zones[new_zone_id] = zone
        engine._append_event('ZONE_CREATED', zone.source_definition_id, actor_id=actor.entity_id,
                             payload={'zone': zone.model_dump(mode='json')})
        sources[zone.source_definition_id] = new_zone_id
    concentration = live.get('concentration')
    if concentration and concentration['source_definition_id'] in sources:
        actor.concentration = ConcentrationState(source_definition_id=concentration['source_definition_id'],
            zone_id=sources[concentration['source_definition_id']],
            started_sequence=int(concentration['started_sequence']))
    refresh(engine)
    for zone_id in sources.values():
        sync_inside(engine, engine.state.zones[zone_id].source_definition_id)


def seed_bed(engine, actor, position):
    bundle = next((b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id), {})
    bed = bundle.get('harvest_seed_bed')
    if bed and engine.state.round_number <= bed['expires_round'] and [position.x, position.y, position.z] in bed['value']['cells']:
        return bed
    return None


def legal_medium(engine, actor, position):
    bed = seed_bed(engine, actor, position)
    if bed and bed['value']['suppresses'] and bed['value']['authority'] != 'ordinary':
        return False
    water = any(r.get('kind') == 'water' and [position.x, position.y] in r.get('cells', ())
        and r.get('min_z', 0) <= position.z <= r.get('max_z', 0)
        for r in (getattr(engine, 'battlefield_document', {}) or {}).get('travel_regions', ()))
    return not water or bool(bed and bed['value']['medium'] == 'suitable_liquid')


@hook('candidate_allowed')
def eligible(engine, actor, candidate, action):
    if action is None:
        return None
    if action.parameters.get('harvest_obsolete'):
        return False
    op = action.parameters.get(KEY)
    if not op:
        return None
    own = ownership(engine, actor)
    if not own:
        return False
    data = stock(actor)
    if op.startswith('plant_'):
        known = FORMULAS if FIELD in own['features'] else data['formulas']
        if op[6:] not in known or data['stock'] < 1 or len(plants(engine, actor)) >= int(own['numbers']['pb']):
            return False
        if candidate.destination and engine.grid.distance_ft(actor.position, candidate.destination) > 30 and actor.resources.get('resource:core.qi', 0) < 1:
            return False
    if op == 'ascension' and data['ascension_used']:
        return False
    if op == 'harvest':
        return any(z.trigger_profile['profile'].get('ascension') and not z.trigger_profile['profile'].get('harvest_used') for z in fields(engine, actor))
    if op == 'lantern_inspect':
        return any('lantern_fruit' in z.trigger_profile['profile']['formulas'] and live(engine, z) for z in fields(engine, actor))
    if candidate.destination and (op.startswith('plant_') or op == 'restoration'):
        from ..asset_anchor_runtime import legal_placement
        if not legal_medium(engine, actor, candidate.destination):
            return False
        ignored = []
        if op == 'restoration':
            if not any(a.active and engine.grid.distance_ft(candidate.destination, a.position) <= 5 for a in engine.state.actors.values()):
                return False
            ignored = [o.object_id for o in plants(engine, actor, True) if o.position == candidate.destination]
        return legal_placement(engine, [candidate.destination], 1, ignore=ignored)
    return True


def choose(ctx, kind, options, *, count=1, maximum=None, optional=False, subject=None, prompt=None, labels=None):
    from .needle import ask, checkpoint_id
    if not options:
        return []
    if labels is None and kind == 'growth_augments':
        labels = {
            'wide_roots': 'Wide Roots: increase this Seed’s radius by 5 feet; 1 Qi.',
            'deep_roots': f'Deep Roots: this Seed gains {int(ctx.numbers["cl"])} Hit Points; 1 Qi.',
            'guiding_vine': 'Guiding Vine: one willing ally within 15 feet of the Seed moves 5 feet without provoking; 1 Qi.',
            'violent_germination': 'Violent Germination: the Seed’s first damage gains 1d6 against one creature; 1 Qi.',
            'protective_bloom': 'Protective Bloom: one ally in the area has Advantage on its next saving throw before your next turn starts; 1 Qi.',
            'swift_germination': 'Swift Germination: plant this Seed within 60 feet instead of 30 feet; 1 Qi.'}
    if labels is None and kind == 'seasons':
        labels = {'spring': 'Spring: one ally in the field heals 1d8 plus your Qi key modifier Hit Points.',
            'summer': 'Summer: the first time each hostile creature in the field takes damage during each turn, add 1d8 Fire or Radiant damage.',
            'autumn': 'Autumn: hostiles in the field face difficult terrain and lose 5 feet of Speed while inside.',
            'winter': 'Winter: chosen allies in the field gain +1 AC against ranged attacks and Advantage against environmental cold and Cold-tagged effects.'}
    automatic_options = None
    if kind != 'chosen_allies' and all(x in ctx.engine.state.actors for x in options):
        from ..target_knowledge import located
        automatic_options = [x for x in options if x == (subject or ctx.actor).entity_id
            or located(ctx.engine, subject or ctx.actor, ctx.engine.state.actors[x])]
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'harvest', ctx.source, kind,
        (subject or ctx.actor).entity_id), subject or ctx.actor, 'choice:needle.harvest_' + kind, list(options),
        labels=labels or {x: ctx.engine.state.actors[x].display_name if x in ctx.engine.state.actors else title(x) for x in options},
        minimum=0 if optional else count, maximum=count if maximum is None else maximum,
        allow_decline=optional, name=ctx.action.display_name, feature_id=ctx.typed.get('source', BASE),
        automatic_options=automatic_options,
        prompt=prompt or f'{ctx.action.display_name}: choose {title(kind)}. The effect lasts up to 1 minute.')


def allies(ctx, center, radius):
    from ..relations import relation, ALLY
    return [a.entity_id for a in ctx.engine.state.actors.values() if a.active and relation(ctx.engine, ctx.actor, a) == ALLY
            and (radius is None or ctx.engine.grid.distance_ft(center, a.position) <= radius)]


def move_offer(ctx, actor, feet, name):
    from .granted_movement import choices, move
    options = choices(ctx.engine, actor, feet)
    ids = {str(i): c for i, c in enumerate(options)}
    if not ids:
        return
    from .needle import ask, checkpoint_id
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'harvest_move', ctx.source, name, actor.entity_id),
        actor, 'choice:needle.harvest_move', list(ids), minimum=0, maximum=1, allow_decline=True,
        labels={k: f'{actor.display_name}: move to ({c.destination.x}, {c.destination.y}, {c.destination.z * 5} feet high)' for k,c in ids.items()},
        name=name, feature_id=ctx.typed.get('source', BASE),
        prompt=f'{name}: {actor.display_name} may move up to {feet} feet without provoking Opportunity Attacks, using no action.')
    if picked:
        move(ctx.engine, actor, ids[picked[0]], ctx.intent, feet, list(ctx.engine.state.actors), name=name)


def pulse_ctx(engine, zone, actor):
    from ..typed_executor import Context
    owner = engine.state.actors[zone.owner_id]
    action = engine.action_catalog[zone.source_definition_id]
    return Context(engine, owner, action, getattr(engine, '_active_intent', None),
        {'source': action.parameters['typed']['source'], 'numbers': zone.trigger_profile['numbers'], 'duration': {'kind': 'instant'}},
        [actor], actor, {})


def heal(ctx, actor, count):
    from ..typed_executor import block_healing
    block_healing(replace(ctx, targets=[actor], target=actor), {'type': 'healing', 'applies_to': 'target',
        'dice': {'count': count, 'sides': 8}, 'formula': 'key_ability_modifier'})


def triggers(formulas):
    rows = []
    for f in formulas:
        if f in ('blossom', 'thorn', 'water_reed'):
            rows.append({'id': 'harvest:' + f, 'name': title(f) + ' Seed',
                'on': ['start'] if f == 'blossom' else ['enter', 'start'] if f == 'thorn' else ['enter'],
                'who': 'hostile' if f == 'thorn' else 'ally', 'per_round': f == 'blossom',
                'effects': [{'type': 'harvest_pulse', 'formula': f}]})
    return rows


@hook('trigger_harm')
def thorn_harm(effects, numbers):
    """A Thorn Seed's wrapped pulse harms the hostile at its trigger, so the
    shared movement-hazard query sees the same danger the pulse deals."""
    return any(isinstance(row, dict) and row.get('type') == 'harvest_pulse' and row.get('formula') == 'thorn'
               for row in effects or ())


@effect('harvest_execute', harmful=False)
def execute(ctx, row):
    from .. import zones
    from ..asset_anchor_runtime import create, retire
    from .retained_updates import record_zone_update
    op = row['operation']; own = ownership(ctx.engine, ctx.actor)
    if not own:
        raise ValueError('Harvest cultivation requires the acquired progression.')
    data = stock(ctx.actor); cl = int(own['numbers']['cl']); pb = int(own['numbers']['pb'])
    center = ctx.intent.destination or ctx.actor.position
    if op == 'lantern_inspect':
        examine_lantern(ctx)
        return
    if op == 'harvest':
        zone = next(z for z in fields(ctx.engine, ctx.actor) if z.trigger_profile['profile'].get('ascension') and not z.trigger_profile['profile'].get('harvest_used'))
        pool = [a.entity_id for a in ctx.engine.state.actors.values() if inside(ctx.engine, zone, a) and a.entity_id in allies(ctx, zone.center, 10000)]
        selected = choose(ctx, 'harvest_allies', pool, count=0, maximum=len(pool), optional=True,
            prompt='Harvest of Restoration: choose any number of allies in the celestial orchard. Each regains 3d8 plus your Qi key modifier Hit Points. No action; once during this activation.')
        zone.trigger_profile['profile']['harvest_used'] = 1; record_zone_update(ctx.engine, zone)
        for aid in selected:
            heal(ctx, ctx.engine.state.actors[aid], 3)
        return
    restoration = op == 'restoration'
    augments = []
    if op.startswith('plant_') and GROWTH in own['features']:
        cap = 2 if cl >= 14 else 1
        cap = min(cap, int(ctx.actor.resources.get('resource:core.qi', 0)))
        far = ctx.engine.grid.distance_ft(ctx.actor.position, center) > 30
        augments = choose(ctx, 'growth_augments', AUGMENTS, count=1 if far else 0, maximum=cap,
            optional=not far, prompt=f'Accelerated Growth: apply up to {cap} different augments to this Seed, spending 1 Qi per augment. Swift Germination is required beyond 30 feet.') if cap else []
        if far and 'swift_germination' not in augments:
            raise ValueError('Planting beyond 30 feet requires Swift Germination.')
        if augments:
            ctx.engine._spend_resource(ctx.actor, 'resource:core.qi', len(augments), ctx.source)
    is_seed = restoration or op.startswith('plant_')
    if is_seed:
        bed = seed_bed(ctx.engine, ctx.actor, center)
        if not legal_medium(ctx.engine, ctx.actor, center):
            raise ValueError('The Seed needs a solid surface or suitable liquid without an absolute planting prohibition.')
        if restoration:
            wards = [a.entity_id for a in ctx.engine.state.actors.values() if a.active and ctx.engine.grid.distance_ft(center, a.position) <= 5]
            selected = choose(ctx, 'ward', wards, prompt='Seed of Restoration: choose a willing creature within 5 feet of the planting space. Costs 4 Qi and a Bonus Action; three charges, up to 1 minute.')
            if not selected:
                # A declined Ward ends the activation cleanly. The preview's
                # menu-discovery pass simulates this decline, so it must not raise.
                return
            ward = ctx.engine.state.actors[selected[0]]
            from .willing_targets import asks_consent
            from ..relations import relation, ALLY
            if not asks_consent(ctx.engine, ctx.intent, ward, 'Seed of Restoration',
                f'{ctx.actor.display_name} offers to make {ward.display_name} the Ward of a Restoration Seed for 1 minute. Accept?',
                prefer_accept=relation(ctx.engine, ctx.actor, ward) == ALLY, asker=ctx.actor):
                # An unwilling creature is not a Ward; the activation ends without
                # planting (the menu-discovery pass also declines, so return).
                return
            for old in plants(ctx.engine, ctx.actor, True):
                retire(ctx.engine, old, ctx.source)
            formulas = []; hp = 3 * cl
        else:
            known = FORMULAS if FIELD in own['features'] else data['formulas']
            if op[6:] not in known or data['stock'] < 1 or len(plants(ctx.engine, ctx.actor)) >= pb:
                raise ValueError('This Formula needs learned access, prepared stock, and an available maintained Seed slot.')
            formulas = [op[6:]]; hp = 2 * cl + (cl if 'deep_roots' in augments else 0)
            data['stock'] -= 1; store(ctx.engine, ctx.actor, data)
        obj = create(ctx.engine, ctx.actor, ctx.source, {'name': 'Restoration Seed' if restoration else title(formulas[0]) + ' Seed',
            'kind': 'cultivation_asset', 'ac': 15 if restoration else 13, 'hp': hp, 'source_cl': cl,
            'height_ft': 1, 'group': KEY,
            # Only the printed statistics grant immunities: the Spirit Seed's block
            # lists Immunity: Psychic, and the Restoration Seed's block lists AC, Hit
            # Points, Charges and Source CL only, so it gets none.
            **({} if restoration else {'immune': ['PSYCHIC']})}, center,
            component={'restoration': int(restoration), 'charges': 3 if restoration else 0,
                'size': 'Tiny', 'formulas': formulas, 'augments': augments, 'ward': ward.entity_id if restoration else ''})
        if bed:
            suppressed = bool(bed['value']['suppresses'] and bed['value']['source_cl'] > cl)
            obj = obj.model_copy(update={'component': {**obj.component, 'suppressed': int(suppressed),
                'bed_expires_round': bed['expires_round'], 'land_source_cl': bed['value']['source_cl'],
                'land_source_id': bed['value']['source_id'], 'land_receipt': bed['receipt_id']}})
            ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
        radius = 10 + (5 if 'wide_roots' in augments else 0)
    else:
        count = 3 if op == 'ascension' else 2
        formulas = choose(ctx, 'field_formulas', FORMULAS, count=count,
            prompt=f'{ctx.action.display_name}: choose {count} different Seed Formulas to apply throughout the field for 1 minute, with Concentration. No prepared Seeds are consumed.')
        radius = 40 if op == 'ascension' else 20
        for old in fields(ctx.engine, ctx.actor):
            if old.trigger_profile['profile'].get('field_kind') == op:
                zones.remove(ctx.engine, old, 'Replaced by a new field')
        if op == 'ascension':
            if data['ascension_used']:
                raise ValueError('Ten Thousand Seed Ascension was already used this scene.')
            data['ascension_used'] = 1; store(ctx.engine, ctx.actor, data)
    chosen = choose(ctx, 'chosen_allies', allies(ctx, center, None), count=0,
        maximum=len(allies(ctx, center, None)), optional=True,
        prompt=f'{ctx.action.display_name}: choose allies for its terrain and protection benefits for up to 1 minute.')
    profile = {KEY: 1, 'seed_object': obj.object_id if is_seed else '', 'field_kind': '' if is_seed else op,
        'ascension': int(op == 'ascension'), 'formulas': formulas, 'chosen_allies': chosen,
        'seasons': [], 'violent_unused': int('violent_germination' in augments)}
    ts = triggers(formulas)
    if restoration:
        ts = [{'id': 'harvest:restoration', 'name': 'Seed of Restoration', 'on': ['start'], 'who': 'any',
               'effects': [{'type': 'harvest_pulse', 'formula': 'restoration'}]}]
    if op == 'ascension':
        ts.append({'id': 'harvest:grasping', 'name': 'Grasping Abundance', 'on': ['enter', 'start'],
                   'who': 'hostile', 'effects': [{'type': 'harvest_pulse', 'formula': 'grasping'}]})
    zone = zones.create(ctx, {'name': ctx.action.display_name, 'shape': 'sphere' if is_seed else 'cylinder',
        'size_ft': radius, 'height_ft': radius, 'centered_on_self': False,
        'duration': {'kind': 'minutes', 'amount': 1, 'concentration': not is_seed},
        'difficult': 'hostile' if 'root' in formulas else None, 'profile': profile, 'triggers': ts})
    if zone is None:
        raise ValueError('The planting failed to create its native area.')
    if is_seed:
        ctx.engine._update_object(obj.model_copy(update={'component': {**obj.component, 'zone_id': zone.zone_id}}), ctx.source, ctx.actor.entity_id)
    if 'guiding_vine' in augments:
        targets = choose(ctx, 'guiding_vine_ally', allies(ctx, center, 15), optional=True,
            prompt='Guiding Vine: choose a willing ally within 15 feet of the Seed to move 5 feet without provoking.')
        if targets:
            from .willing_targets import asks_consent
            a = ctx.engine.state.actors[targets[0]]
            if asks_consent(ctx.engine, ctx.intent, a, 'Guiding Vine', f'{a.display_name}: accept a 5-foot move without provoking from Guiding Vine?', prefer_accept=True, asker=ctx.actor):
                move_offer(ctx, a, 5, 'Guiding Vine')
    if 'protective_bloom' in augments:
        targets = choose(ctx, 'protective_bloom_ally', allies(ctx, center, radius), optional=True,
            prompt='Protective Bloom: one ally in the Seed area gains Advantage on its next saving throw before your next turn starts.')
        if targets:
            from .qi_subpaths_1 import next_mode
            next_mode(replace(ctx, target=ctx.engine.state.actors[targets[0]], targets=[ctx.engine.state.actors[targets[0]]]),
                {'kinds': ['save'], 'duration': {'kind': 'until_start_of_your_next_turn'}})


@hook('zone_trigger_context')
def bind_zone(ctx, zone, creature, moment):
    if zone.trigger_profile.get('profile', {}).get(KEY):
        ctx.typed['harvest_zone'] = zone.zone_id


@effect('harvest_pulse')
def pulse(ctx, row):
    from ..typed_executor import run_effects
    from .retained_updates import record_zone_update
    zone = ctx.engine.state.zones.get(ctx.typed.get('harvest_zone'))
    if zone is None or not live(ctx.engine, zone):
        return
    p = zone.trigger_profile['profile']; actor = ctx.target; f = row['formula']
    if actor is None:
        return
    if f == 'blossom':
        # One creature benefit per round across overlapping Blossom Seeds.
        flag = '_round_harvest_blossom'
        if actor.turn_flags.get(flag) == ctx.engine.state.round_number:
            return
        actor.turn_flags[flag] = ctx.engine.state.round_number
        run_effects(ctx, [{'type': 'temp_hp', 'applies_to': 'target', 'formula': 'pb'}])
    elif f == 'thorn':
        cl = int(ctx.numbers['cl']); count = 1 + int(cl >= 11) + int(cl >= 17)
        damage = {'type': 'damage', 'applies_to': 'target', 'dice': {'count': count, 'sides': 6}, 'damage_types': ['piercing']}
        if p.get('violent_unused'):
            # The first damage packet, not each creature in its area.
            damage['dice']['count'] += 1
        # Violent Germination belongs to this one Seed instance: Seeds sharing
        # the same Formula share a source definition, so receipt consumption is
        # gated to damage committed while exactly this zone's pulse resolves.
        previous_pulsing = getattr(ctx.engine, '_harvest_pulsing_zone', None)
        ctx.engine._harvest_pulsing_zone = zone.zone_id
        try:
            run_effects(ctx, [{'type': 'save', 'ability': 'dex', 'dc': 'technique_save_dc', 'applies_to': 'target',
                'on_fail': [damage], 'on_success': [{'type': 'half_damage', 'applies_to': 'target'}]}])
        finally:
            ctx.engine._harvest_pulsing_zone = previous_pulsing
    elif f == 'water_reed':
        move_offer(ctx, actor, 5, 'Water-Reed Seed')
    elif f == 'grasping':
        run_effects(ctx, [{'type': 'save', 'ability': 'str', 'dc': 'technique_save_dc', 'applies_to': 'target',
            'on_fail': [{'type': 'speed', 'flat': -10, 'applies_to': 'target', 'duration': {'kind': 'until_start_of_next_turn'}},
                        {'type': 'condition', 'condition': 'no_dash', 'applies_to': 'target', 'duration': {'kind': 'until_start_of_next_turn'}}],
            'on_success': [{'type': 'speed', 'flat': -5, 'applies_to': 'target', 'duration': {'kind': 'until_start_of_next_turn'}}]}])
    elif f == 'restoration':
        obj = ctx.engine.state.objects[p['seed_object']]
        if obj.component['ward'] != actor.entity_id or obj.component['charges'] <= 0:
            return
        count = 3 if any(z.trigger_profile['profile'].get('ascension') and inside(ctx.engine, z, obj) for z in fields(ctx.engine, ctx.actor)) else 2
        heal(ctx, actor, count)
        component = deepcopy(obj.component); component['charges'] -= 1
        if component['charges']:
            purify(ctx, actor, component)
        obj = obj.model_copy(update={'component': component})
        ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
        if component['charges'] <= 0:
            from ..asset_anchor_runtime import retire
            retire(ctx.engine, obj, ctx.source)


def purify(ctx, ward, component):
    from .end_effect import known_source_cl, remove_instance
    from .repeat_saves import save_of, attempt_repeat, ordinary_repeat_ends
    options = {}
    labels = {}
    for iid, c in ward.conditions.items():
        name = c.condition_id.removeprefix('condition:typed.')
        tags = source_categories(c)
        ordinary = bool(c.data.get('ordinary'))
        valid = name in ('frightened', 'poisoned') or name == 'bleeding' and ordinary or 'disease' in tags
        source_level = known_source_cl(ctx, c)
        # A higher-CL disease still receives the printed repeat save: eligibility
        # needs the effect's real stored original save, not the engine's narrower
        # ordinary end-on-success record (repeat_saves.ordinary_repeat_ends
        # rejects a native save classified by "category:<tag>").
        if valid and source_level is not None and (source_level <= int(ctx.numbers['cl'])
                or save_of(c) is not None):
            options[iid] = c
            labels[iid] = c.data.get('label') or title(name)
    from .forged_exhaustion import level, add, CONDITION_ID
    # Each confirmed origin record (restoration declaration, ordinary travel record) is its own option.
    # The restoration record keeps the id 'exhaustion'; any other record gets 'exhaustion:<record>'.
    origins = sorted((c for c in ward.conditions.values() if c.condition_id == 'condition:typed.harvest_exhaustion_origin'
        and c.data.get('exhaustion_instance') in ward.conditions and int(c.data.get('levels', 0)) > 0),
        key=lambda c: c.data.get('record') != 'restoration')
    if origins and level(ward) > 0:
        for n, origin in enumerate(origins):
            oid = 'exhaustion' if n == 0 else 'exhaustion:' + str(origin.data.get('record', 'ordinary'))
            options[oid] = origin
            labels[oid] = 'Reduce one level of Exhaustion caused by ' + origin.data['cause'].replace('_', ' ')
    # The cultivator owns this spending: the Ward is healed either way; spending
    # a further charge to purify a condition is the seed user's choice (lead fix
    # round 2026-10-18). The prompt still names the ability, the effect and the cost.
    selected = choose(ctx, 'purifying_germination', list(options), optional=True,
        labels=labels,
        prompt=(f'Seed of Restoration: {ctx.actor.display_name}, choose a qualifying effect on {ward.display_name} '
            f'for Purifying Germination. Ending it or repeating its {ward.display_name}’s saving throw '
            'with Advantage costs one additional Seed charge; choosing nothing keeps the charges.'))
    if not selected:
        return
    iid = selected[0]; c = options[iid]
    component['charges'] -= 1
    if c.condition_id == 'condition:typed.harvest_exhaustion_origin':
        add(ctx.engine, ward, -1, ctx.source)
        c.data['levels'] -= 1
        replacement = next((h for h in ward.conditions.values() if h.condition_id == CONDITION_ID), None)
        if c.data['levels'] and replacement:
            c.data['exhaustion_instance'] = replacement.instance_id
            from .retained_updates import record_instance_update
            record_instance_update(ctx.engine, ward, 'condition', c.instance_id, c)
        else:
            from .condition_ownership import remove_instance as drop
            drop(ctx.engine, ward, c.instance_id, ctx.source)
        return
    source_level = known_source_cl(ctx, c)
    if source_level <= int(ctx.numbers['cl']):
        remove_instance(ctx, ward, 'condition', iid, c)
    else:
        # A lower/equal-source effect ends. A higher-source one repeats the
        # saving throw that imposed it, with Advantage (the printed remedy).
        # The shared helper handles the engine's own end-on-success repeat
        # record; a native condition classified by its save category keeps that
        # original save under extra provenance keys, so it uses the engine's
        # public native resolve_repeat_save seam instead of losing the remedy.
        rolled = attempt_repeat(ctx.engine, ward, iid, c, ctx.source, extra_mode='ADVANTAGE')
        if rolled is None and not ordinary_repeat_ends(c) and save_of(c) is not None:
            save = save_of(c)
            ctx.engine.resolve_repeat_save(ward, iid, c,
                {'ability': str(save['ability']).upper(), 'dc': int(save['dc'])},
                f'SEED_OF_RESTORATION:{ctx.source}', extra_mode='ADVANTAGE', roll_source=ctx.source)


@hook('zone_subject_allowed')
def inactive_seed(engine, zone, actor):
    if zone.trigger_profile.get('profile', {}).get(KEY) and not live(engine, zone):
        return False


@hook('difficult_zone_exempt')
def inactive_seed_terrain(engine, actor, zone):
    if zone.trigger_profile.get('profile', {}).get(KEY) and not live(engine, zone):
        return True


@hook('turn_start_choice')
def seasons(engine, actor):
    from .retained_updates import record_zone_update
    for zone in list(fields(engine)):
        p = zone.trigger_profile['profile']
        if not p.get('field_kind') or not live(engine, zone):
            continue
        if zone.owner_id == actor.entity_id and zone.duration_rounds and engine.state.round_number - zone.created_round >= zone.duration_rounds:
            continue  # the ordinary zone expiry checkpoint follows this choice seam
        speeds = {a.entity_id: engine._effective_speed(a) for a in engine.state.actors.values()}
        ctx = pulse_ctx(engine, zone, actor)
        p['seasons'] = choose(ctx, 'seasons', SEASONS, count=2 if p['ascension'] else 1,
            prompt=f'{ctx.action.display_name}: {ctx.actor.display_name}, choose {"two different seasons" if p["ascension"] else "one season"} until your next turn starts.')
        p['season_owner_turn'] = int(ctx.actor.turns_started)
        zone.trigger_profile['difficult'] = 'hostile' if 'root' in p['formulas'] or 'autumn' in p['seasons'] else None
        zone.trigger_profile['inside'] = ([{'id': 'harvest:winter', 'name': 'Winter protection', 'who': 'ally',
            'harvest_chosen': 1, 'modifiers': [{'field': 'armor_class_vs_ranged', 'operation': 'ADD', 'value': 1}]}]
            if 'winter' in p['seasons'] else [])
        record_zone_update(engine, zone)
        from ..zones import sync_inside
        sync_inside(engine, zone.source_definition_id)
        from ..movement_budget import speed_changed
        for a in engine.state.actors.values():
            delta = engine._effective_speed(a) - speeds[a.entity_id]
            if delta:
                speed_changed(engine, a, delta, zone.source_definition_id)
        if 'spring' in p['seasons']:
            pool = [aid for aid in allies(ctx, zone.center, 10000) if inside(engine, zone, engine.state.actors[aid])]
            selected = choose(ctx, 'spring_ally', pool, optional=True,
                prompt=f'Orchard Spring: {ctx.actor.display_name} chooses one ally in the field to regain 1d8 plus the Qi key modifier Hit Points.')
            if selected:
                heal(ctx, engine.state.actors[selected[0]], 1)
        if p['ascension'] and actor.entity_id in p['chosen_allies'] and inside(engine, zone, actor):
            move_offer(ctx, actor, 10, 'Ten Thousand Seed Ascension')


@hook('speed')
def autumn_speed(engine, actor):
    from ..relations import relation, ENEMY
    penalties = [5 for z in fields(engine) if 'autumn' in z.trigger_profile['profile'].get('seasons', ())
                 and live(engine, z) and inside(engine, z, actor) and relation(engine, engine.state.actors[z.owner_id], actor) == ENEMY]
    return -max(penalties) if penalties else None


@hook('difficult_exempt')
def water_terrain(engine, actor):
    from ..zones import area_cells
    cells = []
    for z in fields(engine):
        p = z.trigger_profile['profile']
        if live(engine, z) and actor.entity_id in p['chosen_allies'] and ('water_reed' in p['formulas'] or p['ascension']):
            cells.extend((c.x, c.y) for c in area_cells(engine, z))
    return cells


@hook('zone_recipient_allowed')
def chosen_recipient(engine, zone, actor, spec):
    if zone.trigger_profile.get('profile', {}).get(KEY) and spec.get('harvest_chosen'):
        eligible_zones = [z.zone_id for z in fields(engine) if live(engine, z) and inside(engine, z, actor)
            and 'winter' in z.trigger_profile['profile'].get('seasons', ())
            and actor.entity_id in z.trigger_profile['profile']['chosen_allies']]
        return bool(eligible_zones and zone.zone_id == min(eligible_zones))


@hook('save')
def winter_save(ctx, actor, ability, named):
    # Only explicit consequence tags qualify; cold damage does not imply this
    # saving throw resists environmental cold or a Cold-tagged effect.
    tags = set(named or ()) | set(ctx.typed.get('tags') or ())
    if not {'cold', 'environmental_cold'}.intersection(str(t).lower() for t in tags):
        return None
    if any(live(ctx.engine, z) and 'winter' in z.trigger_profile['profile'].get('seasons', ())
           and actor.entity_id in z.trigger_profile['profile']['chosen_allies'] and inside(ctx.engine, z, actor)
           for z in fields(ctx.engine)):
        return {'modes': ['ADVANTAGE']}


@hook('event', nested=True)
def summer_damage(engine, event_type, kwargs):
    if event_type != 'DAMAGE_COMMITTED' or int(kwargs.get('payload', {}).get('reduced_to', 0)) <= 0:
        return
    from ..relations import relation, ENEMY
    from .retained_updates import record_zone_update
    from ..typed_executor import run_effects
    current = engine.state.actors[engine.state.current_actor_id]
    clock = f'{engine.state.round_number}:{engine.state.current_slot_index}:{current.entity_id}:{current.turns_started}'
    for zone in list(fields(engine)):
        p = zone.trigger_profile['profile']
        marked = getattr(engine, '_harvest_pulsing_zone', None)
        if (p.get('violent_unused') and zone.source_definition_id == kwargs.get('source_definition_id')
                and marked == zone.zone_id):
            p['violent_unused'] = 0
            record_zone_update(engine, zone)
        if 'summer' not in p.get('seasons', ()) or not live(engine, zone):
            continue
        for aid in kwargs.get('target_ids', ()):
            target = engine.state.actors.get(aid)
            mark = 'harvest_summer:' + aid
            if (target is None or not target.active or not inside(engine, zone, target)
                    or relation(engine, engine.state.actors[zone.owner_id], target) != ENEMY
                    or p.get(mark) == clock):
                continue
            p[mark] = clock
            record_zone_update(engine, zone)
            ctx = pulse_ctx(engine, zone, target)
            run_effects(ctx, [{'type': 'damage', 'applies_to': 'target',
                'dice': {'count': 1, 'sides': 8}, 'damage_types': ['fire', 'radiant']}])


@hook('object_hp_floor')
def ascension_seed_protection(engine, attacker, obj, taken, source):
    if obj.component.get('asset_anchor_runtime', {}).get('group') != KEY or obj.component.get('restoration'):
        return None
    action = engine.action_catalog.get(source)
    level = ((action.parameters.get('typed') or {}).get('numbers') or {}).get('cl') if action else None
    if type(level) is not int:
        return None
    if any(z.trigger_profile['profile'].get('ascension') and live(engine, z) and inside(engine, z, obj)
           and level < int(z.trigger_profile['numbers']['cl']) for z in fields(engine)):
        return 1


def lantern_zones(engine, actor):
    return [z for z in fields(engine) if live(engine, z)
            and 'lantern_fruit' in z.trigger_profile['profile']['formulas'] and inside(engine, z, actor)
            and (not z.trigger_profile['profile'].get('seed_object')
                 or engine.grid.distance_ft(z.center, actor.position) <= 10)]


def manifestation_sources(engine):
    from ..observer_information import sources
    for s in sources(engine):
        tags = set(s['tags'])
        if 'possession' in tags:
            tags.add('active_possession')
        if 'temporary_corruption' in tags:
            tags.add('corruption')
        if s.get('holder_id'):
            actor = engine.state.actors[s['holder_id']]
            from .creature_kinds import matches
            invisible = any(c.condition_id in ('condition:typed.invisible', 'invisible') for c in actor.conditions.values())
            if invisible and (matches(actor, ['spirit']) or 'spirit_manifestation' in tags):
                tags.add('invisible_spirit')
        qualifying = tags & MANIFESTATIONS
        if qualifying:
            yield {**s, 'harvest_tags': qualifying}


def lantern_clear(engine, viewer, source, zone):
    level = source.get('cl')
    if type(level) is not int:
        return False
    if 'visual_illusion' in source['harvest_tags'] and level < int(zone.trigger_profile['numbers']['cl']):
        return True
    if level < int(zone.trigger_profile['numbers']['cl']) or not source['profile'].get('check_required'):
        return True
    return any(c.condition_id == 'condition:typed.harvest_lantern_clear'
        and c.data.get('zone_id') == zone.zone_id and c.data.get('source_id') == source['id']
        and c.data.get('revision') == str(source['revision']) for c in viewer.conditions.values())


class Located:
    def __init__(self, position):
        self.position = position


def sight_subject(engine, viewer, source):
    """The creature carrying a manifestation, or its located zone source, in the
    viewer's plain sight; None when the viewer cannot see the form.

    A holderless source (a zone classification with no holding creature) has no
    body to sight against, so it is visible when the viewer's own position has
    line of sight to the source's actual center position."""
    holder = engine.state.actors.get(source.get('holder_id'))
    if holder is not None:
        from ..senses import physical_sight
        return holder if physical_sight(engine, viewer, holder) else None
    if not engine.grid.line_of_sight(viewer.position, source['position']):
        return None
    return Located(source['position'])


@hook('observer_information')
def lantern_readings(engine, viewer):
    from ..senses import physical_sight
    if not any(live(engine, z) and 'lantern_fruit' in z.trigger_profile['profile']['formulas'] for z in fields(engine)):
        return []
    if any(c.condition_id in ('condition:typed.blinded', 'blinded') for c in viewer.conditions.values()):
        return []
    rows = []
    for source in manifestation_sources(engine):
        seen = sight_subject(engine, viewer, source)
        if seen is None:
            continue
        for zone in lantern_zones(engine, seen):
            if not lantern_clear(engine, viewer, source, zone):
                continue
            tags = source['harvest_tags']
            if tags & {'invisible_spirit', 'incorporeal', 'possessing_entity', 'active_possession'}:
                text = 'A spirit, incorporeal form, or possessing presence is outlined in the bright light.'
            elif 'visual_illusion' in tags:
                if int(source['cl']) >= int(zone.trigger_profile['numbers']['cl']):
                    continue
                text = 'A lower-level visual illusion flickers in the bright light.'
            else:
                text = 'Active poison, disease, or corruption leaves discoloration in the bright light.'
            # The plain sentence is the row's own text, which information_results.describe
            # presents to the observing seat (human player and model alike); a sentence
            # carried only under details would reach no player at all.
            rows.append({'ability': 'Lantern-Fruit Seed', 'kind': 'lantern_observation',
                'text': text, 'viewer_id': viewer.entity_id,
                'source_id': zone.source_definition_id,
                'details': {'position': seen.position.model_dump(mode='json')}, 'zone_id': zone.zone_id})
    for zone in fields(engine):
        p = zone.trigger_profile['profile']
        if not live(engine, zone) or 'lantern_fruit' not in p['formulas']:
            continue
        bright = 10 if p.get('seed_object') else int(zone.trigger_profile['size_ft'])
        if engine.grid.line_of_sight(viewer.position, zone.center):
            rows.append({'ability': 'Lantern-Fruit Seed', 'kind': 'illumination',
                'text': f'The Seed sheds Bright Light {bright} feet and Dim Light another 10 feet.',
                'viewer_id': viewer.entity_id,
                'source_id': zone.source_definition_id, 'details': {'center': zone.center.model_dump(mode='json'),
                    'bright_ft': bright, 'dim_outer_ft': bright + 10}, 'zone_id': zone.zone_id})
    return rows


@hook('masked_conditions')
def lantern_outlines(engine, viewer, target):
    if viewer is None or target is None:
        return None
    if not lantern_zones(engine, target):
        return None
    from ..senses import physical_sight
    if not physical_sight(engine, viewer, target):
        return None
    for source in manifestation_sources(engine):
        if source.get('holder_id') != target.entity_id or not source['harvest_tags'].intersection(
                {'invisible_spirit', 'incorporeal', 'possessing_entity', 'active_possession'}):
            continue
        if any(lantern_clear(engine, viewer, source, zone) for zone in lantern_zones(engine, target)):
            masks = {c.condition_id for c in target.conditions.values() if c.condition_id in ('invisible', 'condition:typed.invisible')}
            return {target.entity_id: masks} if masks else None


def examine_lantern(ctx):
    for source in manifestation_sources(ctx.engine):
        seen = sight_subject(ctx.engine, ctx.actor, source)
        if seen is None:
            continue
        from ..senses import physical_sight
        for zone in lantern_zones(ctx.engine, seen):
            if zone.owner_id != ctx.actor.entity_id or lantern_clear(ctx.engine, ctx.actor, source, zone):
                continue
            picked = choose(ctx, 'lantern_check', ['attempt'], optional=True,
                prompt=f'Lantern-Fruit: {seen.display_name} has equal or higher cultivation concealment in the light. Attempt a Cultivation Check to examine it, using no action?'
                    if hasattr(seen, 'display_name') else
                    f'Lantern-Fruit: a concealed zone form has equal or higher cultivation concealment in the light. Attempt a Cultivation Check to examine it, using no action?')
            if not picked:
                continue
            roll = ctx.engine.roller.d20(modifier=int(ctx.numbers['pb']) + int(ctx.numbers['key_mod']),
                actor_id=ctx.actor.entity_id, reason='CULTIVATION:Lantern-Fruit')
            ctx.engine._record_roll(roll)
            dc = source.get('dc') or 10 + int(source['cl']) // 2
            if roll.total >= int(dc):
                ctx.engine._apply_condition(ctx.actor, 'condition:typed.harvest_lantern_clear', ctx.source, ctx.actor.entity_id,
                    expires_on='UNTIL_REMOVED', data={'zone_id': zone.zone_id, 'source_id': source['id'],
                        'revision': str(source['revision']), 'label': 'Lantern-Fruit: concealment examined while this light lasts'})


@hook('event')
def cleanup_objects(engine, event_type, kwargs):
    from ..asset_anchor_runtime import retire
    if event_type == 'OBJECT_UPDATED':
        row = kwargs.get('payload', {}).get('object') or {}
        component = row.get('component') or {}
        if row.get('destroyed') and component.get('asset_anchor_runtime', {}).get('group') == KEY:
            from ..zones import remove
            zone = engine.state.zones.get(component.get('zone_id'))
            if zone and zone.active:
                remove(engine, zone, 'The Seed was destroyed or spent its last charge.')
    if event_type in ('ZONE_REMOVED', 'ZONE_ENDED'):
        zid = kwargs.get('payload', {}).get('zone_id')
        for obj in list(engine.state.objects.values()):
            if obj.component.get('zone_id') == zid and obj.component.get('asset_anchor_runtime', {}).get('group') == KEY:
                retire(engine, obj, BASE)
        from .condition_ownership import remove_instance
        for actor in engine.state.actors.values():
            for c in list(actor.conditions.values()):
                if c.condition_id == 'condition:typed.harvest_lantern_clear' and c.data.get('zone_id') == zid:
                    remove_instance(engine, actor, c.instance_id, BASE)


@hook('match_initialize')
def restore_stock(engine):
    for bundle in engine.typed_bundle_documents:
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is not None and ownership(engine, actor) and KEY in bundle:
            store(engine, actor, deepcopy(bundle[KEY]))
        if actor is not None and ownership(engine, actor) and bundle.get('harvest_live'):
            live_restore(engine, actor, bundle['harvest_live'])
        fact = bundle.get('harvest_manifestation')
        if actor is not None and fact:
            from ..observer_information import SOURCE
            from .effect_durations import token
            rounds = max(1, int(fact['remaining_seconds']) // 6)
            engine._apply_condition(actor, SOURCE, fact['profile']['source_id'], actor.entity_id,
                expires_on=token('start', actor.entity_id, actor.turns_started + rounds),
                data={'information_profile': fact['profile'], 'receipt_id': fact['receipt_id'],
                      'authority': 'table_owner', 'admission_source': BASE,
                      'label': 'Table-owner recorded manifestation'})
        # Two separate records may coexist (a table-owner confirmed cause and ordinary travel Exhaustion);
        # each crosses the carry under its own key and is restored as its own condition.
        for key, record, label in (
                ('harvest_exhaustion_origin', 'restoration', 'Exhaustion cause confirmed by the table owner'),
                ('harvest_ordinary_origin', 'ordinary', 'Ordinary travel Exhaustion recorded on the journey')):
            origin = bundle.get(key)
            held = any(c.condition_id == 'condition:typed.harvest_exhaustion_origin' and c.data.get('record') == record
                       for c in actor.conditions.values()) if actor is not None else True
            if actor is not None and origin and not held:
                from .forged_exhaustion import CONDITION_ID, level
                exhaustion = next((c for c in actor.conditions.values() if c.condition_id == CONDITION_ID), None)
                if exhaustion and level(actor) >= origin['levels']:
                    engine._apply_condition(actor, 'condition:typed.harvest_exhaustion_origin', RESTORE, actor.entity_id,
                        expires_on='UNTIL_REMOVED', data={**origin, 'record': record, 'exhaustion_instance': exhaustion.instance_id,
                            'label': label})


@hook('journey_initialize')
def initialize(session, aid):
    actor = session.state['actors'][aid]
    if bundle_ownership(actor['bundle']):
        actor.setdefault('source_states', {}).setdefault(KEY, blank())


@hook('journey_continued_concentration')
def carried_concentration(concentration):
    """Only this family's own Concentration (Orchard Field / Ten Thousand Seed
    Ascension) may cross a short encounter break; the live zones, Seeds and
    charges travel with it through journey_encounter_settled/journey_combat_bundle.
    Other sources keep the ordinary GM checkpoint."""
    source = str(getattr(concentration, 'source_definition_id', '') or '')
    if source.endswith('.harvest.field') or source.endswith('.harvest.ascension'):
        return 'carry'


@hook('journey_combat_bundle')
def carry_stock(bundle, session, aid):
    from ..fact_consent_admission import read
    record = read(session, BASE, aid, 'harvest_manifestation', 'native_source', aid)
    if record:
        bundle = {**bundle, 'harvest_manifestation': {'profile': deepcopy(record['value']),
            'receipt_id': record['receipt_id'], 'remaining_seconds': int(record['expires_at'] - session.clock())}}
    origin = read(session, RESTORE, aid, 'restoration_exhaustion_origin', 'native_source', aid)
    if origin:
        bundle = {**bundle, 'harvest_exhaustion_origin': {**deepcopy(origin['value']), 'receipt_id': origin['receipt_id']}}
    ordinary = session.state['actors'][aid].get('source_states', {}).get('harvest_ordinary_exhaustion')
    uncovered = uncovered_ordinary(session, aid, ordinary['levels']) if ordinary else 0
    if uncovered > 0:
        bundle = {**bundle, 'harvest_ordinary_origin': {**deepcopy(ordinary), 'levels': uncovered}}
    bed = read(session, BASE, aid, 'harvest_seed_bed', 'planting', aid)
    if bed:
        bundle = {**bundle, 'harvest_seed_bed': {**deepcopy(bed),
            'expires_round': int(bed['expires_at'] - session.clock()) // 6}}
    live = session.state['actors'][aid].get('source_states', {}).get('harvest_live')
    if live:
        carried = live_export_bundle(live, int(session.clock()) - int(live.get('saved_at', 0)))
        if carried:
            bundle = {**bundle, 'harvest_live': carried}
    if bundle_ownership(bundle):
        return {**bundle, KEY: deepcopy(session.state['actors'][aid]['source_states'][KEY])}
    return bundle


@hook('journey_encounter_settled')
def settle_stock(session, aid, engine, actor):
    saved = session.state['actors'][aid].setdefault('source_states', {})
    if ownership(engine, actor):
        saved[KEY] = stock(actor)
        carried = live_export(engine, actor)
        if carried:
            carried['saved_at'] = int(session.clock())
            saved['harvest_live'] = carried
        else:
            saved.pop('harvest_live', None)
    if saved.get('harvest_ordinary_exhaustion'):
        origin = next((c for c in actor.conditions.values() if c.condition_id == 'condition:typed.harvest_exhaustion_origin'
            and c.data.get('record') == 'ordinary' and c.data.get('exhaustion_instance') in actor.conditions), None)
        saved['harvest_ordinary_exhaustion']['levels'] = int(origin.data['levels']) if origin else 0


def uncovered_ordinary(session, aid, levels):
    """Ordinary travel levels not already claimed by the table-owner Restoration cause.
    The Restoration record and the ordinary record partition the creature's total Exhaustion:
    Restoration levels are covered first, so ordinary can never exceed what is left over."""
    from ..fact_consent_admission import read
    total = int(session.state['actors'][aid]['exhaustion'])
    origin = read(session, RESTORE, aid, 'restoration_exhaustion_origin', 'native_source', aid)
    covered = min(total, int(origin['value'].get('levels', 0))) if origin else 0
    return max(0, min(int(levels), total - covered))


@hook('journey_exhaustion_applied')
def ordinary_travel_origin(session, aid, count, ordinary):
    if not count or not ordinary or not any(RESTORE in (bundle_ownership(a['bundle']) or {}).get('features', ())
            for a in session.state['actors'].values()):
        return
    data = session.state['actors'][aid].setdefault('source_states', {}).setdefault('harvest_ordinary_exhaustion',
        {'cause': 'travel', 'levels': 0, 'receipt_id': ''})
    data['levels'] = uncovered_ordinary(session, aid, int(data['levels']) + int(count))
    data['receipt_id'] = 'journey-event:' + str(len(session.state['events']))


@hook('fact_admission_schema')
def material_schema(session, source, subject, kind):
    if source == BASE and kind == 'harvest_seed_bed' and bundle_ownership(session.state['actors'][subject]['bundle']):
        return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
            'description': 'Mapped planting medium and an explicitly sourced cultivated-land counterauthority. Higher ordinary authority can suppress germination; a lower ordinary drought cannot erase an established Seed.'}
    if source == RESTORE and kind == 'restoration_exhaustion_origin' and any(
            RESTORE in (bundle_ownership(a['bundle']) or {}).get('features', ()) for a in session.state['actors'].values()):
        return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
            'description': 'Confirm the ordinary cause of existing Exhaustion, bounded by this creature’s committed level. This declaration grants no Exhaustion.'}
    if source == BASE and kind == 'harvest_manifestation' and any(bundle_ownership(a['bundle']) for a in session.state['actors'].values()):
        return {'authority': 'table_owner', 'value_type': 'document', 'maximum_seconds': 86400,
                'description': 'Native owner classification of an intrinsic manifestation not represented by an existing mechanical source; exact tags, Source CL, check requirement and Cultivation Check DC.'}
    if source == BASE and kind == 'seed_growing_material' and bundle_ownership(session.state['actors'][subject]['bundle']):
        return {'authority': 'table_owner', 'value_type': 'flag', 'maximum_seconds': 86400,
                'description': 'Ordinary seeds or plant matter and suitable growing material are available for preparing Spirit Seeds.'}
    if source == BASE and kind == 'full_session_environment' and bundle_ownership(session.state['actors'][subject]['bundle']):
        return {'authority': 'table_owner', 'value_type': 'flag', 'maximum_seconds': 86400,
                'description': 'The next two uninterrupted hours are reasonably calm and have sufficient ambient spiritual energy or an appropriate substitute.'}


@hook('fact_admission_validate')
def validate_manifestation(session, source, subject, kind, value):
    """Strict gate: raise to refuse a malformed declaration, return None to admit it.

    The declaration path (combat/fact_consent_admission.py) calls this hook
    through run_strict and refuses only on an exception, so a boolean reply
    would silently admit a document it meant to reject. Each branch keeps the
    original field predicate and names the required fields in its refusal.
    """
    from ..journey import require
    if source == BASE and kind == 'harvest_seed_bed':
        require(isinstance(value, dict) and set(value) == {'cells', 'medium', 'source_id', 'source_cl', 'suppresses', 'authority'}
            and isinstance(value['cells'], list) and bool(value['cells']) and len(value['cells']) <= 100
            and all(isinstance(c, list) and len(c) == 3 and all(type(n) is int and n >= 0 for n in c)
                    and session.grid.in_bounds((c[0], c[1])) for c in value['cells'])
            and value['medium'] in {'solid', 'suitable_liquid', 'cultivated_land'}
            and type(value['source_id']) is str and bool(value['source_id'].strip())
            and type(value['source_cl']) is int and value['source_cl'] >= 0
            and type(value['suppresses']) is int and value['suppresses'] in (0, 1)
            and value['authority'] in {'ordinary', 'artifact', 'immortal', 'secret', 'conceptual', 'named_absolute'},
            "The declaration does not match this source's required fields.")
    elif source == RESTORE and kind == 'restoration_exhaustion_origin':
        require(isinstance(value, dict) and set(value) == {'cause', 'levels'} and value['cause'] in EXHAUSTION_CAUSES
            and type(value['levels']) is int and 1 <= value['levels'] <= session.state['actors'][subject]['exhaustion'],
            "The declaration does not match this source's required fields.")
    elif source == BASE and kind == 'harvest_manifestation':
        require(isinstance(value, dict) and set(value) == {'tags', 'source_id', 'source_cl', 'check_required', 'save_dc'}
            and type(value['source_id']) is str and bool(value['source_id'].strip())
            and isinstance(value['tags'], list) and bool(value['tags']) and all(type(t) is str for t in value['tags'])
            and len(value['tags']) == len(set(value['tags'])) and set(value['tags']) <= MANIFESTATIONS
            and type(value['source_cl']) is int and value['source_cl'] >= 1
            and type(value['save_dc']) is int and value['save_dc'] >= 1
            and type(value['check_required']) is int and value['check_required'] in (0, 1),
            "The declaration does not match this source's required fields.")


def materials(session, aid):
    from ..fact_consent_admission import read
    record = read(session, BASE, aid, 'seed_growing_material', 'preparation', aid)
    return bool(record and record['value'] == 1)


@hook('journey_options')
def preparation_options(session, aid):
    actor = session.state['actors'][aid]; own = bundle_ownership(actor['bundle'])
    if not own:
        return []
    data = actor.get('source_states', {}).get(KEY, blank())
    cl = int(own['numbers']['cl']); count = 5 if cl >= 10 else 4 if cl >= 6 else 3
    options = []
    if not data['formulas'] or cl > data['formula_cl']:
        for formulas in combinations(FORMULAS, count):
            if data['formulas'] and len(set(data['formulas']) - set(formulas)) > 1:
                continue
            options.append({'id': 'harvest:formulas:' + ','.join(formulas), 'kind': 'harvest_formulas',
                'payload': {'formulas': list(formulas)},
                'label': f'{actor["name"]}: learn ' + ', '.join(title(f) for f in formulas) + ' Seed Formulas.'})
    options.extend([{'id': 'harvest:replacement', 'kind': 'harvest_replacement', 'payload': {},
             'label': f'{actor["name"]}: spend 10 minutes and 1 Qi preparing one replacement Spirit Seed, up to Proficiency Bonus; requires seed and growing material.'}]
    )
    options.append({'id': 'harvest:session', 'kind': 'harvest_session', 'payload': {},
        'label': f'{actor["name"]}: prepare Spirit Seeds after 2 uninterrupted hours of cultivation in a calm place with sufficient spiritual energy; requires seed and growing material. This procedure prepares Seeds only.'})
    return options


@hook('journey_command')
def preparation_command(session, aid, kind, payload):
    if not kind.startswith('harvest_'):
        return None
    from ..journey import require
    actor = session.state['actors'][aid]; own = bundle_ownership(actor['bundle'])
    require(own is not None and not actor['incapacitated'], 'An able Harvest Cultivator must prepare the Seeds.')
    data = actor.setdefault('source_states', {}).setdefault(KEY, blank())
    cl = int(own['numbers']['cl']); pb = int(own['numbers']['pb'])
    if kind == 'harvest_formulas':
        count = 5 if cl >= 10 else 4 if cl >= 6 else 3
        selected = payload.get('formulas', FORMULAS if count == 5 else [])
        require(set(payload) <= {'formulas'} and len(selected) == count and len(set(selected)) == count and set(selected) <= set(FORMULAS), 'Choose the exact number of distinct learned Formulas.')
        if data['formulas']:
            require(cl > data['formula_cl'], 'You may replace a known Formula only when gaining a Qi Cultivation level.')
            require(len(set(data['formulas']) - set(selected)) <= 1, 'Replace at most one Formula at a Qi level gain.')
        data['formulas'] = list(selected); data['formula_cl'] = cl
    elif kind == 'harvest_replacement':
        require(not payload and materials(session, aid), 'Preparing a Seed requires ordinary seed/plant matter and suitable growing material confirmed by the table owner.')
        require(data['stock'] < pb and actor['resources'].get('resource:core.qi', 0) >= 1, 'A replacement costs 1 Qi and cannot exceed Proficiency Bonus stock.')
        actor['resources']['resource:core.qi'] -= 1
        session.tick(600); data['stock'] += 1
    elif kind == 'harvest_session':
        from ..fact_consent_admission import read
        record = read(session, BASE, aid, 'full_session_environment', 'preparation', aid)
        require(not payload and record and record['value'] == 1 and record['expires_at'] > session.clock() + 7200
                and materials(session, aid), 'Preparing Seeds during a Full Cultivation Session requires two uninterrupted calm hours, sufficient spiritual energy, seeds and growing material confirmed by the table owner.')
        session.tick(7200)
        require(materials(session, aid), 'Seed and growing material must remain available when preparation completes.')
        data['stock'] = pb
    else:
        raise ValueError('Unknown Harvest cultivation procedure.')
    session.emit('HARVEST_PREPARATION', aid, source=BASE, operation=kind, state=deepcopy(data))
    return True


@hook('journey_rest')
def prepare_after_rest(session, aid):
    actor = session.state['actors'][aid]; own = bundle_ownership(actor['bundle'])
    if own and materials(session, aid):
        data = actor.setdefault('source_states', {}).setdefault(KEY, blank())
        data['stock'] = int(own['numbers']['pb'])
        session.emit('HARVEST_PREPARATION', aid, source=BASE, operation='long_rest', state=deepcopy(data))


@hook('journey_scene_end')
def scene_recovery(session, previous, current):
    for aid, actor in session.state['actors'].items():
        if bundle_ownership(actor['bundle']):
            actor.setdefault('source_states', {}).setdefault(KEY, blank())['ascension_used'] = 0
