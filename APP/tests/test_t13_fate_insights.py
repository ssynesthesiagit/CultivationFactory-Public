"""Fate Insight consumers through table transactions and cold replay.

Session/scene facts are explicit sealed preparation inputs, not fake combat rites.
Synthetic native saves/contests expose printed causes and actual consequences.
"""
import json
import pytest

from combat.ext import fate_insights as F
from combat.gate5_service import CombatService, CombatServiceError
from combat.tabletop_service import TabletopService
from tests import auto_worker1_support as S
from tests.cw2_service_support import add_action
from tests.hunt15_support import action_sender

LEFT, RIGHT = S.LEFT, S.RIGHT
SAVE = [{'type': 'save', 'ability': 'wis', 'dc': 'technique_save_dc',
         'on_fail': [{'type': 'damage', 'damage_types': ['psychic'], 'flat': 9}], 'on_success': []}]
CHECK = [{'type': 'contest_against', 'actor_check': {'kind': 'check', 'ability': 'WIS'},
          'target_check': {'kind': 'dc', 'of': 'cultivation_save_dc'},
          'on_success': [{'type': 'damage', 'damage_types': ['psychic'], 'flat': 9}], 'on_fail': []}]


def fight(tmp_path, monkeypatch, insights=(), inputs=None, *, prepared_for=LEFT, talents=(), dc=100,
          cause_tags=(), check_hazards=(), ask=True, right_ac=1, right_insights=(), right_inputs=None, positions=None,
          right_talents=(), right_dc=None, owner_mode='MANUAL', finish_setup=True):
    if owner_mode != 'MANUAL':
        finish = CombatService._finish_factory_match
        def automatic_owner(self, *args, **kwargs):
            kwargs['control_modes'] = {**kwargs['control_modes'], LEFT: owner_mode}
            return finish(self, *args, **kwargs)
        monkeypatch.setattr(CombatService, '_finish_factory_match', automatic_owner)
    original_turn = S.turn
    monkeypatch.setattr(S, 'turn', lambda *_args, **_kw: None)
    def edit_sheet(doc, aid):
        if aid == LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = list(insights)
        else:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = list(right_insights)
            if right_dc is not None:
                doc['ability_scores_and_statistics']['technique_save_dc'] = right_dc
    def edit_bundle(bundle):
        if bundle['actor_id'] == LEFT:
            bundle.setdefault('prefight', {})['setup_choices'] = inputs or {}
            checks = [{**CHECK[0], 'actor_check': {**CHECK[0]['actor_check'], 'hazards': list(check_hazards)},
                       'target_check': {'kind': 'dc', 'dc': dc}}]
            add_action(bundle, 'Recognition check', checks)
            add_action(bundle, 'Ordinary save', SAVE, typed={'numbers': {'cl': 15, 'pb': 4, 'key_mod': 2, 'save_dc': 1}})
        else:
            bundle.setdefault('prefight', {})['setup_choices'] = right_inputs or {}
            bundle['actor_template']['armor_class'] = right_ac
            add_action(bundle, 'Incoming save', [{**SAVE[0], 'save_categories': list(cause_tags)}], typed={
                'numbers': {'cl': 15, 'pb': 4, 'key_mod': 2, 'save_dc': dc}})
            add_action(bundle, 'Recipient check', [{**CHECK[0], 'target_check': {'kind': 'dc', 'dc': 100}}])
        for action in bundle['action_catalog']:
            if action['display_name'] in ('Recognition check', 'Incoming save', 'Recipient check', 'Ordinary save'):
                action['parameters'].pop('player_only', None)
    c, t, mid = S.fight(tmp_path, talents, sheet_edit=edit_sheet, bundle_edit=edit_bundle,
                        reaction_ask=ask, left_save_dc=dc, positions=positions, right_talents=right_talents)
    monkeypatch.setattr(S, 'turn', original_turn)
    setup = any(v['display_name'].startswith('Finish fight setup')
                for v in c.decision(mid)['context']['legal_candidates'])
    if finish_setup and setup:
        picks = {'choice:needle.fate_preparation.' + fid: [prepared_for] if prepared_for else []
                 for fid in (F.COMPANION, F.NAME)}
        sender = seat_sender(c, t, mid, 'Finish fight setup') if owner_mode != 'MANUAL' else (
            lambda answers: S.act(t, mid, 'Finish fight setup', answers))
        S.resolve(sender, picks)
    return c, t, mid


