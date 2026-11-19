"""Shared public Foundation method and settled-event facts.

Used by foundations3.py, ash_garden.py and foundation_mercy.py. Exact compiled
source records identify methods; battlefield residue and damage categories can
require public table answers. Automatic seats use only observed facts, their
own setup declarations or a conscious human witness of the event.
"""
from . import hook
from .needle import ask, checkpoint_id

ASH = 'foundation.red_lotus_ash_returning_v0_2B.'
CONTEXT = 'choice:needle.foundation_event_context'
UNCONSCIOUS = frozenset(('unconscious', 'life_unconscious', 'asleep', 'dream_sleep'))
SCENE_SOURCE = 'foundation:public_scene_context'
SCENE_CHOICES = {
    'residue': ('unknown', 'battlefield', 'fresh'),
}


@hook('prefight_setup_choices')
def public_scene_choices(bundle):
    """Record encounter adjudication through the existing fight-setup controls.

    These are public facts known to this creature, never an AI judgment from
    damage colours, team membership, or another creature's private information.
    Every default is unknown; recording facts neither grants Ash nor pays costs.
    """
    if not any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
               for row in bundle.get('typed_passives', ())):
        return None
    descriptions = {
        'residue': ('Funeral Ash: public battlefield residue',
            'For this creature\'s methods in this encounter, record only an established public fact: '
            '0 = unknown; 1 = the methods work through battlefield residue; '
            '2 = no battlefield residue is involved. Damage alone does not establish residue.'),
    }
    return [{'id': 'ash_public_' + key, 'kind': 'integer_range_list', 'count': 1,
             'label': descriptions[key][0], 'item_label': descriptions[key][0],
             'help': descriptions[key][1] + ' This record lasts for this encounter and costs no action or resource. '
                     'Leave it unknown if residue may vary or is private.',
             'minimum': 0, 'maximum': len(values) - 1, 'default': [0]}
            for key, values in SCENE_CHOICES.items()]


@hook('match_start')
def record_public_scene(engine):
    for bundle in getattr(engine, 'typed_bundle_documents', ()):
        if bundle.get('actor_id') not in engine.state.actors or not public_scene_choices(bundle):
            continue
        choices = (bundle.get('prefight') or {}).get('setup_choices') or {}
        facts = {}
        for key, values in SCENE_CHOICES.items():
            picked = choices.get('ash_public_' + key, [0])
            index = picked[0] if isinstance(picked, list) and len(picked) == 1 else 0
            facts[key] = values[index] if type(index) is int and 0 <= index < len(values) else 'unknown'
        if all(value == 'unknown' for value in facts.values()):
            continue
        engine._append_event('PASSIVE_TRIGGERED', SCENE_SOURCE, actor_id=bundle['actor_id'],
            payload={'fact_kind': 'foundation_public_scene', **facts,
                     'log': 'Funeral Ash: public encounter facts recorded at fight setup. '
                            'They cost no action or resource and do not grant Funeral Ash.'})


def public_scene_context(engine, owner):
    """Sealed, journaled setup facts known to this owner; absent facts are unknown.

    Consumers: adjudicated_event_context and Foundation conversion plug-ins.
    Only this actor's public declaration is consulted, never an enemy's bundle.
    """
    return next((dict(event.payload, setup_sequence=event.sequence)
                 for event in reversed(engine.events)
                 if event.source_definition_id == SCENE_SOURCE and event.actor_id == owner.entity_id
                 and event.payload.get('fact_kind') == 'foundation_public_scene'), {})


def unconscious_condition(condition_id):
    """Recognize native unconscious states in live and pre-damage queries."""
    return condition_id.rsplit('.', 1)[-1] in UNCONSCIOUS


@hook('choice_reactors')
def context_witnesses(engine):
    """Enroll potential human factual witnesses only in Ash-generator fights."""
    from ..tabletop_service import MANUAL_MODES
    if not any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
               for rows in getattr(engine, 'typed_passive_rows', {}).values() for row in rows):
        return ()
    return tuple(a.entity_id for a in engine.state.actors.values()
                 if conscious(a) and (getattr(engine, 'typed_control_modes', {}) or {}).get(
                     getattr(a, 'owner_id', None) or a.entity_id, 'MANUAL') in MANUAL_MODES)

