"""Guard review: precise boon text and complete manual consent after integration."""
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_lock2_persistence import act
from tests.test_mgr_t14_guard_parent import setup, hit, allowance, ALLY, OWNER
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, RIGHT, HOLD


def test_guard_condition_names_constitution_and_its_source_deadline(tmp_path):
    combat, table, mid = setup(tmp_path, concentrating=False)
    engine, _ = hit(tmp_path, combat, table, mid)
    label = allowance(engine.state.actors[ALLY]).data['label']
    assert 'next Constitution saving throw or eligible check' in label
    assert 'maintain a technique or resist this source of backlash or drain' in label
    assert f"start of {engine.state.actors[OWNER].display_name}'s next turn" in label


def test_integrated_manual_menu_survives_every_pass_and_cold_reopen(tmp_path, monkeypatch):
    corrupt = 'TAL_DAEMONIC_CULTIVATION_CORRUPT_THE_RIGHTEOUS_LAW'
    tax = 'TAL_DEATH_GRAVE_TAX'
    combat, table, mid = table_fight(tmp_path, [corrupt, tax], cl=20, ask=True, ally_talents=[])
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'

    def heal(engine):
        target = engine.state.actors[RIGHT]
        target.current_hp = 40
        engine._heal(target, 5, HOLD, RIGHT, notify_healed=True)

    on_hold(monkeypatch, heal)
    menu = table.state(mid)['menu']
    cid = next(o['candidate_id'] for g in menu['actions']
               if g['source_definition_id'] == HOLD for o in g['options'])
    expected = {'Corrupt the Righteous Law — ' + name for name in (
        'Reduce Healing', 'Reduce Temporary HP', 'Deny Reactions', 'Mark the Target')} | {'Grave Tax'}
    answers, seen = [], set()
    for _ in range(len(expected)):
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert {p['reaction'] for p in prompt.get('alternatives', [prompt])} == expected - seen
        assert prompt['reaction'] not in seen
        seen.add(prompt['reaction'])
        reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
        assert reopened.state(mid)['pending_action']['reaction'] == prompt
        answers.append({**prompt['context'], 'selection': 'DECLINE'})
        table = reopened
    assert seen == expected
    assert table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].reaction_available
    assert not [e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED' and e.actor_id == LEFT]
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