def cold(c, mid):
    new = CombatService(S.ROOT, c.userdata_root)
    loaded = new._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def seat_sender(c, t, mid, name, target_id=None):
    """Exercise the assigned seat without changing it or contacting a provider."""
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate5_service import AI_RESPONSE_SCHEMA
    menu = t.state(mid)['menu']
    mode = cold(c, mid).typed_control_modes[menu['actor_id']]
    if mode == 'MANUAL':
        return action_sender(c, t, mid, name, target_id=target_id)
    # Automatic table views intentionally expose only a header. Select the
    # scripted action from the service context, then execute through auto_step.
    context = c.decision(mid)['context']
    cid = next(v['candidate_id'] for v in context['legal_candidates']
               if (v['kind'] == 'END_TURN' if name == 'end' else v['display_name'].startswith(name))
               and (target_id is None or target_id in v.get('target_ids', [])))
    real = c.controller
    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
        def __getattr__(self, attr):
            return getattr(real, attr)
    class Provider:
        def status(self):
            return {'ready': True}
        def complete_json(self, *, prompt_text, **kwargs):
            frame = json.loads(prompt_text.split('\n\n', 1)[1])
            row = next(v for v in frame['legal_candidates'] if v['candidate_id'] == cid)
            payload = {k: row[k] for k in ('candidate_id', 'actor_id', 'target_ids', 'destination', 'option_ids')}
            payload.update(decision_id=frame['decision_id'], state_version=frame['state_version'])
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': payload, 'rationale': 'Offline regression.'},
                    'provider_id': 'test:offline', 'model': 'fake', 'request_sha256': 'test-request'}
    c.controller = Controller()
    c.ai_provider = Provider()
    return lambda answers: t.auto_step(mid, t.state(mid)['last_sequence'], answers)


def seat_turn(c, t, mid, actor):
    for _ in range(12):
        if t.state(mid)['menu']['actor_id'] == actor:
            return
        S.resolve(seat_sender(c, t, mid, 'end'))
    raise AssertionError('turn did not advance')


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('feature,key', [(F.COMPANION, 'fate_companion_prepared'),
                                       (F.NAME, 'fate_name_prepared')])
@pytest.mark.parametrize('beneficiary,number', [(LEFT, 1), (RIGHT, 2)])
def test_declared_preparation_from_creation_survives_reload_and_benefits(
        tmp_path, monkeypatch, mode, feature, key, beneficiary, number):
    c, t, mid = fight(tmp_path, monkeypatch, [feature],
        {key: [1], key + '_beneficiary': [number]}, owner_mode=mode, cause_tags=['curse'],
        talents=['TAL_FATE_BINDING_WORD'] if feature == F.NAME else [])
    e = cold(c, mid)
    assert e.typed_control_modes[LEFT] == mode
    assert F.receipt(e.state.actors[LEFT], feature).data['beneficiary'] == beneficiary
    assert F.receipt(e.state.actors[LEFT], feature).data['spent'] == 0
    c = CombatService(S.ROOT, c.userdata_root)
    t = TabletopService(c, c.userdata_root)
    if feature == F.COMPANION:
        seat_turn(c, t, mid, beneficiary)
        sender = seat_sender(c, t, mid, 'Recognition check' if beneficiary == LEFT else 'Recipient check',
                             target_id=RIGHT if beneficiary == LEFT else LEFT)
        S.resolve(sender)
        e = cold(c, mid)
        assert F.receipt(e.state.actors[LEFT], feature).data['spent'] == 1
        rewrite = next(v for v in reversed(e.events) if v.event_type == 'D20_REWRITTEN'
                       and v.actor_id == beneficiary and v.source_definition_id == feature)
        assert 1 <= rewrite.payload['bonus'] <= 8
        assert last_roll(e, 'check', beneficiary).total == rewrite.payload['result']['total']
    else:
        seat_turn(c, t, mid, RIGHT if beneficiary == LEFT else LEFT)
        sender = seat_sender(c, t, mid, 'Incoming save' if beneficiary == LEFT else 'Binding Word',
                             target_id=beneficiary)
        S.resolve(sender)
        e = cold(c, mid)
        assert last_roll(e, 'save', beneficiary).mode == 'ADVANTAGE'


def send(c, t, mid, route, *, ai=False):
    actor = RIGHT if route == 'save' else LEFT
    S.turn(t, mid, actor)
    name = 'Incoming save' if route == 'save' else 'Recognition check' if route == 'check' else 'Bi Shou (Dagger) attack'
    return action_sender(c, t, mid, name, ai=ai, target_id=LEFT if route == 'save' else RIGHT)


def last_roll(engine, route, actor=LEFT):
    prefix = {'save': 'SAVE:', 'check': 'CHECK:', 'attack': 'ATTACK:'}[route]
    return next(r for r in reversed(engine.rolls) if r.actor_id == actor and r.reason.startswith(prefix))


@pytest.mark.parametrize('feature,key', [(F.COMPANION, 'fate_companion_prepared'),
                                       (F.NAME, 'fate_name_prepared')])
@pytest.mark.parametrize('declared', [0, 3])
@pytest.mark.parametrize('mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_missing_or_invalid_beneficiary_does_not_spend_preparation(
        tmp_path, monkeypatch, feature, key, declared, mode):
    c, t, mid = fight(tmp_path, monkeypatch, [feature],
        {key: [1], key + '_beneficiary': [declared]}, owner_mode=mode, finish_setup=False)
    before = cold(c, mid).state.model_dump(mode='json')
    error_type = ValueError if mode == 'LOCAL_AUTO' else CombatServiceError
    with pytest.raises(error_type) as refused:
        seat_sender(c, t, mid, 'Finish fight setup')([])
    diagnostic = str(refused.value) if mode == 'LOCAL_AUTO' else json.dumps(refused.value.to_dict())
    assert 'beneficiary' in diagnostic
    assert cold(c, mid).state.model_dump(mode='json') == before
    assert F.receipt(cold(c, mid).state.actors[LEFT], feature) is None


@pytest.mark.parametrize('route', ['attack', 'check', 'save'])
@pytest.mark.parametrize('die', [1, 11, 20])
@pytest.mark.parametrize('use', [True, False])
def test_loaded_recorded_raw_die_all_routes_commit_reload(tmp_path, monkeypatch, route, die, use):
    c, t, mid = fight(tmp_path, monkeypatch, [F.DESTINY], {'fate_destiny_recorded': [die]})
    sender = send(c, t, mid, route)
    before = cold(c, mid).state.model_dump(mode='json')
    result = sender([])
    assert result['status'] == 'REACTION_REQUIRED', result
    assert F.DESTINY in result['reaction']['context']['reaction_source_id']
    assert cold(c, mid).state.model_dump(mode='json') == before
    answer = {**result['reaction']['context'], 'selection': 'USE' if use else 'DECLINE'}
    S.resolve(lambda answers: sender([answer, *answers]))
    engine = cold(c, mid)
    held = F.receipt(engine.state.actors[LEFT], F.DESTINY)
    assert held.data['spent'] == int(use)
    roll = last_roll(engine, route)
    if use:
        assert roll.natural_result == die
        assert roll.total == die + roll.modifier
        if route == 'attack':
            event = next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == LEFT)
            assert event.payload['provisional_hit'] == (die != 1)
            assert (engine.state.actors[RIGHT].current_hp < 1000) == (die != 1)
        # The spent receipt remains through another native action and reload.
        if route != 'attack':
            _, prompts = S.resolve(sender)
            assert not any(F.DESTINY in p['context']['reaction_source_id'] for p in prompts)
            assert F.receipt(cold(c, mid).state.actors[LEFT], F.DESTINY).data['spent'] == 1


