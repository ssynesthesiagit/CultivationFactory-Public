"""Bound origins survive reaction decisions but never leak into nested sources."""
import json
import zipfile
import pytest
from combat import ext, typed_executor, typed_reactions
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import commit
from tests.test_lock8_origins import INK

OWNER, FOE, ANCHOR = ['actor:factory.' + p for p in ('aaaaaaaa','ffffffff','bbbbbbbb')]


def add_hook(monkeypatch, point, fn):
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), fn])


def table(monkeypatch, tmp_path, *, mark_foe=False):
    for pid in ('aaaaaaaa','ffffffff','bbbbbbbb'):
        doc = sheet([INK] if pid == 'aaaaaaaa' else ['SAND_BASE_SCOURING_HAND'])
        doc['identity']['display_name'] = {'aaaaaaaa':'Calligrapher','ffffffff':'Defender','bbbbbbbb':'Marked anchor'}[pid]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode':'ask'}, {INK})
    def mark(engine, event, kwargs):
        if event == 'HOLD_POSITION_COMMITTED' and kwargs.get('actor_id') == OWNER:
            marked = engine.state.actors[FOE if mark_foe else ANCHOR]
            engine._apply_condition(marked, typed_executor.mark_condition_id('ink_mark', OWNER),
                'test:prior_mark', OWNER, expires_on='UNTIL_REMOVED', data={'mark':'ink_mark'})
    add_hook(monkeypatch, 'event', mark)
    add_hook(monkeypatch, 'd20_result', lambda *args: {'source_id':'test:roll','operation':'replace','natural_result':20})
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name':'Review origin yard','width_squares':20,'height_squares':14,
        'walls':[], 'terrain':[{'type':'SIMPLE_COVER','cells':[[4,6]]}],
        'starts':{'team1':[[1,6]],'team2':[[7,6],[16,6]] if mark_foe else [[16,6],[7,6]]}})
    mid = service.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FOE,ANCHOR],
        control_modes={a:'MANUAL' for a in (OWNER,FOE,ANCHOR)},
        arena_id='battlefield:map.review-origin-yard', match_seed='L9-ORIGIN')['match_id']
    ui = TabletopService(service, tmp_path); turn(ui, mid, OWNER)
    assert act(ui, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    return service, ui, mid


def sender(service, ui, mid):
    state = ui.state(mid)
    c = next(c for c in service._load_session(mid).engine.legal_candidates()
             if c.metadata.get('effect_origin') and c.target_ids == (FOE,))
    return lambda answers=(): ui.act(mid, c.candidate_id, c.decision_id, c.state_version,
                                     state['last_sequence'], list(answers))


def checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('use_reaction', [True, False])
def test_attacked_reaction_moves_origin_without_before_attack_reply(monkeypatch, tmp_path, use_reaction):
    row = {'feature_id':'test:step','name':'Defender step','block':'generic','kind':'attacked',
           'ask':True, 'effects':[{'type':'reaction_move','direction':'toward','distance_ft':5}]}
    original = typed_reactions._rows
    def rows(engine, aid, block):
        return ([row] if aid == FOE and block == 'generic' else []) + original(engine, aid, block)
    monkeypatch.setattr(typed_reactions, '_rows', rows)
    service, ui, mid = table(monkeypatch, tmp_path, mark_foe=True)
    # This attack-declaration reaction does not use the before_attack seam.
    monkeypatch.setitem(ext._HOOKS, 'before_attack', [])
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    send = sender(service, ui, mid)
    pause = send()
    assert pause['status'] == 'REACTION_REQUIRED'
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    service = CombatService(ROOT, tmp_path); ui = TabletopService(service, tmp_path)
    send = sender(service, ui, mid)
    result = send([{**pause['reaction']['context'], 'selection':'USE' if use_reaction else 'DECLINE', 'option_ids':[]}])
    assert result['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    actor = engine.state.actors[FOE]
    if use_reaction:
        assert actor.position.model_dump(mode='json') != before['actors'][FOE]['position']
        assert actor.current_hp == before['actors'][FOE]['current_hp']
        assert any('chosen origin moved' in ev.payload.get('rider','') for ev in engine.events)
        assert not [ev for ev in engine.events if ev.event_type == 'ATTACK_ROLLED']
    else:
        assert actor.current_hp < before['actors'][FOE]['current_hp']


@pytest.mark.parametrize('reach', [60, 100])
@pytest.mark.parametrize('entry', ['effects', 'attack'])
def test_different_source_followup_uses_physical_range_and_cover(monkeypatch, tmp_path, reach, entry):
    service, ui, mid = table(monkeypatch, tmp_path)
    observed, sequence_distances = [], []
    def follow(ctx, target, kind):
        if ctx.actor.entity_id != OWNER or ctx.source == 'test:followup':
            return
        action = ActionDefinition(source_definition_id='test:followup', display_name='Follow-up bolt',
            owner_id=OWNER, economy=EconomyKind.REACTION, resolution_kind='TYPED',
            target_kind='HOSTILE_ENTITY', range_ft=reach)
        data = {'numbers':{'attack_bonus':20}, 'range_ft':reach}
        nested = typed_executor.Context(ctx.engine, ctx.actor, action, ctx.intent, data, [target], target)
        effect = {'type':'attack','attack_kind':'cultivation_ranged','on_hit':[
            {'type':'damage','dice':{'count':1,'sides':4},'damage_types':['FIRE']}]}
        if entry == 'effects':
            typed_executor.run_effects(nested, [effect])
        else:
            typed_executor.block_attack(nested, effect)
        # Returning from the follow-up must restore the outer Ink Mark.
        observed.append(ctx.engine._effect_distance(ctx.actor, target))
    add_hook(monkeypatch, 'after_hit', follow)
    def sequence(ctx):
        if ctx.source == 'test:followup':
            sequence_distances.append(ctx.engine._effect_distance(ctx.actor, ctx.target))
    add_hook(monkeypatch, 'attack_sequence_start', sequence)
    commit(sender(service, ui, mid))
    engine = checked(tmp_path, mid)
    follow_rolls = [ev for ev in engine.events if ev.event_type == 'ATTACK_ROLLED' and ev.source_definition_id == 'test:followup']
    assert len(follow_rolls) == (1 if reach == 100 else 0)
    if follow_rolls:
        assert follow_rolls[0].payload['cover_bonus'] == 2
    assert observed and all(distance == 45 for distance in observed)
    assert sequence_distances and all(distance == 75 for distance in sequence_distances)
    assert engine.state.actors[OWNER].position.x == 1
