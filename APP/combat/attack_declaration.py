"""Attack declaration checkpoint shared by typed, fixture and C3 attacks."""
from . import ext


def intercepted(engine, actor, target, source, intent, index=1, *, spec):
    """Resolve a declared strike's noncreature interception once, before d20.

    The transient spec carries the causal receipt across typed/native layers.
    The provider owns evented recipient lifecycle, not attack economy. An
    intercepted strike targets that recipient successfully without rolling
    against or applying any attack/on-hit effects to the original creature.
    Receipts may name physical objects or nonphysical map markers. Providers
    may already have destroyed the recipient; its stored record must remain.
    """
    # Free triggers (such as reactions and zone strikes) may have no in-flight intent.
    intent_id = str(getattr(intent, "intent_id", "") or "")
    key = (actor.entity_id, target.entity_id, source, intent_id, index)
    prior = spec.get("target_interception")
    if prior is not None and prior["key"] == key:
        return bool(prior["receipt"])
    answers = ext.run_checkpoint("attack_target_interception", engine, actor, target, source, intent, index)
    if len(answers) > 1:
        raise ext.CheckpointError("one provider must own attack target interception")
    receipt = answers[0] if answers else None
    if receipt is not None:
        if (not isinstance(receipt, dict) or any(not isinstance(receipt.get(k), str) or not receipt[k]
                for k in ("source_id", "recipient_object_id", "condition_instance_id"))
                or (receipt["recipient_object_id"] not in engine.state.objects
                    and receipt["recipient_object_id"] not in engine.state.map_images)):
            raise ext.CheckpointError("attack target interception requires a sourced object receipt")
        engine._append_event("PASSIVE_TRIGGERED", receipt["source_id"], actor_id=actor.entity_id,
            target_ids=(receipt["recipient_object_id"],), payload={**receipt,
                "kind": "attack_target_intercepted",
                "original_target_id": target.entity_id, "attack_source_id": source,
                "intent_id": intent_id, "attack_index": index})
    spec["target_interception"] = {"key": key, "receipt": receipt}
    return receipt is not None


def can_target(engine, actor, target, source_id, *, action=None, typed=None, effect=None, index=1, typed_profile=None, range_ft=None):
    """Voluntary attack-recipient query for Challenge and reaction consumers.

    Supply the actual typed profile for generic reactions; the catalog entry may
    only describe their activation. The transient attack copy never changes the
    catalog or profile. Forced redirection retains its separate existing rules.
    """
    from copy import deepcopy
    from .gate2_runtime_models import ActionDefinition, EconomyKind
    from .recipients import allowed

    if typed_profile is not None and (type(range_ft) is not int or range_ft < 0):
        raise ValueError('a typed attack recipient query requires its actual range')
    action = action if action is not None else engine.action_catalog.get(source_id)
    if action is None:
        if typed_profile is None:
            return False
        action = ActionDefinition(source_definition_id=source_id, display_name='Reaction attack',
            owner_id=actor.entity_id, economy=EconomyKind.REACTION, resolution_kind='TYPED', target_kind='HOSTILE_ENTITY')
    if typed is not None:
        action = action.model_copy(deep=True, update={'parameters': {**deepcopy(action.parameters), 'typed': deepcopy(typed)}})
    actual_typed = typed_profile if typed_profile is not None else action.parameters.get('typed') or {}
    effect = effect or {}
    if range_ft is None:
        if actual_typed.get('reaction_attack'):
            from .typed_reactions import attack_reaches
            if not attack_reaches(engine, actor, target, effect, actual_typed.get('reaction_range_ft')):
                return False
        else:
            reach = action.range_ft if action.range_ft is not None else action.reach_ft
            if reach is not None:
                range_ft = max(int(reach), int(actual_typed.get('range_ft') or 0), int(actual_typed.get('long_range_ft') or 0))
        if index > 1 and effect.get('later_reach_ft') is not None:
            range_ft = int(effect['later_reach_ft'])
    if typed_profile is not None:
        # The attack payload, not the reaction activation's SELF/ALLY descriptor.
        action = action.model_copy(deep=True, update={'target_kind': 'HOSTILE_ENTITY', 'resolution_kind': 'TYPED',
            'parameters': {**deepcopy(action.parameters), 'typed': deepcopy(typed_profile)}})
    if range_ft is not None:
        action = action.model_copy(update={'range_ft': range_ft, 'reach_ft': None})
    if not allowed(engine, actor, target, action):
        return False
    from .gate2_runtime_models import CandidateKind
    kind = {EconomyKind.ACTION: CandidateKind.ACTION, EconomyKind.REACTION: CandidateKind.REACTION}.get(action.economy, CandidateKind.BONUS_ACTION)
    candidate = engine._candidate(kind, actor, source_id, action.display_name, target_ids=(target.entity_id,))
    return not ext.any_false('candidate_allowed', engine, actor, candidate, action)


