"""A bind's one-drop suppression cannot prevent the later release transaction."""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_needle as N
from tests.test_lock_choices import install


@pytest.mark.parametrize('reload_bound', [False, True])
def test_bound_weapon_release_drops_at_binder_and_replays(monkeypatch, tmp_path, reload_bound):
    bundles = []
    for actor_id, sphere, talents, initiative in (
            (N.FENCER, N.NEEDLE, [*N.BASE, 'TAL_FENCING_BIND_WEAPON'], 100),
            (N.FOE1, N.L4.BRUTE, [], -100)):
        bundle = compile_character(N.t._sheet(sphere, talents, {'starting_kit': N.KIT}),
                                   actor_id=actor_id,
                                   reaction_plan={'ask': True} if actor_id == N.FENCER else None)
        bundle['actor_template']['initiative_bonus'] = initiative
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(N.ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed='LOCK24-BIND-RELEASE', typed_bundles=tuple(bundles),
        roster_setup={'primary_actor_ids': [N.FENCER, N.FOE1],
            'team_by_actor': {N.FENCER: 'team:a', N.FOE1: 'team:b'},
            'starting_positions': {N.FENCER: {'x': 3, 'y': 6}, N.FOE1: {'x': 4, 'y': 6}}})
    mid = session.match_id
    table = TabletopService(combat, tmp_path)
    install(monkeypatch, 'd20_result', lambda engine, roll, intent:
        {'source_id': 'test:bind-roll', 'operation': 'replace',
         'natural_result': 15 if roll.reason.startswith('ATTACK:') else 1}
        if roll.reason.startswith(('ATTACK:', 'SAVE:')) else None)

    def submit(label, answers=()):
        state = table.state(mid)
        menu = state['menu']
        cid = menu['end_turn'] if label == 'end' else next(
            c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
            if c.display_name == label)
        return table.act(mid, cid, menu['decision_id'], menu['state_version'],
                         state['last_sequence'], list(answers))

    assert table.state(mid)['menu']['actor_id'] == N.FENCER
    pending = submit('Bi Shou (Dagger) attack: Disarm')
    assert pending['status'] == 'REACTION_REQUIRED', pending
    prompt = pending['reaction']
    assert prompt['context']['reaction_source_id'] == 'choice:needle.bind_weapon'
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': ['bind']}
    assert submit('Bi Shou (Dagger) attack: Disarm', [answer])['status'] == 'COMMITTED'
    actor = combat._load_session(mid).engine.state.actors[N.FOE1]
    bound = next(c for c in actor.conditions.values() if c.condition_id == 'condition:typed.needle_bound')
    weapon = bound.data['disables_action']
    assert not any(c.condition_id == 'condition:typed.disarmed' for c in actor.conditions.values())
    if reload_bound:
        combat = CombatService(N.ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)
    assert submit('end')['status'] == 'COMMITTED'
    assert table.state(mid)['menu']['actor_id'] == N.FOE1
    assert submit('Let go of the bound weapon')['status'] == 'COMMITTED'
    current = combat._load_session(mid)
    actor, binder = current.engine.state.actors[N.FOE1], current.engine.state.actors[N.FENCER]
    assert not any(c.condition_id in ('condition:typed.needle_bound', 'condition:typed.grappled')
                   for c in actor.conditions.values())
    assert not any(c.condition_id == 'condition:typed.needle_binding' for c in binder.conditions.values())
    dropped = [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.disarmed']
    assert len(dropped) == 1
    assert dropped[0].data['disables_action'] == weapon
    assert dropped[0].data['dropped_at'] == binder.position.model_dump(mode='json')
    assert not any(c.display_name == 'Bi Shou (Dagger) attack' for c in current.engine.legal_candidates())
    loaded = CombatService(N.ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == current.engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
