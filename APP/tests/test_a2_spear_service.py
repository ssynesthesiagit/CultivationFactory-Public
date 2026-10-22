"""Spear second pass: real service casts, transactional choices and cold replay."""
import json
import zipfile

import pytest

from combat import ext
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from combat.shot_geometry import scope, reduce_cover
CONDITION = 'condition:typed.target_cover_ignored'
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act

FLOWERS = 'TAL_SPEAR_FLOWERS_IN_THE_STORM'
RAINBOW = 'TAL_SPEAR_PENETRATING_RAINBOW'
METEOR = 'TAL_SPEAR_METEOR_NET_SPEAR_ART'
IDS = {name: FACTORY_ACTOR_PREFIX + name for name in ('left', 'ally', 'foe1', 'foe2', 'foe3')}
LEFT, ALLY = IDS['left'], IDS['ally']
FOES = [IDS[n] for n in ('foe1', 'foe2', 'foe3')]
PIKE = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.mao',
                                  'name': 'Mao (Long Spear / Lance)', 'quantity': 1}]}}


def fight(tmp_path, talent, *, ai=False, one_miss=False, all_pass=False, kit=PIKE, near=False):
    for name, actor_id in IDS.items():
        document = sheet([talent] if name == 'left' else [], cl=10 if talent == METEOR else 5, dc=16, kit=kit, primary='Stamina')
        document['identity'].update(display_name=name.title(), proficiency_bonus=2)
        stats = document['ability_scores_and_statistics']
        stats['hit_points']['maximum'] = 500
        stats['technique_attack_bonus'] = 40
        stats['armor_class']['base_value'] = 100 if one_miss and name == 'foe2' else 14
        for ability in stats['abilities']:
            # The third foe passes Rainbow, the first two fail it deterministically.
            ability['score'] = 110 if (name == 'foe3' or all_pass) and name.startswith('foe') else 1 if name.startswith('foe') else 14
            ability['modifier'] = (ability['score'] - 10) // 2
        folder = tmp_path / 'portable_characters' / name
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({'display_name': 'Spear second yard', 'width_squares': 16, 'height_squares': 10,
        'walls': [], 'starts': {'team1': [[3, 4], [3, 5]], 'team2': [[5, 4], [6, 4], [7, 4]] if talent == RAINBOW else ([[4, 4], [5, 5], [5, 3]] if near else [[5, 4], [5, 5], [5, 3]])}})
    mid = service.create_factory_match(project_ids=['left', 'ally'], opponent_actor_ids=FOES,
        control_modes={actor: 'MANUAL' for actor in IDS.values()},
        arena_id='battlefield:map.spear-second-yard', match_seed='A2SPEAR')['match_id']
    table = TabletopService(service, tmp_path)
    while table.state(mid)['menu']['actor_id'] != LEFT:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    if ai:
        service.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    return service, table, mid


def checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return session.engine


def cast(service, table, mid, talent, *, picks=None, ai=False, mode=None, expected_roster=None, forbidden_weapon=None):
    state = table.state(mid); menu = state['menu']
    candidates = service._load_session(mid).engine.legal_candidates()
    chosen = next(c for c in candidates if talent in c.source_definition_id
                  and (mode is None or mode in c.display_name)
                  and (mode != '15-foot cone' or c.destination and (c.destination.x, c.destination.y) == (6, 4))
                  and (talent != RAINBOW or c.destination and (c.destination.x, c.destination.y) == (9, 4)))
    cid = chosen.candidate_id
    if ai:
        from combat.gate4_adapters import ManualControllerAdapter
        real = service.controller
        class ForcedPrimary:
            def choose_primary_action(self, context):
                selected = next(c for c in context.legal_candidates if c.candidate_id == cid)
                return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        service.controller = ForcedPrimary()
    answers, prompts = [], []
    for _ in range(15):
        # The same public service request resumes after each transactional pause.
        result = (table.auto_step(mid, state['last_sequence'], answers) if ai else
                  table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers))
        if result['status'] == 'COMMITTED':
            return prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']; prompts.append(prompt)
        if ai:
            raise AssertionError(f'AI left an unanswered choice: {prompt}')
        options = [row['id'] for row in (prompt.get('choice') or {}).get('options', [])]
        answer = {**prompt['context'], 'selection': 'USE'}
        if options:
            source = prompt['context']['reaction_source_id']
            if source.endswith('rider_targets'):
                assert set(options) == set(expected_roster if expected_roster is not None else
                    [LEFT, ALLY, *FOES] if talent == METEOR else FOES), options
                if talent == FLOWERS:
                    assert prompt['context'].get('maximum', 2) == 2, prompt['choice']
                answer['option_ids'] = picks or (FOES if talent == METEOR else FOES[:2])
            elif source.endswith('rider_failed_save'):
                assert set(options) == set(FOES[:2]), options
                answer['option_ids'] = [FOES[1]]
            elif source.endswith('move_without_provoking'):
                answer['selection'] = 'DECLINE'
            else:
                if forbidden_weapon and source.endswith('spear_weapon'):
                    assert not any(option.endswith(forbidden_weapon) for option in options), options
                answer['option_ids'] = [options[0]]
        answers.append(answer)
    raise AssertionError('choice did not settle')


