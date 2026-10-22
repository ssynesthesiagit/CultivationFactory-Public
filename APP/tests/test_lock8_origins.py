"""Remote-origin candidates bind geometry without moving their caster."""
import pytest
from combat import ext
from combat.action_geometry import activate, cells, point, valid
from combat.gate2_runtime_models import ActionIntent, Position
from combat.typed_executor import mark_condition_id
from tests import lock8_support as S
from tests.test_lock_choices import install

INK = 'tianxia.talent.ink.marked_origin'


def fixed_hit(monkeypatch):
    install(monkeypatch, 'd20_result', lambda *args: {'source_id': 'test:roll', 'operation': 'replace', 'natural_result': 10})


def ink_fight(*, owned=True):
    e = S.fight(S.bundle(INK if owned else 'INK_BASE_INK_LASH'), me_at=(1, 6), foe_at=(16, 6),
                ally=S.bundle('SAND_BASE_SCOURING_HAND', actor_id=S.ALLY), ally_at=(7, 6))
    e._apply_condition(e.state.actors[S.ALLY], mark_condition_id('ink_mark', S.ME), 'test:mark', S.ME,
                       expires_on='UNTIL_REMOVED', data={'mark': 'ink_mark'})
    return e


def remote(e):
    return [c for c in e.legal_candidates() if c.metadata.get('effect_origin')]


def use(e, c):
    e.execute_intent(ActionIntent(intent_id='remote-'+str(e.state.event_sequence), decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination))


def test_owned_ink_lash_reaches_from_mark_and_keeps_physical_state(monkeypatch):
    fixed_hit(monkeypatch)
    e = ink_fight()
    actor, target = e.state.actors[S.ME], e.state.actors[S.FOE]
    before = actor.position.model_copy(), actor.movement_remaining_ft, dict(actor.resources)
    c = next(c for c in remote(e) if c.target_ids == (S.FOE,))
    original = e.state.model_dump(mode='json')
    assert remote(e) and original == e.state.model_dump(mode='json')
    use(e, c)
    assert (actor.position, actor.movement_remaining_ft, actor.resources) == before
    assert target.current_hp < target.maximum_hp
    assert any(ev.payload.get('effect_origin') == c.metadata['effect_origin'] for ev in e.events)
    assert not getattr(e, '_effect_origin', None)
    assert not any(ev.event_type == 'MOVEMENT_COMMITTED' for ev in e.events)


def test_unowned_or_hidden_or_destroyed_anchor_provides_no_remote_choice():
    assert remote(ink_fight(owned=False)) == []
    e = ink_fight()
    e._apply_condition(e.state.actors[S.ALLY], 'condition:typed.invisible', 'test:hidden', S.ALLY, expires_on='UNTIL_REMOVED')
    assert not remote(e)
    e = ink_fight()
    e.state.actors[S.ALLY].active = False
    assert not remote(e)


def test_origin_rebind_changes_candidate_and_stale_choice_cannot_execute():
    e = ink_fight()
    old = remote(e)[0]
    e.state.actors[S.ALLY].position = Position(x=8, y=6)
    assert old.candidate_id not in {c.candidate_id for c in remote(e)}
    with pytest.raises(Exception):
        use(e, old)


def test_cover_and_distance_come_from_mark_and_other_attacks_do_not_inherit():
    from combat.action_geometry import attack
    e = ink_fight()
    actor, target = e.state.actors[S.ME], e.state.actors[S.FOE]
    c = remote(e)[0]
    e.grid.cover.add((4, 6))
    assert e._cover_bonus_actor_to_actor(actor, target) == 2
    with activate(e, actor, c.source_definition_id, c.metadata['effect_origin']):
        assert e._cover_bonus_actor_to_actor(actor, target) == 0
        assert e._effect_distance(actor, target) == 45
        assert e._distance_actor_to_actor(actor, target) == 75
        with attack(e, actor, 'different:reaction'):
            assert e._effect_distance(actor, target) == 75
        assert e._effect_distance(actor, target) == 45
    assert e._effect_distance(actor, target) == 75


