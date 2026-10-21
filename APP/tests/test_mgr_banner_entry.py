"""Public synthetic admission -> native Factory table -> cold replay regression."""
import json
from pathlib import Path
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError

ROOT = Path(__file__).resolve().parents[1]
PARENT = 'tianxia.subpath.qi.calamity_banner_cultivator'
RAISE = PARENT + '.feature.raise_the_calamity_banner'
PATH = 'tianxia.path.qi_cultivation'
OWNER = 'actor:factory.banner-entry'
FOE = 'actor:factory.banner-foe'
QI = 'resource:core.qi'
ACCESS = {'kind': 'daemonic_subpath', 'basis': 'projected_imperial_standard',
          'record_id': 'owner:granted-calamity-court-transmission'}


def document(qi=3, cl=3):
    return {
        'identity': {'name': 'Standard Bearer', 'cultivation_level': cl,
                     'proficiency_bonus': 2, 'path': 'Qi Cultivation', 'key_ability': 'WIS'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2}
                          for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 10},
            'armor_class': {'base_value': 14}, 'hit_points': {'maximum': 60},
            'speed': {'walking_ft': 30}, 'technique_save_dc': 12, 'technique_attack_bonus': 4},
        'path_and_subpath': {'paths': [{'path_id': PATH, 'attainment': qi}],
                             'path_record_ids': [PATH], 'path_feature_record_ids': []}}


def setup(tmp_path, monkeypatch, *, qi=3, cl=3):
    def cold():
        return CombatService(ROOT, tmp_path)
    for pid, doc in (('banner-entry', document(qi, cl)), ('banner-foe', document())):
        target = cold().combatant_library.install_root / pid
        target.mkdir(parents=True)
        with zipfile.ZipFile(target / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    arena = {'display_name': 'Synthetic Banner Arena', 'stable_id': 'battlefield:banner-entry',
             'width_squares': 12, 'height_squares': 12, 'square_size_ft': 5,
             'starting_positions': {OWNER: {'x': 3, 'y': 3}, FOE: {'x': 8, 'y': 3}},
             'terrain_regions': []}
    monkeypatch.setattr(CombatService, 'factory_arenas', lambda self, **kw: {'scene': arena})
    return cold


def acquire(cold, **kwargs):
    return cold().acquire_source_feature('banner-entry', RAISE,
        occurrence_id=kwargs.pop('occurrence_id', 'earned:banner-cl3'),
        access_record=kwargs.pop('access', ACCESS), **kwargs)


def commit(table, mid, cid, square=None):
    answers = []
    for _ in range(12):
        menu = table.state(mid)['menu']
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], 0, answers)
        if result['status'] == 'COMMITTED':
            return result
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        answer = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt.get('choice'):
            choice = prompt['choice']
            options = choice['options']
            if prompt['context'].get('reaction_source_id') == 'choice:placement_menu.square':
                assert square is not None
                picked = [o['id'] for o in options if o['id'] in (square, 'cell:' + square + ',0')]
                assert picked, (square, options)
            else:
                picked = choice.get('preferred') or [options[0]['id']]
            answer.update(selection='USE', option_ids=picked)
        answers.append(answer)
    raise AssertionError('Unfinished native table decision')