@pytest.mark.parametrize('ai,one_miss', [(False, False), (False, True), (True, False)])
def test_flowers_uses_long_spear_reach_bounded_recipients_and_hit_only_riders(monkeypatch, tmp_path, ai, one_miss):
    ext._load()
    monkeypatch.setitem(ext._HOOKS, 'd20_result', [*ext._HOOKS.get('d20_result', []),
        lambda engine, roll, intent: {'source_id': 'test:spear.hit', 'operation': 'replace', 'natural_result': 15}
        if roll.actor_id == LEFT else None])
    service, table, mid = fight(tmp_path, FLOWERS, ai=ai, one_miss=one_miss)
    before = checked(tmp_path, mid)
    assert before._distance_actor_to_actor(before.state.actors[LEFT], before.state.actors[FOES[0]]) == 10
    stamina = before.state.actors[LEFT].resources['resource:core.stamina']
    prompts = cast(service, table, mid, FLOWERS, ai=ai)
    after = checked(tmp_path, mid)
    attempts = [e for e in after.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id.endswith(FLOWERS)]
    assert len(attempts) == 2
    assert all(e.payload.get('modifier') == 4 for e in attempts), [e.payload for e in attempts]
    attacked = {who for event in attempts for who in event.target_ids}
    assert len(attacked) == 2 and attacked <= set(FOES)
    if not ai:
        assert attacked == set(FOES[:2])
    assert ALLY not in attacked and LEFT not in attacked
    for who in FOES:
        conditions = after.state.actors[who].conditions.values()
        marked = any(c.condition_id.startswith('condition:typed.mark.spear_intent.') for c in conditions)
        denied = any(c.condition_id.endswith('reaction_denied') for c in conditions)
        expected = who in attacked and not (one_miss and who == FOES[1])
        assert marked == denied == expected, (who, [c.condition_id for c in conditions])
    if ai:
        moved = [e for e in after.events if e.event_type == 'MOVEMENT_COMMITTED'
                 and e.actor_id == LEFT and e.source_definition_id.endswith(FLOWERS)]
        assert len(moved) == 1
        assert moved[0].payload.get('granted_cost_ft') == 5
        assert after.state.actors[LEFT].movement_remaining_ft == before.state.actors[LEFT].movement_remaining_ft
    elif not one_miss:
        exemption = next(p for p in prompts if p['context']['reaction_source_id'].endswith('quiet_step_creature'))
        assert {row['id'] for row in exemption['choice']['options']} == set(FOES[:2])
    assert after.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    assert after.state.actors[LEFT].resources['resource:core.stamina'] == stamina - 4
    assert not any(e.event_type == 'GM_RIDER' for e in after.events if e.source_definition_id.endswith(FLOWERS))
    assert not prompts if ai else any(p['context']['reaction_source_id'].endswith('rider_targets') for p in prompts)


@pytest.mark.parametrize('ai,all_pass', [(False, False), (True, False), (False, True)])
def test_rainbow_chooses_one_failed_recipient_and_cover_scope_survives_reload(tmp_path, ai, all_pass):
    service, table, mid = fight(tmp_path, RAINBOW, ai=ai, all_pass=all_pass)
    cast(service, table, mid, RAINBOW, ai=ai)
    engine = checked(tmp_path, mid)
    holders = [actor for actor in engine.state.actors.values() if any(c.condition_id == CONDITION for c in actor.conditions.values())]
    assert len(holders) == (0 if all_pass else 1), [a.entity_id for a in holders]
    if all_pass:
        return
    holder = holders[0]; caster = engine.state.actors[LEFT]
    assert holder.entity_id in FOES[:2]
    if not ai:
        assert holder.entity_id == FOES[1]
    condition = next(c for c in holder.conditions.values() if c.condition_id == CONDITION)
    assert condition.expires_on == 'START_OF_SOURCE_NEXT_TURN'
    spear = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.source_definition_id.endswith(RAINBOW))
    ordinary = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.parameters.get('typed', {}).get('weapon'))
    with scope(engine, caster, spear):
        assert reduce_cover(engine, caster, holder, 2) == 0
        assert reduce_cover(engine, caster, holder, 5) == 0
        assert reduce_cover(engine, caster, holder, 99) == 99
        other = engine.state.actors[next(who for who in FOES[:2] if who != holder.entity_id)]
        assert reduce_cover(engine, caster, other, 5) == 5
    with scope(engine, caster, ordinary):
        assert reduce_cover(engine, caster, holder, 5) == 5
    ally = engine.state.actors[ALLY]
    with scope(engine, ally, spear):
        assert reduce_cover(engine, ally, holder, 5) == 5
    if ai:
        service.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    for _ in range(8):
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
        engine = checked(tmp_path, mid)
        if engine.state.current_actor_id == LEFT:
            break
    else:
        raise AssertionError('caster next turn not reached')
    assert not any(c.condition_id == CONDITION for a in engine.state.actors.values() for c in a.conditions.values())


