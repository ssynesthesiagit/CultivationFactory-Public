"""Optional package guidance and policy enrichment shared by Factory/inventory.

Core loaders retain sphere policy authority. Optional guidance never invalidates
that policy, and providers keep their own activation gates.
"""
import json
import zipfile


def enrich_policy(policy, sheet, package):
    """Return an enriched copy; missing/malformed optional JSON is neutral."""
    from . import ext
    guidance = dict(sheet)
    try:
        with zipfile.ZipFile(package) as archive:
            profile = json.loads(archive.read('Dao_IChing_Combat_Profile.json'))
        if (isinstance(profile, dict) and profile
                and isinstance(profile.get('dao_i_ching', profile), dict)):
            guidance['dao_i_ching'] = profile
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        pass
    result = dict(policy)
    for additions in ext.run_strict('ai_policy_enrichment', dict(policy), guidance):
        if not isinstance(additions, dict):
            raise ValueError('ai_policy_enrichment must return a dict or None')
        result.update(additions)
    return result
