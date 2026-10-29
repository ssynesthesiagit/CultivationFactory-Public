"""Real nested consumers compose across player choices, commits and reloads."""
import json
import zipfile
import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.tabletop import ButtonStore
from combat import ext
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.r10_fixup_support import cast_sender, commit
from combat.ext.daemonic_riders import BLACK_SUN_STATE
from combat.ext.beastmastery_riders import PREFIX

OWNER, FOE, PARTNER = ('actor:factory.' + k for k in ('aaaaaaaa', 'ffffffff', 'bbbbbbbb'))
SUN = 'TAL_DAEMONIC_CULTIVATION_BLACK_SUN_OVER_THE_DANTIAN'
TAMER = 'TAL_BEASTMASTERY_BEAST_TAMER'
CHAINS = 'TAL_LIGHTNING_LIGHTNING_CHAINS'
CP = 'resource:core.stamina'


def install(monkeypatch, point, callback):
    """Fixture callbacks must preserve the production consumers under test."""
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, ()), callback])


def fight(monkeypatch, tmp_path, *, foe_hp=200, foe_features=(), partner_at=(7,4)):
    for pid in ('aaaaaaaa', 'ffffffff', 'bbbbbbbb'):
        features = [SUN, TAMER, CHAINS] if pid == 'aaaaaaaa' else [SUN, *(foe_features if pid == 'ffffffff' else ())]
        doc = sheet(features, cl=17, dc=50, primary='Stamina')
        doc['identity']['display_name'] = {'aaaaaaaa': 'Caster', 'ffffffff': 'Target', 'bbbbbbbb': 'Partner'}[pid]
        stats = doc['ability_scores_and_statistics']
        stats['primary_resource']['maximum'] = 200
        stats['hit_points']['maximum'] = foe_hp if pid == 'ffffffff' else 200
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {SUN, TAMER, CHAINS, *foe_features})
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 10})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Nested yard', 'width_squares': 16, 'height_squares': 12,
        'walls': [], 'starts': {'team1': [[3, 4]], 'team2': [[6, 4], list(partner_at)]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[FOE, PARTNER],
        control_modes={a: 'MANUAL' for a in (OWNER, FOE, PARTNER)},
        arena_id='battlefield:map.nested-yard', match_seed='LOCK8-NESTED')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    return combat, table, mid


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def select(prompt):
    ids = {o['id'] for o in prompt.get('choice', {}).get('options', [])}
    if 'necrotic' in ids:
        return 'necrotic', True
    if 'guard' in ids:
        return 'guard', True
    if PARTNER in ids:
        return PARTNER, True
    return None, False


def hold_sender(combat, table, mid):
    state = table.state(mid)
    c = next(c for c in combat._load_session(mid).engine.legal_candidates()
             if c.source_definition_id == 'system:combat.hold_position')
    return lambda answers=(): table.act(mid, c.candidate_id, c.decision_id, c.state_version,
                                      state['last_sequence'], list(answers))