@pytest.mark.parametrize('cover', [2, 5, 99])
def test_rainbow_cover_bypass_reaches_native_save_bonus_and_recorded_roll(monkeypatch, tmp_path, cover):
    from combat import typed_executor as te
    from tests.test_tabletop_hunt6 import on_hold
    service, table, mid = fight(tmp_path, RAINBOW)
    cast(service, table, mid, RAINBOW)
    held = checked(tmp_path, mid)
    target_id = next(a.entity_id for a in held.state.actors.values()
                     if any(c.condition_id == CONDITION for c in a.conditions.values()))
    ext._load()
    # Represent any spatial cover provider and a separate non-cover bonus.
    monkeypatch.setitem(ext._HOOKS, 'save_bonus_details', [*ext._HOOKS.get('save_bonus_details', []),
        lambda engine, target, ability, dc, source, intent:
            {'bonus': cover + 3, 'contributions': {'cover': cover, 'other': 3}}
            if target.entity_id == target_id else None])
    def followup(engine):
        actor, target = engine.state.actors[LEFT], engine.state.actors[target_id]
        spear = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.source_definition_id.endswith(RAINBOW))
        ordinary = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.parameters.get('typed', {}).get('weapon'))
        for action in (spear, ordinary):
            ctx = te.Context(engine, actor, action, engine._active_intent,
                             action.parameters['typed'], [target], target, {})
            te.run_effects(ctx, [{'type': 'save', 'ability': 'dex', 'dc': 'technique_save_dc',
                                 'applies_to': 'target', 'on_fail': [], 'on_success': []}])
    on_hold(monkeypatch, followup)
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'
             and e.actor_id == target_id and e.payload.get('save_bonus_contributions', {}).get('other') == 3]
    assert len(saves) == 2
    spear, ordinary = saves
    expected_cover = 0 if cover <= 5 else cover
    assert spear.payload['modifier'] == engine.state.actors[target_id].saving_throws['DEX'] + expected_cover + 3
    assert ordinary.payload['modifier'] == engine.state.actors[target_id].saving_throws['DEX'] + cover + 3
    assert spear.payload['save_bonus_contributions'] == ({'other': 3} if cover <= 5 else {'cover': cover, 'other': 3})
    assert ordinary.payload['save_bonus_contributions'] == {'cover': cover, 'other': 3}


@pytest.mark.parametrize('picks', [FOES, [FOES[0], FOES[0]]])
def test_flowers_rejects_over_cap_or_duplicate_answers_without_spending(tmp_path, picks):
    from combat.gate5_service import CombatServiceError
    service, table, mid = fight(tmp_path, FLOWERS)
    before = checked(tmp_path, mid).state.model_dump(mode='json')
    with pytest.raises(CombatServiceError):
        cast(service, table, mid, FLOWERS, picks=picks)
    after = checked(tmp_path, mid).state.model_dump(mode='json')
    assert after == before


@pytest.mark.parametrize('ai,mode', [(False, '15-foot cone'), (True, '15-foot cone'),
                                    (False, 'Spear Line'), (True, 'Spear Line')])
def test_meteor_net_offers_both_shapes_and_resolves_every_chosen_creature(tmp_path, ai, mode):
    from combat.ext import approach_lock
    service, table, mid = fight(tmp_path, METEOR, ai=ai)
    before = checked(tmp_path, mid)
    actions = [a for a in before.action_catalog.values() if a.owner_id == LEFT and METEOR in a.source_definition_id]
    assert {a.display_name for a in actions} == {'Meteor-Net Spear Art: 15-foot cone', 'Meteor-Net Spear Art: Spear Line'}
    stamina = before.state.actors[LEFT].resources['resource:core.stamina']
    cast(service, table, mid, METEOR, ai=ai, mode=mode)
    engine = checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and METEOR in e.source_definition_id]
    assert {e.actor_id for e in saves} == set(FOES)
    assert len(saves) == 3
    success = {e.actor_id: e.payload['success'] for e in saves}
    assert success == {FOES[0]: False, FOES[1]: False, FOES[2]: True}
    for who in FOES:
        target = engine.state.actors[who]
        assert any(c.condition_id.startswith('condition:typed.mark.spear_intent.') for c in target.conditions.values())
        assert any(c.condition_id.endswith('reaction_denied') for c in target.conditions.values()) == (not success[who])
        locks = approach_lock.records(engine, target)
        assert bool(locks) == (not success[who])
        if locks:
            assert locks[0]['mode'] == 'closer'
    assert engine.state.actors[LEFT].resources['resource:core.stamina'] == stamina - 6
    assert engine.state.actors[ALLY].current_hp == before.state.actors[ALLY].current_hp
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and METEOR in e.source_definition_id]
    assert {who for e in damage for who in e.target_ids} == set(FOES)
    assert not any(e.event_type == 'GM_RIDER' and METEOR in e.source_definition_id for e in engine.events)


