"""Cai printed combat contracts through accepted table intents and cold reload."""
from copy import deepcopy
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext import cai_clan as cai
from combat.gate2_runtime_models import ActionIntent
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.test_cai_clan_subpath import _fight, _loaded, _use
from tests.test_tabletop_hunt6 import on_hold, act, HOLD, LEFT, ALLY
from tests import worker2_support as w


def _split_hit(bundles):
    # A real compiled attack with two separately committed damage components.
    bundle = bundles[1]
    attack = next(a for a in bundle['action_catalog'] if a['display_name'] == 'Wind Lash: Cut')
    damage = next(e for e in attack['parameters']['typed']['effects'][0]['on_hit'] if e['type'] == 'damage')
    bonus = deepcopy(damage)
    bonus['dice'] = {'count': 1, 'sides': 4}
    attack['parameters']['typed']['effects'][0]['on_hit'].append(bonus)
    bundle.pop('bundle_sha256', None)
    bundle['bundle_sha256'] = canonical_sha256(bundle)


def test_one_hit_claims_only_strongest_censure_across_damage_components(tmp_path, monkeypatch):
    combat, table, mid = w.fixture(tmp_path, [cai.INVEST, cai.EDICT],
        ally_talents=['AIR_BASE_WIND_LASH'], extra_allies=1, bundle_transform=_split_hit,
        positions={w.OWNER: {'x':3,'y':6}, w.ALLY: {'x':4,'y':6}, w.FOE: {'x':4,'y':5}}, seed='A2GQISUB11-SPLIT')
    third = 'actor:factory.worker2-ally3'
    w.turn(table, mid, w.ALLY)
    # Establish both marks after intervening turns, so neither has expired.
    def marks(engine):
        for owner, dice in ((w.OWNER, 2), (third, 3)):
            engine._apply_condition(engine.state.actors[w.FOE], cai.CENSURE, cai.EDICT, owner,
                expires_on='START_OF_SOURCE_NEXT_TURN', data={'dice': dice, 'name':'Censure'})
    with monkeypatch.context() as patch:
        on_hold(patch, marks)
        w.settle(table, mid, next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.source_definition_id == HOLD))
    w.settle(table, mid, w.candidate(combat, mid, 'Wind Lash: Cut', target=w.FOE).candidate_id)
    loaded = w.reload(tmp_path, mid)
    claims = [e for e in loaded.events if e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == cai.EDICT]
    assert len(claims) == 1
    assert claims[0].payload['expression'] in ('3d8+0', '6d8+0')
    remaining = [c for c in loaded.state.actors[w.FOE].conditions.values() if c.condition_id == cai.CENSURE]
    assert len(remaining) == 1 and remaining[0].data['dice'] == 2


@pytest.mark.parametrize('court', [False, True])
def test_automatic_investiture_chooses_allies_and_never_enemy(tmp_path, court):
    combat, table, mid = _fight(tmp_path, 18 if court else 10,
        modes={LEFT: 'LOCAL_AUTO', ALLY: 'MANUAL', 'actor:factory.33333333':'MANUAL'})
    # The real AI-owned choice uses its default selection through execute_intent.
    name = 'Court Beneath the Colorless Star' if court else 'Empyreal Layer'
    session = combat._load_session(mid)
    c = next(c for c in session.engine.legal_candidates() if session.engine.action_catalog.get(c.source_definition_id)
             and session.engine.action_catalog[c.source_definition_id].display_name == name)
    session.mechanical.execute_intent(ActionIntent(intent_id='a2gqisub11-auto-invest', decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=c.actor_id,
        target_ids=c.target_ids, destination=c.destination, option_ids=c.option_ids))
    loaded = _loaded(combat, mid)
    protected = {a.entity_id for a in loaded.engine.state.actors.values()
                 if any(c.condition_id == cai.LAYER for c in a.conditions.values())}
    assert protected == {LEFT, ALLY}
    assert loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('court', [False, True], ids=['empyreal-layer', 'colorless-court'])
