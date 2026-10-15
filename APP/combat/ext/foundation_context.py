"""Public Foundation source and settled-event context transport.

Consumers: Funeral Ash generation; Ash Strike/Garden/Mercy can use the same
public queries. Method membership is sealed from exact compiled source records,
not affinity spheres, action labels or damage colours. Scene judgments come from
the native table choice transport, are event-scoped and journaled, and remain
unknown when no person can attest them. An automatic seat cannot invent facts.
"""
from . import hook
from .needle import ask, checkpoint_id

ASH = 'foundation.red_lotus_ash_returning_v0_2B.'
CONTEXT = 'choice:needle.foundation_event_context'

# Exact individually reviewed records plus the printed Meridian sphere-method
# taxonomy. This classifies the ACTION'S source mechanic, never an actor's
# owned/affinity spheres or its damage type. Alignment still requires residue.
METHOD_SPHERES = {f'tianxia.sphere.{name}': name for name in
                  ('fire', 'ash', 'blood', 'yin', 'destruction', 'poison', 'disease', 'death')}
METHODS = {
    'FIRE_TAL_FLAME_LASH': ('fire', '4454ffffe87b5d131ed4e4aa9b3de2d44b06e9e017c941d4895e66362cf8b46a'),
    'FIRE_TAL_SCORCHING_RAY_ART': ('fire', 'cdeb76036c4457baf6a0858f0b31008e88b5656f264799c73815b4d61d8c1853'),
    'FIRE_TAL_FIREBALL_ART': ('fire', '3e09583d71bf13d8cb81045fd2b3f6834c1fe77be7a3ee931692b0f3530a6e75'),
    'DISEASE_BASE_SOW_THE_FEVER_SEED': ('disease', 'bad2b38124ecf015ee13a1e6651b52d784300b3509002487c74bc63aa430357e'),
    'BLOOD_BASE_COAGULATE': ('blood', '736c3a45e34fccf35d2ede00bdd85e741dc7205c85147108b2987e6128af0104'),
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


def settled_execution_events(engine, first_sequence):
    """Receipts in this fully resolved accepted execution, including reactions.

    Call only from transaction_settled. No backwards scan across another accepted
    execution, and no persistent/transient packet cache requiring cold repair.
    """
    return tuple(e for e in engine.events if e.sequence > first_sequence)


def conscious(actor):
    """Positive HP alone does not make a sleeping/unconscious owner conscious."""
    return (actor is not None and actor.active and actor.current_hp > 0
            and actor.life_state not in ('DYING', 'STABLE')
            and not any(c.condition_id.rsplit('.', 1)[-1] in ('unconscious', 'life_unconscious', 'asleep')
                        for c in actor.conditions.values()))


def helpless_before(event):
    """Mechanical helplessness at the event's start, not its defeat consequence."""
    payload = event.payload or {}
    return (int(payload.get('hp_before') or 0) <= 0
            or not payload.get('target_active_before', 1)
            or any(c.rsplit('.', 1)[-1] in ('unconscious', 'life_unconscious', 'asleep', 'paralyzed')
                   for c in payload.get('target_conditions_before') or ()))


def hostile_zero_drop(engine, observer, event):
    """Public zero-HP receipt qualification used by Garden's ending consumer.

    Require a new non-helpless hostile subject; a known friendly/self source
    cannot be turned into danger by testimony. Unknown environmental source
    circumstances remain for the explicit public context query to establish.
    """
    from ..relations import relation, ENEMY
    target = engine.state.actors.get(next(iter(event.target_ids), ''))
    source = engine.state.actors.get(event.actor_id)
    return bool(event.event_type == 'DAMAGE_COMMITTED' and target
        and int(event.payload.get('hp_before') or 0) > 0 and event.payload.get('remaining_hp') == 0
        and relation(engine, observer, target) == ENEMY and not helpless_before(event)
        and (source is None or relation(engine, source, target) == ENEMY))


def ash_aligned(engine, owner, event, facts):
    """Public Meridian alignment query for generation/Strike/Garden.

    Exact-source method membership and attested battlefield residue are both
    required. Wounded means wounded BEFORE the packet, never a fresh target
    made eligible by that packet. Unknown/private facts do not qualify.
    Generation callers must separately apply the printed generation exclusions;
    a wounded helpless target can still receive aligned Garden hit damage.
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
    """Read exact-event public testimony, never a prior attack's scene answer.

    Garden owners can share an attestation only if both observed that event.
    Primitive observer ids are journaled at declaration; reload and automatic
    seats consume the same receipt. Hidden/private facts are never imported.
    """
    if intent is None:
        return {}
    for receipt in reversed(engine.events):
        p = receipt.payload or {}
        if (p.get('fact_kind') == 'foundation_event_context'
                and p.get('event_sequence') == event.sequence
                and p.get('intent_id') == intent.intent_id and p.get('route') == route
                and receipt.source_definition_id == event.source_definition_id
                and receipt.target_ids == event.target_ids
                and owner.entity_id in p.get('observer_ids', ())
                and p.get('circumstances') != 'unknown'):
            return {k: p[k] for k in ('circumstances', 'residue', 'ending', 'damage_category', 'method_category') if k in p}
    return {}


def adjudicated_event_context(engine, owner, event, intent, *, route,
                              ability_name='Funeral Ash', feature_id=ASH + 'generate_funeral_ash'):
    """Get public event facts through actual native controller/table answers.

    Generation's first answer attests ALL listed exclusion boundaries. Another answer
    supplies a fact whose meaning is not inferable from HP/damage (residue,
    real attrition or an ending). Each receipt binds source, target, packet,
    execution and declarant. Automatic actors preserve unknown judgments.
    """
    action = engine.action_catalog.get(event.source_definition_id)
    action_name = action.display_name if action else 'the resolved event'
    subject = engine.state.actors.get(next(iter(event.target_ids), event.actor_id))
    subject_name = subject.display_name if subject else 'the affected creature'
    from ..target_knowledge import located
    if subject is not None and subject.entity_id != owner.entity_id and not located(engine, owner, subject):
        # A fact question must not publish private enemy identity/condition.
        return {'circumstances': 'unknown'}
    base = dict(name=ability_name, feature_id=feature_id,
                target_id=subject.entity_id if subject else owner.entity_id,
                prompt_context={'action_name': action_name, 'source_definition_id': event.source_definition_id,
                    'affected_id': subject.entity_id if subject else '', 'cost': 'No action or resource cost'})
    if route == 'ending' and event.event_type == 'LIFE_STATE_CHANGED':
        # Stabilization establishes neither cautery nor a general exception to
        # the printed helpless-target exclusion. The owner ruling and a genuine
        # source-qualified treatment/ending producer are still required.
        return {'circumstances': 'unknown', 'ending': 'unknown'}
    facts = public_event_context(engine, owner, event, intent, route)
    if route == 'outgoing':
        # Alignment has no generation-only danger/helplessness exclusion.
        # Known native residue needs no testimony, even for automatic owners.
        facts.setdefault('residue', observed_residue(engine, owner, subject))
        if (not source_method_facts(engine, event.source_definition_id)
                and facts.get('method_category') not in METHOD_CATEGORIES):
            typed = (action.parameters.get('typed') or {}) if action else {}
            if not typed.get('foundation_source_provenance'):
                return facts
            labels = {k: k.replace('_', ' ').title() + ' method' for k in METHOD_CATEGORIES}
            labels.update(life_cautery='Life method working through cautery',
                          protection_sacrifice='Protection method working through sacrifice',
                          unknown='The printed source does not establish a qualifying method')
            selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_METHOD', event.sequence, owner.entity_id),
                owner, CONTEXT + '.method', list(labels), labels=labels, preferred=['unknown'],
                automatic_options=['unknown'], allow_decline=True, default='decline',
                prompt=f'{ability_name} after {action_name} affects {subject_name}: which Foundation method '
                    'does the printed source establish? ' + str(typed.get('gm_text') or ''), **base)
            facts['method_category'] = selected[0] if selected else 'unknown'
        if facts['residue'] != 'battlefield':
            options = {'battlefield': 'This method worked through battlefield residue',
                       'fresh': 'No battlefield residue was involved', 'unknown': 'Residue is unknown'}
            selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACT_DETAIL', event.sequence, owner.entity_id),
                owner, CONTEXT + '.detail', list(options), labels=options, preferred=['unknown'],
                automatic_options=['unknown'], allow_decline=True, default='decline',
                prompt=f'{ability_name} after {action_name} affects {subject_name}: confirm the observed residue.', **base)
            facts['residue'] = selected[0] if selected else 'unknown'
        return facts
    if facts:
        return facts
    labels = {
        'real': 'Real hostile danger: not staged, harmless, voluntary, training, or a helpless-target event',
        'staged': 'Staged event', 'harmless': 'Harmless event', 'voluntary': 'Voluntary harm',
        'training': 'Training event', 'helpless': 'Helpless-target event', 'unknown': 'Circumstances are unknown',
    }
    chosen = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACTS', event.sequence, owner.entity_id),
        owner, CONTEXT, list(labels), labels=labels, preferred=['unknown'], allow_decline=True,
        automatic_options=['unknown'], default='decline',
        prompt=f'{ability_name} after {action_name} affects {subject_name}: which circumstances are established?', **base)
    facts = {'circumstances': chosen[0] if chosen else 'unknown'}
    if facts['circumstances'] == 'real':
        if route == 'incoming':
            # Fire/poison/necrotic and explicitly reviewed Disease are mechanically
            # known. Other ordinary damage needs an actual attrition judgment.
            method = source_method_facts(engine, event.source_definition_id) or {}
            kind = str(event.payload.get('damage_type') or '').lower()
            if method.get('category') == 'disease':
                facts['damage_category'] = 'disease'
                options = None
            elif kind in ('fire', 'poison', 'necrotic'):
                facts['damage_category'] = kind
                options = None
            else:
                options = {'attrition': 'Actual hostile attrition damage',
                           'blood_loss': 'Actual hostile blood-loss damage',
                           'other': 'Other damage, without established attrition', 'unknown': 'Damage context is unknown'}
            key = 'damage_category'
        elif route == 'zero_hp':
            # The native receipt establishes the new drop. Garden's explicit
            # zero-HP alternative does not require inventing a later defeat.
            facts['ending'] = ('zero_hp' if event.event_type == 'DAMAGE_COMMITTED'
                and int(event.payload.get('hp_before') or 0) > 0
                and event.payload.get('remaining_hp') == 0 else 'unknown')
            options = None
            key = 'ending'
        else:
            options = {'defeat': 'A meaningful enemy defeat resolved under real danger',
                       **({'mercy': 'The defeated enemy was genuinely spared under real danger'}
                          if event.payload.get('nonlethal') else {})}
            options['unknown'] = 'No meaningful ending is established'
            key = 'ending'
        if options:
            selected = ask(engine, intent, checkpoint_id(engine, 'FOUNDATION_FACT_DETAIL', event.sequence, owner.entity_id),
                owner, CONTEXT + '.detail', list(options), labels=options, preferred=['unknown'],
                automatic_options=['unknown'], allow_decline=True, default='decline',
                prompt=f'{ability_name} after {action_name} affects {subject_name}: confirm the observed {key.replace("_", " ")}.', **base)
            facts[key] = selected[0] if selected else 'unknown'
    from ..senses import perceives
    observers = event.payload.get('target_perceived_by')
    if observers is None:
        observers = [a.entity_id for a in engine.state.actors.values()
                     if subject is not None and perceives(engine, a, subject)]
    engine._append_event('PASSIVE_TRIGGERED', event.source_definition_id,
        actor_id=owner.entity_id, target_ids=event.target_ids,
        payload={'event_sequence': event.sequence, 'intent_id': intent.intent_id,
                 'fact_kind': 'foundation_event_context',
                 'route': route, 'declarant': owner.entity_id, 'observer_ids': sorted(observers), **facts})
    return facts