def test_flow_line_strike_uses_actual_array_eye(monkeypatch):
    from tests import test_formations as F
    fixed_hit(monkeypatch)
    e, _ = F._engine(['tianxia.talent.formations.flow_line_strike'], foe_at=(6, 6))
    F._do(e, 'Combat Array: Killing Line (Radiant)', at=(5, 6))
    choices = [c for c in remote(e) if 'Pulse: Killing Line' in c.display_name]
    assert choices
    c = choices[0]
    assert c.metadata['effect_origin']['position'] == {'x': 5, 'y': 6}
    before = e.state.actors[F.ME].position.model_copy()
    use(e, c)
    assert e.state.actors[F.ME].position == before
    assert any(ev.event_type == 'DAMAGE_COMMITTED' and ev.payload['damage_type'] == 'RADIANT' for ev in e.events)


def test_unowned_flow_line_keeps_original_candidate_family():
    from tests import test_formations as F
    e, _ = F._engine([], foe_at=(6, 6))
    F._do(e, 'Combat Array: Killing Line (Radiant)', at=(5, 6))
    assert not remote(e)


def test_area_and_zone_geometry_use_origin_without_moving_owner():
    from combat.typed_executor import _area_targets, Context
    from combat import zones
    e = ink_fight()
    actor = e.state.actors[S.ME]
    c = remote(e)[0]
    action = e.action_catalog[c.source_definition_id]
    area = {'shape': 'line', 'size_ft': 50, 'width_ft': 5}
    aim = Position(x=16, y=6)
    assert e.state.actors[S.FOE] not in _area_targets(e, actor, aim, area)
    with activate(e, actor, action.source_definition_id, c.metadata['effect_origin']):
        assert e.state.actors[S.FOE] in _area_targets(e, actor, aim, area)
        ctx = Context(e, actor, action, None, action.parameters['typed'], [], None)
        zone = zones.create(ctx, {'name': 'Origin test', 'shape': 'sphere', 'size_ft': 5,
                                 'centered_on_self': True, 'duration': {'kind': 'one_minute'}})
        assert zone.center == Position(x=7, y=6)
        e.state.actors[S.ALLY].active = False
        assert not valid(e, actor, action)
    assert actor.position == Position(x=1, y=6)


def test_origin_scope_restores_after_error():
    e = ink_fight()
    c = remote(e)[0]
    with pytest.raises(RuntimeError):
        with activate(e, e.state.actors[S.ME], c.source_definition_id, c.metadata['effect_origin']):
            raise RuntimeError('fixture')
    assert not getattr(e, '_effect_origin', None)


def test_ordinary_native_attack_resolves_from_bound_origin(monkeypatch):
    from combat.gate2_runtime_models import DiceSpec
    fixed_hit(monkeypatch)
    e = ink_fight()
    original = next(a for a in e.action_catalog.values() if a.owner_id == S.ME
                    and a.parameters.get('typed', {}).get('source') == 'INK_BASE_INK_LASH')
    native = original.model_copy(update={'resolution_kind': 'ATTACK', 'attack_bonus': 100,
                                        'damage': DiceSpec(count=1, sides=4, modifier=2), 'damage_type': 'FORCE'})
    e.action_catalog[native.source_definition_id] = native
    c = next(c for c in remote(e) if c.target_ids == (S.FOE,))
    before = e.state.actors[S.FOE].current_hp
    use(e, c)
    assert e.state.actors[S.FOE].current_hp < before


