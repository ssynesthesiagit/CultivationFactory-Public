"""Round 20 composition at the Table boundary.

Owner 2026-09-27: spheres, cylinders and emanations are round. A square is
included when its centre is within the radius, using altitude as a third axis.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet, ROOT
from tests.test_hidden_targeting import turn


@pytest.mark.parametrize('shape', ['sphere', 'cylinder', 'emanation'])
def test_round_area_table_commit_reload_and_replay(tmp_path, shape):
    owner = 'an_eui_early_book1_cl5'
    boundary = 'lee_jia_early_book1_cl5'
    diagonal = 'ling_qi_early_outer_sect_cl5'
    inside = 'bai_meizhen_early_outer_sect_cl5'
    bundle = compile_character(sheet([]), actor_id=owner)
    source = 'test:round20.area'
    action = ActionDefinition(source_definition_id=source, display_name='Round area marker', owner_id=owner,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='CELL', range_ft=30,
        parameters={'typed': {'source': source, 'numbers': {'cl': 15, 'pb': 5},
            'area': {'shape': shape, 'size_ft': 10},
            'effects': [{'type': 'condition', 'condition': 'poisoned', 'applies_to': 'creatures_in_area',
                         'expires_on': 'END_OF_SOURCE_NEXT_TURN'}]}})
    bundle['action_catalog'].append(action.model_dump(mode='json'))
    bundle['actor_template']['action_ids'].append(source)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)
    service = CombatService(ROOT, tmp_path)
    mid = service.persistence.create_match(match_seed='LOCK20-ROUND-'+shape, typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [owner, boundary, diagonal, inside],
                      'team_by_actor': {owner: 'a', boundary: 'b', diagonal: 'b', inside: 'b'},
                      'starting_positions': {owner: {'x': 5, 'y': 5}, boundary: {'x': 7, 'y': 5},
                                             diagonal: {'x': 7, 'y': 7}, inside: {'x': 6, 'y': 6}}}).match_id
    for actor in (owner, boundary, diagonal, inside):
        service.set_controller_mode(mid, actor_id=actor, controller_mode='MANUAL')
    table = TabletopService(service, tmp_path)
    turn(table, mid, owner)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == source
                     and c.destination == Position(x=5, y=5))
    result = table.act(mid, candidate.candidate_id, candidate.decision_id, candidate.state_version, 0, [])
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    affected = {a.entity_id for a in loaded.engine.state.actors.values()
                if any(c.source_definition_id == source for c in a.conditions.values())}
    assert {owner, boundary, inside} <= affected
    assert diagonal not in affected
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('choice', ['maximum_hp', 'Armor Class'])
def test_modify_characteristics_has_one_choice_and_one_payment(tmp_path, monkeypatch, choice):
    from combat import ext
    from combat.ext.riders14_research import KNOWN
    from combat.ext.maximum_hp_riders import FOCUS
    from tests.test_lock9_maximum_review import critical_table
    from tests.test_lock8_maximum_hp import answer
    from tests.test_lock2_persistence import act

    def learn(engine, event_type, event):
        if event_type != 'HOLD_POSITION_COMMITTED' or event.get('actor_id') != 'actor:factory.left':
            return
        actor = engine.state.actors['actor:factory.left']
        engine._apply_condition(actor, KNOWN, 'test:learn', actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'target_id': 'actor:factory.right', 'name': 'Armor Class', 'value': 20})

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), learn])
    service, table, mid, owner, target = critical_table(tmp_path, monkeypatch, known=True)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    first = act(table, mid, 'test:critical:')
    assert first['status'] == 'REACTION_REQUIRED'
    choices = {o['id'] for o in first['reaction']['choice']['options']}
    assert {'Armor Class', 'maximum_hp'} <= choices
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    result = answer(table, mid, 'test:critical:', first['reaction'], [choice])
    assert result['status'] == 'COMMITTED'  # no second overlapping prompt
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[owner].resources[FOCUS] == before['actors'][owner]['resources'][FOCUS] - 1
    victim = loaded.engine.state.actors[target]
    if choice == 'maximum_hp':
        assert victim.maximum_hp == before['actors'][target]['maximum_hp'] - 10
    else:
        assert any(m.target_field == 'armor_class' and m.value == -2 for m in victim.modifiers.values())
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
