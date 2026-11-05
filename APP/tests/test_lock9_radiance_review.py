"""Radiance decisions observe defended damage and final, source-aware saves."""
import json
import zipfile
import pytest
from combat import ext, typed_executor
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat.ext.radiance_rescue import FEATURE
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit

OWNER, FOE = 'actor:factory.aaaaaaaa', 'actor:factory.ffffffff'
P = 'tianxia.talent.radiance.'


def add_hook(monkeypatch, point, callback):
    ext.effects(); monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), callback])


def table(tmp_path, features, *, mode='ask', hp=100, kind='Undead'):
    for pid in ['aaaaaaaa', 'ffffffff']:
        doc = sheet(features if pid == 'aaaaaaaa' else ['SAND_BASE_SCOURING_HAND'], cl=20)
        doc['identity']['display_name'] = 'Lightkeeper' if pid == 'aaaaaaaa' else 'Grave sentinel'
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = hp if pid == 'aaaaaaaa' else 100
        if pid == 'ffffffff' and kind:
            doc['identity']['creature_type'] = kind
        folder = tmp_path / 'portable_characters' / pid; folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    ButtonStore(tmp_path / 'tabletop_buttons').save_reactions('aaaaaaaa', {'mode': mode}, set(features))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Review light yard', 'width_squares': 12, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3,4]], 'team2': [[6,4]]}})
    mid = service.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', FOE: 'MANUAL'}, arena_id='battlefield:map.review-light-yard',
        match_seed='L9-RADIANCE')['match_id']
    ui = TabletopService(service, tmp_path); turn(ui, mid, OWNER)
    return service, ui, mid


def checked(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    return loaded.engine


def hold_sender(service, ui, mid):
    state = ui.state(mid)
    c = next(c for c in service._load_session(mid).engine.legal_candidates() if c.source_definition_id == 'system:combat.hold_position')
    return lambda answers=(): ui.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], list(answers))


