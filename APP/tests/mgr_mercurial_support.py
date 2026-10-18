"""Select the native compiled expression of one exact Source Rule.

Printed choose-one abilities expose named native options rather than a bare
parent action. No bundle, ownership, trigger or outcome is synthesized here.
"""


def source_candidate(combat, mid, source, target):
    engine = combat._load_session(mid).engine
    for candidate in engine.legal_candidates():
        action = engine.action_catalog.get(candidate.source_definition_id)
        typed = (action.parameters or {}).get('typed') or {} if action else {}
        if (typed.get('option_of') or typed.get('source')) == source and candidate.target_ids == (target,):
            return candidate
    raise AssertionError(f'No legal expression of {source} for {target}')
