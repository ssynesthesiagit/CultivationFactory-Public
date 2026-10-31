"""Source-bound scalar transport for support effects.

Native HP grants, typed reaction reductions and Water Shield use this public
interface. Producers supply the actual provider, beneficiary and method, before
their ordinary caps. Policy remains in plug-ins; absent providers return the
original signed value. A settled value is transactional, never a preview fact.
"""
from dataclasses import dataclass
from functools import lru_cache
import json


@dataclass(frozen=True)
class SupportValue:
    actor_id: str
    beneficiary_id: str
    source_id: str
    kind: str
    value: int
    value_id: str = ''


@dataclass(frozen=True)
class SupportRollSource:
    """An actual held roll benefit, published by its owning plug-in.

    Shared by Returning Source Guard and Foundation scalar support. This is
    transient provenance, not a new condition or a persisted allowance.
    """
    actor_id: str
    source_id: str
    purpose: str


def roll_sources(engine, subject, context):
    """Read scoped grants without consuming, prompting or inventing purpose."""
    from . import ext
    sources = []
    for reply in ext.run_strict('support_roll_sources', engine, subject, context):
        if not isinstance(reply, (list, tuple)) or any(
                not isinstance(row, SupportRollSource) or not row.actor_id
                or not row.source_id or row.purpose not in {
                    'concentration', 'rhythm', 'backlash', 'drain', 'fear',
                    'curse_pressure', 'spiritual_exhaustion', 'stabilization'}
                for row in reply):
            raise ValueError('Support roll sources require native provider, method and purpose')
        sources.extend(reply)
    return list(dict.fromkeys(sources))


@lru_cache(maxsize=1)
def method_catalog():
    """Read the shipped authority, shared by source-aware support providers."""
    from .factory_compiler import TYPED_AUTHORITY
    return json.loads(TYPED_AUTHORITY.read_bytes())['mechanics']


def method_of(engine, actor, source_id):
    """Resolve an owned native action or passive to its authoritative method.

    A free-form sphere label does not establish method provenance. Passive and
    triggered callers may use their actual feature id; actions must belong to
    this actor's accepted compiled action catalogue.
    """
    from .alternative_payments import owned
    action = engine.action_catalog.get(source_id)
    if action is not None:
        if action.owner_id != actor.entity_id or source_id not in actor.action_ids:
            return None
        method = str((action.parameters.get('typed') or {}).get('source') or '').split('#')[0]
    else:
        method = str(source_id).split('#')[0]
    row = (action.parameters.get('typed') or {}).get('support_method') if action is not None else None
    if action is None:
        for field in ('typed_passive_rows', 'typed_reaction_rows'):
            row = next((r.get('support_method') for r in getattr(engine, field, {}).get(actor.entity_id, ())
                        if r.get('feature_id') == method and r.get('support_method')), row)
    # Runtime labels cannot manufacture source membership. The production
    # compile hooks seal source facts before the accepted bundle hash is made.
    if row is None or not owned(engine, actor, source_id if action else method):
        return None
    return method, row


def source_snapshot(method):
    """Primitive provenance sealed by compile hooks, consumed by method_of."""
    row = method_catalog().get(method)
    if row is None:
        return None
    return {key: row.get(key) for key in ('name', 'sphere_id', 'foundation_id', 'source')}


def resolve_save_bonus(engine, actor, beneficiary, source_id, purpose, value=0):
    """Select one source-owned contribution to the actual recipient save."""
    selected = value + offered_bonus(engine, actor, beneficiary, source_id, purpose, value, consume=True)
    settled(engine, actor, beneficiary, source_id, purpose, value, selected, selected)
    return selected


def offered_bonus(engine, actor, beneficiary, source_id, kind, value, *, consume, value_id=''):
    """Strict scalar additions. A signed base is never clamped before selection."""
    from . import ext
    if type(value) is not int:
        raise ValueError('Support values must be integers')
    proposal = SupportValue(actor.entity_id, beneficiary.entity_id, str(source_id), kind, value, str(value_id))
    replies = ext.run_checkpoint('support_value_bonus', engine, proposal, consume=consume)
    if any(type(reply) is not int or reply < 0 for reply in replies):
        raise ext.CheckpointError('Support value bonuses must be nonnegative integers')
    return sum(replies)


def settled(engine, actor, beneficiary, source_id, kind, original, selected, result, *, value_id=''):
    """Publish final native consumption after ordinary caps, within its transaction."""
    if any(type(value) is not int for value in (original, selected, result)):
        raise ValueError('Support value results must be integers')
    from . import ext
    proposal = SupportValue(actor.entity_id, beneficiary.entity_id, str(source_id), kind, original, str(value_id))
    ext.run_strict('support_value_resolved', engine, proposal, selected, result)