@pytest.mark.parametrize('talent', [FLOWERS, METEOR])
def test_stowed_long_spear_cannot_bind_or_expand_drawn_short_spear_roster(tmp_path, talent):
    from tests.hunt12_support import candidate, send
    from combat.ext.hand_occupancy import weapon_grips
    from combat.weapon_delivery import available_weapons
    kit = {'starting_kit': {'items': [
        {'item_id': 'tianxia.mortal.weapon.mao', 'name': 'Mao', 'quantity': 1},
        {'item_id': 'tianxia.mortal.weapon.duan_cha', 'name': 'Duan Cha (Short Trident)', 'quantity': 1}]}}
    service, table, mid = fight(tmp_path, talent, kit=kit, near=True)
    stow = candidate(service, mid, lambda c: 'Stow Mao' in c.display_name)
    assert send(service, table, mid, stow)['status'] == 'COMMITTED'
    engine = checked(tmp_path, mid)
    actor = engine.state.actors[LEFT]
    assert any(k.endswith('weapon.mao') for k in available_weapons(engine, actor))
    assert not any(k.endswith('weapon.mao') for k in weapon_grips(engine, actor))
    assert any(k.endswith('weapon.duan_cha') for k in weapon_grips(engine, actor))
    roster = [FOES[0]] if talent == FLOWERS else [LEFT, ALLY, FOES[0]]
    cast(service, table, mid, talent, picks=[FOES[0]], mode='Spear Line' if talent == METEOR else None,
         expected_roster=roster, forbidden_weapon='weapon.mao')
    after = checked(tmp_path, mid)
    packets = [e for e in after.events if talent in e.source_definition_id
               and e.event_type == ('ATTACK_ROLLED' if talent == FLOWERS else 'SAVE_ROLLED')]
    assert len(packets) == 1
    assert (set(packets[0].target_ids) if talent == FLOWERS else {packets[0].actor_id}) == {FOES[0]}


def test_meteor_player_can_deliberately_choose_same_team_recipient(tmp_path):
    service, table, mid = fight(tmp_path, METEOR)
    before = checked(tmp_path, mid)
    cast(service, table, mid, METEOR, picks=[ALLY], mode='Spear Line')
    after = checked(tmp_path, mid)
    saves = [e for e in after.events if e.event_type == 'SAVE_ROLLED' and METEOR in e.source_definition_id]
    assert [e.actor_id for e in saves] == [ALLY]
    assert after.state.actors[ALLY].current_hp < before.state.actors[ALLY].current_hp
    assert all(after.state.actors[who].current_hp == before.state.actors[who].current_hp for who in FOES)


def test_rainbow_public_choice_explains_benefit_duration_and_enclosing_cost(tmp_path):
    service, table, mid = fight(tmp_path, RAINBOW)
    prompts = cast(service, table, mid, RAINBOW)
    after = checked(tmp_path, mid)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'].endswith('rider_failed_save'))
    assert prompt['reaction'] == 'Penetrating Rainbow'
    assert 'choose one creature that failed its save' in prompt['moment'].lower()
    assert 'Half Cover and Three-Quarters Cover' in prompt['moment']
    assert 'Spear talents against' in prompt['moment']
    assert 'start of your next turn' in prompt['moment']
    assert '4 Stamina' in json.dumps(prompt), prompt
    assert {row['label'] for row in prompt['choice']['options']} == {'Foe1', 'Foe2'}
    condition = next(c for c in after.state.actors[FOES[1]].conditions.values() if c.condition_id == CONDITION)
    assert "start of Left's next turn" in condition.data['label']


def test_reviewed_spear_definitions_are_unique_and_still_compile_through_service(tmp_path):
    service, table, mid = fight(tmp_path, RAINBOW)
    cast(service, table, mid, RAINBOW)
    assert any(c.condition_id == CONDITION for a in checked(tmp_path, mid).state.actors.values()
               for c in a.conditions.values())
    for talent in (FLOWERS, RAINBOW, METEOR):
        files = [p.name for p in (ROOT / 'authority/typed_mechanics/reviewed_final.d').glob('*.json')
                 if talent in json.loads(p.read_text()).get('mechanics', {})]
        assert len(files) == 1, (talent, files)