@pytest.mark.parametrize('mode,amount,hp,spent', [('auto',6,3,0), ('ask',6,3,0), ('ask',10,0,0), ('auto',10,1,8)])
def test_halo_reduction_precedes_morning_breath_auto_or_decline(monkeypatch, tmp_path, mode, amount, hp, spent):
    service, ui, mid = table(tmp_path, [FEATURE, P+'halo_of_the_merciful_sovereign'], mode=mode, hp=5)
    commit(cast_sender(service, ui, mid, 'Halo of the Merciful Sovereign', target=OWNER))
    e = service._load_session(mid).engine
    source = next(a.source_definition_id for a in e.action_catalog.values() if a.owner_id == FOE and 'Scouring Hand' in a.display_name)
    def hit(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            engine._commit_damage(engine.state.actors[OWNER], amount, 'FIRE', source, FOE, engine._active_intent, reaction_depth=0)
    add_hook(monkeypatch, 'event', hit)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = hold_sender(service, ui, mid)
    result = send()
    if mode == 'ask' and amount == 10:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']['prompt'] if 'prompt' in result['reaction'] else str(result['reaction'])
        assert 'Grave sentinel' in prompt and 'Scouring Hand' in prompt and '8 Cultivation Points' in prompt
        assert service._load_session(mid).engine.state.model_dump(mode='json') == before
        result = send([{**result['reaction']['context'], 'selection': 'DECLINE', 'option_ids': []}])
    elif mode == 'auto' and amount == 10:
        # Auto permits the reaction; willingness and follow-up remain a choice.
        assert result['status'] == 'REACTION_REQUIRED'
        choice = result['reaction']['choice']['options']
        option = next(o['id'] for o in choice if 'GM' in str(o))
        result = send([{**result['reaction']['context'], 'selection': 'USE', 'option_ids': [option]}])
    assert result['status'] == 'COMMITTED'
    e = checked(tmp_path, mid); a = e.state.actors[OWNER]
    assert a.current_hp == hp
    assert a.resources['resource:core.qi'] == before['actors'][OWNER]['resources']['resource:core.qi'] - spent
    if not spent:
        assert {k:v for k,v in a.resources.items() if 'resurrection_of_the_morning_breath' in k} == {
            k:v for k,v in before['actors'][OWNER]['resources'].items() if 'resurrection_of_the_morning_breath' in k}


@pytest.mark.parametrize('original,final', [(1,'success'), (20,'failure')])
def test_crown_uses_final_outcome_after_stored_rewrite(monkeypatch, tmp_path, original, final):
    service, ui, mid = table(tmp_path, [P+'crown_of_the_unblinking_sun', 'RADIANCE_BASE_STRIKE'])
    commit(cast_sender(service, ui, mid, 'Crown of the Unblinking Sun'))
    add_hook(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':original})
    def rewrite(ctx, subject, ability, named, failed):
        ctx.engine.__dict__.setdefault('_typed_roll_outcome', {})[subject.entity_id] = final
    add_hook(monkeypatch, 'after_save', rewrite)
    def save(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            a = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER and a.display_name == 'Radiance Strike')
            subject = engine.state.actors[FOE]
            ctx = typed_executor.Context(engine, engine.state.actors[OWNER], a, engine._active_intent,
                a.parameters['typed'], [subject], subject)
            typed_executor.block_save(ctx, {'type':'save','ability':'wis','applies_to':'target','on_fail':[]})
    add_hook(monkeypatch, 'event', save)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    e = checked(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.reaction_denied' for c in e.state.actors[FOE].conditions.values()) == (final == 'failure')


@pytest.mark.parametrize('kind,penalty,mode', [('Undead',False,'ADVANTAGE'), (None,False,'NORMAL'),
                                           ('Undead',True,'NORMAL'), (None,True,'DISADVANTAGE')])
def test_bell_repeat_save_keeps_original_fear_source_and_mode_cancellation(monkeypatch, tmp_path, kind, penalty, mode):
    service, ui, mid = table(tmp_path, [P+'searing_halo', 'TAL_SOUND_BELL_OF_CLARITY'], kind=kind)
    commit(cast_sender(service, ui, mid, 'Searing Halo'))
    assert act(ui, mid, 'end')['status'] == 'COMMITTED'; turn(ui, mid, OWNER)
    def fear(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            a = engine.state.actors[OWNER]
            engine._apply_condition(a, 'condition:typed.frightened', 'test:original_fear', FOE,
                expires_on='UNTIL_REMOVED', data={'origin_save': {'ability':'WIS','dc':20}})
            if penalty:
                engine._apply_condition(a, 'condition:typed.review_save_penalty', 'test:penalty', FOE,
                    expires_on='UNTIL_REMOVED', data={'rule': {'save_mode': {'WIS':'DISADVANTAGE'}}})
    add_hook(monkeypatch, 'event', fear)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    def repeat(prompt):
        assert prompt['context']['reaction_source_id'] in ('choice:repeat_save.targets', 'choice:repeat_save.effect')
        return prompt['choice']['options'][0]['id'], True
    commit(cast_sender(service, ui, mid, 'Bell of Clarity', target=OWNER), repeat)
    e = checked(tmp_path, mid)
    saves = [ev for ev in e.events if ev.event_type == 'SAVE_ROLLED' and ev.actor_id == OWNER]
    assert saves[-1].payload['mode'] == mode


@pytest.mark.parametrize('floor', [True, -1, 500])
def test_invalid_survival_floor_rolls_back_the_table_transaction(monkeypatch, tmp_path, floor):
    from combat.gate5_service import CombatServiceError
    service, ui, mid = table(tmp_path, ['SAND_BASE_SCOURING_HAND'], hp=5)
    add_hook(monkeypatch, 'lethal_damage', lambda *args: floor)
    add_hook(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':20})
    assert act(ui, mid, 'end')['status'] == 'COMMITTED'; turn(ui, mid, FOE)
    send = cast_sender(service, ui, mid, 'Scouring Hand', target=OWNER)
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    with pytest.raises(CombatServiceError, match='completed intent was rejected'):
        commit(send)
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