@pytest.mark.parametrize('route', ['attack', 'check', 'save'])
@pytest.mark.parametrize('ai', [False, True])
def test_companion_recipient_choice_and_bonus_native_routes(tmp_path, monkeypatch, route, ai):
    c, t, mid = fight(tmp_path, monkeypatch, [F.COMPANION], {'fate_companion_prepared': [1]}, dc=100, right_ac=100)
    sender = send(c, t, mid, route, ai=ai)
    result = sender([])
    if result['status'] == 'REACTION_REQUIRED':
        assert result['reaction']['context']['reactor_id'] == LEFT
        assert F.COMPANION in result['reaction']['context']['reaction_source_id']
        answer = {**result['reaction']['context'], 'selection': 'USE'}
        S.resolve(lambda answers: sender([answer, *answers]))
    else:
        assert ai and route != 'save' and result['status'] == 'COMMITTED', result
    engine = cold(c, mid)
    event = next(e for e in reversed(engine.events) if e.event_type == 'D20_REWRITTEN'
                 and e.source_definition_id == F.COMPANION)
    assert 1 <= event.payload['bonus'] <= 8
    roll = last_roll(engine, route)
    assert roll.total == event.payload['result']['total']
    assert F.receipt(engine.state.actors[LEFT], F.COMPANION).data['spent'] == 1
    assert engine.state.actors[LEFT].reaction_available


@pytest.mark.parametrize('prepared', [False, True])
@pytest.mark.parametrize('owns', [False, True])
def test_no_owner_no_preparation_are_inert(tmp_path, monkeypatch, prepared, owns):
    c, t, mid = fight(tmp_path, monkeypatch, [F.DESTINY, F.COMPANION] if owns else [],
        {'fate_destiny_recorded': [20 if prepared else 0], 'fate_companion_prepared': [int(prepared)]})
    sender = send(c, t, mid, 'check')
    S.resolve(sender)
    e = cold(c, mid)
    events = [v for v in e.events if v.event_type == 'D20_REWRITTEN' and v.source_definition_id in {F.COMPANION, F.DESTINY}]
    assert bool(events) == (owns and prepared)


@pytest.mark.parametrize('cause', sorted(F.RECOGNITION) + ['generic_awareness', 'loaded_dice'])
@pytest.mark.parametrize('owns', [False, True])
def test_gambler_exact_admitted_recognition_cause(tmp_path, monkeypatch, cause, owns):
    c, t, mid = fight(tmp_path, monkeypatch, [F.GAMBLER] if owns else [], check_hazards=[cause])
    S.resolve(send(c, t, mid, 'check'))
    assert last_roll(cold(c, mid), 'check').mode == ('ADVANTAGE' if owns and cause in F.RECOGNITION else 'NORMAL')


@pytest.mark.parametrize('cause', ['fate', 'curse', 'possession', 'domination', 'name_targeting', 'damage', ''])
@pytest.mark.parametrize('recipient', [LEFT, RIGHT, None])
def test_named_preparation_only_qualifying_beneficiary_save(tmp_path, monkeypatch, cause, recipient):
    c, t, mid = fight(tmp_path, monkeypatch, [F.NAME], {'fate_name_prepared': [1]},
                        prepared_for=recipient, cause_tags=[cause] if cause else [])
    S.resolve(send(c, t, mid, 'save'))
    e = cold(c, mid)
    assert last_roll(e, 'save').mode == ('ADVANTAGE' if recipient == LEFT and 'category:' + cause in F.NAME_CAUSES else 'NORMAL')
    assert F.receipt(e.state.actors[LEFT], F.NAME).data['beneficiary'] == (recipient or '')


def test_word_range_is_compiled_owned_and_narrow(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE], talents=['TAL_FATE_BINDING_WORD'])
    e = cold(c, mid)
    word = next(a for a in e.action_catalog.values() if (a.parameters.get('typed') or {}).get('source') == 'TAL_FATE_BINDING_WORD')
    assert word.range_ft == 60
    assert word.parameters['typed']['range_ft'] == 60
    assert word.parameters['typed']['mandate_word_owner'] == LEFT
    assert next(a for a in e.action_catalog.values() if a.display_name == 'Recognition check').range_ft == 120


