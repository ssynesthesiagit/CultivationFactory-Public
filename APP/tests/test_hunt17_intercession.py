"""Spirit Intercession protects only the owning bond, before the attack roll."""
import pytest
from combat.gate5_service import CombatService
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit
from tests.r1i_service_support import force_ai_candidate
from tests.h1_support import ROOT
from tests.r10_fixup_support import fixed_dice, answer

INTERCESSION = 'tianxia.talent.spirit_companions.spirit_intercession'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('kind', ['ally', 'spirit'])
def test_intercession_eligibility_and_roll_survive_reload(tmp_path, kind, auto):
    talents = [INTERCESSION]
    if kind == 'spirit':
        talents += ['tianxia.talent.spirit_companions.battle_manifestation',
                    'tianxia.talent.spirit_companions.covenant_spirit']
    bow = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian', 'quantity': 1}]}}
    combat, table, mid = table_fight(tmp_path, talents, kits={'right': bow}, ask=True, ally_talents=[])
    if kind == 'spirit':
        commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'))
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Move', at=(7, 4)))
    loaded = combat._load_session(mid)
    sequence = loaded.engine.state.event_sequence
    target = ALLY if kind == 'ally' else next(a.entity_id for a in loaded.engine.state.actors.values()
        if a.summon and a.summon.get('group') == 'bonded_spirit' and a.owner_id == LEFT)
    send = cast_sender(combat, table, mid, 'Gong Jian', target=target)
    if auto:
        action = next(c for c in loaded.engine.legal_candidates() if 'Gong Jian' in c.display_name and target in c.target_ids)
        force_ai_candidate(combat, mid, RIGHT, action.candidate_id)
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    result = send()
    if kind == 'ally':
        assert result['status'] == 'COMMITTED', result
    else:
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['reaction'] == 'Spirit Intercession'
        assert send([{**prompt['context'], 'selection': 'USE'}])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [e for e in fresh.engine.events if e.sequence > sequence and e.event_type == 'ATTACK_ROLLED']
    assert rolls and rolls[0].payload['mode'] == ('DISADVANTAGE' if kind == 'spirit' else 'NORMAL')
    assert fresh.engine.state.actors[LEFT].reaction_available == (kind == 'ally')
    assert fresh.mechanical.replay()['status'] == 'PASS'


def test_ai_owner_without_cp_accumulates_bond_strain_across_rounds(tmp_path, monkeypatch):
    from tests.test_tabletop_hunt6 import on_hold, HOLD
    talents = [INTERCESSION, 'tianxia.talent.spirit_companions.battle_manifestation',
               'tianxia.talent.spirit_companions.covenant_spirit']
    bow = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian', 'quantity': 1}]}}
    combat, table, mid = table_fight(tmp_path, talents, kits={'right': bow}, ask=True, ally_talents=[])
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'))
    def drain(engine):
        owner = engine.state.actors[LEFT]
        for pool in ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'):
            if owner.resources.get(pool, 0):
                engine._spend_resource(owner, pool, owner.resources[pool], 'test:empty_cp')
    on_hold(monkeypatch, drain)
    assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Move', at=(7, 4)))
    spirit = next(a for a in combat._load_session(mid).engine.state.actors.values()
                  if a.summon and a.summon.get('group') == 'bonded_spirit' and a.owner_id == LEFT)
    fixed_dice(monkeypatch, [19, 19, 1] * 100)
    for count in (1, 2):
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        assert cast_sender(combat, table, mid, 'Gong Jian', target=spirit.entity_id)()['status'] == 'COMMITTED'
        fresh = CombatService(ROOT, tmp_path)._load_session(mid)
        owner = fresh.engine.state.actors[LEFT]
        held = [c for c in owner.conditions.values() if c.condition_id == 'condition:typed.spirit_bond_strain']
        assert len(held) == 1 and held[0].data['strain'] == count, [
            (e.event_type, e.actor_id, e.payload) for e in fresh.engine.events[-15:]]
        assert held[0].data['bond_id'] == spirit.entity_id and held[0].expires_on is None
        assert owner.resources['resource:named.bond_strain'] == count
        assert fresh.mechanical.replay()['status'] == 'PASS'
        if count == 1:
            combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
            assert act(table, mid, 'end')['status'] == 'COMMITTED'
            while table.state(mid)['menu']['actor_id'] != RIGHT:
                assert act(table, mid, 'end')['status'] == 'COMMITTED'


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('outcome', ['pay', 'strain', 'miss', 'decline'])
def test_intercession_post_hit_price_commits_and_reloads(tmp_path, monkeypatch, auto, outcome):
    talents = [INTERCESSION, 'tianxia.talent.spirit_companions.battle_manifestation',
               'tianxia.talent.spirit_companions.covenant_spirit']
    bow = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.gong_jian', 'quantity': 1}]}}
    combat, table, mid = table_fight(tmp_path, talents, kits={'right': bow}, ask=True, ally_talents=[])
    commit(cast_sender(combat, table, mid, 'Command Bonded Spirit'))
    while table.state(mid)['menu']['actor_id'] != RIGHT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Move', at=(7, 4)))
    loaded = combat._load_session(mid)
    spirit = next(a for a in loaded.engine.state.actors.values()
                  if a.summon and a.summon.get('group') == 'bonded_spirit' and a.owner_id == LEFT)
    before = dict(loaded.engine.state.actors[LEFT].resources)
    pool = next(p for p in before if p in ('resource:core.qi', 'resource:core.stamina', 'resource:core.resonance'))
    fixed_dice(monkeypatch, [1 if outcome == 'miss' else 19] * 100)
    send = cast_sender(combat, table, mid, 'Gong Jian', target=spirit.entity_id)
    if auto:
        action = next(c for c in loaded.engine.legal_candidates()
                      if 'Gong Jian' in c.display_name and spirit.entity_id in c.target_ids)
        force_ai_candidate(combat, mid, RIGHT, action.candidate_id)
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    result = send()
    assert result['status'] == 'REACTION_REQUIRED', result
    answers = [{**result['reaction']['context'], 'selection': 'DECLINE' if outcome == 'decline' else 'USE'}]
    result = send(answers)
    if outcome in ('pay', 'strain'):
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['reaction'] == 'Spirit Intercession'
        assert 'Gong Jian' in str(prompt) and spirit.display_name in str(prompt)
        labels = {o['id']: o['label'] for o in prompt['choice']['options']}
        assert '1' in labels['pay_cp'] and 'Bond Strain' in labels['take_strain']
        answers.append(answer(prompt, 'pay_cp' if outcome == 'pay' else 'take_strain'))
        result = send(answers)
    assert result['status'] == 'COMMITTED', result
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = fresh.engine.state.actors[LEFT]
    assert owner.resources[pool] == before[pool] - (outcome == 'pay')
    strains = [c for c in owner.conditions.values() if c.condition_id == 'condition:typed.spirit_bond_strain']
    assert len(strains) == (outcome == 'strain')
    if strains:
        assert strains[0].data['bond_id'] == spirit.entity_id
        assert strains[0].data['strain'] == 1 and type(strains[0].data['strain']) is int
        assert 'Bond Strain' in strains[0].data['label']
    # The shared counter and saved condition describe the same single charge.
    assert owner.resources['resource:named.bond_strain'] == (outcome == 'strain')
    assert owner.reaction_available == (outcome == 'decline')
    assert fresh.mechanical.replay()['status'] == 'PASS'
