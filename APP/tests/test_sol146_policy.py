"""Fight-bound optional targeting checks survive table commit and cold reload."""

import pytest

from combat import targeting, zones
from combat.gate5_service import CombatService
from combat.saved_fight_format import UnsupportedSavedFight, saved_targeting_policy
from tests.persistence_support import inventory
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_hidden_targeting import hidden_fight, LEFT, RIGHT, STRIKE
from tests.r10_fixup_support import cast_sender, commit


@pytest.mark.parametrize('benefit,wording,expected', [
    (None, 'Disadvantage', 'DISADVANTAGE'),
    ('advantage', 'normal roll: your Advantage cancels it', 'NORMAL'),
    ('piercing', 'normal roll: no Disadvantage applies', 'NORMAL'),
])
def test_remembered_table_menu_uses_real_modes_without_mutation(tmp_path, monkeypatch, benefit, wording, expected):
    from tests import test_tabletop_hunt6 as H
    from tests.test_lock9_attack_modes import PIERCING, KIT
    from tests.test_lock2_persistence import act
    combat, table, mid = H.table_fight(tmp_path, [PIERCING] if benefit == 'piercing' else [],
                                      kit=KIT, ally_talents=[])
    def setup(e):
        e._apply_condition(e.state.actors[H.RIGHT], 'condition:typed.invisible', 'test:unseen',
                           H.RIGHT, expires_on='UNTIL_REMOVED')
        if benefit == 'advantage':
            e._add_modifier(e.state.actors[H.LEFT], 'test:benefit', 'attack_mode', 'SET',
                            'ADVANTAGE', 'NEXT_ATTACK', expires_on='CONSUMED')
    H.on_hold(monkeypatch, setup)
    assert act(table, mid, H.HOLD)['status'] == 'COMMITTED'
    monkeypatch.undo()
    # Cold-load the accepted state; repeat menus and query without spending it.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat._load_session(mid)
    e = session.engine
    before = e.state.model_dump(mode='json')
    rolls = [r.model_dump(mode='json') for r in e.rolls]
    events = [v.model_dump(mode='json') for v in e.events]
    journals = inventory(session.store.match_dir)
    for _ in range(2):
        label = targeting.remembered_square_label(e, e.state.actors[H.LEFT], e.state.actors[H.RIGHT])
        assert f'— {wording}; a miss if nobody is there' in label
        state = table.state(mid)
        group = next(g for g in state['menu']['actions']
                     if '.weapon.dao' in g['source_definition_id'] and '#' not in g['source_definition_id'])
        option = next(o for o in group['options'] if H.RIGHT in o['target_ids'])
        assert option['destination'] is not None
        assert option['label'] == label
    assert e.state.model_dump(mode='json') == before
    assert [r.model_dump(mode='json') for r in e.rolls] == rolls
    assert [v.model_dump(mode='json') for v in e.events] == events
    assert inventory(session.store.match_dir) == journals
    assert table.act(mid, option['candidate_id'], state['menu']['decision_id'],
                     state['menu']['state_version'], state['last_sequence'])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    attacks = [v for v in loaded.engine.events
               if v.sequence > state['last_sequence'] and v.event_type == 'ATTACK_ROLLED']
    assert attacks and all(v.payload['mode'] == expected for v in attacks)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('configured', [{}, {key: 0 for key in targeting.POLICY_KEYS}])
def test_default_unseen_table_attack_no_percentile_commit_reload(tmp_path, monkeypatch, configured):
    monkeypatch.setattr(targeting, 'rules', lambda: dict(configured))
    combat, table, mid = hidden_fight(tmp_path, monkeypatch)
    monkeypatch.undo()  # The setup scripts Hide; this attack uses real seeded dice.
    engine = combat._load_session(mid).engine
    actor, target = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    assert 'DISADVANTAGE' in zones.attack_modes(engine, actor, target)
    label = targeting.remembered_square_label(engine, actor, target)
    assert label == 'Attack the square where you last saw Right — Disadvantage; a miss if nobody is there'
    options = [o for g in table.state(mid)['menu']['actions'] if g['label'] == STRIKE for o in g['options']]
    assert options and all(o['label'] == label for o in options)
    seq, start = engine.state.event_sequence, len(engine.rolls)
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in loaded.engine.events if e.sequence > seq)
    assert not any('miss chance' in e.payload.get('log', '') or 'miss_chance_percent' in e.payload
                   for e in loaded.engine.events if e.sequence > seq)
    assert not any(r.reason == 'CONCEALMENT_MISS_CHANCE' for r in loaded.engine.rolls[start:])
    assert targeting.policy(loaded.engine) == {key: 0 for key in targeting.POLICY_KEYS}
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_configured_policy_freezes_at_creation_and_uses_plain_label(tmp_path, monkeypatch):
    configured = {'concealment_miss_percent': 13, 'total_concealment_miss_percent': 37}
    monkeypatch.setattr(targeting, 'rules', lambda: dict(configured))
    combat, _, mid = hidden_fight(tmp_path, monkeypatch)
    monkeypatch.undo()
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    e = loaded.engine
    assert targeting.policy(e) == configured
    assert targeting.concealment_percent(e, e.state.actors[LEFT], e.state.actors[RIGHT]) == 37
    assert '37% miss chance' in targeting.remembered_square_label(e, e.state.actors[LEFT], e.state.actors[RIGHT])
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize('value', [None, -1, 101, 1.5, True, '50'])
def test_invalid_saved_policy_rejected(value):
    policy = {'concealment_miss_percent': value, 'total_concealment_miss_percent': 37}
    with pytest.raises(UnsupportedSavedFight) as caught:
        saved_targeting_policy([{'event_type': 'MATCH_CREATED', 'payload': {'targeting_policy': policy}}])
    assert 'targeting settings' in caught.value.reason