# Exact individually reviewed records plus the printed Meridian sphere-method
# taxonomy. This classifies the ACTION'S source mechanic, never an actor's
# owned/affinity spheres or its damage type. Alignment still requires residue.
METHOD_SPHERES = {f'tianxia.sphere.{name}': name for name in
                  ('fire', 'ash', 'blood', 'yin', 'destruction', 'poison', 'disease', 'death')}
METHODS = {
    'FIRE_TAL_FLAME_LASH': ('fire', '4454ffffe87b5d131ed4e4aa9b3de2d44b06e9e017c941d4895e66362cf8b46a'),
    'FIRE_TAL_SCORCHING_RAY_ART': ('fire', '4c9ff973a4129976d79942d039993f0866af9d5455af7d856c097696854e172a'),
    'FIRE_TAL_FIREBALL_ART': ('fire', '755421b978db68dc9fb1bbdb2101ab98be8b9d65b5591461cd4aa41ecca29a15'),
    'DISEASE_BASE_SOW_THE_FEVER_SEED': ('disease', 'bad2b38124ecf015ee13a1e6651b52d784300b3509002487c74bc63aa430357e'),
    'BLOOD_BASE_COAGULATE': ('blood', '385ad19566e5c1b525399a1de91173ae27697173c9eecc7c1319856c811fb55d'),
}
METHOD_CATEGORIES = ('fire', 'ash', 'blood', 'yin', 'destruction', 'poison', 'disease', 'death',
                     'life_cautery', 'protection_sacrifice')


@hook('compile_passives')
def seal_meridian_ownership(rows, info):
    source = ASH + 'ash_returning_meridian'
    if source not in info['owned_ids']:
        return rows
    return [*rows, {'block': 'foundation_context_meridian', 'feature_id': source}]


@hook('damage_receipt_facts')
def ash_target_facts(engine, target, source_id, source_actor_id):
    if not any(any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
                   for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))
               for actor in engine.state.actors.values()):
        return None
    from ..senses import perceives
    observers = [actor.entity_id for actor in engine.state.actors.values()
                 if any(row.get('block') == 'generate' and 'foundations3_ash' in row.get('on', ())
                        for row in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ()))
                 and perceives(engine, actor, target)]
    return {'target_active_before': int(target.active), 'target_perceived_by': sorted(observers),
            'target_context_witnesses_before': sorted(aid for aid in context_witnesses(engine)
                if perceives(engine, engine.state.actors[aid], target)),
            'target_conditions_before': sorted(c.condition_id for c in target.conditions.values())}


@hook('compile_action')
def seal_source_method(action, info):
    typed = dict(action.parameters.get('typed') or {})
    source = typed.get('source')
    method = METHODS.get(source)
    mechanic = info['mechanics'].get(source) or {}
    source_hash = (mechanic.get('source') or {}).get('text_sha256')
    # Keep exact printed provenance available for source-grounded adjudication
    # of methods not yet individually reviewed in METHODS. No colour/name guess.
    if ASH + 'ash_returning_meridian' in info['owned_ids'] and (mechanic.get('source') or {}).get('text_sha256'):
        typed['foundation_source_provenance'] = dict(mechanic['source'])
        category = METHOD_SPHERES.get(mechanic.get('sphere_id'))
        if method is None and category:
            method = (category, source_hash)
    if method and (mechanic.get('source') or {}).get('text_sha256') == method[1]:
        typed['foundation_source_method'] = {
            'category': method[0], 'mechanic_id': source, 'text_sha256': method[1]}
    if typed != (action.parameters.get('typed') or {}):
        return action.model_copy(update={'parameters': {**action.parameters, 'typed': typed}})
    return action