def test_area_candidates_bind_distinct_origins_and_apply_remote_range(monkeypatch):
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    e = ink_fight(owned=False)
    source = 'test:remote-area'
    action = ActionDefinition(source_definition_id=source, display_name='Area test', owner_id=S.ME,
        economy=EconomyKind.ACTION, resolution_kind='TYPED', target_kind='CELL', range_ft=10, radius_ft=5,
        parameters={'typed': {'effects': [], 'area': {'shape': 'sphere', 'size_ft': 5},
                             'zone_spec': {'name': 'Test area'}, 'numbers': {}}})
    e.action_catalog[source] = action
    e.state.actors[S.ME].action_ids += (source,)
    install(monkeypatch, 'effect_origins', lambda engine, actor, a: [
        {'id': 'test:a', 'label': 'First anchor', 'position': {'x': 7, 'y': 6}},
        {'id': 'test:b', 'label': 'Second anchor', 'position': {'x': 8, 'y': 6}}] if a is action else None)
    candidates = [c for c in e.legal_candidates() if c.source_definition_id == source]
    distant = [c for c in candidates if c.destination == Position(x=9, y=6)]
    assert len(distant) == 2 and len({c.candidate_id for c in distant}) == 2
    assert all(c.metadata.get('effect_origin') for c in distant)
    assert e.state.actors[S.ME].position == Position(x=1, y=6)


def test_manual_remote_attack_pause_reload_and_replay(monkeypatch, tmp_path):
    import json
    import zipfile
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from combat.ext import needle
    from tests.h1_support import ROOT, sheet
    from tests.test_hidden_targeting import turn
    from tests.test_lock2_persistence import act
    from tests.r10_fixup_support import commit
    owner, foe, anchor = ['actor:factory.' + pid for pid in ('aaaaaaaa', 'ffffffff', 'bbbbbbbb')]
    for pid in ('aaaaaaaa', 'ffffffff', 'bbbbbbbb'):
        doc = sheet([INK] if pid == 'aaaaaaaa' else ['SAND_BASE_SCOURING_HAND'])
        doc['identity']['display_name'] = {'aaaaaaaa': 'Calligrapher', 'ffffffff': 'Target', 'bbbbbbbb': 'Marked fighter'}[pid]
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {INK})
    fixed_hit(monkeypatch)
    def mark(engine, kind, kwargs):
        if kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == owner:
            engine._apply_condition(engine.state.actors[anchor], mark_condition_id('ink_mark', owner),
                'test:prior-press-mark', owner, expires_on='UNTIL_REMOVED', data={'mark': 'ink_mark'})
    install(monkeypatch, 'event', mark)
    def defend(engine, target, amount, dtype, source, *args):
        if target.entity_id != foe:
            return None
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, 'origin_guard', source),
            target, needle.CHOICE + 'origin_guard', ['guard'], labels={'guard': 'Halve this Ink Lash damage'},
            name='Target defense', prompt='Target may halve this Ink Lash damage from the Ink Mark, at no cost.', allow_decline=True)
        return {'amount': amount // 2} if chosen else None
    install(monkeypatch, 'final_damage', defend)
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Origin yard', 'width_squares': 20, 'height_squares': 14,
        'walls': [], 'starts': {'team1': [[1, 6]], 'team2': [[16, 6], [7, 6]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa'], opponent_actor_ids=[foe, anchor],
        control_modes={a: 'MANUAL' for a in (owner, foe, anchor)}, arena_id='battlefield:map.origin-yard', match_seed='L8-ORIGIN')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, owner)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    def sender(answers=()):
        state = table.state(mid)
        c = next(c for c in combat._load_session(mid).engine.legal_candidates()
                 if c.metadata.get('effect_origin') and c.target_ids == (foe,))
        return table.act(mid, c.candidate_id, c.decision_id, c.state_version, state['last_sequence'], list(answers))
    before = combat._load_session(mid).engine.state.model_dump(mode='json')
    assert sender()['status'] == 'REACTION_REQUIRED'
    assert combat._load_session(mid).engine.state.model_dump(mode='json') == before
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    commit(sender, lambda prompt: ('guard', True))
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
    assert loaded.engine.state.actors[owner].position.model_dump(mode='json') == before['actors'][owner]['position']
    assert loaded.engine.state.actors[owner].resources == before['actors'][owner]['resources']
    assert loaded.engine.state.actors[foe].current_hp < before['actors'][foe]['current_hp']
    assert any(ev.payload.get('effect_origin', {}).get('id') == 'ink:' + anchor for ev in loaded.engine.events)
