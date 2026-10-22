"""TEMPORARY probe (MAINREDSOUND1) — not for commit. One-line diagnostic on the failing move."""
from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, reload, settle, turn
from tests.test_mgr_t14_sound_read import READ

SCENE_VOICE = 'test.sound_review.spoken_scene'


def voiced(bundles):
    for bundle in bundles:
        for name, condition in [('Become hidden', 'hidden'), ('Become silent', 'silenced')]:
            source = 'action:test.review.' + condition + '.' + bundle['actor_id']
            bundle['action_catalog'].append({'source_definition_id': source, 'display_name': name,
                'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
                'target_kind': 'SELF', 'costs': [], 'parameters': {'free_primary': True, 'typed': {'effects': [
                    {'type': 'condition', 'condition': condition, 'applies_to': 'self',
                     'duration': {'kind': 'rounds', 'amount': 5}}]}}})
            bundle['actor_template']['action_ids'].append(source)
        source = 'action:test.review.voice.' + bundle['actor_id']
        bundle['action_catalog'].append({'source_definition_id': source, 'display_name': 'Speak in scene',
            'owner_id': bundle['actor_id'], 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'SELF', 'costs': [], 'parameters': {'free_primary': True, 'typed': {
                'source': SCENE_VOICE, 'effects': []}}})
        bundle['actor_template']['action_ids'].append(source)
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_probe_move(tmp_path, monkeypatch):
    from combat import speech
    monkeypatch.setitem(speech.rules(), 'needs_voice', {
        **speech.rules().get('needs_voice', {}), SCENE_VOICE: {'reason': 'probe'}})
    combat, table, mid = fixture(tmp_path, [READ], named=True, bundle_transform=voiced, owner_speed=90)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Become hidden').candidate_id)
    settle(table, mid, candidate(combat, mid, 'Speak in scene').candidate_id)
    turn(table, mid, OWNER)
    e = combat._load_session(mid).engine
    owner, foe = e.state.actors[OWNER], e.state.actors[FOE]
    far = [c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination
           and c.metadata.get('movement_mode', 'walk') == 'walk'
           and not ({(p.x, p.y) for p in c.canonical_path} & set(e._actor_cells(e.state.actors[FOE])))
           and e.grid.distance_between_cell_sets_ft([(c.destination.x, c.destination.y, c.destination.z)],
               e._actor_volume(e.state.actors[FOE])) > 60]
    assert far, 'no far move: ' + str(len([c for c in e.legal_candidates() if c.kind == 'MOVE']))
    move = far[0]
    rows = [f'start=({owner.position.x},{owner.position.y}) foe=({foe.position.x},{foe.position.y})',
            f'speed={e._effective_speed(owner)} rem={owner.movement_remaining_ft} fars={len(far)}',
            f'chosen=({move.destination.x},{move.destination.y},{move.destination.z}) cost={move.movement_cost_ft}',
            'cpath=' + ';'.join(f'{p.x},{p.y}' for p in move.canonical_path)]
    settle(table, mid, move.candidate_id)
    moved = reload(tmp_path, mid)
    mo, mf = moved.state.actors[OWNER], moved.state.actors[FOE]
    rows.append(f'end=({mo.position.x},{mo.position.y}) foe=({mf.position.x},{mf.position.y})')
    rows.append(f'dist={moved._distance_actor_to_actor(mo, mf)}')
    for ev in moved.events:
        if ev.event_type in ('MOVEMENT_COMMITTED', 'PASSIVE_TRIGGERED'):
            rows.append(ev.event_type + ':' + str((ev.payload or {}).get('log') or (ev.payload or {}).get('destination'))[:160])
    assert moved._distance_actor_to_actor(mo, mf) > 60, ' | '.join(rows)
