"""Shield review regressions through compiled fights and real triggering actions."""
import pytest

from combat import armour, carry, falling
from combat.gate2_runtime_models import ActionIntent
from tests.test_auto55_shield import (
    ME, THEM, TS, _fight, _act, _answers, _stab, _answered, _conds,
)
from tests.test_auto_lane4 import _script
from tests.test_auto55_shield import ROOT, _sheet


@pytest.mark.parametrize('choice', ['catch', 'intact', 'cracked'])
def test_drop_recovers_item_for_every_unbroken_result(monkeypatch, choice):
    _answers(monkeypatch, 'shield_uncbroken', unbroken_rim=[choice])
    engine = _fight(['TAL_SHIELD_UNBROKEN_RIM'])
    me = engine.state.actors[ME]
    focus = me.resources['resource:core.martial_focus']
    _act(engine, 'Drop Shield')
    assert not carry.lost_to_another_hand(me, armour.shield_item_key(engine, me))
    assert me.resources['resource:core.martial_focus'] == focus - 1
    assert ('condition:typed.shield_cracked' in _conds(me)) == (choice == 'cracked')
    assert not any(e.event_type == 'GM_RIDER' and 'dictionary changed size' in str(e.payload) for e in engine.events)


def test_dropped_shield_cannot_answer_active_defense():
    engine = _fight(['TAL_SHIELD_GUARDED_STANCE'])
    _act(engine, 'Drop Shield')
    assert any('guarded_stance' in c.source_definition_id for c in engine.legal_candidates())
    _script(engine, [5])
    assert not _answered(_stab(engine), 'SHIELD_BASE_ACTIVE_DEFENSE')


