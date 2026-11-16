"""Chained recipient and documented choice authority via service commits/cold replay."""
import pytest
from combat.ext import placed
from tests.test_a2_trap_service import setup, pick, move, cold, AERIAL, ROAD, NET
from tests.test_a2_trap_fix_round import prepare_road
from tests.worker2_support import OWNER, ALLY, FOE, candidate, settle, turn


@pytest.fixture
def named_characters(monkeypatch):
    from tests import test_a2_trap_service as support
    original = support.fixture
    def named_fixture(*args, **kwargs):
        tune = kwargs['bundle_transform']
        def named_bundles(bundles):
            tune(bundles)
            from tests.cw2_service_support import seal
            for b, name in zip(bundles, ('Lin the trapper', 'Mei the ally', 'Han the enemy')):
                b['actor_template']['display_name'] = name
                seal(b)
        return original(*args, **{**kwargs, 'bundle_transform': named_bundles})
    monkeypatch.setattr(support, 'fixture', named_fixture)


@pytest.mark.parametrize('mode', ['SUGGESTED', 'MANUAL_AI_BRIDGE'])
@pytest.mark.parametrize('form,talent,event', [
    ('Dart Mechanism', None, 'ATTACK_ROLLED'),
    ('Net (Dart use)', NET, 'SAVE_ROLLED'),
    ('Flash Trap', 'TAL_TRAP_FLASH_TRAP', 'SAVE_ROLLED')])
def test_chain_label_matches_second_pattern_recipients(tmp_path, named_characters, mode, form, talent, event):
    talents = [AERIAL, ROAD, 'TAL_TRAP_CHAINED_MECHANISM'] + ([talent] if talent else [])
    combat, table, mid = setup(tmp_path, talents, height=0, restore_focus=True)
    prepare_road(combat, table, mid)
    pick(combat, table, mid, 'Trap form: ' + form)
    pick(combat, table, mid, 'Trap aim: east')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(3, 7)).candidate_id)
    second = next(z for z in placed.of(cold(tmp_path, mid), 'trap') if (z.center.x, z.center.y) == (3, 7))
    move(combat, table, mid, ALLY, (4, 7, 0))
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Prepare focus').candidate_id)
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    pick(combat, table, mid, 'Trap form: Tripwire')
    pick(combat, table, mid, 'Trap trigger: Chained Mechanism')
    settle(table, mid, candidate(combat, mid, 'Set Trap', at=(4, 6)).candidate_id)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode=mode)
    before = cold(tmp_path, mid)
    prompts = move(combat, table, mid, FOE, (4, 6, 0), picks={
        'choice:needle.trap_chained_pick': second.zone_id, 'choice:needle.trap_relocate': None})
    p = next(p for p in prompts if p['context']['reaction_source_id'].endswith('trap_chained_pick'))
    label = next(o['label'] for o in p['choice']['options'] if o['id'] == second.zone_id)
    e = cold(tmp_path, mid)
    assert placed.data(e.state.zones[second.zone_id])['chain_turn'] == e.state.round_number * 1000 + e.state.current_slot_index
    # Actual resolution is checked before the label assertion, including on the red run.
    events = [v for v in e.events[len(before.events):] if v.event_type == event]
    if form == 'Dart Mechanism':
        assert any(ALLY in v.target_ids for v in events)
        assert not any(FOE in v.target_ids for v in events)
    else:
        assert any(v.actor_id == ALLY for v in events)
        assert any(c.condition_id == ('condition:typed.blinded' if form == 'Flash Trap' else 'condition:typed.restrained')
                   for c in e.state.actors[ALLY].conditions.values())
    if form == 'Flash Trap':
        assert '5-foot burst' in label
        assert 'affected creature:' not in label
    else:
        assert 'affected creature: ' + e.state.actors[ALLY].display_name in label
        assert 'affected creature: ' + e.state.actors[FOE].display_name not in label


@pytest.mark.parametrize('mode', ['SUGGESTED', 'MANUAL_AI_BRIDGE', 'LOCAL_AUTO'])
def test_warning_documented_authority_matches_committed_choices(tmp_path, mode):
    from combat import ext
    from tests.test_a2_trap_service import test_warning_respects_controller_choice_authority
    test_warning_respects_controller_choice_authority(tmp_path, mode)
    # Check the public contract after exercising commit, warning response and cold replay.
    assert 'Player-controlled MANUAL, SUGGESTED and MANUAL_AI_BRIDGE' in ext.__doc__
    assert 'Actual automatic actors admit allies/self only' in ext.__doc__
