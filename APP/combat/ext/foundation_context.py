"""Shared public Foundation method and settled-event facts.

Used by foundations3.py, ash_garden.py and foundation_mercy.py. Exact compiled
source records identify methods; damage and residue facts come from the
engine and from public scene context recorded at setup.
"""
from . import hook
from .damage_delivery import AREA, LASTING, recurring_hazard

ASH = 'foundation.red_lotus_ash_returning_v0_2B.'
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

    Consumers: event_facts and Foundation conversion plug-ins.
    Only this actor's public declaration is consulted, never an enemy's bundle.
    """
    return next((dict(event.payload, setup_sequence=event.sequence)
                 for event in reversed(engine.events)
                 if event.source_definition_id == SCENE_SOURCE and event.actor_id == owner.entity_id
                 and event.payload.get('fact_kind') == 'foundation_public_scene'), {})


def unconscious_condition(condition_id):
    """Recognize native unconscious states in live and pre-damage queries."""
    return condition_id.rsplit('.', 1)[-1] in UNCONSCIOUS


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
LISTED_DAMAGE_CATEGORIES = frozenset(('fire', 'poison', 'necrotic', 'disease', 'blood_loss', 'attrition'))


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
    hazard = recurring_hazard(engine, source_id)
    return {'target_active_before': int(target.active), 'target_perceived_by': sorted(observers),
            'target_conditions_before': sorted(c.condition_id for c in target.conditions.values()),
            **({'delivery_hazard': hazard} if hazard else {})}


@hook('compile_action')
def seal_source_method(action, info):
    typed = dict(action.parameters.get('typed') or {})
    source = typed.get('source')
    method = METHODS.get(source)
    mechanic = info['mechanics'].get(source) or {}
    source_hash = (mechanic.get('source') or {}).get('text_sha256')
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


def ash_aligned(engine, owner, event):
    """Public Meridian alignment query for generation/Strike/Garden.

    Exact-source method membership and attested battlefield residue are both
    required. Wounded means wounded BEFORE the packet, never a fresh target
    made eligible by that packet. Unknown/private facts do not qualify.
    Helplessness does not exclude a wounded enemy from alignment or generation.
    """
    target = engine.state.actors.get(next(iter(event.target_ids), ''))
    owns = any(row.get('feature_id') == ASH + 'ash_returning_meridian'
               for row in engine.typed_passive_rows.get(owner.entity_id, ()))
    from ..relations import relation, ENEMY
    from ..target_knowledge import located
    if not (owns and event.actor_id == owner.entity_id and target
            and relation(engine, owner, target) == ENEMY and located(engine, owner, target)
            and 0 < int(event.payload.get('hp_before') or 0) < target.maximum_hp):
        return False
    facts = event_facts(engine, event.source_definition_id, owner=owner, target=target,
                        prior_conditions=event.payload.get('target_conditions_before'))
    return bool(facts['method_category'] and facts['residue'] == 'battlefield')


def observed_residue(engine, owner, target, *, prior_conditions=None):
    """Public native residue for Garden/Meridian; unseen residue stays unknown.

    Ashen Brand is explicitly a visible residue mark; Ash Terrain is native
    battlefield residue. Only already-present residue qualifies: the current
    hit cannot supply its own pre-hit facts.
    """
    from ..senses import perceives
    from ..typed_executor import mark_condition_id
    if target is not None and perceives(engine, owner, target, sight_only=True):
        prefix = mark_condition_id('Ashen Brand', '')
        condition_ids = (prior_conditions if prior_conditions is not None
                         else (c.condition_id for c in target.conditions.values()))
        if any(cid.startswith(prefix) for cid in condition_ids):
            return 'battlefield'
        from ..zones import typed_zones
        from ..spatial_areas import zone_contains
        if any('ash terrain' in z.trigger_profile.get('terrain', ())
               and zone_contains(engine, target, z) for z in typed_zones(engine) if z.active):
            return 'battlefield'
    return 'unknown'


def event_facts(engine, source_id, *, damage_type=None, delivery_hazard='', owner=None, target=None,
                prior_conditions=None):
    """Resolve typed facts shared by Ash generation, Cautery and Garden.

    Incoming uses the pending or committed packet's damage type and delivery class.
    The outgoing trigger requires a qualifying source method and public residue;
    damage type alone never establishes method alignment.
    """
    action = engine.action_catalog.get(source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    method = ((source_method_facts(engine, source_id) or {}).get('category')
              or METHOD_SPHERES.get(typed.get('sphere')))
    facts = {'method_category': method}
    if damage_type is not None:
        kind = str(damage_type).lower()
        facts['damage_category'] = ('disease' if method == 'disease'
                                    else kind if kind in ('fire', 'poison', 'necrotic')
                                    else 'blood_loss' if method == 'blood'
                                    else 'attrition' if delivery_hazard in (LASTING, AREA)
                                    else 'other')
    if owner is not None:
        residue = observed_residue(engine, owner, target, prior_conditions=prior_conditions)
        if residue != 'battlefield':
            residue = public_scene_context(engine, owner).get('residue', residue)
        facts['residue'] = residue
    return facts


def event_ending(engine, owner, event, damage_receipt=None):
    """Recognize established zero-HP, defeat and mercy receipts, never ordinary stabilization."""
    from ..target_knowledge import located
    receipt = damage_receipt if damage_receipt is not None else event
    subject = engine.state.actors.get(next(iter(receipt.target_ids), event.actor_id))
    if subject is not None and subject is not owner and not located(engine, owner, subject):
        return None
    if event.event_type == 'ENTITY_DEFEATED':
        return 'mercy' if event.payload.get('nonlethal') else 'defeat'
    if hostile_zero_drop(engine, owner, event):
        return 'zero_hp'
    return None