def source_method_facts(engine, source_id):
    """Return sealed public method provenance, or None for an unknown source."""
    action = engine.action_catalog.get(source_id)
    return (action.parameters.get('typed') or {}).get('foundation_source_method') if action else None


def event_source_facts(engine, event):
    """Public action identity for a packet or its system-recorded defeat.

    Used by Foundation scene prompts. A defeat's defeating_source is the actual
    action; when a recorder has only a system source, the lethal packet in
    that same transaction supplies its actual source and actor. Unknown sources
    keep their identity and a neutral description.
    """
    source_id = (event.payload.get('defeating_source') if event.event_type == 'ENTITY_DEFEATED'
                 else None) or event.source_definition_id
    source_actor_id = event.actor_id
    if event.event_type == 'ENTITY_DEFEATED' and source_id not in engine.action_catalog:
        packet = next((receipt for receipt in reversed(engine.events)
                       if receipt.sequence < event.sequence
                       and receipt.transaction_id == event.transaction_id
                       and receipt.event_type == 'DAMAGE_COMMITTED'
                       and event.actor_id in receipt.target_ids
                       and int(receipt.payload.get('hp_before') or 0) > 0
                       and receipt.payload.get('remaining_hp') == 0), None)
        if packet is not None:
            source_id = packet.source_definition_id
            source_actor_id = packet.actor_id
    action = engine.action_catalog.get(source_id)
    return {'source_definition_id': source_id,
            'name': action.display_name if action else 'the resolved event',
            'actor_id': action.owner_id if action else source_actor_id}


def paid_source_facts(engine, event):
    """Public owned-source identity for an actual positive resource spend.

    Used by Ash Mercy. Action identity comes from the owner's compiled action;
    reaction/passive identity comes from that owner's compiled native row. An
    administrative drain, expiry or merely similarly named source is unknown.
    No resource or scene qualification is inferred by this identity query.
    """
    if event.event_type != 'RESOURCE_SPENT' or int(event.payload.get('amount') or 0) <= 0:
        return None
    actor = engine.state.actors.get(event.actor_id)
    if actor is None:
        return None
    action = engine.action_catalog.get(event.source_definition_id)
    if action and action.source_definition_id in actor.action_ids and action.owner_id == actor.entity_id:
        source = (action.parameters.get('typed') or {}).get('source')
        return {'mechanic_id': source, 'name': action.display_name} if source else None
    source = event.source_definition_id.removeprefix('passive:')
    rows = [*getattr(engine, 'typed_reaction_rows', {}).get(actor.entity_id, ()),
            *getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())]
    row = next((r for r in rows if r.get('feature_id') == source), None)
    if row is not None:
        return {'mechanic_id': source, 'name': row.get('name') or 'the Foundation use'}
    return None


def settled_execution_events(engine, first_sequence):
    """Receipts in this fully resolved accepted execution, including reactions.

    Call only from transaction_settled. No backwards scan across another accepted
    execution, and no persistent/transient packet cache requiring cold repair.
    """
    return tuple(e for e in engine.events if e.sequence > first_sequence)


def has_unconscious_condition(condition_ids):
    """Native unconsciousness query used by conscious owners and Mercy subjects."""
    return any(unconscious_condition(cid) for cid in condition_ids)


def conscious(actor):
    """Positive HP alone does not make a sleeping/unconscious owner conscious."""
    return (actor is not None and actor.active and actor.current_hp > 0
            and actor.life_state not in ('DYING', 'STABLE')
            and not has_unconscious_condition(c.condition_id for c in actor.conditions.values()))


def hostile_zero_drop(engine, observer, event):
    """Observed new zero-HP enemy receipt, irrespective of the damage source."""
    from ..relations import relation, ENEMY
    target = engine.state.actors.get(next(iter(event.target_ids), ''))
    return bool(event.event_type == 'DAMAGE_COMMITTED' and target
        and int(event.payload.get('hp_before') or 0) > 0 and event.payload.get('remaining_hp') == 0
        and relation(engine, observer, target) == ENEMY
        and observer.entity_id in event.payload.get('target_perceived_by', ()))