@pytest.mark.parametrize('owns,scene,use', [(True, 7, True), (True, 7, False), (True, 0, True), (False, 7, True)])
def test_mandate_native_word_save_failure_notice_scene_receipt(tmp_path, monkeypatch, owns, scene, use):
    from combat.ext.d20_rewrite import pool_id
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE] if owns else [], {'fate_voice_scene': [scene]},
        talents=['TAL_FATE_BINDING_WORD'], dc=22, right_insights=[F.DESTINY],
        right_inputs={'fate_destiny_recorded': [20]})
    S.turn(t, mid, LEFT)
    sender = action_sender(c, t, mid, 'Binding Word', target_id=RIGHT)
    answers, prompts = [], []
    for _ in range(8):
        result = sender(answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        p = result['reaction']
        prompts.append(p)
        source = p['context']['reaction_source_id']
        accept = use if F.VOICE in source else True
        answers.append({**p['context'], 'selection': 'USE' if accept else 'DECLINE'})
    else:
        raise AssertionError('Word choices did not settle')
    e = cold(c, mid)
    target = e.state.actors[RIGHT]
    changed = owns and scene > 0 and use
    assert any(c.condition_id == 'condition:typed.restrained' for c in target.conditions.values()) == changed
    roll = last_roll(e, 'save', RIGHT)
    assert roll.natural_result == 20
    assert (roll.total < 22) == changed
    actor = e.state.actors[LEFT]
    assert actor.resources.get(pool_id(actor, 'heaven_s_notice'), 0) == int(changed)
    assert any(F.VOICE in p['context']['reaction_source_id'] for p in prompts) == (owns and scene > 0)
    if owns and scene:
        assert F.receipt(actor, F.VOICE).data['spent'] == int(changed)


@pytest.mark.parametrize('route', ['attack', 'check', 'save'])
def test_companion_real_failure_becomes_success_and_decline_preserves_grant(tmp_path, monkeypatch, route):
    # Derive a native threshold from the same seed without any optional provider.
    c, t, mid = fight(tmp_path / 'baseline', monkeypatch)
    S.resolve(send(c, t, mid, route))
    baseline = last_roll(cold(c, mid), route)
    assert baseline.natural_result not in (1, 20), 'Choose a seed with an ordinary attack result'
    threshold = baseline.total + 1
    c, t, mid = fight(tmp_path / 'prepared', monkeypatch, [F.COMPANION], {'fate_companion_prepared': [1]},
                        dc=threshold, right_ac=threshold)
    sender = send(c, t, mid, route)
    state = cold(c, mid).state.model_dump(mode='json')
    prompt = sender([])
    assert prompt['status'] == 'REACTION_REQUIRED'
    assert cold(c, mid).state.model_dump(mode='json') == state
    answer = {**prompt['reaction']['context'], 'selection': 'USE'}
    S.resolve(lambda a: sender([answer, *a]))
    e = cold(c, mid)
    roll = last_roll(e, route)
    assert roll.natural_result == baseline.natural_result
    assert roll.total >= threshold
    assert F.receipt(e.state.actors[LEFT], F.COMPANION).data['spent'] == 1
    if route == 'save':
        assert e.state.actors[LEFT].current_hp == 1000
    else:
        assert e.state.actors[RIGHT].current_hp < 1000


@pytest.mark.parametrize('beneficiary', [None, RIGHT, LEFT])
def test_companion_no_beneficiary_wrong_target_and_decline(tmp_path, monkeypatch, beneficiary):
    c, t, mid = fight(tmp_path, monkeypatch, [F.COMPANION], {'fate_companion_prepared': [1]}, prepared_for=beneficiary)
    sender = send(c, t, mid, 'check')
    result = sender([])
    if beneficiary == LEFT:
        assert result['status'] == 'REACTION_REQUIRED'
        assert sender([{**result['reaction']['context'], 'selection': 'DECLINE'}])['status'] == 'COMMITTED'
    else:
        assert result['status'] == 'COMMITTED'
    held = F.receipt(cold(c, mid).state.actors[LEFT], F.COMPANION)
    assert held.data['spent'] == int(beneficiary is None)


@pytest.mark.parametrize('feature', [F.DESTINY, F.COMPANION])
@pytest.mark.parametrize('route', ['attack', 'check', 'save'])
def test_automatic_roll_choice_without_player_prompt(tmp_path, monkeypatch, feature, route):
    inputs = {'fate_destiny_recorded': [20]} if feature == F.DESTINY else {'fate_companion_prepared': [1]}
    c, t, mid = fight(tmp_path, monkeypatch, [feature], inputs, ask=False, right_ac=100)
    sender = send(c, t, mid, route, ai=route != 'save')
    if route == 'save':
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    result = sender([])
    assert result['status'] == 'COMMITTED', result
    e = cold(c, mid)
    assert F.receipt(e.state.actors[LEFT], feature).data['spent'] == 1
    assert any(v.event_type == 'D20_REWRITTEN' and v.source_definition_id == feature for v in e.events)


@pytest.mark.parametrize('ai', [False, True])
def test_companion_nonowner_beneficiary_controls_the_choice(tmp_path, monkeypatch, ai):
    c, t, mid = fight(tmp_path, monkeypatch, [F.COMPANION], {'fate_companion_prepared': [1]}, prepared_for=RIGHT)
    S.turn(t, mid, RIGHT)
    sender = action_sender(c, t, mid, 'Recipient check', target_id=LEFT, ai=ai)
    before = cold(c, mid).state.model_dump(mode='json')
    result = sender([])
    if not ai:
        assert result['status'] == 'REACTION_REQUIRED', result
        assert result['reaction']['context']['reactor_id'] == RIGHT
        assert F.COMPANION in result['reaction']['context']['reaction_source_id']
        assert cold(c, mid).state.model_dump(mode='json') == before
        assert sender([{**result['reaction']['context'], 'selection': 'DECLINE'}])['status'] == 'COMMITTED'
        assert F.receipt(cold(c, mid).state.actors[LEFT], F.COMPANION).data['spent'] == 0
        S.resolve(sender)
    else:
        assert result['status'] == 'COMMITTED', result
    e = cold(c, mid)
    assert not F.owns(e, e.state.actors[RIGHT], F.COMPANION)
    assert F.receipt(e.state.actors[LEFT], F.COMPANION).data['spent'] == 1
    assert any(v.event_type == 'D20_REWRITTEN' and v.actor_id == RIGHT and v.source_definition_id == F.COMPANION for v in e.events)


def test_mandate_wrong_source_does_not_spend_admitted_scene(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE], {'fate_voice_scene': [9]}, talents=['TAL_FATE_BINDING_WORD'])
    S.turn(t, mid, LEFT)
    _, prompts = S.resolve(action_sender(c, t, mid, 'Ordinary save', target_id=RIGHT))
    assert not any(F.VOICE in p['context']['reaction_source_id'] for p in prompts)
    assert F.receipt(cold(c, mid).state.actors[LEFT], F.VOICE).data['spent'] == 0


