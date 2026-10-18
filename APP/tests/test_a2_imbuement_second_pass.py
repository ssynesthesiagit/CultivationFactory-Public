"""Automatic Mass recipients obey printed sides through accepted table actions."""
import json
from pathlib import Path
import pytest
from combat import concentration
from tests.test_a2_imbuement import fixture, cold, S, M, QI


@pytest.mark.parametrize('side,option,expected', [
    ('Place', 'Quicken', (S.OWNER, S.SECOND)),
    ('Fray', 'Slow', (S.FOE, S.THIRD)),
])
def test_ai_mass_uses_only_printed_side_with_both_sides_in_range(monkeypatch, tmp_path, side, option, expected):
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'layered_mandate'], extra=True, third_ally=False)
    before = cold(tmp_path, mid)
    actor = before.state.actors[S.OWNER]
    assert all(before._distance_actor_to_actor(actor, a) <= 30 for a in before.state.actors.values())
    cid = S.candidate(table, mid, f'Mass {side} Mandate: {option}', expected[-1])
    S.force_ai_candidate(combat, mid, S.OWNER, cid)
    answers = []
    for _ in range(16):
        result = send(cid, answers, auto=True)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        # The AI owns its recipient choice. No human roster answer is supplied.
        assert prompt['context']['reaction_source_id'] != 'choice:needle.mass_mandate'
        answers.append({**prompt['context'], 'selection': 'DECLINE'})
    else:
        raise AssertionError('AI cast did not commit')
    engine = cold(tmp_path, mid)
    caster = engine.state.actors[S.OWNER]
    source = caster.concentration.source_definition_id
    affected = {aid for aid, bearer in engine.state.actors.items()
                if any(row.source_definition_id == source and concentration.is_recipient_effect(row)
                       for row in (*bearer.conditions.values(), *bearer.modifiers.values()))}
    assert affected == set(expected)
    assert caster.resources[QI] == actor.resources[QI] - 2
    roster = next(row for row in caster.conditions.values() if row.condition_id == M.MASS_LOAD)
    assert set(roster.data['recipients']) == set(expected)
    assert engine.state.actors[S.OWNER].action_available is False