@pytest.mark.parametrize('focus', [0, 1])
def test_incarnation_free_defense_never_charges_focus(focus):
    engine = _fight(['TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION', TS + 'projected_shield_face'], cl=16)
    _act(engine, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    me = engine.state.actors[ME]
    me.reaction_available = False
    me.resources['resource:core.martial_focus'] = focus
    me.armor_class = 60
    _script(engine, [5])
    assert _answered(_stab(engine), 'SHIELD_BASE_ACTIVE_DEFENSE')
    assert me.resources['resource:core.martial_focus'] == focus


@pytest.mark.parametrize('interposing', [False, True])
def test_incarnation_reduces_damage_before_resistance(interposing):
    engine = _fight(['TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION', TS + 'projected_shield_face']
                    + (['TAL_SHIELD_INTERPOSING_SHIELD'] if interposing else []), cl=16)
    _act(engine, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    me = engine.state.actors[ME]
    # The dagger chooses between Piercing and Slashing to avoid Resistance.
    # Resist both so the actual attack exercises the ordering under test.
    for kind in ('PIERCING', 'SLASHING'):
        engine._add_modifier(me, 'test:ward', 'damage_resistance', 'SET', kind, 'ALL', expires_on='UNTIL_REMOVED')
    hp = me.current_hp
    _script(engine, [19, 19, 4])
    events = _stab(engine)
    assert _answered(events, 'SHIELD_BASE_ACTIVE_DEFENSE')
    roll = next(e for e in events if e.event_type == 'DAMAGE_ROLLED')
    assert next(e for e in events if e.event_type == 'DAMAGE_COMMITTED').payload['damage_type'] in {'PIERCING', 'SLASHING'}
    assert me.current_hp == hp - max(0, roll.payload['total'] - me.proficiency_bonus) // 2


def test_falling_star_requires_skating_for_real_fall():
    engine = _fight(['TAL_SHIELD_RIDING_THE_FALLING_STAR'], cl=10)
    me = engine.state.actors[ME]
    hp = me.current_hp
    me.position = me.position.model_copy(update={'z': 4})
    _script(engine, [6, 6])
    falling.settle(engine)
    assert me.position.z == 0 and me.current_hp == hp - 12
    assert 'condition:typed.prone' in _conds(me)


def test_skating_keeps_shield_ac_after_movement():
    engine = _fight(['TAL_SHIELD_SHIELD_SKATE'])
    me = engine.state.actors[ME]
    _act(engine, 'SHIELD SKATE')
    assert me.armor_class + engine._ac_modifier(me) == 18


def test_incarnation_cover_ally_needs_line_of_effect_even_when_ally_is_visible(monkeypatch):
    from combat import stealth, typed_reactions
    from tests.test_auto55_shield import ALLY
    engine = _fight(['TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION', TS + 'projected_shield_face'],
                    cl=16, ally_at=(14, 6))
    _act(engine, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    row = next(r for r in typed_reactions._rows(engine, ME, 'generic') if r['feature_id'] == 'TAL_SHIELD_COVER_ALLY')
    monkeypatch.setattr(stealth, 'sees', lambda *a: True)
    engine.grid.blocked.update((8, y) for y in range(engine.grid.height))
    assert not typed_reactions._generic_in_range(engine, engine.state.actors[ME], engine.state.actors[ALLY], row)


def test_unbroken_can_decline_payment(monkeypatch):
    from combat.ext import shield_uncbroken
    calls = []
    def decline(*args, **kwargs):
        calls.append(kwargs)
        return []
    monkeypatch.setattr(shield_uncbroken, 'ask', decline)
    engine = _fight(['TAL_SHIELD_UNBROKEN_RIM'])
    me = engine.state.actors[ME]
    focus = me.resources[shield_uncbroken.FOCUS]
    _act(engine, 'Drop Shield')
    assert calls and calls[0]['allow_decline'] is True
    assert me.resources[shield_uncbroken.FOCUS] == focus
    assert carry.lost_to_another_hand(me, armour.shield_item_key(engine, me))


def test_unbroken_has_one_compile_provider():
    engine = _fight(['TAL_SHIELD_UNBROKEN_RIM'])
    assert len([r for r in engine.typed_passive_rows[ME] if r.get('kind') == 'unbroken_rim']) == 1


def test_never_falls_destruction_default_suppresses_instead_of_claiming_hp(monkeypatch):
    from combat.typed_executor import run_effects
    # An actual typed condition attempt uses the same prevention transport as Sacrificial Shield.
    engine = _fight(['TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS'], cl=16)
    me = engine.state.actors[ME]
    from combat import typed_reactions
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get('feature_id') == 'TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS')
    ctx = typed_reactions.triggered_context(engine, me, me, row)
    run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken', 'applies_to': 'self', 'duration': 'special'}])
    assert 'condition:typed.shield_broken' not in _conds(me)
    assert 'condition:typed.shield_destruction_suppressed' in _conds(me)


def test_two_rescue_abilities_do_not_both_spend_on_one_break(monkeypatch):
    from combat import typed_reactions
    from combat.typed_executor import run_effects
    _answers(monkeypatch, 'shield_incarnation', shield_soul_never_falls=['destruction'])
    _answers(monkeypatch, 'shield_uncbroken', unbroken_rim=['intact'])
    engine = _fight(['TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS', 'TAL_SHIELD_UNBROKEN_RIM'], cl=16)
    me = engine.state.actors[ME]
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get('feature_id') == 'TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS')
    ctx = typed_reactions.triggered_context(engine, me, me, row)
    run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken', 'applies_to': 'self', 'duration': 'special'}])
    assert 'condition:typed.shield_broken' not in _conds(me)
    assert me.resources['resource:core.martial_focus'] == 1



def table_match(tmp_path, talents, *, foe_talents=(), cl=16, map_terrain=None, hp=None, strength=None):
    """Install synthetic sheets and create a real persisted table, never touch live data."""
    import json
    import zipfile
    import copy
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_riders_lane9 import _sheet as plain

    docs = copy.deepcopy([_sheet(talents, cl=cl), plain(list(foe_talents), cl, 60)])
    if hp is not None:
        docs[0]['ability_scores_and_statistics']['hit_points']['maximum'] = hp
    if strength is not None:
        for row in docs[0]['ability_scores_and_statistics']['abilities']:
            if row['ability'] == 'STR':
                row.update(score=strength, modifier=(strength - 10) // 2)
    ids = [ME, THEM]
    for aid, doc in zip(ids, docs):
        doc['identity']['display_name'] = 'Shield Bearer' if aid == ME else 'Attacker'
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in zip(ids, docs)]
    service = CombatService(ROOT, tmp_path)
    table = TabletopService(service, tmp_path)
    arena = service.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena']
    if map_terrain is not None:
        arena = {**arena, 'map_terrain': map_terrain}
    mid = service._finish_factory_match(bundles, ids, {ME: 'team:a', THEM: 'team:b'},
            {ME: {'x': 3, 'y': 6}, THEM: {'x': 4, 'y': 6}}, arena,
            ['auto55_shield'], [THEM], control_modes={ME: 'MANUAL', THEM: 'MANUAL'},
            match_seed='SHIELD-R1-TABLE', display_name='Shield regressions', maximum_rounds=8)['match_id']
    while table.state(mid)['menu']['actor_id'] != ME:
        table_action(table, mid, 'end')
    return service, table, mid


def table_action(table, mid, name, answers=()):
    state = table.state(mid)
    menu = state['menu']
    if name == 'end':
        cid = menu['end_turn']
    else:
        group = next(g for g in menu['actions'] if g['label'] == name)
        cid = group['options'][0]['candidate_id']
    return table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], list(answers))