def start(cold):
    svc = cold()
    mid = svc.create_factory_match(project_ids=['banner-entry'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, arena_id='scene',
        match_seed='BANNER-ENTRY', maximum_rounds=700)['match_id']
    table = TabletopService(svc, svc.userdata_root)
    for _ in range(4):
        if svc._load_session(mid).engine.state.current_actor_id == OWNER:
            return mid, table
        commit(table, mid, table.state(mid)['menu']['end_turn'])
    raise AssertionError('Owner never received a turn')


def reload(cold, mid):
    session = cold()._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    assert not [e for e in session.engine.events if e.event_type == 'GM_RIDER'
                and e.source_definition_id in (RAISE, 'ext:combat.ext.calamity_banner')]
    return session.engine


def action(engine):
    return next(a for a in engine.action_catalog.values()
                if a.owner_id == OWNER and a.parameters.get('banner_projection'))


def test_native_acquisition_raise_cold_replay_and_continuation(tmp_path, monkeypatch):
    cold = setup(tmp_path, monkeypatch, qi=3, cl=9)
    admitted = acquire(cold)
    assert admitted['combat_acquisitions'][0]['feature_id'] == RAISE
    assert cold()._factory_owner_sheet('banner-entry') == admitted
    with pytest.raises(ValueError, match='already acquired'):
        acquire(cold)
    mid, table = start(cold)
    before = reload(cold, mid)
    assert len([a for a in before.action_catalog.values()
                if a.owner_id == OWNER and a.parameters.get('banner_projection')]) == 1
    offered = [c for c in before.legal_candidates()
               if c.source_definition_id == action(before).source_definition_id]
    assert offered
    assert not any(PARENT + '.feature.' in json.dumps(a.parameters) and
                   a.parameters.get('typed', {}).get('source') != RAISE
                   for a in before.action_catalog.values())
    selected = next(c for c in offered if c.destination is not None
                    and (c.destination.x, c.destination.y, c.destination.z) == (4,4,0))
    commit(table, mid, selected.candidate_id)
    after = reload(cold, mid)
    obj, = [o for o in after.state.objects.values() if o.object_kind == 'CALAMITY_BANNER']
    assert (obj.position.x, obj.position.y) == (4, 4)
    assert (obj.ac, obj.maximum_hp, obj.current_hp) == (14, 12, 12)
    assert obj.owner_id == OWNER and obj.component['source_cl'] == 3
    assert obj.component['calamity_banner']['expires_on'] == (
        f'START_OF_SLOT_AT:{before.state.round_number + 600}:{before.state.current_slot_index}')
    assert after.state.actors[OWNER].resources[QI] == before.state.actors[OWNER].resources[QI] - 1
    assert not after.state.actors[OWNER].bonus_action_available
    assert set(after.state.actors) == {OWNER, FOE}
    saved, = [b for b in after.typed_bundle_documents if b['actor_id'] == OWNER]
    assert saved['source_acquisitions'] == admitted['combat_acquisitions']
    assert not [c for c in after.legal_candidates()
                if c.source_definition_id == action(after).source_definition_id
                and not c.metadata.get('placement_picker') and not c.metadata.get('lazy_action')]
    # A new service and table continue the current-format journal normally.
    table = TabletopService(cold(), tmp_path)
    commit(table, mid, table.state(mid)['menu']['end_turn'])
    continued = reload(cold, mid)
    assert continued.state.objects[obj.object_id].model_dump() == obj.model_dump()
    assert continued.state.actors[OWNER].resources[QI] == after.state.actors[OWNER].resources[QI]
    with pytest.raises(ValueError, match='already acquired'):
        acquire(cold, occurrence_id='earned:second-copy')


@pytest.mark.parametrize('qi,cl,access', [(2,9,ACCESS), (3,3,None),
    (3,3,{**ACCESS, 'kind':'social_accusation'}), (3,3,{**ACCESS, 'basis':'inherited_war_flag'})])
def test_invalid_admission_is_not_persisted(tmp_path, monkeypatch, qi, cl, access):
    cold = setup(tmp_path, monkeypatch, qi=qi, cl=cl)
    with pytest.raises(ValueError):
        acquire(cold, access=access)
    assert not cold()._factory_owner_sheet('banner-entry').get('combat_acquisitions')


def test_nonowner_and_occupied_or_out_of_range_placement_cost_nothing(tmp_path, monkeypatch):
    cold = setup(tmp_path, monkeypatch)
    mid, table = start(cold)
    engine = reload(cold, mid)
    assert not any(a.parameters.get('banner_projection') for a in engine.action_catalog.values())
    acquire(cold)
    mid, table = start(cold)
    engine = reload(cold, mid)
    from combat.gate2_runtime_models import Position
    from combat import ext
    offer = action(engine)
    actor = engine.state.actors[OWNER]
    balance = actor.resources[QI]
    sample = next(c for c in engine.legal_candidates() if c.source_definition_id == offer.source_definition_id)
    # Pure legality check for forged concrete positions; real table submission
    # below rejects its unknown candidate before committing any transaction.
    for point in (actor.position, engine.state.actors[FOE].position, Position(x=11,y=11)):
        candidate = sample.model_copy(update={'candidate_id': 'forged', 'destination': point})
        assert ext.any_false('candidate_allowed', engine, actor, candidate, offer)
    menu = table.state(mid)['menu']
    with pytest.raises(TabletopError) as rejected:
        table.act(mid, 'forged', menu['decision_id'], menu['state_version'], 0, [])
    assert rejected.value.code == 'TABLETOP_STALE'
    unchanged = reload(cold, mid)
    assert unchanged.state.actors[OWNER].resources[QI] == balance
    assert unchanged.state.actors[OWNER].bonus_action_available
    assert not [o for o in unchanged.state.objects.values() if o.object_kind == 'CALAMITY_BANNER']


def test_exclusive_progression_and_cross_owner_receipt_rejected(tmp_path, monkeypatch):
    cold = setup(tmp_path, monkeypatch)
    admitted = acquire(cold)
    from combat.source_acquisition import acquired_feature_ids
    other = json.loads(json.dumps(admitted))
    other['path_and_subpath']['subpath_record_id'] = 'tianxia.subpath.qi.storm_soul_cultivator'
    with pytest.raises(ValueError, match='Another Subpath'):
        acquired_feature_ids(other, actor_id=OWNER)
    with pytest.raises(ValueError, match='another creature'):
        acquired_feature_ids(admitted, actor_id=FOE)
    # Ownership is not a resource reset path, even during an active encounter.
    mid, table = start(cold)
    engine = reload(cold, mid)
    offer = next(c for c in engine.legal_candidates()
                 if c.source_definition_id == action(engine).source_definition_id)
    commit(table, mid, offer.candidate_id)
    paid = reload(cold, mid)
    with pytest.raises(ValueError, match='already acquired'):
        acquire(cold, occurrence_id='another:receipt')
    assert reload(cold, mid).state.model_dump() == paid.state.model_dump()
