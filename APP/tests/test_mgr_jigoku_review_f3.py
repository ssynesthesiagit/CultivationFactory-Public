"""Review regressions: recipient work and independent native pulse consent."""
from copy import deepcopy
import json

import pytest

from combat.journey_native import KEY, PENDING, answer_key, capture, commit
from combat.journey_replay import initialize
from combat.ext.jigoku_procedures import SESSION, COOL, PREFIX, interrupts
from combat.ext.journey_activities import KEY as ACTIVITY
from tests.test_mgr_jigoku_brand_journey import branded_journey, answer_pending, native_events
from tests.test_mgr_jigoku_native import A, B, controlling_source_base


@pytest.mark.parametrize('use', [False, True])
def test_working_recipient_can_answer_hostile_brand_and_resume(tmp_path, monkeypatch, use):
    cold, jid, _, _, s = branded_journey(tmp_path, monkeypatch, defender=True)
    s = cold().journey_act(jid, s['revision'], B, 'activity_start', {'source':SESSION, 'parameters':{}})
    stamina = s['actors'][B]['resources']['resource:core.stamina']
    seconds = s['seconds']
    seen = []

    def choose(rows, pending):
        request = pending['request']
        rid = request['reaction_source_id']
        live = cold().journey_state(jid)
        assert ACTIVITY in live['actors'][B]['source_states']
        assert live['seconds'] == seconds
        if rid == 'choice:needle.fact_admission.hostile_intent':
            assert request['reactor_id'] == A
            return next(r for r in rows if r['payload']['option_ids'] == ['genuine'])
        if rid in ('choice:needle.eat_the_flame', 'choice:needle.pain_eater'):
            assert request['reactor_id'] == B
            seen.append(rid)
            if use:
                pick = 'eat' if rid.endswith('eat_the_flame') else 'mark'
                return next(r for r in rows if r['payload']['option_ids'] == [pick])
        return next(r for r in rows if r['payload']['selection'] == 'DECLINE')

    s = cold().journey_act(jid, s['revision'], B, 'activity_work', {'seconds':7200})
    s = answer_pending(cold, jid, s, choose)
    assert set(seen) == {'choice:needle.eat_the_flame', 'choice:needle.pain_eater'}
    assert ACTIVITY not in s['actors'][B]['source_states']
    assert s['seconds'] == seconds + 6
    assert s['actors'][B]['resources']['resource:core.stamina'] == stamina - int(use)
    assert not any(e['kind'] == 'ACTIVITY_FINISHED' for e in s['events'])
    assert cold().journey_verify(jid)['status'] == 'PASS'


@pytest.mark.parametrize('source', [COOL, SESSION])
@pytest.mark.parametrize('kind', ['native_effect_answer', 'native_effect_pick'])
def test_response_transport_does_not_interrupt_either_rite(source, kind):
    assert interrupts(None, B, {'source':source}, B, kind, {}) is False


def stock_brand_journey(tmp_path):
    """A real stock defender in the native JourneyStore cold/replay boundary."""
    from combat.gate2_runtime_content import ACTORS, AN
    from combat.gate5_service import CombatService
    from tests.h1_support import duel, ME, ROOT
    engine = duel([PREFIX+'flame_fist'], cl=17)
    engine._apply_condition(engine.state.actors[AN], 'condition:typed.burning',
        PREFIX+'flame_fist', ME, expires_on='UNTIL_REMOVED', data={
            'burn':0, 'brand_dice':2, 'source_cl':17, 'brand_save_dc':100,
            'label':'Burning Brand: 2d8 Fire at the start of each turn'})
    cold = lambda: CombatService(ROOT, tmp_path)
    bundles = [*engine.typed_bundle_documents,
               {'actor_id':AN, 'actor_template':ACTORS[AN].model_dump(mode='json')}]
    arena = json.loads((ROOT/'combat_gate1/generated/Battlefield.json').read_text())
    s = cold().journeys.create(bundles, arena,
        {aid:engine.state.actors[aid].position.model_dump(mode='json') for aid in (ME, AN)},
        {ME:1800, AN:1800})
    session = cold().journeys.load(s['journey_id'])
    capture(session, engine)
    commit(session, engine)
    initialize(session)
    cold().journeys.save(session)
    return cold, s['journey_id'], ME, AN