def reload(service, mid):
    from combat.gate5_service import CombatService
    old = service._load_session(mid)
    fresh = CombatService(ROOT, service.userdata_root)
    session = fresh._load_session(mid)
    assert session.engine.state.model_dump(mode='json') == old.engine.state.model_dump(mode='json')
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return fresh


@pytest.mark.parametrize('choice', ['catch', 'intact', 'cracked', None])
def test_table_drop_choice_is_optional_and_survives_reload(tmp_path, choice):
    service, table, mid = table_match(tmp_path, ['TAL_SHIELD_UNBROKEN_RIM'])
    before = service._load_session(mid).engine.state.model_dump(mode='json')
    result = table_action(table, mid, 'Drop Shield')
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert 'Unbroken Rim' in prompt['trigger']
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    response = {**prompt['context'], 'selection': 'USE' if choice else 'DECLINE', 'option_ids': [choice] if choice else []}
    result = table_action(table, mid, 'Drop Shield', [response])
    assert result['status'] == 'COMMITTED', result
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    me = engine.state.actors[ME]
    assert bool(carry.lost_to_another_hand(me, armour.shield_item_key(engine, me))) == (choice is None)
    assert me.resources['resource:core.martial_focus'] == (0 if choice else 1)
    assert not any('dictionary changed size' in str(e.payload) for e in engine.events)


def test_unbroken_allows_a_second_loss_in_the_same_round(monkeypatch):
    _answers(monkeypatch, 'shield_uncbroken', unbroken_rim=['catch'])
    engine = _fight(['TAL_SHIELD_UNBROKEN_RIM'])
    me = engine.state.actors[ME]
    _act(engine, 'Drop Shield')
    engine._gain_resource(me, 'resource:core.martial_focus', 1, 'test:regain')
    _act(engine, 'Drop Shield')
    assert not carry.lost_to_another_hand(me, armour.shield_item_key(engine, me))
    assert me.resources['resource:core.martial_focus'] == 0


@pytest.mark.parametrize('first', ['hp', 'destruction'])
def test_never_falls_uses_one_persisted_counter_for_both_triggers(monkeypatch, first):
    from combat import typed_reactions
    from combat.typed_executor import run_effects
    _answers(monkeypatch, 'shield_incarnation', shield_soul_never_falls=['one_hp' if first == 'hp' else 'destruction'])
    engine = _fight(['TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS'], cl=16)
    me = engine.state.actors[ME]
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get('feature_id') == 'TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS')
    ctx = typed_reactions.triggered_context(engine, me, me, row)
    broken = [{'type': 'condition', 'condition': 'shield_broken', 'applies_to': 'self', 'duration': 'special'}]
    if first == 'hp':
        engine._commit_damage(me, me.current_hp + 10, 'SLASHING', 'test:lethal', THEM, None, reaction_depth=0)
        assert me.current_hp == 1
        run_effects(ctx, broken)
        assert 'condition:typed.shield_broken' in _conds(me)
    else:
        run_effects(ctx, broken)
        assert 'condition:typed.shield_broken' not in _conds(me)
        engine._commit_damage(me, me.current_hp + 10, 'SLASHING', 'test:lethal', THEM, None, reaction_depth=0)
        assert me.current_hp == 0


