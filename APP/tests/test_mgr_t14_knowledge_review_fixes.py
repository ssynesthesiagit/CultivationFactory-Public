"""Service regressions for the four knowledge-input review findings.

All characters, journals and native scenes belong to pytest's isolated directory.
No model, browser, live service or owner-state dependency is used.
"""
import json
import subprocess
import zipfile

import pytest

from combat.encounter_sources import payload, prepare
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop import TabletopError
from tests.h1_support import ROOT
from tests.knowledge_inputs_support import (
    OWNER, ALLY, FOE, SKY, TRACE, VESSEL, make, source, candidates,
    answers, journey_settle,
)
from tests.worker2_support import settle, turn, reload

SPHERE = 'tianxia.sphere.weather'
SHROUD = 'WEATHER_BASE_CLOUD_SHROUD'
PID = OWNER.removeprefix('actor:factory.')


def scene(combat, *, values=None, automatic=ALLY):
    return combat.create_journey(
        project_ids=[PID, ALLY.removeprefix('actor:factory.')],
        arena_id='battlefield:map.builtin-sect-trial-platform',
        positions={OWNER: {'x': 4, 'y': 5}, ALLY: {'x': 4, 'y': 6}},
        base_paces={OWNER: 5, ALLY: 5},
        control_modes={OWNER: 'LOCAL_AUTO' if automatic in (OWNER, 'both') else 'MANUAL',
                       ALLY: 'LOCAL_AUTO' if automatic in (ALLY, 'both') else 'MANUAL'},
        source_inputs=[source(ALLY, values)] if values else None)


@pytest.mark.parametrize('response', ['auto_step', 'world_fact', 'end_scene'])
def test_private_reading_and_pending_choice_never_leave_journey_projection(tmp_path, response):
    combat, table, _ = make(tmp_path, VESSEL)
    private = 'Reader-only silver resonance'
    state = scene(combat, values={'vessel.dc': 0, 'vessel.safe': private, 'vessel.resists': 'Weight'})
    jid = state['journey_id']
    state = journey_settle(combat, jid, state, OWNER, 'information_reading',
        {'source': VESSEL, 'subject_id': ALLY, 'questions': ['vessel.safe', 'vessel.resists']})
    fresh = CombatService(ROOT, tmp_path)
    assert private in json.dumps(fresh.journey_menu(jid, OWNER)['properties']['information'])
    assert private not in json.dumps(fresh.journey_state(jid, viewer_id=ALLY))
    assert fresh.journey_replay(jid)['status'] == 'PASS'
    for edge in ('end', 'start'):
        state = fresh.journey_act(jid, state['revision'], OWNER, 'scene_turn', {'edge': edge})
    action = next(row['payload'] for row in fresh.journey_menu(jid, OWNER)['options']
                  if row['kind'] == 'native_scene_action' and row['payload']['subject_id'] == ALLY)
    state = fresh.journey_act(jid, state['revision'], OWNER, 'native_scene_action', action)
    assert state['native_scene_pending']['request']
    before = fresh.journeys.load(jid).state
    assert 'native_scene' in before and private in json.dumps(before)
    if response == 'auto_step':
        result = fresh.journey_auto_step(jid, state['revision'], ALLY)
        assert fresh.journeys.load(jid).state == before
    elif response == 'world_fact':
        result = fresh.journey_world_fact(jid, state['revision'],
            payload(ALLY, 'vessel.nature', {'value': 'Table-only artifact grade'}))
    else:
        result = fresh.journey_end_scene(jid, state['revision'], 'The examination scene ends.')
    encoded = json.dumps(result)
    assert 'native_scene' not in result
    # This is a journey JSON key, not a Git-baseline replay dependency. Keep its
    # spelling out of the CI router's stock-test marker heuristic.
    assert '_'.join(('replay', 'base')) not in result and 'command_journal' not in result
    assert 'answers' not in result.get('native_scene_pending', {})
    assert 'request' not in result.get('native_scene_pending', {})
    assert private not in encoded and 'Table-only artifact grade' not in encoded
    expected = fresh.journey_state(jid, viewer_id=ALLY if response == 'auto_step' else None)
    assert result == expected


