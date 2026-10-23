"""Yin second pass: table choices, session commits, cold reload and replay."""
import pytest
from combat.gate5_service import CombatService
from combat.typed_executor import bears_mark
from tests.worker2_support import OWNER, ALLY, FOE, ROOT, fixture, candidate, act, settle, turn
from tests.test_carry import KIT

TWO = 'TAL_YIN_TWOFOLD_WANING'
PATIENT = 'TAL_YIN_PATIENT_MOON_METHOD'
CHOICE = 'choice:needle.yin_twofold_targets'
FORCE = 'TAL_YIN_SPENDING_A_WANING_MARK#diminish_force'


def cold(combat, tmp_path, mid):
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.engine.state.model_dump(mode='json') == before
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def setup(tmp_path, talents, **kwargs):
    return fixture(tmp_path, [*talents, 'TAL_YIN_MARKED_ALLIES'], foe_kit={'starting_kit': KIT},
                   owner_ac=1, foe_position={'x': 3, 'y': 5}, **kwargs)


def test_twofold_requires_two_selected_creatures_and_commits_once(tmp_path):
    combat, table, mid = setup(tmp_path, [TWO], seed='YIN-A2-TWO')
    cid = candidate(combat, mid, 'Twofold Waning').candidate_id
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    first = act(table, mid, cid)
    assert first['status'] == 'REACTION_REQUIRED', first
    assert first['reaction']['context']['reaction_source_id'] == CHOICE
    assert first['reaction']['context']['reactor_id'] == OWNER
    assert 'two different' in str(first['reaction']).lower()
    assert first['reaction']['cost'] == '2 Qi'
    assert act(table, mid, cid)['reaction'] == first['reaction']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    settle(table, mid, cid, {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    engine = cold(combat, tmp_path, mid)
    assert all(bears_mark(engine.state.actors[a], OWNER, 'Waning Mark') for a in (FOE, ALLY))
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 98
    applied = [e for e in engine.events if e.event_type == 'CONDITION_APPLIED' and e.source_definition_id.endswith(TWO)
               and str(e.payload.get('condition_id', '')).startswith('condition:typed.mark.waning_mark.')]
    assert len(applied) == 2


@pytest.mark.parametrize('pick', ['extend', None])
def test_patient_expiry_off_turn_choice_reload_and_deadline(tmp_path, pick):
    combat, table, mid = setup(tmp_path, [PATIENT], seed='YIN-A2-PATIENT')
    settle(table, mid, candidate(combat, mid, 'Mark the Waning', target=FOE).candidate_id, choices={})
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     choices={'choice:needle.yin_patient': pick})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yin_patient']
    assert len(asked) == 1
    assert asked[0]['context']['reactor_id'] == OWNER
    assert 'following turn' in str(asked[0]) and 'no action' in str(asked[0]).lower()
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark') == bool(pick)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100
    if pick:
        turn(table, mid, OWNER)
        again = settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in again)
        assert not bears_mark(cold(combat, tmp_path, mid).state.actors[FOE], OWNER, 'Waning Mark')


@pytest.mark.parametrize('pick', [FOE, None])
def test_twofold_first_spend_moves_exact_other_mark_or_declines(tmp_path, pick):
    combat, table, mid = setup(tmp_path, [TWO], seed='H5-CHOICES')
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    original = cold(combat, tmp_path, mid)
    mark = next(c for c in original.state.actors[ALLY].conditions.values() if 'mark.waning_mark.' in c.condition_id)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
                     choices={FORCE: 'first', 'choice:needle.yin_twofold_move': pick})
    asked = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yin_twofold_move']
    assert len(asked) == 1, prompts
    assert asked[0]['context']['reactor_id'] == OWNER
    assert '30 feet' in str(asked[0]) and 'no action' in str(asked[0])
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark') == bool(pick)
    assert bears_mark(engine.state.actors[ALLY], OWNER, 'Waning Mark') != bool(pick)
    assert not any(c.condition_id == 'condition:typed.yin_twofold_pair' for c in engine.state.actors[OWNER].conditions.values())
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 98
    if pick:
        moved = next(c for c in engine.state.actors[FOE].conditions.values() if 'mark.waning_mark.' in c.condition_id)
        assert (moved.expires_on, moved.data) == (mark.expires_on, mark.data)
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.yin_patient': None})
    engine = cold(combat, tmp_path, mid)
    assert not any(bears_mark(engine.state.actors[a], OWNER, 'Waning Mark') for a in (FOE, ALLY))


def test_patient_moves_to_chosen_creature_and_uses_one_round_limit(tmp_path):
    combat, table, mid = setup(tmp_path, [TWO, PATIENT], seed='YIN-A2-PATIENT-PAIR')
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'],
                     choices={'choice:needle.yin_patient': OWNER})
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in prompts) == 1
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[OWNER], OWNER, 'Waning Mark')
    assert not any(bears_mark(engine.state.actors[a], OWNER, 'Waning Mark') for a in (FOE, ALLY))
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 98
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.yin_patient': None})
    assert not bears_mark(cold(combat, tmp_path, mid).state.actors[OWNER], OWNER, 'Waning Mark')


