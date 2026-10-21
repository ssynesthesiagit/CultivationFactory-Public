"""Source-qualified protection queries for typed defenses and ongoing effects.

Only explicit source profiles participate. Missing origin/CL remains protected;
an unclassified immunity is never assumed biological. A policy is also opt-in:
ordinary actions keep all their old defenses. Numerical authority cannot erase
an artifact, Immortal, Secret, conceptual or explicitly absolute protection.
"""
ABSOLUTE = frozenset({'artifact', 'immortal', 'secret', 'conceptual', 'absolute', 'heavenly', 'world_law'})


def explicit_superior(profile):
    """Only declared authority/tags/flags establish a named superior protection."""
    if not isinstance(profile,dict):
        return False
    authority=profile.get('authority')
    if profile.get('absolute') or (isinstance(authority,str) and authority in ABSOLUTE):
        return True
    raw=profile.get('tags') or ()
    tags={str(t).strip().lower() for t in raw} if isinstance(raw,(list,tuple,set,frozenset)) else set()
    return bool(tags & ABSOLUTE) or any(profile.get(key) is True for key in ABSOLUTE)


def protection_applies(incoming, protection):
    """Pure bool: does this one protection remain against this one source?"""
    policy = incoming.get('authority_contest') or {}
    if not policy or not protection or explicit_superior(protection):
        return True
    if (policy.get('cultivated') == 1 and policy.get('bypass_biology') == 1
            and protection.get('origin') == 'ordinary_biology' and protection.get('authority') == 'ordinary'):
        return False
    mine = (incoming.get('numbers') or {}).get('cl')
    theirs = protection.get('source_cl')
    gap = policy.get('decisive_gap')
    if (protection.get('origin') == 'cultivated' and protection.get('authority') == 'ordinary'
            and type(mine) is int and type(theirs) is int and type(gap) is int
            and mine > 0 and theirs > 0 and gap >= 6 and mine - theirs >= gap):
        return False
    return True


def modifier_profile(engine, modifier):
    """An existing modifier's explicitly declared source authority, when known."""
    action = engine.action_catalog.get(modifier.source_definition_id)
    typed = action.parameters.get('typed') or {} if action is not None else {}
    return typed.get('protection_authority') or {}