def resolve_reduction(engine, actor, beneficiary, source_id, value, pending, *, value_id=''):
    """Resolve one rolled/flat reduction and its actual capped damage prevention."""
    selected = value + offered_bonus(engine, actor, beneficiary, source_id,
                                     'damage_reduction', value, consume=True, value_id=value_id)
    result = min(pending, max(0, selected))
    settled(engine, actor, beneficiary, source_id, 'damage_reduction', value, selected, result, value_id=value_id)
    return max(0, selected)


def reduction_terms(engine, actor, beneficiary, source_id, portions):
    """Pure opt-in folding of one reduction's signed printed arithmetic.

    The generic reaction producer supplies already drawn terms. A provider
    can request signed arithmetic before the final floor without changing
    unowned reactions. Equal damage-type filters identify one native scalar.
    """
    from . import ext
    replies = ext.run_strict('support_value_sign', engine,
        SupportValue(actor.entity_id, beneficiary.entity_id, source_id, 'damage_reduction', 0))
    if any(type(reply) is not bool for reply in replies):
        raise ValueError('Support value sign policy must be boolean')
    if not any(replies):
        return None
    groups = {}
    for value, types in portions:
        groups[types] = groups.get(types, 0) + value
    return [(value, types) for types, value in groups.items()]


def committed_reduction(engine, actor, beneficiary, source_id, pending, reduced, portions, damage_type):
    """Select once after native consent/payment, without redrawing query dice.

    Update the caller's ordinary carry budget with the selected value. Only
    currently applicable filters offer a scalar; the remaining parts retain
    their source-owned future packet semantics.
    """
    before = sum(max(0, value) for value, types in portions if not types or damage_type in types)
    selected = []
    for index, (value, types) in enumerate(portions):
        if not types or damage_type in types:
            value = resolve_reduction(engine, actor, beneficiary, source_id, value, pending,
                                      value_id=f'part:{index}')
        selected.append((value, types))
    after = sum(max(0, value) for value, types in selected if not types or damage_type in types)
    portions[:] = selected
    return max(0, reduced - (after - before))


def condition_purpose(condition):
    """Read represented consequences for native suppression/check consumers.

    Unknown causes remain unknown. Names are condition identities and sealed
    origin-save category tags, never ability labels or affinity guesses.
    """
    name = str(getattr(condition, 'condition_id', '')).removeprefix('condition:typed.')
    data = getattr(condition, 'data', None) or {}
    tags = {name, *map(str, (data.get('origin_save') or {}).get('named') or ()),
            *map(str, (data.get('repeat_save') or {}).get('named') or ())}
    tags.update(tag.removeprefix('category:') for tag in tuple(tags))
    scopes = (
        ('concentration', {'concentration_mode', 'concentration'}),
        ('rhythm', {'technique_rhythm', 'rhythm'}),
        ('backlash', {'turbulent', 'backlash', 'qi_backlash', 'qi_deviation'}),
        ('drain', {'drain', 'life_drain', 'necrotic_drain', 'spiritual_drain'}),
        ('fear', {'frightened', 'fear', 'fear_darkness', 'fear_death', 'fear_cold'}),
        ('curse_pressure', {'curse', 'cursed', 'curse_pressure'}),
        ('spiritual_exhaustion', {'spiritual_exhaustion', 'spiritual_depletion'}),
    )
    return next((kind for kind, names in scopes if tags & names), None)


def condition_purpose_from(engine, actor, beneficiary, source_id, condition):
    """Resolve represented or table-attested consequence of one selected harm.

    The native end_effect check is the production caller. Optional subscribers
    can ask for an unknown scene fact through the normal controller; returning
    None preserves unknown facts. The represented condition and accepted source
    are passed intact, rather than assigning a category by ability name.
    """
    known = condition_purpose(condition)
    if known is not None:
        return known
    from . import ext
    answers = ext.run_checkpoint('support_condition_purpose', engine, actor,
                                 beneficiary, source_id, condition)
    kinds = {'concentration', 'rhythm', 'backlash', 'drain', 'fear',
             'curse_pressure', 'spiritual_exhaustion', 'stabilization'}
    if len(answers) > 1 or any(answer not in kinds for answer in answers):
        raise ext.CheckpointError('One support condition provider may name an actual consequence')
    return answers[0] if answers else None


def healing_offer(engine, beneficiary, source_id, actor_id, value):
    """Shared signed healing offer; native and explicit restoration callers.

    Native restrictions still own denial and interception. A previously chosen
    scalar is reserved in the enclosing transaction, so a caller that already
    ran stored reductions cannot add it again at the HP commit boundary.
    """
    actor = engine.state.actors.get(actor_id)
    from .typed_executor import healing_denied
    if (actor is None or beneficiary.current_hp >= beneficiary.maximum_hp
            or healing_denied(beneficiary)):
        return value
    return value + offered_bonus(engine, actor, beneficiary, source_id, 'healing', value, consume=True)