@pytest.mark.parametrize('temporary_hp', [0, 100])
def test_nested_black_sun_damage_prompts_defense_and_ends_only_owned_tame(monkeypatch, tmp_path, temporary_hp):
    from combat.ext import needle
    combat, table, mid = fight(monkeypatch, tmp_path)
    commit(cast_sender(combat, table, mid, 'Beast Tamer', target=FOE), select)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    def setup(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == OWNER:
            target = engine.state.actors[FOE]
            engine._apply_condition(target, 'condition:typed.poisoned', 'test:unrelated', PARTNER, expires_on='UNTIL_REMOVED')
            if temporary_hp:
                engine._grant_temp_hp(target, temporary_hp, 'test:temporary', PARTNER)
        elif kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == FOE:
            engine._spend_resource(engine.state.actors[FOE], CP, 1, 'test:nested-spend')
    install(monkeypatch, 'event', setup)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Black Sun Over the Dantian', target=FOE), select)
    def defend(engine, target, amount, dtype, source, *args):
        if target.entity_id != FOE or dtype != 'NECROTIC':
            return None
        choices = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, 'defend', source), target,
            needle.CHOICE + 'test_guard', ['guard'], labels={'guard': 'Halve this damage'}, allow_decline=True,
            name='Fixture defense', prompt='Target may halve this Black Sun damage, at no cost.')
        return {'amount': amount // 2} if choices else None
    install(monkeypatch, 'final_damage', defend)
    turn(table, mid, FOE)
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert any(c['condition_id'].startswith(PREFIX) for c in before['actors'][FOE]['conditions'].values())
    paused = hold_sender(combat, table, mid)()
    assert paused['status'] == 'REACTION_REQUIRED' and 'Fixture defense' in paused['reaction']['reaction']
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    commit(hold_sender(combat, table, mid), select)
    e = reload_checked(tmp_path, mid)
    target = e.state.actors[FOE]
    assert not any(c.condition_id.startswith(PREFIX) or c.condition_id == BLACK_SUN_STATE
                   or c.condition_id == 'condition:typed.charmed' for c in target.conditions.values())
    assert any(c.source_definition_id == 'test:unrelated' for c in target.conditions.values())
    hits = [ev for ev in e.events if ev.event_type == 'DAMAGE_COMMITTED' and ev.target_ids == (FOE,)]
    assert len(hits) == 1 and hits[0].payload['damage_type'] == 'NECROTIC'
    assert target.resources[CP] == before['actors'][FOE]['resources'][CP] - 1
    assert target.current_hp == (200 if temporary_hp else 200 - hits[0].payload['hp_damage'])
    assert not any('deferred' in ev.payload.get('rider', '').lower() and 'damage' in ev.payload.get('rider', '').lower() for ev in e.events)


def test_lethal_black_sun_payment_interrupts_cast_with_living_teammate(monkeypatch, tmp_path):
    combat, table, mid = fight(monkeypatch, tmp_path, foe_hp=1)
    commit(cast_sender(combat, table, mid, 'Black Sun Over the Dantian', target=FOE), select)
    turn(table, mid, FOE)
    completed = []
    install(monkeypatch, 'resolution_final', lambda engine, actor, *args: completed.append(actor.entity_id))
    before_cp = combat._load_session(mid).engine.state.actors[FOE].resources[CP]
    commit(cast_sender(combat, table, mid, 'Black Sun Over the Dantian', target=OWNER), select)
    e = reload_checked(tmp_path, mid)
    assert e.state.actors[FOE].current_hp == 0 and e.state.terminal_result is None
    assert not any(c.source_actor_id == FOE and c.condition_id == BLACK_SUN_STATE for c in e.state.actors[OWNER].conditions.values())
    assert FOE not in completed
    assert e.state.actors[FOE].resources[CP] < before_cp
    assert any('cannot finish this action' in ev.payload.get('log', '') for ev in e.events)


def test_actual_lightning_link_snap_delivers_nested_tame_ending(monkeypatch, tmp_path):
    from combat.typed_executor import mark_condition_id
    combat, table, mid = fight(monkeypatch, tmp_path)
    commit(cast_sender(combat, table, mid, 'Beast Tamer', target=PARTNER), select)
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, OWNER)
    def mark(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == OWNER:
            engine._apply_condition(engine.state.actors[FOE], mark_condition_id('Charged', OWNER), 'test:charge', OWNER,
                expires_on='UNTIL_REMOVED', data={'mark': 'Charged'})
    install(monkeypatch, 'event', mark)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    commit(cast_sender(combat, table, mid, 'Lightning Lash: Jolt + Lightning Chains', target=FOE), select)
    e = reload_checked(tmp_path, mid)
    assert any(c.condition_id == 'condition:typed.link.lightning' for c in e.state.actors[PARTNER].conditions.values())
    assert not any(c.condition_id.startswith(PREFIX) for c in e.state.actors[PARTNER].conditions.values())
    # Initial arc damage already ends Tame. Reapply via the real owned effect in
    # an event fixture to isolate the later snap callback's nested delivery.
    def retame(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == PARTNER:
            from combat.typed_executor import Context, run_effects
            action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                          and (a.parameters.get('typed') or {}).get('source') == TAMER)
            target = engine.state.actors[PARTNER]
            run_effects(Context(engine, engine.state.actors[OWNER], action, engine._active_intent,
                               action.parameters['typed'], [target], target), action.parameters['typed']['effects'])
    install(monkeypatch, 'event', retame)
    turn(table, mid, PARTNER)
    commit(hold_sender(combat, table, mid), select)
    before = combat._load_session(mid).engine.state.actors[PARTNER].current_hp
    e = combat._load_session(mid).engine
    assert any(c.condition_id.startswith(PREFIX) for c in e.state.actors[PARTNER].conditions.values())
    c = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination.x == 10 and c.destination.y == 4)
    state = table.state(mid)
    commit(lambda answers=(): table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], list(answers)), select)
    e = reload_checked(tmp_path, mid)
    target = e.state.actors[PARTNER]
    assert before - target.current_hp == 4
    assert not any(c.condition_id.startswith(PREFIX) or c.condition_id == 'condition:typed.link.lightning'
                   or c.condition_id == 'condition:typed.charmed' for c in target.conditions.values())
