"""TEMPORARY probe (MAINREDSOUND1) — not for commit. Prints the movement diagnostics."""
import json

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
    diag = {'owner_start': (owner.position.x, owner.position.y, owner.position.z),
            'foe': (foe.position.x, foe.position.y, foe.position.z),
            'start_distance': e._distance_actor_to_actor(owner, foe),
            'speed': e._effective_speed(owner),
            'movement_remaining': owner.movement_remaining_ft,
            'action_available': owner.action_available,
            'afraid_of': sorted(str(c.condition_id) for c in owner.conditions.values())}
    moves = [c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination]
    diag['move_count'] = len(moves)
    diag['move_dests'] = sorted({(c.destination.x, c.destination.y, c.destination.z, c.movement_cost_ft,
                                 c.metadata.get('movement_mode', 'walk')) for c in moves})[:20]
    far = [c for c in moves if c.metadata.get('movement_mode', 'walk') == 'walk'
           and not ({(p.x, p.y) for p in c.canonical_path} & set(e._actor_cells(e.state.actors[FOE])))
           and e.grid.distance_between_cell_sets_ft([(c.destination.x, c.destination.y, c.destination.z)],
               e._actor_volume(e.state.actors[FOE])) > 60]
    diag['far_count'] = len(far)
    diag['far_sample'] = [(c.destination.x, c.destination.y, c.destination.z, c.movement_cost_ft,
                           [(p.x, p.y) for p in c.canonical_path]) for c in far[:5]]
    assert far, diag
    move = far[-1]
    diag['chosen'] = (move.destination.x, move.destination.y, move.destination.z, move.movement_cost_ft,
                      move.candidate_id, [(p.x, p.y) for p in move.canonical_path])
    result = settle(table, mid, move.candidate_id)
    diag['prompts'] = [p.get('context', {}).get('reaction_source_id') for p in result]
    moved = reload(tmp_path, mid)
    mo, mf = moved.state.actors[OWNER], moved.state.actors[FOE]
    diag['owner_end'] = (mo.position.x, mo.position.y, mo.position.z)
    diag['foe_end'] = (mf.position.x, mf.position.y, mf.position.z)
    diag['end_distance'] = moved._distance_actor_to_actor(mo, mf)
    diag['events'] = [(ev.event_type, (ev.payload or {}).get('log') or (ev.payload or {}).get('destination')
                       or (ev.payload or {}).get('attempted_destination') or '')
                      for ev in moved.events if ev.event_type in
                      ('MOVEMENT_COMMITTED', 'PASSIVE_TRIGGERED', 'INTENT_ACCEPTED', 'CONDITION_APPLIED', 'CHECK_ROLLED')]
    diag['path'] = [(p.x, p.y) for p in (mo.path or ())] if hasattr(mo, 'path') else None
    assert diag['end_distance'] > 60, json.dumps(diag, indent=1, default=str)
