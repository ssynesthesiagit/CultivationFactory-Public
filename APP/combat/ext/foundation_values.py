"""Read source-bound Foundation values already included in an exported sheet.

Consumer: foundations3.compile_open_channels_hp. Producer: Stage2Service._rows
publishes hp.foundation_delta and hp.authority_components; CharacterSheetService
publishes those rows as advancement_history.levels. Unknown or stale breakdowns
return None, never an inferred zero. No hook or runtime authority lookup.
"""


def foundation_hp_in_maximum(owner_sheet):
    """One current, matching recorded contribution, or None if unestablished."""
    foundation = owner_sheet.get('foundation') or {}
    if not isinstance(foundation, dict):
        return None
    record_id = foundation.get('expression_record_id') or foundation.get('record_id')
    if not isinstance(record_id, str) or not record_id:
        return None
    history = owner_sheet.get('advancement_history') or {}
    if not isinstance(history, dict):
        return None
    rows = history.get('levels') or []
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or type(row.get('cl')) is not int for row in rows):
        return None
    latest = max(rows, key=lambda row: row['cl'])
    if latest['cl'] != (owner_sheet.get('identity') or {}).get('cultivation_level'):
        return None
    hp = latest.get('hp') or {}
    stats = owner_sheet.get('ability_scores_and_statistics') or {}
    hit_points = stats.get('hit_points') if isinstance(stats, dict) else None
    if not isinstance(hp, dict) or not isinstance(hit_points, dict):
        return None
    maximum = hit_points.get('maximum')
    if type(hp.get('total')) is not int or hp['total'] != maximum or type(hp.get('foundation_delta')) is not int:
        return None
    components = hp.get('authority_components')
    if not isinstance(components, list):
        return None
    rows = [row for row in components if isinstance(row, dict) and row.get('role') == 'foundation_hp']
    if any(type(row.get('value')) is not int or row['value'] < 0 for row in rows):
        return None
    if sum(row['value'] for row in rows) != hp['foundation_delta']:
        return None
    own = [row for row in rows if row.get('record_id') == record_id]
    if not own:
        return None
    record_hash = foundation.get('record_hash')
    if any(not isinstance(row.get('record_hash'), str) or len(row['record_hash']) != 64
           or (record_hash is not None and row['record_hash'] != record_hash)
           or not isinstance(row.get('formula_id'), str) or '.hp_maximum.' not in row['formula_id']
           or not isinstance(row.get('source_anchor'), str) or not row['source_anchor'] for row in own):
        return None
    return sum(row['value'] for row in own)