@pytest.mark.parametrize('presentation', ['cost', 'trigger'])
def test_player_twofold_transfer_is_asked_during_ai_attack(tmp_path, presentation):
    from tests.r1i_service_support import force_ai_candidate
    def name_actors(bundles):
        from combat.canonical import canonical_sha256
        for bundle, name in zip(bundles, ['Moon Keeper', 'Marked Companion', 'Dagger Raider']):
            bundle['actor_template']['display_name'] = name
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = setup(tmp_path, [TWO], seed='H5-CHOICES', bundle_transform=name_actors)
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id
    force_ai_candidate(combat, mid, FOE, cid)
    before = cold(combat, tmp_path, mid).state.model_dump(mode='json')
    answers, prompts = [], []
    for _ in range(12):
        result = table.auto_step(mid, 0, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']; prompts.append(prompt)
        assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
        assert table.auto_step(mid, 0, answers)['reaction'] == prompt
        rid = prompt['context']['reaction_source_id']
        answer = {**prompt['context'], 'selection': 'USE' if rid in (FORCE, 'choice:needle.yin_twofold_move') else 'DECLINE'}
        if rid == 'choice:needle.yin_twofold_move':
            answer['option_ids'] = [FOE]
        answers.append(answer)
    else:
        raise AssertionError('too many prompts')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yin_twofold_move'
               and p['context']['reactor_id'] == OWNER for p in prompts)
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')
    assert not bears_mark(engine.state.actors[ALLY], OWNER, 'Waning Mark')
    assert engine.state.actors[OWNER].resources == before['actors'][OWNER]['resources']
    for economy in ('action_available', 'bonus_action_available', 'reaction_available'):
        assert getattr(engine.state.actors[OWNER], economy) == before['actors'][OWNER][economy]
    asked = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yin_twofold_move')
    import json
    (tmp_path / 'transfer-prompt.json').write_text(json.dumps(asked, indent=2))
    if presentation == 'cost':
        assert asked['cost'] == 'No action or additional resource cost'
    else:
        assert asked['action'] == 'Bi Shou (Dagger) attack'
        assert asked['trigger_actor'] == engine.state.actors[FOE].display_name
        assert asked['action'] in asked['moment']
        assert asked['trigger_actor'] in asked['moment']


def test_ai_patient_owner_extends_automatically_at_its_turn_end(tmp_path):
    from tests.r1i_service_support import force_ai_candidate
    combat, table, mid = setup(tmp_path, [PATIENT], seed='YIN-A2-AI-PATIENT')
    settle(table, mid, candidate(combat, mid, 'Mark the Waning', target=FOE).candidate_id, choices={})
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    cid = table.state(mid)['menu']['end_turn']
    force_ai_candidate(combat, mid, OWNER, cid)
    result = table.auto_step(mid, 0, [])
    assert result['status'] == 'COMMITTED', result
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 100


def test_legacy_patient_without_new_compiled_row_stays_inert(tmp_path):
    def legacy(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            bundle['typed_passives'] = [r for r in bundle.get('typed_passives', []) if r.get('block') != 'yin_patient_moon']
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = setup(tmp_path, [PATIENT], seed='YIN-A2-LEGACY', bundle_transform=legacy)
    settle(table, mid, candidate(combat, mid, 'Mark the Waning', target=FOE).candidate_id, choices={})
    engine = cold(combat, tmp_path, mid)
    assert not any(c.condition_id == 'condition:typed.yin_patient_watch' for c in engine.state.actors[OWNER].conditions.values())
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in prompts)
    assert not bears_mark(cold(combat, tmp_path, mid).state.actors[FOE], OWNER, 'Waning Mark')


def test_patient_watch_follows_twofold_transfer_without_restarting(tmp_path):
    combat, table, mid = setup(tmp_path, [TWO, PATIENT], seed='H5-CHOICES')
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    original = cold(combat, tmp_path, mid)
    watch = next(c for c in original.state.actors[OWNER].conditions.values()
                 if c.condition_id == 'condition:typed.yin_patient_watch' and c.data['target'] == ALLY)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
           choices={FORCE: 'first', 'choice:needle.yin_twofold_move': FOE})
    moved = cold(combat, tmp_path, mid)
    mark = next(c for c in moved.state.actors[FOE].conditions.values() if 'mark.waning_mark.' in c.condition_id)
    tracking = next(c for c in moved.state.actors[OWNER].conditions.values()
                    if c.condition_id == 'condition:typed.yin_patient_watch' and c.data['instance'] == mark.instance_id)
    assert tracking.data['target'] == FOE and tracking.expires_on == watch.expires_on
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.yin_patient': 'extend'})
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in prompts) == 1
    assert bears_mark(cold(combat, tmp_path, mid).state.actors[FOE], OWNER, 'Waning Mark')


