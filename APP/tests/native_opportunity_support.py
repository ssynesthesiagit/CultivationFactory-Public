"""Shared native-opportunity table setup for LOCK13 and SOL114."""
import pytest
from combat.gate4_adapters import ManualControllerAdapter
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, sheet
from tests.test_hidden_targeting import turn

CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"


def fight(tmp_path, *, owned=True, two=False):
    doc = sheet([CM] if owned else [], cl=12, dc=30)
    doc['identity']['display_name'] = 'Watcher'
    bundle = compile_character(doc, actor_id=ME, reaction_plan={'ask': True})
    svc = CombatService(ROOT, tmp_path)
    positions = {ME: {'x': 4, 'y': 6}, AN: {'x': 5, 'y': 6}, BAI: {'x': 4, 'y': 7}}
    mid = svc.persistence.create_match(match_seed='LOCK13-NATIVE', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI] if two else [ME, AN],
                      'team_by_actor': {ME: 'a', AN: 'b', BAI: 'b'},
                      'starting_positions': positions}).match_id
    for aid in ([ME, AN, BAI] if two else [ME, AN]):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(svc, tmp_path)
    turn(table, mid, ME)
    return svc, table, mid

def move(svc, table, mid, *, auto=False, oa_use=True, counter_use=True):
    state = table.state(mid)
    before = svc._load_session(mid).engine.state.model_dump(mode='json')
    c = next(c for c in svc._load_session(mid).engine.legal_candidates()
             if c.kind == 'MOVE' and c.destination.x == 4 and c.destination.y == 4)
    if auto:
        # A supported primary-action driver chooses a legal move; production
        # reaction policy still decides every AI reactor's answers.
        production = svc.controller
        class MoveController:
            def choose_primary_action(self, context):
                selected = next(x for x in context.legal_candidates if x.candidate_id == c.candidate_id)
                return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(production, name)
        svc.controller = MoveController()
    answers, prompts = [], []
    for _ in range(12):
        response = (table.auto_step(mid, state['last_sequence'], answers) if auto else
                    table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], answers))
        if response['status'] == 'COMMITTED':
            break
        assert response['status'] == 'REACTION_REQUIRED', response
        assert svc._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = response['reaction']
        prompts.append(prompt)
        use = counter_use if prompt['reaction'] == 'Charged Countermeasure' else oa_use
        answers.append({**prompt['context'], 'selection': 'USE' if use else 'DECLINE'})
    else:
        pytest.fail('Repeated reaction prompts without commit')
    return prompts


def checked(svc, tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == svc._load_session(mid).engine.state
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine
