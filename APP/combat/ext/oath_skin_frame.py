"""Oath-Skin Frame: one source-bound sheet contribution and frozen scene HP.

Initial installation remains in the causal calculator. The owner source-event
route records availability, explicit story severance/replacement, or the actual
three printed stabilizations for integration. Suppression and ordinary dispels
never remove a running scene's HP. Severance uses the public max-HP adjustment
policy (clamp only, no healing), is irreversible for that acquisition, and does
not interpret any sibling ability's risk/severity mechanics.
"""
from copy import deepcopy
from . import hook

FOUNDATION = 'iron_oath_skin_v0_2B'
FRAME = 'foundation.' + FOUNDATION + '.oath_skin_frame'
HASH = '77f358d41a5453c702cf0bc2045cc856f356c79723e17aa4183e481aecbd2098'
BLOCK = 'oath_skin_frame_source'
STABILIZATIONS = {'protect_without_controlling', 'accept_protection', 'clarify_oath',
                  'retreat_strategically', 'treat_iron_scar_constriction',
                  'forge_defensive_technique_with_declared_subject'}


def source_projection(sheet):
    """Return authenticated installation inputs; absence grants no new benefit."""
    from non_sphere_authority.foundation_mechanics import (
        has_acquired_foundation, resolve_initial_foundation_mechanics, verified_foundation_records,
    )
    from ..canonical import canonical_sha256
    foundation = sheet.get('foundation') or {}
    if foundation.get('record_id') != FOUNDATION or not has_acquired_foundation(foundation):
        return None
    from hashlib import sha256
    from ..status_text import printed_rules
    if sha256(printed_rules()[FRAME].encode()).hexdigest() != HASH:
        raise ValueError('Oath-Skin Frame requires its exact controlling printed source.')
    mechanics = foundation.get('mechanics')
    if not isinstance(mechanics, dict):
        return None
    initial = mechanics.get('initial_state') or {}
    expected = resolve_initial_foundation_mechanics(verified_foundation_records()[FOUNDATION],
        initial.get('active_expression_path_ids') or [], stage=initial.get('stage'))
    if canonical_sha256(mechanics) != canonical_sha256(expected):
        raise ValueError('Oath-Skin Frame installation does not match its published source.')
    return foundation, expected


def hp_value(mechanics, pb):
    from stage2.formulas import evaluate_formula
    return sum(evaluate_formula(row['formula']['root'], {'pb': pb}).value
               for row in mechanics['hp_maximum_modifiers']
               if row.get('feature_name') == 'Oath-Skin Frame')


@hook('compile_bundle')
def seal_frame(bundle, info):
    projection = source_projection(info['owner_sheet'])
    if projection is None:
        return bundle
    foundation, mechanics = projection
    pb = int(info['numbers']['pb'])
    # The sheet contribution is an output/cache, never authority. Recompute from
    # the authenticated mechanics so edited imports cannot mint arbitrary HP.
    amount = hp_value(mechanics, pb)
    bundle['typed_passives'].append({'feature_id': FRAME, 'block': BLOCK,
        'acquisition_id': foundation['acquisition_event_id'], 'amount': int(amount),
        'source_sha256': HASH, 'stage': foundation['stage'],
        'available': int(bool(foundation.get('frame_available', True))),
        'source_event_order_floor': max(int(foundation.get('frame_source_event_order', 0)),
                                        int(foundation.get('frame_availability_order', 0))),
        'severed': int(bool(foundation.get('frame_severed')))})
    return bundle


def owned_row(engine, actor_id):
    return next((r for r in engine.typed_passive_rows.get(actor_id, [])
                 if r.get('block') == BLOCK and r.get('feature_id') == FRAME), None)


@hook('validate_source_event')
def validate_frame_event(engine, event):
    if event.source_id != FRAME:
        return None
    row = owned_row(engine, event.actor_id)
    if row is None or event.acquisition_id != row['acquisition_id']:
        raise ValueError('The source event must bind the creature’s current acquired Iron Oath Skin.')
    if event.data.get('source_sha256') != HASH:
        raise ValueError('Use the exact controlling Oath-Skin Frame source.')
    if event.kind not in {'suppressed', 'available', 'ordinary_dispel', 'fully_severed', 'replaced', 'integrated'}:
        raise ValueError('Record availability, dispel, explicit full severance/replacement, or integration.')
    if set(event.data) != {'source_sha256'}:
        raise ValueError('Numerical bonuses and private story details cannot enter source-event data.')
    severed = row.get('severed') or any(e.event_type == 'SOURCE_EVENT_RECORDED'
        and e.payload['source_event']['acquisition_id'] == event.acquisition_id
        and e.payload['source_event']['actor_id'] == event.actor_id
        and e.payload['source_event']['source_id'] == FRAME
        and e.payload['source_event']['kind'] in {'fully_severed', 'replaced'} for e in engine.events)
    if severed and event.kind not in {'ordinary_dispel', 'fully_severed', 'replaced'}:
        raise ValueError('A fully severed acquisition cannot be restored or integrated; acquire its replacement.')
    return True


