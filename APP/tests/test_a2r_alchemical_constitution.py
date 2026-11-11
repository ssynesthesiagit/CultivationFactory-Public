"""Alchemical Constitution: Advantage on saving throws against Poison,
through CombatService transactions, a real repeat save and cold reload."""
import json
import zipfile

import pytest

from combat import ext
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_r9i_karma_persistence import end_turn

OWNER = 'actor:factory.aaaaaaaa'
ALLY = 'actor:factory.bbbbbbbb'
FOE = 'actor:factory.ffffffff'
BASE = 'ALCHEMY_BASE_FIELD_FORMULA'
POISONED = 'condition:typed.poisoned'
INSIGHT = 'insight.alchemical-constitution'


def fight(monkeypatch, tmp_path, *, insights=(), prepare=None):
    for pid in ('aaaaaaaa', 'bbbbbbbb', 'ffffffff'):
        doc = sheet([BASE], primary='Stamina', dc=50, cl=10)
        doc['identity']['display_name'] = {'aaaaaaaa': 'Alchemist', 'bbbbbbbb': 'Ally', 'ffffffff': 'Enemy'}[pid]
        doc['spheres_and_talents']['cultivation_insight_record_ids'] = list(insights) if pid == 'aaaaaaaa' else []
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 400
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        ButtonStore(tmp_path / 'tabletop_buttons').save_reactions(pid, {'mode': 'ask'}, {BASE})
    if prepare:
        ext.effects()
        monkeypatch.setitem(ext._HOOKS, 'event', [*ext._HOOKS.get('event', []), prepare])
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Alchemy second pass', 'width_squares': 10, 'height_squares': 8,
        'walls': [], 'starts': {'team1': [[3, 4], [6, 5]], 'team2': [[6, 4]]}})
    mid = combat.create_factory_match(project_ids=['aaaaaaaa', 'bbbbbbbb'], opponent_actor_ids=[FOE],
        control_modes={OWNER: 'MANUAL', ALLY: 'MANUAL', FOE: 'MANUAL'},
        arena_id='battlefield:map.alchemy-second-pass', match_seed='A2ALCHEMY')['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, OWNER)
    return combat, table, mid


def poison_setup(recipient, *, dc=-40):
    """Poison the recipient with a Constitution save that repeats at the
    end of its turn (the Poisoned condition's own printed repeat save)."""
    def prepare(engine, kind, record):
        if kind != 'HOLD_POSITION_COMMITTED' or record.get('actor_id') != OWNER:
            return
        target = engine.state.actors[recipient]
        if engine.state.actors[OWNER].turn_flags.get('test_poison_ready'):
            return
        engine.state.actors[OWNER].turn_flags['test_poison_ready'] = True
        data = {'origin_save': {'ability': 'CON', 'dc': dc}, 'label': 'Test poison'}
        data['repeat_save'] = {'ability': 'CON', 'dc': dc, 'when': 'end'}
        engine._apply_condition(target, POISONED, 'test:poison', FOE,
                                expires_on='UNTIL_REMOVED', data=data)
    return prepare


def reload_checked(tmp_path, mid):
    session = CombatService(ROOT, tmp_path)._load_session(mid)
    assert session.verify()['status'] == session.mechanical.replay()['status'] == 'PASS'
    return session.engine


@pytest.mark.parametrize('insight,expected', [(False, 'NORMAL'), (True, 'ADVANTAGE')])
def test_the_poisoned_repeat_save_has_advantage(monkeypatch, tmp_path, insight, expected):
    # "You have Advantage on saving throws against Poison": the save a
    # creature repeats against the Poisoned condition it still bears is
    # a saving throw against Poison, so its mode is Advantage.
    combat, table, mid = fight(monkeypatch, tmp_path,
                               insights=[INSIGHT] if insight else [],
                               prepare=poison_setup(OWNER))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    assert end_turn(table, mid)['status'] == 'COMMITTED'
    engine = reload_checked(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == OWNER]
    assert saves and saves[-1].payload['mode'] == expected


@pytest.mark.parametrize('insight,expected', [(False, False), (True, True)])
def test_the_defense_row_grants_advantage_on_a_typed_poison_save(tmp_path, insight, expected):
    from combat.pressure import save_advantage
    combat, table, mid = fight(None, tmp_path, insights=[INSIGHT] if insight else [])
    engine = reload_checked(tmp_path, mid)
    rows = [row for row in engine.typed_passive_rows.get(OWNER, ())
            if row.get('feature_id') == INSIGHT and row.get('block') == 'defense']
    assert bool(rows) is insight
    if rows:
        assert rows[0]['kind'] == 'save_advantage'
        assert 'poisoned' in rows[0]['against']
    # a typed save against the Poisoned condition, and one against fixed
    # Poison damage, both read the printed Advantage
    assert save_advantage(engine, engine.state.actors[OWNER], 'CON', {'poisoned'}) is expected
    assert save_advantage(engine, engine.state.actors[OWNER], 'DEX', {'damage:poison'}) is expected
    # a save against anything else is untouched
    assert save_advantage(engine, engine.state.actors[OWNER], 'STR', {'frightened'}) is False
