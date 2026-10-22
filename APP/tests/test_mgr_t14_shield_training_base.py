"""SHIELD_BASE_SHIELD_TRAINING at the real table: the +2 is a training grant, and donning costs the Utilize Action.

Report: /var/tmp/auto-audit/fix/MGR-T14-ling-base-shield-training-1.report.md

``tests/test_a2_shield_service.py`` already proves the Utilize Action, the shared hand state and the cold
commit/reload for a fighter who *has* Shield Training. This file proves the parts that were only asserted at
compile time, plus the boundary and wrong-owner controls that row does not cover:

* ``A standard Shield grants a +2 bonus to Armor Class only when the wielder has Shield training`` -- two
  fighters with byte-identical gear, stats and armour differ by exactly +2 in the live session and after a
  cold reload, because one owns the Shield sphere and one owns nothing (never a name, never the gear itself).
* ``A creature may wield only one Shield at a time`` -- with the Shield already in hand the Don option is not
  offered at all, and doffing returns the hand and the option together.
* ``Donning or doffing a Shield requires the Utilize action`` -- the Action is spent, the condition survives a
  cold commit/reload, and the grant follows the fighter rather than the item: the untrained carrier can still
  don and doff its own Shield (nothing printed forbids that) but never gains the +2.
"""
import copy
import json
import zipfile

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_auto55_shield import ME, THEM, ROOT, _sheet
from tests.test_riders_lane9 import _sheet as plain
from tests.test_shield_fix_r1 import reload, table_action
from tests.test_shield_fix_r2 import advance

BARE = "actor:factory.mgr_t14_shield_untrained"
PROF = "actor:factory.mgr_t14_shield_proficient"
PROFICIENCY = 'tianxia.talent.equipment.shield_training'


def _bare(*, cl=17):
    """Identical fighter to :func:`_sheet`, minus every Shield sphere id: same gear, stats and armour."""
    doc = copy.deepcopy(_sheet([], cl=cl))
    doc['spheres_and_talents'] = {'sphere_record_ids': [], 'automatic_sphere_component_record_ids': [],
                                  'learned_talent_record_ids': []}
    return doc


def _proficient(*, cl=17):
    """No Shield sphere at all, but the book's own "### Shield Training ... You gain shield proficiency"."""
    doc = _bare(cl=cl)
    doc['spheres_and_talents']['learned_talent_record_ids'] = [PROFICIENCY]
    return doc


def match(tmp_path):
    docs = [copy.deepcopy(_sheet([], cl=17)), _bare(), _proficient(), plain([], 17, 1000)]
    ids = [ME, BARE, PROF, THEM]
    # The three Shield carriers must differ in nothing but training, so they share ability scores exactly.
    for doc in docs[:3]:
        for row in doc['ability_scores_and_statistics']['abilities']:
            row.update(score=18 if row['ability'] == 'STR' else 12, modifier=4 if row['ability'] == 'STR' else 1)
    for aid, doc in zip(ids, docs):
        doc['identity']['display_name'] = {ME: 'Shield Bearer', BARE: 'Untrained Bearer',
                                           PROF: 'Proficient Bearer', THEM: 'Enemy'}[aid]
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        doc['ability_scores_and_statistics']['technique_save_dc'] = 15
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as z:
            z.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in zip(ids, docs)]
    svc = CombatService(ROOT, tmp_path)
    table = TabletopService(svc, tmp_path)
    arena = {**svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
             'map_terrain': [], 'terrain_regions': [], 'width_squares': 30}
    mid = svc._finish_factory_match(bundles, ids,
        {ME: 'team:a', BARE: 'team:a', PROF: 'team:a', THEM: 'team:b'},
        {ME: {'x': 3, 'y': 6}, BARE: {'x': 5, 'y': 6}, PROF: {'x': 7, 'y': 6}, THEM: {'x': 8, 'y': 6}},
        arena, ['mgr-t14-shield-training'], [THEM],
        control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='MGRT14SHIELD', display_name='Shield Training tests', maximum_rounds=10)['match_id']
    advance(table, mid, ME)
    return svc, table, mid


def _ac(engine, actor):
    return engine.state.actors[actor].armor_class + engine._ac_modifier(engine.state.actors[actor])


def _labels(table, mid):
    return {group['label'] for group in table.state(mid)['menu']['actions']}


def test_the_plus_two_is_a_training_grant_and_survives_a_cold_reload(tmp_path):
    svc, table, mid = match(tmp_path)
    engine = svc._load_session(mid).engine
    trained, bare, proficient = _ac(engine, ME), _ac(engine, BARE), _ac(engine, PROF)
    # Byte-identical gear and armour; the only difference is who owns Shield Training.
    assert trained == bare + 2
    # "### Shield Training ... You gain shield proficiency" is Shield training too, with no Shield sphere.
    assert proficient == bare + 2
    svc = reload(svc, mid)
    engine = svc._load_session(mid).engine
    assert (_ac(engine, ME), _ac(engine, BARE), _ac(engine, PROF)) == (trained, bare, proficient)


def test_one_shield_in_hand_keeps_the_don_option_closed_and_the_grant_follows_the_fighter(tmp_path):
    from combat import armour, carry
    from combat.ext.hand_occupancy import free_hands
    from combat.ext.shield_wielding import wielding_a_shield
    svc, table, mid = match(tmp_path)
    engine = svc._load_session(mid).engine
    hands = len(free_hands(engine, engine.state.actors[ME]))
    # "A creature may wield only one Shield at a time": one Shield is already in hand, so there is no Don.
    assert 'Don Shield (Utilize Action)' not in _labels(table, mid)
    assert 'Doff Shield (Utilize Action)' in _labels(table, mid)

    assert table_action(table, mid, 'Doff Shield (Utilize Action)')['status'] == 'COMMITTED'
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    me = engine.state.actors[ME]
    assert not me.action_available, 'Doffing spent the Utilize Action'
    assert _ac(engine, ME) == _ac(engine, BARE)
    assert not wielding_a_shield(engine, me)
    assert len(free_hands(engine, me)) == hands + 1
    assert carry.owned_item_location(me, armour.shield_item_key(engine, me)) == 'carried'

    table_action(table, mid, 'end')
    advance(table, mid, ME)
    assert 'Don Shield (Utilize Action)' in _labels(table, mid)
    assert table_action(table, mid, 'Don Shield (Utilize Action)')['status'] == 'COMMITTED'
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    assert _ac(engine, ME) == _ac(engine, BARE) + 2
    assert wielding_a_shield(engine, engine.state.actors[ME])

    # Wrong owner: the untrained carrier may doff its own Shield, and the grant never follows the item.
    table_action(table, mid, 'end')
    advance(table, mid, BARE)
    assert 'Don Shield (Utilize Action)' not in _labels(table, mid)
    assert 'Doff Shield (Utilize Action)' in _labels(table, mid)
    bare_ac = _ac(svc._load_session(mid).engine, BARE)
    assert table_action(table, mid, 'Doff Shield (Utilize Action)')['status'] == 'COMMITTED'
    svc = reload(svc, mid)
    table.combat = svc
    engine = svc._load_session(mid).engine
    bare = engine.state.actors[BARE]
    assert not bare.action_available
    assert not wielding_a_shield(engine, bare)
    assert _ac(engine, BARE) == bare_ac, 'an untrained wielder never gains the +2, before or after'
    assert _ac(engine, ME) == bare_ac + 2
    assert wielding_a_shield(engine, engine.state.actors[ME])