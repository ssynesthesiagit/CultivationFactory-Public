"""Printed Scoundrel area outcomes through accepted table intents and cold services."""
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import scoundrel_riders
from tests import auto11_service_support as S

ABILITY = 'TAL_SCOUNDREL_EVERYTHING_IN_THE_WRONG_PLACE'
TALENTS = ['TAL_SCOUNDREL_STEAL', 'TAL_SCOUNDREL_DIRTY_TRICK', ABILITY]


def cold(combat, mid):
    svc = CombatService(combat.source_root, combat.userdata_root)
    assert svc.replay(mid)['status'] == 'PASS'
    return S.engine(svc, mid)


def reply(result):
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source == 'choice:needle.area_recipients':
            return S.VICTIM
        if source in ('choice:needle.wrong_place_fail','choice:needle.wrong_place_success'):
            return result
        if source == 'choice:needle.wrong_place_object':
            return next(row['id'] for row in prompt['choice']['options'])
        if source.endswith('steal_spot'):
            # A destination farther than the old five-foot object radius.
            return 'cell:6,6'
        if source == 'choice:needle.subject_destination':
            return 'cell:6,6'
        return None
    return answer


@pytest.mark.parametrize('result', ['prone','reactions','opening','move','held','drop'])
def test_wrong_place_failure_chooses_exactly_one_result_and_reloads(tmp_path, result):
    combat, table, mid = S.fight(S.scratch(tmp_path), TALENTS, ally=True, rival=True,
                               victim_kit=S.SWORD if result == 'held' else S.PACK, seed='A2SCOUNDRE-area-B')
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=reply(result))
    assert response['status'] == 'COMMITTED'
    assert any(p['context']['reaction_source_id'] == 'choice:needle.wrong_place_fail' for p in prompts)
    engine = S.engine(combat, mid)
    victim = engine.state.actors[S.VICTIM]
    conditions = [c.condition_id for c in victim.conditions.values()]
    assert ('condition:typed.prone' in conditions) == (result == 'prone')
    assert ('condition:typed.reaction_denied' in conditions) == (result == 'reactions')
    assert ('condition:typed.exploited_opening' in conditions) == (result == 'opening')
    assert (victim.position.x == 6 and victim.position.y == 6) == (result == 'move')
    for who in (S.THIEF, S.ALLY, S.RIVAL):
        assert not engine.state.actors[who].conditions
    if result in ('held','drop'):
        key = 'tianxia.mortal.weapon.qiang' if result == 'held' else S.PACK_KEY
        records = S.records(engine, key)
        assert len(records) == 1
        assert records[0][1]['dropped_at'] == {'x':6,'y':6}
        assert records[0][1]['dropped_at'].get('z',0) == 0
        assert records[0][1].get('held_by') is None
    assert engine.state.actors[S.THIEF].resources[S.FOCUS] == 0
    assert engine.state.model_dump(mode='json') == cold(combat, mid).state.model_dump(mode='json')
    assert all('EVERYTHING IN THE WRONG PLACE' not in g['label'] for g in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('talents,count', [([],1), (['TAL_SCOUNDREL_CLEANED_OUT'],2)])
def test_steal_repositions_objects_without_losing_weight_or_identity(tmp_path, talents, count):
    from combat import carry
    combat, table, mid = S.fight(S.scratch(tmp_path),
        ['TAL_SCOUNDREL_STEAL', 'TAL_SCOUNDREL_DIRTY_TRICK', *talents],
        victim_kit={'items': [*S.PACK['items'], *S.SWORD['items']]})
    before = S.engine(combat, mid)
    weight = carry.weight(before, before.state.actors[S.VICTIM])
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'):
            return 'reposition:' + S.PACK_KEY
        if source.endswith('steal_location'):
            return 'carried'
        return None
    # Use the actual session route for a multi-option player answer, with both
    # distinct object identities in one accepted Steal check.
    candidate = S.candidate(table, mid, 'STEAL', target=S.VICTIM)
    answers, prompts = [], []
    for _ in range(20):
        result = S.act(table, mid, candidate, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']; prompts.append(prompt)
        reply = S.answer_for(prompt, answer)
        if prompt['context']['reaction_source_id'].endswith('steal_objects') and count == 2:
            legal = [row['id'] for row in prompt['choice']['options']]
            reply['option_ids'] = [S.offered(legal, 'reposition:' + key) for key in (S.PACK_KEY,'tianxia.mortal.weapon.qiang')]
        answers.append(reply)
    else:
        pytest.fail('Reposition did not commit')
    engine = S.engine(combat, mid)
    assert S.checks_succeeded(engine)
    records = [row for row in engine.state.actors[S.VICTIM].conditions.values() if row.data.get('object_location')]
    assert len(records) == count
    assert all(row.data['held_by'] == S.VICTIM and row.data['object_location'] == 'carried' for row in records)
    assert carry.weight(engine, engine.state.actors[S.VICTIM]) == weight
    assert len({row.data['object_id'] for row in records}) == count
    assert engine.state.model_dump(mode='json') == cold(combat, mid).state.model_dump(mode='json')
    assert len([p for p in prompts if p['context']['reaction_source_id'].endswith('steal_location')]) == count
    if count == 2:
        from combat.ext import hand_occupancy
        assert not any(row.data.get('disables_action') for row in records)
        assert not hand_occupancy.weapon_grips(engine, engine.state.actors[S.VICTIM])
        for _ in range(16):
            if table.state(mid)['menu']['actor_id'] == S.VICTIM:
                break
            S.play(table,mid,table.state(mid)['menu']['end_turn'])
        else:
            pytest.fail('Victim turn never arrived')
        assert not any(group['label'].startswith('Qiang') for group in table.state(mid)['menu']['actions'])
        assert any(group['label'].startswith('Draw Qiang') for group in table.state(mid)['menu']['actions'])
        assert cold(combat,mid).state.actors[S.VICTIM].conditions



@pytest.mark.parametrize('result', ['opening','move'])
def test_wrong_place_success_chooses_one_of_its_two_results(tmp_path, result):
    combat, table, mid = S.fight(S.scratch(tmp_path), TALENTS, ally=True, rival=True, seed='A2SCOUNDRE-area-A')
    def answer(prompt):
        if prompt['context']['reaction_source_id'] == 'choice:needle.subject_destination':
            return 'cell:5,6'  # exactly five feet from the targets starting square
        return reply(result)(prompt)
    response, prompts = S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=answer)
    assert response['status'] == 'COMMITTED'
    menu = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.wrong_place_success')
    assert {row['id'] for row in menu['choice']['options']} == {'opening', 'move'}
    engine = S.engine(combat, mid)
    victim = engine.state.actors[S.VICTIM]
    assert (victim.position.x, victim.position.y) == ((5,6) if result == 'move' else (4,6))
    assert not any(c.condition_id in ('condition:typed.prone','condition:typed.reaction_denied') for c in victim.conditions.values())
    assert bool(victim.conditions) == (result == 'opening')
    assert engine.state.model_dump(mode='json') == cold(combat, mid).state.model_dump(mode='json')


def test_ai_wrong_place_affects_enemies_and_excludes_allies_in_range(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    combat, table, mid = S.fight(S.scratch(tmp_path), TALENTS, ally=True, rival=True, seed='A2SCOUNDRE-area-B')
    candidate = S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE')
    force_ai_candidate(combat, mid, S.THIEF, candidate)
    response = table.auto_step(mid, table.state(mid)['last_sequence'])
    assert response['status'] == 'COMMITTED', response
    engine = S.engine(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and 'EVERYTHING_IN_THE_WRONG_PLACE' in e.source_definition_id]
    assert {e.actor_id for e in saves} == {S.VICTIM,S.RIVAL}
    assert not engine.state.actors[S.ALLY].conditions
    assert not engine.state.actors[S.THIEF].conditions
    for who in (S.VICTIM,S.RIVAL):
        assert any(c.condition_id == 'condition:typed.prone' for c in engine.state.actors[who].conditions.values())
        assert not any(c.condition_id == 'condition:typed.reaction_denied' for c in engine.state.actors[who].conditions.values())
    assert engine.state.model_dump(mode='json') == cold(combat, mid).state.model_dump(mode='json')


def test_wrong_place_reaction_denial_ends_at_owners_next_turn_end(tmp_path):
    combat, table, mid = S.fight(S.scratch(tmp_path), TALENTS, ally=True, rival=True, seed='A2SCOUNDRE-area-B')
    S.play(table, mid, S.candidate(table, mid, 'EVERYTHING IN THE WRONG PLACE'), answer=reply('reactions'))
    def denied():
        return any(c.condition_id == 'condition:typed.reaction_denied' for c in cold(combat, mid).state.actors[S.VICTIM].conditions.values())
    assert denied()
    S.to_thief(table, mid, end_thief=True)
    assert denied(), 'It lasts through the start of the owners next turn'
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert not denied(), 'It ends at that turn end, not the targets boundary'


def crowd(tmp_path):
    """Five visible enemies exceed the printed PB=4; all data is sealed before genesis."""
    import json, zipfile
    from combat.factory_compiler import compile_character
    ids = [S.THIEF, S.ALLY, *[S.VICTIM + str(i) for i in range(5)]]
    positions = [(3,6),(3,7),(4,6),(2,6),(3,5),(2,7),(4,7)]
    docs = {who: S._doc(TALENTS if who == S.THIEF else [], kit=S.PACK,
                       name='Thief' if who == S.THIEF else ('Ally' if who == S.ALLY else f'Enemy {i}'))
            for i,who in enumerate(ids)}
    for who,doc in docs.items():
        folder = tmp_path/'portable_characters'/who.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder/'current.zip','w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json',json.dumps(doc))
    bundles = [compile_character(docs[who],actor_id=who,reaction_plan={'ask':True} if who==S.THIEF else None) for who in ids]
    combat = CombatService(S.ROOT,tmp_path); table=TabletopService(combat,tmp_path)
    arena=combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    mid=combat._finish_factory_match(bundles,ids,
        {who:'team:a' if who in (S.THIEF,S.ALLY) else 'team:b' for who in ids},
        {who:{'x':x,'y':y} for who,(x,y) in zip(ids,positions)}, arena,
        [S.THIEF],[who for who in ids if who != S.THIEF],
        control_modes={who:'MANUAL' for who in ids},match_seed='A2SCOUNDRE-crowd',display_name='Scoundrel PB limit',maximum_rounds=10)['match_id']
    S.to_thief(table,mid)
    return combat,table,mid,ids[2:]


def test_player_and_ai_recipient_count_is_capped_by_proficiency(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    combat,table,mid,enemies=crowd(S.scratch(tmp_path))
    cid=S.candidate(table,mid,'EVERYTHING IN THE WRONG PLACE')
    response=S.act(table,mid,cid)
    assert response['status']=='REACTION_REQUIRED'
    prompt=response['reaction']
    assert prompt['context']['reaction_source_id']=='choice:needle.area_recipients'
    assert prompt['choice']['maximum']==4
    assert {o['id'] for o in prompt['choice']['options']}==set(enemies)
    # Finish the paused manual action, then test a separate automatic fight.
    answers = [{**prompt['context'], 'selection':'USE', 'option_ids':enemies[:4]}]
    for _ in range(20):
        committed = S.act(table,mid,cid,answers)
        if committed['status']=='COMMITTED':
            break
        assert committed['status']=='REACTION_REQUIRED'
        answers.append(S.answer_for(committed['reaction']))
    else:
        pytest.fail('Capped manual area did not commit')
    manual = cold(combat,mid)
    assert len([e for e in manual.events if e.event_type=='SAVE_ROLLED' and 'EVERYTHING_IN_THE_WRONG_PLACE' in e.source_definition_id]) == 4
    combat,table,mid,enemies=crowd(S.scratch(tmp_path/'ai'))
    cid=S.candidate(table,mid,'EVERYTHING IN THE WRONG PLACE')
    force_ai_candidate(combat,mid,S.THIEF,cid)
    response=table.auto_step(mid,table.state(mid)['last_sequence'])
    assert response['status']=='COMMITTED',response
    engine=cold(combat,mid)
    saves=[e for e in engine.events if e.event_type=='SAVE_ROLLED' and 'EVERYTHING_IN_THE_WRONG_PLACE' in e.source_definition_id]
    assert len(saves)==4 and len({e.actor_id for e in saves})==4
    assert {e.actor_id for e in saves} <= set(enemies)
    assert not engine.state.actors[S.ALLY].conditions


def test_reposition_failed_check_moves_nothing(tmp_path):
    from combat import carry
    combat,table,mid=S.fight(S.scratch(tmp_path), ['TAL_SCOUNDREL_STEAL','TAL_SCOUNDREL_DIRTY_TRICK'],seed='A2SCOUNDRE-reposition-D')
    initial=cold(combat,mid)
    weight=carry.weight(initial,initial.state.actors[S.VICTIM])
    response,prompts=S.play(table,mid,S.candidate(table,mid,'STEAL',target=S.VICTIM),answer='reposition:'+S.PACK_KEY)
    assert response['status']=='COMMITTED'
    engine=cold(combat,mid)
    checks=[e for e in engine.events if e.event_type=='CHECK_ROLLED' and e.payload.get('skill')=='Sleight of Hand']
    assert checks and checks[-1].payload['success'] is False
    assert not S.records(engine,S.PACK_KEY)
    assert not any(p['context']['reaction_source_id'].endswith('steal_location') for p in prompts)
    assert carry.weight(engine,engine.state.actors[S.VICTIM])==weight


def test_reposition_into_own_free_hand_retains_weight_and_occupies_that_hand(tmp_path):
    from combat import carry
    from combat.ext import hand_occupancy
    combat,table,mid=S.fight(S.scratch(tmp_path),['TAL_SCOUNDREL_STEAL','TAL_SCOUNDREL_DIRTY_TRICK'])
    before=cold(combat,mid)
    weight=carry.weight(before,before.state.actors[S.VICTIM]);hands=hand_occupancy.free_hands(before,before.state.actors[S.VICTIM])
    def answer(prompt):
        source=prompt['context']['reaction_source_id']
        if source.endswith('steal_objects'):return 'reposition:'+S.PACK_KEY
        if source.endswith('steal_location'):return next(o['id'] for o in prompt['choice']['options'] if o['id'].startswith('hand:'))
        return None
    response,prompts=S.play(table,mid,S.candidate(table,mid,'STEAL',target=S.VICTIM),answer=answer)
    assert response['status']=='COMMITTED'
    engine=cold(combat,mid);records=S.records(engine,S.PACK_KEY)
    assert len(records)==1 and records[0][1]['held_by']==S.VICTIM
    assert records[0][1]['object_location'].startswith('hand:')
    assert records[0][1]['hand'] in hands and records[0][1]['hand'] not in hand_occupancy.free_hands(engine,engine.state.actors[S.VICTIM])
    assert carry.weight(engine,engine.state.actors[S.VICTIM])==weight