def ash_aligned(engine, owner, event, facts):
    """Public Meridian alignment query for generation/Strike/Garden.

    Exact-source method membership and attested battlefield residue are both
    required. Wounded means wounded BEFORE the packet, never a fresh target
    made eligible by that packet. Unknown/private facts do not qualify.
    Helplessness does not exclude a wounded enemy from alignment or generation.
    """
    method = source_method_facts(engine, event.source_definition_id)
    action = engine.action_catalog.get(event.source_definition_id)
    provenance = (action.parameters.get('typed') or {}).get('foundation_source_provenance') if action else None
    method = method or (provenance and facts.get('method_category') in METHOD_CATEGORIES)
    target = engine.state.actors.get(next(iter(event.target_ids), ''))
    owns = any(row.get('feature_id') == ASH + 'ash_returning_meridian'
               for row in engine.typed_passive_rows.get(owner.entity_id, ()))
    from ..relations import relation, ENEMY
    return bool(owns and method and facts.get('residue') == 'battlefield'
                and event.actor_id == owner.entity_id and target
                and relation(engine, owner, target) == ENEMY
                and 0 < int(event.payload.get('hp_before') or 0) < target.maximum_hp)


def observed_residue(engine, owner, target):
    """Public native residue for Garden/Meridian; unseen residue stays unknown.

    Ashen Brand is explicitly a visible residue mark; Ash Terrain is native
    battlefield residue. Only already-present residue qualifies: the current
    hit cannot supply its own pre-hit facts.
    """
    from ..senses import perceives
    from ..typed_executor import mark_condition_id
    if target is not None and perceives(engine, owner, target, sight_only=True):
        prefix = mark_condition_id('Ashen Brand', '')
        if any(c.condition_id.startswith(prefix) for c in target.conditions.values()):
            return 'battlefield'
        from ..zones import typed_zones
        from ..spatial_areas import zone_contains
        if any('ash terrain' in z.trigger_profile.get('terrain', ())
               and zone_contains(engine, target, z) for z in typed_zones(engine) if z.active):
            return 'battlefield'
    return 'unknown'


def public_event_context(engine, owner, event, intent, route):
    """Read only exact-event method/residue/category answers observed by this owner."""
    if intent is None:
        return {}
    for receipt in reversed(engine.events):
        p = receipt.payload or {}
        if (p.get('fact_kind') == 'foundation_event_context'
                and p.get('event_sequence') == event.sequence
                and p.get('intent_id') == intent.intent_id and p.get('route') == route
                and receipt.source_definition_id == event.source_definition_id
                and receipt.target_ids == event.target_ids
                and owner.entity_id in p.get('observer_ids', ())):
            return {k: p[k] for k in ('residue', 'damage_category', 'method_category') if k in p}
    return {}