def test_investiture_excludes_visible_ally_behind_physical_effect_blocker(
        tmp_path, monkeypatch, court):
    """Sight alone is insufficient: a physical wall blocks the layer's reach."""
    from combat.targeting import line_of_effect

    # The map wall is solid for movement/effects; perception is independently
    # established so this specifically exercises the second eligibility gate.
    from combat.tabletop import TabletopMapStore
    save_map = TabletopMapStore.save
    def save_wall(store, document):
        document['walls'] = [{'shape': 'line', 'points': [[0, 5], [11, 5]],
                              'blocks': 'sight_and_movement'}]
        return save_map(store, document)
    monkeypatch.setattr(TabletopMapStore, 'save', save_wall)
    monkeypatch.setattr(cai, 'can_see', lambda engine, observer, target: True)
    combat, table, mid = _fight(tmp_path, 18 if court else 10)
    session = combat._load_session(mid)
    owner, ally = session.engine.state.actors[LEFT], session.engine.state.actors[ALLY]
    assert cai.can_see(session.engine, owner, ally)
    assert not line_of_effect(session.engine, owner, target=ally)

    name = 'Court Beneath the Colorless Star' if court else 'Empyreal Layer'
    menu = table.state(mid)['menu']
    action = next(g for g in menu['actions'] if g['label'].startswith(name))['options'][0]
    result = table.act(mid, action['candidate_id'], menu['decision_id'],
                       menu['state_version'], table.state(mid)['last_sequence'], [])
    assert result['status'] == 'REACTION_REQUIRED', result
    offered = {row['id'] for row in result['reaction']['choice']['options']}
    assert LEFT in offered  # eligible self control
    assert ALLY not in offered

    # Commit the player-selected eligible control, then prove the rejected
    # recipient receives no layer after cold reload and deterministic replay.
    result = table.act(mid, action['candidate_id'], menu['decision_id'],
                       menu['state_version'], table.state(mid)['last_sequence'],
                       [{**result['reaction']['context'], 'selection': 'USE', 'option_ids': [LEFT]}])
    assert result['status'] == 'COMMITTED', result
    loaded = _loaded(combat, mid)
    assert not any(c.condition_id == cai.LAYER for c in loaded.engine.state.actors[ALLY].conditions.values())
    assert any(c.condition_id == cai.LAYER for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert loaded.mechanical.replay()['status'] == 'PASS'


def test_duty_and_edict_compile_as_owned_implemented_passives():
    bundle = compile_character(sheet([cai.INVEST, cai.EDICT, cai.DUTY], cl=10), actor_id=LEFT)
    rows = {r['feature_id']: r for r in bundle['typed_passives']}
    assert {cai.EDICT, cai.DUTY} <= rows.keys()
    assert all(rows[f]['player_outcome'] for f in (cai.EDICT, cai.DUTY))
    assert not {'Edict of Shared Purpose', 'Court of Duty'} & set(bundle['diagnostics']['skipped']['passive'])


def test_court_of_duty_fixed_group_saves_and_temp_hp_survive_dismissal(tmp_path, monkeypatch):
    from combat.gate2_runtime_models import Position
    combat, table, mid = _fight(tmp_path, 10)
    # This small combat fixture supplies IDs; a built sheet also supplies its
    # printed library cards. Add those real rules cards before inspecting it.
    package = tmp_path / 'portable_characters' / LEFT.removeprefix('actor:factory.') / 'current.zip'
    with zipfile.ZipFile(package) as archive:
        doc = json.loads(archive.read('Tianxia_Owner_Character_Sheet_v1.json'))
    rules = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())
    doc['selected_record_sections'] = {'path_features': [
        {'record_id': fid, 'display_name': name, 'full_description': rules[fid], 'acquisition_cl': cl}
        for fid, name, cl in ((cai.EDICT, 'Edict of Shared Purpose', 6), (cai.DUTY, 'Court of Duty', 10))]}
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    connected = table.sheet(LEFT.removeprefix('actor:factory.'))
    assert connected['summary']['resource'] == {'name': 'Qi', 'maximum': 30}
    def entries(value):
        if isinstance(value, dict):
            if value.get('id') in (cai.EDICT, cai.DUTY):
                yield value
            for child in value.values():
                yield from entries(child)
        elif isinstance(value, list):
            for child in value:
                yield from entries(child)
    records = {e['id']: e for e in entries(connected['library'])}
    assert records[cai.EDICT]['status'] == records[cai.DUTY]['status'] == 'auto'
    _use(table, mid, 'Empyreal Layer', [LEFT, ALLY])
    def distant_save(engine):
        ally = engine.state.actors[ALLY]
        ally.position = Position(x=11, y=7)
        engine._roll_save(ally, 'WIS', 15, 'test:a2gqisub11.wis')
        engine._roll_save(ally, 'DEX', 15, 'test:a2gqisub11.dex')
    with monkeypatch.context() as patch:
        on_hold(patch, distant_save)
        assert act(table, mid, HOLD)['status'] == 'COMMITTED'
    loaded = _loaded(combat, mid)
    ally = loaded.engine.state.actors[ALLY]
    assert cai.layer_ac(loaded.engine, ally) == 2
    rolls = {r.reason: r for r in loaded.engine.rolls if r.reason.startswith('SAVE:test:a2gqisub11.')}
    assert rolls['SAVE:test:a2gqisub11.wis:WIS'].modifier == ally.saving_throws['WIS'] + 2
    assert rolls['SAVE:test:a2gqisub11.dex:DEX'].modifier == ally.saving_throws['DEX']
    assert loaded.mechanical.replay()['status'] == 'PASS'
    _use(table, mid, 'End Empyreal Layers')
    loaded = _loaded(combat, mid)
    assert loaded.engine.state.actors[ALLY].temporary_hp == 6
    assert not list(cai._active_layers(loaded.engine, loaded.engine.state.actors[ALLY]))
    assert loaded.mechanical.replay()['status'] == 'PASS'