@pytest.mark.parametrize('side,option', [('Place', 'Sharpen'), ('Fray', 'Dull')])
def test_army_ai_ten_equipment_vessels_three_load_and_correct_side(monkeypatch, tmp_path, side, option):
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.relations import ALLY, ENEMY, relation
    from tests.test_auto20_imbuement import DAO
    from combat.ext import persist_augment as P
    real_sheet = S.sheet
    def equipped(*args, **kwargs):
        kwargs['kit'] = {'starting_kit': {'items': [DAO]}}
        return real_sheet(*args, **kwargs)
    monkeypatch.setattr(S, 'sheet', equipped)
    finish = CombatService._finish_factory_match
    def with_equipment_bearers(self, *args, **kwargs):
        args = list(args)
        for i in range(10):
            aid = FACTORY_ACTOR_PREFIX + f'army-{i}'
            doc = S.sheet([], cl=17)
            doc['identity']['display_name'] = f'Bearer {i + 1}'
            doc['ability_scores_and_statistics']['hit_points']['maximum'] = 500
            args[0].append(S.compile_character(doc, actor_id=aid))
            args[1].append(aid)
            args[2][aid] = 'team:a' if side == 'Place' else 'team:b'
            args[3][aid] = {'x': 3 + i % 4, 'y': 7 + i // 4}
            args[6].append(aid)
            kwargs['control_modes'][aid] = 'MANUAL'
        return finish(self, *args, **kwargs)
    monkeypatch.setattr(CombatService, '_finish_factory_match', with_equipment_bearers)
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'name_the_army_s_gear', 'sharpen_and_dull',
                 'layered_mandate', 'qi_written_mandate'])
    menu = table.state(mid)['menu']['actions']
    label = f'Name the Army’s Gear: Mass {side} Mandate: {option}'
    army_action = next(g for g in menu if g['label'].startswith(label))
    assert 'one weapon or armor Vessel per creature' in army_action['description']
    assert 'up to ten creatures' in army_action['description']
    assert 'Multiple Vessels on one creature need GM resolution' in army_action['description']
    authority_path = Path(__file__).parents[1] / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json'
    authority = json.loads(authority_path.read_text())
    riders = authority['mechanics']['tianxia.talent.imbuement.name_the_army_s_gear']['riders']
    assert any('one weapon or armor Vessel per creature' in rider and
               'multiple Vessels on one bearer' in rider for rider in riders)
    assert not any('Name the Army’s Gear:' in g['label'] and 'Quicken' in g['label'] for g in menu)
    target = S.SECOND if side == 'Place' else S.FOE
    cid = S.candidate(table, mid, label, target)
    before = cold(tmp_path, mid)
    owner = before.state.actors[S.OWNER]
    S.force_ai_candidate(combat, mid, S.OWNER, cid)
    answers = []
    for _ in range(16):
        result = send(cid, answers, auto=True)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        assert prompt['context']['reaction_source_id'] != 'choice:needle.mass_mandate'
        answers.append({**prompt['context'], 'selection': 'DECLINE'})
    else:
        raise AssertionError('Army cast did not commit')
    engine = cold(tmp_path, mid)
    caster = engine.state.actors[S.OWNER]
    source = caster.concentration.source_definition_id
    roster = next(row for row in caster.conditions.values() if row.condition_id == M.MASS_LOAD)
    assert len(roster.data['recipients']) == 10
    wanted = ALLY if side == 'Place' else ENEMY
    for aid in roster.data['recipients']:
        bearer = engine.state.actors[aid]
        assert relation(engine, caster, bearer) == wanted
        assert any(row.source_definition_id == source and row.condition_id == M.VESSEL
                   for row in bearer.conditions.values())
    assert M._mandate_weight(engine, caster, source, caster.concentration.started_sequence) == 3
    assert caster.resources[QI] == owner.resources[QI] - 2
    if side == 'Fray':
        saves = [r for r in engine.rolls if r.reason.startswith('SAVE:') and source in r.reason]
        assert len(saves) == 10
    else:
        combat.set_controller_mode(mid, actor_id=S.OWNER, controller_mode='MANUAL')
        commit(S.candidate(table, mid, 'Set Mandate:'))
        engine = cold(tmp_path, mid)
        caster = engine.state.actors[S.OWNER]
        record = P.persisted(engine, caster, P.MANDATE)[0][1]
        assert M._mandate_weight(engine, caster, source, record.data['started']) == 3
        assert caster.concentration is None


def test_army_armor_selects_only_equipped_allies(monkeypatch, tmp_path):
    real = S.sheet
    def armored(*args, **kwargs):
        if args[0]:
            kwargs['kit'] = {'starting_kit': {'items': [
                {'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1}]}}
        return real(*args, **kwargs)
    monkeypatch.setattr(S, 'sheet', armored)
    combat, table, mid, send, commit = fixture(monkeypatch, tmp_path,
        talents=['mass_mandate', 'name_the_army_s_gear', 'tempered_equipment',
                 'layered_mandate', 'qi_written_mandate'])
    cid = S.candidate(table, mid, 'Name the Army’s Gear: Mass Place Mandate: Temper (armor)', S.OWNER)
    S.force_ai_candidate(combat, mid, S.OWNER, cid)
    result = send(cid, auto=True)
    assert result['status'] == 'COMMITTED', result
    engine = cold(tmp_path, mid)
    caster = engine.state.actors[S.OWNER]
    roster = next(row for row in caster.conditions.values() if row.condition_id == M.MASS_LOAD)
    assert roster.data['recipients'] == [S.OWNER]
    assert M.vessel_armor(engine, caster) > 0
    assert not any(row.condition_id == M.VESSEL for row in engine.state.actors[S.SECOND].conditions.values())