def test_name_preparation_input_without_owner_is_inert(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [], {'fate_name_prepared': [1]}, cause_tags=['curse'])
    S.resolve(send(c, t, mid, 'save'))
    e = cold(c, mid)
    assert F.receipt(e.state.actors[LEFT], F.NAME) is None
    assert last_roll(e, 'save').mode == 'NORMAL'


def test_loaded_other_creature_cannot_spend_owners_result(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.DESTINY], {'fate_destiny_recorded': [20]})
    S.turn(t, mid, RIGHT)
    _, prompts = S.resolve(action_sender(c, t, mid, 'Recipient check', target_id=LEFT))
    assert not any(F.DESTINY in p['context']['reaction_source_id'] for p in prompts)
    assert F.receipt(cold(c, mid).state.actors[LEFT], F.DESTINY).data['spent'] == 0


def test_loaded_natural_twenty_hits_high_ac_and_doubles_native_damage(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.DESTINY], {'fate_destiny_recorded': [20]}, right_ac=100)
    S.resolve(send(c, t, mid, 'attack'))
    e = cold(c, mid)
    damage = next(v for v in reversed(e.events) if v.event_type == 'DAMAGE_ROLLED' and v.actor_id == LEFT)
    assert damage.payload['critical'] is True
    assert len(damage.payload['dice']) == 2
    assert e.state.actors[RIGHT].current_hp < 1000


