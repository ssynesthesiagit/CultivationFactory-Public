"""Explicit inclusive wording includes the user; unscoped harm hits enemies."""
import json

import pytest

from combat.area_recipients import scoped_area
from combat.forged import mechanic_for, rules
from combat.typed_executor import _area_targets
from tests.h1_support import ROOT, sheet
from tests.test_area_shapes import _Actor, _Engine
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT
from combat.gate5_service import CombatService


def test_compiler_reads_printed_recipients_missing_from_typed_description():
    from combat.factory_compiler import compile_character
    bundle = compile_character(sheet(['ASH_TAL_CINDER_BURST']), actor_id='user')
    action = next(a for a in bundle['action_catalog'] if 'ASH_TAL_CINDER_BURST' in a['source_definition_id'])
    area = action['parameters']['typed']['area']
    assert area['recipients'] == 'hostile' and not area['include_self'] and area['exclude_self']


@pytest.mark.parametrize('ask', [False, True])
def test_chosen_creatures_offer_the_user_and_resolve_only_the_choice(tmp_path, ask):
    ability = 'TAL_DAEMONIC_CULTIVATION_WORLD_DEVOURING_MAW'
    combat, table, mid = table_fight(tmp_path, [ability], ask=ask, ally_talents=[])
    result, option = _commit_area_action(table, mid, 'World-Devouring Maw', {'x': 4, 'y': 4})
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert any(o['id'] == LEFT for o in prompt['choice']['options'])
    answers = [{**prompt['context'], 'selection': 'USE', 'option_ids': [LEFT]}]
    for _ in range(16):
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
            state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
             and ability in (e.source_definition_id or '')}
    assert saves == {LEFT}
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('form', ['burst', 'cone', 'line', 'zone', 'aura'])
def test_forged_area_replaces_primary_creature_scope_with_enemy_delivery(form):
    mechanics = json.loads((ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    forged = mechanic_for({'name': 'Practice forged area',
        'primary_sphere_effect': {'talent_id': 'RADIANCE_TAL_JUDGMENT_RAY'},
        'base_form': {'form_id': form}}, mechanics)
    area = scoped_area(forged['area'], forged['effects'], ' '.join(forged['description']), typed=forged)
    assert area['recipients'] == 'hostile' and area['exclude_self']
    assert forged['effects'][0]['applies_to'] == 'enemies_in_area'


@pytest.mark.parametrize('payload,expected', [
    ({'type': 'unclassified_practice_payload'}, 'enemies_in_area'),
    ({'type': 'temp_hp', 'flat': 4}, 'creatures_in_area'),
])
def test_forged_delivery_retains_conservative_unknown_and_known_benefit(payload, expected):
    mechanic = {'name': 'Practice primary', 'effects': [payload]}
    forged = mechanic_for({'name': 'Practice Burst', 'base_form': {'form_id': 'burst'},
        'primary_sphere_effect': {'talent_id': 'practice'}}, {'practice': mechanic})
    assert forged['effects'][0]['applies_to'] == expected


@pytest.mark.parametrize('legacy', [False, True])
def test_each_creature_metadata_includes_user_without_explicit_exception(legacy):
    effects = [{'type': 'damage', 'flat': 4, 'applies_to': 'creatures_in_area'}]
    area = {'shape': 'sphere', 'size_ft': 15}
    if legacy:
        area.update(recipients='all', exclude_self=True)
    area = scoped_area(area, effects, 'Each creature in the area takes damage.')
    user, ally, enemy = _Actor('user', 'a', 3, 4), _Actor('ally', 'a', 3, 5), _Actor('enemy', 'b', 4, 4)
    assert _area_targets(_Engine([user, ally, enemy]), user, user.position, area) == [user, ally, enemy]


def test_printed_each_creature_damage_hits_user_on_table_commit_reload_replay(tmp_path):
    ability = 'tianxia.subpath.qi.alchemical_cultivator.feature.explosive_pill'
    combat, table, mid = table_fight(tmp_path, [ability], cl=20, ally_talents=[])
    result, option = _commit_area_action(table, mid, 'Explosive Pill: Flame Pill', {'x': 4, 'y': 4})
    answers = []
    for _ in range(16):
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
            state['menu']['state_version'], state['last_sequence'], answers)
    assert result['status'] == 'COMMITTED', result
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
             and ability in (e.source_definition_id or '')}
    assert saves == {LEFT, ALLY, RIGHT}
    assert loaded.engine.state.actors[LEFT].current_hp < 60
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
