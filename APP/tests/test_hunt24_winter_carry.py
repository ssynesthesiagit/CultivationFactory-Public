"""Winter Stores carries actual prevention into a persisted, single-use fracture."""
import pytest

from combat.ext.ice_fracture import STORED
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.hunt23_support import action_sender
from tests.test_hunt24_reduction import attack_bundle, SOURCE
from tests.test_r9i_ice_persistence import fixture, fractures, action_id
from tests.test_r9i_karma_persistence import PLAYER, FOE, act, end_turn


@pytest.mark.parametrize('ai_turn', [False, True])
@pytest.mark.parametrize('automatic_owner', [False, True])
def test_winter_carried_prevention_commits_reloads_and_shatters_once(tmp_path, ai_turn, automatic_owner):
    def prepare(bundle):
        attack_bundle(bundle, owner=FOE)
        if bundle['actor_id'] == FOE:
            effects = bundle['action_catalog'][-1]['parameters']['typed']['effects'][0]['on_hit']
            effects[0].pop('dice')
            effects[0]['flat'] = 2

    combat, table, mid = fixture(tmp_path, prepare=prepare)
    if automatic_owner:
        combat.set_controller_mode(mid, actor_id=PLAYER, controller_mode='LOCAL_AUTO')
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    send = action_sender(combat, table, mid, SOURCE, ai=ai_turn, target_id=PLAYER)
    result = send([])
    if not automatic_owner:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] == 'choice:needle.winter_stores'
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        result = send([{**prompt['context'], 'selection':'USE', 'option_ids':['use']}])
    assert result['status'] == 'COMMITTED'
    combat = CombatService(ROOT, tmp_path)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    packets = [e.payload for e in loaded.engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id == SOURCE]
    assert len(packets) == 2
    prevented = sum(p['rolled_or_pending_damage'] - p['reduced_to'] for p in packets)
    stored = fractures(combat, mid)
    assert len(stored) == 1
    assert prevented == 6  # PB 4 + key modifier 2; spans both packets.
    assert stored[0].data['amount'] == prevented
    assert all(type(v) in (int, str) for v in stored[0].data.values())
    owner = loaded.engine.state.actors[PLAYER]
    assert owner.resources['resource:core.qi'] == before['actors'][PLAYER]['resources']['resource:core.qi'] - 1
    assert not owner.reaction_available
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    for aid in (PLAYER, FOE):
        combat.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    end_turn(table, mid)
    assert fractures(combat, mid)[0].data['amount'] == prevented
    cid = action_id(table, mid, 'Shatter Bloom')
    answers = []
    result = act(table, mid, cid)
    while result['status'] == 'REACTION_REQUIRED':
        context = result['reaction']['context']
        assert fractures(combat, mid)[0].data['amount'] == prevented
        source = context['reaction_source_id']
        if source == 'choice:needle.bloom_spaces':
            answer = {'selection':'USE', 'option_ids':['3,6']}
        elif source == 'choice:needle.bloom_type':
            answer = {'selection':'USE', 'option_ids':['COLD']}
        else:
            assert source == 'choice:needle.winter_stores'
            answer = {'selection':'DECLINE'}
        answers.append({**context, **answer})
        result = act(table, mid, cid, answers)
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    rolls = [r for r in loaded.engine.rolls if r.reason.startswith('DAMAGE:') and 'SHATTER_BLOOM' in r.reason.upper()]
    assert len(rolls) == 2
    assert [r.modifier for r in rolls] == [2 + prevented, 2]  # Printed Bloom adds the key modifier.
    assert not any(c.condition_id == STORED for c in loaded.engine.state.actors[PLAYER].conditions.values())
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_carry_receipt_credits_only_its_exact_owned_fracture():
    from combat.ext.ice_fracture import winter_stores_carried, T
    from tests.test_riders_lane9 import ME, ALLY, _ice_fight

    engine = _ice_fight(['WINTER_STORES_THE_BLOW'], ally_at=(3, 7))
    caster = engine.state.actors[ME]
    for amount in (1, 2):
        engine._apply_condition(caster, STORED, T + 'WINTER_STORES_THE_BLOW', ME,
                                expires_on='END_OF_CURRENT_TURN', data={'amount':amount})
    first, second = [c for c in caster.conditions.values() if c.condition_id == STORED]
    receipt = f'{STORED}|{ME}|{second.instance_id}'
    winter_stores_carried(engine, engine.state.actors[ALLY], receipt, 4)
    assert first.data['amount'] == 1 and second.data['amount'] == 6
    winter_stores_carried(engine, caster, 'unrelated', 99)
    winter_stores_carried(engine, caster, f'{STORED}|{ALLY}|{second.instance_id}', 99)
    del caster.conditions[second.instance_id]
    winter_stores_carried(engine, caster, receipt, 99)
    assert first.data['amount'] == 1 and second.instance_id not in caster.conditions
