"""A manual Ask-me Initiative reaction is resolved once before the first turn."""
import json
import pathlib
import shutil
import sys
import zipfile

import pytest

APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.factory_compiler import compile_character

INPUT = pathlib.Path('/var/tmp/auto-audit/astra/lock3-inputs/portable_characters')
PID = '8a8d2bb6-4d6a-4623-8de5-498bf11d1be1'
BELL = 'tianxia.talent.music.bell_of_warning'


@pytest.mark.parametrize('held_back', [False, True])
def test_held_initiative_row_does_not_queue_empty_setup(held_back):
    """Holding a reaction disables its setup work as well as its execution."""
    from types import SimpleNamespace
    from combat.ext.ask_initiative import ask_initiative_tasks
    engine = SimpleNamespace(typed_reaction_rows={'owner': [{
        'block': 'generic', 'kind': 'initiative', 'feature_id': BELL,
        'ask': True, 'held_back': held_back}]}, _roster_setup={})
    assert ask_initiative_tasks(engine) == (None if held_back else [
        {'actor_id': 'owner', 'source_id': BELL}])


@pytest.mark.parametrize('selection', ['USE', 'DECLINE'])
def test_manual_ask_bell_is_once_and_survives_commit_reload(selection, tmp_path):
    peers = []
    for path in sorted(INPUT.glob('*/current.zip')):
        with zipfile.ZipFile(path) as archive:
            doc = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
        if int(doc['identity'].get('cultivation_level', 1)) == 5 and path.parent.name != PID:
            peers.append(path.parent.name)
    ids = [PID, *peers[:3]]
    for project_id in ids:
        dest = tmp_path / 'portable_characters' / project_id
        dest.mkdir(parents=True)
        shutil.copy2(INPUT / project_id / 'current.zip', dest / 'current.zip')
    with zipfile.ZipFile(INPUT / PID / 'current.zip') as archive:
        doc = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PID, {'mode': 'ask'}, set())
    svc = CombatService(APP, tmp_path)
    table = TabletopService(svc, tmp_path)
    me = 'actor:factory.' + PID
    bundle = compile_character(doc, actor_id=me, reaction_plan={'mode': 'ask'})
    mid = svc.create_factory_match(project_ids=ids[:2], opponent_actor_ids=['actor:factory.' + p for p in ids[2:]],
                                   control_modes={me: 'MANUAL'}, prefight={p: [] for p in ids},
                                   match_seed='H37-BELL-' + selection, maximum_rounds=100)['match_id']

    session = svc._load_session(mid)
    actor = session.engine.state.actors[me]
    bell_rows = [row for row in session.engine.typed_reaction_rows[me] if row['feature_id'] == BELL]
    assert bell_rows and all(row['ask'] for row in bell_rows)
    assert session.engine.state.setup_tasks
    assert actor.reaction_available
    assert not any(event.source_definition_id == BELL for event in session.engine.events)
    cost = next(cost for cost in bell_rows[0]['costs'] if cost.get('amount'))
    resource_id = cost['resource_id']
    assert resource_id == 'resource:core.resonance' and cost['amount'] == 1
    initial_resource = actor.resources[resource_id]
    name = actor.display_name

    answers = []
    bell_prompts = []
    for _ in range(20):
        state = table.state(mid)
        menu = state['menu']
        if menu.get('manual'):
            candidate = next((option['candidate_id'] for group in menu['actions'] for option in group['options']), None)
            candidate = candidate or menu.get('end_turn')
            response = table.act(mid, candidate, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        else:
            response = table.auto_step(mid, state['last_sequence'], answers)
        if response['status'] != 'REACTION_REQUIRED':
            break
        prompt = response['reaction']
        assert prompt['context']['reactor_id'] == me
        if prompt['reaction'] == 'Bell of Warning':
            bell_prompts.append(prompt)
            assert 'initiative' in prompt['moment'].lower()
            assert name in prompt['moment']
            choice = selection
        else:
            choice = 'DECLINE'
        answer = {**prompt['context'], 'selection': choice}
        if choice == 'USE' and prompt.get('choice'):
            options = prompt['choice']['options']
            answer['option_ids'] = [option['id'] for option in options[:max(1, int(prompt['choice'].get('minimum', 1)))]]
        answers.append(answer)
        assert not any(event.source_definition_id == BELL for event in svc._load_session(mid).engine.events)
    assert response['status'] == 'COMMITTED'
    assert len(bell_prompts) == 1

    saved = svc._load_session(mid)
    reloaded = CombatService(APP, svc.userdata_root)._load_session(mid)
    assert saved.engine.state.model_dump(mode='json') == reloaded.engine.state.model_dump(mode='json')
    assert saved.engine.state.setup_tasks == ()
    assert saved.engine.state.actors[me].turn_flags['once_per_turn:_round_initiative_checkpoint_handled'] == 0
    handled = [e for e in saved.engine.events if e.event_type == 'ONCE_PER_TURN_CLAIMED'
               and e.actor_id == me and e.payload.get('scope') == '_round_initiative_checkpoint_handled']
    assert len(handled) == 1 and handled[0].payload['turns_started'] == 0
    resolved = [e for e in saved.engine.events if e.source_definition_id == BELL and e.event_type == 'REACTION_RESOLVED']
    assert len(resolved) == int(selection == 'USE')
    assert saved.engine.state.actors[me].resources[resource_id] == initial_resource - int(selection == 'USE')
    if selection == 'DECLINE':
        assert saved.engine.state.actors[me].reaction_available
    assert reloaded.verify()['status'] == reloaded.mechanical.replay()['status'] == 'PASS'


def test_ai_control_does_not_queue_saved_ask_preference(tmp_path):
    """A saved Ask me row is automatic when its owner is AI-controlled at fight setup."""
    with zipfile.ZipFile(INPUT / PID / 'current.zip') as archive:
        doc = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(PID, {'mode': 'ask'}, set())
    ids = [PID]
    peers = [p.parent.name for p in sorted(INPUT.glob('*/current.zip')) if p.parent.name != PID][:1]
    ids += peers
    for project_id in ids:
        dest = tmp_path / 'portable_characters' / project_id
        dest.mkdir(parents=True)
        shutil.copy2(INPUT / project_id / 'current.zip', dest / 'current.zip')
    me = 'actor:factory.' + PID
    svc = CombatService(APP, tmp_path)
    mid = svc.create_factory_match(project_ids=[PID], opponent_actor_ids=['actor:factory.' + peers[0]],
                                   control_modes={me: 'LOCAL_AUTO'}, prefight={p: [] for p in ids},
                                   match_seed='H37-BELL-AI', maximum_rounds=100)['match_id']
    loaded = svc._load_session(mid)
    assert any(row['feature_id'] == BELL and row['ask'] for row in loaded.engine.typed_reaction_rows[me])
    assert not loaded.engine.state.setup_tasks
    assert any(event.event_type == 'TURN_STARTED' for event in loaded.engine.events)
    assert not any(event.event_type == 'FIGHT_SETUP_COMPLETED' for event in loaded.engine.events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