def test_suppressed_destruction_resumes_at_the_end_of_next_holder_turn():
    from tests.test_formations import _turn
    from combat import typed_reactions
    from combat.typed_executor import run_effects
    engine = _fight(['TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS'], cl=16)
    me = engine.state.actors[ME]
    row = next(r for r in engine.typed_reaction_rows[ME] if r.get('feature_id') == 'TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS')
    ctx = typed_reactions.triggered_context(engine, me, me, row)
    run_effects(ctx, [{'type': 'condition', 'condition': 'shield_broken', 'applies_to': 'self', 'duration': 'special'}])
    assert 'condition:typed.shield_destruction_suppressed' in _conds(me)
    _turn(engine, THEM)
    _turn(engine, ME)
    assert 'condition:typed.shield_broken' not in _conds(me)
    candidate = next(c for c in engine.legal_candidates() if c.kind.value == 'END_TURN')
    engine.execute_intent(ActionIntent(intent_id='end', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME))
    assert 'condition:typed.shield_destruction_suppressed' not in _conds(me)
    assert 'condition:typed.shield_broken' in _conds(me)


def test_incarnation_recovery_remains_used_after_owner_turn_starts():
    from tests.test_formations import _turn
    from combat.ext import shield_incarnation
    engine = _fight(['TAL_SHIELD_SOVEREIGN_SHIELD_SOUL_INCARNATION', TS + 'projected_shield_face'], cl=16)
    _act(engine, 'SOVEREIGN SHIELD-SOUL INCARNATION')
    me = engine.state.actors[ME]
    me.resources[shield_incarnation.FOCUS] = 0
    _turn(engine, THEM)
    _script(engine, [16, 16])  # +2 attack: hits AC18, misses Active Defense AC20
    _act(engine, 'Bi Shou (Dagger) attack', ME, actor=THEM)
    assert me.resources[shield_incarnation.FOCUS] == 1
    _turn(engine, ME)
    assert me.turn_flags.get(shield_incarnation.ROUND) == engine.state.round_number
    me.resources[shield_incarnation.FOCUS] = 0
    _turn(engine, THEM)
    _script(engine, [16, 16])
    _act(engine, 'Bi Shou (Dagger) attack', ME, actor=THEM)
    assert me.resources[shield_incarnation.FOCUS] == 0


@pytest.mark.parametrize('star', [False, True])
def test_table_skating_terrain_permissions_survive_reload(tmp_path, star):
    talents = ['TAL_SHIELD_SHIELD_SKATE'] + (['TAL_SHIELD_RIDING_THE_FALLING_STAR'] if star else [])
    service, table, mid = table_match(tmp_path, talents, map_terrain=[{'terrain': 'loose rubble', 'cells': [[3, 5]]}])
    assert table_action(table, mid, 'SHIELD SKATE')['status'] == 'COMMITTED'
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    from combat import zones
    # The native engine at this base skips map terrain unless another TYPED zone
    # exists (a locked caller defect). Verify the actual persisted terrain
    # consumer here; the magical-zone movement regression below exercises MOVE.
    assert ((3, 5) in zones.difficult_cells(engine, engine.state.actors[ME])) == (not star)


def test_magical_loose_ground_keeps_its_movement_cost_even_overlapping_map_ground():
    from combat.gate2_runtime_models import Position, ZoneState
    engine = _fight(['TAL_SHIELD_SHIELD_SKATE', 'TAL_SHIELD_RIDING_THE_FALLING_STAR'])
    _act(engine, 'SHIELD SKATE')
    cell = Position(x=3, y=5)
    for owner, zid in [(THEM, 'spell'), ('system:map', 'map')]:
        from combat import zones
        zone = ZoneState(zone_id=zid, source_definition_id='test:sand', owner_id=owner if zid == 'spell' else zones.MAP_OWNER,
                         center=cell, radius_cells=0, affected_cells=(cell,), concentration_link=False,
                         created_round=engine.state.round_number,
                         trigger_profile={'kind': 'TYPED', 'difficult': 'all', 'visual': {'material': 'sand'}})
        engine.state.zones[zid] = zone
    move = next(c for c in engine.legal_candidates() if c.destination == cell and c.kind.value == 'MOVE')
    assert move.movement_cost_ft == 10


