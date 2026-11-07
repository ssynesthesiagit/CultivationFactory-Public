"""Owner r4: catalogue martial harm defaults, owner flips and old bundles."""
import json

import pytest

from combat import area_recipient_rules
from combat.area_recipients import scoped_area, harmful_area_subject_allowed
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from tests.h1_support import ROOT, sheet
from tests.test_area_shapes import _Actor
from tests.test_friendly_fire_area_table import _commit_area_action
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT

ARMY = 'tianxia.talent.sabers.army_line_chopping_field'


def test_catalogue_types_aliases_and_unambiguous_tradition_not_ability_names():
    spheres, _, features, uncertain = area_recipient_rules.martial_catalogue()
    assert len([s for s in spheres.values() if s['martial']]) == 31
    for sphere in ['iron_fist', 'fencing', 'sabers', 'beastmastery', 'chains', 'music', 'thread']:
        assert area_recipient_rules.is_martial({'sphere': 'tianxia.sphere.' + sphere})
    for sphere in ['formations', 'sound', 'fire']:
        assert not area_recipient_rules.is_martial({'sphere': 'tianxia.sphere.' + sphere,
                                                  'name': 'Martial Iron Fist'})
    fid = 'tianxia.subpath.body.heaven_binding_chain_body.feature.heaven_binding_prison'
    assert fid in features and area_recipient_rules.is_martial({'source': fid})
    assert 'tianxia.subpath.qi.alchemical_cultivator.feature.explosive_pill' in uncertain
    assert area_recipient_rules.is_martial({'forged_from': 'TAL_IRON_FIST_RISING_KNEE'})


@pytest.mark.parametrize('legacy', [False, True])
def test_martial_policy_bounds_creature_wide_payload_and_preserves_benefits_and_self_cost(legacy):
    from combat.typed_executor import _declared_subjects
    from types import SimpleNamespace
    user, ally, enemy = _Actor('user', 'a', 3, 4), _Actor('ally', 'a', 3, 5), _Actor('enemy', 'b', 4, 4)
    effects = [{'type': 'damage', 'flat': 4, 'applies_to': 'creatures_in_area'},
               {'type': 'temp_hp', 'flat': 3, 'applies_to': 'creatures_in_area'},
               {'type': 'save', 'applies_to': 'self', 'on_fail': [
                   {'type': 'damage', 'flat': 1, 'applies_to': 'target'}]}]
    area = {'shape': 'sphere', 'size_ft': 15}
    if legacy:
        area.update(recipients='all', exclude_self=False, include_self=True)
    typed = {'sphere': 'tianxia.sphere.sabers', 'source': 'practice', 'effects': effects, 'area': area}
    scoped = scoped_area(area, effects, 'Creatures in the area.', typed=typed)
    assert scoped['recipients'] == 'all' and scoped['harmful_recipients'] == 'hostile'
    assert [a for a in [user, ally, enemy] if harmful_area_subject_allowed(user, a, scoped, effects[0])] == [enemy]
    ctx = SimpleNamespace(actor=user, typed=typed, targets=[user, ally, enemy], target=None,
                          explicit_self_recipient=False)
    assert _declared_subjects(ctx, effects[0], harmful=True) == [enemy]
    assert _declared_subjects(ctx, effects[1], harmful=False) == [user, ally, enemy]
    ctx.explicit_self_recipient = True
    ctx.target = user
    assert _declared_subjects(ctx, effects[2]['on_fail'][0], harmful=True) == [user]


@pytest.mark.parametrize('call', [None, 'enemies', 'everyone'])
def test_army_field_owner_default_and_flip_commit_reload_replay(tmp_path, monkeypatch, call):
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {} if call is None else {
        ARMY: {'recipients': call, 'reason': 'Owner test ruling'}}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    combat, table, mid = table_fight(tmp_path / 'fight', [ARMY], ally_talents=[],
        starts={'team1': [[3, 4], [5, 4]], 'team2': [[4, 4]]})
    caster_hp = combat._load_session(mid).engine.state.actors[LEFT].current_hp
    result, option = _commit_area_action(table, mid, 'Army-Line Chopping Field', {'x': 5, 'y': 4})
    assert ('Hits allies too:' in option['label']) is (call == 'everyone')
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
             and ARMY in (e.source_definition_id or '')}
    # Owner's everyone ruling includes allies, but an emitted cone can never
    # hit its caster (owner addendum 2026-10-14), regardless of wording/ruling.
    assert saves == ({ALLY, RIGHT} if call == 'everyone' else {RIGHT})
    assert loaded.engine.state.actors[LEFT].current_hp == caster_hp
    assert not any(e.event_type == 'DAMAGE_COMMITTED' and LEFT in e.target_ids
                   and ARMY in (e.source_definition_id or '') for e in loaded.engine.events)
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