@hook('validate_source_evidence')
def validate_frame_evidence(engine, event, evidence):
    if event.source_id != FRAME:
        return None
    if not isinstance(evidence, dict) or set(evidence) != {'source_reference', 'story_effect', 'stabilizations'}:
        raise ValueError('Provide the actual private source reference, story effect and stabilization records.')
    if any(not isinstance(evidence.get(k), str) or not evidence[k].strip()
           for k in ('source_reference', 'story_effect')):
        raise ValueError('Describe the actual source and story effect; a success/approval flag is insufficient.')
    rows = evidence['stabilizations']
    if not isinstance(rows, list):
        raise ValueError('Stabilizations must be explicit source-defined scene records.')
    if event.kind == 'integrated':
        row = owned_row(engine, event.actor_id)
        available = bool(row['available'])
        for prior in engine.events:
            if prior.event_type == 'SOURCE_EVENT_RECORDED':
                old = prior.payload['source_event']
                if (old['acquisition_id'] == event.acquisition_id and old['source_id'] == FRAME
                        and old['actor_id'] == event.actor_id):
                    if old['kind'] in {'suppressed', 'available'}:
                        available = old['kind'] == 'available'
        if not available:
            raise ValueError('Integration requires the Foundation to be available, not fully suppressed.')
        if row['stage'] != 'Awakened':
            raise ValueError('Integrate the currently Awakened Foundation through its printed route.')
        if len(rows) != 3:
            raise ValueError('Integration needs three completed printed stabilizations.')
        for stabilization in rows:
            if (not isinstance(stabilization, dict)
                    or set(stabilization) != {'kind', 'source_reference', 'description'}
                    or stabilization['kind'] not in STABILIZATIONS
                    or any(not isinstance(stabilization[k], str) or not stabilization[k].strip()
                           for k in ('source_reference', 'description'))):
                raise ValueError('Each stabilization must name its printed route and actual completed scene.')
        if len({row['source_reference'] for row in rows}) != 3:
            raise ValueError('One completed scene cannot be counted as three stabilizations.')
    elif rows:
        raise ValueError('Stabilizations belong only to an integration event.')
    return True


@hook('apply_source_event')
def frame_scene_event(engine, event):
    if event.source_id != FRAME:
        return
    if event.kind not in {'fully_severed', 'replaced'}:
        text = {
            'integrated': 'Oath-Skin Frame is Integrated. Its additional proficiency bonus increases maximum HP in the next scene; this grants no healing now.',
            'suppressed': 'Oath-Skin Frame is unavailable. Its current maximum HP benefit stays through this scene; future scenes grant no benefit while it remains unavailable.',
            'available': 'Oath-Skin Frame is available. Its maximum HP benefit applies in the next scene; this grants no healing now.',
            'ordinary_dispel': 'An ordinary dispel does not remove Oath-Skin Frame or change its maximum HP benefit.',
        }[event.kind]
        engine._append_event('PASSIVE_TRIGGERED', FRAME, actor_id=event.actor_id,
            payload={'log': engine.state.actors[event.actor_id].display_name + ': ' + text})
        return
    row = owned_row(engine, event.actor_id)
    from ..maximum_hp import change
    change(engine, engine.state.actors[event.actor_id], FRAME + ':severance', -row['amount'],
        FRAME, event.actor_id, label='Oath-Skin Frame fully severed')


@hook('character_source_event')
def frame_character_event(sheet, receipt):
    event = receipt.get('event') or {}
    if event.get('source_id') != FRAME:
        return sheet
    projection = source_projection(sheet)
    if projection is None:
        return sheet
    foundation, initial = projection
    if event.get('acquisition_id') != foundation.get('acquisition_event_id'):
        return sheet  # Receipts from a former Foundation never affect a replacement.
    if not receipt.get('journal_sha256') or type(receipt.get('sequence')) is not int:
        raise ValueError('Foundation changes require their actual committed source-event receipt.')
    out = deepcopy(sheet)
    foundation = out['foundation']
    seen = foundation.setdefault('frame_source_event_ids', [])
    from ..canonical import canonical_sha256
    identity = canonical_sha256([receipt['match_id'], event['event_id']])
    if identity in seen:
        return out
    seen.append(identity)
    seen.sort()
    foundation['frame_source_event_order'] = max(
        int(foundation.get('frame_source_event_order', 0)), event.get('commit_order', 0))
    if foundation.get('frame_severed'):
        return out
    if event['kind'] in {'fully_severed', 'replaced'}:
        foundation['frame_severed'] = 1
        foundation['frame_available'] = 0
    elif event['kind'] in {'available', 'suppressed'}:
        # Also protect already-projected sheets when an older receipt arrives
        # after a newer availability transition has been applied to that sheet.
        order = event.get('commit_order', 0)
        if order >= foundation.get('frame_availability_order', 0):
            foundation['frame_available'] = int(event['kind'] == 'available')
            foundation['frame_availability_order'] = order
    elif event['kind'] == 'integrated':
        foundation['stage'] = 'Integrated'
    from non_sphere_authority.foundation_mechanics import resolve_foundation_stage_mechanics, verified_foundation_records
    mechanics = resolve_foundation_stage_mechanics(verified_foundation_records()[FOUNDATION],
        initial['initial_state']['active_expression_path_ids'], stage=foundation['stage'])
    pb = int(out['identity']['proficiency_bonus'])
    hp = out['ability_scores_and_statistics']['hit_points']
    contributions = hp.setdefault('source_contributions', {})
    # Likewise, only the verified prior mechanics establish the old amount;
    # stale or edited contribution metadata must not alter the delta.
    previous = hp_value(initial, pb)
    amount = hp_value(mechanics, pb) if foundation.get('frame_available', True) else 0
    hp['maximum'] = max(1, hp['maximum'] + amount - previous)
    if 'current' in hp:
        hp['current'] = min(hp['current'], hp['maximum'])
    contributions[FRAME] = amount
    return out