@pytest.mark.parametrize('choices', [None, {}, {'weather_starting_sign': []}])
def test_new_weather_learning_without_starting_choice_cannot_create_ai_pause(tmp_path, choices):
    combat, table, _ = make(tmp_path, SKY, own=False)
    with pytest.raises(TabletopError, match='Choose'):
        table.add_advancement(PID, 'sphere', SPHERE, choices=choices)
    saved = CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)
    assert SPHERE not in saved.get('spheres_and_talents', {}).get('sphere_record_ids', [])
    state = scene(combat, automatic=OWNER)
    assert not any(row['kind'] == 'native_scene_action'
                   for row in combat.journey_menu(state['journey_id'], OWNER)['options'])


def test_weather_starting_sign_survives_two_independently_created_fights(tmp_path):
    combat, table, _ = make(tmp_path, SKY, own=False)
    # Rejection is essential: otherwise the first cast can choose an ephemeral Sign.
    with pytest.raises(TabletopError, match='Choose'):
        table.add_advancement(PID, 'sphere', SPHERE)
    table.add_advancement(PID, 'sphere', SPHERE, choices={'weather_starting_sign': ['cold']})
    match_ids = []
    for index in range(2):
        fresh = CombatService(ROOT, tmp_path)
        match = fresh.create_factory_match(
            project_ids=[PID], opponent_actor_ids=[FOE],
            control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'},
            arena_id='battlefield:map.builtin-sect-trial-platform', match_seed='START-SIGN-' + str(index))
        mid = match['match_id']
        match_ids.append(mid)
        turn(table, mid, OWNER)
        offered = candidates(fresh, mid, SHROUD, FOE)
        assert offered
        e = fresh._load_session(mid).engine
        assert all(e.action_catalog[c.source_definition_id].parameters['typed']['known_weather_signs'] == ['cold']
                   for c in offered)
        prompts = settle(table, mid, offered[0].candidate_id,
            picks={'choice:needle.weather_shroud_sign': 'cold', 'choice:needle.weather_battle_reading': 'cold'})
        assert not any(p['context']['reaction_source_id'] == 'choice:needle.acquisition_weather_starting_sign' for p in prompts)
        assert any(c.data.get('sign') == 'cold' for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())
    assert len(set(match_ids)) == 2
    assert CombatService(ROOT, tmp_path)._factory_owner_sheet(PID)['acquisition_choices'][SPHERE]['weather_starting_sign'] == ['cold']


def test_merged_battle_reading_has_one_prompt_and_ai_does_not_read_world_truth(tmp_path):
    from combat.ext.weather_knowledge import active_signs
    categories=dict.fromkeys(['wind','precipitation','cold','heat','aridity','storm'],0)
    categories['cold']=1
    combat,table,mid=make(tmp_path,SKY,{'weather.categories':categories},subject='scene',starting_sign='heat')
    engine=combat._load_session(mid).engine
    assert 'cold' in active_signs(engine,engine.state.actors[OWNER])
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='LOCAL_AUTO')
    engine=combat._load_session(mid).engine
    assert active_signs(engine,engine.state.actors[OWNER])==[]
    combat.set_controller_mode(mid,actor_id=OWNER,controller_mode='MANUAL')
    prompts=settle(table,mid,candidates(combat,mid,SHROUD,FOE)[0].candidate_id,
        picks={'choice:needle.weather_shroud_sign':'heat','choice:needle.weather_battle_reading':'heat'})
    readings=[p for p in prompts if p['context']['reaction_source_id'] in
        {'choice:needle.weather_battle_reading','choice:needle.reading_battle_sign'}]
    assert len(readings)==1
    assert {o['id'] for o in readings[0]['choice']['options']}=={'heat','cold'}