def adjudicated_event_context(engine, owner, event, intent, *, route,
                              ability_name='Funeral Ash', feature_id=ASH + 'generate_funeral_ash',
                              damage_receipt=None):
    """Resolve mechanical facts, never whether an encounter or damage is real.

    Method, residue and non-colour damage-category questions retain native
    choice transport. Defeat/zero-HP receipts establish endings without a vote;
    ordinary stabilization still does not establish a cautery source.
    """
    receipt = damage_receipt if damage_receipt is not None else event
    source = event_source_facts(engine, receipt)
    source_id, action_name = source['source_definition_id'], source['name']
    action = engine.action_catalog.get(source_id)
    subject = engine.state.actors.get(next(iter(receipt.target_ids), event.actor_id))
    subject_name = subject.display_name if subject else 'the affected creature'
    from ..target_knowledge import located
    if subject is not None and subject is not owner and not located(engine, owner, subject):
        return {}
    from . import ai_controlled
    established = public_scene_context(engine, owner) if ai_controlled(engine, owner) else {}
    declarant = owner
    if ai_controlled(engine, owner):
        witnesses = set(receipt.payload.get('target_context_witnesses_before') or ())
        declarant = next((engine.state.actors[aid] for aid in sorted(witnesses)
                          if aid in context_witnesses(engine)), owner)
    base = dict(name=ability_name, feature_id=feature_id,
                target_id=subject.entity_id if subject else owner.entity_id,
                prompt_context={'action_name': action_name, 'source_definition_id': source_id,
                    'affected_id': subject.entity_id if subject else '', 'cost': 'No action or resource cost'})
    facts = public_event_context(engine, owner, event, intent, route)
    options, key = None, None
    if route == 'outgoing':
        typed = (action.parameters.get('typed') or {}) if action else {}
        if not source_method_facts(engine, source_id):
            if not typed.get('foundation_source_provenance'):
                return facts
            if facts.get('method_category') not in METHOD_CATEGORIES:
                labels = {k: k.replace('_', ' ').title() + ' method' for k in METHOD_CATEGORIES}
                labels.update(life_cautery='Life method working through cautery',
                              protection_sacrifice='Protection method working through sacrifice',
                              unknown='The printed source does not establish a qualifying method')
                selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_METHOD', event.sequence, owner.entity_id),
                    declarant, CONTEXT + '.method', list(labels), labels=labels, preferred=['unknown'],
                    automatic_options=['unknown'], allow_decline=True, default='decline',
                    prompt=f'{ability_name} after {action_name} affects {subject_name}: which Foundation method '
                        'does the printed source establish? ' + str(typed.get('gm_text') or ''), **base)
                facts['method_category'] = selected[0] if selected else 'unknown'
        facts.setdefault('residue', observed_residue(engine, owner, subject))
        if facts['residue'] == 'unknown' and established.get('residue'):
            facts['residue'] = established['residue']
        if facts['residue'] != 'battlefield':
            options = {'battlefield': 'This method worked through battlefield residue',
                       'fresh': 'No battlefield residue was involved', 'unknown': 'Residue is unknown'}
            key = 'residue'
    elif route == 'incoming':
        method = source_method_facts(engine, source_id) or {}
        kind = str(receipt.payload.get('damage_type') or '').lower()
        if method.get('category') == 'disease':
            facts['damage_category'] = 'disease'
        elif kind in ('fire', 'poison', 'necrotic'):
            facts['damage_category'] = kind
        elif 'damage_category' not in facts:
            options = {'attrition': 'Attrition damage', 'blood_loss': 'Blood-loss damage',
                       'other': 'Other damage, without established attrition', 'unknown': 'Damage context is unknown'}
            key = 'damage_category'
    elif route == 'zero_hp':
        facts['ending'] = 'zero_hp' if hostile_zero_drop(engine, owner, receipt) else 'unknown'
    else:
        facts['ending'] = ('mercy' if event.payload.get('nonlethal') else 'defeat') \
            if event.event_type == 'ENTITY_DEFEATED' else 'unknown'
    if options:
        selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACT_DETAIL', event.sequence, owner.entity_id),
            declarant, CONTEXT + '.detail', list(options), labels=options, preferred=['unknown'],
            automatic_options=['unknown'], allow_decline=True, default='decline',
            prompt=f'{ability_name} after {action_name} affects {subject_name}: confirm the '
                + ('observed residue.' if key == 'residue' else 'damage category.'), **base)
        facts[key] = selected[0] if selected else 'unknown'
    observers = set(receipt.payload.get('target_perceived_by') or ())
    observers.add(owner.entity_id)
    engine._append_event('PASSIVE_TRIGGERED', event.source_definition_id, actor_id=owner.entity_id,
        target_ids=event.target_ids,
        payload={'event_sequence': event.sequence, 'intent_id': intent.intent_id,
                 'fact_kind': 'foundation_event_context', 'route': route,
                 'declarant': declarant.entity_id, 'beneficiary': owner.entity_id,
                 'source_definition_id': source_id, 'observer_ids': sorted(observers),
                 **({'setup_sequence': established['setup_sequence']} if established else {}),
                 'log': f'{ability_name} facts after {action_name} affects {subject_name}. '
                        'Recording facts costs no action or resource.',
                 **facts})
    return facts
