"""Source-owned contraindications for native recovery support.

Public query: exclusion(engine, subject) -> active native ConditionState or None.
Lotus-Root Recovery calls this before consent or payment. Other recovery
consumers may use it without importing the Foundation provider.

An authored typed condition may declare condition_data.recovery_support_exclusion
as 'preserves_corruption'. This means supporting health would preserve that
source's corruption, not merely that the patient is contaminated. Admission
requires both the actual active condition and the same declaration in its
originating owned action's condition effect. Names, damage types, teams and
missing classifications establish nothing. The existing native condition
producer/reducer/expiry own persistence; this query creates no fact ledger.
"""


def exclusion(engine, subject):
    for condition in subject.conditions.values():
        if (condition.data or {}).get('recovery_support_exclusion') != 'preserves_corruption':
            continue
        action = engine.action_catalog.get(condition.source_definition_id)
        if action is None or action.owner_id != condition.source_actor_id:
            continue
        typed = (action.parameters or {}).get('typed') or {}
        if source_declares_exclusion(typed.get('effects') or [], condition.condition_id):
            return condition
    return None


def source_declares_exclusion(effects, condition_id):
    """Validate the literal semantic declaration against its real source effect."""
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        if (effect.get('type') == 'condition'
                and 'condition:typed.' + str(effect.get('condition')) == condition_id
                and (effect.get('condition_data') or {}).get('recovery_support_exclusion') == 'preserves_corruption'):
            return True
        for value in effect.values():
            if isinstance(value, list) and source_declares_exclusion(value, condition_id):
                return True
    return False
