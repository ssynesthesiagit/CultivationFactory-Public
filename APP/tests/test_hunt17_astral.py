"""Projection restrictions, dismissal and damage ending at the table boundary."""
import pytest
from combat.gate5_service import CombatService
from tests.r1i_service_support import ROOT, OWNER, FOE, fixture, candidate, force_ai_candidate
from tests.test_carry import KIT
from tests.h1_support import sheet
from combat.factory_compiler import compile_character

ASTRAL = 'tianxia.path.spirit_awakening.feature.astral_projection'
MIND = 'tianxia.path.spirit_awakening.feature.mind_spike'


def projected(actor):
    return [c for c in actor.conditions.values() if c.condition_id == 'condition:typed.invisible'
            and ASTRAL in str(c.source_definition_id)]


@pytest.mark.parametrize('auto', [False, True])
def test_projection_blocks_physical_actions_until_free_dismissal(tmp_path, auto):
    owned = [ASTRAL, MIND,
        'tianxia.talent.spirit_companions.covenant_spirit',
        'tianxia.talent.spirit_companions.battle_manifestation']
    def spirit(bundles):
        document = sheet(owned, cl=17, primary='Resonance', kit={'starting_kit': KIT})
        document['identity']['path'] = 'Spirit Awakening'
        bundles[0] = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = fixture(tmp_path, owned, bundle_transform=spirit)
    if not projected(combat._load_session(mid).engine.state.actors[OWNER]):
        commit(candidate(table, mid, 'Astral Projection'))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert projected(loaded.engine.state.actors[OWNER])
    names = [g['label'] for g in table.state(mid)['menu']['actions']]
    assert not any('Mind Spike' in n or 'Dagger' in n or 'Command Bonded Spirit' in n
                   or n == 'Grapple' or n.startswith('Shove') for n in names), names
    # A real table commit/reload ends projection without an action or resource spend.
    action = candidate(table, mid, 'Dismiss Astral Projection')
    actor = loaded.engine.state.actors[OWNER]
    resources, economy = dict(actor.resources), (actor.action_available, actor.bonus_action_available)
    if auto:
        force_ai_candidate(combat, mid, OWNER, action)
        assert send(action, auto=True)['status'] == 'COMMITTED'
    else:
        commit(action)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert not projected(actor)
    assert dict(actor.resources) == resources
    assert (actor.action_available, actor.bonus_action_available) == economy
    assert loaded.mechanical.replay()['status'] == 'PASS'
    if auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='MANUAL')
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    assert candidate(table, mid, 'Mind Spike', FOE)


@pytest.mark.parametrize('auto', [False, True])
def test_damage_ends_projection_after_table_commit_and_reload(tmp_path, auto):
    def spirit(bundles):
        doc = sheet([ASTRAL], cl=17, primary='Resonance')
        doc['identity']['path'] = 'Spirit Awakening'
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = fixture(tmp_path, [ASTRAL],
        foe_talents=['TAL_VOID_VOID_NEEDLE'], bundle_transform=spirit)
    if not projected(combat._load_session(mid).engine.state.actors[OWNER]):
        commit(candidate(table, mid, 'Astral Projection'))
    before = combat._load_session(mid).engine.state.actors[OWNER].current_hp
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    action = candidate(table, mid, 'Void Needle', OWNER)
    if auto:
        force_ai_candidate(combat, mid, FOE, action)
        assert send(action, auto=True)['status'] == 'COMMITTED'
    else:
        commit(action)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.actors[OWNER].current_hp < before
    assert not projected(fresh.engine.state.actors[OWNER])
    assert fresh.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('auto', [False, True])
def test_fate_deferred_damage_ends_projection_at_next_turn_end(tmp_path, auto):
    """Real deferred damage arrives inside turn-end dispatch, not a root event."""
    from combat.ext.karma_riders import DEFERRED_ID, DEFERRED

    owned = [ASTRAL, DEFERRED_ID]
    def spirit(bundles):
        doc = sheet(owned, cl=17, primary='Resonance')
        doc['identity']['path'] = 'Spirit Awakening'
        bundles[0] = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})
    combat, table, mid, send, commit = fixture(tmp_path, owned,
        foe_talents=['TAL_VOID_VOID_NEEDLE'], bundle_transform=spirit)
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != FOE:
        commit(table.state(mid)['menu']['end_turn'])
    before = combat._load_session(mid).engine.state.actors[OWNER].current_hp
    attack = candidate(table, mid, 'Void Needle', OWNER)
    answers = []
    accepted = False
    for _ in range(16):
        result = send(attack, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt['context']['reaction_source_id'] == 'choice:needle.fate_deferred':
            answer.update(selection='USE', option_ids=[prompt['choice']['options'][0]['id']])
            accepted = True
        answers.append(answer)
    else:
        pytest.fail('too many prompts')
    assert accepted
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = fresh.engine.state.actors[OWNER]
    debts = [c for c in owner.conditions.values() if c.condition_id == DEFERRED]
    assert len(debts) == 1 and debts[0].data['amount'] > 0
    debt_id, debt_amount = debts[0].instance_id, debts[0].data['amount']
    assert all(type(v) in (int, str) for v in debts[0].data.values())
    assert owner.current_hp == before
    assert fresh.mechanical.replay()['status'] == 'PASS'
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table, mid, 'Astral Projection'))
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    projections = projected(fresh.engine.state.actors[OWNER])
    assert len(projections) == 1
    projection_id = projections[0].instance_id
    assert any(c.condition_id == DEFERRED for c in fresh.engine.state.actors[OWNER].conditions.values())
    assert fresh.mechanical.replay()['status'] == 'PASS'
    sequence_before_end = fresh.engine.state.event_sequence
    hp_before_end = fresh.engine.state.actors[OWNER].current_hp
    assert fresh.engine.state.actors[OWNER].temporary_hp == 0
    end = table.state(mid)['menu']['end_turn']
    if auto:
        force_ai_candidate(combat, mid, OWNER, end)
        assert send(end, auto=True)['status'] == 'COMMITTED'
    else:
        commit(end)
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    owner = fresh.engine.state.actors[OWNER]
    arrived = [e for e in fresh.engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and e.source_definition_id == DEFERRED_ID and OWNER in e.target_ids]
    assert len(arrived) == 1 and arrived[0].payload['reduced_to'] == debt_amount
    debt_removals = [e for e in fresh.engine.events if e.event_type == 'CONDITION_REMOVED'
                     and e.payload.get('instance_id') == debt_id and OWNER in e.target_ids]
    assert len(debt_removals) == 1
    assert debt_removals[0].transaction_id == arrived[0].transaction_id
    assert sequence_before_end < debt_removals[0].sequence < arrived[0].sequence
    removals = [e for e in fresh.engine.events if e.event_type == 'CONDITION_REMOVED'
                and e.payload.get('instance_id') == projection_id and OWNER in e.target_ids]
    assert len(removals) == 1
    # The damage-ending rule must persist once, after damage, in the very same
    # table transaction; a later cleanup would hide the nested-delivery defect.
    assert removals[0].transaction_id == arrived[0].transaction_id
    ended = [e for e in fresh.engine.events if e.sequence > sequence_before_end
             and e.event_type == 'TURN_ENDED' and e.actor_id == OWNER]
    assert len(ended) == 1
    assert arrived[0].transaction_id == ended[0].transaction_id
    assert removals[0].sequence > arrived[0].sequence
    assert owner.current_hp == hp_before_end - debt_amount
    assert not any(c.condition_id == DEFERRED for c in owner.conditions.values())
    assert not projected(owner)
    assert fresh.mechanical.replay()['status'] == 'PASS'