def test_mandate_spent_scene_receipt_survives_turns_and_cold_reload(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE], {'fate_voice_scene': [17]},
        talents=['TAL_FATE_BINDING_WORD'], dc=22, right_insights=[F.DESTINY],
        right_inputs={'fate_destiny_recorded': [20]})
    S.turn(t, mid, LEFT)
    S.resolve(action_sender(c, t, mid, 'Binding Word', target_id=RIGHT))
    assert F.receipt(cold(c, mid).state.actors[LEFT], F.VOICE).data['spent'] == 1
    S.resolve(lambda a: S.act(t, mid, 'end', a))
    S.turn(t, mid, LEFT)
    c = CombatService(S.ROOT, c.userdata_root)
    t = TabletopService(c, c.userdata_root)
    _, prompts = S.resolve(action_sender(c, t, mid, 'Binding Word', target_id=RIGHT))
    assert not any(F.VOICE in p['context']['reaction_source_id'] for p in prompts)
    actor = cold(c, mid).state.actors[LEFT]
    assert F.receipt(actor, F.VOICE).data['scene'] == 17
    assert F.receipt(actor, F.VOICE).data['spent'] == 1


@pytest.mark.parametrize('owns,ai', [(False, False), (True, False), (True, True)])
def test_word_native_target_beyond_thirty_feet(tmp_path, monkeypatch, owns, ai):
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE] if owns else [], talents=['TAL_FATE_BINDING_WORD'],
        positions={LEFT: {'x': 3, 'y': 5}, RIGHT: {'x': 10, 'y': 5}})
    S.turn(t, mid, LEFT)
    menu = t.state(mid)['menu']
    options = [o for g in menu['actions'] if g['label'] == 'Binding Word' for o in g['options']
               if RIGHT in o.get('target_ids', [])]
    assert bool(options) == owns
    if owns:
        S.resolve(action_sender(c, t, mid, 'Binding Word', target_id=RIGHT, ai=ai))
        e = cold(c, mid)
        assert any(v.condition_id == 'condition:typed.restrained' for v in e.state.actors[RIGHT].conditions.values())


@pytest.mark.parametrize('prepared', [False, True])
def test_name_native_fate_word_source_without_guessed_cause(tmp_path, monkeypatch, prepared):
    c, t, mid = fight(tmp_path, monkeypatch, [F.NAME], {'fate_name_prepared': [int(prepared)]},
        prepared_for=RIGHT, talents=['TAL_FATE_BINDING_WORD'])
    S.turn(t, mid, LEFT)
    S.resolve(action_sender(c, t, mid, 'Binding Word', target_id=RIGHT))
    roll = last_roll(cold(c, mid), 'save', RIGHT)
    assert roll.mode == ('ADVANTAGE' if prepared else 'NORMAL')
    assert len(roll.dice) == (2 if prepared else 1)


def test_mandate_only_the_actual_word_caster_can_spend_its_scene_receipt(tmp_path, monkeypatch):
    c, t, mid = fight(tmp_path, monkeypatch, [F.VOICE], {'fate_voice_scene': [17]},
        talents=['TAL_FATE_BINDING_WORD'], right_talents=['TAL_FATE_BINDING_WORD'], right_dc=1,
        right_insights=[F.VOICE], right_inputs={'fate_voice_scene': [29]})
    S.turn(t, mid, RIGHT)
    sender = action_sender(c, t, mid, 'Binding Word', target_id=LEFT)
    prompt = sender([])
    assert prompt['status'] == 'REACTION_REQUIRED', prompt
    assert prompt['reaction']['context']['reactor_id'] == RIGHT
    S.resolve(lambda a: sender([{**prompt['reaction']['context'], 'selection': 'USE'}, *a]))
    e = cold(c, mid)
    assert F.receipt(e.state.actors[LEFT], F.VOICE).data['spent'] == 0
    assert F.receipt(e.state.actors[RIGHT], F.VOICE).data['spent'] == 1