@pytest.mark.parametrize('first', ['USE', 'DECLINE'])
def test_each_ordinary_damage_pulse_requires_its_own_answer(tmp_path, first):
    cold, jid, source, target = stock_brand_journey(tmp_path)
    s = cold().journey_state(jid)
    offset = len(s['events'])
    stamina = s['actors'][target]['resources']['resource:an_eui.stamina']
    s = cold().journey_act(jid, s['revision'], source, 'wait', {'seconds':12})
    original = deepcopy(s[PENDING]['original'])
    keys = []
    for selection in (first, 'DECLINE' if first == 'USE' else 'USE'):
        assert PENDING in s, 'A later pulse must ask again, including after a decline'
        r = s[PENDING]['request']
        assert r['checkpoint'] == 'DAMAGE_APPLICATION'
        assert r['reaction_source_id'] == 'reaction:core.stamina_guard'
        assert r['journey_occurrence'] == len(keys)
        keys.append(answer_key(r))
        assert s[PENDING]['original'] == original
        menu = cold().journey_menu(jid, target)['options']
        rows = [o for o in menu if o['kind'] == 'native_effect_answer']
        for row in rows:
            assert 'Stamina Guard' in row['label']
            assert 'An Eui' in row['label']
            assert 'Burning Brand' in row['label']
            assert 'reaction:' not in row['label'] and 'resource:' not in row['label']
        uses = [o for o in rows if o['payload']['selection'] == 'USE']
        assert {o['payload']['spend'] for o in uses} == set(r['spend_options'])
        assert all(f"spend {o['payload']['spend']} Stamina" in o['label'] for o in uses)
        option = next(o for o in rows if o['payload']['selection'] == selection
                      and o['payload']['spend'] == (1 if selection == 'USE' else 0))
        s = cold().journey_act(jid, s['revision'], target, option['kind'], option['payload'])
        assert cold().journey_verify(jid)['status'] == 'PASS'
    assert len(set(keys)) == 2 and PENDING not in s
    assert s['actors'][target]['resources']['resource:an_eui.stamina'] == stamina - 1
    events = native_events(s, offset)
    packets = [e for e in events if e['event_type'] == 'DAMAGE_COMMITTED' and target in e['target_ids']]
    responses = [e for e in events if e['event_type'] == 'REACTION_RESOLVED'
                 and e['source_definition_id'] == 'reaction:core.stamina_guard']
    assert len(packets) == 2 and len(responses) == 1
    assert responses[0]['payload']['spend'] == 1


def test_event_unique_extension_keys_keep_their_native_identity():
    request = {'checkpoint':'NEEDLE@event:41', 'reactor_id':B, 'reaction_source_id':'choice:needle.pain_eater'}
    assert answer_key(request) == json.dumps(list(request.values()))
    assert answer_key({**request, 'checkpoint':'NEEDLE@event:42'}) != answer_key(request)


def test_journey_contract_registry_covers_new_call_sites():
    """Prevent another unregistered integration contract in these producers."""
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]/'combat'
    registry = (root/'ext/__init__.py').read_text()
    required = {'journey_acquisition', 'character_source_projection', 'journey_snapshot_actor',
                'journey_encounter_settled', 'journey_before_command', 'activity_spec',
                'reaction_admission', 'damage_packet_resolved'}
    found = set()
    for name in ('gate5_service.py', 'journey.py', 'typed_reactions.py', 'gate2_engine.py', 'ext/journey_activities.py'):
        for node in ast.walk(ast.parse((root/name).read_text())):
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                if node.args[0].value in required:
                    found.add(node.args[0].value)
    assert found == required
    assert all('# '+name+'(' in registry for name in required)
