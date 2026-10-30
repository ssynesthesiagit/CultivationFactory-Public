"""Appraise the Venom: one source-owned, transactional diagnostic provider.

Subject selection uses live actors, physical wounds, inventory, map objects and
sealed encounter sensory sources. No category creates a physical object. The
encounter's poison medium describes actual material properties (contents,
delivery routes, onset and countermeasure scope), never player diagnostic
answers. Missing properties remain unknown. Mechanical conditions are read
directly, including creator-scoped marks; finding prose never names creators.

Findings and profiles use information_results' private journal storage and
observer_information delivery. Internal toxin identity is retained separately
from the allowlisted learned facts. Profile limits come from the governing
Poison rules: PB profiles, dismiss at will, until the next long rest. Combat
contains no long rest; profile records carry that lifecycle explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import effect, hook

SOURCE = 'POISON_BASE_APPRAISE_THE_VENOM'
NAME = 'Appraise the Venom'
PREFIX = 'choice:needle.venom_'
FACTS = {
    'classification': 'Poison classification: ordinary, alchemical, spiritual, demonic, plant, beast, mineral or corrosive',
    'poisoned': 'Whether the subject is Poisoned (Disadvantage on attacks and ability checks)',
    'dose_marks': 'Your own Dose Marks (toxic traces you can spend with Poison abilities)',
    'burden': 'Toxin Burden (poison settled deeper than a surface wound)',
    'ingrained': 'Ingrained Toxin (a lingering poison pattern)',
    'danger': 'Immediate, delayed or long-term danger',
    'antidote': 'Whether an ordinary antidote might help',
    'handling': 'Safe handling in this scene',
    'sphere': 'Association with another sphere',
}
# One transient declaration per engine, never saved fight state. Weak engine
# identity prevents cross-fight/owner cache reuse or retention. The string
# intent binding is rechecked by the effect and native subjects are resolved
# again after declarations. Paused previews own their own engine instance.
_DECLARED_SUBJECT = WeakKeyDictionary()


class Substance(BaseModel):
    """Physical world truth from the sealed encounter, not revelation authority.

    The identity is private, and never used as a display label. Extra provenance
    such as formulas is deliberately ignored and never copied to a finding.
    None means unknown; an empty sphere list explicitly means no association.
    """
    model_config = ConfigDict(extra='ignore', strict=True)
    toxin_id: str = Field(min_length=1)
    classification: Literal['ordinary', 'alchemical', 'spiritual', 'demonic', 'plant-based',
                            'beast-based', 'mineral', 'corrosive', 'unknown'] = 'unknown'
    onset: Literal['immediate', 'delayed', 'long-term'] | None = None
    routes: list[Literal['contact', 'inhaled', 'ingested', 'injury', 'spiritual']] | None = None
    antidote_scope: Literal['ordinary', 'special', 'none'] | None = None
    spheres: list[str] | None = None

    @field_validator('spheres')
    @classmethod
    def native_spheres(cls, values):
        if values is None:
            return None
        from factory_authoring.path_access import access
        names = {key.casefold(): row['name'] for key, row in access().items()}
        names.update({row['name'].casefold(): row['name'] for row in access().values()})
        names['another sphere'] = 'another sphere'
        if any(value.casefold() not in names for value in values):
            raise ValueError('A toxin association must name a native sphere')
        return [names[value.casefold()] for value in values]


class Material(BaseModel):
    """Source-bound extension to encounter_sources' native poison medium.

    Exactly one native anchor is required by encounter_sources.sources. Item
    and wound bindings further narrow an entity anchor; terrain binds an actual
    active zone and one of its cells. The sealed battlefield hash, row key and
    native subject are retained in private profiles. No action accepts these
    properties from an intent, choice reply or player diagnostic receipt.
    """
    model_config = ConfigDict(extra='ignore', strict=True)
    source_key: str = Field(min_length=1)
    kind: Literal['creature', 'corpse', 'object', 'wound', 'food', 'drink', 'weapon',
                  'sample', 'terrain', 'contamination', 'poison']
    contents: list[Substance] | None = None
    sealed: Literal[0, 1] | None = None
    item_key: str | None = None
    wound_instance_id: str | None = None
    zone_id: str | None = None


@dataclass
class Subject:
    key: str
    label: str
    kind: str
    position: object
    actor: object = None
    obj: object = None
    zone: object = None
    conditions: tuple = ()
    material: Material | None = None
    touching: bool = False
    visible: bool = False


def is_appraisal(action):
    typed = (getattr(action, 'parameters', None) or {}).get('typed') or {}
    return typed.get('source') == SOURCE and any(r.get('type') == 'poison_appraisal'
                                                for r in typed.get('effects') or [])


@hook('compile_action')
def seal_action(action, info):
    if not is_appraisal(action):
        return None
    from ..factory_compiler import RESOURCE_IDS
    resource = info['owner_sheet']['ability_scores_and_statistics'].get('primary_resource') or {}
    if isinstance(resource, str):
        import json
        resource = json.loads(resource)
    primary = str(resource.get('name') or 'Qi').lower()
    from factory_authoring.path_access import can_learn
    identity = info['owner_sheet'].get('identity') or {}
    paths = identity.get('path_ids') or (info['owner_sheet'].get('path_and_subpath') or {}).get('path_record_ids') or [
        {'Qi Cultivation': 'tianxia.path.qi_cultivation', 'Body Refining': 'tianxia.path.body_refining',
         'Spirit Awakening': 'tianxia.path.spirit_awakening'}.get(identity.get('path'), '')]
    # A self-targeted envelope opens the native subject chooser. It neither
    # changes another action's target permissions nor applies effects to self.
    return action.model_copy(update={'target_kind': 'SELF',
        'parameters': {**action.parameters, 'venom_pool': RESOURCE_IDS.get(primary, 'resource:core.qi'),
                       'venom_path_eligible': can_learn('tianxia.sphere.poison', paths),
                       'description': 'One Action, no base CP cost. Examine one subject by touch or clear perception '
                                      'within 30 feet. Learn poison presence and one chosen fact; optionally pay '
                                      '1 Cultivation Point for three facts. An optional Antidote Profile costs '
                                      'nothing extra. No formulas, creators, secret techniques, rare recipes or history.'}})


def physical_contact(engine, viewer, target):
    """Actual body/physical-hold contact; adjacency and memory prove neither."""
    if viewer.entity_id == target.entity_id:
        return True
    from .hand_occupancy import physical_holds
    return any(subject.entity_id == target.entity_id for subject, _ in physical_holds(engine, viewer)) or any(
        subject.entity_id == viewer.entity_id for subject, _ in physical_holds(engine, target))


def _reachable(engine, viewer, subject, maximum):
    from ..targeting import line_of_effect
    if subject.touching:
        return True
    if subject.obj is not None:
        from ..object_geometry import target_cells
        from ..senses import perceives_cell
        return any(engine._distance_actor_to_cell(viewer, cell) <= maximum
                   and perceives_cell(engine, viewer, cell)
                   for cell in target_cells(engine, subject.obj))
    creature = subject.actor if subject.kind != 'corpse' else None
    distance = (engine._distance_actor_to_actor(viewer, creature) if creature is not None
                else engine._distance_actor_to_cell(viewer, subject.position))
    return distance <= maximum and subject.visible and line_of_effect(engine, viewer,
        target=creature, destination=None if creature is not None else subject.position)


def subjects(engine, viewer, action=None):
    """All native eligible subjects, without peeking at their toxic contents."""
    from .. import carry, senses
    from ..gate2_runtime_models import Position
    from ..target_knowledge import located, can_see, requires_sight
    from ..information_results import creature_name
    from .life_state import is_deceased
    from ..condition_names import condition_key
    from ..encounter_sources import sources
    from ..zones import typed_zones

    maximum = 30
    sight_only = action is not None and requires_sight(action)
    if action is not None:
        from ..attack_reach import maximum as current_range
        # The declaration pipeline already returns its range-adjusted action.
        maximum = max(0, current_range(engine, viewer, action) or 0)
    result = {}
    for actor in engine.state.actors.values():
        if not actor.active and not is_deceased(actor):
            continue
        touching = physical_contact(engine, viewer, actor)
        # Pinpointing reveals a subject, not its hidden identity.
        seen = (senses.perceives_cell(engine, viewer, actor.position) if is_deceased(actor)
                else can_see(engine, viewer, actor) if sight_only else located(engine, viewer, actor))
        touching = touching and (not sight_only or seen)
        name = creature_name(engine, viewer, actor.entity_id,
                             'Yourself' if actor is viewer else 'the perceived creature' if seen else 'the creature in contact')
        body_conditions = []
        for condition in actor.conditions.values():
            if condition.condition_id == 'condition:typed.poison_coating':
                weapon = engine.action_catalog.get(condition.data.get('weapon'))
                if weapon is not None and (weapon.parameters.get('typed') or {}).get('weapon'):
                    continue  # venom on a carried blade belongs to that blade
            body_conditions.append(condition)
        subject = Subject(actor.entity_id, name, 'corpse' if is_deceased(actor) else 'creature',
                          actor.position, actor=actor, conditions=tuple(body_conditions),
                          touching=touching, visible=seen)
        if _reachable(engine, viewer, subject, maximum):
            result[subject.key] = subject
            for condition in actor.conditions.values():
                if condition_key(condition.condition_id) in {'bleeding', 'wounded', 'injury'}:
                    key = 'wound:' + actor.entity_id + ':' + condition.instance_id
                    result[key] = Subject(key, 'Wound on ' + name, 'wound', actor.position,
                        actor=actor, conditions=(condition,), touching=touching, visible=seen)
    for obj in engine.state.objects.values():
        if obj.destroyed or obj.suppressed or not senses.perceives_object(engine, viewer, obj):
            continue
        from ..object_rules import label
        subject = Subject(obj.object_id, label(obj), 'object', obj.position, obj=obj, visible=True)
        if _reachable(engine, viewer, subject, maximum):
            result[subject.key] = subject
    # Inventory identities survive native drop, pickup and hand transfer.
    for owner in engine.state.actors.values():
        for item in (carry.carrying_of(engine, owner.entity_id) or {}).get('items') or []:
            if carry.quantity_exhausted(engine, owner, item):
                continue
            bearer = carry.item_carrier(engine, owner, item['key'])
            carrier = engine.state.actors.get(bearer)
            dropped = carry.dropped(owner, item['key'])
            if carrier is not None:
                position = carrier.position
                from .hand_occupancy import weapon_grips
                location = carry.owned_item_location(owner, item['key']) or ''
                in_hand = location.startswith('hand:') or item.get('weapon_action') in weapon_grips(engine, carrier)
                # Carrying a bag is not contact with everything inside it, and
                # seeing a carrier never reveals hidden inventory identities.
                touching = carrier.entity_id == viewer.entity_id and in_hand
                visible = in_hand and senses.ordinary_sight_perceives(engine, viewer, carrier)
                touching = touching and (not sight_only or visible)
            elif dropped:
                position = Position.model_validate(owner.conditions[dropped].data['dropped_at'])
                touching, visible = False, senses.perceives_cell(engine, viewer, position)
            else:
                continue
            key = 'inventory:' + owner.entity_id + ':' + item['key']
            subject = Subject(key, str(item.get('name') or 'carried item'),
                'weapon' if item.get('weapon_action') else 'object', position,
                conditions=tuple(c for c in owner.conditions.values()
                    if c.condition_id == 'condition:typed.poison_coating'
                    and c.data.get('weapon') == item.get('weapon_action')),
                touching=touching, visible=visible)
            if _reachable(engine, viewer, subject, maximum):
                result[key] = subject
    zones = {z.zone_id: z for z in typed_zones(engine) if z.active}
    for zone in zones.values():
        if not zone.trigger_profile.get('terrain'):
            continue
        # One real, clearly perceived patch of this native terrain, never the
        # hidden rest of its area. The full zone remains its private identity.
        cells = [cell for cell in zone.affected_cells
                 if engine._distance_actor_to_cell(viewer, cell) <= maximum
                 and senses.perceives_cell(engine, viewer, cell)]
        if cells:
            position = min(cells, key=lambda p: (engine._distance_actor_to_cell(viewer, p), p.x, p.y, p.z))
            subject = Subject(zone.zone_id, 'Terrain patch: ' + str(zone.trigger_profile.get('name') or 'ground'),
                              'terrain', position, zone=zone, visible=True)
            if _reachable(engine, viewer, subject, maximum):
                result[zone.zone_id] = subject
    # The existing encounter-source caller seals these rows at match creation;
    # they are never supplied by the appraisal action's choices.
    for row, position, actor, obj in sources(engine, 'poison', include_corpses=True):
        material = Material.model_validate(row)
        if material.item_key:
            if actor is None:
                continue
            key = 'inventory:' + actor.entity_id + ':' + material.item_key
        elif material.wound_instance_id:
            if actor is None:
                continue
            key = 'wound:' + actor.entity_id + ':' + material.wound_instance_id
        elif actor is not None:
            key = actor.entity_id
        elif obj is not None:
            key = obj.object_id
        else:
            key = 'scene:' + material.source_key
            if material.kind == 'terrain':
                zone = zones.get(material.zone_id)
                if zone is None or position not in zone.affected_cells:
                    continue
                key = zone.zone_id
            elif material.kind != 'contamination' or row.get('obvious') != 1:
                continue  # a label cannot create a sample/food/weapon/corpse
            visible = senses.perceives_cell(engine, viewer, position)
            subject = Subject(key, str(row.get('label') or ('terrain patch' if material.kind == 'terrain' else 'visible contamination')),
                              material.kind, position, zone=zones.get(material.zone_id), visible=visible)
            if not _reachable(engine, viewer, subject, maximum):
                continue
            result[key] = subject
        if key not in result:
            continue
        subject = result[key]
        if actor is not None and not (material.item_key or material.wound_instance_id):
            if material.kind not in {'creature', 'corpse'} or (material.kind == 'corpse') != is_deceased(actor):
                continue
        # Conflicting or duplicated authorship is an invalid encounter, never
        # last-writer-wins poison truth.
        if subject.material is not None:
            raise ValueError('A subject has more than one poison material source')
        subject.material = material
        subject.kind = material.kind
    return result


def _mechanical(subject):
    from ..condition_names import condition_key
    return [c for c in subject.conditions if not (c.data or {}).get('suppressed')
            and not c.condition_id.startswith('condition:typed.suppressed.')], condition_key


def _source(engine, row):
    from .source_eligibility import catalog_action
    action = catalog_action(engine, row.source_definition_id)
    typed = (action.parameters.get('typed') or {}) if action is not None else {}
    if not typed.get('sphere') and typed.get('source'):
        from ..typed_numbers import authority_mechanics
        record = authority_mechanics().get(typed.get('option_of') or typed['source']) or {}
        typed = {**typed, 'sphere': record.get('sphere_id')}
    return typed


def _ingrained(engine, subject):
    rows = [*subject.conditions, *(subject.actor.modifiers.values() if subject.actor is not None
                                  and subject.kind in {'creature', 'corpse'} else [])]
    for row in rows:
        if getattr(row, 'data', {}).get('suppressed'):
            continue
        typed = _source(engine, row)
        if ('ingrained' in getattr(row, 'condition_id', '').lower()
                or (typed.get('option_of') or typed.get('source')) == 'POISON_BASE_INGRAIN_THE_TOXIN'):
            return True
    return False


def presence(engine, subject):
    conditions, name = _mechanical(subject)
    if any(name(c.condition_id) in {'poisoned', 'ingrainedtoxin', 'ingrained_toxin', 'poison_coating', 'mundane_poison_residue'} or
           c.condition_id.startswith(('condition:typed.mark.dose_mark.', 'condition:typed.mark.toxin_burden.'))
           for c in conditions) or _ingrained(engine, subject):
        return True
    if _zone_toxins(subject):
        return True
    if subject.material is not None and subject.material.contents is not None:
        return bool(subject.material.contents)
    return None


def _zone_toxins(subject):
    """Poison/Acid hazard packets in real terrain, not its name or paint."""
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from walk(child)
    profile = subject.zone.trigger_profile if subject.zone is not None else {}
    return {kind.lower() for row in walk(profile) if row.get('type') in {'damage', 'extra_damage'}
            for kind in [*(row.get('damage_types') or []), row.get('damage_type') or '']
            if kind.lower() in {'poison', 'acid'}}


def _substances(subject):
    if subject.material and subject.material.contents is not None:
        return subject.material.contents
    kinds = _zone_toxins(subject)
    if kinds:
        return [Substance(toxin_id=subject.zone.source_definition_id + ':' + subject.zone.zone_id,
                          classification='corrosive' if 'acid' in kinds else 'unknown', onset='immediate')]
    return []


def fact(engine, owner, subject, key):
    """Compute only the selected printed category; never copy source prose."""
    conditions, name = _mechanical(subject)
    substances = _substances(subject)
    material = subject.material
    unknown = 'Unknown: the available traces do not establish this fact.'
    creature = subject.kind in {'creature', 'corpse'} and subject.actor is not None
    if key == 'poisoned':
        return ('The subject is Poisoned (Disadvantage on attacks and ability checks).' if
                any(name(c.condition_id) == 'poisoned' for c in conditions) else
                'The subject is not Poisoned.' if creature else 'Poisoned is a creature condition; it does not apply to this subject.')
    if key == 'dose_marks':
        if not creature:
            return 'Dose Marks are creature traces; none are recorded on this subject.'
        from .stacking_marks import count
        number = count(engine, owner, subject.actor, 'Dose Mark')
        return f'The subject carries {number} of your Dose Marks.' if number else 'The subject carries none of your Dose Marks.'
    if key == 'burden':
        from ..typed_executor import mark_condition_id
        held = any(c.condition_id == mark_condition_id('Toxin Burden', a.entity_id)
                   for c in conditions for a in engine.state.actors.values())
        return 'The subject has Toxin Burden (deeper settled poison).' if held else 'The subject has no Toxin Burden recorded.'
    if key == 'ingrained':
        held = _ingrained(engine, subject)
        return 'The subject has an Ingrained Toxin (lingering poison).' if held else 'The subject has no Ingrained Toxin recorded.'
    if key == 'classification':
        classes = sorted({s.classification for s in substances})
        return 'Poison classification: ' + ', '.join(classes) + '.' if classes else unknown
    if key == 'danger':
        kinds = sorted({s.onset for s in substances if s.onset})
        if _ingrained(engine, subject):
            kinds.append('long-term')
        if any(name(c.condition_id) == 'poisoned' for c in conditions):
            kinds.append('immediate')
        if not kinds:
            return unknown
        return ('Poison danger: ' + ', '.join(sorted(set(kinds))) + '.'
                + (' Additional poison danger is unknown.' if any(s.onset is None for s in substances) else ''))
    if key == 'antidote':
        scopes = {s.antidote_scope for s in substances}
        if scopes and None not in scopes:
            return ('An ordinary antidote might help' + (' with some of the poison.' if len(scopes) > 1 else '.')
                    if 'ordinary' in scopes else 'An ordinary antidote is not a matching countermeasure for this poison.')
        return unknown
    if key == 'handling':
        if material and material.sealed == 1:
            return 'Safe to carry while its present container stays sealed; opening it is not certified safe.'
        routes = {r for s in substances for r in s.routes or []}
        if material and material.sealed == 0 and routes & {'contact', 'inhaled', 'spiritual'}:
            return 'Unsafe to handle directly in this scene: exposed poison can affect contact, breath or spirit.'
        return unknown
    if key == 'sphere':
        spheres = {str(_source(engine, c).get('sphere') or '').removeprefix('tianxia.sphere.').title()
                   for c in conditions if name(c.condition_id) == 'poisoned'
                   or name(c.condition_id) == 'poison_coating'
                   or c.condition_id.startswith(('condition:typed.mark.dose_mark.', 'condition:typed.mark.toxin_burden.'))}
        if subject.zone is not None and _zone_toxins(subject):
            spheres.add(str(_source(engine, subject.zone).get('sphere') or '').removeprefix('tianxia.sphere.').title())
        spheres.update(n for s in substances for n in s.spheres or [])
        if spheres - {''}:
            return 'Sphere association: ' + ', '.join(sorted(spheres - {''})) + '.'
        if substances and all(s.spheres == [] for s in substances):
            return 'Sphere association: no association.'
        return unknown
    raise ValueError('Unknown appraisal fact')


def _ask(ctx, key, options, *, label, labels=None, maximum=1, optional=False, cancel=False, preferred=None, payment=None):
    from .needle import ask, checkpoint_id
    return ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'VENOM_' + key, ctx.actor.entity_id),
        ctx.actor, PREFIX + key, list(options), labels=labels or {k: k for k in options},
        prompt=NAME + ': ' + label, name=NAME, minimum=maximum, maximum=maximum,
        allow_decline=optional or cancel, preferred=preferred, default='decline' if optional else 'all',
        payment=payment)


@hook('technique_declared')
def declare_subject(engine, actor, action, candidate, intent):
    if not is_appraisal(action) or action.owner_id != actor.entity_id:
        return None
    from ..typed_executor import Context
    _DECLARED_SUBJECT.pop(engine, None)
    ctx = Context(engine, actor, action, intent, action.parameters['typed'], [actor], actor, {})
    available = subjects(engine, actor, action)
    chosen = _ask(ctx, 'subject', available, labels={k: v.label for k, v in available.items()},
                  cancel=True, label='Choose one subject to examine now. One Action; no base Cultivation Point cost. '
                                     'Decline to cancel without spending your Action or points.')
    if not chosen:
        return {'source_id': SOURCE, 'label': NAME, 'cancel': True, 'spend_activation': False}
    _DECLARED_SUBJECT[engine] = (intent.intent_id, chosen[0])
    return None


@hook('activation_end')
def finish_declaration(engine, actor, action, candidate, intent):
    if is_appraisal(action) and action.owner_id == actor.entity_id:
        _DECLARED_SUBJECT.pop(engine, None)


@effect('poison_appraisal', harmful=False, forge_rejection='Appraise the Venom requires its own acquired Poison ability.')
def appraise(ctx, row):
    from ..information_results import record_private, private_records
    from .choice_costs import payable
    if not is_appraisal(ctx.action) or ctx.action.owner_id != ctx.actor.entity_id or ctx.action.source_definition_id not in ctx.actor.action_ids:
        return
    available = subjects(ctx.engine, ctx.actor, ctx.action)
    declaration = _DECLARED_SUBJECT.pop(ctx.engine, None)
    if declaration is None or declaration[0] != ctx.intent.intent_id or declaration[1] not in available:
        raise ValueError('The declared Appraise the Venom subject is no longer available')
    subject = available[declaration[1]]
    payment = payable(ctx.actor, ctx.action.parameters['venom_pool'], 1)
    extra = _ask(ctx, 'detail', ['three'], labels={'three': 'Spend 1 Cultivation Point to learn three distinct facts instead of one'},
                 label=f'Examine {subject.label}: optionally pay for three facts; decline for one free fact.',
                 optional=True, payment=payment) if payment else []
    count = 3 if extra else 1
    selected = _ask(ctx, 'facts', FACTS, labels=FACTS, maximum=count,
                    label=f'Examine {subject.label}: choose {count} distinct facts. Poison presence is always included.')
    if len(selected) != count or len(set(selected)) != count or not set(selected) <= set(FACTS):
        raise ValueError('Choose the stated number of distinct appraisal facts')
    # Re-resolve native identity after all answered choices; nothing is paid or
    # learned until every decision, including profile capacity, has succeeded.
    current = subjects(ctx.engine, ctx.actor, ctx.action).get(subject.key)
    if current is None:
        raise ValueError('The subject is no longer available for Appraise the Venom')
    status = presence(ctx.engine, current)
    learned = {key: fact(ctx.engine, ctx.actor, current, key) for key in selected}
    profile = []
    profiles = private_records(ctx.engine, ctx.actor, SOURCE, 'antidote_profile')
    if status is True or current.kind == 'sample':
        profile = _ask(ctx, 'profile', ['create'], labels={'create': 'Create an Antidote Profile: understanding, not a physical antidote; no extra cost'},
            label=f'Appraise {current.label}: create a profile? Keep up to your Proficiency Bonus; lasts until a long rest.', optional=True)
    key = canonical_identity(ctx.engine, current)
    dismiss = []
    if profile and key not in profiles and len(profiles) >= ctx.actor.proficiency_bonus:
        dismiss = _ask(ctx, 'replace', profiles, labels={k: 'Dismiss profile: ' + v['public']['subject'] for k, v in profiles.items()},
                       label='Your profiles are full. Choose one to dismiss before creating this profile.')
        if not dismiss:
            raise ValueError('No profile was dismissed; appraisal canceled')
    if extra:
        if payment is None or not payable(ctx.actor, payment.pool, payment.amount):
            raise ValueError('The Cultivation Point for Appraise the Venom is no longer available')
        payment.pay(ctx.engine, ctx.actor, ctx.source)
    public = {'ability': NAME, 'kind': 'reading', 'subject': current.label,
              'presence': 'unknown' if status is None else 'present' if status else 'absent',
              'facts': learned}
    public['text'] = describe(public)
    record_private(ctx.engine, ctx.actor, ctx.source, SOURCE, 'appraisal', current.key, public)
    if profile:
        if dismiss:
            record_private(ctx.engine, ctx.actor, ctx.source, SOURCE, 'antidote_profile', dismiss[0], None)
        saved = {**public, 'kind': 'antidote_profile', 'lifetime': 'until your next long rest'}
        saved['text'] = describe(saved)
        record_private(ctx.engine, ctx.actor, ctx.source, SOURCE, 'antidote_profile', key, saved,
            identity={'subject': current.key, 'source': SOURCE,
                      'source_text_sha256': '39ee306edfffa683cad887972e68ed007986f760905ce0dd6318e1cf1a97eda8',
                      'material_source': current.material.source_key if current.material else '',
                      'toxins': [s.toxin_id for s in _substances(current)],
                      'mechanical_sources': sorted({c.source_definition_id for c in current.conditions
                          if c.condition_id.startswith(('condition:typed.mark.dose_mark.', 'condition:typed.mark.toxin_burden.'))
                          or c.condition_id in {'condition:typed.poisoned', 'condition:typed.poison_coating'}})})


def describe(reading):
    status = reading['presence']
    presence = ('Poison is present.' if status == 'present' else 'Poison is absent.'
                if status == 'absent' else 'Poison presence is unknown.')
    profile = reading['kind'] == 'antidote_profile'
    text = ('Antidote Profile for ' if profile else 'Examination of ') + reading['subject'] + ': '
    text += presence + ' ' + ' '.join(reading['facts'].values())
    if profile:
        text += ' Understanding only, not a physical antidote; until your next long rest. You can dismiss it at any time.'
    return text


def canonical_identity(engine, subject):
    from ..canonical import canonical_sha256
    return canonical_sha256({'subject': subject.key,
        'toxins': sorted(s.toxin_id for s in _substances(subject)),
        'conditions': sorted(c.instance_id for c in subject.conditions) if not _substances(subject) else [],
        'material_source': subject.material.source_key if subject.material else ''})


@hook('observer_information')
def learned_information(engine, observer):
    from ..information_results import private_records
    if not any(is_appraisal(engine.action_catalog.get(key)) for key in observer.action_ids):
        return []
    # Knowledge belongs to its appraiser; allies and other Poison owners do not
    # inherit it. Only the explicit public half ever leaves this provider.
    return [v['public'] for kind in ('appraisal', 'antidote_profile')
            for v in private_records(engine, observer, SOURCE, kind).values()]


@hook('compile_actions')
def profile_management(info):
    if SOURCE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.venom_profiles",
        display_name='Dismiss an Antidote Profile', owner_id=info['actor_id'], economy='NONE',
        resolution_kind='TYPED', target_kind='SELF', parameters={'player_only': True,
            'typed': {'source': SOURCE, 'effects': [{'type': 'poison_profile_dismiss'}],
                      'numbers': info['numbers'], 'riders': [], 'duration': {'kind': 'instant'}}})]


@hook('candidate_allowed')
def dismissal_available(engine, actor, candidate, action):
    if is_appraisal(action):
        return (action.owner_id == actor.entity_id and action.source_definition_id in actor.action_ids
                and bool(action.parameters.get('venom_path_eligible', True)))
    if action is None or not any(r.get('type') == 'poison_profile_dismiss'
                                for r in (action.parameters.get('typed') or {}).get('effects') or []):
        return None
    from ..information_results import private_records
    return bool(private_records(engine, actor, SOURCE, 'antidote_profile'))


@effect('poison_profile_dismiss', harmful=False)
def dismiss_profile(ctx, row):
    from ..information_results import private_records, record_private
    profiles = private_records(ctx.engine, ctx.actor, SOURCE, 'antidote_profile')
    selected = _ask(ctx, 'dismiss', profiles,
        labels={k: 'Dismiss ' + v['public']['subject'] for k, v in profiles.items()},
        label='Dismiss one of your Antidote Profiles at no Action or Cultivation Point cost.', optional=True)
    if selected:
        record_private(ctx.engine, ctx.actor, ctx.source, SOURCE, 'antidote_profile', selected[0], None)