def test_real_table_jump_fall_asks_for_immediate_landing_move_and_reloads(tmp_path):
    service, table, mid = table_match(tmp_path,
            ['TAL_SHIELD_SHIELD_SKATE', 'TAL_SHIELD_RIDING_THE_FALLING_STAR'], strength=50)
    assert table_action(table, mid, 'SHIELD SKATE')['status'] == 'COMMITTED'
    state = table.state(mid)
    engine = service._load_session(mid).engine
    jump = next(c for c in engine.legal_candidates() if c.destination is not None
                and c.kind.value == 'MOVE' and c.destination.z == 4
                and (c.destination.x, c.destination.y) == (3, 4))
    menu = state['menu']
    answers, landing = [], False
    for _ in range(8):
        result = table.act(mid, jump.candidate_id, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        is_landing = 'falling_star_landing' in prompt['context']['reaction_source_id']
        if is_landing:
            assert 'Riding the Falling Star' in prompt['trigger'] and '20 feet' in prompt['trigger']
            landing = True
        answers.append({**prompt['context'], 'selection': 'USE' if is_landing else 'DECLINE',
                        'option_ids': ['cell:3,5'] if is_landing else []})
    else:
        raise AssertionError('jump did not finish')
    assert landing
    service = reload(service, mid)
    actor = service._load_session(mid).engine.state.actors[ME]
    assert (actor.position.x, actor.position.y, actor.position.z) == (3, 5, 0)
    assert actor.current_hp == actor.maximum_hp
    assert 'condition:typed.prone' not in _conds(actor)
    assert not actor.turn_flags.get('flight_typed_dashes')




@pytest.mark.parametrize('lost', ['taken', 'broken', 'legacy'])
def test_possession_gate_uses_recorded_state_and_legacy_bonus(lost):
    engine = _fight([])
    me = engine.state.actors[ME]
    if lost == 'taken':
        key = armour.shield_item_key(engine, me)
        engine._apply_condition(me, carry.DROPPED, 'test:take', THEM, expires_on='UNTIL_REMOVED',
                                data={'item_key': key, 'held_by': THEM})
    elif lost == 'broken':
        engine._apply_condition(me, armour.BROKEN_SHIELD, 'test:break', THEM, expires_on='UNTIL_REMOVED')
    else:
        # A sealed old bundle that still records the Shield bonus but no inventory marker.
        for bundle in engine.typed_bundle_documents:
            if bundle.get('actor_id') == ME:
                for item in bundle.get('carrying', {}).get('items', []):
                    item.pop('shield', None)
        assert armour.shield_item_key(engine, me) is None
    _script(engine, [5])
    assert _answered(_stab(engine), 'SHIELD_BASE_ACTIVE_DEFENSE') == (lost == 'legacy')


@pytest.mark.parametrize('state', ['released', 'broken', 'taken'])
def test_orbiting_exception_requires_a_usable_unstolen_shield(state):
    engine = _fight(['TAL_SHIELD_ORBITING_SHIELD_DISC'])
    _act(engine, 'ORBITING SHIELD DISC')
    me = engine.state.actors[ME]
    if state == 'broken':
        engine._apply_condition(me, armour.BROKEN_SHIELD, 'test:break', THEM, expires_on='UNTIL_REMOVED')
    else:
        data = {'item_key': armour.shield_item_key(engine, me), 'dropped_at': me.position.model_dump(mode='json')}
        if state == 'taken':
            data['held_by'] = THEM
        engine._apply_condition(me, carry.DROPPED, 'test:release', ME, expires_on='UNTIL_REMOVED', data=data)
    assert me.armor_class + engine._ac_modifier(me) == (18 if state == 'released' else 16)
    _script(engine, [5])
    assert _answered(_stab(engine), 'SHIELD_BASE_ACTIVE_DEFENSE') == (state == 'released')



@pytest.mark.parametrize('foe_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_never_falls_player_choice_on_other_turn_commits_and_reloads(tmp_path, monkeypatch, foe_mode):
    from tests.test_lock_choices import install
    from combat.tabletop_service import TabletopService
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:hit', 'operation': 'replace', 'natural_result': 20})
    service, table, mid = table_match(tmp_path, ['TAL_SHIELD_SHIELD_SOUL_NEVER_FALLS'], hp=1)
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    service.set_controller_mode(mid, actor_id=THEM, controller_mode=foe_mode)
    answers = []
    prompts = []
    for _ in range(16):
        if foe_mode == 'MANUAL':
            state = table.state(mid)
            attack = next(g['label'] for g in state['menu']['actions'] if 'attack' in g['label'].lower())
            result = table_action(table, mid, attack, answers)
        else:
            result = table.auto_step(mid, 0, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        prompt = result['reaction']
        prompts.append(prompt)
        source = prompt['context']['reaction_source_id']
        if 'shield_soul_never_falls' in source:
            assert 'Shield Soul Never Falls' in prompt['trigger']
            assert 'Shield Bearer' in prompt['trigger']
            selection, options = 'USE', ['one_hp']
        else:
            selection, options = 'DECLINE', []
        answers.append({**prompt['context'], 'selection': selection, 'option_ids': options})
    else:
        raise AssertionError('action did not finish')
    assert any('shield_soul_never_falls' in p['context']['reaction_source_id'] for p in prompts)
    service = reload(service, mid)
    engine = service._load_session(mid).engine
    me = engine.state.actors[ME]
    assert me.current_hp == 1
    from combat.ext.shield_incarnation import available
    assert not available(engine, me)


@pytest.mark.parametrize('foe_mode', ['MANUAL', 'LOCAL_AUTO'])
def test_actual_sacrificial_break_asks_unbroken_owner_on_other_turn(tmp_path, monkeypatch, foe_mode):
    from tests.test_lock_choices import install
    install(monkeypatch, 'd20_result', lambda *a: {'source_id': 'test:critical', 'operation': 'replace', 'natural_result': 20})
    service, table, mid = table_match(tmp_path, ['TAL_SHIELD_UNBROKEN_RIM', TS + 'sacrificial_shield'])
    assert table_action(table, mid, 'end')['status'] == 'COMMITTED'
    service.set_controller_mode(mid, actor_id=THEM, controller_mode=foe_mode)
    answers, saw_rescue = [], False
    for _ in range(16):
        if foe_mode == 'MANUAL':
            attack = next(g['label'] for g in table.state(mid)['menu']['actions'] if 'attack' in g['label'].lower())
            result = table_action(table, mid, attack, answers)
        else:
            result = table.auto_step(mid, 0, answers)
        if result['status'] != 'REACTION_REQUIRED':
            assert result['status'] == 'COMMITTED', result
            break
        prompt = result['reaction']
        source = prompt['context']['reaction_source_id']
        if 'unbroken_rim' in source:
            assert 'Unbroken Rim' in prompt['trigger'] and 'Shield Bearer' in prompt['trigger']
            saw_rescue = True
            picked = ['intact']
        elif 'sacrificial_shield' in source:
            picked = ['break']
        elif 'active_defense_payment' in source:
            picked = ['reaction']
        elif 'SHIELD_BASE_ACTIVE_DEFENSE' in source:
            # The reviewed payment menu now travels on Active Defense itself.
            # Accept the Reaction option so Sacrificial Shield has its prerequisite.
            picked = ['reaction']
        else:
            answers.append({**prompt['context'], 'selection': 'DECLINE', 'option_ids': []})
            continue
        answers.append({**prompt['context'], 'selection': 'USE', 'option_ids': picked})
    else:
        raise AssertionError('critical hit did not finish')
    assert saw_rescue
    service = reload(service, mid)
    actor = service._load_session(mid).engine.state.actors[ME]
    assert 'condition:typed.shield_broken' not in _conds(actor)
    assert actor.resources['resource:core.martial_focus'] == 0