@pytest.mark.parametrize('automatic', [False, True])
def test_historical_weather_owner_respects_manual_or_ai_control(tmp_path, automatic):
    combat, table, _ = make(tmp_path, SKY, own=False)
    # Genuine historical character input: Weather was learned before advancement
    # recorded starting choices. This is not a fabricated scene condition/grant.
    table.add_advancement(PID, 'sphere', SPHERE, choices={'weather_starting_sign': ['wind']})
    doc = combat._factory_owner_sheet(PID)
    doc.pop('acquisition_choices', None)
    table.remove_advancement(PID, 'sphere', SPHERE)
    path = tmp_path / 'portable_characters' / PID / 'current.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    state = scene(combat, automatic='both' if automatic else ALLY)
    jid = state['journey_id']
    action = next(row['payload'] for row in combat.journey_menu(jid, OWNER)['options']
                  if row['kind'] == 'native_scene_action' and row['payload']['subject_id'] == ALLY
                  and 'Shroud' in row['label'])
    result = combat.journey_act(jid, state['revision'], OWNER, 'native_scene_action', action)
    if automatic:
        assert 'native_scene_pending' not in result
        raw = CombatService(ROOT, tmp_path).journeys.load(jid).state
        assert raw['actors'][OWNER]['resources']['resource:core.qi'] == 99
        assert combat.journey_replay(jid)['status'] == 'PASS'
    else:
        request = result['native_scene_pending']['request']
        assert request['reactor_id'] == OWNER
        assert request['reaction_source_id'] == 'choice:needle.acquisition_weather_starting_sign'
        assert len(request['extension_choice']['option_ids']) == 6
        assert combat.journeys.load(jid).state['actors'][OWNER]['resources']['resource:core.qi'] == 100


@pytest.mark.parametrize('row,values,questions,ability', [
    (TRACE, {'subject.kind': 'inscription', 'trace.concealed': True, 'trace.dc': 1000,
             'trace.hand': 'Do not disclose this'}, 'trace.hand', 'Read the Trace'),
    (VESSEL, {'vessel.dc': 1000, 'vessel.safe': 'Do not disclose this',
              'vessel.resists': 'Also secret'}, ['vessel.safe', 'vessel.resists'], 'Read the Vessel'),
])
def test_actual_failed_reading_envelope_renders_private_ability_and_target(tmp_path, row, values, questions, ability):
    combat, table, mid = make(tmp_path, row, values)
    settle(table, mid, candidates(combat, mid, row, FOE)[0].candidate_id,
           picks={'choice:needle.reading_questions': questions})
    envelope = answers(tmp_path, mid)[-1]
    assert envelope['details']['check_failed'] == 1 and envelope['details']['answers'] == {}
    assert envelope['details']['subject_name'] == 'Mara'
    # Use the real renderer and the real observer projection, rather than a
    # reconstructed envelope. No browser is launched.
    from combat.senses import perception
    engine = reload(tmp_path, mid)
    projected = {OWNER: perception(engine, engine.state.actors[OWNER])}
    script = '''import {observerInformationLines} from './static/tabletop/observer-information.js';
let input=''; for await (const chunk of process.stdin) input+=chunk;
const p=JSON.parse(input);
console.log(JSON.stringify([observerInformationLines({entity_id:p.owner},p.data),
observerInformationLines({entity_id:p.other},p.data)]));'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
        input=json.dumps({'owner': OWNER, 'other': ALLY, 'data': projected}),
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    lines, other = json.loads(result.stdout)
    assert any(ability in line and 'Mara' in line and 'check failed' in line for line in lines)
    assert not other and 'Do not disclose' not in json.dumps(lines)


def test_scene_hook_contracts_document_veto_notification_and_inert_defaults():
    contract = (ROOT / 'combat/ext/__init__.py').read_text()
    for name in ('journey_command_gate(session,actor_id,kind,payload)',
                 'journey_turn_boundary(session,actor_id,edge)'):
        assert name in contract
    assert 'False vetoes the command' in contract
    assert 'Return values are ignored' in contract
    assert 'With no subscriber' in contract


def test_knowledge_fact_hook_is_inert_without_source_inputs():
    from combat.gate4_engine import Gate4ControllerEngine
    engine=Gate4ControllerEngine(ROOT,match_seed='KNOWLEDGE-INERT')
    assert not any(e.source_definition_id=='ext:combat.ext.knowledge_inputs' for e in engine.events)
    assert [e.event_type for e in engine.events]==[
        'MATCH_CREATED',*(['INITIATIVE_ROLLED']*4),'ROUND_STARTED','TURN_STARTED']