def test_twofold_first_spend_still_qualifies_after_target_mark_refresh(tmp_path):
    def add_refresh(bundles):
        import copy
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle['actor_id'] != OWNER:
                continue
            action = copy.deepcopy(next(a for a in bundle['action_catalog'] if a['display_name'] == 'Mark the Waning'))
            action.update(source_definition_id='test:yin.refresh', display_name='Refresh test mark', economy='NONE')
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = setup(tmp_path, [TWO], seed='H5-CHOICES', bundle_transform=add_refresh)
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    settle(table, mid, candidate(combat, mid, 'Refresh test mark', target=FOE).candidate_id, choices={})
    cold(combat, tmp_path, mid)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=OWNER).candidate_id,
                     choices={FORCE: 'first', 'choice:needle.yin_twofold_move': FOE})
    assert any(p['context']['reaction_source_id'] == 'choice:needle.yin_twofold_move' for p in prompts)
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')
    assert not bears_mark(engine.state.actors[ALLY], OWNER, 'Waning Mark')


@pytest.mark.parametrize('pick', ['extend', None])
def test_patient_eligibility_precedes_a_long_marks_expiry(tmp_path, pick):
    # A sealed preparation action models Quiet Reception's long-lived mark.
    # Patient's compiled effect, choice, clocks and session code are unmodified.
    def long_mark(bundles):
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            if bundle['actor_id'] != OWNER:
                continue
            for action in bundle['action_catalog']:
                if action['display_name'] == 'Mark the Waning':
                    action['parameters']['typed']['effects'][0]['duration'] = {'kind': 'one_minute'}
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    combat, table, mid = setup(tmp_path, [PATIENT], seed='YIN-A2-LONG', bundle_transform=long_mark)
    settle(table, mid, candidate(combat, mid, 'Mark the Waning', target=FOE).candidate_id, choices={})
    before = cold(combat, tmp_path, mid)
    mark = next(c for c in before.state.actors[FOE].conditions.values() if 'mark.waning_mark.' in c.condition_id)
    assert mark.expires_on.startswith('START_OF_SLOT_AT:')
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], choices={'choice:needle.yin_patient': pick})
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in prompts) == 1
    engine = cold(combat, tmp_path, mid)
    after = next(c for c in engine.state.actors[FOE].conditions.values() if 'mark.waning_mark.' in c.condition_id)
    assert (after.instance_id, after.expires_on, after.data) == (mark.instance_id, mark.expires_on, mark.data)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, table.state(mid)['menu']['end_turn'], choices={})
    assert not any(p['context']['reaction_source_id'] == 'choice:needle.yin_patient' for p in prompts)
    cold(combat, tmp_path, mid)


def test_twofold_transfer_names_nested_counterattack_after_cold_reload(tmp_path):
    def counter(bundles):
        import copy
        from combat.canonical import canonical_sha256
        foe = bundles[2]
        dagger = next(a for a in foe['action_catalog'] if a['display_name'] == 'Bi Shou (Dagger) attack')
        typed = dagger['parameters']['typed']
        foe['typed_reactions'].append({'block': 'generic', 'kind': 'attacked',
            'feature_id': 'test:yin.counter', 'name': 'Counter Dagger', 'ask': True,
            'costs': [], 'numbers': {**typed['numbers'], 'attack_bonus': 100},
            'effects': copy.deepcopy(typed['effects'])})
        foe.pop('bundle_sha256', None)
        foe['bundle_sha256'] = canonical_sha256(foe)
    combat, table, mid = setup(tmp_path, [TWO], seed='H5-CHOICES',
                               owner_kit={'starting_kit': KIT}, bundle_transform=counter)
    settle(table, mid, candidate(combat, mid, 'Twofold Waning').candidate_id,
           {CHOICE: [FOE, ALLY], 'choice:willing.consent': 'accept'})
    before = cold(combat, tmp_path, mid).state.model_dump(mode='json')
    prompts = settle(table, mid, candidate(combat, mid, 'Bi Shou (Dagger) attack', target=FOE).candidate_id,
                     choices={'reaction:typed.test:yin.counter': 'first', FORCE: 'first',
                              'choice:needle.yin_twofold_move': FOE})
    engine = cold(combat, tmp_path, mid)
    assert bears_mark(engine.state.actors[FOE], OWNER, 'Waning Mark')
    assert not bears_mark(engine.state.actors[ALLY], OWNER, 'Waning Mark')
    assert engine.state.actors[OWNER].resources == before['actors'][OWNER]['resources']
    asked = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.yin_twofold_move')
    assert asked['action'] == 'Counter Dagger'
    assert asked['trigger_actor'] == engine.state.actors[FOE].display_name
    assert asked['cost'] == 'No action or additional resource cost'