def test_owner_flip_is_read_after_compile_without_service_restart(tmp_path, monkeypatch):
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    bundle = compile_character(sheet([ARMY]), actor_id='user')
    typed = next(a['parameters']['typed'] for a in bundle['action_catalog'] if ARMY in a['source_definition_id'])
    assert typed['area']['harmful_recipients'] == 'hostile'
    path.write_text(json.dumps({'abilities': {ARMY: {'recipients': 'everyone', 'reason': 'Owner wants collateral'}}}))
    updated = scoped_area(typed['area'], typed['effects'], typed=typed)
    assert updated['harmful_recipients'] == 'all'
    assert updated['include_self']


def test_removing_non_martial_override_restores_printed_scope(tmp_path, monkeypatch):
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {'practice': {'recipients': 'enemies', 'reason': 'Owner ruling'}}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    typed = {'source': 'practice', 'sphere': 'tianxia.sphere.fire',
             'effects': [{'type': 'damage', 'flat': 4, 'applies_to': 'creatures_in_area',
                          'evidence': 'Each creature in the area takes damage.'}]}
    area = scoped_area({'shape': 'sphere', 'size_ft': 15}, typed['effects'], typed=typed)
    assert area['harmful_recipients'] == 'hostile'
    path.write_text(json.dumps({'abilities': {}}))
    area = scoped_area(area, typed['effects'], typed=typed)
    assert area['recipients'] == 'all' and area['harmful_recipient_override'] == 'all'


def test_everyone_override_replaces_compiled_enemy_payload_scope(tmp_path, monkeypatch):
    from combat.typed_executor import _declared_subjects
    from types import SimpleNamespace
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {'practice': {'recipients': 'everyone', 'reason': 'Owner collateral ruling'}}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    user, ally, enemy = _Actor('user', 'a', 3, 4), _Actor('ally', 'a', 3, 5), _Actor('enemy', 'b', 4, 4)
    effect = {'type': 'damage', 'flat': 4, 'applies_to': 'enemies_in_area'}
    ctx = SimpleNamespace(actor=user, target=None, targets=[user, ally, enemy], typed={
        'source': 'practice', 'sphere': 'tianxia.sphere.sabers', 'effects': [effect],
        'area': {'shape': 'sphere', 'size_ft': 15}})
    assert _declared_subjects(ctx, effect, harmful=True) == [user, ally, enemy]


@pytest.mark.parametrize('call', [None, 'everyone'])
def test_chain_web_delayed_harm_default_and_owner_flip_after_reload(tmp_path, monkeypatch, call):
    from tests.test_lock2_persistence import act
    ability = 'tianxia.talent.chains.chain_web'
    path = tmp_path / 'owner-area-rulings.json'
    path.write_text(json.dumps({'abilities': {} if call is None else {
        ability: {'recipients': call, 'reason': 'Owner collateral ruling'}}}))
    monkeypatch.setattr(area_recipient_rules, 'OVERRIDES', path)
    combat, table, mid = table_fight(tmp_path / 'fight', [ability], ally_talents=[])
    result, option = _commit_area_action(table, mid, 'Chain Web', {'x': 4, 'y': 4})
    assert ('Hits allies too:' in option['label']) is (call == 'everyone')
    answers = []
    for _ in range(16):
        if result['status'] == 'COMMITTED': break
        assert result['status'] == 'REACTION_REQUIRED', result
        answers.append({**result['reaction']['context'], 'selection': 'DECLINE'})
        state = table.state(mid)
        result = table.act(mid, option['candidate_id'], state['menu']['decision_id'],
            state['menu']['state_version'], state['last_sequence'], answers)
    assert result['status'] == 'COMMITTED', result
    # A fresh service opens the saved zone before any later start-turn trigger.
    combat = CombatService(ROOT, combat.userdata_root)
    from combat.tabletop_service import TabletopService
    table = TabletopService(combat, combat.userdata_root)
    for _ in range(3):
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    loaded = combat._load_session(mid)
    saves = {e.actor_id for e in loaded.engine.events if e.event_type == 'SAVE_ROLLED'
             and ability in (e.source_definition_id or '')}
    assert saves == ({LEFT, ALLY, RIGHT} if call == 'everyone' else {RIGHT})
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'
