"""Damage-pipeline consumers for the existing Foundation conversion owners.

Shared helper contracts: foundation_combat supplies ownership/payment and
foundation_resources supplies the reviewed affinity vocabulary. This module
owns Oath-Mark Strike and Verdant Mercy Bloom; Jade Furnace Release's numeric
damage/healing/temp-HP providers stay in foundation_combat, with represented
reduction/purification/stabilization scalars delivered here.
"""
from . import hook
from .foundation_combat import row, feature, pool, held, aligned, spend, values, choose, furnace_residue
from .choice_costs import Payment

MERCY_PENDING = 'foundation_mercy_pending'


def _method(engine, owner, source_id, group):
    action = engine.action_catalog.get(source_id)
    if action is not None and action.owner_id == owner.entity_id:
        typed = action.parameters.get('typed') or {}
        if aligned(typed, group):
            return True
    # Native reaction/passive methods carry compile-sealed authority, not a
    # runtime name or a caller-supplied sphere label.
    from ..support_values import method_of
    from .foundation_resources import affinity_spheres
    native = method_of(engine, owner, source_id)
    if native is None:
        return False
    method, authority = native
    from .foundation_combat import GROUPS
    return (authority.get('foundation_id') == GROUPS[group][0]
            or authority.get('sphere_id') in affinity_spheres(GROUPS[group][0]))


def _paid_technique(engine, owner, source_id):
    for event in reversed(engine.events):
        if event.event_type == 'INTENT_ACCEPTED' and event.actor_id == owner.entity_id:
            break
        if (event.event_type == 'RESOURCE_SPENT' and event.actor_id == owner.entity_id
                and event.source_definition_id == source_id
                and event.payload.get('resource_id') in {
                    'resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'}
                and int(event.payload.get('amount') or 0) > 0):
            return True
    return False


@hook('damage_value_adjustment')
def oath_strike(engine, target, amount, damage_type, source_id, source_actor_id, intent):
    owner = engine.state.actors.get(source_actor_id)
    if (owner is None or intent is None or amount <= 0 or owner.team_id == target.team_id
            or row(engine, owner, 'oath', 'oath_mark_strike') is None):
        return None
    protected = held(owner, 'protected_subject')
    subject = engine.state.actors.get(protected.data.get('subject')) if protected else None
    if subject is None or not subject.active:
        return None
    attack = engine.damage_context()
    action = engine.action_catalog.get(source_id)
    if not (attack is not None and attack.kind in {'weapon', 'unarmed'}
            or action is not None and aligned(action.parameters.get('typed') or {}, 'oath')):
        return None
    # An actual hostile attack/effect against the protected creature establishes
    # threat without a second flag, and survives a cold table replay.
    threatened = any(e.actor_id == target.entity_id and subject.entity_id in e.target_ids
        and e.event_type in {'ATTACK_ROLLED', 'DAMAGE_COMMITTED', 'CONDITION_APPLIED', 'INTENT_ACCEPTED'}
        for e in engine.events)
    if not threatened:
        return None
    pb = values(engine, owner)[0]
    if spend(engine, owner, 'oath', 'oath_mark_strike',
             f"Spend 1 Guarding Iron to add {pb} {damage_type.title()} damage to {target.display_name}",
             target):
        return pb
    return None


@hook('support_value_bonus')
def support_conversion(engine, proposal, *, consume):
    owner = engine.state.actors.get(proposal.actor_id)
    target = engine.state.actors.get(proposal.beneficiary_id)
    if owner is None or target is None or not owner.active or owner.current_hp <= 0:
        return None
    group = None
    if (proposal.kind in {'damage_reduction', 'purification', 'stabilization'}
            and row(engine, owner, 'furnace', 'jade_furnace_release') is not None
            and _method(engine, owner, proposal.source_id, 'furnace')
            and _paid_technique(engine, owner, proposal.source_id)):
        group, leaf = 'furnace', 'jade_furnace_release'
    elif (target is not owner and proposal.kind in {'healing', 'temporary_hp', 'damage_reduction'}
            and row(engine, owner, 'spring', 'verdant_mercy_bloom') is not None
            and _method(engine, owner, proposal.source_id, 'spring')):
        group, leaf = 'spring', 'verdant_mercy_bloom'
    if group is None:
        return None
    payment = Payment(pool(group), 1)
    if not payment.available(engine, owner):
        return None
    bonus = max(0, sum(values(engine, owner)))
    if not consume:
        return bonus
    name = 'Jade Furnace Release' if group == 'furnace' else 'Verdant Mercy Bloom'
    if not bonus or not choose(engine, owner, feature(group, leaf), name,
            f"Add {bonus} to this {proposal.kind.replace('_', ' ')} value for {target.display_name}; spend 1 "
            + ('Furnace Heat' if group == 'furnace' else 'Spring Dew'), target, payment=payment):
        return None
    payment.pay(engine, owner, feature(group, leaf))
    if group == 'furnace':
        furnace_residue(engine, owner, feature(group, leaf))
    else:
        owner.turn_flags[MERCY_PENDING] = {
            'source': proposal.source_id, 'target': target.entity_id, 'kind': proposal.kind}
    return bonus


def _settle_mercy(engine, owner, target, source_id, kind):
    pending = owner.turn_flags.get(MERCY_PENDING) or {}
    if pending != {'source': source_id, 'target': target.entity_id, 'kind': kind}:
        return
    owner.turn_flags.pop(MERCY_PENDING, None)
    from ..typed_executor import condition_rules
    from .life_state import stabilize
    if not any(r.get('stabilization_denied') or r.get('anti_life_wound')
               for r in condition_rules(target, engine=engine)):
        stabilize(engine, target, feature('spring', 'verdant_mercy_bloom'))


@hook('support_value_resolved')
def support_resolved(engine, proposal, selected, result):
    if proposal.kind != 'damage_reduction':
        return
    owner = engine.state.actors.get(proposal.actor_id)
    target = engine.state.actors.get(proposal.beneficiary_id)
    if owner is not None and target is not None:
        spent = bool(owner.turn_flags.get(MERCY_PENDING))
        _settle_mercy(engine, owner, target, proposal.source_id, proposal.kind)
        if result > 0 and not spent:
            _generate_dew(engine, owner, target, proposal.source_id)


@hook('event', nested=True)
def support_receipt(engine, event_type, kwargs):
    if event_type not in {'HEALING_APPLIED', 'TEMP_HP_GRANTED'}:
        return
    owner = engine.state.actors.get(kwargs.get('actor_id'))
    if owner is None:
        return
    kind = 'healing' if event_type == 'HEALING_APPLIED' else 'temporary_hp'
    for aid in kwargs.get('target_ids') or ():
        target = engine.state.actors.get(aid)
        if target is not None:
            spent = bool(owner.turn_flags.get(MERCY_PENDING))
            source_id = kwargs.get('source_definition_id')
            _settle_mercy(engine, owner, target, source_id, kind)
            payload = kwargs.get('payload') or {}
            if int(payload.get('after') or 0) > int(payload.get('before') or 0) and not spent:
                _generate_dew(engine, owner, target, source_id)


def _generate_dew(engine, owner, target, source_id):
    if owner is target or not owner.active or owner.current_hp <= 0:
        return
    from .iron_oath_generation import conscious_for_guarding_iron
    if not conscious_for_guarding_iron(engine, owner):
        return
    action = engine.action_catalog.get(source_id)
    flags = ((action.parameters.get('typed') or {}).get('support_source_flags') or ()) if action else ()
    if set(flags).intersection({'training', 'staged', 'harmless', 'self_inflicted'}):
        return
    from ..pressure import generate
    generate(engine, owner, 'spring_support')