def declare(engine, actor, target, source, intent, index=1, *, range_ft=None, context=None):
    if not ext.has("retarget_attack"):
        return target, 0
    trigger = {**(context or {}), "actor_id": actor.entity_id, "target_id": target.entity_id,
               "source_id": source, "attack_index": index, "range_ft": range_ft}
    # Typed callers supply their future resolver spec explicitly. Native callers
    # own a declaration scratch frame bounded by the existing roll_context_end.
    if "attack_spec" not in trigger:
        from .ext.attack_defenses import declaration_spec

        trigger["attack_spec"] = declaration_spec(engine, actor, source, index)
    answers = ext.run_strict("retarget_attack", engine, actor, target, intent, trigger)
    if not answers:
        return target, 0
    if len(answers) != 1 or not isinstance(answers[0], dict):
        raise ValueError("one plugin must own attack redirection")
    answer = answers[0]
    redirected = engine.state.actors.get(answer.get("target_id"))
    cover = answer.get("cover_bonus", 0)
    if not isinstance(answer.get("source_id"), str) or not answer["source_id"]:
        raise ValueError("redirection requires a source_id")
    if (redirected is None or not redirected.active or redirected.entity_id == actor.entity_id
            or not engine._line_of_sight_actor_to_actor(actor, redirected)
            or (range_ft is not None and engine._effect_distance(actor, redirected) > range_ft)):
        raise ValueError("illegal redirected attack target")
    if type(cover) is not int or cover not in {0, 2, 5}:
        raise ValueError("redirection cover must be 0, 2 or 5")
    engine._append_event("ATTACK_RETARGETED", answer["source_id"], actor_id=actor.entity_id,
        target_ids=(redirected.entity_id,), payload={"original_target_id": target.entity_id,
            "attack_source_id": source, "attack_index": index, "cover_bonus": cover})
    return redirected, cover


from contextlib import contextmanager


def current_pending(engine):
    """Native committed pre-roll declaration, or None outside that window.

    Read-only public metadata: attacker/target IDs, action name, bonus and reach.
    The reaction executor separately receives the actual triggering_attack_spec.
    Nested attacks shadow and restore this declaration; no caller may manufacture
    an eligibility/payment receipt from this query.
    """
    from types import MappingProxyType
    value=getattr(engine,'_typed_pending_attack',None)
    return MappingProxyType(value) if value is not None else None


@contextmanager
def pending_attack(engine,record):
    """Scope one native declaration without erasing an enclosing attack."""
    from .paid_relocation import preserve_pending
    preserve_pending(engine,'_typed_pending_attack')
    previous=getattr(engine,'_typed_pending_attack',None)
    engine._typed_pending_attack=record
    try:yield
    finally:engine._typed_pending_attack=previous


def ordinary_attack_action(engine, actor, action, typed):
    """Actual root Attack-action provenance; no attack is granted by this query."""
    from .gate2_runtime_models import EconomyKind
    from .ext.attack_scope import current
    if (action is None or typed.get('granted_attack') or typed.get('reaction_attack') or typed.get('opportunity_of')
            or action.economy != EconomyKind.ACTION
            or current(engine) is not None or current_pending(engine) is not None):
        return False
    weapon=typed.get('weapon') or {}
    return (action.resolution_kind in ('ATTACK','MULTI_ATTACK') or
            bool(weapon.get('implement_id') and typed.get('source') == weapon['implement_id']) or
            bool(typed.get('unarmed_option')) or typed.get('attack_action') is True or typed.get('source') == 'unarmed_strike')


def native_reactions(engine, actor, target, source, intent, spec, index=1):
    """Opt-in native pre-roll generic reactions; absent providers do nothing.

    Providers return nonempty feature-ID lists for their own acquired reactions.
    The existing generic dispatcher owns consent, payment and reaction limits.
    The supplied mutable spec is the one the native resolver will roll.
    """
    from .ext.attack_scope import current
    if current(engine) is not None or spec is None:return False
    ids=native_reaction_ids(engine,actor,target,source,spec)
    if not ids:return False
    from .typed_reactions import on_attacked
    before=len(engine.events)
    declaration={'attacker':actor.entity_id,'target':target.entity_id,
        'action_name':spec.get('action_name') or source,'bonus':int(spec.get('attack_bonus') or 0),
        'reach':int(spec.get('reach_ft') or spec.get('range_ft') or 5),
        'granted_attack':int(is_granted_attack(engine,actor,engine.action_catalog.get(source),spec.get('typed') or {},source=source))}
    with pending_attack(engine,declaration):
        on_attacked(engine,actor,target,spec,intent,accept=lambda row:row.get('feature_id') in ids)
    reacted=any(e.event_type=='REACTION_RESOLVED' for e in engine.events[before:])
    if reacted:
        from .technique_interception import require_attack_geometry_recheck
        require_attack_geometry_recheck(engine,actor.entity_id,source)
    return reacted


def native_reaction_ids(engine,actor,target,source,spec):
    """Validated opt-in reaction rows for a real native declaration."""
    answers=ext.run_strict('native_attack_reactions',engine,actor,target,source,spec)
    ids=set()
    for answer in answers:
        if not isinstance(answer,list) or any(not isinstance(v,str) or not v for v in answer):
            raise ValueError('native_attack_reactions requires feature-ID lists')
        ids.update(answer)
    return ids


def is_granted_attack(engine,actor,action,typed,*,source=None):
    """Positive native grant provenance; an unknown legacy profile is inert.

    False ordinary provenance is not evidence that an attack was granted.
    Explicit granted/reaction roots, accepted native reaction scopes, and the
    actual sealed action's non-Attack profile/economy supply that evidence.
    """
    if typed.get('granted_attack') or typed.get('reaction_attack') or typed.get('opportunity_of'):return True
    from .native_reactions import context
    actual_source=source or (action.source_definition_id if action is not None else '')
    if context(engine,actor.entity_id,actual_source) is not None:return True
    if action is None:return False
    from .gate2_runtime_models import EconomyKind
    if action.resolution_kind in ('ATTACK','MULTI_ATTACK'):
        return action.economy!=EconomyKind.ACTION
    sealed=action.parameters.get('typed') or {}
    if not sealed or not typed.get('source') or sealed.get('source')!=typed.get('source'):return False
    def contains_attack(value):
        if isinstance(value,dict):return value.get('type')=='attack' or any(contains_attack(v) for v in value.values())
        if isinstance(value,list):return any(contains_attack(v) for v in value)
        return False
    if not contains_attack(typed.get('effects')) or not contains_attack(sealed.get('effects')):return False
    return not ordinary_attack_action(engine,actor,action,typed)
