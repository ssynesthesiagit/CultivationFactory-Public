"""Puppetry destination choices through the real table transaction and saved replay."""
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.ext import needle, placed
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests import test_sys_placed_effects as P
from tests.test_auto_lane1 import ROOT


@pytest.mark.parametrize('mode', ['MANUAL', 'SUGGESTED'])
def test_tug_owner_selects_nonpreferred_square_table_commit_reload(tmp_path, mode):
    owner, foe = P.ME, 'actor:factory.r3i-tug-target'
    documents = [P._sheet(P.PUPPET[3], cl=5, dc=50), P._sheet(P.PUPPET[3], cl=5)]
    documents[0]['spheres_and_talents']['learned_talent_record_ids'] = [P.PUPPET[3]]
    documents[0]['ability_scores_and_statistics']['technique_attack_bonus'] = 100
    documents[1]['spheres_and_talents'] = {}
    for document, name in zip(documents, ['Puppeteer', 'Tug Target']):
        document['identity']['display_name'] = name
        document['ability_scores_and_statistics']['hit_points']['maximum'] = 200
    bundles = [compile_character(d, actor_id=a, reaction_plan={'ask': True})
               for d, a in zip(documents, [owner, foe])]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [owner, foe], {owner: 'team:a', foe: 'team:b'},
        {owner: {'x': 3, 'y': 6}, foe: {'x': 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [owner], [foe],
        control_modes={owner: mode, foe: 'MANUAL'}, match_seed='R3I-TUG',
        display_name='R3i Tug choice', maximum_rounds=5)['match_id']

    def act(cid, answers=()):
        menu = table.state(mid)['menu']
        return table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, list(answers))

    for _ in range(2):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == owner:
            break
        assert act(menu['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    raise_it = next(c for c in engine.legal_candidates()
                    if c.display_name.startswith('Raise the Vessel') and c.destination == Position(x=4, y=7))
    from tests.auto28_puppetry_support import resolve
    resolve(lambda answers:act(raise_it.candidate_id,answers),{'choice:needle.vessel_raise_move':[]})
    assert act(table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    assert act(table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    strike = next(c for c in engine.legal_candidates()
                  if c.source_definition_id in engine.action_catalog
                  and engine.action_catalog[c.source_definition_id].display_name == 'Puppet Strike (from the vessel)' and foe in c.target_ids)
    assert act(strike.candidate_id)['status'] == 'COMMITTED'
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode='json')
    tug = next(c for c in engine.legal_candidates()
               if c.display_name == 'Tension Response: Tug the Joint' and foe in c.target_ids)
    result = act(tug.candidate_id)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == owner
    assert prompt['context']['reaction_source_id'] == 'choice:needle.vessel_tug'
    assert 'Tug the Joint' in prompt['moment'] and 'Tug Target' in prompt['moment']
    chosen = needle.cell_id(Position(x=4, y=5))
    assert chosen in {o['id'] for o in prompt['choice']['options']}
    assert act(tug.candidate_id)['reaction'] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    answer = {**prompt['context'], 'selection': 'USE', 'option_ids': [chosen]}
    assert act(tug.candidate_id, [answer])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[foe].position == Position(x=4, y=5)
    assert not any('typed.mark.tension_mark' in c.condition_id
                   for c in loaded.engine.state.actors[foe].conditions.values())
    assert len([e for e in loaded.engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                and e.actor_id == foe and e.payload.get('forced')]) == 1
    for actor in [owner, foe]:
        assert loaded.engine.state.actors[actor].movement_remaining_ft == before['actors'][actor]['movement_remaining_ft']
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_tug_automatic_owner_retains_nearest_vessel_destination(tmp_path):
    engine = P._marked_stage()
    candidate = next(c for c in engine.legal_candidates() if c.display_name == 'Tension Response: Tug the Joint')
    intent = ActionIntent(intent_id='r3i-auto-tug', actor_id=candidate.actor_id,
        decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
        state_version=candidate.state_version, target_ids=candidate.target_ids)
    before = canonical_sha256(engine.state.model_dump(mode='json'))
    service = CombatService(ROOT, tmp_path)
    result = service._run_preview(SimpleNamespace(engine=engine, match_id=engine.state.match_id),
        {'participant_control_modes': {a: 'LOCAL_AUTO' for a in engine.state.actors}}, intent, ())
    moves = [e for e in result['events'] if e['event_type'] == 'MOVEMENT_COMMITTED' and e['actor_id'] == P.AN]
    assert len(moves) == 1 and moves[0]['payload']['destination'] == {'x': 5, 'y': 6}
    assert canonical_sha256(engine.state.model_dump(mode='json')) == before


def test_tug_large_target_options_respect_whole_footprint():
    from tests.test_riders_lane3 import _grow

    engine = P._marked_stage()
    target = engine.state.actors[P.AN]
    _grow(engine, actor_id=P.AN, cells=2)
    placed.reshape(engine, placed.of(engine, 'vessel')[0], cells=Position(x=3, y=8))
    # A free anchor is insufficient when the far edge overlaps another creature.
    engine.state.actors[P.ALLY].position = Position(x=6, y=6)
    offered = []

    class Provider:
        def __call__(self, context):
            from combat.gate2_runtime_models import ReactionDecision
            offered.extend(context['legal_option_ids'])
            return ReactionDecision(checkpoint=context['checkpoint'], reactor_id=context['reactor_id'],
                reaction_source_id=context['reaction_source_id'], selection='USE',
                option_ids=(offered[0],)), None

    engine.set_reaction_provider(Provider())
    P._pick(engine, 'Tension Response: Tug the Joint')
    assert offered and needle.cell_id(Position(x=5, y=6)) not in offered
    assert engine.grid.step_legal(Position(x=4, y=6), target.position,
        occupied_cells=engine._occupied_cells_except(P.AN) | {
            (z.center.x, z.center.y) for z in placed.of(engine, 'vessel')},
        footprint=engine._footprint(target))
